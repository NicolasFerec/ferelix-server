"""Job registry and runtime tracking helpers."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from apscheduler.events import (
    EVENT_JOB_ERROR,
    EVENT_JOB_EXECUTED,
    EVENT_JOB_MISSED,
    EVENT_JOB_SUBMITTED,
    JobEvent,
    JobExecutionEvent,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logger = logging.getLogger(__name__)

# Track running job tasks for cancellation during shutdown
_RUNNING_JOB_TASKS: dict[str, asyncio.Task[Any]] = {}

JobStatus = Literal["pending", "running", "success", "failed"]


@dataclass
class JobMeta:
    """Static job metadata used for display and translation."""

    id: str
    name_key: str
    fallback_name: str


@dataclass
class JobState:
    """Mutable job state tracked at runtime."""

    id: str
    name_key: str
    fallback_name: str
    status: JobStatus = "pending"
    last_run_time: datetime | None = None
    next_run_time: datetime | None = None
    running_since: datetime | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.fallback_name,
            "name_key": self.name_key,
            "status": self.status,
            "last_run_time": self.last_run_time,
            "next_run_time": self.next_run_time,
            "running_since": self.running_since,
            "error": self.error,
        }


class JobEventStream:
    """In-process broadcaster for job state changes."""

    def __init__(self) -> None:
        self._queues: set[asyncio.Queue[dict[str, Any]]] = set()
        self._lock = asyncio.Lock()

    async def publish(self, payload: dict[str, Any]) -> None:
        """Fan out payload to all subscribers."""
        async with self._lock:
            queues = list(self._queues)

        for queue in queues:
            try:
                # If queue is full, drop the oldest to make room
                if queue.full():
                    queue.get_nowait()
                queue.put_nowait(payload)
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug("Failed to publish job event: %s", exc)

    async def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        """Register a new subscriber queue."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=20)
        async with self._lock:
            self._queues.add(queue)
        return queue

    async def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        """Remove a subscriber queue."""
        async with self._lock:
            self._queues.discard(queue)


# Registry of known jobs. Add more entries as new background jobs are introduced.
JOB_REGISTRY: dict[str, JobMeta] = {
    "library_scanner": JobMeta(
        id="library_scanner",
        name_key="jobs.names.library_scanner",
        fallback_name="Library Scanner",
    ),
}

# Mutable state cache keyed by job id
_JOB_STATES: dict[str, JobState] = {
    meta.id: JobState(
        id=meta.id,
        name_key=meta.name_key,
        fallback_name=meta.fallback_name,
    )
    for meta in JOB_REGISTRY.values()
}

# Shared broadcaster for WebSocket/long-poll subscribers (wired in later)
job_event_stream = JobEventStream()


def _ensure_state(job_id: str) -> JobState:
    """Ensure we have a state entry for a job (even if not pre-registered)."""
    if job_id not in _JOB_STATES:
        meta = JOB_REGISTRY.get(
            job_id,
            JobMeta(
                id=job_id,
                name_key=f"jobs.names.{job_id}",
                fallback_name=job_id.replace("_", " ").title(),
            ),
        )
        _JOB_STATES[job_id] = JobState(
            id=meta.id,
            name_key=meta.name_key,
            fallback_name=meta.fallback_name,
        )
    return _JOB_STATES[job_id]


def _as_aware(dt: datetime | None) -> datetime | None:
    """Normalize naive datetimes to UTC-aware."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _job_next_run(job: Any) -> datetime | None:
    """Handle APScheduler v3/v4 differences in next run field names."""
    next_run = getattr(job, "next_run_time", None)
    if next_run is None:
        next_run = getattr(job, "next_fire_time", None)
    return _as_aware(next_run)


def _next_run_for_job(scheduler: AsyncIOScheduler, job_id: str) -> datetime | None:
    job = scheduler.get_job(job_id)
    return _job_next_run(job) if job else None


def _schedule_publish(payload: dict[str, Any]) -> None:
    """Publish payload to subscribers without blocking the scheduler thread."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running loop; nothing to publish to
        return
    task = loop.create_task(job_event_stream.publish(payload))
    task.add_done_callback(lambda t: t.exception())


def init_job_tracking(scheduler: AsyncIOScheduler) -> None:
    """Attach listeners and prime state from existing jobs."""
    # Prime next_run_time for known jobs
    for job in scheduler.get_jobs():
        state = _ensure_state(job.id)
        state.next_run_time = _job_next_run(job)

    scheduler.add_listener(
        lambda event: _handle_job_event(event, scheduler),
        EVENT_JOB_SUBMITTED | EVENT_JOB_EXECUTED | EVENT_JOB_ERROR | EVENT_JOB_MISSED,
    )
    logger.info("Job tracking initialized for %d job(s)", len(_JOB_STATES))


def _handle_job_event(event: JobEvent, scheduler: AsyncIOScheduler) -> None:
    """Update in-memory state when APScheduler emits job events."""
    state = _ensure_state(event.job_id)
    now = datetime.now(UTC)

    if event.code == EVENT_JOB_SUBMITTED:
        state.status = "running"
        state.running_since = now
        state.error = None
    elif event.code == EVENT_JOB_EXECUTED:
        state.status = "success"
        state.last_run_time = _as_aware(
            event.scheduled_run_time if isinstance(event, JobExecutionEvent) else now
        )
        state.running_since = None
        state.error = None
        # Remove from tracking
        _RUNNING_JOB_TASKS.pop(event.job_id, None)
    elif event.code in (EVENT_JOB_ERROR, EVENT_JOB_MISSED):
        state.status = "failed"
        state.last_run_time = _as_aware(
            event.scheduled_run_time if isinstance(event, JobExecutionEvent) else now
        )
        state.running_since = None
        if isinstance(event, JobExecutionEvent) and event.exception:
            state.error = str(event.exception)
        # Remove from tracking
        _RUNNING_JOB_TASKS.pop(event.job_id, None)
    else:  # pragma: no cover - defensive
        logger.debug("Unhandled job event: %s", event)

    state.next_run_time = _next_run_for_job(scheduler, event.job_id)
    _schedule_publish(state.to_dict())


def track_job_task(job_id: str, task: asyncio.Task[Any]) -> None:
    """Register a job task for cancellation tracking."""
    _RUNNING_JOB_TASKS[job_id] = task


def get_job_states(scheduler: AsyncIOScheduler) -> list[JobState]:
    """Return current job states, refreshing next_run_time from scheduler."""
    for job in scheduler.get_jobs():
        state = _ensure_state(job.id)
        state.next_run_time = _as_aware(job.next_run_time)
    return list(_JOB_STATES.values())


def get_job_state(job_id: str) -> JobState | None:
    """Lookup a job state."""
    return _JOB_STATES.get(job_id)


def mark_manual_run(job_id: str, status: JobStatus) -> JobState:
    """Record a manual (non-scheduler) run outcome."""
    state = _ensure_state(job_id)
    now = datetime.now(UTC)
    state.status = status
    state.last_run_time = now
    state.running_since = None
    state.next_run_time = state.next_run_time or now
    _schedule_publish(state.to_dict())
    return state


async def cancel_all_running_jobs() -> None:
    """Cancel all currently running job tasks.

    This is called during server shutdown to prevent hanging on background tasks.
    """
    if not _RUNNING_JOB_TASKS:
        return

    logger.info(f"Cancelling {len(_RUNNING_JOB_TASKS)} running job(s)...")
    for job_id, task in list(_RUNNING_JOB_TASKS.items()):
        if not task.done():
            logger.info(f"Cancelling job: {job_id}")
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                logger.info(f"Job {job_id} cancelled successfully")
            except Exception as exc:
                logger.warning(f"Error cancelling job {job_id}: {exc}")

    _RUNNING_JOB_TASKS.clear()
