"""Thumbnail extraction helpers for scanned media files."""

import hashlib
import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_THUMBNAIL_DIR = "/tmp/ferelix-thumbnails"


def thumbnail_cache_dir() -> Path:
    """Return the directory used for generated screenshot thumbnails."""
    path = Path(os.getenv("FERELIX_THUMBNAIL_DIR", DEFAULT_THUMBNAIL_DIR))
    path.mkdir(parents=True, exist_ok=True, mode=0o755)
    path.chmod(0o755)
    return path


def thumbnail_path_for_media(file_path: str | Path) -> Path:
    """Return the deterministic thumbnail path for a media file path."""
    digest = hashlib.sha256(str(file_path).encode("utf-8")).hexdigest()
    return thumbnail_cache_dir() / f"{digest}.jpg"


def screenshot_timestamp(duration: float | None) -> float:
    """Choose a representative timestamp away from credits and black leaders."""
    if not duration or duration <= 0:
        return 10.0

    if duration < 30:
        return max(1.0, duration * 0.35)

    return min(max(duration * 0.2, 30.0), duration * 0.8)


def generate_video_thumbnail(
    file_path: str | Path,
    duration: float | None = None,
    *,
    force: bool = False,
) -> str | None:
    """Extract a scaled JPEG screenshot for a media file.

    Returns the generated thumbnail path, or ``None`` when ffmpeg cannot create
    one. Failures should not block library scans.
    """
    source_path = Path(file_path)
    if not source_path.exists():
        return None

    output_path = thumbnail_path_for_media(source_path)
    if output_path.exists() and not force:
        return str(output_path)

    timestamp = screenshot_timestamp(duration)
    command = [
        os.getenv("FERELIX_FFMPEG_PATH", "ffmpeg"),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{timestamp:.3f}",
        "-i",
        str(source_path),
        "-frames:v",
        "1",
        "-vf",
        "scale='min(720,iw)':-2",
        "-q:v",
        "4",
        str(output_path),
    ]

    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=45)
    except subprocess.TimeoutExpired:
        logger.warning("Thumbnail extraction timed out for %s", source_path)
        return None
    except Exception as exc:
        logger.warning("Thumbnail extraction failed for %s: %s", source_path, exc)
        return None

    if result.returncode != 0 or not output_path.exists():
        logger.warning("ffmpeg thumbnail extraction failed for %s: %s", source_path, result.stderr)
        return None

    output_path.chmod(0o644)
    return str(output_path)
