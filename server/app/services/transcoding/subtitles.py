"""Subtitle extraction helpers."""

import asyncio
import contextlib
import logging
import uuid
from pathlib import Path
from weakref import WeakValueDictionary

logger = logging.getLogger(__name__)
EXTRACTION_TIMEOUT_SECONDS = 30.0
_extraction_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()


def _valid_webvtt(path: Path) -> bool:
    try:
        with path.open("rb") as subtitle:
            return subtitle.read(6) == b"WEBVTT"
    except OSError:
        return False


async def extract_subtitle_to_webvtt(
    ffmpeg_path: str,
    media_file_path: str,
    subtitle_stream_index: int,
    output_path: str,
) -> bool:
    """Deduplicate extraction and publish only complete WebVTT files, within 30s.

    The lock is process-local, matching the server's single-worker contract.
    Cancellation of the extractor kills/reaps FFmpeg; another waiting request
    can then retry. Waiting for another extraction consumes the same deadline.
    """
    output = await asyncio.to_thread(Path(output_path).absolute)
    lock = _extraction_locks.setdefault(str(output), asyncio.Lock())
    try:
        async with asyncio.timeout(EXTRACTION_TIMEOUT_SECONDS), lock:
            if await asyncio.to_thread(_valid_webvtt, output):
                return True
            return await _extract_atomic(ffmpeg_path, media_file_path, subtitle_stream_index, output)
    except TimeoutError:
        logger.warning("Subtitle extraction exceeded %.0fs for %s", EXTRACTION_TIMEOUT_SECONDS, media_file_path)
        return False
    except Exception:
        logger.exception("Subtitle extraction error for %s", media_file_path)
        return False


async def _extract_atomic(ffmpeg_path: str, source: str, stream_index: int, output: Path) -> bool:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{uuid.uuid4().hex}.tmp")
    cmd = [
        ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-y",
        "-i",
        source,
        "-map",
        f"0:{stream_index}",
        "-c:s",
        "webvtt",
        "-f",
        "webvtt",
        str(temporary),
    ]
    process = None
    try:
        spawning = asyncio.create_task(
            asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
        )
        try:
            process = await asyncio.shield(spawning)
        except asyncio.CancelledError:
            # Recover the handle even if cancellation arrives between fork/exec
            # and create_subprocess_exec returning it, then clean it up below.
            process = await spawning
            raise
        _stdout, stderr = await process.communicate()
        if process.returncode == 0 and await asyncio.to_thread(_valid_webvtt, temporary):
            temporary.replace(output)
            logger.info("Successfully extracted subtitle to %s", output)
            return True

        logger.error("Subtitle extraction failed: %s", stderr.decode("utf-8", errors="ignore"))
        return False
    finally:
        if process is not None and process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            await process.communicate()
        temporary.unlink(missing_ok=True)
