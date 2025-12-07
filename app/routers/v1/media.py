"""API endpoints for managing media library and files (v1 with authentication)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.dependencies import get_current_active_user, require_admin
from app.models import (
    LibraryPath,
    LibraryPathSchema,
    MediaFile,
    MediaFileSchema,
    Movie,
    MovieSchema,
    User,
)

router = APIRouter(prefix="/api/v1", tags=["media"])


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
    path: str,
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
    enabled: bool = True,
) -> LibraryPath:
    """Add a new library path to scan (admin only).

    Args:
        path: Filesystem path to scan
        _admin: Admin user (dependency)
        session: Database session
        enabled: Whether the path is enabled for scanning

    Returns:
        Created library path

    Raises:
        HTTPException: If path already exists
    """
    # Check if path already exists
    existing = await session.scalar(select(LibraryPath).where(LibraryPath.path == path))

    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Library path already exists",
        )

    library_path = LibraryPath(path=path, enabled=enabled)
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


# Movie endpoints (authenticated users)
@router.get("/movies", response_model=list[MovieSchema])
async def get_movies(
    _user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    skip: int = 0,
    limit: int = 100,
) -> list[Movie]:
    """Get all movies.

    Args:
        _user: Authenticated user (dependency)
        session: Database session
        skip: Number of records to skip
        limit: Maximum number of records to return

    Returns:
        List of movies
    """
    result = await session.execute(select(Movie).offset(skip).limit(limit))
    return list(result.scalars().all())


@router.get("/movies/{movie_id}", response_model=MovieSchema)
async def get_movie(
    movie_id: int,
    _user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Movie:
    """Get a specific movie by ID.

    Args:
        movie_id: Movie ID
        _user: Authenticated user (dependency)
        session: Database session

    Returns:
        Movie details

    Raises:
        HTTPException: If movie not found
    """
    movie = await session.get(Movie, movie_id)
    if not movie:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Movie not found",
        )
    return movie
