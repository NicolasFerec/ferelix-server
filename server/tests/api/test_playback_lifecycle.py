"""Playback session boundaries own the lifetime of their generated HLS jobs."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.models import MediaFile, PlaybackSession, PlaybackSessionStatus, TranscodingJob
from app.models.transcoding import TranscodingJobStatus, TranscodingJobType


@pytest.fixture
async def playback(db_session, test_user):
    media = MediaFile(file_path="/movie.mp4", file_name="movie", file_size=1, file_extension=".mp4")
    db_session.add(media)
    await db_session.flush()
    playback = PlaybackSession(user_id=test_user.id, media_file_id=media.id)
    db_session.add(playback)
    await db_session.commit()
    return playback


async def test_session_end_stops_all_its_jobs_only(client, db_session, auth_headers, playback, monkeypatch):
    for job_id, session_id in [("old", playback.id), ("current", playback.id), ("other-viewer", "other")]:
        db_session.add(
            TranscodingJob(
                id=job_id,
                media_file_id=playback.media_file_id,
                session_id=session_id,
                type=TranscodingJobType.HLS,
                status=TranscodingJobStatus.RUNNING,
            )
        )
    await db_session.commit()
    transcoder = MagicMock()
    transcoder.stop_job = AsyncMock(return_value=True)
    monkeypatch.setattr("app.routers.v1.streaming.get_transcoder", lambda: transcoder)
    response = await client.delete(f"/api/v1/playback-sessions/{playback.id}", headers=auth_headers)
    assert response.status_code == 204
    assert {call.args[0] for call in transcoder.stop_job.await_args_list} == {"old", "current"}
    await db_session.refresh(playback)
    assert playback.status == PlaybackSessionStatus.ENDED


@pytest.mark.parametrize("status", [PlaybackSessionStatus.ENDED, PlaybackSessionStatus.STOPPED_BY_ADMIN])
async def test_closed_session_cannot_start_encoder(client, db_session, auth_headers, playback, monkeypatch, status):
    playback.status = status
    await db_session.commit()
    start = AsyncMock(side_effect=HTTPException(status_code=418, detail="Unexpected encoder startup"))
    monkeypatch.setattr("app.routers.v1.streaming.start_hls_job_response", start)
    response = await client.post(
        f"/api/v1/hls/{playback.media_file_id}/remux",
        headers=auth_headers,
        params={"session_id": playback.id, "playback_generation": 1},
    )
    assert response.status_code == 410
    start.assert_not_awaited()


async def test_paused_heartbeat_renews_only_its_job(client, db_session, auth_headers, playback):
    old = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=11)
    job = TranscodingJob(
        id="current",
        media_file_id=playback.media_file_id,
        session_id=playback.id,
        type=TranscodingJobType.HLS,
        status=TranscodingJobStatus.COMPLETED,
        last_accessed_at=old,
    )
    db_session.add(job)
    await db_session.commit()
    response = await client.post(
        f"/api/v1/playback-sessions/{playback.id}/heartbeat",
        headers=auth_headers,
        json={"is_paused": True, "transcoding_job_id": job.id},
    )
    assert response.status_code == 200
    await db_session.refresh(job)
    assert job.last_accessed_at > old


async def test_heartbeat_cannot_claim_another_sessions_job(client, db_session, auth_headers, playback):
    old = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=11)
    job = TranscodingJob(
        id="foreign",
        media_file_id=playback.media_file_id,
        session_id="another-session",
        type=TranscodingJobType.HLS,
        status=TranscodingJobStatus.RUNNING,
        last_accessed_at=old,
    )
    db_session.add(job)
    await db_session.commit()
    response = await client.post(
        f"/api/v1/playback-sessions/{playback.id}/heartbeat",
        headers=auth_headers,
        json={"transcoding_job_id": job.id},
    )
    assert response.status_code == 404
    await db_session.refresh(job)
    await db_session.refresh(playback)
    assert job.last_accessed_at == old
    assert playback.transcoding_job_id is None


async def test_session_ending_while_hls_starts_stops_new_job(db_session, playback, tmp_path, monkeypatch):
    from app.services.playback_session import HlsStartOptions, PlaybackSessionService

    media = await db_session.get(MediaFile, playback.media_file_id)
    source = tmp_path / "movie.mp4"
    source.touch()
    media.file_path = str(source)
    await db_session.commit()
    transcoder = MagicMock()
    transcoder.stop_job = AsyncMock(return_value=True)

    async def end_session_during_launch(**kwargs):
        playback.status = PlaybackSessionStatus.ENDED
        await db_session.commit()

    transcoder.start_remux_hls = AsyncMock(side_effect=end_session_during_launch)
    monkeypatch.setattr("app.services.playback_session.get_transcoder", lambda: transcoder)
    with pytest.raises(HTTPException) as error:
        await PlaybackSessionService(db_session).start_hls_job(
            media.id,
            HlsStartOptions(job_type=TranscodingJobType.REMUX, playback_session_id=playback.id, playback_generation=1),
        )
    assert error.value.status_code == 410
    transcoder.stop_job.assert_awaited_once()


@pytest.mark.parametrize(
    "endpoint", ["status", "playlist.m3u8", "segment_000.ts", "init.mp4", "segment_000.m4s", "stop"]
)
async def test_hls_job_is_private_to_its_session_owner(
    client, db_session, auth_headers, admin_user, playback, endpoint, tmp_path, monkeypatch
):
    playback.user_id = admin_user.id
    (tmp_path / "playlist.m3u8").write_text("#EXTM3U\n#EXTINF:6.0,\nsegment_000.ts\n")
    for name in ["segment_000.ts", "init.mp4", "segment_000.m4s"]:
        (tmp_path / name).write_bytes(b"data")
    transcoder = MagicMock()
    transcoder.stop_job = AsyncMock(return_value=True)
    monkeypatch.setattr("app.routers.v1.streaming.get_transcoder", lambda: transcoder)
    db_session.add(
        TranscodingJob(
            id="other-job",
            output_path=str(tmp_path),
            playlist_path=str(tmp_path / "playlist.m3u8"),
            media_file_id=playback.media_file_id,
            session_id=playback.id,
            type=TranscodingJobType.HLS,
            status=TranscodingJobStatus.RUNNING,
        )
    )
    await db_session.commit()
    response = await client.request(
        "DELETE" if endpoint == "stop" else "GET",
        f"/api/v1/hls/other-job/{endpoint}",
        headers=auth_headers,
        params={"session_id": playback.id},
    )
    assert response.status_code == 404


async def test_heartbeat_cannot_renew_a_job_claimed_for_cleanup(client, db_session, auth_headers, playback):
    old = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=11)
    job = TranscodingJob(
        id="stopping",
        media_file_id=playback.media_file_id,
        session_id=playback.id,
        type=TranscodingJobType.HLS,
        status=TranscodingJobStatus.STOPPING,
        last_accessed_at=old,
    )
    db_session.add(job)
    await db_session.commit()
    response = await client.post(
        f"/api/v1/playback-sessions/{playback.id}/heartbeat",
        headers=auth_headers,
        json={"transcoding_job_id": job.id, "is_paused": True},
    )
    assert response.status_code == 410
    await db_session.refresh(job)
    assert job.last_accessed_at == old
    assert job.status == TranscodingJobStatus.STOPPING


async def test_stale_heartbeat_cannot_overwrite_new_timeline(client, db_session, auth_headers, playback, monkeypatch):
    playback.playback_generation = 2
    playback.position_seconds = 25
    playback.transcoding_job_id = "new"
    db_session.add_all([
        TranscodingJob(
            id="old",
            media_file_id=playback.media_file_id,
            session_id=playback.id,
            playback_generation=1,
            type=TranscodingJobType.HLS,
            status=TranscodingJobStatus.CANCELLED,
        ),
        TranscodingJob(
            id="new",
            media_file_id=playback.media_file_id,
            session_id=playback.id,
            playback_generation=2,
            type=TranscodingJobType.HLS,
            status=TranscodingJobStatus.RUNNING,
        ),
    ])
    await db_session.commit()
    transcoder = MagicMock()
    monkeypatch.setattr("app.routers.v1.streaming.get_transcoder", lambda: transcoder)
    response = await client.post(
        f"/api/v1/playback-sessions/{playback.id}/heartbeat",
        headers=auth_headers,
        json={"playback_generation": 1, "transcoding_job_id": "old", "position_seconds": 500},
    )
    assert response.status_code == 409
    await db_session.refresh(playback)
    assert playback.transcoding_job_id == "new"
    assert playback.position_seconds == pytest.approx(25)
    transcoder.update_playback_position.assert_not_called()


async def test_heartbeat_compare_and_set_rechecks_generation_after_loading_session(
    client, db_session, auth_headers, playback, monkeypatch
):
    from sqlalchemy import update
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.routers.v1 import streaming

    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    original = streaming.get_playback_session_or_404

    async def newer_intent_after_read(session, session_id, user):
        snapshot = await original(session, session_id, user)
        async with factory() as concurrent:
            await concurrent.execute(
                update(PlaybackSession).where(PlaybackSession.id == session_id).values(playback_generation=1)
            )
            await concurrent.commit()
        return snapshot

    monkeypatch.setattr(streaming, "get_playback_session_or_404", newer_intent_after_read)
    response = await client.post(
        f"/api/v1/playback-sessions/{playback.id}/heartbeat",
        headers=auth_headers,
        json={"playback_generation": 0, "position_seconds": 500},
    )
    assert response.status_code == 409
    await db_session.refresh(playback)
    assert playback.playback_generation == 1
    assert playback.position_seconds == pytest.approx(0)


@pytest.mark.parametrize("field", ["position_seconds", "duration_seconds"])
async def test_heartbeat_rejects_non_finite_positions(client, auth_headers, playback, field):
    response = await client.post(
        f"/api/v1/playback-sessions/{playback.id}/heartbeat",
        headers={**auth_headers, "Content-Type": "application/json"},
        content='{"' + field + '":1e309}',
    )
    assert response.status_code == 422


@pytest.mark.parametrize("operation", ["stop", "end"])
async def test_failed_encoder_stop_is_not_reported_as_success(
    client, db_session, auth_headers, playback, monkeypatch, operation
):
    db_session.add(
        TranscodingJob(
            id="job",
            media_file_id=playback.media_file_id,
            session_id=playback.id,
            type=TranscodingJobType.HLS,
            status=TranscodingJobStatus.RUNNING,
        )
    )
    await db_session.commit()
    transcoder = MagicMock()
    transcoder.stop_job = AsyncMock(return_value=False)
    monkeypatch.setattr("app.routers.v1.streaming.get_transcoder", lambda: transcoder)
    path = "/api/v1/hls/job/stop" if operation == "stop" else f"/api/v1/playback-sessions/{playback.id}"
    assert (await client.delete(path, headers=auth_headers)).status_code == 503
