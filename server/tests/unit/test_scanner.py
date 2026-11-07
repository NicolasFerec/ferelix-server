"""Unit tests for library scanner change detection."""

import asyncio
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AudioTrack, Library, MediaFile, VideoTrack
from app.services.scanner import MetadataExtractionError, extract_video_metadata, scan_library_path


def test_ffprobe_color_transfer_is_preserved_for_hdr(tmp_path: Path) -> None:
    with patch("app.services.scanner.subprocess.run") as probe:
        probe.return_value.returncode = 0
        probe.return_value.stdout = json.dumps({
            "streams": [
                {
                    "index": 0,
                    "codec_type": "video",
                    "codec_name": "hevc",
                    "pix_fmt": "yuv420p10le",
                    "color_transfer": "smpte2084",
                    "color_primaries": "bt2020",
                    "color_space": "bt2020nc",
                }
            ],
            "format": {},
        })
        metadata = extract_video_metadata(tmp_path / "movie.mkv")
    assert metadata["video_tracks"][0]["color_transfer"] == "smpte2084"


def _write_media_file(path: Path, content: bytes = b"video") -> None:
    path.write_bytes(content)


async def _create_library(db_session: AsyncSession, path: Path) -> Library:
    library = Library(name="Movies", path=str(path), library_type="movie", enabled=True)
    db_session.add(library)
    await db_session.commit()
    await db_session.refresh(library)
    return library


async def _create_media_file(db_session: AsyncSession, file_path: Path, **overrides: object) -> MediaFile:
    file_stat = await asyncio.to_thread(file_path.stat)
    values = {
        "file_path": str(file_path),
        "file_name": file_path.name,
        "file_size": file_stat.st_size,
        "file_extension": file_path.suffix,
        "duration": 120.0,
        "width": 1920,
        "height": 1080,
        "codec": "h264",
        "bitrate": 4_000_000,
        "scanned_at": datetime.now(UTC),
    }
    values.update(overrides)
    media_file = MediaFile(**values)
    db_session.add(media_file)
    await db_session.commit()
    await db_session.refresh(media_file)
    return media_file


@pytest.mark.asyncio
async def test_scan_skips_metadata_and_thumbnail_for_unchanged_existing_file(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    media_path = tmp_path / "movie.mkv"
    _write_media_file(media_path)
    library = await _create_library(db_session, tmp_path)
    media_file = await _create_media_file(db_session, media_path)

    with (
        patch("app.services.scanner.extract_video_metadata") as extract_metadata,
        patch("app.services.scanner.generate_video_thumbnail") as generate_thumbnail,
    ):
        stats = await scan_library_path(db_session, library)

    await db_session.refresh(media_file)

    assert stats == {"new": 0, "updated": 0, "deleted": 0, "restored": 0, "cancelled": False, "failed": 0}
    extract_metadata.assert_not_called()
    generate_thumbnail.assert_not_called()
    assert media_file.file_modified_at is not None


@pytest.mark.asyncio
async def test_scan_reextracts_metadata_and_regenerates_thumbnail_for_changed_file(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    media_path = tmp_path / "movie.mkv"
    _write_media_file(media_path)
    library = await _create_library(db_session, tmp_path)
    media_file = await _create_media_file(
        db_session,
        media_path,
        file_size=1,
        file_modified_at=datetime.fromtimestamp(1, UTC).replace(tzinfo=None),
        thumbnail_path=str(tmp_path / "old.jpg"),
    )
    metadata = {
        "duration": 240.0,
        "width": 3840,
        "height": 2160,
        "codec": "hevc",
        "bitrate": 8_000_000,
        "video_tracks": [],
        "audio_tracks": [],
        "subtitle_tracks": [],
    }

    with (
        patch("app.services.scanner.extract_video_metadata", return_value=metadata) as extract_metadata,
        patch(
            "app.services.scanner.generate_video_thumbnail", return_value=str(tmp_path / "new.jpg")
        ) as generate_thumbnail,
    ):
        stats = await scan_library_path(db_session, library)

    await db_session.refresh(media_file)

    assert stats["updated"] == 1
    extract_metadata.assert_called_once_with(media_path)
    generate_thumbnail.assert_called_once_with(media_path, 240.0, force=True)
    assert media_file.file_size == media_path.stat().st_size
    assert media_file.duration == pytest.approx(240.0)
    assert media_file.width == 3840
    assert media_file.height == 2160
    assert media_file.codec == "hevc"
    assert media_file.bitrate == 8_000_000
    assert media_file.thumbnail_path == str(tmp_path / "new.jpg")


@pytest.mark.asyncio
async def test_scan_processes_existing_file_without_metadata(db_session: AsyncSession, tmp_path: Path) -> None:
    media_path = tmp_path / "movie.mkv"
    _write_media_file(media_path)
    library = await _create_library(db_session, tmp_path)
    media_file = await _create_media_file(
        db_session,
        media_path,
        duration=None,
        width=None,
        height=None,
        codec=None,
        bitrate=None,
    )
    metadata = {
        "duration": 90.0,
        "width": 1280,
        "height": 720,
        "codec": "h264",
        "bitrate": 2_000_000,
        "video_tracks": [],
        "audio_tracks": [],
        "subtitle_tracks": [],
    }

    with (
        patch("app.services.scanner.extract_video_metadata", return_value=metadata) as extract_metadata,
        patch("app.services.scanner.generate_video_thumbnail", return_value=None) as generate_thumbnail,
    ):
        stats = await scan_library_path(db_session, library)

    await db_session.refresh(media_file)

    assert stats["updated"] == 1
    extract_metadata.assert_called_once_with(media_path)
    generate_thumbnail.assert_called_once_with(media_path, 90.0, force=False)
    assert media_file.duration == pytest.approx(90.0)


@pytest.mark.parametrize(
    ("returncode", "stdout", "error"),
    [(1, "", "exited"), (0, "invalid json", "invalid JSON"), (0, '{"streams": []}', "no video")],
)
def test_probe_failure_is_explicit(tmp_path: Path, returncode: int, stdout: str, error: str) -> None:
    with patch("app.services.scanner.subprocess.run") as probe:
        probe.return_value.returncode = returncode
        probe.return_value.stdout = stdout
        with pytest.raises(MetadataExtractionError, match=error):
            extract_video_metadata(tmp_path / "movie.mkv")


def test_probe_timeout_is_explicit(tmp_path: Path) -> None:
    with (
        patch("app.services.scanner.subprocess.run", side_effect=subprocess.TimeoutExpired("ffprobe", 30)),
        pytest.raises(MetadataExtractionError, match="timed out"),
    ):
        extract_video_metadata(tmp_path / "movie.mkv")


@pytest.mark.asyncio
async def test_failed_rescan_keeps_tracks_and_retries(db_session: AsyncSession, tmp_path: Path) -> None:
    media_path = tmp_path / "movie.mkv"
    _write_media_file(media_path)
    library = await _create_library(db_session, tmp_path)
    media_file = await _create_media_file(db_session, media_path, file_size=1, thumbnail_path="known-good.jpg")
    video = VideoTrack(media_file_id=media_file.id, stream_index=0, codec="h264")
    audio = AudioTrack(media_file_id=media_file.id, stream_index=1, codec="aac")
    db_session.add_all([video, audio])
    await db_session.commit()
    await db_session.refresh(media_file)
    scanned_at = media_file.scanned_at
    with (
        patch("app.services.scanner.extract_video_metadata", side_effect=MetadataExtractionError("temporary failure")),
        patch("app.services.scanner.generate_video_thumbnail") as thumbnail,
    ):
        stats = await scan_library_path(db_session, library)
    await db_session.refresh(media_file)
    assert stats["failed"] == 1
    assert stats["updated"] == 0
    assert media_file.duration == pytest.approx(120.0)
    assert media_file.file_size == 1
    assert media_file.thumbnail_path == "known-good.jpg"
    assert media_file.scanned_at == scanned_at
    assert media_file.scan_error == "temporary failure"
    assert media_file.last_scan_attempt_at is not None
    assert await db_session.scalar(select(VideoTrack.id).where(VideoTrack.media_file_id == media_file.id)) == video.id
    assert await db_session.scalar(select(AudioTrack.id).where(AudioTrack.media_file_id == media_file.id)) == audio.id
    thumbnail.assert_not_called()
    metadata = {"duration": 240, "video_tracks": [{"stream_index": 0, "codec": "hevc"}]}
    with (
        patch("app.services.scanner.extract_video_metadata", return_value=metadata),
        patch("app.services.scanner.generate_video_thumbnail", return_value=None),
    ):
        retried = await scan_library_path(db_session, library)
    await db_session.refresh(media_file)
    assert retried["updated"] == 1
    assert retried["failed"] == 0
    assert media_file.duration == 240
    assert media_file.scan_error is None


@pytest.mark.asyncio
async def test_failed_new_file_is_diagnosable_and_other_files_continue(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    _write_media_file(tmp_path / "bad.mkv")
    _write_media_file(tmp_path / "good.mkv")
    library = await _create_library(db_session, tmp_path)

    def probe(path: Path) -> dict:
        if path.name == "bad.mkv":
            raise MetadataExtractionError("unreadable")
        return {"duration": 120, "video_tracks": [{"stream_index": 0, "codec": "h264"}]}

    with (
        patch("app.services.scanner.extract_video_metadata", side_effect=probe),
        patch("app.services.scanner.generate_video_thumbnail", return_value=None),
    ):
        stats = await scan_library_path(db_session, library)
    assert stats["failed"] == 1
    assert stats["new"] == 1
    failed = await db_session.scalar(select(MediaFile).where(MediaFile.file_name == "bad.mkv"))
    assert failed is not None
    assert failed.scan_error == "unreadable"
    assert failed.last_scan_attempt_at is not None
    assert failed.duration is None
