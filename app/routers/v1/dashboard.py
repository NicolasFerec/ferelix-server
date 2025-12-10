"""Dashboard API endpoints for admin management (v1 with router-level authentication)."""

from datetime import UTC, datetime
from typing import Annotated

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import APIRouter, Depends, HTTPException, WebSocket, status
from fastapi.exceptions import WebSocketException
from fastapi.websockets import WebSocketDisconnect
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_maker, get_session
from app.dependencies import get_scheduler, require_admin
from app.models import (
    Library,
    LibraryCreate,
    LibrarySchema,
    LibraryUpdate,
    User,
    UserSchema,
    UserUpdate,
)
from app.services.auth import verify_token
from app.services.jobs import JobState, get_job_state, get_job_states, job_event_stream

# Router with admin-only security at the router level
router = APIRouter(
    prefix="/api/v1/dashboard",
    tags=["dashboard"],
    dependencies=[Depends(require_admin)],
)


# ============================================================================
# Library Management Endpoints
# ============================================================================


@router.get("/libraries", response_model=list[LibrarySchema])
async def get_libraries(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[Library]:
    """Get all libraries (admin only - includes disabled libraries).

    Args:
        session: Database session

    Returns:
        List of all libraries (including disabled)
    """
    result = await session.execute(select(Library))
    return list(result.scalars().all())


@router.post(
    "/libraries",
    response_model=LibrarySchema,
    status_code=status.HTTP_201_CREATED,
)
async def create_library(
    library_data: LibraryCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Library:
    """Add a new library path to scan (admin only).

    Args:
        library_data: Library path creation data
        session: Database session

    Returns:
        Created library path

    Raises:
        HTTPException: If path already exists
    """
    # Check if path already exists
    existing = await session.scalar(
        select(Library).where(Library.path == library_data.path)
    )

    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Library path already exists",
        )

    library_path = Library(
        path=library_data.path,
        library_type=library_data.library_type,
        enabled=library_data.enabled,
    )
    session.add(library_path)
    await session.commit()
    await session.refresh(library_path)
    return library_path


@router.delete("/libraries/{library_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_library(
    library_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    """Remove a library (admin only).

    Args:
        library_id: Library ID
        session: Database session

    Raises:
        HTTPException: If library not found
    """
    library_path = await session.scalar(select(Library).where(Library.id == library_id))
    if not library_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Library not found",
        )

    await session.delete(library_path)
    await session.commit()


@router.patch("/libraries/{library_id}", response_model=LibrarySchema)
async def update_library(
    library_id: int,
    update_data: LibraryUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Library:
    """Update a library (admin only).

    Args:
        library_id: Library ID
        update_data: Library update data
        session: Database session

    Returns:
        Updated library

    Raises:
        HTTPException: If library not found or library already exists
    """
    library_path = await session.scalar(select(Library).where(Library.id == library_id))
    if not library_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Library not found",
        )

    # Check if path is being updated and if it conflicts with existing paths
    if update_data.path is not None and update_data.path != library_path.path:
        existing = await session.scalar(
            select(Library).where(Library.path == update_data.path)
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Library path already exists",
            )
        library_path.path = update_data.path

    if update_data.library_type is not None:
        library_path.library_type = update_data.library_type

    if update_data.enabled is not None:
        library_path.enabled = update_data.enabled

    session.add(library_path)
    await session.commit()
    await session.refresh(library_path)
    return library_path


# ============================================================================
# Job Management Endpoints
# ============================================================================


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


@router.get("/jobs", response_model=list[JobSchema])
async def list_jobs(
    scheduler: Annotated[AsyncIOScheduler, Depends(get_scheduler)],
) -> list[JobSchema]:
    """List all scheduled jobs (admin only)."""

    return [JobSchema.from_state(state) for state in get_job_states(scheduler)]


@router.post("/jobs/{job_id}/trigger", response_model=JobTriggerResponse)
async def trigger_job(
    job_id: str,
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


@router.websocket("/jobs/ws")
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


# ============================================================================
# User Management Endpoints (Admin Only)
# ============================================================================


@router.get("/users", response_model=list[UserSchema])
async def list_users(
    session: Annotated[AsyncSession, Depends(get_session)],
    skip: int = 0,
    limit: int = 100,
) -> list[User]:
    """List all users (admin only).

    Args:
        session: Database session
        skip: Number of records to skip
        limit: Maximum number of records to return

    Returns:
        List of users
    """
    result = await session.execute(select(User).offset(skip).limit(limit))
    users = result.scalars().all()
    return list(users)


@router.get("/users/{user_id}", response_model=UserSchema)
async def get_user(
    user_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    """Get user by ID (admin only).

    Args:
        user_id: User ID
        session: Database session

    Returns:
        User profile

    Raises:
        HTTPException: If user not found
    """
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    return user


@router.patch("/users/{user_id}", response_model=UserSchema)
async def update_user(
    user_id: int,
    user_update: UserUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    """Update user by ID (admin only).

    Args:
        user_id: User ID
        user_update: User update data
        session: Database session

    Returns:
        Updated user profile

    Raises:
        HTTPException: If user not found
    """
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    if user_update.email is not None:
        # Check if email is already taken by another user
        existing = await session.scalar(
            select(User).where(User.email == user_update.email, User.id != user_id)
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already in use",
            )
        user.email = user_update.email

    if user_update.password is not None:
        user.password = user_update.password

    if user_update.is_active is not None:
        user.is_active = user_update.is_active

    await session.commit()
    await session.refresh(user)

    return user


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    """Delete user by ID (admin only).

    Args:
        user_id: User ID
        admin: Admin user (dependency - needed to check if deleting self)
        session: Database session

    Raises:
        HTTPException: If user not found or trying to delete self
    """
    if user_id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account",
        )

    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    await session.delete(user)
    await session.commit()
