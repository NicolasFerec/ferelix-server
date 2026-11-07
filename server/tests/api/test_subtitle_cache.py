"""Subtitle responses reuse only complete cache entries for the current source version."""

import asyncio
import os
from pathlib import Path

import pytest

from app.models import MediaFile, PlaybackSession, SubtitleTrack
from app.services.transcoder import FFmpegTranscoder
from app.services.transcoding import subtitles


@pytest.fixture
async def subtitle_source(db_session, test_user, tmp_path, monkeypatch):
    source = tmp_path / "movie.mkv"
    source.write_bytes(b"first")
    media = MediaFile(file_path=str(source), file_name=source.name, file_size=5, file_extension=".mkv")
    media.subtitle_tracks = [SubtitleTrack(stream_index=2, codec="subrip")]
    db_session.add(media)
    await db_session.flush()
    playback = PlaybackSession(user_id=test_user.id, media_file_id=media.id)
    db_session.add(playback)
    await db_session.commit()
    transcoder = object.__new__(FFmpegTranscoder)
    transcoder.ffmpeg_path = "ffmpeg"
    transcoder.temp_dir = tmp_path / "cache"
    monkeypatch.setattr("app.routers.v1.streaming.get_transcoder", lambda: transcoder)
    return media, playback, source, transcoder.temp_dir / "subtitles"


async def test_cache_reuse_and_invalidation_by_actual_size_or_mtime(client, auth_headers, subtitle_source, monkeypatch):
    media, playback, source, cache = subtitle_source
    cache.mkdir(parents=True)
    (cache / f"{media.id}_2.vtt").write_text("WEBVTT\nlegacy partial")
    extractions = []

    class Process:
        returncode = 0

        async def communicate(self):
            return b"", b""

    async def spawn(*command, **_kwargs):
        extractions.append(command)
        content = await asyncio.to_thread(source.read_text)
        await asyncio.to_thread(Path(command[-1]).write_text, f"WEBVTT\n\n{content}\n")
        return Process()

    monkeypatch.setattr(subtitles.asyncio, "create_subprocess_exec", spawn)
    endpoint = f"/api/v1/subtitle/{media.id}/2"
    params = {"session_id": playback.id}
    first = await client.get(endpoint, params=params, headers=auth_headers)
    assert first.status_code == 200
    assert first.text == "WEBVTT\n\nfirst\n"
    assert "no-store" in first.headers["Cache-Control"]
    again = await client.get(endpoint, params=params, headers=auth_headers)
    assert again.text == first.text
    assert len(extractions) == 1

    stat = source.stat()
    source.write_bytes(b"second version")
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))  # Size alone changed.
    second = await client.get(endpoint, params=params, headers=auth_headers)
    assert second.text == "WEBVTT\n\nsecond version\n"
    assert len(extractions) == 2

    source.write_bytes(b"third version!")  # Same size; mtime alone changes the key.
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    third = await client.get(endpoint, params=params, headers=auth_headers)
    assert third.text == "WEBVTT\n\nthird version!\n"
    assert len(extractions) == 3


async def test_failed_extraction_is_not_served_or_reused(client, auth_headers, subtitle_source, monkeypatch):
    media, playback, _source, cache = subtitle_source
    returncode = 1

    class Process:
        def __init__(self):
            self.returncode = returncode

        async def communicate(self):
            return b"", b"failed"

    async def spawn(*command, **_kwargs):
        await asyncio.to_thread(
            Path(command[-1]).write_text, "WEBVTT\n\nComplete\n" if returncode == 0 else "WEBVTT\npartial"
        )
        return Process()

    monkeypatch.setattr(subtitles.asyncio, "create_subprocess_exec", spawn)
    endpoint = f"/api/v1/subtitle/{media.id}/2"
    params = {"session_id": playback.id}
    failed = await client.get(endpoint, params=params, headers=auth_headers)
    assert failed.status_code == 500
    assert list(cache.iterdir()) == []
    returncode = 0
    retried = await client.get(endpoint, params=params, headers=auth_headers)
    assert retried.status_code == 200
    assert retried.text == "WEBVTT\n\nComplete\n"
