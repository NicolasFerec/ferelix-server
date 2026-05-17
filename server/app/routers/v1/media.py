"""API endpoints for managing media library and files (v1 with authentication)."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_session
from app.dependencies import get_current_active_user
from app.models import (
    Library,
    LibrarySchema,
    MediaFile,
    MediaFileSchema,
    MediaView,
    MediaViewSchema,
    MediaViewUpdate,
    RecommendationRow,
    User,
)
from app.models.playback import (
    PlaybackInfoRequest,
    PlaybackInfoResponse,
)
from app.services.playback_session import ClientContext, PlaybackSessionService
from app.services.recommendation_row import apply_filter_criteria
from app.services.stream_builder import StreamBuilder
from app.services.thumbnails import generate_video_thumbnail

router = APIRouter(prefix="/api/v1", tags=["media"])


@router.post("/playback-info/{media_id}", response_model=PlaybackInfoResponse)
async def get_playback_info(
    media_id: int,
    playback_request: PlaybackInfoRequest,
    _user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PlaybackInfoResponse:
    """Get playback information for a media file.

    Analyzes the media file against the provided device profile to determine
    the optimal playback method (DirectPlay, DirectStream, or Transcode).

    Args:
        media_id: ID of the media file
        playback_request: Device profile and playback preferences
        _user: Authenticated user (dependency)
        session: Database session

    Returns:
        Playback information with recommended streaming method

    Raises:
        404: Media file not found
    """
    # Get media file with all track information
    result = await session.execute(
        select(MediaFile)
        .options(
            selectinload(MediaFile.video_tracks),
            selectinload(MediaFile.audio_tracks),
            selectinload(MediaFile.subtitle_tracks),
        )
        .where(MediaFile.id == media_id)
    )
    media_file = result.scalar_one_or_none()

    if not media_file:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media file not found")

    # Build stream info using device profile
    stream_builder = StreamBuilder(playback_request.DeviceProfile)
    stream_info = stream_builder.build_stream_info(
        media_file,
        enable_direct_play=playback_request.EnableDirectPlay,
        enable_direct_stream=playback_request.EnableDirectStream,
        enable_transcoding=playback_request.EnableTranscoding,
        requested_resolution=playback_request.RequestedResolution,
    )

    return PlaybackInfoResponse(MediaSources=[stream_info])


class HomepageRow(BaseModel):
    """Schema for homepage row response."""

    playlist_id: int
    library_id: int
    library_name: str
    name: str
    display_name: str
    items: list[MediaFileSchema]


# Library endpoints (authenticated users - enabled libraries only)
@router.get("/libraries", response_model=list[LibrarySchema])
async def get_libraries(
    _user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[Library]:
    """Get enabled library paths (authenticated users).

    Returns only enabled libraries. Admin users should use /dashboard/libraries
    to see all libraries including disabled ones.

    Args:
        _user: Authenticated user (dependency)
        session: Database session

    Returns:
        List of enabled library paths
    """
    result = await session.execute(select(Library).where(Library.enabled))
    return list(result.scalars().all())


@router.get("/libraries/{library_id}/items", response_model=list[MediaFileSchema])
async def get_library_items(
    library_id: int,
    user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    skip: int = 0,
    limit: int = 100,
) -> list[MediaFileSchema]:
    """Get items (media files) from a specific library.

    Args:
        library_id: Library path ID
        user: Authenticated user
        session: Database session
        skip: Number of records to skip
        limit: Maximum number of records to return

    Returns:
        List of media files from the library

    Raises:
        HTTPException: If library not found
    """
    # Get the library path
    library_path = await session.get(Library, library_id)
    if not library_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Library not found",
        )

    # Find MediaFiles that belong to this library (file_path starts with library path)
    # Exclude soft-deleted files
    result = await session.execute(
        select(MediaFile)
        .options(
            selectinload(MediaFile.video_tracks),
            selectinload(MediaFile.audio_tracks),
            selectinload(MediaFile.subtitle_tracks),
        )
        .where(
            MediaFile.file_path.startswith(library_path.path),
            MediaFile.deleted_at.is_(None),
        )
        .offset(skip)
        .limit(limit)
    )
    media_files = list(result.scalars().all())
    return await media_files_with_user_views(session, user.id, media_files)


# Media File endpoints (authenticated users)
@router.get("/media-files", response_model=list[MediaFileSchema])
async def get_media_files(
    user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    skip: int = 0,
    limit: int = 100,
) -> list[MediaFileSchema]:
    """Get all discovered media files.

    Args:
        user: Authenticated user
        session: Database session
        skip: Number of records to skip
        limit: Maximum number of records to return

    Returns:
        List of media files
    """
    # Exclude soft-deleted files
    result = await session.execute(
        select(MediaFile)
        .options(
            selectinload(MediaFile.video_tracks),
            selectinload(MediaFile.audio_tracks),
            selectinload(MediaFile.subtitle_tracks),
        )
        .where(MediaFile.deleted_at.is_(None))
        .offset(skip)
        .limit(limit)
    )
    media_files = list(result.scalars().all())
    return await media_files_with_user_views(session, user.id, media_files)


@router.get("/media-files/continue-watching", response_model=list[MediaFileSchema])
async def get_continue_watching_media_files(
    user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: int = 24,
) -> list[MediaFileSchema]:
    """Get media files started by the current user but not completed."""
    normalized_limit = min(max(limit, 1), 100)
    query_limit = normalized_limit * 3
    result = await session.execute(
        select(MediaFile, MediaView)
        .join(MediaView, MediaView.media_file_id == MediaFile.id)
        .options(
            selectinload(MediaFile.video_tracks),
            selectinload(MediaFile.audio_tracks),
            selectinload(MediaFile.subtitle_tracks),
        )
        .where(
            MediaView.user_id == user.id,
            MediaFile.deleted_at.is_(None),
            MediaView.watched.is_(False),
            MediaView.position_seconds > 10,
        )
        .order_by(MediaView.last_viewed_at.desc())
        .limit(query_limit)
    )

    items = [
        media_file_with_user_view(media_file, view)
        for media_file, view in result.all()
        if is_media_in_progress(view, media_file.duration)
    ]
    return items[:normalized_limit]


# Media item endpoints (authenticated users)
@router.get("/media/{media_id}", response_model=MediaFileSchema)
async def get_media_file(
    media_id: int,
    user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MediaFileSchema:
    """Get a specific media file by ID with track information.

    Args:
        media_id: Media file ID
        user: Authenticated user
        session: Database session

    Returns:
        Media file details with tracks

    Raises:
        HTTPException: If media file not found or is deleted
    """
    result = await session.execute(
        select(MediaFile)
        .options(
            selectinload(MediaFile.video_tracks),
            selectinload(MediaFile.audio_tracks),
            selectinload(MediaFile.subtitle_tracks),
        )
        .where(MediaFile.id == media_id)
    )
    media_file = result.scalar_one_or_none()

    if not media_file or media_file.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Media file not found",
        )

    view = await get_user_media_view(session, user.id, media_id)
    return media_file_with_user_view(media_file, view)


@router.get("/media/{media_id}/view", response_model=MediaViewSchema)
async def get_media_view(
    media_id: int,
    user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MediaView:
    """Get the current user's saved watch state for a media file."""
    await require_media_file(session, media_id)
    view = await get_user_media_view(session, user.id, media_id)
    if not view:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media view not found")
    return view


@router.patch("/media/{media_id}/view", response_model=MediaViewSchema)
async def update_media_view(
    media_id: int,
    payload: MediaViewUpdate,
    user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MediaView:
    """Update the current user's saved watch state for a media file."""
    await require_media_file(session, media_id)
    now = datetime.now(UTC).replace(tzinfo=None)
    view = await get_user_media_view(session, user.id, media_id)
    if not view:
        view = MediaView(user_id=user.id, media_file_id=media_id)
        session.add(view)
        await session.flush()

    view.position_seconds = max(payload.position_seconds, 0.0)
    view.duration_seconds = payload.duration_seconds
    view.last_viewed_at = now

    if payload.watched is not None:
        view.watched = payload.watched
    elif is_media_watched(view.position_seconds, payload.duration_seconds):
        view.watched = True

    if view.watched:
        view.completed_at = view.completed_at or now
    else:
        view.completed_at = None

    await session.commit()
    await session.refresh(view)
    return view


@router.get("/media/{media_id}/thumbnail")
async def get_media_thumbnail(
    media_id: int,
    _user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FileResponse:
    """Serve or lazily generate a screenshot thumbnail for a media file."""
    media_file = await session.get(MediaFile, media_id)
    if not media_file or media_file.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media file not found")

    source_path = Path(media_file.file_path)
    if not source_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media file not found on disk")

    thumbnail_path = Path(media_file.thumbnail_path) if media_file.thumbnail_path else None
    if not thumbnail_path or not thumbnail_path.exists():
        generated_path = generate_video_thumbnail(source_path, media_file.duration)
        if not generated_path:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thumbnail not available")

        media_file.thumbnail_path = generated_path
        await session.commit()
        thumbnail_path = Path(generated_path)

    return FileResponse(
        thumbnail_path,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )


# Homepage rows endpoint
@router.get("/homepage/rows", response_model=list[HomepageRow])
async def get_homepage_rows(
    user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[HomepageRow]:
    """Get all visible rows for homepage.

    Returns playlists that are visible on homepage, with their filtered media files.

    Args:
        user: Authenticated user
        session: Database session

    Returns:
        List of homepage rows with media files
    """
    # Get all recommendation rows visible on homepage from enabled libraries
    result = await session.execute(
        select(RecommendationRow, Library)
        .join(Library, RecommendationRow.library_id == Library.id)
        .where(RecommendationRow.visible_on_homepage == True, Library.enabled == True)  # noqa: E712
        .order_by(Library.name, RecommendationRow.name)
    )

    rows = []

    for recommendation_row, library in result.all():
        # Build base query with eager loading of tracks
        query = select(MediaFile).options(
            selectinload(MediaFile.video_tracks),
            selectinload(MediaFile.audio_tracks),
            selectinload(MediaFile.subtitle_tracks),
        )
        query = apply_filter_criteria(query, recommendation_row.filter_criteria, library.path)

        # Execute query
        media_result = await session.execute(query)
        media_files = list(media_result.scalars().all())

        # Determine display name
        # Replace %LIBRARY_NAME% placeholder with actual library name
        # Also support backward compatibility with {library_name}
        display_name = recommendation_row.name
        if "%LIBRARY_NAME%" in display_name:
            display_name = display_name.replace("%LIBRARY_NAME%", library.name)
        elif "{library_name}" in display_name:
            # Backward compatibility with old format
            display_name = display_name.replace("{library_name}", library.name)

        rows.append({
            "playlist_id": recommendation_row.id,
            "library_id": library.id,
            "library_name": library.name,
            "name": recommendation_row.name,
            "display_name": display_name,
            "items": await media_files_with_user_views(session, user.id, media_files),
        })

    # Auto-prefix duplicate names with library name
    # First pass: count occurrences of each display name
    display_name_counts: dict[str, int] = {}
    for row in rows:
        display_name = row["display_name"]
        display_name_counts[display_name] = display_name_counts.get(display_name, 0) + 1

    # Second pass: prefix duplicates
    final_rows = []
    for row in rows:
        display_name = row["display_name"]

        # If this name appears multiple times, prefix with library name
        if display_name_counts[display_name] > 1:
            display_name = f"{row['library_name']} - {display_name}"

        final_rows.append(
            HomepageRow(
                playlist_id=row["playlist_id"],
                library_id=row["library_id"],
                library_name=row["library_name"],
                name=row["name"],
                display_name=display_name,
                items=row["items"],
            )
        )

    return final_rows


# Library rows endpoint
@router.get("/libraries/{library_id}/rows", response_model=list[HomepageRow])
async def get_library_rows(
    library_id: int,
    user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[HomepageRow]:
    """Get rows for a specific library (for Library View "Recommended" tab).

    Args:
        library_id: Library ID
        user: Authenticated user
        session: Database session

    Returns:
        List of rows with media files for the library

    Raises:
        HTTPException: If library not found or is disabled
    """
    # Get the library
    library = await session.get(Library, library_id)
    if not library:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Library not found",
        )

    if not library.enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Library is disabled",
        )

    # Get recommendation rows visible in recommended tab
    result = await session.execute(
        select(RecommendationRow)
        .where(
            RecommendationRow.library_id == library_id,
            RecommendationRow.visible_on_recommend,
        )
        .order_by(RecommendationRow.name)
    )

    rows = []

    for recommendation_row in result.scalars().all():
        # Build base query with eager loading of tracks
        query = select(MediaFile).options(
            selectinload(MediaFile.video_tracks),
            selectinload(MediaFile.audio_tracks),
            selectinload(MediaFile.subtitle_tracks),
        )
        query = apply_filter_criteria(query, recommendation_row.filter_criteria, library.path)

        # Execute query
        media_result = await session.execute(query)
        media_files = list(media_result.scalars().all())

        # Determine display name
        # Replace %LIBRARY_NAME% placeholder with actual library name
        # Also support backward compatibility with {library_name}
        display_name = recommendation_row.name
        if "%LIBRARY_NAME%" in display_name:
            display_name = display_name.replace("%LIBRARY_NAME%", library.name)
        elif "{library_name}" in display_name:
            # Backward compatibility with old format
            display_name = display_name.replace("{library_name}", library.name)

        rows.append(
            HomepageRow(
                playlist_id=recommendation_row.id,
                library_id=library.id,
                library_name=library.name,
                name=recommendation_row.name,
                display_name=display_name,
                items=await media_files_with_user_views(session, user.id, media_files),
            )
        )

    return rows


async def require_media_file(session: AsyncSession, media_id: int) -> MediaFile:
    media_file = await session.get(MediaFile, media_id)
    if not media_file or media_file.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media file not found")
    return media_file


async def get_user_media_view(session: AsyncSession, user_id: int, media_id: int) -> MediaView | None:
    return await session.scalar(
        select(MediaView).where(
            MediaView.user_id == user_id,
            MediaView.media_file_id == media_id,
        )
    )


async def media_files_with_user_views(
    session: AsyncSession,
    user_id: int,
    media_files: list[MediaFile],
) -> list[MediaFileSchema]:
    media_ids = [media_file.id for media_file in media_files if media_file.id is not None]
    if not media_ids:
        return [MediaFileSchema.model_validate(media_file) for media_file in media_files]

    result = await session.execute(
        select(MediaView).where(
            MediaView.user_id == user_id,
            MediaView.media_file_id.in_(media_ids),
        )
    )
    views_by_media_id = {view.media_file_id: view for view in result.scalars().all()}
    return [media_file_with_user_view(media_file, views_by_media_id.get(media_file.id)) for media_file in media_files]


def media_file_with_user_view(media_file: MediaFile, view: MediaView | None) -> MediaFileSchema:
    schema = MediaFileSchema.model_validate(media_file)
    schema.user_view = MediaViewSchema.model_validate(view) if view else None
    return schema


def is_media_watched(position_seconds: float, duration_seconds: float | None) -> bool:
    if not duration_seconds or duration_seconds <= 0:
        return False
    if position_seconds >= duration_seconds * 0.9:
        return True
    return duration_seconds >= 120 and duration_seconds - position_seconds <= 60


def is_media_in_progress(view: MediaView, media_duration: float | None) -> bool:
    duration = view.duration_seconds or media_duration
    if view.watched or view.position_seconds <= 10:
        return False
    if not duration or duration <= 0:
        return True
    return not is_media_watched(view.position_seconds, duration)


@router.post("/start-stream/{media_id}")
async def start_media_stream(
    media_id: int,
    request: Request,
    playback_request: PlaybackInfoRequest,
    _user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, str]:
    """Start streaming for a media file with automatic transcoding decisions.

    Uses StreamBuilder to determine the best streaming method and automatically
    starts HLS transcoding if needed.

    Returns:
        Dictionary with streaming URL or transcoding job ID
    """
    # Get media file
    result = await session.execute(
        select(MediaFile)
        .options(
            selectinload(MediaFile.video_tracks),
            selectinload(MediaFile.audio_tracks),
            selectinload(MediaFile.subtitle_tracks),
        )
        .where(MediaFile.id == media_id)
    )
    media_file = result.scalar_one_or_none()

    if not media_file:
        raise HTTPException(status_code=404, detail="Media file not found")

    # Get stream decision from StreamBuilder
    stream_builder = StreamBuilder(playback_request.DeviceProfile)
    stream_info = stream_builder.build_stream_info(
        media_file,
        enable_direct_play=playback_request.EnableDirectPlay,
        enable_direct_stream=playback_request.EnableDirectStream,
        enable_transcoding=playback_request.EnableTranscoding,
    )

    service = PlaybackSessionService(session)
    client = ClientContext(
        client_ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    try:
        return await service.start_from_stream_info(media_id, stream_info, client)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start streaming: {e}") from e
