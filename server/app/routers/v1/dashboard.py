"""Dashboard API endpoints for admin management (v1 with router-level authentication)."""

import shlex
from datetime import UTC, datetime, timedelta
from typing import Annotated

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_session
from app.dependencies import get_scheduler, require_admin
from app.models import (
    Library,
    LibraryCreate,
    LibrarySchema,
    LibraryUpdate,
    MediaFile,
    PlaybackSession,
    PlaybackSessionStatus,
    RecommendationRow,
    RecommendationRowCreate,
    RecommendationRowSchema,
    RecommendationRowUpdate,
    Settings,
    SettingsSchema,
    SettingsUpdate,
    TranscodingJob,
    User,
    UserCreate,
    UserRole,
    UserSchema,
    UserUpdate,
)
from app.services.directory_browser import DirectoryItem, browse_directory_items
from app.services.jobs import (
    JobExecutionRecord,
    JobState,
    get_job_history,
    get_job_state,
    get_job_states,
)
from app.services.profile_images import delete_profile_image, save_profile_image
from app.services.recommendation_row import validate_filter_criteria
from app.services.scanner import schedule_library_scan
from app.services.transcoder import get_transcoder
from app.services.transcoding.hardware import HardwareAccelerationStatus

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
    existing = await session.scalar(select(Library).where(Library.path == library_data.path))

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
        existing = await session.scalar(select(Library).where(Library.path == update_data.path))
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
    return browse_directory_items(path)


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


class StreamAccelerationSchema(BaseModel):
    """Detailed transcoding acceleration data for admins."""

    is_hardware: bool
    summary: str
    video_decode: str
    video_encode: str
    audio_encode: str | None = None
    device: str | None = None
    hw_output_format: str | None = None
    video_filters: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    ffmpeg_command: str | None = None


class StreamMediaTrackSchema(BaseModel):
    """Admin-friendly stream track detail."""

    label: str
    source_label: str
    target_label: str | None = None
    decision: str
    is_hardware: bool = False


class ActiveStreamSchema(BaseModel):
    """Admin view of an active playback/transcoding stream."""

    id: str
    user_id: int
    username: str
    media_file_id: int
    media_file_name: str | None = None
    media_file_path: str | None = None
    thumbnail_url: str | None = None
    duration: float | None = None
    play_method: str
    transcoding_type: str | None = None
    status: str
    is_paused: bool
    position_seconds: float
    progress_percent: float | None = None
    transcoding_job_id: str | None = None
    job_type: str | None = None
    job_status: str | None = None
    transcoded_duration: float | None = None
    current_fps: float | None = None
    current_bitrate: int | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    video: StreamMediaTrackSchema | None = None
    audio: StreamMediaTrackSchema | None = None
    subtitle: StreamMediaTrackSchema | None = None
    max_width: int | None = None
    max_height: int | None = None
    start_time: float | None = None
    started_at: datetime | None = None
    last_accessed_at: datetime | None = None
    last_heartbeat_at: datetime | None = None
    client_ip: str | None = None
    user_agent: str | None = None
    acceleration: StreamAccelerationSchema | None = None


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


@router.get("/streams", response_model=list[ActiveStreamSchema])
async def list_active_streams(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[ActiveStreamSchema]:
    """List active playback sessions across all users, including direct play."""
    active_cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=45)
    result = await session.execute(
        select(PlaybackSession, MediaFile, User, TranscodingJob)
        .join(MediaFile, MediaFile.id == PlaybackSession.media_file_id)
        .join(User, User.id == PlaybackSession.user_id)
        .join(TranscodingJob, TranscodingJob.id == PlaybackSession.transcoding_job_id, isouter=True)
        .options(
            selectinload(MediaFile.video_tracks),
            selectinload(MediaFile.audio_tracks),
            selectinload(MediaFile.subtitle_tracks),
        )
        .where(
            PlaybackSession.status == PlaybackSessionStatus.ACTIVE,
            PlaybackSession.last_heartbeat_at >= active_cutoff,
        )
        .order_by(PlaybackSession.last_heartbeat_at.desc(), PlaybackSession.started_at.desc())
    )

    streams = []
    for playback_session, media_file, user, job in result.all():
        duration = playback_session.duration_seconds or media_file.duration
        streams.append(
            ActiveStreamSchema(
                id=playback_session.id,
                user_id=user.id,
                username=user.username,
                media_file_id=playback_session.media_file_id,
                media_file_name=media_file.file_name if media_file else None,
                media_file_path=media_file.file_path if media_file else None,
                thumbnail_url=media_file.thumbnail_url if media_file else None,
                duration=duration,
                play_method=playback_session.play_method,
                transcoding_type=playback_session.transcoding_type,
                status=playback_session.status,
                is_paused=playback_session.is_paused,
                position_seconds=playback_session.position_seconds,
                progress_percent=_playback_progress(playback_session.position_seconds, duration),
                transcoding_job_id=job.id if job else None,
                job_type=job.type if job else None,
                job_status=job.status if job else None,
                transcoded_duration=job.transcoded_duration if job else None,
                current_fps=job.current_fps if job else None,
                current_bitrate=job.current_bitrate if job else media_file.bitrate,
                video_codec=job.video_codec if job else media_file.codec,
                audio_codec=job.audio_codec if job else None,
                video=_video_track_detail(media_file, playback_session, job),
                audio=_audio_track_detail(media_file, playback_session, job),
                subtitle=_subtitle_track_detail(media_file, playback_session),
                max_width=job.max_width if job else media_file.width,
                max_height=job.max_height if job else media_file.height,
                start_time=job.start_time if job else None,
                started_at=playback_session.started_at,
                last_accessed_at=job.last_accessed_at if job else None,
                last_heartbeat_at=playback_session.last_heartbeat_at,
                client_ip=playback_session.client_ip,
                user_agent=playback_session.user_agent,
                acceleration=analyze_stream_acceleration(job) if job else None,
            )
        )

    return streams


@router.delete("/streams/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def stop_active_stream(
    session_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    """Kick a playback session and stop its transcoder if one is attached."""
    playback_session = await session.get(PlaybackSession, session_id)
    if not playback_session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Playback session not found")

    playback_session.status = PlaybackSessionStatus.STOPPED_BY_ADMIN
    playback_session.stopped_reason = "admin"
    playback_session.ended_at = datetime.now(UTC).replace(tzinfo=None)

    if playback_session.transcoding_job_id:
        await get_transcoder().stop_job(playback_session.transcoding_job_id)

    await session.commit()


def _playback_progress(position: float, duration: float | None) -> float | None:
    if not duration or duration <= 0:
        return None
    return min(max((position / duration) * 100, 0.0), 100.0)


def _video_track_detail(
    media_file: MediaFile,
    playback_session: PlaybackSession,
    job: TranscodingJob | None,
) -> StreamMediaTrackSchema | None:
    track = media_file.video_tracks[0] if media_file.video_tracks else None
    if not track and not media_file.codec:
        return None

    resolution = _resolution_label(
        track.width if track else media_file.width, track.height if track else media_file.height
    )
    codec = (track.codec if track else media_file.codec) or "Unknown"
    profile = f" {track.profile}" if track and track.profile else ""
    bit_depth = f" {track.bit_depth}-bit" if track and track.bit_depth and track.bit_depth > 8 else ""
    source_label = " ".join(part for part in [resolution, f"({_codec_label(codec)}{profile}{bit_depth})"] if part)
    target_label = (
        None if _is_direct_video(playback_session.play_method, job) else _codec_label(job.video_codec if job else None)
    )
    acceleration = analyze_stream_acceleration(job) if job and target_label else None
    is_hardware = bool(acceleration and acceleration.is_hardware)
    return StreamMediaTrackSchema(
        label=source_label,
        source_label=source_label,
        target_label=target_label,
        decision=_stream_decision(playback_session.play_method, job, "video"),
        is_hardware=is_hardware,
    )


def _audio_track_detail(
    media_file: MediaFile,
    playback_session: PlaybackSession,
    job: TranscodingJob | None,
) -> StreamMediaTrackSchema | None:
    track = next(
        (item for item in media_file.audio_tracks if item.stream_index == playback_session.audio_stream_index),
        media_file.audio_tracks[0] if media_file.audio_tracks else None,
    )
    if not track:
        return None

    language = track.language or "Unknown"
    channels = f" {track.channels}.0" if track.channels else ""
    source_label = f"{language} ({_codec_label(track.codec)}{channels})"
    target_label = (
        None if _is_direct_audio(playback_session.play_method, job) else _codec_label(job.audio_codec if job else None)
    )
    return StreamMediaTrackSchema(
        label=source_label,
        source_label=source_label,
        target_label=target_label,
        decision=_stream_decision(playback_session.play_method, job, "audio"),
    )


def _subtitle_track_detail(media_file: MediaFile, playback_session: PlaybackSession) -> StreamMediaTrackSchema | None:
    if playback_session.subtitle_stream_index is None:
        return None

    track = next(
        (item for item in media_file.subtitle_tracks if item.stream_index == playback_session.subtitle_stream_index),
        None,
    )
    if not track:
        return None

    language = track.language or "Unknown"
    source_label = f"{language} ({_codec_label(track.codec)})"
    decision = "Burned in" if playback_session.play_method == "Transcode" else "Direct Stream"
    target_label = "Video burn-in" if decision == "Burned in" else "WEBVTT"
    return StreamMediaTrackSchema(
        label=source_label,
        source_label=source_label,
        target_label=target_label if decision == "Burned in" else None,
        decision=decision,
    )


def _resolution_label(width: int | None, height: int | None) -> str:
    if height and height >= 2160:
        return "4K"
    if height:
        return f"{height}p"
    if width:
        return f"{width}px"
    return ""


def _stream_decision(play_method: str, job: TranscodingJob | None, track_type: str) -> str:
    if play_method == "DirectPlay":
        return "Direct Play"
    if play_method == "DirectStream":
        return "Direct Stream"
    if not job:
        return play_method
    if track_type == "video" and job.video_codec == "copy":
        return "Direct Stream"
    if track_type == "audio" and job.audio_codec == "copy":
        return "Direct Stream"
    return "Transcode"


def _is_direct_video(play_method: str, job: TranscodingJob | None) -> bool:
    return play_method in {"DirectPlay", "DirectStream"} or not job or job.video_codec == "copy"


def _is_direct_audio(play_method: str, job: TranscodingJob | None) -> bool:
    return play_method in {"DirectPlay", "DirectStream"} or not job or job.audio_codec == "copy"


def _codec_label(codec: str | None) -> str:
    if not codec:
        return "Unknown"
    normalized = codec.lower().replace("_vaapi", "").replace("_nvenc", "").replace("_qsv", "").replace("_amf", "")
    labels = {
        "aac": "AAC",
        "ac3": "AC3",
        "eac3": "EAC3",
        "h264": "H264",
        "hevc": "HEVC",
        "h265": "HEVC",
        "libx264": "H264",
        "libx265": "HEVC",
        "opus": "OPUS",
        "srt": "SRT",
        "webvtt": "WEBVTT",
    }
    return labels.get(normalized, normalized.upper())


def analyze_stream_acceleration(job: TranscodingJob) -> StreamAccelerationSchema | None:
    """Parse the persisted FFmpeg command into an admin-friendly acceleration summary."""
    command = job.ffmpeg_command
    if not command:
        return None

    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()

    video_encoder = _value_after(tokens, "-c:v") or job.video_codec or "unknown"
    audio_encoder = _value_after(tokens, "-c:a") or job.audio_codec
    hwaccel = _value_after(tokens, "-hwaccel")
    hw_output_format = _value_after(tokens, "-hwaccel_output_format")
    vaapi_device = _value_after(tokens, "-vaapi_device")
    hw_device = _value_after(tokens, "-hwaccel_device")
    nvidia_gpu = _value_after(tokens, "-gpu")
    video_filters = [
        *_split_filters(_value_after(tokens, "-vf")),
        *_split_filters(_value_after(tokens, "-filter_complex")),
    ]

    is_video_copy = video_encoder == "copy" or job.video_codec == "copy"
    is_hardware_decode = hwaccel is not None
    is_hardware_encode = _is_hardware_video_encoder(video_encoder)
    notes: list[str] = []

    if is_video_copy:
        notes.append("Video stream is copied; no video decode or encode is needed.")
    elif is_hardware_decode and is_hardware_encode:
        notes.append("Video decode and encode are both running through hardware acceleration.")
    elif is_hardware_encode:
        notes.append("Video encode is hardware accelerated; source video decode is still on CPU.")
    else:
        notes.append("Video encode is using a software encoder.")

    if any("scale_vaapi" in item for item in video_filters):
        notes.append("Scaling is performed on the VAAPI device.")
    elif any(item.startswith("scale=") for item in video_filters):
        notes.append("Scaling is performed by a software filter.")
    if "hwupload" in video_filters:
        notes.append("Frames are uploaded from CPU memory to the hardware encoder.")
    if any("subtitles=" in item or "overlay" in item for item in video_filters):
        notes.append("Subtitle burn-in requires software filtering, so hardware decode may be disabled.")
    if audio_encoder == "copy":
        notes.append("Audio stream is copied.")
    elif audio_encoder:
        notes.append(f"Audio is encoded with {audio_encoder}.")

    return StreamAccelerationSchema(
        is_hardware=is_hardware_decode or is_hardware_encode,
        summary=_acceleration_summary(is_hardware_decode, is_hardware_encode, is_video_copy),
        video_decode="Not needed (copy)" if is_video_copy else _hwaccel_label(hwaccel),
        video_encode="Not needed (copy)" if is_video_copy else f"{_encoder_label(video_encoder)} ({video_encoder})",
        audio_encode=audio_encoder,
        device=vaapi_device
        or (f"GPU {hw_device}" if hw_device else None)
        or (f"NVIDIA GPU {nvidia_gpu}" if nvidia_gpu else None),
        hw_output_format=hw_output_format,
        video_filters=video_filters,
        notes=notes,
        ffmpeg_command=command,
    )


def _value_after(tokens: list[str], flag: str) -> str | None:
    try:
        index = tokens.index(flag)
    except ValueError:
        return None
    return tokens[index + 1] if index + 1 < len(tokens) else None


def _split_filters(filters: str | None) -> list[str]:
    if not filters:
        return []
    return [item.strip() for item in filters.replace(";", ",").split(",") if item.strip()]


def _is_hardware_video_encoder(encoder: str) -> bool:
    return encoder.endswith(("_vaapi", "_nvenc", "_qsv", "_amf", "_videotoolbox"))


def _acceleration_summary(hardware_decode: bool, hardware_encode: bool, video_copy: bool) -> str:
    if video_copy:
        return "Video copy"
    if hardware_decode and hardware_encode:
        return "Full hardware video path"
    if hardware_encode:
        return "Hardware video encode"
    return "Software video transcode"


def _encoder_label(encoder: str) -> str:
    if encoder.endswith("_vaapi"):
        return "VAAPI hardware encode"
    if encoder.endswith("_nvenc"):
        return "NVIDIA NVENC hardware encode"
    if encoder.endswith("_qsv"):
        return "Intel QSV hardware encode"
    if encoder.endswith("_amf"):
        return "AMD AMF hardware encode"
    if encoder.endswith("_videotoolbox"):
        return "VideoToolbox hardware encode"
    if encoder.startswith("lib"):
        return "Software encode"
    return "Encoder"


def _hwaccel_label(hwaccel: str | None) -> str:
    if hwaccel == "vaapi":
        return "VAAPI hardware decode"
    if hwaccel == "cuda":
        return "NVIDIA CUDA/NVDEC hardware decode"
    if hwaccel == "qsv":
        return "Intel QSV hardware decode"
    if hwaccel == "videotoolbox":
        return "VideoToolbox hardware decode"
    if hwaccel:
        return f"{hwaccel.upper()} hardware decode"
    return "Software CPU decode"


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


@router.post("/users", response_model=UserSchema, status_code=status.HTTP_201_CREATED)
async def create_user(
    user_data: UserCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    """Create a user account from the admin dashboard."""
    existing = await session.scalar(select(User).where(func.lower(User.username) == func.lower(user_data.username)))
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered",
        )

    email = _normalize_email(user_data.email)
    if email:
        existing_email = await session.scalar(select(User).where(User.email == email))
        if existing_email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered",
            )

    user = User(
        username=user_data.username,
        email=email,
        password=user_data.password,
        is_admin=_is_admin_payload(user_data.role, user_data.is_admin),
        is_active=True,
        language=user_data.language,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


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
    admin: Annotated[User, Depends(require_admin)],
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
    was_active_admin = user.is_admin and user.is_active

    if user_update.username is not None:
        existing = await session.scalar(
            select(User).where(
                func.lower(User.username) == func.lower(user_update.username),
                User.id != user_id,
            )
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already in use",
            )
        user.username = user_update.username

    if "email" in user_update.model_fields_set:
        email = _normalize_email(user_update.email)
        # Check if email is already taken by another user
        existing = await session.scalar(select(User).where(User.email == email, User.id != user_id))
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already in use",
            )
        user.email = email

    if user_update.password is not None:
        user.password = user_update.password

    if user_update.language is not None:
        user.language = user_update.language

    requested_admin = _requested_admin_flag(user_update.role, user_update.is_admin)
    if requested_admin is not None:
        if user_id == admin.id and not requested_admin:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot remove your own admin role",
            )
        user.is_admin = requested_admin

    if user_update.is_active is not None:
        if user_id == admin.id and not user_update.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot deactivate your own account",
            )
        user.is_active = user_update.is_active

    await ensure_active_admin_remains(session, user, was_active_admin=was_active_admin)

    user.updated_at = datetime.now(UTC).replace(tzinfo=None)
    await session.commit()
    await session.refresh(user)

    return user


@router.put("/users/{user_id}/profile-image", response_model=UserSchema)
async def upload_user_profile_image(
    user_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    image: Annotated[UploadFile, File()],
) -> User:
    """Upload or replace a user's profile image."""
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    previous_image_path = user.profile_image_path
    user.profile_image_path = await save_profile_image(user.id, image)
    user.updated_at = datetime.now(UTC).replace(tzinfo=None)
    await session.commit()
    await session.refresh(user)
    delete_profile_image(previous_image_path)
    return user


@router.delete("/users/{user_id}/profile-image", response_model=UserSchema)
async def delete_user_profile_image(
    user_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    """Remove a user's profile image."""
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    previous_image_path = user.profile_image_path
    user.profile_image_path = None
    user.updated_at = datetime.now(UTC).replace(tzinfo=None)
    await session.commit()
    await session.refresh(user)
    delete_profile_image(previous_image_path)
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

    await ensure_active_admin_remains(session, user, was_active_admin=user.is_admin and user.is_active)

    previous_image_path = user.profile_image_path
    await session.delete(user)
    await session.commit()
    delete_profile_image(previous_image_path)


def _normalize_email(email: str | None) -> str | None:
    if not email:
        return None
    normalized = email.strip()
    return normalized or None


def _is_admin_payload(role: UserRole, legacy_is_admin: bool) -> bool:
    return role == UserRole.ADMIN or legacy_is_admin


def _requested_admin_flag(role: UserRole | None, legacy_is_admin: bool | None) -> bool | None:
    if role is not None:
        return role == UserRole.ADMIN
    return legacy_is_admin


async def ensure_active_admin_remains(
    session: AsyncSession,
    user: User,
    *,
    was_active_admin: bool,
) -> None:
    """Prevent user mutations that would leave the server without an active admin."""
    if not was_active_admin or (user.is_admin and user.is_active):
        return

    remaining_admin_count = await session.scalar(
        select(func.count(User.id)).where(
            User.id != user.id,
            User.is_admin == True,  # noqa: E712
            User.is_active == True,  # noqa: E712
        )
    )
    if not remaining_admin_count:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one active admin is required",
        )

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
        select(RecommendationRow).where(RecommendationRow.library_id == library_id).order_by(RecommendationRow.name)
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
# Settings Management Endpoints (Admin Only)
# ============================================================================


@router.get("/hardware-transcoding", response_model=HardwareAccelerationStatus)
async def get_hardware_transcoding_status(
    session: Annotated[AsyncSession, Depends(get_session)],
    refresh: bool = Query(False, description="Force hardware capability detection to run again"),
) -> HardwareAccelerationStatus:
    """Get detected hardware transcoding devices and capabilities."""
    settings = await session.get(Settings, 1)
    transcoder = get_transcoder()
    transcoder.set_hardware_device(settings.hardware_transcoding_device if settings else "auto")
    return transcoder.refresh_hardware_status() if refresh else transcoder.hardware_status()


@router.get("/settings", response_model=SettingsSchema)
async def get_settings(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Settings:
    """Get application settings (admin only).

    Returns:
        Current application settings
    """
    settings = await session.get(Settings, 1)
    if not settings:
        # Create default settings if they don't exist
        settings = Settings()
        session.add(settings)
        await session.commit()
        await session.refresh(settings)
    return settings


@router.patch("/settings", response_model=SettingsSchema)
async def update_settings(
    update_data: SettingsUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
    scheduler: Annotated[AsyncIOScheduler, Depends(get_scheduler)],
) -> Settings:
    """Update application settings (admin only).

    Args:
        update_data: Settings update data
        session: Database session
        scheduler: APScheduler instance

    Returns:
        Updated settings

    Raises:
        HTTPException: If validation fails
    """
    from app.services.settings import update_scheduler_jobs

    settings = await session.get(Settings, 1)
    if not settings:
        # Create default settings if they don't exist
        settings = Settings()
        session.add(settings)
        await session.commit()
        await session.refresh(settings)

    # Update fields if provided
    if update_data.library_scan_interval_minutes is not None:
        if update_data.library_scan_interval_minutes < 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Library scan interval must be at least 1 minute",
            )
        settings.library_scan_interval_minutes = update_data.library_scan_interval_minutes

    if update_data.cleanup_schedule_hour is not None:
        if not 0 <= update_data.cleanup_schedule_hour <= 23:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cleanup schedule hour must be between 0 and 23",
            )
        settings.cleanup_schedule_hour = update_data.cleanup_schedule_hour

    if update_data.cleanup_schedule_minute is not None:
        if not 0 <= update_data.cleanup_schedule_minute <= 59:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cleanup schedule minute must be between 0 and 59",
            )
        settings.cleanup_schedule_minute = update_data.cleanup_schedule_minute

    if update_data.cleanup_grace_period_days is not None:
        if update_data.cleanup_grace_period_days < 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cleanup grace period must be at least 1 day",
            )
        settings.cleanup_grace_period_days = update_data.cleanup_grace_period_days

    if update_data.hardware_transcoding_device is not None:
        if not update_data.hardware_transcoding_device.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Hardware transcoding device cannot be empty",
            )
        settings.hardware_transcoding_device = update_data.hardware_transcoding_device.strip()

    session.add(settings)
    await session.commit()
    await session.refresh(settings)

    # Update scheduler jobs with new settings
    update_scheduler_jobs(scheduler, settings)
    get_transcoder().set_hardware_device(settings.hardware_transcoding_device)

    return settings
