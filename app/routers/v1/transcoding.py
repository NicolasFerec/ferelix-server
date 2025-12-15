"""API endpoints for media transcoding (v1 with authentication)."""

import asyncio
import logging
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.dependencies import get_current_active_user
from app.models import (
    CompatibilityCheckRequest,
    CompatibilityCheckResponse,
    MediaFile,
    StartTranscodingRequest,
    TranscodingFormat,
    TranscodingProgressResponse,
    TranscodingSessionSchema,
    TranscodingStatus,
    User,
)
from app.services.transcoding import (
    check_media_compatibility,
    cleanup_session,
    create_transcoding_session,
    get_transcoding_session,
    start_transcoding,
    update_last_accessed,
)

router = APIRouter(prefix="/api/v1", tags=["transcoding"])
logger = logging.getLogger(__name__)


@router.post("/transcode/compatibility-check", response_model=CompatibilityCheckResponse)
async def check_compatibility(
    request: CompatibilityCheckRequest,
    _user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CompatibilityCheckResponse:
    """Check if media file is compatible with client capabilities.

    This endpoint allows the client to declare what formats it supports
    and returns whether direct play is possible or transcoding is needed.

    Args:
        request: Compatibility check request with media ID and client capabilities
        _user: Authenticated user (dependency)
        session: Database session

    Returns:
        Compatibility check response with direct play status and reasons
    """
    caps = request.client_capabilities

    result = await check_media_compatibility(
        session=session,
        media_file_id=request.media_file_id,
        video_codecs=caps.video_codecs,
        audio_codecs=caps.audio_codecs,
        containers=caps.containers,
        subtitle_codecs=caps.subtitle_codecs,
    )

    return CompatibilityCheckResponse(
        can_direct_play=result["can_direct_play"],
        requires_transcoding=result["requires_transcoding"],
        reasons=result.get("reasons", []),
        suggested_profile=None,  # TODO: Implement profile suggestion
    )


@router.post("/transcode/start", response_model=TranscodingSessionSchema)
async def start_transcode_session(
    request: StartTranscodingRequest,
    user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TranscodingSessionSchema:
    """Start a new transcoding session.

    Creates a transcoding session and starts the FFmpeg process to
    transcode the media file to a compatible format.

    Args:
        request: Transcoding request with media ID and parameters
        user: Authenticated user (dependency)
        session: Database session

    Returns:
        Created transcoding session with session_id
    """
    # Check if media file exists
    media_file = await session.get(MediaFile, request.media_file_id)
    if not media_file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Media file not found",
        )

    # Create transcoding session
    transcode_session = await create_transcoding_session(
        session=session,
        media_file_id=request.media_file_id,
        user_id=user.id,
        output_format=request.output_format,
        audio_track_index=request.audio_track_index,
        subtitle_track_index=request.subtitle_track_index,
    )

    # Start transcoding in background
    task = asyncio.create_task(start_transcoding(transcode_session.session_id))
    # Store task reference to prevent GC (task will run to completion)
    task.add_done_callback(lambda t: None)

    return TranscodingSessionSchema.model_validate(transcode_session)


@router.get("/transcode/{session_id}/progress", response_model=TranscodingProgressResponse)
async def get_transcode_progress(
    session_id: str,
    _user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TranscodingProgressResponse:
    """Get transcoding progress for a session.

    Returns the current status and progress percentage of the transcoding.
    Useful for showing progress bars to users.

    Args:
        session_id: Transcoding session ID
        _user: Authenticated user (dependency)
        session: Database session

    Returns:
        Progress response with status and percentage
    """
    transcode_session = await get_transcoding_session(session, session_id)

    if not transcode_session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transcoding session not found",
        )

    # Update last accessed time
    await update_last_accessed(session, session_id)

    return TranscodingProgressResponse(
        session_id=session_id,
        status=transcode_session.status,
        progress=transcode_session.progress,
        error_message=transcode_session.error_message,
    )


@router.get("/transcode/{session_id}/stream", response_model=None)
async def stream_transcoded(
    session_id: str,
    _user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FileResponse:
    """Stream transcoded content.

    For HLS format, returns the m3u8 playlist.
    For progressive format, returns the transcoded video file.

    Args:
        session_id: Transcoding session ID
        _user: Authenticated user (dependency)
        session: Database session

    Returns:
        File response with transcoded content
    """
    transcode_session = await get_transcoding_session(session, session_id)

    if not transcode_session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transcoding session not found",
        )

    # Check if transcoding is complete
    if transcode_session.status != TranscodingStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_425_TOO_EARLY,
            detail=f"Transcoding not complete. Status: {transcode_session.status}",
        )

    # Update last accessed time
    await update_last_accessed(session, session_id)

    # Return appropriate file based on format
    if transcode_session.output_format == TranscodingFormat.HLS:
        if not transcode_session.manifest_path:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="HLS manifest path not set",
            )

        manifest_path = Path(transcode_session.manifest_path)
        if not manifest_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="HLS manifest not found",
            )

        return FileResponse(
            manifest_path,
            media_type="application/vnd.apple.mpegurl",
            filename="playlist.m3u8",
        )
    else:
        # Progressive format
        if not transcode_session.output_path:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Output path not set",
            )

        output_file = Path(transcode_session.output_path) / "output.mp4"
        if not output_file.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Transcoded file not found",
            )

        return FileResponse(
            output_file,
            media_type="video/mp4",
            filename="video.mp4",
        )


@router.get("/transcode/{session_id}/segment/{segment_name}")
async def get_hls_segment(
    session_id: str,
    segment_name: str,
    _user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FileResponse:
    """Get HLS segment file.

    Returns individual HLS segment files (.ts) for streaming.

    Args:
        session_id: Transcoding session ID
        segment_name: Segment filename (e.g., "segment_001.ts")
        _user: Authenticated user (dependency)
        session: Database session

    Returns:
        File response with HLS segment
    """
    transcode_session = await get_transcoding_session(session, session_id)

    if not transcode_session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transcoding session not found",
        )

    if transcode_session.output_format != TranscodingFormat.HLS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This endpoint is only for HLS format",
        )

    # Update last accessed time
    await update_last_accessed(session, session_id)

    # Validate segment name to prevent directory traversal
    if ".." in segment_name or "/" in segment_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid segment name",
        )

    if not transcode_session.output_path:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Output path not set",
        )

    segment_path = Path(transcode_session.output_path) / segment_name
    if not segment_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Segment not found",
        )

    return FileResponse(
        segment_path,
        media_type="video/mp2t",
        filename=segment_name,
    )


@router.delete("/transcode/{session_id}")
async def delete_transcode_session(
    session_id: str,
    _user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, str]:
    """Delete a transcoding session and cleanup files.

    Removes the transcoding session and all associated files.
    Should be called when the client is done with the transcoded content.

    Args:
        session_id: Transcoding session ID
        _user: Authenticated user (dependency)
        session: Database session

    Returns:
        Success message
    """
    success = await cleanup_session(session, session_id)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transcoding session not found",
        )

    return {"message": "Transcoding session deleted"}
