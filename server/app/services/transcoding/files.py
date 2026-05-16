"""Filesystem and process cleanup helpers for transcoding jobs."""

import logging
import os
import shutil
import signal
from pathlib import Path

logger = logging.getLogger(__name__)


def remove_output_path(output_path: str | None) -> None:
    """Delete a generated transcode directory if it exists."""
    if not output_path:
        return

    job_path = Path(output_path)
    if job_path.exists():
        shutil.rmtree(job_path, ignore_errors=True)


def terminate_process(process_id: int) -> None:
    """Terminate a persisted ffmpeg PID from before this server process."""
    try:
        os.kill(process_id, signal.SIGTERM)
        logger.info("Terminated stalled ffmpeg process %s", process_id)
    except ProcessLookupError, PermissionError:
        return
