"""Job registry and runtime tracking helpers."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
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
JobType = Literal["scheduled", "one-off"]


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


@dataclass
class JobExecutionRecord:
    """Historical record of a job execution."""

    job_id: str
    job_name: str
    job_type: JobType
    started_at: datetime
    completed_at: datetime | None = None
    duration_seconds: float | None = None
    status: str = "running"  # "running", "completed", "failed"
    error: str | None = None
    name_key: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "job_name": self.job_name,
            "name_key": self.name_key,
            "job_type": self.job_type,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": self.duration_seconds,
            "status": self.status,
            "error": self.error,
        }


# Registry of known jobs. Add more entries as new background jobs are introduced.
JOB_REGISTRY: dict[str, JobMeta] = {
    "library_scanner": JobMeta(
        id="library_scanner",
        name_key="jobs.names.library_scanner",
        fallback_name="Library Scanner",
    ),
    "cleanup_deleted_media": JobMeta(
        id="cleanup_deleted_media",
        name_key="jobs.names.cleanup_deleted_media",
        fallback_name="Cleanup Deleted Media",
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

# In-memory job execution history (last 100 executions)
_JOB_EXECUTION_HISTORY: deque[JobExecutionRecord] = deque(maxlen=100)


def _ensure_state(job_id: str, scheduler: AsyncIOScheduler | None = None) -> JobState:
    """Ensure we have a state entry for a job (even if not pre-registered).

    Args:
        job_id: Job identifier
        scheduler: Optional scheduler instance to look up job metadata
    """
    if job_id not in _JOB_STATES:
        # Handle scan library jobs specially - use generic translation key
        if job_id.startswith("scan_library_"):
            # Extract library ID from job_id format: scan_library_{library_id}_{timestamp}
            parts = job_id.split("_")
            library_id = parts[2] if len(parts) >= 3 else None

            # Try to get library_name from job kwargs if scheduler is available
            library_name = None
            if scheduler:
                job = scheduler.get_job(job_id)
                if job and hasattr(job, "kwargs") and "library_name" in job.kwargs:
                    library_name = job.kwargs.get("library_name")

            # Build fallback name with library name if available
            if library_name:
                fallback_name = f"Library Scanner: {library_name}"
            elif library_id:
                fallback_name = f"Library Scanner: {library_id}"
            else:
                fallback_name = "Library Scanner"

            meta = JobMeta(
                id=job_id,
                name_key="jobs.names.scan_library",
                fallback_name=fallback_name,
            )
        else:
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
    else:
        # Update existing state if library_name becomes available
        state = _JOB_STATES[job_id]
        if job_id.startswith("scan_library_") and scheduler:
            job = scheduler.get_job(job_id)
            if job and hasattr(job, "kwargs") and "library_name" in job.kwargs:
                library_name = job.kwargs.get("library_name")
                if library_name:
                    # Update fallback name if we now have the library name
                    parts = job_id.split("_")
                    library_id = parts[2] if len(parts) >= 3 else None
                    # Only update if current name doesn't already have the library name
                    if not state.fallback_name.startswith(
                        f"Library Scanner: {library_name}"
                    ):
                        state.fallback_name = f"Library Scanner: {library_name}"
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


def _update_execution_record(job_id: str, status: str, error: str | None) -> None:
    """Update the most recent execution record for a job."""
    # Find the most recent record for this job_id
    for record in reversed(_JOB_EXECUTION_HISTORY):
        if record.job_id == job_id and record.status == "running":
            record.status = status
            record.completed_at = datetime.now(UTC)
            record.error = error
            if record.started_at:
                duration = (record.completed_at - record.started_at).total_seconds()
                record.duration_seconds = duration
            break


def init_job_tracking(scheduler: AsyncIOScheduler) -> None:
    """Attach listeners and prime state from existing jobs."""
    # Prime next_run_time for known jobs
    for job in scheduler.get_jobs():
        state = _ensure_state(job.id, scheduler)
        state.next_run_time = _job_next_run(job)

    scheduler.add_listener(
        lambda event: _handle_job_event(event, scheduler),
        EVENT_JOB_SUBMITTED | EVENT_JOB_EXECUTED | EVENT_JOB_ERROR | EVENT_JOB_MISSED,
    )
    logger.info("Job tracking initialized for %d job(s)", len(_JOB_STATES))


def _handle_job_event(event: JobEvent, scheduler: AsyncIOScheduler) -> None:
    """Update in-memory state when APScheduler emits job events."""
    state = _ensure_state(event.job_id, scheduler)
    now = datetime.now(UTC)

    if event.code == EVENT_JOB_SUBMITTED:
        state.status = "running"
        state.running_since = now
        state.error = None

        # For scan_library jobs, ensure we have the library name from job kwargs
        job_name_for_record = state.fallback_name
        if (
            event.job_id.startswith("scan_library_")
            and scheduler
            and (job := scheduler.get_job(event.job_id))
            and hasattr(job, "kwargs")
            and job.kwargs
            and "library_name" in job.kwargs
            and (library_name := job.kwargs.get("library_name"))
        ):
            job_name_for_record = f"Library Scanner: {library_name}"
            # Also update state for consistency
            state.fallback_name = job_name_for_record

        # Determine job type: one-off jobs typically have timestamps or unique suffixes
        job_type: JobType = (
            "one-off"
            if "_" in event.job_id
            and any(event.job_id.startswith(prefix) for prefix in ["scan_library_"])
            else "scheduled"
        )

        # Create execution record
        record = JobExecutionRecord(
            job_id=event.job_id,
            job_name=job_name_for_record,
            name_key=state.name_key,
            job_type=job_type,
            started_at=now,
            status="running",
        )
        _JOB_EXECUTION_HISTORY.append(record)

    elif event.code == EVENT_JOB_EXECUTED:
        state.status = "success"
        state.last_run_time = _as_aware(
            event.scheduled_run_time if isinstance(event, JobExecutionEvent) else now
        )
        state.running_since = None
        state.error = None
        # Remove from tracking
        _RUNNING_JOB_TASKS.pop(event.job_id, None)

        # Update execution history
        _update_execution_record(event.job_id, "completed", None)

    elif event.code in (EVENT_JOB_ERROR, EVENT_JOB_MISSED):
        state.status = "failed"
        state.last_run_time = _as_aware(
            event.scheduled_run_time if isinstance(event, JobExecutionEvent) else now
        )
        state.running_since = None
        error_msg = None
        if isinstance(event, JobExecutionEvent) and event.exception:
            state.error = str(event.exception)
            error_msg = str(event.exception)
        # Remove from tracking
        _RUNNING_JOB_TASKS.pop(event.job_id, None)

        # Update execution history
        _update_execution_record(event.job_id, "failed", error_msg)

    else:  # pragma: no cover - defensive
        logger.debug("Unhandled job event: %s", event)

    state.next_run_time = _next_run_for_job(scheduler, event.job_id)


def track_job_task(job_id: str, task: asyncio.Task[Any]) -> None:
    """Register a job task for cancellation tracking."""
    _RUNNING_JOB_TASKS[job_id] = task


def get_job_states(scheduler: AsyncIOScheduler) -> list[JobState]:
    """Return current job states, refreshing next_run_time from scheduler.

    Filters out one-off jobs (those with 'date' trigger type, which are one-time executions).
    """
    states = []
    for job in scheduler.get_jobs():
        # Filter out one-off jobs - they use 'date' trigger type
        # Scheduled jobs use 'interval' or 'cron' triggers
        # Check trigger type by examining the trigger object
        if hasattr(job, "trigger"):
            trigger_class_name = type(job.trigger).__name__
            # DateTrigger is used for one-off jobs
            if trigger_class_name == "DateTrigger":
                continue

        state = _ensure_state(job.id, scheduler)
        state.next_run_time = _as_aware(job.next_run_time)
        states.append(state)
    return states


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
    return state


def get_job_history() -> list[JobExecutionRecord]:
    """Get recent job execution history (most recent first)."""
    return list(reversed(_JOB_EXECUTION_HISTORY))


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
