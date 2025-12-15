"""Transcoding service for adaptive video streaming."""

import asyncio
import json
import logging
import os
import re
import secrets
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_maker
from app.models import (
    AudioTrack,
    MediaFile,
    SubtitleTrack,
    TranscodingFormat,
    TranscodingProfile,
    TranscodingSession,
    TranscodingStatus,
    VideoTrack,
)

logger = logging.getLogger(__name__)

# Default transcoding directory
TRANSCODING_DIR = Path("/tmp/ferelix-transcoding")
TRANSCODING_DIR.mkdir(parents=True, exist_ok=True)


def _can_extract_subtitle(codec: str) -> bool:
    """Check if subtitle codec can be extracted (not burned in)."""
    # Extractable subtitle formats
    extractable = {"srt", "ass", "ssa", "webvtt", "vtt", "subrip"}
    return codec.lower() in extractable


def _get_default_profile() -> dict[str, Any]:
    """Get default transcoding profile for broad compatibility."""
    return {
        "video_codec": "h264",
        "audio_codec": "aac",
        "container": "mp4",
        "max_video_bitrate": None,  # Use source bitrate
        "max_audio_bitrate": None,  # Use source bitrate
    }


async def check_media_compatibility(
    session: AsyncSession,
    media_file_id: int,
    video_codecs: list[str],
    audio_codecs: list[str],
    containers: list[str],
    subtitle_codecs: list[str] | None = None,
) -> dict[str, Any]:
    """Check if media file is compatible with client capabilities.

    Args:
        session: Database session
        media_file_id: Media file ID to check
        video_codecs: List of supported video codecs
        audio_codecs: List of supported audio codecs
        containers: List of supported container formats
        subtitle_codecs: List of supported subtitle formats (optional)

    Returns:
        Dictionary with compatibility information
    """
    # Fetch media file with tracks
    media_file = await session.get(MediaFile, media_file_id)
    if not media_file:
        return {
            "can_direct_play": False,
            "requires_transcoding": True,
            "reasons": ["Media file not found"],
        }

    reasons = []

    # Check container
    container = media_file.file_extension.lstrip(".")
    if container not in containers:
        reasons.append(f"Container format '{container}' not supported")

    # Check video codec (use first video track)
    video_tracks = await session.scalars(
        select(VideoTrack).where(VideoTrack.media_file_id == media_file_id)
    )
    video_tracks_list = list(video_tracks)

    if video_tracks_list:
        video_codec = video_tracks_list[0].codec
        if video_codec not in video_codecs:
            reasons.append(f"Video codec '{video_codec}' not supported")

    # Check audio codec (use first audio track)
    audio_tracks = await session.scalars(
        select(AudioTrack).where(AudioTrack.media_file_id == media_file_id)
    )
    audio_tracks_list = list(audio_tracks)

    if audio_tracks_list:
        audio_codec = audio_tracks_list[0].codec
        if audio_codec not in audio_codecs:
            reasons.append(f"Audio codec '{audio_codec}' not supported")

    can_direct_play = len(reasons) == 0

    return {
        "can_direct_play": can_direct_play,
        "requires_transcoding": not can_direct_play,
        "reasons": reasons,
    }


async def create_transcoding_session(
    session: AsyncSession,
    media_file_id: int,
    user_id: int | None = None,
    output_format: TranscodingFormat = TranscodingFormat.HLS,
    audio_track_index: int | None = None,
    subtitle_track_index: int | None = None,
    profile: dict[str, Any] | None = None,
) -> TranscodingSession:
    """Create a new transcoding session.

    Args:
        session: Database session
        media_file_id: Media file to transcode
        user_id: Optional user ID
        output_format: Output format (HLS or progressive)
        audio_track_index: Optional audio track index
        subtitle_track_index: Optional subtitle track index
        profile: Optional transcoding profile

    Returns:
        Created transcoding session
    """
    # Generate unique session ID
    session_id = secrets.token_urlsafe(32)

    # Use default profile if not provided
    if profile is None:
        profile = _get_default_profile()

    # Determine if subtitles need to be burned in
    burn_subtitles = False
    if subtitle_track_index is not None:
        subtitle_track = await session.scalar(
            select(SubtitleTrack).where(
                SubtitleTrack.media_file_id == media_file_id,
                SubtitleTrack.stream_index == subtitle_track_index,
            )
        )
        if subtitle_track:
            burn_subtitles = not _can_extract_subtitle(subtitle_track.codec)

    # Create session record
    transcode_session = TranscodingSession(
        session_id=session_id,
        media_file_id=media_file_id,
        user_id=user_id,
        output_format=output_format,
        video_codec=profile.get("video_codec"),
        audio_codec=profile.get("audio_codec"),
        audio_track_index=audio_track_index,
        subtitle_track_index=subtitle_track_index,
        burn_subtitles=burn_subtitles,
        status=TranscodingStatus.PENDING,
        progress=0.0,
    )

    session.add(transcode_session)
    await session.commit()
    await session.refresh(transcode_session)

    return transcode_session


def _build_ffmpeg_command(
    input_file: Path,
    output_path: Path,
    video_codec: str,
    audio_codec: str,
    output_format: TranscodingFormat,
    audio_track_index: int | None = None,
    subtitle_track_index: int | None = None,
    burn_subtitles: bool = False,
) -> list[str]:
    """Build FFmpeg command for transcoding.

    Args:
        input_file: Input file path
        output_path: Output file/directory path
        video_codec: Target video codec
        audio_codec: Target audio codec
        output_format: Output format (HLS or progressive)
        audio_track_index: Optional audio track stream index
        subtitle_track_index: Optional subtitle track stream index
        burn_subtitles: Whether to burn subtitles into video

    Returns:
        FFmpeg command as list of arguments
    """
    cmd = [
        "ffmpeg",
        "-i",
        str(input_file),
        "-y",  # Overwrite output files
    ]

    # Map audio track if specified
    if audio_track_index is not None:
        cmd.extend(["-map", "0:v:0"])  # First video stream
        cmd.extend(["-map", f"0:a:{audio_track_index}"])  # Specific audio stream
    else:
        cmd.extend(["-map", "0:v:0"])  # First video stream
        cmd.extend(["-map", "0:a:0"])  # First audio stream

    # Video codec settings
    if video_codec == "h264":
        cmd.extend(["-c:v", "libx264", "-preset", "veryfast", "-crf", "23"])
    elif video_codec == "hevc":
        cmd.extend(["-c:v", "libx265", "-preset", "medium", "-crf", "28"])
    elif video_codec == "vp9":
        cmd.extend(["-c:v", "libvpx-vp9", "-crf", "30", "-b:v", "0"])
    else:
        cmd.extend(["-c:v", "copy"])  # Copy if unknown

    # Audio codec settings
    if audio_codec == "aac":
        cmd.extend(["-c:a", "aac", "-b:a", "128k"])
    elif audio_codec == "mp3":
        cmd.extend(["-c:a", "libmp3lame", "-b:a", "128k"])
    elif audio_codec == "opus":
        cmd.extend(["-c:a", "libopus", "-b:a", "128k"])
    else:
        cmd.extend(["-c:a", "copy"])  # Copy if unknown

    # Handle subtitles
    if subtitle_track_index is not None:
        if burn_subtitles:
            # Burn subtitles into video
            cmd.extend(["-vf", f"subtitles={input_file}:si={subtitle_track_index}"])
        else:
            # Extract/copy subtitles
            cmd.extend(["-map", f"0:s:{subtitle_track_index}"])
            cmd.extend(["-c:s", "mov_text"])  # For MP4 container

    # Output format specific settings
    if output_format == TranscodingFormat.HLS:
        # HLS output
        manifest_path = output_path / "playlist.m3u8"
        cmd.extend(
            [
                "-f",
                "hls",
                "-hls_time",
                "4",  # 4 second segments
                "-hls_list_size",
                "0",  # Keep all segments in playlist
                "-hls_segment_filename",
                str(output_path / "segment_%03d.ts"),
                str(manifest_path),
            ]
        )
    else:
        # Progressive download (single file)
        cmd.extend(["-movflags", "+faststart", str(output_path / "output.mp4")])

    return cmd


async def _monitor_ffmpeg_progress(
    process: asyncio.subprocess.Process,
    session_id: str,
    duration: float,
) -> None:
    """Monitor FFmpeg progress and update database.

    Args:
        process: FFmpeg process
        session_id: Transcoding session ID
        duration: Video duration in seconds
    """
    # Pattern to extract progress from FFmpeg output
    time_pattern = re.compile(r"time=(\d{2}):(\d{2}):(\d{2}\.\d{2})")

    async with async_session_maker() as db_session:
        while True:
            if process.stderr is None:
                break

            line = await process.stderr.readline()
            if not line:
                break

            line_str = line.decode("utf-8", errors="ignore")

            # Try to extract progress
            match = time_pattern.search(line_str)
            if match and duration > 0:
                hours, minutes, seconds = match.groups()
                current_time = (
                    int(hours) * 3600 + int(minutes) * 60 + float(seconds)
                )
                progress = min((current_time / duration) * 100, 100.0)

                # Update progress in database
                transcode_session = await db_session.scalar(
                    select(TranscodingSession).where(
                        TranscodingSession.session_id == session_id
                    )
                )
                if transcode_session:
                    transcode_session.progress = progress
                    await db_session.commit()


async def start_transcoding(
    session_id: str,
) -> bool:
    """Start transcoding process for a session.

    Args:
        session_id: Transcoding session ID

    Returns:
        True if transcoding started successfully, False otherwise
    """
    async with async_session_maker() as session:
        # Get transcoding session
        transcode_session = await session.scalar(
            select(TranscodingSession).where(
                TranscodingSession.session_id == session_id
            )
        )

        if not transcode_session:
            logger.error(f"Transcoding session {session_id} not found")
            return False

        # Get media file
        media_file = await session.get(MediaFile, transcode_session.media_file_id)
        if not media_file:
            logger.error(
                f"Media file {transcode_session.media_file_id} not found for session {session_id}"
            )
            transcode_session.status = TranscodingStatus.FAILED
            transcode_session.error_message = "Media file not found"
            await session.commit()
            return False

        # Create output directory
        output_dir = TRANSCODING_DIR / session_id
        output_dir.mkdir(parents=True, exist_ok=True)

        # Build FFmpeg command
        try:
            cmd = _build_ffmpeg_command(
                input_file=Path(media_file.file_path),
                output_path=output_dir,
                video_codec=transcode_session.video_codec or "h264",
                audio_codec=transcode_session.audio_codec or "aac",
                output_format=transcode_session.output_format,
                audio_track_index=transcode_session.audio_track_index,
                subtitle_track_index=transcode_session.subtitle_track_index,
                burn_subtitles=transcode_session.burn_subtitles,
            )

            logger.info(f"Starting transcoding for session {session_id}")
            logger.debug(f"FFmpeg command: {' '.join(cmd)}")

            # Start FFmpeg process
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            # Update session with process ID and status
            transcode_session.status = TranscodingStatus.IN_PROGRESS
            transcode_session.process_id = process.pid
            transcode_session.output_path = str(output_dir)

            if transcode_session.output_format == TranscodingFormat.HLS:
                transcode_session.manifest_path = str(output_dir / "playlist.m3u8")

            await session.commit()

            # Monitor progress in background
            duration = media_file.duration or 0
            asyncio.create_task(_monitor_ffmpeg_progress(process, session_id, duration))

            # Wait for process to complete
            await process.wait()

            # Update final status
            if process.returncode == 0:
                transcode_session.status = TranscodingStatus.COMPLETED
                transcode_session.progress = 100.0
                logger.info(f"Transcoding completed for session {session_id}")
            else:
                transcode_session.status = TranscodingStatus.FAILED
                stderr_output = (
                    await process.stderr.read() if process.stderr else b""
                )
                error_msg = stderr_output.decode("utf-8", errors="ignore")[-500:]
                transcode_session.error_message = f"FFmpeg error: {error_msg}"
                logger.error(
                    f"Transcoding failed for session {session_id}: {error_msg}"
                )

            await session.commit()
            return process.returncode == 0

        except Exception as e:
            logger.exception(f"Error starting transcoding for session {session_id}: {e}")
            transcode_session.status = TranscodingStatus.FAILED
            transcode_session.error_message = str(e)
            await session.commit()
            return False


async def get_transcoding_session(
    session: AsyncSession, session_id: str
) -> TranscodingSession | None:
    """Get transcoding session by session ID.

    Args:
        session: Database session
        session_id: Transcoding session ID

    Returns:
        Transcoding session or None if not found
    """
    return await session.scalar(
        select(TranscodingSession).where(TranscodingSession.session_id == session_id)
    )


async def update_last_accessed(session: AsyncSession, session_id: str) -> None:
    """Update last accessed timestamp for a transcoding session.

    Args:
        session: Database session
        session_id: Transcoding session ID
    """
    transcode_session = await get_transcoding_session(session, session_id)
    if transcode_session:
        transcode_session.last_accessed_at = datetime.now(UTC)
        await session.commit()


async def cleanup_session(session: AsyncSession, session_id: str) -> bool:
    """Cleanup a transcoding session and its files.

    Args:
        session: Database session
        session_id: Transcoding session ID

    Returns:
        True if cleanup was successful
    """
    transcode_session = await get_transcoding_session(session, session_id)
    if not transcode_session:
        return False

    # Delete output files
    if transcode_session.output_path:
        output_dir = Path(transcode_session.output_path)
        if output_dir.exists():
            try:
                import shutil

                shutil.rmtree(output_dir)
                logger.info(f"Cleaned up transcoding files for session {session_id}")
            except Exception as e:
                logger.error(f"Error cleaning up files for session {session_id}: {e}")

    # Delete session from database
    await session.delete(transcode_session)
    await session.commit()

    return True


async def cleanup_stale_sessions(max_age_hours: int = 24) -> int:
    """Cleanup transcoding sessions that haven't been accessed recently.

    Args:
        max_age_hours: Maximum age in hours before cleanup

    Returns:
        Number of sessions cleaned up
    """
    from datetime import timedelta

    async with async_session_maker() as session:
        cutoff_time = datetime.now(UTC) - timedelta(hours=max_age_hours)

        # Find stale sessions
        result = await session.execute(
            select(TranscodingSession).where(
                TranscodingSession.last_accessed_at < cutoff_time
            )
        )
        stale_sessions = result.scalars().all()

        count = 0
        for transcode_session in stale_sessions:
            try:
                await cleanup_session(session, transcode_session.session_id)
                count += 1
            except Exception as e:
                logger.error(
                    f"Error cleaning up session {transcode_session.session_id}: {e}"
                )

        logger.info(f"Cleaned up {count} stale transcoding sessions")
        return count
