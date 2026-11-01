"""Filesystem and process cleanup helpers for transcoding jobs."""

import asyncio
import logging
import os
import re
import shutil
import signal
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


def terminate_process(process_id: int, output_path: str | None = None) -> None:
    """Terminate a persisted ffmpeg PID from before this server process."""
    # A persisted PID can belong to an unrelated process after a restart/reboot.
    # Only signal a process whose command still identifies this exact output directory.
    if not output_path:
        return
    try:
        arguments = Path(f"/proc/{process_id}/cmdline").read_bytes().decode().split("\0")
        prefix = output_path.rstrip("/") + "/"
        if not arguments or "ffmpeg" not in Path(arguments[0]).name:
            return
        if not any(argument.startswith(prefix) for argument in arguments[1:]):
            return
        os.kill(process_id, signal.SIGTERM)
        logger.info("Terminated stalled ffmpeg process %s", process_id)
    except OSError, UnicodeError:
        return
