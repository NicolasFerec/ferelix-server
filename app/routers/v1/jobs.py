"""Job management endpoints (admin-only)."""

from datetime import UTC, datetime
from typing import Annotated

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict

from app.dependencies import get_scheduler, require_admin
from app.models import User

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])

# Job display name mapping
JOB_NAMES = {
    "library_scanner": "Library Scanner",
}


class JobSchema(BaseModel):
    """Schema for job API responses."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    last_run_time: datetime | None
    next_run_time: datetime | None
    status: str


class JobTriggerResponse(BaseModel):
    """Response schema for job trigger."""

    success: bool
    message: str


@router.get("", response_model=list[JobSchema])
@router.get("/", response_model=list[JobSchema])
async def list_jobs(
    _admin: Annotated[User, Depends(require_admin)],
    scheduler: Annotated[AsyncIOScheduler, Depends(get_scheduler)],
) -> list[JobSchema]:
    """List all scheduled jobs (admin only).

    Args:
        _admin: Admin user (dependency)
        scheduler: Scheduler instance (dependency)

    Returns:
        List of scheduled jobs with their status and execution times
    """

    jobs = []
    for job in scheduler.get_jobs():
        # Determine job status (simplified - always pending for now)
        job_status = "pending"

        # Get display name (ensure it's always a string)
        job_name: str = JOB_NAMES.get(job.id) or job.id.replace("_", " ").title()

        jobs.append(
            JobSchema(
                id=job.id,
                name=job_name,
                last_run_time=None,  # APScheduler doesn't track last_run_time by default
                next_run_time=job.next_run_time,
                status=job_status,
            )
        )

    return jobs


@router.post("/{job_id}/trigger", response_model=JobTriggerResponse)
async def trigger_job(
    job_id: str,
    _admin: Annotated[User, Depends(require_admin)],
    scheduler: Annotated[AsyncIOScheduler, Depends(get_scheduler)],
) -> JobTriggerResponse:
    """Manually trigger a scheduled job (admin only).

    Args:
        job_id: The ID of the job to trigger
        _admin: Admin user (dependency)
        scheduler: Scheduler instance (dependency)

    Returns:
        Success response

    Raises:
        HTTPException: If job not found or trigger fails
    """

    # Check if job exists
    job = scheduler.get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{job_id}' not found",
        )

    try:
        # Trigger the job immediately by modifying next_run_time to now
        scheduler.modify_job(job_id, next_run_time=datetime.now(UTC))
        return JobTriggerResponse(
            success=True,
            message=f"Job '{job_id}' triggered successfully",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to trigger job: {e!s}",
        )
