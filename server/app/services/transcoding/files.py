"""Filesystem and process cleanup helpers for transcoding jobs."""

import asyncio
import logging
import os
import re
import shutil
import signal
import time
from collections.abc import AsyncIterator
from pathlib import Path

logger = logging.getLogger(__name__)


async def read_process_messages(stream: asyncio.StreamReader) -> AsyncIterator[str]:
    """Read bounded FFmpeg messages, including carriage-return progress updates."""
    pending = b""
    while chunk := await stream.read(4096):
        parts = re.split(rb"[\r\n]", pending + chunk)
        pending = parts.pop()
        for part in parts:
            if message := part.decode("utf-8", errors="replace").strip():
                yield message
        if len(pending) > 8192:
            yield pending[:8192].decode("utf-8", errors="replace")
            pending = pending[8192:]
    if message := pending.decode("utf-8", errors="replace").strip():
        yield message


def remove_output_path(output_path: str | None) -> None:
    """Delete a generated transcode directory if it exists."""
    if not output_path:
        return

    job_path = Path(output_path)
    if job_path.exists():
        shutil.rmtree(job_path, ignore_errors=True)


def _owned_process_running(process_id: int, output_path: str) -> bool:
    try:
        arguments = Path(f"/proc/{process_id}/cmdline").read_bytes().decode().split("\0")
        prefix = output_path.rstrip("/") + "/"
        if not arguments or "ffmpeg" not in Path(arguments[0]).name:
            return False
        return any(argument.startswith(prefix) for argument in arguments[1:])
    except OSError, UnicodeError:
        return False


def terminate_process(process_id: int, output_path: str | None = None) -> bool:
    """Stop a persisted, verified FFmpeg PID and confirm its disappearance.

    A PID may have been reused since the previous server run. Revalidate its
    command before every signal and never send a signal to an unrelated process.
    This bounded blocking helper must run outside the asyncio event loop.
    """
    if not output_path:
        return False
    if not _owned_process_running(process_id, output_path):
        return True
    try:
        os.kill(process_id, signal.SIGCONT)
        os.kill(process_id, signal.SIGTERM)
        for signal_to_send, timeout in ((None, 2.0), (signal.SIGKILL, 1.0)):
            if not _owned_process_running(process_id, output_path):
                return True
            if signal_to_send is not None:
                os.kill(process_id, signal_to_send)
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if not _owned_process_running(process_id, output_path):
                    logger.info("Terminated stalled ffmpeg process %s", process_id)
                    return True
                time.sleep(0.05)
        return not _owned_process_running(process_id, output_path)
    except ProcessLookupError:
        return True
    except OSError:
        logger.exception("Could not terminate stalled ffmpeg process %s", process_id)
        return False
