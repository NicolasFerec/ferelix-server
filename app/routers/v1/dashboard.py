"""Dashboard API endpoints for admin management (v1 with router-level authentication)."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.dependencies import get_scheduler, require_admin
from app.models import (
    Library,
    LibraryCreate,
    LibrarySchema,
    LibraryUpdate,
    RecommendationRow,
    RecommendationRowCreate,
    RecommendationRowSchema,
    RecommendationRowUpdate,
    User,
    UserSchema,
    UserUpdate,
)
from app.services.jobs import (
    JobExecutionRecord,
    JobState,
    get_job_history,
    get_job_state,
    get_job_states,
)
from app.services.recommendation_row import validate_filter_criteria
from app.services.scanner import schedule_library_scan
from app.version import get_version_info

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
    scheduler: Annotated[AsyncIOScheduler, Depends(get_scheduler)],
) -> Library:
    """Add a new library path to scan (admin only).

    Args:
        library_data: Library path creation data
        session: Database session
        scheduler: APScheduler instance

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
        name=library_data.name,
        path=library_data.path,
        library_type=library_data.library_type,
        enabled=library_data.enabled,
    )
    session.add(library_path)
    await session.commit()
    await session.refresh(library_path)

    # Automatically create "Recently Added" recommendation row for the new library
    recently_added_row = RecommendationRow(
        library_id=library_path.id,
        name="Recently Added in %LIBRARY_NAME%",
        filter_criteria={
            "order_by": "scanned_at",
            "order": "DESC",
            "limit": 20,
        },
        visible_on_homepage=True,
        visible_on_recommend=True,
        is_special=True,
    )
    session.add(recently_added_row)
    await session.commit()

    # Trigger scan for the newly created library
    schedule_library_scan(scheduler, library_path.id, library_path.name)

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
    scheduler: Annotated[AsyncIOScheduler, Depends(get_scheduler)],
) -> Library:
    """Update a library (admin only).

    Args:
        library_id: Library ID
        update_data: Library update data
        session: Database session
        scheduler: APScheduler instance

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

    if update_data.name is not None:
        library_path.name = update_data.name

    # Check if path is being updated and if it conflicts with existing paths
    path_changed = False
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
        path_changed = True

    if update_data.library_type is not None:
        library_path.library_type = update_data.library_type

    if update_data.enabled is not None:
        library_path.enabled = update_data.enabled

    session.add(library_path)
    await session.commit()
    await session.refresh(library_path)

    # Trigger scan if path was changed
    if path_changed:
        schedule_library_scan(scheduler, library_path.id, library_path.name)

    return library_path


# ============================================================================
# Directory Browsing Endpoints
# ============================================================================


class DirectoryItem(BaseModel):
    """Schema for directory browser items."""

    name: str
    path: str
    is_directory: bool
    is_symlink: bool = False
    symlink_target: str | None = None


@router.get("/browse", response_model=list[DirectoryItem])
async def browse_directory(
    path: str = Query(..., description="Directory path to browse"),
) -> list[DirectoryItem]:
    """Browse directories and files at a given path (admin only).

    Args:
        path: Directory path to browse

    Returns:
        List of directory items (directories first, then files)

    Raises:
        HTTPException: If path doesn't exist or is not accessible
    """
    try:
        dir_path = Path(path)

        # Validate path exists
        if not dir_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Path does not exist: {path}",
            )

        # Validate it's a directory
        if not dir_path.is_dir():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Path is not a directory: {path}",
            )

        # Get all items in directory
        items = []
        current_real_path = dir_path.resolve()
        current_path_str = str(current_real_path)

        # Track visited resolved paths to detect loops
        # Build up the path hierarchy and resolve each to catch symlink loops
        visited_resolved_paths = set()
        path_parts = current_path_str.split("/")
        for i in range(1, len(path_parts) + 1):
            path_to_check = "/" + "/".join(path_parts[1:i])
            try:
                resolved = Path(path_to_check).resolve()
                visited_resolved_paths.add(str(resolved))
            except OSError, RuntimeError:
                # Path can't be resolved, skip it
                pass

        try:
            for item in dir_path.iterdir():
                # Skip hidden files/directories
                if item.name.startswith("."):
                    continue

                # Check if it's a symlink
                is_symlink = item.is_symlink()
                symlink_target = None
                skip_item = False

                if is_symlink:
                    try:
                        resolved_path = item.resolve()
                        symlink_target_str = str(resolved_path)
                        symlink_target = symlink_target_str

                        # Check if symlink creates a loop
                        # 1. Check if resolved symlink target is already in visited resolved paths
                        if (
                            symlink_target_str in visited_resolved_paths
                            or resolved_path == current_real_path
                            or str(current_real_path).startswith(
                                symlink_target_str + "/"
                            )
                        ):
                            skip_item = True
                    except OSError, RuntimeError:
                        # Symlink is broken or can't be resolved - skip it to be safe
                        skip_item = True
                        symlink_target = None

                if skip_item:
                    continue

                items.append(
                    DirectoryItem(
                        name=item.name,
                        path=str(item.absolute()),
                        is_directory=item.is_dir(),
                        is_symlink=is_symlink,
                        symlink_target=symlink_target,
                    )
                )
        except PermissionError:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: {path}",
            )

        # Sort: directories first, then files, both alphabetically
        items.sort(key=lambda x: (not x.is_directory, x.name.lower()))

        return items

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error browsing directory: {e!s}",
        )


# ============================================================================
# Job Management Endpoints
# ============================================================================


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


@router.post("/libraries/{library_id}/scan", response_model=JobTriggerResponse)
async def scan_library(
    library_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    scheduler: Annotated[AsyncIOScheduler, Depends(get_scheduler)],
) -> JobTriggerResponse:
    """Trigger a scan for a specific library (returns immediately).

    Args:
        library_id: Library ID to scan
        session: Database session
        scheduler: APScheduler instance

    Returns:
        Job trigger response with job_id

    Raises:
        HTTPException: If library not found
    """
    # Verify library exists
    library_path = await session.get(Library, library_id)
    if not library_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Library not found",
        )

    # Create one-off scan job with library name for display
    job_id = schedule_library_scan(scheduler, library_id, library_path.name)

    return JobTriggerResponse(
        success=True,
        message=f"Scan started for library {library_id}. Job ID: {job_id}",
    )


class JobExecutionSchema(BaseModel):
    """Schema for job execution history."""

    model_config = ConfigDict(from_attributes=True)

    job_id: str
    job_name: str
    name_key: str | None = None
    job_type: str
    started_at: datetime
    completed_at: datetime | None = None
    duration_seconds: float | None = None
    status: str
    error: str | None = None
    files_total: int | None = None
    files_processed: int | None = None

    @classmethod
    def from_record(cls, record: JobExecutionRecord) -> JobExecutionSchema:
        return cls(
            job_id=record.job_id,
            job_name=record.job_name,
            name_key=record.name_key,
            job_type=record.job_type,
            started_at=record.started_at,
            completed_at=record.completed_at,
            duration_seconds=record.duration_seconds,
            status=record.status,
            error=record.error,
            files_total=record.files_total,
            files_processed=record.files_processed,
        )


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
        # Set next_run_time to now to trigger the job immediately
        # With event listeners set up, this will properly track job execution
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


@router.post("/jobs/{job_id}/cancel", response_model=JobTriggerResponse)
async def cancel_job(
    job_id: str,
    scheduler: Annotated[AsyncIOScheduler, Depends(get_scheduler)],
) -> JobTriggerResponse:
    """Cancel a running job (admin only).

    Args:
        job_id: Job ID to cancel
        scheduler: APScheduler instance

    Returns:
        Job trigger response

    Raises:
        HTTPException: If job not found or not running
    """
    from app.services.jobs import request_job_cancellation

    # Check if job exists in scheduler or has state
    state = get_job_state(job_id)
    if not state:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{job_id}' not found",
        )

    if state.status != "running":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Job '{job_id}' is not running (status: {state.status})",
        )

    # Request cancellation
    success = request_job_cancellation(job_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to request cancellation for job '{job_id}'",
        )

    return JobTriggerResponse(
        success=True,
        message=f"Cancellation requested for job '{job_id}'",
    )


@router.get("/jobs/history", response_model=list[JobExecutionSchema])
async def get_job_history_endpoint() -> list[JobExecutionSchema]:
    """Get recent job execution history (admin only).

    Returns:
        List of job execution records (most recent first)
    """
    history = get_job_history()
    return [JobExecutionSchema.from_record(record) for record in history]


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


# ============================================================================
# Recommendation Row Management Endpoints (Admin Only)
# ============================================================================


@router.get("/recommendation-rows", response_model=list[RecommendationRowSchema])
async def get_recommendation_rows(
    session: Annotated[AsyncSession, Depends(get_session)],
    skip: int = 0,
    limit: int = 100,
) -> list[RecommendationRow]:
    """List all recommendation rows (admin only).

    Args:
        session: Database session
        skip: Number of records to skip
        limit: Maximum number of records to return

    Returns:
        List of recommendation rows
    """
    result = await session.execute(select(RecommendationRow).offset(skip).limit(limit))
    return list(result.scalars().all())


@router.post(
    "/recommendation-rows",
    response_model=RecommendationRowSchema,
    status_code=status.HTTP_201_CREATED,
)
async def create_recommendation_row(
    row_data: RecommendationRowCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RecommendationRow:
    """Create a new recommendation row (admin only).

    Args:
        row_data: Recommendation row creation data
        session: Database session

    Returns:
        Created recommendation row

    Raises:
        HTTPException: If library not found or filter criteria is invalid
    """
    # Validate library exists
    library = await session.get(Library, row_data.library_id)
    if not library:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Library not found",
        )

    # Validate filter criteria
    try:
        validate_filter_criteria(row_data.filter_criteria)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid filter criteria: {e}",
        )

    recommendation_row = RecommendationRow(
        library_id=row_data.library_id,
        name=row_data.name,
        filter_criteria=row_data.filter_criteria,
        visible_on_homepage=row_data.visible_on_homepage,
        visible_on_recommend=row_data.visible_on_recommend,
        is_special=False,
    )
    session.add(recommendation_row)
    await session.commit()
    await session.refresh(recommendation_row)

    return recommendation_row


@router.get("/recommendation-rows/{row_id}", response_model=RecommendationRowSchema)
async def get_recommendation_row(
    row_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RecommendationRow:
    """Get recommendation row by ID (admin only).

    Args:
        row_id: Recommendation row ID
        session: Database session

    Returns:
        Recommendation row details

    Raises:
        HTTPException: If recommendation row not found
    """
    recommendation_row = await session.get(RecommendationRow, row_id)
    if not recommendation_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recommendation row not found",
        )
    return recommendation_row


@router.patch("/recommendation-rows/{row_id}", response_model=RecommendationRowSchema)
async def update_recommendation_row(
    row_id: int,
    update_data: RecommendationRowUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RecommendationRow:
    """Update a recommendation row (admin only).

    Args:
        row_id: Recommendation row ID
        update_data: Recommendation row update data
        session: Database session

    Returns:
        Updated recommendation row

    Raises:
        HTTPException: If recommendation row not found or filter criteria is invalid
    """
    recommendation_row = await session.get(RecommendationRow, row_id)
    if not recommendation_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recommendation row not found",
        )

    # Update fields if provided
    if update_data.name is not None:
        recommendation_row.name = update_data.name

    if update_data.filter_criteria is not None:
        # Validate filter criteria
        try:
            validate_filter_criteria(update_data.filter_criteria)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid filter criteria: {e}",
            )
        recommendation_row.filter_criteria = update_data.filter_criteria

    if update_data.visible_on_homepage is not None:
        recommendation_row.visible_on_homepage = update_data.visible_on_homepage

    if update_data.visible_on_recommend is not None:
        recommendation_row.visible_on_recommend = update_data.visible_on_recommend

    session.add(recommendation_row)
    await session.commit()
    await session.refresh(recommendation_row)

    return recommendation_row


@router.delete("/recommendation-rows/{row_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_recommendation_row(
    row_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    """Delete a recommendation row (admin only).

    Args:
        row_id: Recommendation row ID
        session: Database session

    Raises:
        HTTPException: If recommendation row not found or is special (cannot be deleted)
    """
    recommendation_row = await session.get(RecommendationRow, row_id)
    if not recommendation_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recommendation row not found",
        )

    if recommendation_row.is_special:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete special recommendation rows",
        )

    await session.delete(recommendation_row)
    await session.commit()


# ============================================================================
# Library-specific Recommendation Row Management Endpoints
# ============================================================================


@router.get(
    "/libraries/{library_id}/recommendation-rows",
    response_model=list[RecommendationRowSchema],
)
async def get_library_recommendation_rows(
    library_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[RecommendationRow]:
    """Get recommendation rows for a specific library (admin only).

    Args:
        library_id: Library ID
        session: Database session

    Returns:
        List of recommendation rows for the library

    Raises:
        HTTPException: If library not found
    """
    # Validate library exists
    library = await session.get(Library, library_id)
    if not library:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Library not found",
        )

    result = await session.execute(
        select(RecommendationRow)
        .where(RecommendationRow.library_id == library_id)
        .order_by(RecommendationRow.name)
    )
    return list(result.scalars().all())


@router.post(
    "/libraries/{library_id}/recommendation-rows",
    response_model=RecommendationRowSchema,
    status_code=status.HTTP_201_CREATED,
)
async def add_library_recommendation_row(
    library_id: int,
    row_data: RecommendationRowCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RecommendationRow:
    """Add a recommendation row to a library (admin only).

    Creates a new recommendation row or associates an existing one.

    Args:
        library_id: Library ID
        row_data: Recommendation row data (library_id in body must match path param)
        session: Database session

    Returns:
        Created or updated recommendation row

    Raises:
        HTTPException: If library not found or library_id mismatch
    """
    # Validate library exists
    library = await session.get(Library, library_id)
    if not library:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Library not found",
        )

    # Ensure library_id matches
    if row_data.library_id != library_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Library ID in body must match path parameter",
        )

    # Validate filter criteria
    try:
        validate_filter_criteria(row_data.filter_criteria)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid filter criteria: {e}",
        )

    recommendation_row = RecommendationRow(
        library_id=row_data.library_id,
        name=row_data.name,
        filter_criteria=row_data.filter_criteria,
        visible_on_homepage=row_data.visible_on_homepage,
        visible_on_recommend=row_data.visible_on_recommend,
        is_special=False,
    )
    session.add(recommendation_row)
    await session.commit()
    await session.refresh(recommendation_row)

    return recommendation_row


@router.patch(
    "/libraries/{library_id}/recommendation-rows/{row_id}",
    response_model=RecommendationRowSchema,
)
async def update_library_recommendation_row(
    library_id: int,
    row_id: int,
    update_data: RecommendationRowUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RecommendationRow:
    """Update a recommendation row's visibility for a library (admin only).

    Args:
        library_id: Library ID
        row_id: Recommendation row ID
        update_data: Update data (typically visibility flags)
        session: Database session

    Returns:
        Updated recommendation row

    Raises:
        HTTPException: If library or row not found, or row doesn't belong to library
    """
    # Validate library exists
    library = await session.get(Library, library_id)
    if not library:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Library not found",
        )

    recommendation_row = await session.get(RecommendationRow, row_id)
    if not recommendation_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recommendation row not found",
        )

    if recommendation_row.library_id != library_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Recommendation row does not belong to this library",
        )

    # Update fields if provided
    if update_data.name is not None:
        recommendation_row.name = update_data.name

    if update_data.filter_criteria is not None:
        if recommendation_row.is_special:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot modify filter criteria for special recommendation rows",
            )
        # Validate filter criteria
        try:
            validate_filter_criteria(update_data.filter_criteria)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid filter criteria: {e}",
            )
        recommendation_row.filter_criteria = update_data.filter_criteria

    if update_data.visible_on_homepage is not None:
        recommendation_row.visible_on_homepage = update_data.visible_on_homepage

    if update_data.visible_on_recommend is not None:
        recommendation_row.visible_on_recommend = update_data.visible_on_recommend

    session.add(recommendation_row)
    await session.commit()
    await session.refresh(recommendation_row)

    return recommendation_row


@router.delete(
    "/libraries/{library_id}/recommendation-rows/{row_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_library_recommendation_row(
    library_id: int,
    row_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    """Remove a recommendation row from a library (admin only).

    Args:
        library_id: Library ID
        row_id: Recommendation row ID
        session: Database session

    Raises:
        HTTPException: If library or row not found, or row is special
    """
    # Validate library exists
    library = await session.get(Library, library_id)
    if not library:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Library not found",
        )

    recommendation_row = await session.get(RecommendationRow, row_id)
    if not recommendation_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recommendation row not found",
        )

    if recommendation_row.library_id != library_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Recommendation row does not belong to this library",
        )

    if recommendation_row.is_special:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete special recommendation rows",
        )

    await session.delete(recommendation_row)
    await session.commit()


# ============================================================================
# Version Information Endpoint
# ============================================================================


@router.get("/version")
async def get_version_info_endpoint() -> dict[str, str]:
    """Get backend version information (git commit and branch).

    Returns:
        Dictionary with 'commit' and 'branch' keys containing version info.
        In local dev, uses git commands. In production, reads from version.json
        generated during Docker build.
    """
    return get_version_info()
