"""Bounded real-media benchmark: python -m scripts.benchmark_encoding_ahead --source movie.mkv."""

import argparse
import asyncio
import contextlib
import json
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from app.services.transcoder import FFmpegTranscoder
from app.services.transcoding.commands import HlsCommandOptions
from app.services.transcoding.files import read_process_messages
from app.services.transcoding.throttling import PlaybackBuffer


def cpu_seconds(pid: int) -> float:
    fields = Path(f"/proc/{pid}/stat").read_text().split()
    return (int(fields[13]) + int(fields[14])) / os.sysconf("SC_CLK_TCK")


def kill_if_running(process: asyncio.subprocess.Process) -> None:
    if process.returncode is None:
        with contextlib.suppress(ProcessLookupError):
            os.kill(process.pid, signal.SIGKILL)


def probe_source(source: Path) -> tuple[int, str, int | None]:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=index,codec_type,codec_name", "-of", "json", str(source)],
        capture_output=True,
        text=True,
        check=True,
        timeout=5,
    )
    streams = json.loads(result.stdout)["streams"]
    video = next(stream for stream in streams if stream["codec_type"] == "video")
    audio = next((stream for stream in streams if stream["codec_type"] == "audio"), None)
    return video["index"], video["codec_name"], audio["index"] if audio else None


async def sample(source: Path, duration: float, regulated: bool, tracks: tuple[int, str, int | None]) -> dict[str, Any]:
    directory = Path(tempfile.mkdtemp(prefix="ferelix-throttle-measure-"))
    video_index, codec, audio_index = tracks
    segment_type = "fmp4" if codec in {"hevc", "h265", "av1", "vp9"} else "mpegts"
    extension = "m4s" if segment_type == "fmp4" else "ts"
    process = None
    watchdog = None
    try:
        transcoder = FFmpegTranscoder(temp_dir=str(directory / "controller"))
        transcoder.set_hardware_device("software")
        command = transcoder.commands.build_transcode(
            HlsCommandOptions(
                input_path=str(source),
                playlist_path=str(directory / "playlist.m3u8"),
                segment_pattern=str(directory / f"segment_%03d.{extension}"),
                video_codec="copy",
                audio_codec="aac",
                audio_bitrate=128000,
                source_video_codec=codec,
                hls_segment_type=segment_type,
                video_stream_index=video_index,
                audio_stream_index=audio_index,
            )
        )
        # An additional media-duration cap; the wall-clock watchdog is authoritative.
        command[-1:-1] = ["-t", "1800"]
        process = await asyncio.create_subprocess_exec(
            *command, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE, stdin=asyncio.subprocess.PIPE
        )
        watchdog = threading.Timer(min(duration + 4, 30), kill_if_running, args=(process,))
        watchdog.start()
        started = time.monotonic()
        buffer = PlaybackBuffer("benchmark")
        transitions = []
        max_ahead = 0.0
        last_duration = 0.0

        async def monitor() -> None:
            nonlocal last_duration, max_ahead
            assert process is not None and process.stderr is not None
            async for line in read_process_messages(process.stderr):
                progress = transcoder._parse_ffmpeg_progress(line, None, 0)
                if progress is None:
                    continue
                last_duration = progress.get("transcoded_duration", last_duration)
                buffer.encoded_duration = last_duration
                max_ahead = max(max_ahead, buffer.ahead_seconds)
                if regulated and buffer.reconcile(process):
                    transitions.append({
                        "wall_s": round(time.monotonic() - started, 3),
                        "paused": buffer.paused,
                        "ahead_s": round(buffer.ahead_seconds, 2),
                    })

        monitor_task = asyncio.create_task(monitor())
        checkpoints = {}
        advanced = False
        next_checkpoint = 0
        checkpoint_times = [duration * 0.2, duration * 0.6, duration]
        last_cpu = 0.0
        try:
            while (elapsed := time.monotonic() - started) < duration and process.returncode is None:
                await asyncio.sleep(min(0.1, max(0.0, duration - elapsed)))
                elapsed = time.monotonic() - started
                with contextlib.suppress(FileNotFoundError):
                    last_cpu = cpu_seconds(process.pid)
                if next_checkpoint < 3 and elapsed >= checkpoint_times[next_checkpoint]:
                    checkpoints[str(next_checkpoint)] = {
                        "wall_s": round(elapsed, 3),
                        "cpu_s": last_cpu,
                        "encoded_s": last_duration,
                    }
                    next_checkpoint += 1
                if not advanced and elapsed >= duration * 0.6:
                    advanced = True
                    buffer.position = 90.0
                    if regulated and buffer.reconcile(process):
                        transitions.append({
                            "wall_s": round(elapsed, 3),
                            "paused": buffer.paused,
                            "ahead_s": round(buffer.ahead_seconds, 2),
                        })
            output_bytes = await asyncio.to_thread(
                lambda: sum(path.stat().st_size for path in directory.glob(f"*.{extension}"))
            )
        finally:
            await transcoder._stop_process(process)
            await monitor_task
        return {
            "regulated": regulated,
            "wall_s": round(time.monotonic() - started, 3),
            "checkpoints": checkpoints,
            "max_ahead_s": max_ahead,
            "encoded_s": last_duration,
            "output_bytes": output_bytes,
            "transitions": transitions,
            "returncode": process.returncode,
        }
    finally:
        if process is not None and process.returncode is None:
            process.kill()
            await process.communicate()
        if watchdog is not None:
            watchdog.cancel()
        shutil.rmtree(directory, ignore_errors=True)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--duration", type=float, default=10.0, help="Wall-clock seconds per trial, maximum 30")
    parser.add_argument("--output", type=Path, help="Optional JSON result file")
    args = parser.parse_args()
    if not 0 < args.duration <= 30:
        parser.error("--duration must be greater than zero and at most 30 seconds")
    if os.name != "posix" or not await asyncio.to_thread(Path("/proc").exists):
        parser.error("This benchmark requires Linux process counters and signals")
    tracks = await asyncio.to_thread(probe_source, args.source)
    results = [
        await sample(args.source, args.duration, False, tracks),
        await sample(args.source, args.duration, True, tracks),
    ]
    content = json.dumps(results, indent=2)
    if args.output:
        args.output.write_text(content + "\n")
    print(content)


if __name__ == "__main__":
    asyncio.run(main())
