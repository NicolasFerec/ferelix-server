"""Job management endpoints (admin-only)."""

from datetime import UTC, datetime
from typing import Annotated

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import APIRouter, Depends, HTTPException, WebSocket, status
from fastapi.exceptions import WebSocketException
from fastapi.websockets import WebSocketDisconnect
from pydantic import BaseModel, ConfigDict

from app.database import async_session_maker
from app.dependencies import get_scheduler, require_admin
from app.models import User
from app.services.auth import verify_token
from app.services.jobs import JobState, get_job_state, get_job_states, job_event_stream

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


def _serialize_job_event(event: dict) -> dict:
    """Serialize a job event dict, converting datetime objects to ISO strings."""

    def serialize_datetime(value: datetime | None) -> str | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.isoformat()

    return {
        **event,
        "last_run_time": serialize_datetime(event.get("last_run_time")),
        "next_run_time": serialize_datetime(event.get("next_run_time")),
        "running_since": serialize_datetime(event.get("running_since")),
    }


class JobSchema(BaseModel):
    """Schema for job API responses."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    name_key: str
    last_run_time: datetime | None
    next_run_time: datetime | None
    running_since: datetime | None
    status: str
    error: str | None = None

    @classmethod
    def from_state(cls, state: JobState) -> JobSchema:
        return cls(
            id=state.id,
            name=state.fallback_name,
            name_key=state.name_key,
            last_run_time=state.last_run_time,
            next_run_time=state.next_run_time,
            running_since=state.running_since,
            status=state.status,
            error=state.error,
        )


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
    """List all scheduled jobs (admin only)."""

    return [JobSchema.from_state(state) for state in get_job_states(scheduler)]


@router.post("/{job_id}/trigger", response_model=JobTriggerResponse)
async def trigger_job(
    job_id: str,
    _admin: Annotated[User, Depends(require_admin)],
    scheduler: Annotated[AsyncIOScheduler, Depends(get_scheduler)],
) -> JobTriggerResponse:
    """Manually trigger a scheduled job (admin only)."""

    job = scheduler.get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{job_id}' not found",
        )

    state = get_job_state(job_id)
    if state and state.status == "running":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Job '{job_id}' is already running",
        )

    try:
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


async def _authenticate_admin_websocket(websocket: WebSocket) -> User:
    """Authenticate websocket connections using the same JWT tokens as HTTP."""

    auth_header = websocket.headers.get("authorization")
    token = None
    if auth_header and auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1]
    elif "api_key" in websocket.query_params:
        token = websocket.query_params["api_key"]

    if not token:
        raise WebSocketException(
            code=status.WS_1008_POLICY_VIOLATION, reason="Missing token"
        )

    payload = verify_token(token, token_type="access")
    if payload is None or "sub" not in payload:
        raise WebSocketException(
            code=status.WS_1008_POLICY_VIOLATION, reason="Invalid token"
        )

    user_id = int(payload["sub"])
    async with async_session_maker() as session:
        user = await session.get(User, user_id)
        if user is None or not user.is_admin:
            raise WebSocketException(
                code=status.WS_1008_POLICY_VIOLATION, reason="Admin privileges required"
            )
        return user


@router.websocket("/ws")
async def jobs_websocket(
    websocket: WebSocket,
    scheduler: Annotated[AsyncIOScheduler, Depends(get_scheduler)],
) -> None:
    """Realtime job status stream for admins."""

    try:
        await _authenticate_admin_websocket(websocket)
    except WebSocketException as exc:
        await websocket.close(code=exc.code, reason=exc.reason)
        return

    await websocket.accept()

    # Send initial snapshot
    await websocket.send_json({
        "type": "snapshot",
        "jobs": [
            JobSchema.from_state(state).model_dump(mode="json")
            for state in get_job_states(scheduler)
        ],
    })

    queue = await job_event_stream.subscribe()
    try:
        while True:
            event = await queue.get()
            # Serialize event dict (which comes from JobState.to_dict()) for JSON transmission
            await websocket.send_json({
                "type": "job_update",
                "job": _serialize_job_event(event),
            })
    except WebSocketDisconnect:
        pass
    finally:
        await job_event_stream.unsubscribe(queue)
