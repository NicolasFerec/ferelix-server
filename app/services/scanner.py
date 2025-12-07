"""Media library scanner service."""

import json
import logging
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_maker
from app.models import LibraryPath, MediaFile

logger = logging.getLogger(__name__)

# Supported video file extensions
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v", ".flv", ".wmv"}


def extract_video_metadata(file_path: Path) -> dict:
    """Extract video metadata using ffprobe.

    Returns a dictionary with duration, width, height, codec, and bitrate.
    """
    try:
        result = subprocess.run(
            [
                "ffprobe",
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

        # Find video stream
        video_stream = None
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                video_stream = stream
                break

        metadata = {}

        # Extract format information
        format_info = data.get("format", {})
        if "duration" in format_info:
            metadata["duration"] = float(format_info["duration"])
        if "bit_rate" in format_info:
            metadata["bitrate"] = int(format_info["bit_rate"])

        # Extract video stream information
        if video_stream:
            if "width" in video_stream:
                metadata["width"] = int(video_stream["width"])
            if "height" in video_stream:
                metadata["height"] = int(video_stream["height"])
            if "codec_name" in video_stream:
                metadata["codec"] = video_stream["codec_name"]

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


async def scan_library_path(session: AsyncSession, library_path: LibraryPath) -> int:
    """Scan a library path for video files and update the database.

    Returns the number of new files discovered.
    """
    path = Path(library_path.path)
    if not path.exists() or not path.is_dir():
        logger.warning(f"Library path does not exist or is not a directory: {path}")
        return 0

    new_files_count = 0
    logger.info(f"Scanning library path: {path}")

    # Walk the directory tree
    for root, dirs, files in os.walk(path):
        for file_name in files:
            file_path = Path(root) / file_name
            file_extension = file_path.suffix.lower()

            # Check if it's a video file
            if file_extension not in VIDEO_EXTENSIONS:
                continue

            # Check if file already exists in database
            existing_file = await session.scalar(
                select(MediaFile).where(MediaFile.file_path == str(file_path))
            )

            if existing_file:
                # Update scanned_at timestamp
                existing_file.scanned_at = datetime.now(UTC)
                session.add(existing_file)
                continue

            # Extract metadata
            logger.info(f"Processing new file: {file_path}")
            metadata = extract_video_metadata(file_path)

            # Create new MediaFile entry
            media_file = MediaFile(
                file_path=str(file_path),
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
            new_files_count += 1

    await session.commit()
    logger.info(f"Scan complete. Found {new_files_count} new files in {path}")
    return new_files_count


async def scan_all_libraries() -> int:
    """Scan all enabled library paths.

    Returns the total number of new files discovered.
    """
    async with async_session_maker() as session:
        # Get all enabled library paths
        library_paths = await session.scalars(
            select(LibraryPath).where(LibraryPath.enabled)
        )

        if not library_paths:
            logger.info("No library paths configured for scanning")
            return 0

        total_new_files = 0
        for library_path in library_paths:
            new_files = await scan_library_path(session, library_path)
            total_new_files += new_files

        logger.info(f"Total new files discovered: {total_new_files}")
        return total_new_files
