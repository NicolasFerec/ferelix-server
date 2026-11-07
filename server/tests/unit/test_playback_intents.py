"""Deterministic interleavings for replacement and session-close races."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Base, MediaFile, PlaybackSession, PlaybackSessionStatus, TranscodingJob, User, VideoTrack
from app.models.playback import PlayMethod, StreamInfo
from app.models.transcoding import TranscodingJobStatus, TranscodingJobType
from app.services.playback_session import HlsStartOptions, PlaybackSessionService


@pytest.fixture
async def intent_database(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'intents.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.mark.parametrize("close_session", [False, True])
async def test_newer_intent_cannot_overlap_or_revive_closed_session(
    intent_database, tmp_path, monkeypatch, close_session
):
    source = tmp_path / "movie.mkv"
    source.touch()
    media = MediaFile(file_path=str(source), file_name=source.name, file_size=0, file_extension=".mkv")
    media.video_tracks = [VideoTrack(stream_index=0, codec="h264")]
    factory = intent_database
    async with factory() as session:
        user = User(username="viewer", password="testpassword123", is_active=True)
        session.add_all([media, user])
        await session.flush()
        playback = PlaybackSession(user_id=user.id, media_file_id=media.id)
        session.add(playback)
        await session.commit()
    started = asyncio.Event()
    release = asyncio.Event()
    active = set()
    launched = []
    max_active = 0

    async def launch(**options):
        nonlocal max_active
        job_id = options["job_id"]
        active.add(job_id)
        launched.append(job_id)
        max_active = max(max_active, len(active))
        async with factory() as session:
            await session.execute(
                update(TranscodingJob).where(TranscodingJob.id == job_id).values(status=TranscodingJobStatus.RUNNING)
            )
            await session.commit()
        if len(launched) == 1:
            started.set()
            await release.wait()

    async def stop(job_id):
        active.discard(job_id)
        async with factory() as session:
            await session.execute(
                update(TranscodingJob).where(TranscodingJob.id == job_id).values(status=TranscodingJobStatus.CANCELLED)
            )
            await session.commit()
        return True

    transcoder = MagicMock()
    transcoder.start_remux_hls = AsyncMock(side_effect=launch)
    transcoder.stop_job = AsyncMock(side_effect=stop)
    monkeypatch.setattr("app.services.playback_session.get_transcoder", lambda: transcoder)

    async def request(generation):
        async with factory() as session:
            return await PlaybackSessionService(session).start_hls_job(
                media.id,
                HlsStartOptions(
                    job_type=TranscodingJobType.REMUX,
                    playback_session_id=playback.id,
                    playback_generation=generation,
                ),
            )

    async with asyncio.timeout(3):
        first = asyncio.create_task(request(1))
        await started.wait()
        second = asyncio.create_task(request(2))
        while True:
            async with factory() as session:
                generation = await session.scalar(
                    select(PlaybackSession.playback_generation).where(PlaybackSession.id == playback.id)
                )
            if generation == 2:
                break
            await asyncio.sleep(0.01)
        if close_session:
            async with factory() as session:
                await session.execute(
                    update(PlaybackSession)
                    .where(PlaybackSession.id == playback.id)
                    .values(status=PlaybackSessionStatus.ENDED)
                )
                await session.commit()
        release.set()
        results = await asyncio.gather(first, second, return_exceptions=True)

    assert isinstance(results[0], HTTPException)
    assert results[0].status_code == 410
    assert max_active == 1
    if close_session:
        assert isinstance(results[1], HTTPException)
        assert results[1].status_code == 410
        assert active == set()
        assert len(launched) == 1
    else:
        assert isinstance(results[1], TranscodingJob)
        assert active == {results[1].id}
        with pytest.raises(HTTPException) as stale:
            await request(1)
        assert stale.value.status_code == 410
        assert active == {results[1].id}


@pytest.mark.parametrize("stop_confirmed", [False, True])
async def test_direct_play_replacement_requires_old_encoder_to_stop(
    intent_database, tmp_path, monkeypatch, stop_confirmed
):
    source = tmp_path / "movie.mp4"
    source.touch()
    media = MediaFile(file_path=str(source), file_name=source.name, file_size=0, file_extension=".mp4")
    media.video_tracks = [VideoTrack(stream_index=0, codec="h264")]
    factory = intent_database
    async with factory() as session:
        user = User(username="viewer", password="testpassword123", is_active=True)
        session.add_all([media, user])
        await session.flush()
        playback = PlaybackSession(user_id=user.id, media_file_id=media.id, playback_generation=1)
        session.add(playback)
        await session.flush()
        job = TranscodingJob(
            media_file_id=media.id,
            session_id=playback.id,
            playback_generation=1,
            status=TranscodingJobStatus.RUNNING,
            type=TranscodingJobType.HLS,
        )
        session.add(job)
        await session.commit()

    transcoder = MagicMock()
    transcoder.stop_job = AsyncMock(return_value=stop_confirmed)
    monkeypatch.setattr("app.services.playback_session.get_transcoder", lambda: transcoder)
    info = StreamInfo(Id=str(media.id), PlayMethod=PlayMethod.DIRECT_PLAY)
    async with factory() as session:
        service = PlaybackSessionService(session)
        if stop_confirmed:
            result = await service.start_from_stream_info(media.id, info, playback.id, 2)
            assert result["method"] == "direct_play"
        else:
            with pytest.raises(HTTPException) as failed:
                await service.start_from_stream_info(media.id, info, playback.id, 2)
            assert failed.value.status_code == 503
        transcoder.stop_job.assert_awaited_once_with(job.id)
        with pytest.raises(HTTPException) as stale:
            await service.start_from_stream_info(media.id, info, playback.id, 1)
        assert stale.value.status_code == 410
        transcoder.stop_job.assert_awaited_once_with(job.id)
