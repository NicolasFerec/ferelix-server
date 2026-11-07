"""Scanner isolation checks using a real, independently connected SQLite database."""

import asyncio
import threading
from collections.abc import AsyncGenerator
from pathlib import Path
from unittest.mock import patch

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import Base, Library, MediaFile
from app.services import scanner


@pytest.fixture
async def scan_database(tmp_path: Path) -> AsyncGenerator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path}/scan.db",
        connect_args={"timeout": 0.2},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


@pytest.mark.parametrize("existing", [False, True], ids=["new-files", "changed-files"])
@pytest.mark.parametrize("operation", ["probe", "thumbnail"])
async def test_slow_extraction_does_not_block_other_database_writes(
    scan_database: async_sessionmaker[AsyncSession], tmp_path: Path, existing: bool, operation: str
) -> None:
    media_directory = tmp_path / "movies"
    media_directory.mkdir()
    paths = [media_directory / "a.mkv", media_directory / "b.mkv"]
    for path in paths:
        path.write_bytes(b"fake-media")
    async with scan_database() as session:
        library = Library(name="test", path=str(media_directory), enabled=True)
        session.add(library)
        if existing:
            session.add_all([
                MediaFile(file_path=str(path), file_name=path.name, file_extension=".mkv", file_size=1)
                for path in paths
            ])
        await session.commit()

    entered = threading.Event()
    release = threading.Event()
    calls = 0
    metadata = {"duration": 60, "codec": "h264"}

    def slow_operation(*_args: object, **_kwargs: object) -> dict | None:
        nonlocal calls
        calls += 1
        if calls == 2:
            entered.set()
            if not release.wait(timeout=5):
                raise TimeoutError("Test failed to release extraction")
        return metadata if operation == "probe" else None

    async def scan() -> dict[str, int | bool]:
        async with scan_database() as session:
            return await scanner.scan_library_path(session, library)

    with (
        patch(
            "app.services.scanner.extract_video_metadata",
            side_effect=slow_operation if operation == "probe" else None,
            return_value=metadata,
        ),
        patch(
            "app.services.scanner.generate_video_thumbnail",
            side_effect=slow_operation if operation == "thumbnail" else None,
            return_value=None,
        ),
    ):
        task = asyncio.create_task(scan())
        try:
            assert await asyncio.to_thread(entered.wait, 5), "The second extraction never started"
            # Progress reports/heartbeats require this same SQLite writer lock.
            # The write must complete before the blocked extraction is released.
            async with scan_database() as session:
                session.add(Library(name="parallel-write", path="/other", enabled=True))
                await session.commit()
        finally:
            release.set()
            result = await asyncio.wait_for(task, timeout=5)
        assert result["updated" if existing else "new"] == 2


async def test_overlapping_scan_jobs_coalesce_and_release_the_slot(
    scan_database: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    async with scan_database() as session:
        library = Library(name="test", path="/movies", enabled=True)
        session.add(library)
        await session.commit()
    monkeypatch.setattr(scanner, "async_session_maker", scan_database)
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def scan(*_args: object) -> dict[str, int | bool]:
        nonlocal calls
        calls += 1
        entered.set()
        await release.wait()
        return {"new": 1}

    monkeypatch.setattr(scanner, "scan_library_path", scan)
    task = asyncio.create_task(scanner.scan_library_job(library.id, job_id="first"))
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        assert scanner.schedule_library_scan(AsyncIOScheduler(), library.id) == "first"
        assert await scanner.scan_library_job(library.id, job_id="second") == {"skipped": True}
        assert calls == 1
    finally:
        release.set()
        await task
    assert await scanner.scan_library_job(library.id, job_id="third") == {"new": 1}
    assert calls == 2


def test_pending_scan_requests_reuse_the_scheduled_job() -> None:
    scheduler = AsyncIOScheduler()
    first = scanner.schedule_library_scan(scheduler, 123, "test")
    assert scanner.schedule_library_scan(scheduler, 123, "test") == first
    assert len(scheduler.get_jobs()) == 1
