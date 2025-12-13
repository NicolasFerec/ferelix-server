"""API endpoints for managing media library and files (v1 with authentication)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
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
    RecommendationRow,
    User,
)
from app.services.recommendation_row import apply_filter_criteria

router = APIRouter(prefix="/api/v1", tags=["media"])


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
    _user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    skip: int = 0,
    limit: int = 100,
) -> list[MediaFile]:
    """Get items (media files) from a specific library.

    Args:
        library_id: Library path ID
        _user: Authenticated user (dependency)
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
    return list(result.scalars().all())


# Media File endpoints (authenticated users)
@router.get("/media-files", response_model=list[MediaFileSchema])
async def get_media_files(
    _user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    skip: int = 0,
    limit: int = 100,
) -> list[MediaFile]:
    """Get all discovered media files.

    Args:
        _user: Authenticated user (dependency)
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
    return list(result.scalars().all())


# Media item endpoints (authenticated users)
@router.get("/media/{media_id}", response_model=MediaFileSchema)
async def get_media_file(
    media_id: int,
    _user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MediaFileSchema:
    """Get a specific media file by ID with track information.

    Args:
        media_id: Media file ID
        _user: Authenticated user (dependency)
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

    return MediaFileSchema.model_validate(media_file)


# Homepage rows endpoint
@router.get("/homepage/rows", response_model=list[HomepageRow])
async def get_homepage_rows(
    _user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[HomepageRow]:
    """Get all visible rows for homepage.

    Returns playlists that are visible on homepage, with their filtered media files.

    Args:
        _user: Authenticated user (dependency)
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
        query = apply_filter_criteria(
            query, recommendation_row.filter_criteria, library.path
        )

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
            "items": [MediaFileSchema.model_validate(mf) for mf in media_files],
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
    _user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[HomepageRow]:
    """Get rows for a specific library (for Library View "Recommended" tab).

    Args:
        library_id: Library ID
        _user: Authenticated user (dependency)
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
        query = apply_filter_criteria(
            query, recommendation_row.filter_criteria, library.path
        )

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
                items=[MediaFileSchema.model_validate(mf) for mf in media_files],
            )
        )

    return rows
