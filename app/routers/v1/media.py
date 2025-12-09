"""API endpoints for managing media library and files (v1 with authentication)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.dependencies import get_current_active_user, require_admin
from app.models import (
    LibraryPath,
    LibraryPathCreate,
    LibraryPathSchema,
    LibraryPathUpdate,
    MediaFile,
    MediaFileSchema,
    Movie,
    MovieSchema,
    User,
)

router = APIRouter(prefix="/api/v1", tags=["media"])


# Library endpoints (authenticated users - enabled libraries only)
@router.get("/libraries", response_model=list[LibraryPathSchema])
async def get_libraries(
    _user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[LibraryPath]:
    """Get all enabled library paths (authenticated users).

    Args:
        _user: Authenticated user (dependency)
        session: Database session

    Returns:
        List of enabled library paths
    """
    result = await session.execute(select(LibraryPath).where(LibraryPath.enabled))
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
    library_path = await session.get(LibraryPath, library_id)
    if not library_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Library not found",
        )

    # Find MediaFiles that belong to this library (file_path starts with library path)
    result = await session.execute(
        select(MediaFile)
        .where(MediaFile.file_path.startswith(library_path.path))
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


@router.get("/libraries/{library_id}/movies", response_model=list[MovieSchema])
async def get_library_movies(
    library_id: int,
    _user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    skip: int = 0,
    limit: int = 100,
) -> list[Movie]:
    """Get movies from a specific library.

    Args:
        library_id: Library path ID
        _user: Authenticated user (dependency)
        session: Database session
        skip: Number of records to skip
        limit: Maximum number of records to return

    Returns:
        List of movies from the library

    Raises:
        HTTPException: If library not found
    """
    # Get the library path
    library_path = await session.get(LibraryPath, library_id)
    if not library_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Library not found",
        )

    # Find Movies that have media_file_id matching MediaFiles in this library
    # First, get MediaFile IDs in this library
    media_files_result = await session.execute(
        select(MediaFile.id).where(MediaFile.file_path.startswith(library_path.path))
    )
    media_file_ids = [mf_id for (mf_id,) in media_files_result.all()]

    if not media_file_ids:
        return []

    # Find Movies with matching media_file_id
    result = await session.execute(
        select(Movie)
        .where(Movie.media_file_id.in_(media_file_ids))
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


# Library Path endpoints (admin only)
@router.get("/library-paths", response_model=list[LibraryPathSchema])
async def get_library_paths(
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[LibraryPath]:
    """Get all configured library paths (admin only).

    Args:
        _admin: Admin user (dependency)
        session: Database session

    Returns:
        List of library paths
    """
    result = await session.execute(select(LibraryPath))
    return list(result.scalars().all())


@router.post(
    "/library-paths",
    response_model=LibraryPathSchema,
    status_code=status.HTTP_201_CREATED,
)
async def create_library_path(
    library_data: LibraryPathCreate,
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> LibraryPath:
    """Add a new library path to scan (admin only).

    Args:
        library_data: Library path creation data
        _admin: Admin user (dependency)
        session: Database session

    Returns:
        Created library path

    Raises:
        HTTPException: If path already exists
    """
    # Check if path already exists
    existing = await session.scalar(
        select(LibraryPath).where(LibraryPath.path == library_data.path)
    )

    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Library path already exists",
        )

    library_path = LibraryPath(
        path=library_data.path,
        library_type=library_data.library_type,
        enabled=library_data.enabled,
    )
    session.add(library_path)
    await session.commit()
    await session.refresh(library_path)
    return library_path


@router.delete("/library-paths/{path_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_library_path(
    path_id: int,
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    """Remove a library path (admin only).

    Args:
        path_id: Library path ID
        _admin: Admin user (dependency)
        session: Database session

    Raises:
        HTTPException: If path not found
    """
    library_path = await session.scalar(
        select(LibraryPath).where(LibraryPath.id == path_id)
    )
    if not library_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Library path not found",
        )

    await session.delete(library_path)
    await session.commit()


@router.patch("/library-paths/{path_id}", response_model=LibraryPathSchema)
async def update_library_path(
    path_id: int,
    update_data: LibraryPathUpdate,
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> LibraryPath:
    """Update a library path (admin only).

    Args:
        path_id: Library path ID
        update_data: Library path update data
        _admin: Admin user (dependency)
        session: Database session

    Returns:
        Updated library path

    Raises:
        HTTPException: If path not found or path already exists
    """
    library_path = await session.scalar(
        select(LibraryPath).where(LibraryPath.id == path_id)
    )
    if not library_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Library path not found",
        )

    # Check if path is being updated and if it conflicts with existing paths
    if update_data.path is not None and update_data.path != library_path.path:
        existing = await session.scalar(
            select(LibraryPath).where(LibraryPath.path == update_data.path)
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
    result = await session.execute(select(MediaFile).offset(skip).limit(limit))
    return list(result.scalars().all())


@router.get("/media-files/{media_id}", response_model=MediaFileSchema)
async def get_media_file(
    media_id: int,
    _user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MediaFile:
    """Get a specific media file by ID.

    Args:
        media_id: Media file ID
        _user: Authenticated user (dependency)
        session: Database session

    Returns:
        Media file details

    Raises:
        HTTPException: If media file not found
    """
    media_file = await session.get(MediaFile, media_id)
    if not media_file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Media file not found",
        )
    return media_file


# Media item endpoints (authenticated users)
@router.get("/media/{media_id}", response_model=MovieSchema)
async def get_media_item(
    media_id: int,
    _user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Movie:
    """Get a specific media item by ID (currently returns Movie).

    Args:
        media_id: Media item ID
        _user: Authenticated user (dependency)
        session: Database session

    Returns:
        Media item details (Movie schema)

    Raises:
        HTTPException: If media item not found
    """
    movie = await session.get(Movie, media_id)
    if not movie:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Media item not found",
        )
    return movie
