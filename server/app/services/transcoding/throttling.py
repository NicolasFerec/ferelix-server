"""Hysteresis for bounded HLS encoding ahead of the viewer's playhead."""

import asyncio
import contextlib
import os
import signal
from dataclasses import dataclass


@dataclass(slots=True)
class PlaybackBuffer:
    session_id: str
    generation: int = 0
    start_time: float = 0.0
    position: float = 0.0
    encoded_duration: float = 0.0
    paused: bool = False
    ready: bool = True
    high_water: float = 120.0
    low_water: float = 60.0

    @property
    def ahead_seconds(self) -> float:
        return max(0.0, self.start_time + self.encoded_duration - self.position)

    def reconcile(self, process: asyncio.subprocess.Process) -> bool:
        """Pause/resume all FFmpeg threads; return whether its state changed."""
        if not self.ready or os.name != "posix" or process.returncode is not None:
            return False
        should_pause = self.ahead_seconds >= self.high_water
        should_resume = self.ahead_seconds <= self.low_water
        if (not self.paused and should_pause) or (self.paused and should_resume):
            try:
                process.send_signal(signal.SIGCONT if self.paused else signal.SIGSTOP)
            except ProcessLookupError:
                return False
            self.paused = not self.paused
            return True
        return False


def resume_before_stop(process: asyncio.subprocess.Process) -> None:
    """A stopped encoder cannot read quit or handle SIGTERM until resumed."""
    if os.name == "posix" and process.returncode is None:
        with contextlib.suppress(ProcessLookupError):
            process.send_signal(signal.SIGCONT)
