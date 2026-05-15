"""Video streaming endpoints with HTTP Range and HLS transcoding support."""

from pathlib import Path
from typing import Annotated

import aiofiles
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_session
from app.dependencies import get_current_active_user
from app.models import (
    MediaFile,
    TranscodingJob,
    TranscodingJobSchema,
    User,
)
from app.models.transcoding import TranscodingJobType
from app.services.playback_session import ClientContext, HlsStartOptions, PlaybackSessionService
from app.services.streaming_io import (
    HLS_HEADERS,
    SEGMENT_HEADERS,
    VIDEO_CONTENT_TYPES,
    append_api_key_to_playlist_segments,
    parse_range_header,
    range_reader,
    touch_job,
    wait_for_hls_asset,
    wait_for_playlist,
    wait_for_segment,
)
from app.services.transcoder import TEXT_SUBTITLE_CODECS, get_transcoder

router = APIRouter(prefix="/api/v1", tags=["streaming"])


def client_context_from_request(request: Request) -> ClientContext:
    """Extract the small amount of request metadata stored with an HLS job."""
    return ClientContext(
        client_ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )


async def get_hls_job_or_404(session: AsyncSession, job_id: str) -> TranscodingJob:
    result = await session.execute(select(TranscodingJob).where(TranscodingJob.id == job_id))
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transcoding job not found")

    return job


async def start_hls_job_response(
    media_id: int,
    request: Request,
    session: AsyncSession,
    options: HlsStartOptions,
    failure_message: str,
) -> TranscodingJobSchema:
    try:
        service = PlaybackSessionService(session)
        job = await service.start_hls_job(media_id, options, client_context_from_request(request))
        return TranscodingJobSchema.model_validate(job)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{failure_message}: {exc}",
        ) from exc


@router.get("/stream/{media_id}")
async def stream_video(
    media_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[User, Depends(get_current_active_user)],
    range_header: Annotated[str | None, Header(alias="Range")] = None,
) -> StreamingResponse:
    """Stream video file with HTTP Range request support for seeking.

    Supports both:
    - Authorization: Bearer <token> header
    - ?api_key=<token> query parameter (for browser video tags)

    Args:
        media_id: Media file ID
        session: Database session
        _user: Authenticated user
        range_header: HTTP Range header for partial content requests

    Returns:
        Streaming response with video content

    Raises:
        HTTPException: If media file not found or range invalid
    """
    media_file = await session.get(MediaFile, media_id)

    if not media_file:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media file not found")

    file_path = Path(media_file.file_path)
    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Media file not found on disk",
        )

    file_size = file_path.stat().st_size
    start, end, partial = parse_range_header(range_header, file_size)
    content_type = VIDEO_CONTENT_TYPES.get(media_file.file_extension.lower(), "application/octet-stream")

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Type": content_type,
        "Content-Length": str(end - start + 1),
    }

    # Return partial content if range was requested
    if partial:
        headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
        return StreamingResponse(
            range_reader(file_path, start, end),
            status_code=status.HTTP_206_PARTIAL_CONTENT,
            headers=headers,
        )

    # Return full content
    return StreamingResponse(
        range_reader(file_path, start, end),
        status_code=status.HTTP_200_OK,
        headers=headers,
    )


@router.post("/hls/{media_id}/remux", response_model=TranscodingJobSchema)
async def start_hls_remux(
    media_id: int,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[User, Depends(get_current_active_user)],
    audio_stream_index: Annotated[int | None, Query(description="Audio stream index to include")] = None,
    start_time: Annotated[float | None, Query(description="Start time in seconds for seeking")] = None,
) -> TranscodingJobSchema:
    """Start HLS remuxing (container conversion only, no re-encoding).

    Fast operation that changes the container format without re-encoding.
    Ideal for MKV files with compatible codecs (H.264/AAC).

    Args:
        media_id: Media file ID
        audio_stream_index: Specific audio stream to include (None = default)
        start_time: Start position in seconds for seeking
    """

    return await start_hls_job_response(
        media_id,
        request,
        session,
        HlsStartOptions(
            job_type=TranscodingJobType.REMUX,
            video_codec="copy",
            audio_codec="copy",
            audio_stream_index=audio_stream_index,
            start_time=start_time,
        ),
        "Failed to start remuxing",
    )


@router.post("/hls/{media_id}/start", response_model=TranscodingJobSchema)
async def start_hls_stream(
    media_id: int,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[User, Depends(get_current_active_user)],
    video_codec: Annotated[str, Query(description="Target video codec")] = "h264",
    audio_codec: Annotated[str, Query(description="Target audio codec")] = "aac",
    video_bitrate: Annotated[int | None, Query(description="Target video bitrate")] = None,
    audio_bitrate: Annotated[int | None, Query(description="Target audio bitrate")] = None,
    max_width: Annotated[int | None, Query(description="Maximum video width")] = None,
    max_height: Annotated[int | None, Query(description="Maximum video height")] = None,
    audio_stream_index: Annotated[int | None, Query(description="Audio stream index to include")] = None,
    subtitle_stream_index: Annotated[int | None, Query(description="Subtitle stream index to burn")] = None,
    start_time: Annotated[float | None, Query(description="Start time in seconds for seeking")] = None,
) -> TranscodingJobSchema:
    """Start HLS transcoding for a media file.

    Full transcoding with optional re-encoding of video/audio streams.

    Args:
        media_id: Media file ID
        video_codec: Target video codec (h264, hevc, copy)
        audio_codec: Target audio codec (aac, mp3, copy)
        video_bitrate: Target video bitrate
        audio_bitrate: Target audio bitrate
        max_width: Maximum video width for scaling
        max_height: Maximum video height for scaling
        audio_stream_index: Specific audio stream to include (None = default)
        subtitle_stream_index: Subtitle stream to burn into video (None = no subtitles)
        start_time: Start position in seconds for seeking

    Returns:
        Transcoding job that can be used to access the HLS playlist once ready.
    """
    return await start_hls_job_response(
        media_id,
        request,
        session,
        HlsStartOptions(
            job_type=TranscodingJobType.HLS,
            video_codec=video_codec,
            audio_codec=audio_codec,
            video_bitrate=video_bitrate,
            audio_bitrate=audio_bitrate,
            max_width=max_width,
            max_height=max_height,
            audio_stream_index=audio_stream_index,
            subtitle_stream_index=subtitle_stream_index,
            start_time=start_time,
        ),
        "Failed to start transcoding",
    )


@router.post("/hls/{media_id}/audio-transcode", response_model=TranscodingJobSchema)
async def start_hls_audio_transcode(
    media_id: int,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[User, Depends(get_current_active_user)],
    audio_codec: Annotated[str, Query(description="Target audio codec")] = "aac",
    audio_bitrate: Annotated[int | None, Query(description="Target audio bitrate")] = 128000,
    audio_stream_index: Annotated[int | None, Query(description="Audio stream index to include")] = None,
    start_time: Annotated[float | None, Query(description="Start time in seconds for seeking")] = None,
) -> TranscodingJobSchema:
    """Start HLS audio-transcode: copy video streams and transcode only the audio track.

    This is faster than full transcoding when only the audio codec is incompatible.

    Args:
        media_id: Media file ID
        audio_codec: Target audio codec (aac, mp3)
        audio_bitrate: Target audio bitrate
        audio_stream_index: Specific audio stream to include (None = default)
        start_time: Start position in seconds for seeking
    """

    return await start_hls_job_response(
        media_id,
        request,
        session,
        HlsStartOptions(
            job_type=TranscodingJobType.AUDIO_TRANSCODE,
            video_codec="copy",
            audio_codec=audio_codec,
            audio_bitrate=audio_bitrate,
            audio_stream_index=audio_stream_index,
            start_time=start_time,
        ),
        "Failed to start audio-transcode",
    )


@router.get("/hls/{job_id}/playlist.m3u8")
@router.head("/hls/{job_id}/playlist.m3u8")
async def get_hls_playlist(
    job_id: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[User, Depends(get_current_active_user)],
) -> PlainTextResponse:
    """Get HLS playlist file for a transcoding job."""

    job = await get_hls_job_or_404(session, job_id)
    playlist_path = await wait_for_playlist(job, session)
    await touch_job(session, job)

    # For HEAD requests, just return empty response with proper headers
    if request.method == "HEAD":
        return PlainTextResponse(
            content="",
            media_type="application/vnd.apple.mpegurl",
            headers=HLS_HEADERS,
        )

    # Return playlist content with CORS headers
    try:
        async with aiofiles.open(playlist_path) as f:
            content = await f.read()

        content = append_api_key_to_playlist_segments(content, request.query_params.get("api_key"))

        return PlainTextResponse(
            content,
            media_type="application/vnd.apple.mpegurl",
            headers=HLS_HEADERS,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read playlist: {exc}") from exc


@router.get("/hls/{job_id}/segment_{segment_num:int}.ts")
async def get_hls_segment(
    job_id: str,
    segment_num: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[User, Depends(get_current_active_user)],
) -> FileResponse:
    """Get HLS segment file for a transcoding job."""

    job = await get_hls_job_or_404(session, job_id)
    segment_path = await wait_for_segment(job, segment_num, session)
    await touch_job(session, job)

    # Return segment file
    return FileResponse(
        segment_path,
        media_type="video/mp2t",
        headers=SEGMENT_HEADERS,
    )


@router.get("/hls/{job_id}/init.mp4")
async def get_hls_fmp4_init(
    job_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[User, Depends(get_current_active_user)],
) -> FileResponse:
    """Get fMP4 HLS initialization segment."""
    job = await get_hls_job_or_404(session, job_id)
    asset_path = await wait_for_hls_asset(job, "init.mp4", session)
    await touch_job(session, job)

    return FileResponse(
        asset_path,
        media_type="video/mp4",
        headers=SEGMENT_HEADERS,
    )


@router.get("/hls/{job_id}/segment_{segment_num:int}.m4s")
async def get_hls_fmp4_segment(
    job_id: str,
    segment_num: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[User, Depends(get_current_active_user)],
) -> FileResponse:
    """Get fMP4 HLS media segment."""
    job = await get_hls_job_or_404(session, job_id)
    asset_path = await wait_for_hls_asset(job, f"segment_{segment_num:03d}.m4s", session)
    await touch_job(session, job)

    return FileResponse(
        asset_path,
        media_type="video/iso.segment",
        headers=SEGMENT_HEADERS,
    )


@router.get("/hls/{job_id}/status", response_model=TranscodingJobSchema)
async def get_hls_status(
    job_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[User, Depends(get_current_active_user)],
) -> TranscodingJobSchema:
    """Get status of HLS transcoding job."""

    job = await get_hls_job_or_404(session, job_id)
    await touch_job(session, job)
    return TranscodingJobSchema.model_validate(job)


@router.delete("/hls/{job_id}/stop")
async def stop_hls_stream(
    job_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[User, Depends(get_current_active_user)],
) -> dict[str, str]:
    """Stop HLS transcoding job."""

    await get_hls_job_or_404(session, job_id)
    transcoder = get_transcoder()
    success = await transcoder.stop_job(job_id)

    if success:
        return {"message": "Transcoding job stopped"}
    else:
        return {"message": "Job was not running or could not be stopped"}


@router.get("/subtitle/{media_id}/{stream_index}")
async def get_subtitle(
    media_id: int,
    stream_index: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[User, Depends(get_current_active_user)],
) -> PlainTextResponse:
    """Extract and serve a subtitle track as WebVTT.

    Only works with text-based subtitle codecs (SRT, ASS, WebVTT, etc.).
    Image-based subtitles (PGS, VOBSUB) must be burned into the video.

    Args:
        media_id: Media file ID
        stream_index: Subtitle stream index within the media file

    Returns:
        WebVTT formatted subtitle content
    """
    # Fetch media file with subtitle tracks
    result = await session.execute(
        select(MediaFile).options(selectinload(MediaFile.subtitle_tracks)).where(MediaFile.id == media_id)
    )
    media_file = result.scalar_one_or_none()

    if not media_file:
        raise HTTPException(status_code=404, detail="Media file not found")

    file_path = Path(media_file.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Media file not found on disk")

    subtitle_track = next(
        (track for track in media_file.subtitle_tracks if track.stream_index == stream_index),
        None,
    )
    if not subtitle_track:
        raise HTTPException(status_code=404, detail="Subtitle track not found")

    # Check if it's a text-based subtitle
    if subtitle_track.codec.lower() not in TEXT_SUBTITLE_CODECS:
        raise HTTPException(
            status_code=400,
            detail=f"Subtitle codec '{subtitle_track.codec}' cannot be extracted to WebVTT. "
            "Image-based subtitles must be burned into the video.",
        )

    # Create temp directory for extracted subtitles
    transcoder = get_transcoder()
    subtitle_cache_dir = transcoder.temp_dir / "subtitles"
    subtitle_cache_dir.mkdir(parents=True, exist_ok=True, mode=0o755)
    subtitle_cache_dir.chmod(0o755)

    # Check if already extracted (cache)
    output_file = subtitle_cache_dir / f"{media_id}_{stream_index}.vtt"

    if not output_file.exists():
        # Extract subtitle to WebVTT
        success = await transcoder.extract_subtitle_to_webvtt(
            media_file_path=str(file_path),
            subtitle_stream_index=stream_index,
            output_path=str(output_file),
        )

        if not success:
            raise HTTPException(status_code=500, detail="Failed to extract subtitle")

    # Read and return the WebVTT content
    try:
        async with aiofiles.open(output_file) as f:
            content = await f.read()

        return PlainTextResponse(
            content,
            media_type="text/vtt",
            headers={
                "Access-Control-Allow-Origin": "*",
                "Cache-Control": "public, max-age=86400",  # Cache for 24 hours
            },
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read subtitle: {exc}") from exc
