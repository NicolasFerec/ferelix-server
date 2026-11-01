"""Application shutdown must run even when serving or cleanup fails."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI

from app import main


@pytest.mark.parametrize("body_fails", [False, True])
@pytest.mark.parametrize("cleanup_fails", [False, True])
async def test_lifespan_always_stops_scheduler(monkeypatch, body_fails: bool, cleanup_fails: bool) -> None:
    scheduler = MagicMock()
    monkeypatch.setattr(main, "scheduler", scheduler)
    monkeypatch.setattr(main, "set_scheduler", MagicMock())
    monkeypatch.setattr(main, "init_job_tracking", MagicMock())
    monkeypatch.setattr(main, "initialize_scheduler_jobs", MagicMock())
    monkeypatch.setattr(main, "async_session_maker", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(main, "get_or_create_settings", AsyncMock())
    cleanup = AsyncMock(side_effect=[0, RuntimeError("cleanup failed") if cleanup_fails else 0])
    monkeypatch.setattr(main, "cleanup_stalled_jobs_job", cleanup)

    async def serve() -> None:
        async with main.lifespan(FastAPI()):
            if body_fails:
                raise RuntimeError("serving failed")

    if body_fails:
        with pytest.raises(RuntimeError, match="serving failed"):
            await serve()
    else:
        await serve()

    assert cleanup.await_count == 2
    scheduler.shutdown.assert_called_once_with()


async def test_lifespan_stops_scheduler_when_startup_fails(monkeypatch) -> None:
    scheduler = MagicMock()
    monkeypatch.setattr(main, "scheduler", scheduler)
    monkeypatch.setattr(main, "set_scheduler", MagicMock())
    monkeypatch.setattr(main, "init_job_tracking", MagicMock())
    monkeypatch.setattr(main, "async_session_maker", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(main, "get_or_create_settings", AsyncMock(side_effect=RuntimeError("settings failed")))
    monkeypatch.setattr(main, "cleanup_stalled_jobs_job", AsyncMock(return_value=0))
    with pytest.raises(RuntimeError, match="settings failed"):
        async with main.lifespan(FastAPI()):
            pytest.fail("Application should not start")
    scheduler.shutdown.assert_called_once_with()
