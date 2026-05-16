"""Subtitle extraction helpers."""

import asyncio
import logging

logger = logging.getLogger(__name__)


async def extract_subtitle_to_webvtt(
    ffmpeg_path: str,
    media_file_path: str,
    subtitle_stream_index: int,
    output_path: str,
) -> bool:
    """Extract a subtitle stream to WebVTT format."""
    cmd = [
        ffmpeg_path,
        "-hide_banner",
        "-y",
        "-i",
        media_file_path,
        "-map",
        f"0:{subtitle_stream_index}",
        "-c:s",
        "webvtt",
        output_path,
    ]

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _stdout, stderr = await process.communicate()
        if process.returncode == 0:
            logger.info("Successfully extracted subtitle to %s", output_path)
            return True

        logger.error("Subtitle extraction failed: %s", stderr.decode("utf-8", errors="ignore"))
        return False
    except Exception as exc:
        logger.error("Subtitle extraction error: %s", exc)
        return False
