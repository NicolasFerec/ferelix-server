"""Video streaming endpoints with HTTP Range and HLS transcoding support."""

import uuid
from pathlib import Path
from typing import Annotated

import aiofiles
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_session
from app.dependencies import get_optional_user
from app.models import (
    MediaFile,
    TranscodingJob,
    TranscodingJobSchema,
    User,
)
from app.models.transcoding import TranscodingJobStatus, TranscodingJobType
from app.services.transcoder import TEXT_SUBTITLE_CODECS, get_transcoder

router = APIRouter(prefix="/api/v1", tags=["streaming"])


async def range_reader(file_path: Path, start: int, end: int, chunk_size: int = 8192):
    """Async generator to stream file chunks within a byte range.

    Args:
        file_path: Path to the file to stream
        start: Start byte position
        end: End byte position (inclusive)
        chunk_size: Size of chunks to read

    Yields:
        File chunks as bytes
    """
    async with aiofiles.open(file_path, mode="rb") as f:
        await f.seek(start)
        remaining = end - start + 1

        while remaining > 0:
            chunk_size_to_read = min(chunk_size, remaining)
            data = await f.read(chunk_size_to_read)
            if not data:
                break
            remaining -= len(data)
            yield data


@router.get("/stream/{media_id}")
async def stream_video(
    media_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User | None, Depends(get_optional_user)] = None,
    range_header: Annotated[str | None, Header(alias="Range")] = None,
) -> StreamingResponse:
    """Stream video file with HTTP Range request support for seeking.

    Authentication is optional but recommended. Supports both:
    - Authorization: Bearer <token> header
    - ?api_key=<token> query parameter (for browser video tags)

    Args:
        media_id: Media file ID
        session: Database session
        user: Optional authenticated user
        range_header: HTTP Range header for partial content requests

    Returns:
        Streaming response with video content

    Raises:
        HTTPException: If media file not found or range invalid
    """
    # Note: Authentication is optional for streaming to support public access
    # In production, you may want to require authentication

    # Fetch media file from database
    media_file = await session.get(MediaFile, media_id)

    if not media_file:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media file not found")

    file_path = Path(media_file.file_path)
    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Media file not found on disk",
        )

    file_size = media_file.file_size

    # Parse Range header
    start = 0
    end = file_size - 1

    if range_header:
        # Range header format: "bytes=start-end"
        range_str = range_header.replace("bytes=", "")
        range_parts = range_str.split("-")

        if range_parts[0]:
            start = int(range_parts[0])
        end = int(range_parts[1]) if range_parts[1] else file_size - 1

        # Validate range
        if start >= file_size or end >= file_size or start > end:
            raise HTTPException(
                status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
                detail="Invalid range",
            )

    # Determine content type based on file extension
    content_type_map = {
        ".mp4": "video/mp4",
        ".mkv": "video/x-matroska",
        ".avi": "video/x-msvideo",
        ".mov": "video/quicktime",
        ".webm": "video/webm",
        ".m4v": "video/x-m4v",
    }
    content_type = content_type_map.get(media_file.file_extension.lower(), "application/octet-stream")

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Type": content_type,
        "Content-Length": str(end - start + 1),
    }

    # Return partial content if range was requested
    if range_header:
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
    user: Annotated[User | None, Depends(get_optional_user)] = None,
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

    # Fetch media file
    media_file = await session.get(MediaFile, media_id)
    if not media_file:
        raise HTTPException(status_code=404, detail="Media file not found")

    file_path = Path(media_file.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Media file not found on disk")

    # Generate session ID for this streaming session
    session_id = str(uuid.uuid4())

    # Create transcoding job
    job_id = str(uuid.uuid4())
    job = TranscodingJob(
        id=job_id,
        media_file_id=media_id,
        type=TranscodingJobType.REMUX,  # Use REMUX type for fast container conversion
        status=TranscodingJobStatus.PENDING,
        session_id=session_id,
        client_ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    session.add(job)
    await session.commit()
    await session.refresh(job)

    # Start remuxing (fast, no re-encoding)
    transcoder = get_transcoder()
    try:
        await transcoder.start_remux_hls(
            job_id=job_id,
            media_file=media_file,
            session_id=session_id,
            client_ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            audio_stream_index=audio_stream_index,
            start_time=start_time,
        )

        # Refresh job to get updated status
        await session.refresh(job)
        return TranscodingJobSchema.model_validate(job)

    except Exception as e:
        # Clean up failed job
        await session.delete(job)
        await session.commit()
        raise HTTPException(status_code=500, detail=f"Failed to start remuxing: {e}")


@router.post("/hls/{media_id}/start", response_model=TranscodingJobSchema)
async def start_hls_stream(
    media_id: int,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User | None, Depends(get_optional_user)] = None,
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
    # Fetch media file with tracks
    result = await session.execute(
        select(MediaFile)
        .options(
            selectinload(MediaFile.subtitle_tracks),
        )
        .where(MediaFile.id == media_id)
    )
    media_file = result.scalar_one_or_none()
    if not media_file:
        raise HTTPException(status_code=404, detail="Media file not found")

    file_path = Path(media_file.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Media file not found on disk")

    # Generate session ID for this streaming session
    session_id = str(uuid.uuid4())

    # Create transcoding job
    job_id = str(uuid.uuid4())
    job = TranscodingJob(
        id=job_id,
        media_file_id=media_id,
        type=TranscodingJobType.HLS,
        status=TranscodingJobStatus.PENDING,
        session_id=session_id,
        client_ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    session.add(job)
    await session.commit()
    await session.refresh(job)

    # Start transcoding
    transcoder = get_transcoder()
    try:
        await transcoder.start_hls_transcode(
            job_id=job_id,
            media_file=media_file,
            video_codec=video_codec,
            audio_codec=audio_codec,
            video_bitrate=video_bitrate,
            audio_bitrate=audio_bitrate,
            max_width=max_width,
            max_height=max_height,
            session_id=session_id,
            client_ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            audio_stream_index=audio_stream_index,
            subtitle_stream_index=subtitle_stream_index,
            start_time=start_time,
        )

        # Refresh job to get updated status
        await session.refresh(job)
        return TranscodingJobSchema.model_validate(job)

    except Exception as e:
        # Clean up failed job
        await session.delete(job)
        await session.commit()
        raise HTTPException(status_code=500, detail=f"Failed to start transcoding: {e}")


@router.post("/hls/{media_id}/audio-transcode", response_model=TranscodingJobSchema)
async def start_hls_audio_transcode(
    media_id: int,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User | None, Depends(get_optional_user)] = None,
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

    # Fetch media file with tracks
    result = await session.execute(
        select(MediaFile)
        .options(
            selectinload(MediaFile.subtitle_tracks),
        )
        .where(MediaFile.id == media_id)
    )
    media_file = result.scalar_one_or_none()
    if not media_file:
        raise HTTPException(status_code=404, detail="Media file not found")

    file_path = Path(media_file.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Media file not found on disk")

    # Generate session ID for this streaming session
    session_id = str(uuid.uuid4())

    # Create transcoding job (audio-transcode)
    job_id = str(uuid.uuid4())
    job = TranscodingJob(
        id=job_id,
        media_file_id=media_id,
        type=TranscodingJobType.AUDIO_TRANSCODE,
        status=TranscodingJobStatus.PENDING,
        session_id=session_id,
        client_ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        audio_codec=audio_codec,
        audio_bitrate=audio_bitrate,
        video_codec="copy",
    )

    session.add(job)
    await session.commit()
    await session.refresh(job)

    # Start transcoding (copy video, transcode audio)
    transcoder = get_transcoder()
    try:
        await transcoder.start_hls_transcode(
            job_id=job_id,
            media_file=media_file,
            video_codec="copy",
            audio_codec=audio_codec,
            video_bitrate=None,
            audio_bitrate=audio_bitrate,
            session_id=session_id,
            client_ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            audio_stream_index=audio_stream_index,
            start_time=start_time,
        )

        # Refresh job to get updated status
        await session.refresh(job)
        return TranscodingJobSchema.model_validate(job)

    except Exception as e:
        # Clean up failed job
        await session.delete(job)
        await session.commit()
        raise HTTPException(status_code=500, detail=f"Failed to start audio-transcode: {e}")


@router.get("/hls/{job_id}/playlist.m3u8")
@router.head("/hls/{job_id}/playlist.m3u8")
async def get_hls_playlist(
    job_id: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User | None, Depends(get_optional_user)] = None,
) -> PlainTextResponse:
    """Get HLS playlist file for a transcoding job."""

    # Get job from database
    result = await session.execute(select(TranscodingJob).where(TranscodingJob.id == job_id))
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Transcoding job not found")

    if job.status == TranscodingJobStatus.CANCELLED:
        raise HTTPException(status_code=410, detail="Transcoding job was cancelled")
    elif job.status == TranscodingJobStatus.FAILED:
        error_detail = f"Transcoding failed: {job.error_message}" if job.error_message else "Transcoding failed"
        raise HTTPException(status_code=500, detail=error_detail)
    elif job.status != TranscodingJobStatus.RUNNING and job.status != TranscodingJobStatus.COMPLETED:
        raise HTTPException(status_code=404, detail="Playlist not ready yet")

    if not job.playlist_path:
        raise HTTPException(status_code=404, detail="Playlist path not set")

    playlist_path = Path(job.playlist_path)
    if not playlist_path.exists():
        raise HTTPException(status_code=404, detail="Playlist file not found")

    # For HEAD requests, just return empty response with proper headers
    if request.method == "HEAD":
        return PlainTextResponse(
            content="",
            media_type="application/vnd.apple.mpegurl",
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "*",
                "Cache-Control": "no-cache",
            },
        )

    # Update last accessed time - will be set by database default
    await session.commit()

    # Return playlist content with CORS headers
    try:
        async with aiofiles.open(playlist_path) as f:
            content = await f.read()

        return PlainTextResponse(
            content,
            media_type="application/vnd.apple.mpegurl",
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "*",
                "Cache-Control": "no-cache",
            },
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read playlist: {e}")


@router.get("/hls/{job_id}/segment_{segment_num:int}.ts")
async def get_hls_segment(
    job_id: str,
    segment_num: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User | None, Depends(get_optional_user)] = None,
) -> FileResponse:
    """Get HLS segment file for a transcoding job."""

    # Get job from database
    result = await session.execute(select(TranscodingJob).where(TranscodingJob.id == job_id))
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Transcoding job not found")

    if not job.output_path:
        raise HTTPException(status_code=404, detail="Job output path not set")

    # Build segment file path
    segment_path = Path(job.output_path) / f"segment_{segment_num:03d}.ts"

    if not segment_path.exists():
        raise HTTPException(status_code=404, detail=f"Segment {segment_num} not found")

    # Update last accessed time - will be set by database default
    await session.commit()

    # Return segment file
    return FileResponse(
        segment_path,
        media_type="video/mp2t",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*",
            "Cache-Control": "public, max-age=3600",  # Cache segments for 1 hour
        },
    )


@router.get("/hls/{job_id}/status", response_model=TranscodingJobSchema)
async def get_hls_status(
    job_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User | None, Depends(get_optional_user)] = None,
) -> TranscodingJobSchema:
    """Get status of HLS transcoding job."""

    result = await session.execute(select(TranscodingJob).where(TranscodingJob.id == job_id))
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Transcoding job not found")

    return TranscodingJobSchema.model_validate(job)


@router.delete("/hls/{job_id}/stop")
async def stop_hls_stream(
    job_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User | None, Depends(get_optional_user)] = None,
) -> dict[str, str]:
    """Stop HLS transcoding job."""

    # Check job exists
    result = await session.execute(select(TranscodingJob).where(TranscodingJob.id == job_id))
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Transcoding job not found")

    # Stop transcoding process
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
    user: Annotated[User | None, Depends(get_optional_user)] = None,
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

    # Find the subtitle track
    subtitle_track = None
    for track in media_file.subtitle_tracks:
        if track.stream_index == stream_index:
            subtitle_track = track
            break

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
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read subtitle: {e}")
