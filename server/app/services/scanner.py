"""Media library scanner service."""

import json
import logging
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from static_ffmpeg import run

from app.database import async_session_maker
from app.models import AudioTrack, Library, MediaFile, SubtitleTrack, VideoTrack

logger = logging.getLogger(__name__)

# Supported video file extensions
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v", ".flv", ".wmv"}

# Get ffprobe path from static-ffmpeg
def _get_ffprobe_path() -> str:
    """Get the path to the ffprobe binary from static-ffmpeg."""
    try:
        # static_ffmpeg.run returns tuple (ffmpeg_path, ffprobe_path)
        _, ffprobe_path = run.get_or_fetch_platform_executables_else_raise()
        return ffprobe_path
    except Exception as e:
        logger.error(f"Failed to get ffprobe from static-ffmpeg: {e}")
        # Fallback to system ffprobe (for backwards compatibility during transition)
        return "ffprobe"


def _parse_fps(r_frame_rate: str | None) -> float | None:
    """Parse frame rate from ffprobe format (e.g., '30/1' or '30000/1001')."""
    if not r_frame_rate or "/" not in str(r_frame_rate):
        return None
    try:
        parts = str(r_frame_rate).split("/")
        if len(parts) == 2:
            numerator = float(parts[0])
            denominator = float(parts[1])
            if denominator != 0:
                return numerator / denominator
    except ValueError, ZeroDivisionError:
        pass
    return None


def _parse_hdr_metadata(side_data_list: list) -> dict:
    """Parse HDR metadata from ffprobe side data."""
    hdr_info = {}

    for side_data in side_data_list:
        side_type = side_data.get("side_data_type")

        # Mastering Display Color Volume
        if side_type == "Mastering display metadata":
            if "max_luminance" in side_data:
                # Convert from rational format "10000000/10000" to int
                max_lum = side_data["max_luminance"]
                if "/" in str(max_lum):
                    num, den = map(float, str(max_lum).split("/"))
                    hdr_info["max_luminance"] = int(num / den) if den != 0 else None
                else:
                    hdr_info["max_luminance"] = int(float(max_lum))

            if "min_luminance" in side_data:
                min_lum = side_data["min_luminance"]
                if "/" in str(min_lum):
                    num, den = map(float, str(min_lum).split("/"))
                    hdr_info["min_luminance"] = num / den if den != 0 else None
                else:
                    hdr_info["min_luminance"] = float(min_lum)

        # Content Light Level
        elif side_type == "Content light level metadata":
            if "max_content" in side_data:
                hdr_info["max_cll"] = int(side_data["max_content"])
            if "max_average" in side_data:
                hdr_info["max_fall"] = int(side_data["max_average"])

    return hdr_info


def _parse_bit_depth(pix_fmt: str | None) -> int | None:
    """Extract bit depth from pixel format (e.g., yuv420p -> 8, yuv420p10le -> 10)."""
    if not pix_fmt:
        return None

    # Common patterns for bit depth in pixel format names
    if "10le" in pix_fmt or "10be" in pix_fmt or "p010" in pix_fmt:
        return 10
    elif "12le" in pix_fmt or "12be" in pix_fmt or "p012" in pix_fmt:
        return 12
    elif "16le" in pix_fmt or "16be" in pix_fmt or "p016" in pix_fmt:
        return 16
    else:
        # Default to 8-bit for most common formats
        return 8


def extract_video_metadata(file_path: Path) -> dict:  # noqa: C901
    """Extract video metadata using ffprobe.

    Returns a dictionary with duration, width, height, codec, bitrate,
    and track information (video_tracks, audio_tracks, subtitle_tracks).
    """
    try:
        ffprobe_path = _get_ffprobe_path()
        result = subprocess.run(
            [
                ffprobe_path,
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(file_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            logger.warning(f"ffprobe failed for {file_path}: {result.stderr}")
            return {}

        data = json.loads(result.stdout)

        metadata = {}

        # Extract format information
        format_info = data.get("format", {})
        if "duration" in format_info:
            metadata["duration"] = float(format_info["duration"])
        if "bit_rate" in format_info:
            metadata["bitrate"] = int(format_info["bit_rate"])

        # Extract video tracks
        video_tracks = []
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                # Parse HDR metadata from side data
                hdr_info = _parse_hdr_metadata(stream.get("side_data_list", []))

                track = {
                    "stream_index": stream.get("index"),
                    "codec": stream.get("codec_name"),
                    "width": stream.get("width"),
                    "height": stream.get("height"),
                    "bitrate": stream.get("bit_rate"),
                    "fps": _parse_fps(stream.get("r_frame_rate")),
                    "language": stream.get("tags", {}).get("language"),
                    "title": stream.get("tags", {}).get("title"),
                    "is_default": stream.get("disposition", {}).get("default", 0) == 1,
                    # Enhanced metadata for transcoding decisions
                    "profile": stream.get("profile"),
                    "level": stream.get("level"),
                    "pixel_format": stream.get("pix_fmt"),
                    "bit_depth": _parse_bit_depth(stream.get("pix_fmt")),
                    "color_range": stream.get("color_range"),
                    "color_space": stream.get("color_space"),
                    "color_primaries": stream.get("color_primaries"),
                    "color_transfer": stream.get("color_trc"),
                    # HDR metadata
                    "max_luminance": hdr_info.get("max_luminance"),
                    "min_luminance": hdr_info.get("min_luminance"),
                    "max_cll": hdr_info.get("max_cll"),
                    "max_fall": hdr_info.get("max_fall"),
                }
                video_tracks.append(track)

        # Extract audio tracks
        audio_tracks = []
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "audio":
                track = {
                    "stream_index": stream.get("index"),
                    "codec": stream.get("codec_name"),
                    "language": stream.get("tags", {}).get("language"),
                    "title": stream.get("tags", {}).get("title"),
                    "channels": stream.get("channels"),
                    "bitrate": stream.get("bit_rate"),
                    "is_default": stream.get("disposition", {}).get("default", 0) == 1,
                    "sample_rate": stream.get("sample_rate"),
                }
                audio_tracks.append(track)

        # Extract subtitle tracks
        subtitle_tracks = []
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "subtitle":
                track = {
                    "stream_index": stream.get("index"),
                    "codec": stream.get("codec_name"),
                    "language": stream.get("tags", {}).get("language"),
                    "title": stream.get("tags", {}).get("title"),
                    "is_forced": stream.get("disposition", {}).get("forced", 0) == 1,
                    "is_default": stream.get("disposition", {}).get("default", 0) == 1,
                }
                subtitle_tracks.append(track)

        # Keep legacy fields for compatibility (use first video track)
        if video_tracks:
            first_video = video_tracks[0]
            if first_video.get("width"):
                metadata["width"] = int(first_video["width"])
            if first_video.get("height"):
                metadata["height"] = int(first_video["height"])
            if first_video.get("codec"):
                metadata["codec"] = first_video["codec"]

        metadata["video_tracks"] = video_tracks
        metadata["audio_tracks"] = audio_tracks
        metadata["subtitle_tracks"] = subtitle_tracks

        return metadata

    except subprocess.TimeoutExpired:
        logger.error(f"ffprobe timeout for {file_path}")
        return {}
    except json.JSONDecodeError:
        logger.error(f"Failed to parse ffprobe output for {file_path}")
        return {}
    except Exception as e:
        logger.error(f"Error extracting metadata for {file_path}: {e}")
        return {}


async def _update_media_tracks(session: AsyncSession, media_file: MediaFile, metadata: dict) -> None:
    """Create or update track records for a media file.

    Args:
        session: Database session
        media_file: MediaFile instance
        metadata: Metadata dictionary with video_tracks, audio_tracks, subtitle_tracks
    """
    # Delete existing tracks
    video_tracks_to_delete = await session.scalars(select(VideoTrack).where(VideoTrack.media_file_id == media_file.id))
    for track in video_tracks_to_delete:
        await session.delete(track)

    audio_tracks_to_delete = await session.scalars(select(AudioTrack).where(AudioTrack.media_file_id == media_file.id))
    for track in audio_tracks_to_delete:
        await session.delete(track)

    subtitle_tracks_to_delete = await session.scalars(
        select(SubtitleTrack).where(SubtitleTrack.media_file_id == media_file.id)
    )
    for track in subtitle_tracks_to_delete:
        await session.delete(track)

    # Create video tracks
    for track_data in metadata.get("video_tracks", []):
        video_track = VideoTrack(
            media_file_id=media_file.id,
            stream_index=track_data.get("stream_index", 0),
            codec=track_data.get("codec", "unknown"),
            width=track_data.get("width"),
            height=track_data.get("height"),
            bitrate=track_data.get("bitrate"),
            fps=track_data.get("fps"),
            language=track_data.get("language"),
            title=track_data.get("title"),
            is_default=track_data.get("is_default", False),
            # Enhanced metadata
            profile=track_data.get("profile"),
            level=track_data.get("level"),
            pixel_format=track_data.get("pixel_format"),
            bit_depth=track_data.get("bit_depth"),
            color_range=track_data.get("color_range"),
            color_space=track_data.get("color_space"),
            color_primaries=track_data.get("color_primaries"),
            color_transfer=track_data.get("color_transfer"),
            max_luminance=track_data.get("max_luminance"),
            min_luminance=track_data.get("min_luminance"),
            max_cll=track_data.get("max_cll"),
            max_fall=track_data.get("max_fall"),
        )
        session.add(video_track)

    # Create audio tracks
    for track_data in metadata.get("audio_tracks", []):
        audio_track = AudioTrack(
            media_file_id=media_file.id,
            stream_index=track_data.get("stream_index", 0),
            codec=track_data.get("codec", "unknown"),
            language=track_data.get("language"),
            title=track_data.get("title"),
            channels=track_data.get("channels"),
            bitrate=track_data.get("bitrate"),
            is_default=track_data.get("is_default", False),
            sample_rate=track_data.get("sample_rate"),
        )
        session.add(audio_track)

    # Create subtitle tracks
    for track_data in metadata.get("subtitle_tracks", []):
        subtitle_track = SubtitleTrack(
            media_file_id=media_file.id,
            stream_index=track_data.get("stream_index", 0),
            codec=track_data.get("codec", "unknown"),
            language=track_data.get("language"),
            title=track_data.get("title"),
            is_forced=track_data.get("is_forced", False),
            is_default=track_data.get("is_default", False),
        )
        session.add(subtitle_track)


async def scan_library_path(  # noqa: C901
    session: AsyncSession, library_path: Library, job_id: str | None = None
) -> dict[str, int | bool]:
    """Scan a library path for video files and update the database.

    Args:
        session: Database session
        library_path: Library to scan
        job_id: Optional job ID for progress tracking and cancellation

    Returns:
        Statistics about the scan: new, updated, deleted, restored files, and cancelled flag
    """
    from app.services.jobs import (
        is_cancellation_requested,
        mark_job_cancelled,
        update_job_progress,
    )

    path = Path(library_path.path)
    if not path.exists() or not path.is_dir():
        logger.warning(f"Library path does not exist or is not a directory: {path}")
        return {"new": 0, "updated": 0, "deleted": 0, "restored": 0, "cancelled": False}

    new_files_count = 0
    updated_files_count = 0
    restored_files_count = 0
    scanned_paths: set[str] = set()
    batch_size = 10  # Commit every 10 files
    pending_changes = 0
    was_cancelled = False

    logger.info(f"Scanning library path: {path}")

    # First pass: Count video files for progress tracking
    video_files = []
    logger.info("Counting video files...")
    for root, dirs, files in os.walk(path):
        # Check for cancellation during counting
        if job_id and is_cancellation_requested(job_id):
            logger.info("Cancellation requested during file counting")
            was_cancelled = True
            if job_id:
                mark_job_cancelled(job_id)
            return {
                "new": 0,
                "updated": 0,
                "deleted": 0,
                "restored": 0,
                "cancelled": True,
            }

        for file_name in files:
            file_path = Path(root) / file_name
            file_extension = file_path.suffix.lower()

            # Check if it's a video file
            if file_extension in VIDEO_EXTENSIONS:
                video_files.append((file_path, file_name, file_extension))

    files_total = len(video_files)
    logger.info(f"Found {files_total} video files to process")

    # Update progress with total count
    if job_id:
        update_job_progress(job_id, files_total=files_total, files_processed=0)

    # Second pass: Process video files with progress tracking
    for idx, (file_path, file_name, file_extension) in enumerate(video_files):
        # Check for cancellation before processing each file
        if job_id and is_cancellation_requested(job_id):
            logger.info(f"Cancellation requested at file {idx + 1}/{files_total}")
            was_cancelled = True
            # Commit any pending changes before exiting
            if pending_changes > 0:
                await session.commit()
                logger.info(f"Committed {pending_changes} pending changes before cancellation")
            if job_id:
                mark_job_cancelled(job_id)
            break

        file_path_str = str(file_path)
        scanned_paths.add(file_path_str)

        # Update progress with current file
        if job_id:
            update_job_progress(job_id, files_processed=idx, current_file=file_path_str)

        # Check if file already exists in database
        existing_file = await session.scalar(select(MediaFile).where(MediaFile.file_path == file_path_str))

        if existing_file:
            # Check if file was previously marked as deleted (restored!)
            if existing_file.deleted_at is not None:
                logger.info(f"File restored: {file_path}")
                existing_file.deleted_at = None
                restored_files_count += 1
            else:
                updated_files_count += 1

            # Extract metadata and update tracks
            metadata = extract_video_metadata(file_path)
            await _update_media_tracks(session, existing_file, metadata)

            # Update scanned_at timestamp
            existing_file.scanned_at = datetime.now(UTC)
            session.add(existing_file)
            pending_changes += 1
        else:
            # Extract metadata for new file
            logger.info(f"Processing new file: {file_path}")
            metadata = extract_video_metadata(file_path)

            # Create new MediaFile entry
            media_file = MediaFile(
                file_path=file_path_str,
                file_name=file_name,
                file_size=file_path.stat().st_size,
                file_extension=file_extension,
                duration=metadata.get("duration"),
                width=metadata.get("width"),
                height=metadata.get("height"),
                codec=metadata.get("codec"),
                bitrate=metadata.get("bitrate"),
            )

            session.add(media_file)
            # Flush to get the ID
            await session.flush()

            # Create tracks
            await _update_media_tracks(session, media_file, metadata)

            new_files_count += 1
            pending_changes += 1

        # Batch commit every N files
        if pending_changes >= batch_size:
            await session.commit()
            logger.debug(f"Batch commit: {pending_changes} changes committed")
            pending_changes = 0

    # Update final progress
    if job_id and not was_cancelled:
        update_job_progress(job_id, files_processed=files_total, current_file=None)

    # Commit any remaining changes
    if pending_changes > 0:
        await session.commit()
        logger.debug(f"Final commit: {pending_changes} changes committed")

    # Find files in database that weren't scanned (soft delete them)
    # Only do this if scan wasn't cancelled
    deleted_files_count = 0
    if not was_cancelled:
        library_files = await session.scalars(
            select(MediaFile).where(
                MediaFile.file_path.startswith(str(path)),
                MediaFile.deleted_at.is_(None),
            )
        )

        now = datetime.now(UTC)
        for db_file in library_files:
            if db_file.file_path not in scanned_paths:
                logger.info(f"File missing, marking as deleted: {db_file.file_path}")
                db_file.deleted_at = now
                session.add(db_file)
                deleted_files_count += 1

        # Final commit for deletions
        if deleted_files_count > 0:
            await session.commit()

    stats = {
        "new": new_files_count,
        "updated": updated_files_count,
        "deleted": deleted_files_count,
        "restored": restored_files_count,
        "cancelled": was_cancelled,
    }

    if was_cancelled:
        logger.info(
            f"Scan cancelled for {path}: {new_files_count} new, {updated_files_count} updated, "
            f"{restored_files_count} restored (before cancellation)"
        )
    else:
        logger.info(
            f"Scan complete for {path}: {new_files_count} new, {updated_files_count} updated, "
            f"{deleted_files_count} deleted, {restored_files_count} restored"
        )

    return stats


async def scan_all_libraries(
    scheduler: AsyncIOScheduler | None = None,
) -> dict[str, int]:
    """Scan all enabled library paths by spawning individual per-library scan jobs.

    Args:
        scheduler: Optional scheduler instance to spawn per-library jobs

    Returns:
        Statistics about scheduled jobs (count of libraries to scan).
    """
    async with async_session_maker() as session:
        # Get all enabled library paths
        library_paths = await session.scalars(select(Library).where(Library.enabled))
        libraries_list = list(library_paths)

        if not libraries_list:
            logger.info("No library paths configured for scanning")
            return {"libraries_scheduled": 0}

        # If scheduler is provided, spawn per-library scan jobs
        if scheduler:
            logger.info(f"Scheduling scans for {len(libraries_list)} libraries")
            for library in libraries_list:
                schedule_library_scan(scheduler, library.id, library.name)
            logger.info(f"Scheduled {len(libraries_list)} library scan jobs")
            return {"libraries_scheduled": len(libraries_list)}
        else:
            # Fallback: scan directly (for backwards compatibility or if no scheduler)
            logger.warning("No scheduler provided to scan_all_libraries, scanning directly (not recommended)")
            total_stats = {"new": 0, "updated": 0, "deleted": 0, "restored": 0}
            for library_path in libraries_list:
                stats = await scan_library_path(session, library_path)
                for key in total_stats:
                    total_stats[key] += stats.get(key, 0)

            logger.info(
                f"Total scan results: {total_stats['new']} new, {total_stats['updated']} updated, "
                f"{total_stats['deleted']} deleted, {total_stats['restored']} restored"
            )
            return total_stats


async def scan_library_job(
    library_id: int, library_name: str | None = None, job_id: str | None = None
) -> dict[str, int | bool]:
    """Wrapper for scanning a single library (used by one-off jobs).

    Args:
        library_id: Library ID to scan
        library_name: Library name - used for display purposes only
        job_id: Job ID for progress tracking and cancellation

    Returns:
        Scan statistics dictionary

    Raises:
        ValueError: If library not found
    """
    async with async_session_maker() as session:
        library = await session.get(Library, library_id)
        if not library:
            raise ValueError(f"Library {library_id} not found")

        logger.info(f"Starting scan job for library {library_id}: {library.path}")
        stats = await scan_library_path(session, library, job_id)
        logger.info(f"Library scan job completed: {stats}")
        return stats


def schedule_library_scan(scheduler: AsyncIOScheduler, library_id: int, library_name: str | None = None) -> str:
    """Create a one-off job to scan a specific library.

    Args:
        scheduler: APScheduler instance
        library_id: Library ID to scan
        library_name: Library name for display purposes

    Returns:
        Job ID for tracking
    """
    timestamp = int(datetime.now(UTC).timestamp())
    job_id = f"scan_library_{library_id}_{timestamp}"

    scheduler.add_job(
        func=scan_library_job,
        trigger="date",
        run_date=datetime.now(UTC),
        id=job_id,
        kwargs={
            "library_id": library_id,
            "library_name": library_name,
            "job_id": job_id,
        },
        name=f"Library {library_id} Scan",
    )

    # Ensure state is initialized with library name immediately after job creation
    # This prevents the state from being created with just the ID
    from app.services.jobs import _ensure_state

    state = _ensure_state(job_id, scheduler)
    if library_name and state.fallback_name == f"Library Scanner: {library_id}":
        # Update state with library name if it was created with just the ID
        state.fallback_name = f"Library Scanner: {library_name}"

    logger.info(f"Scheduled one-off scan job {job_id} for library {library_id}")
    return job_id


async def cleanup_deleted_media(grace_period_days: int = 30) -> int:
    """Permanently delete media files marked as deleted beyond grace period.

    Args:
        grace_period_days: Number of days to keep deleted files before permanent deletion

    Returns:
        Number of files permanently deleted
    """
    async with async_session_maker() as session:
        cutoff_date = datetime.now(UTC) - timedelta(days=grace_period_days)

        # Find all files marked as deleted before the cutoff date
        result = await session.execute(
            select(MediaFile).where(MediaFile.deleted_at.isnot(None), MediaFile.deleted_at < cutoff_date)
        )
        files_to_delete = result.scalars().all()

        if not files_to_delete:
            logger.info("No deleted media files to clean up")
            return 0

        count = len(files_to_delete)
        logger.info(f"Cleaning up {count} deleted media files older than {grace_period_days} days")

        # Delete the files
        for file in files_to_delete:
            await session.delete(file)

        await session.commit()
        logger.info(f"Permanently deleted {count} media files")
        return count
