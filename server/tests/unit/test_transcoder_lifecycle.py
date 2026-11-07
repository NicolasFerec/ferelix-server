"""Regression coverage for encoder ownership and bounded process cleanup."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models import MediaFile, TranscodingJob
from app.models.transcoding import TranscodingJobStatus, TranscodingJobType
from app.services.transcoder import FFmpegTranscoder


@pytest.fixture
async def job(db_session, monkeypatch):
    media = MediaFile(file_path="/movie.mp4", file_name="movie", file_size=1, file_extension=".mp4")
    db_session.add(media)
    await db_session.flush()
    row = TranscodingJob(
        id="job",
        media_file_id=media.id,
        type=TranscodingJobType.HLS,
        status=TranscodingJobStatus.RUNNING,
        output_path="/job",
        last_accessed_at=datetime.now(UTC) - timedelta(minutes=11),
    )
    db_session.add(row)
    await db_session.commit()

    @asynccontextmanager
    async def session_scope():
        yield db_session

    monkeypatch.setattr("app.services.transcoder.async_session_maker", session_scope)
    return row


async def test_encoder_progress_does_not_renew_viewer_lease(job, db_session):
    transcoder = object.__new__(FFmpegTranscoder)
    before = job.last_accessed_at.replace(tzinfo=None)
    await transcoder._update_job_progress(job.id, {"transcoded_duration": 120.0})
    await db_session.refresh(job)
    assert job.transcoded_duration == pytest.approx(120.0)
    assert job.last_accessed_at == before


@pytest.mark.parametrize("status", [TranscodingJobStatus.CANCELLED, TranscodingJobStatus.FAILED])
async def test_late_encoder_exit_cannot_overwrite_terminal_status(job, db_session, status):
    transcoder = object.__new__(FFmpegTranscoder)
    job.status = status
    job.error_message = "original failure" if status == TranscodingJobStatus.FAILED else None
    await db_session.commit()
    await transcoder._mark_job_completed(job.id)
    await db_session.refresh(job)
    assert job.status == status


async def test_late_monitor_error_cannot_overwrite_cancellation(job, db_session):
    transcoder = object.__new__(FFmpegTranscoder)
    job.status = TranscodingJobStatus.CANCELLED
    await db_session.commit()
    await transcoder._mark_job_failed(job.id, "stderr interrupted during stop")
    await db_session.refresh(job)
    assert job.status == TranscodingJobStatus.CANCELLED


async def test_stop_still_terminates_process_when_stdin_is_broken(job, monkeypatch):
    transcoder = object.__new__(FFmpegTranscoder)
    process = MagicMock()
    process.returncode = None
    process.stdin.is_closing.return_value = False
    process.stdin.write.side_effect = BrokenPipeError
    process.wait = AsyncMock(return_value=0)
    transcoder._active_jobs = {job.id: process}
    remove = MagicMock()
    monkeypatch.setattr("app.services.transcoder.remove_output_path", remove)
    assert await transcoder.stop_job(job.id) is True
    process.terminate.assert_called_once()
    process.wait.assert_awaited()
    remove.assert_called_once_with("/job")
    assert job.id not in transcoder._active_jobs


async def test_cancelled_job_cannot_be_resurrected_during_startup(job, db_session, tmp_path):
    from fastapi import HTTPException

    transcoder = object.__new__(FFmpegTranscoder)
    job.status = TranscodingJobStatus.CANCELLED
    await db_session.commit()
    with pytest.raises(HTTPException) as error:
        await transcoder._mark_job_running(job.id, ["ffmpeg"], tmp_path, tmp_path / "playlist.m3u8", None, None, None)
    assert error.value.status_code == 410
    await db_session.refresh(job)
    assert job.status == TranscodingJobStatus.CANCELLED


async def test_stop_between_spawn_and_pid_registration_reaps_process(job, monkeypatch, tmp_path, db_session):
    from fastapi import HTTPException

    transcoder = object.__new__(FFmpegTranscoder)
    transcoder._active_jobs = {}
    transcoder._background_tasks = set()
    process = MagicMock()
    process.pid = 123
    process.returncode = None
    process.communicate = AsyncMock(return_value=(b"", b""))
    monkeypatch.setattr("app.services.transcoder.asyncio.create_subprocess_exec", AsyncMock(return_value=process))

    async def stop_before_registration(_job_id, _process):
        job.status = TranscodingJobStatus.CANCELLED
        await db_session.commit()

    monkeypatch.setattr(transcoder, "_ensure_process_running", stop_before_registration)
    with pytest.raises(HTTPException) as error:
        await transcoder._launch_ffmpeg(job.id, 100, ["ffmpeg"], tmp_path / "playlist.m3u8", 1, "test")
    assert error.value.status_code == 410
    process.kill.assert_called_once()
    process.communicate.assert_awaited_once()
    assert transcoder._active_jobs == {}
    await db_session.refresh(job)
    assert job.status == TranscodingJobStatus.CANCELLED


async def test_startup_watchdog_does_not_accept_an_empty_playlist(job, tmp_path):
    transcoder = object.__new__(FFmpegTranscoder)
    transcoder._mark_job_failed = AsyncMock()
    process = MagicMock()
    process.returncode = None
    process.wait = AsyncMock()
    playlist = tmp_path / "playlist.m3u8"
    playlist.touch()
    await transcoder._watch_playlist_startup(job.id, process, playlist, 0.001)
    process.kill.assert_called_once()
    process.wait.assert_awaited_once()
    transcoder._mark_job_failed.assert_awaited_once()


async def test_monitor_write_failure_kills_and_reaps_encoder_before_forgetting_it(monkeypatch):
    import asyncio

    transcoder = object.__new__(FFmpegTranscoder)
    process = MagicMock()
    process.returncode = None
    process.stderr = asyncio.StreamReader()
    process.stderr.feed_data(b"frame=1 time=00:00:01.00\n")
    process.stderr.feed_eof()
    process.communicate = AsyncMock(return_value=(b"", b""))
    transcoder._active_jobs = {"job": process}
    transcoder._get_job_start_time = AsyncMock(return_value=0)
    transcoder._parse_ffmpeg_progress = MagicMock(return_value={"transcoded_duration": 1})
    transcoder._update_job_progress = AsyncMock(side_effect=RuntimeError("Database unavailable"))
    transcoder._mark_job_failed = AsyncMock()
    await transcoder._monitor_progress("job", process, 120)
    process.kill.assert_called_once()
    process.communicate.assert_awaited_once()
    transcoder._mark_job_failed.assert_awaited_once_with("job", "Progress monitoring failed: Database unavailable")
    assert transcoder._active_jobs == {}


async def test_stale_viewer_cleanup_still_runs_while_encoder_makes_progress(job, monkeypatch):
    transcoder = object.__new__(FFmpegTranscoder)
    transcoder._active_jobs = {job.id: MagicMock()}
    transcoder._stop_process = AsyncMock()
    monkeypatch.setattr("app.services.transcoder.remove_output_path", MagicMock())
    await transcoder._update_job_progress(job.id, {"transcoded_duration": 120.0})
    assert await transcoder.cleanup_transcode_files() == 1
    transcoder._stop_process.assert_awaited_once()


@pytest.mark.parametrize("next_status", [TranscodingJobStatus.RUNNING, TranscodingJobStatus.COMPLETED])
async def test_cleanup_preserves_lease_renewed_while_previous_job_stops(job, db_session, monkeypatch, next_status):
    from sqlalchemy import update
    from sqlalchemy.ext.asyncio import async_sessionmaker

    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    next_job = TranscodingJob(
        id="next-job",
        media_file_id=job.media_file_id,
        type=TranscodingJobType.HLS,
        status=next_status,
        output_path="/next-job",
        last_accessed_at=job.last_accessed_at,
    )
    db_session.add(next_job)
    await db_session.commit()
    monkeypatch.setattr("app.services.transcoder.async_session_maker", factory)
    transcoder = object.__new__(FFmpegTranscoder)
    process = MagicMock()
    transcoder._active_jobs = {job.id: process, next_job.id: MagicMock()}

    async def stop_and_receive_heartbeat(_process):
        assert _process is process
        async with factory() as session:
            await session.execute(
                update(TranscodingJob)
                .where(TranscodingJob.id == next_job.id)
                .values(last_accessed_at=datetime.now(UTC))
            )
            await session.commit()

    transcoder._stop_process = AsyncMock(side_effect=stop_and_receive_heartbeat)
    remove = MagicMock()
    monkeypatch.setattr("app.services.transcoder.remove_output_path", remove)
    assert await transcoder.cleanup_transcode_files() == 1
    remove.assert_called_once_with("/job")
    transcoder._stop_process.assert_awaited_once_with(process)
    await db_session.refresh(next_job)
    assert next_job.status == next_status


async def test_failed_cleanup_keeps_claim_for_retry_without_removing_assets(job, db_session, monkeypatch):
    transcoder = object.__new__(FFmpegTranscoder)
    process = MagicMock()
    transcoder._active_jobs = {job.id: process}
    transcoder._stop_process = AsyncMock(side_effect=[RuntimeError("Process still alive"), None])
    remove = MagicMock()
    monkeypatch.setattr("app.services.transcoder.remove_output_path", remove)

    assert await transcoder.cleanup_transcode_files() == 0
    await db_session.refresh(job)
    assert job.status == TranscodingJobStatus.STOPPING
    remove.assert_not_called()

    assert await transcoder.cleanup_transcode_files() == 1
    assert await db_session.get(TranscodingJob, job.id) is None
    remove.assert_called_once_with("/job")
    assert transcoder._stop_process.await_count == 2


async def test_cleanup_claim_blocks_late_reader_lease_renewal(job, db_session, monkeypatch):
    from fastapi import HTTPException
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.services.streaming_io import touch_job

    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    monkeypatch.setattr("app.services.transcoder.async_session_maker", factory)
    transcoder = object.__new__(FFmpegTranscoder)
    transcoder._active_jobs = {job.id: MagicMock()}

    async def late_reader(_process):
        # Its original ORM snapshot still says RUNNING, but the DB claim won.
        assert job.status == TranscodingJobStatus.RUNNING
        with pytest.raises(HTTPException) as error:
            await touch_job(db_session, job)
        assert error.value.status_code == 410

    transcoder._stop_process = AsyncMock(side_effect=late_reader)
    monkeypatch.setattr("app.services.transcoder.remove_output_path", MagicMock())
    assert await transcoder.cleanup_transcode_files() == 1
    transcoder._stop_process.assert_awaited_once()


async def test_failed_persisted_stop_keeps_job_and_files_for_retry(job, monkeypatch):
    job.process_id = 123
    transcoder = object.__new__(FFmpegTranscoder)
    transcoder._active_jobs = {}
    monkeypatch.setattr("app.services.transcoder.terminate_process", lambda *_args: False)
    remove = MagicMock()
    monkeypatch.setattr("app.services.transcoder.remove_output_path", remove)
    assert await transcoder.stop_job(job.id) is False
    assert job.status == TranscodingJobStatus.RUNNING
    remove.assert_not_called()


async def test_failed_active_stop_retains_the_process_handle(job, monkeypatch):
    transcoder = object.__new__(FFmpegTranscoder)
    process = MagicMock(returncode=None)
    transcoder._active_jobs = {job.id: process}
    transcoder._stop_process = AsyncMock(side_effect=RuntimeError("stop failed"))
    remove = MagicMock()
    monkeypatch.setattr("app.services.transcoder.remove_output_path", remove)
    assert await transcoder.stop_job(job.id) is False
    assert transcoder._active_jobs[job.id] is process
    remove.assert_not_called()


async def test_progress_bursts_are_coalesced_without_losing_the_last_value():
    import asyncio

    transcoder = object.__new__(FFmpegTranscoder)
    process = MagicMock(returncode=0)
    process.stderr = asyncio.StreamReader()
    process.stderr.feed_data("\n".join(str(index) for index in range(100)).encode())
    process.stderr.feed_eof()
    process.wait = AsyncMock(return_value=0)
    transcoder._active_jobs = {"job": process}
    transcoder._get_job_start_time = AsyncMock(return_value=0)
    transcoder._parse_ffmpeg_progress = MagicMock(side_effect=lambda line, *_args: {"transcoded_duration": int(line)})
    transcoder._update_job_progress = AsyncMock()
    transcoder._job_has_status = AsyncMock(return_value=False)
    transcoder._mark_job_completed = AsyncMock()
    await transcoder._monitor_progress("job", process, 100)
    assert transcoder._update_job_progress.await_count == 2
    assert transcoder._update_job_progress.call_args.args == ("job", {"transcoded_duration": 99})
