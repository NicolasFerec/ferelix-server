"""API endpoints for managing media library and files (v1 with authentication)."""

import asyncio
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_session
from app.dependencies import get_current_active_user
from app.models import (
    Library,
    LibrarySchema,
    MediaCardSchema,
    MediaFile,
    MediaFileSchema,
    MediaView,
    MediaViewSchema,
    MediaViewUpdate,
    RecommendationRow,
    User,
    WatchlistState,
)
from app.models.playback import (
    PlaybackInfoRequest,
    PlaybackInfoResponse,
    PlayMethod,
)
from app.services.catalogue import (
    media_card,
    media_card_query,
    recommendation_cards,
    visible_media_filter,
    watchlist_membership,
)
from app.services.item_catalogue import enrich_file_cards
from app.services.library_paths import library_file_filter
from app.services.media_access import require_owned_playback_session
from app.services.playback_preferences import resolve_playback_tracks
from app.services.playback_session import ClientContext, PlaybackSessionService
from app.services.stream_builder import StreamBuilder
from app.services.thumbnails import generate_video_thumbnail
from app.services.viewing import apply_file_progress_patch, set_file_watch_state
from app.services.watchlist import add_to_watchlist, remove_from_watchlist

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
    try:
        audio_index, subtitle_index = resolve_playback_tracks(
            media_file, _user, playback_request.AudioStreamIndex, playback_request.SubtitleStreamIndex
        )
        stream_info = stream_builder.build_stream_info(
            media_file,
            enable_direct_play=playback_request.EnableDirectPlay,
            enable_direct_stream=playback_request.EnableDirectStream,
            enable_transcoding=playback_request.EnableTranscoding,
            requested_resolution=playback_request.RequestedResolution,
            audio_stream_index=audio_index,
            subtitle_stream_index=subtitle_index,
            video_stream_index=playback_request.VideoStreamIndex,
            allow_video_stream_copy=playback_request.AllowVideoStreamCopy,
            allow_audio_stream_copy=playback_request.AllowAudioStreamCopy,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return PlaybackInfoResponse(
        MediaSources=[stream_info],
        ErrorCode="NoCompatiblePlaybackMethod" if stream_info.PlayMethod == PlayMethod.NONE else None,
    )


class HomepageRow(BaseModel):
    """Schema for homepage row response."""

    playlist_id: int
    library_id: int
    library_name: str
    name: str
    display_name: str
    items: list[MediaCardSchema]


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


@router.get("/libraries/{library_id}/items", response_model=list[MediaCardSchema])
async def get_library_items(
    library_id: int,
    user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    after_id: Annotated[int | None, Query(ge=0)] = None,
) -> list[MediaCardSchema]:
    """Get a stable, bounded page of library cards and current-user progress."""
    library = await session.get(Library, library_id)
    if not library:
        raise HTTPException(status_code=404, detail="Library not found")
    if not library.enabled:
        raise HTTPException(status_code=403, detail="Library is disabled")
    query = media_card_query(user.id).where(library_file_filter(library.path), MediaFile.deleted_at.is_(None))
    if after_id is not None:
        if skip:
            raise HTTPException(status_code=422, detail="Use either skip or after_id")
        query = query.where(MediaFile.id > after_id)
    result = await session.execute(query.order_by(MediaFile.id).offset(skip).limit(limit))
    return await enrich_file_cards(
        session, user.id, [media_card(media_file, view, in_watchlist) for media_file, view, in_watchlist in result]
    )


@router.get("/media-files", response_model=list[MediaCardSchema])
async def get_media_files(
    user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    after_id: Annotated[int | None, Query(ge=0)] = None,
) -> list[MediaCardSchema]:
    """Get a stable page; after_id supports traversal despite earlier deletions."""
    query = media_card_query(user.id).where(MediaFile.deleted_at.is_(None))
    if after_id is not None:
        if skip:
            raise HTTPException(status_code=422, detail="Use either skip or after_id")
        query = query.where(MediaFile.id > after_id)
    result = await session.execute(query.order_by(MediaFile.id).offset(skip).limit(limit))
    return await enrich_file_cards(
        session, user.id, [media_card(media_file, view, in_watchlist) for media_file, view, in_watchlist in result]
    )


@router.get("/media-files/search", response_model=list[MediaCardSchema])
async def search_media_files(
    user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    q: Annotated[str, Query(min_length=1, max_length=200)],
    library_id: Annotated[int | None, Query(ge=1)] = None,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 48,
    after_id: Annotated[int | None, Query(ge=0)] = None,
    sort: Literal["id", "relevance"] = "id",
) -> list[MediaCardSchema]:
    """Search the complete visible catalogue, interpreting SQL wildcards literally."""
    search = q.strip()
    if not search:
        raise HTTPException(status_code=422, detail="Search query must not be blank")
    query = media_card_query(user.id).where(
        visible_media_filter(library_id),
        MediaFile.file_name.icontains(search, autoescape=True),
    )
    if after_id is not None and sort == "relevance":
        raise HTTPException(status_code=422, detail="Relevance sorting uses skip pagination")
    if after_id is not None:
        if skip:
            raise HTTPException(status_code=422, detail="Use either skip or after_id")
        query = query.where(MediaFile.id > after_id)
    if sort == "relevance":
        # Rank across the whole catalogue before limiting suggestions, not within
        # an arbitrary first page. Prefer title prefixes, then word boundaries.
        relevance = case(
            (MediaFile.file_name.istartswith(search, autoescape=True), 0),
            (
                or_(
                    *(
                        MediaFile.file_name.icontains(f"{separator}{search}", autoescape=True)
                        for separator in (" ", ".", "_", "-")
                    )
                ),
                1,
            ),
            else_=2,
        )
        query = query.order_by(relevance, func.length(MediaFile.file_name), MediaFile.id)
    else:
        query = query.order_by(MediaFile.id)
    result = await session.execute(query.offset(skip).limit(limit))
    return await enrich_file_cards(
        session, user.id, [media_card(media_file, view, in_watchlist) for media_file, view, in_watchlist in result]
    )


@router.get("/users/me/watchlist", response_model=list[MediaCardSchema])
async def get_watchlist(
    user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 48,
    after_id: Annotated[int | None, Query(ge=0)] = None,
) -> list[MediaCardSchema]:
    """Get a stable page of the current user's visible saved films."""
    query = media_card_query(user.id).where(visible_media_filter(), watchlist_membership(user.id))
    if after_id is not None:
        if skip:
            raise HTTPException(status_code=422, detail="Use either skip or after_id")
        query = query.where(MediaFile.id > after_id)
    result = await session.execute(query.order_by(MediaFile.id).offset(skip).limit(limit))
    return await enrich_file_cards(
        session, user.id, [media_card(media_file, view, in_watchlist) for media_file, view, in_watchlist in result]
    )


@router.put("/users/me/watchlist/{media_id}", response_model=WatchlistState)
async def save_to_watchlist(
    media_id: int,
    user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> WatchlistState:
    await add_to_watchlist(session, user.id, media_id)
    return WatchlistState(media_file_id=media_id, in_watchlist=True)


@router.delete("/users/me/watchlist/{media_id}", response_model=WatchlistState)
async def delete_from_watchlist(
    media_id: int,
    user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> WatchlistState:
    await remove_from_watchlist(session, user.id, media_id)
    return WatchlistState(media_file_id=media_id, in_watchlist=False)


@router.get("/media-files/continue-watching", response_model=list[MediaCardSchema])
async def get_continue_watching_media_files(
    user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 24,
) -> list[MediaCardSchema]:
    """Get in-progress cards, filtering completed items before applying the limit."""
    result = await session.execute(
        media_card_query(user.id)
        .where(
            visible_media_filter(),
            MediaView.resume_active.is_(True),
            MediaView.position_seconds > 10,
        )
        .order_by(MediaView.last_viewed_at.desc(), MediaFile.id)
        .limit(limit)
    )
    return await enrich_file_cards(
        session, user.id, [media_card(media_file, view, in_watchlist) for media_file, view, in_watchlist in result]
    )


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
        select(MediaFile, watchlist_membership(user.id))
        .options(
            selectinload(MediaFile.video_tracks),
            selectinload(MediaFile.audio_tracks),
            selectinload(MediaFile.subtitle_tracks),
        )
        .where(MediaFile.id == media_id)
    )
    media_result = result.one_or_none()
    media_file = media_result[0] if media_result else None

    if not media_file or media_file.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Media file not found",
        )

    view = await get_user_media_view(session, user.id, media_id)
    schema = media_file_with_user_view(media_file, view)
    schema.in_watchlist = bool(media_result and media_result[1])
    await enrich_file_cards(session, user.id, [schema])
    return schema


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
    if payload.watched is not None:
        view = await set_file_watch_state(session, user.id, media_id, payload.watched)
    else:
        view = await apply_file_progress_patch(
            session, user.id, media_id, payload.position_seconds, payload.duration_seconds
        )

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
    if not (await asyncio.to_thread(source_path.exists)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media file not found on disk")

    thumbnail_path = Path(media_file.thumbnail_path) if media_file.thumbnail_path else None
    if not thumbnail_path or not thumbnail_path.exists():
        generated_path = await asyncio.to_thread(generate_video_thumbnail, source_path, media_file.duration)
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
        .where(RecommendationRow.visible_on_homepage == True, Library.enabled == True)
        .order_by(Library.name, RecommendationRow.name)
    )

    row_libraries = [(row, library) for row, library in result.all()]
    cards = await recommendation_cards(session, user.id, row_libraries)
    rows = []

    for recommendation_row, library in row_libraries:
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
            "items": cards[recommendation_row.id],
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

    row_libraries = [(row, library) for row in result.scalars().all()]
    cards = await recommendation_cards(session, user.id, row_libraries)
    rows = []

    for recommendation_row, _library in row_libraries:
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
                items=cards[recommendation_row.id],
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


def media_file_with_user_view(media_file: MediaFile, view: MediaView | None) -> MediaFileSchema:
    schema = MediaFileSchema.model_validate(media_file)
    schema.user_view = MediaViewSchema.model_validate(view) if view else None
    return schema


def is_media_in_progress(view: MediaView, media_duration: float | None) -> bool:
    return view.resume_active and view.position_seconds > 10


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
    try:
        audio_index, subtitle_index = resolve_playback_tracks(
            media_file, _user, playback_request.AudioStreamIndex, playback_request.SubtitleStreamIndex
        )
        stream_info = stream_builder.build_stream_info(
            media_file,
            enable_direct_play=playback_request.EnableDirectPlay,
            enable_direct_stream=playback_request.EnableDirectStream,
            enable_transcoding=playback_request.EnableTranscoding,
            requested_resolution=playback_request.RequestedResolution,
            audio_stream_index=audio_index,
            subtitle_stream_index=subtitle_index,
            video_stream_index=playback_request.VideoStreamIndex,
            allow_video_stream_copy=playback_request.AllowVideoStreamCopy,
            allow_audio_stream_copy=playback_request.AllowAudioStreamCopy,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if not playback_request.PlaybackSessionId:
        raise HTTPException(status_code=422, detail="PlaybackSessionId is required")
    await require_owned_playback_session(session, playback_request.PlaybackSessionId, media_id, _user)
    service = PlaybackSessionService(session)
    client = ClientContext(
        client_ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    try:
        response = await service.start_from_stream_info(
            media_id, stream_info, playback_request.PlaybackSessionId, playback_request.PlaybackGeneration, client
        )
        if stream_info.SubtitleStreamIndex is not None:
            response["subtitle_stream_index"] = str(stream_info.SubtitleStreamIndex)
        if stream_info.SubtitleDeliveryMethod:
            response["subtitle_delivery_method"] = stream_info.SubtitleDeliveryMethod
        if stream_info.SubtitleUrl:
            response["subtitle_url"] = stream_info.SubtitleUrl
        return response
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start streaming: {e}") from e
