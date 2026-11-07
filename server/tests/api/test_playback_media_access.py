"""Native media credentials are scoped to a live, owned playback session."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from app.models import MediaFile, PlaybackSession, TranscodingJob
from app.models.transcoding import TranscodingJobStatus, TranscodingJobType


@pytest.fixture
async def media_access(client, db_session, auth_headers, tmp_path, monkeypatch):
    source = tmp_path / "movie.mp4"
    source.write_bytes(b"0123456789")
    media = MediaFile(file_path=str(source), file_name=source.name, file_size=10, file_extension=".mp4")
    db_session.add(media)
    await db_session.commit()
    monkeypatch.setattr("app.routers.v1.streaming.get_transcoder", MagicMock())
    response = await client.post("/api/v1/playback-sessions", headers=auth_headers, json={"media_file_id": media.id})
    assert response.status_code == 200
    data = response.json()
    assert data["media_access_token"]
    return media, data, {"session_id": data["id"], "media_token": data["media_access_token"]}


async def test_native_range_token_is_not_a_general_api_credential(client, media_access):
    media, _session, query = media_access
    response = await client.get(f"/api/v1/stream/{media.id}", params=query, headers={"Range": "bytes=2-5"})
    assert response.status_code == 206
    assert response.content == b"2345"
    assert (await client.get("/api/v1/users/me", params={"api_key": query["media_token"]})).status_code == 401


async def test_token_hash_only_is_stored(client, db_session, media_access):
    _media, payload, query = media_access
    playback = await db_session.get(PlaybackSession, payload["id"])
    assert playback.media_token_hash != query["media_token"]
    assert len(playback.media_token_hash) == 64


async def test_native_token_cannot_read_another_media(client, db_session, media_access):
    _media, _payload, query = media_access
    other = MediaFile(file_path="/other.mp4", file_name="other.mp4", file_size=1, file_extension=".mp4")
    db_session.add(other)
    await db_session.commit()
    response = await client.get(f"/api/v1/stream/{other.id}", params=query)
    assert response.status_code == 404


async def test_heartbeat_renews_native_url_without_rotating_it(client, db_session, auth_headers, media_access):
    media, payload, query = media_access
    playback = await db_session.get(PlaybackSession, payload["id"])
    playback.last_heartbeat_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=11)
    await db_session.commit()
    assert (await client.get(f"/api/v1/stream/{media.id}", params=query)).status_code == 410
    response = await client.post(f"/api/v1/playback-sessions/{playback.id}/heartbeat", headers=auth_headers, json={})
    assert response.status_code == 200
    assert (await client.get(f"/api/v1/stream/{media.id}", params=query)).status_code == 200
    await client.delete(f"/api/v1/playback-sessions/{playback.id}", headers=auth_headers)
    assert (await client.get(f"/api/v1/stream/{media.id}", params=query)).status_code == 410


async def test_password_reset_revokes_native_token(client, db_session, test_user, media_access):
    media, _payload, query = media_access
    test_user.credentials_version += 1
    await db_session.commit()
    assert (await client.get(f"/api/v1/stream/{media.id}", params=query)).status_code == 401


async def test_hls_manifest_propagates_only_session_scope(client, db_session, media_access, tmp_path):
    media, payload, query = media_access
    playlist = tmp_path / "playlist.m3u8"
    playlist.write_text('#EXTM3U\n#EXT-X-MAP:URI="init.mp4"\n#EXTINF:6.0,\nsegment_000.m4s\n')
    (tmp_path / "init.mp4").write_bytes(b"init")
    (tmp_path / "segment_000.m4s").write_bytes(b"fragment")
    db_session.add(
        TranscodingJob(
            id="job",
            media_file_id=media.id,
            session_id=payload["id"],
            type=TranscodingJobType.REMUX,
            status=TranscodingJobStatus.COMPLETED,
            output_path=str(tmp_path),
            playlist_path=str(playlist),
        )
    )
    await db_session.commit()
    response = await client.get("/api/v1/hls/job/playlist.m3u8", params=query)
    assert response.status_code == 200
    assert f"media_token={query['media_token']}" in response.text
    assert f"session_id={query['session_id']}" in response.text
    assert "api_key" not in response.text
    assert (await client.get("/api/v1/hls/job/segment_000.m4s", params=query)).content == b"fragment"


async def test_old_unowned_hls_job_is_not_accessible(client, db_session, auth_headers, media_access):
    media, _payload, _query = media_access
    db_session.add(
        TranscodingJob(
            id="legacy",
            media_file_id=media.id,
            session_id="old-random-uuid",
            type=TranscodingJobType.REMUX,
            status=TranscodingJobStatus.RUNNING,
        )
    )
    await db_session.commit()
    assert (await client.get("/api/v1/hls/legacy/status", headers=auth_headers)).status_code == 404
    assert (await client.delete("/api/v1/hls/legacy/stop", headers=auth_headers)).status_code == 404


async def test_native_media_token_outlives_an_expired_general_jwt(client, media_access):
    from app.services.auth import create_access_token

    media, _payload, query = media_access
    expired = create_access_token({"sub": "1"}, expires_delta=timedelta(seconds=-1))
    response = await client.get(
        f"/api/v1/stream/{media.id}", params=query, headers={"Authorization": f"Bearer {expired}"}
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
