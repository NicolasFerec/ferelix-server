"""Compare scanner failure handling and task retention without real media work.

Run from server: uv run python -m scripts.benchmark_background_resilience
Uses temporary files and an in-memory database. No ffprobe or FFmpeg is launched.
"""

import asyncio
import importlib.util
import json
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock, patch

from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_SUBMITTED, JobExecutionEvent, JobSubmissionEvent
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import AudioTrack, Base, Library, MediaFile, VideoTrack
from app.services import jobs, scanner


def load_baseline(name: str, directory: Path) -> ModuleType:
    source = subprocess.run(
        ["git", "show", f"db5fede:server/app/services/{name}.py"], capture_output=True, text=True, check=True
    ).stdout
    path = directory / f"baseline_{name}.py"
    path.write_text(source)
    spec = importlib.util.spec_from_file_location(f"baseline_{name}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


async def measure_scanner(module: ModuleType, directory: Path) -> dict:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    media_path = directory / "movie.mkv"
    media_path.write_bytes(b"fixture")
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            library = Library(name="Fixture", path=str(directory), library_type="movie", enabled=True)
            media = MediaFile(
                file_path=str(media_path),
                file_name=media_path.name,
                file_size=1,
                file_extension=".mkv",
                duration=120,
                codec="h264",
                thumbnail_path="known-good.jpg",
            )
            session.add_all([library, media])
            await session.flush()
            session.add_all([
                VideoTrack(media_file_id=media.id, stream_index=0, codec="h264"),
                AudioTrack(media_file_id=media.id, stream_index=1, codec="aac"),
            ])
            await session.commit()
            with (
                patch.object(module.subprocess, "run", return_value=Mock(returncode=1, stderr="fixture error")),
                patch.object(module, "generate_video_thumbnail", return_value=None),
            ):
                stats = await module.scan_library_path(session, library)
            tracks = sum([
                await session.scalar(select(func.count()).select_from(VideoTrack)) or 0,
                await session.scalar(select(func.count()).select_from(AudioTrack)) or 0,
            ])
            await session.refresh(media)
            return {
                "tracks_before": 2,
                "tracks_after_failed_probe": tracks,
                "duration_after_failed_probe": media.duration,
                "scan_error": media.scan_error,
                "reported_stats": stats,
            }
    finally:
        await engine.dispose()


def measure_jobs(module: ModuleType) -> dict:
    scheduler = Mock()
    scheduler.get_job.return_value = None
    now = datetime.now(UTC)
    job_id = "scan_library_1_cancelled"
    with patch.object(module, "_JOB_STATES", {}):
        module._handle_job_event(JobSubmissionEvent(EVENT_JOB_SUBMITTED, job_id, "default", [now]), scheduler)
        module.mark_job_cancelled(job_id)
        module._handle_job_event(JobExecutionEvent(EVENT_JOB_EXECUTED, job_id, "default", now), scheduler)
        final_status = module._JOB_STATES[job_id].status
        module._JOB_STATES.clear()
        for index in range(1000):
            module.mark_manual_run(f"scan_library_1_{index}", "success")
        retained = len(module._JOB_STATES)
    return {"cancelled_task_final_status": final_status, "completed_tasks": 1000, "retained_states": retained}


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="ferelix-resilience-") as temporary:
        directory = Path(temporary)
        baseline_scanner = load_baseline("scanner", directory)
        baseline_jobs = load_baseline("jobs", directory)
        result = {
            "scenario": "Injected ffprobe exit 1; cooperative cancellation; 1000 completed one-off tasks",
            "baseline_revision": "db5fede",
            "before": {
                "scanner": await measure_scanner(baseline_scanner, directory),
                "jobs": measure_jobs(baseline_jobs),
            },
            "after": {"scanner": await measure_scanner(scanner, directory), "jobs": measure_jobs(jobs)},
        }
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
