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
from app.models.playback import (
    PlaybackInfoRequest,
    PlaybackInfoResponse,
)
from app.services.recommendation_row import apply_filter_criteria
from app.services.stream_builder import StreamBuilder

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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Media file not found"
        )

    # Build stream info using device profile
    stream_builder = StreamBuilder(playback_request.DeviceProfile)
    stream_info = stream_builder.build_stream_info(
        media_file,
        enable_direct_play=playback_request.EnableDirectPlay,
        enable_direct_stream=playback_request.EnableDirectStream,
        enable_transcoding=playback_request.EnableTranscoding,
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


@router.post("/start-stream/{media_id}")
async def start_media_stream(
    media_id: int,
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

    from app.models.playback import PlayMethod

    if stream_info.PlayMethod == PlayMethod.DIRECT_PLAY:
        # Direct file streaming
        return {
            "method": "direct_play",
            "url": f"/api/v1/stream/{media_id}",
            "message": "Use direct streaming endpoint",
        }

    elif stream_info.PlayMethod == PlayMethod.DIRECT_STREAM:
        # DirectStream could be remux or direct file access
        if stream_info.IsRemuxOnly:
            # Need container conversion - start remux job
            from app.routers.v1.streaming import start_hls_remux

            class RemuxMockRequest:
                def __init__(self):
                    self.client = None
                    self.headers = {}
                    self.url = "mock://remux"
                    self.method = "POST"
                    self.path_info = "/"
                    self.query_string = b""
                    self.cookies = {}

            mock_request = RemuxMockRequest()

            try:
                job = await start_hls_remux(
                    media_id=media_id,
                    request=mock_request,  # type: ignore
                    session=session,
                    user=_user,
                )

                return {
                    "method": "hls_remux",
                    "job_id": job.id,
                    "playlist_url": f"/api/v1/hls/{job.id}/playlist.m3u8",
                    "status_url": f"/api/v1/hls/{job.id}/status",
                    "message": "HLS remuxing started (fast, no re-encoding)",
                }

            except Exception as e:
                raise HTTPException(
                    status_code=500, detail=f"Failed to start remuxing: {e}"
                )

        else:
            # Direct streaming (no transcoding needed)
            return {
                "method": "direct_stream",
                "url": f"/api/v1/stream/{media_id}",
                "message": "Use direct streaming endpoint",
            }

    else:
        # Need full transcoding - start HLS job automatically

        from app.routers.v1.streaming import start_hls_stream

        # Create a mock request for the HLS endpoint
        # In a real implementation, you'd pass the actual request
        class TranscodeMockRequest:
            def __init__(self):
                self.client = None
                self.headers = {}
                self.url = "mock://transcode"
                self.method = "POST"
                self.path_info = "/"
                self.query_string = b""
                self.cookies = {}

        mock_request = TranscodeMockRequest()

        # Extract transcoding settings from stream info
        transcode_settings = stream_info.TranscodeSettings
        video_codec = "h264"  # Default
        audio_codec = "aac"  # Default

        if transcode_settings and transcode_settings.VideoCodec:
            video_codec = transcode_settings.VideoCodec
        if transcode_settings and transcode_settings.AudioCodec:
            audio_codec = transcode_settings.AudioCodec

        # Start HLS transcoding
        try:
            job = await start_hls_stream(
                media_id=media_id,
                request=mock_request,  # type: ignore
                session=session,
                user=_user,
                video_codec=video_codec,
                audio_codec=audio_codec,
                video_bitrate=transcode_settings.VideoBitrate
                if transcode_settings
                else None,
                audio_bitrate=transcode_settings.AudioBitrate
                if transcode_settings
                else None,
                max_width=transcode_settings.MaxWidth if transcode_settings else None,
                max_height=transcode_settings.MaxHeight if transcode_settings else None,
            )

            return {
                "method": "hls_transcode",
                "job_id": job.id,
                "playlist_url": f"/api/v1/hls/{job.id}/playlist.m3u8",
                "status_url": f"/api/v1/hls/{job.id}/status",
                "message": "HLS transcoding started",
            }

        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Failed to start streaming: {e}"
            )
