"""FFmpeg transcoding service for HLS streaming."""

import asyncio
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select, update

from ..database import async_session_maker
from ..models import (
    MediaFile,
    TranscodingJob,
)
from ..models.transcoding import TranscodingJobStatus


class FFmpegTranscoder:
    """FFmpeg transcoding service with HLS support."""

    def __init__(self, temp_dir: str = "/tmp/ferelix-transcode"):
        self.temp_dir = Path(temp_dir)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self._active_jobs: dict[str, Any] = {}
        self._cleanup_task: asyncio.Task | None = None

        # FFmpeg progress regex patterns
        self.progress_patterns = {
            "frame": re.compile(r"frame=\s*(\d+)"),
            "fps": re.compile(r"fps=\s*([\d.]+)"),
            "time": re.compile(r"time=(\d{2}):(\d{2}):([\d.]+)"),
            "bitrate": re.compile(r"bitrate=\s*([\d.]+)kbits/s"),
            "speed": re.compile(r"speed=\s*([\d.]+)x"),
        }

    async def start_hls_transcode(
        self,
        job_id: str,
        media_file: MediaFile,
        video_codec: str = "h264",
        audio_codec: str = "aac",
        video_bitrate: int | None = None,
        audio_bitrate: int | None = None,
        max_width: int | None = None,
        max_height: int | None = None,
        segment_duration: int = 6,
        session_id: str | None = None,
        client_ip: str | None = None,
        user_agent: str | None = None,
    ) -> str:
        """Start HLS transcoding job for a media file."""

        # Create job directory
        job_dir = self.temp_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)

        playlist_path = job_dir / "playlist.m3u8"
        segment_pattern = str(job_dir / "segment_%03d.ts")

        # Build FFmpeg command
        cmd = self._build_hls_command(
            input_path=media_file.file_path,
            playlist_path=str(playlist_path),
            segment_pattern=segment_pattern,
            video_codec=video_codec,
            audio_codec=audio_codec,
            video_bitrate=video_bitrate,
            audio_bitrate=audio_bitrate,
            max_width=max_width,
            max_height=max_height,
            segment_duration=segment_duration,
        )

        # Update job record
        async with async_session_maker() as session:
            await session.execute(
                update(TranscodingJob)
                .where(TranscodingJob.id == job_id)
                .values(
                    status=TranscodingJobStatus.RUNNING,
                    started_at=datetime.utcnow(),
                    ffmpeg_command=" ".join(cmd),
                    output_path=str(job_dir),
                    playlist_path=str(playlist_path),
                    video_codec=video_codec,
                    audio_codec=audio_codec,
                    video_bitrate=video_bitrate,
                    audio_bitrate=audio_bitrate,
                    max_width=max_width,
                    max_height=max_height,
                    session_id=session_id,
                    client_ip=client_ip,
                    user_agent=user_agent,
                )
            )
            await session.commit()

        # Start FFmpeg process
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.PIPE,
            )

            # Store process for job management
            self._active_jobs[job_id] = process

            # Update job with process ID
            async with async_session_maker() as session:
                await session.execute(
                    update(TranscodingJob)
                    .where(TranscodingJob.id == job_id)
                    .values(process_id=process.pid)
                )
                await session.commit()

            # Start progress monitoring
            task = asyncio.create_task(
                self._monitor_progress(job_id, process, media_file.duration)
            )
            # Store task reference to prevent garbage collection
            if not hasattr(self, "_background_tasks"):
                self._background_tasks = set()
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

            return str(playlist_path)

        except Exception as e:
            await self._mark_job_failed(job_id, str(e))
            raise HTTPException(
                status_code=500, detail=f"Failed to start transcoding: {e}"
            )

    async def start_remux_hls(
        self,
        job_id: str,
        media_file: MediaFile,
        segment_duration: int = 6,
        session_id: str | None = None,
        client_ip: str | None = None,
        user_agent: str | None = None,
    ) -> str:
        """Start HLS remuxing (container conversion only, no re-encoding)."""

        # Create job directory
        job_dir = self.temp_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)

        playlist_path = job_dir / "playlist.m3u8"
        segment_pattern = str(job_dir / "segment_%03d.ts")

        # Build FFmpeg remux command (copy codecs, no re-encoding)
        cmd = self._build_remux_hls_command(
            input_path=media_file.file_path,
            playlist_path=str(playlist_path),
            segment_pattern=segment_pattern,
            segment_duration=segment_duration,
        )

        # Update job record
        async with async_session_maker() as session:
            await session.execute(
                update(TranscodingJob)
                .where(TranscodingJob.id == job_id)
                .values(
                    status=TranscodingJobStatus.RUNNING,
                    started_at=datetime.utcnow(),
                    ffmpeg_command=" ".join(cmd),
                    output_path=str(job_dir),
                    playlist_path=str(playlist_path),
                    video_codec="copy",
                    audio_codec="copy",
                    session_id=session_id,
                    client_ip=client_ip,
                    user_agent=user_agent,
                )
            )
            await session.commit()

        # Start FFmpeg process
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.PIPE,
            )

            # Store process for job management
            self._active_jobs[job_id] = process

            # Update job with process ID
            async with async_session_maker() as session:
                await session.execute(
                    update(TranscodingJob)
                    .where(TranscodingJob.id == job_id)
                    .values(process_id=process.pid)
                )
                await session.commit()

            # Start progress monitoring
            task = asyncio.create_task(
                self._monitor_progress(job_id, process, media_file.duration)
            )
            # Store task reference to prevent garbage collection
            if not hasattr(self, "_background_tasks"):
                self._background_tasks = set()
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

            return str(playlist_path)

        except Exception as e:
            await self._mark_job_failed(job_id, str(e))
            raise HTTPException(
                status_code=500, detail=f"Failed to start remuxing: {e}"
            )

    def _build_remux_hls_command(
        self,
        input_path: str,
        playlist_path: str,
        segment_pattern: str,
        segment_duration: int = 6,
    ) -> list[str]:
        """Build FFmpeg command for HLS remuxing (no re-encoding)."""

        cmd = [
            "ffmpeg",
            "-y",  # Overwrite output files
            "-i",
            input_path,
            "-c",
            "copy",  # Copy all streams without re-encoding
            "-avoid_negative_ts",
            "make_zero",  # Fix timestamp issues
        ]

        # HLS specific settings optimized for remux
        cmd.extend([
            "-f",
            "hls",
            "-hls_time",
            str(segment_duration),
            "-hls_playlist_type",
            "event",  # Allow seeking
            "-hls_segment_filename",
            segment_pattern,
            "-start_number",
            "0",
            "-hls_allow_cache",
            "1",
            "-hls_flags",
            "delete_segments+append_list",  # Auto cleanup
            playlist_path,
        ])

        return cmd

    def _build_hls_command(
        self,
        input_path: str,
        playlist_path: str,
        segment_pattern: str,
        video_codec: str,
        audio_codec: str,
        video_bitrate: int | None = None,
        audio_bitrate: int | None = None,
        max_width: int | None = None,
        max_height: int | None = None,
        segment_duration: int = 6,
    ) -> list[str]:
        """Build FFmpeg command for HLS transcoding."""

        cmd = [
            "ffmpeg",
            "-y",  # Overwrite output files
            "-i",
            input_path,
            "-c:v",
            video_codec,
            "-c:a",
            audio_codec,
        ]

        # Video encoding settings
        if video_codec == "h264":
            cmd.extend([
                "-preset",
                "veryfast",  # Fast encoding for live streaming
                "-profile:v",
                "high",
                "-level",
                "4.1",
                "-pix_fmt",
                "yuv420p",  # Compatibility
            ])
        elif video_codec == "hevc":
            cmd.extend([
                "-preset",
                "veryfast",
                "-profile:v",
                "main",
                "-level",
                "4.1",
                "-pix_fmt",
                "yuv420p",
            ])
        elif video_codec != "copy":
            # Hardware acceleration attempts
            cmd.extend(["-preset", "veryfast"])

        # Video bitrate
        if video_bitrate and video_codec != "copy":
            cmd.extend([
                "-b:v",
                f"{video_bitrate}",
                "-maxrate",
                f"{int(video_bitrate * 1.2)}",
                "-bufsize",
                f"{video_bitrate * 2}",
            ])

        # Audio encoding
        if audio_codec == "aac":
            cmd.extend(["-profile:a", "aac_low"])

        # Audio bitrate
        if audio_bitrate and audio_codec != "copy":
            cmd.extend(["-b:a", f"{audio_bitrate}"])

        # Resolution scaling
        if max_width or max_height:
            if max_width and max_height:
                scale_filter = f"scale='min({max_width},iw)':'min({max_height},ih)':force_original_aspect_ratio=decrease"
            elif max_width:
                scale_filter = f"scale={max_width}:-2"
            else:
                scale_filter = f"scale=-2:{max_height}"

            if video_codec != "copy":
                cmd.extend(["-vf", scale_filter])

        # HLS specific settings
        cmd.extend([
            "-f",
            "hls",
            "-hls_time",
            str(segment_duration),
            "-hls_playlist_type",
            "event",  # Allow seeking in live streams
            "-hls_segment_filename",
            segment_pattern,
            "-start_number",
            "0",
            "-hls_allow_cache",
            "1",
            "-hls_flags",
            "delete_segments+append_list",  # Auto cleanup old segments
            playlist_path,
        ])

        return cmd

    async def _monitor_progress(
        self,
        job_id: str,
        process: asyncio.subprocess.Process,
        total_duration: float | None,
    ) -> None:
        """Monitor FFmpeg process and update job progress."""

        try:
            while True:
                if process.stderr is None:
                    break

                # Read stderr line for progress info
                line_bytes = await process.stderr.readline()
                if not line_bytes:
                    break

                line = line_bytes.decode("utf-8", errors="ignore").strip()
                if not line:
                    continue

                # Parse progress from FFmpeg output
                progress_data = self._parse_ffmpeg_progress(line, total_duration)
                if progress_data:
                    await self._update_job_progress(job_id, progress_data)

            # Wait for process to complete
            await process.wait()

            # Check final status
            if process.returncode == 0:
                await self._mark_job_completed(job_id)
            else:
                stderr_output = ""
                if process.stderr:
                    stderr_output = (await process.stderr.read()).decode(
                        "utf-8", errors="ignore"
                    )
                await self._mark_job_failed(
                    job_id,
                    f"FFmpeg exited with code {process.returncode}: {stderr_output}",
                )

        except Exception as e:
            await self._mark_job_failed(job_id, f"Progress monitoring failed: {e}")

        finally:
            # Remove from active jobs
            self._active_jobs.pop(job_id, None)

    def _parse_ffmpeg_progress(
        self, line: str, total_duration: float | None
    ) -> dict[str, Any] | None:
        """Parse FFmpeg stderr output for progress information."""

        if "frame=" not in line or "time=" not in line:
            return None

        progress = {}

        # Extract frame count
        if match := self.progress_patterns["frame"].search(line):
            progress["frame"] = int(match.group(1))

        # Extract current FPS
        if match := self.progress_patterns["fps"].search(line):
            progress["current_fps"] = float(match.group(1))

        # Extract current time
        if match := self.progress_patterns["time"].search(line):
            hours, minutes, seconds = match.groups()
            current_seconds = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
            progress["transcoded_duration"] = current_seconds

            # Calculate progress percentage
            if total_duration and total_duration > 0:
                progress["progress_percent"] = min(
                    100.0, (current_seconds / total_duration) * 100
                )

        # Extract current bitrate
        if match := self.progress_patterns["bitrate"].search(line):
            bitrate_kbps = float(match.group(1))
            progress["current_bitrate"] = int(bitrate_kbps * 1000)  # Convert to bps

        return progress if progress else None

    async def _update_job_progress(
        self, job_id: str, progress_data: dict[str, Any]
    ) -> None:
        """Update job progress in database."""

        async with async_session_maker() as session:
            await session.execute(
                update(TranscodingJob)
                .where(TranscodingJob.id == job_id)
                .values(
                    progress_percent=progress_data.get("progress_percent"),
                    transcoded_duration=progress_data.get("transcoded_duration"),
                    current_fps=progress_data.get("current_fps"),
                    current_bitrate=progress_data.get("current_bitrate"),
                    last_accessed_at=datetime.utcnow(),
                )
            )
            await session.commit()

    async def _mark_job_completed(self, job_id: str) -> None:
        """Mark job as completed."""

        async with async_session_maker() as session:
            await session.execute(
                update(TranscodingJob)
                .where(TranscodingJob.id == job_id)
                .values(
                    status=TranscodingJobStatus.COMPLETED,
                    completed_at=datetime.utcnow(),
                    progress_percent=100.0,
                )
            )
            await session.commit()

    async def _mark_job_failed(self, job_id: str, error_message: str) -> None:
        """Mark job as failed with error message."""

        async with async_session_maker() as session:
            await session.execute(
                update(TranscodingJob)
                .where(TranscodingJob.id == job_id)
                .values(
                    status=TranscodingJobStatus.FAILED,
                    error_message=error_message,
                    completed_at=datetime.utcnow(),
                )
            )
            await session.commit()

    async def stop_job(self, job_id: str) -> bool:
        """Gracefully stop a transcoding job."""

        process = self._active_jobs.get(job_id)
        if not process:
            return False

        try:
            # Send 'q' to FFmpeg stdin for graceful quit
            if process.stdin and not process.stdin.is_closing():
                process.stdin.write(b"q\n")
                await process.stdin.drain()
                process.stdin.close()

            # Wait for graceful shutdown (max 10 seconds)
            try:
                await asyncio.wait_for(process.wait(), timeout=10.0)
            except TimeoutError:
                # Force kill if graceful shutdown fails
                process.kill()
                await process.wait()

            # Update job status
            async with async_session_maker() as session:
                await session.execute(
                    update(TranscodingJob)
                    .where(TranscodingJob.id == job_id)
                    .values(
                        status=TranscodingJobStatus.CANCELLED,
                        completed_at=datetime.utcnow(),
                    )
                )
                await session.commit()

            return True

        except Exception as e:
            await self._mark_job_failed(job_id, f"Failed to stop job: {e}")
            return False

        finally:
            self._active_jobs.pop(job_id, None)

    async def cleanup_old_jobs(self, max_age_hours: int = 24) -> int:
        """Cleanup old transcoding jobs and their files."""

        cutoff_time = datetime.utcnow() - timedelta(hours=max_age_hours)
        cleanup_count = 0

        async with async_session_maker() as session:
            # Find old jobs to cleanup
            result = await session.execute(
                select(TranscodingJob).where(
                    TranscodingJob.auto_cleanup == True,  # noqa: E712
                    TranscodingJob.last_accessed_at < cutoff_time,
                    TranscodingJob.status.in_([
                        TranscodingJobStatus.COMPLETED,
                        TranscodingJobStatus.FAILED,
                        TranscodingJobStatus.CANCELLED,
                    ]),
                )
            )
            old_jobs = result.scalars().all()

            for job in old_jobs:
                try:
                    # Stop active process if still running
                    if job.status == TranscodingJobStatus.RUNNING:
                        await self.stop_job(job.id)

                    # Remove job directory and files
                    if job.output_path:
                        job_path = Path(job.output_path)
                        if job_path.exists():
                            shutil.rmtree(job_path, ignore_errors=True)

                    # Delete job record
                    await session.delete(job)
                    cleanup_count += 1

                except Exception as e:
                    print(f"Failed to cleanup job {job.id}: {e}")

            await session.commit()

        return cleanup_count

    async def get_job_status(self, job_id: str) -> TranscodingJob | None:
        """Get current status of a transcoding job."""

        async with async_session_maker() as session:
            result = await session.execute(
                select(TranscodingJob).where(TranscodingJob.id == job_id)
            )
            return result.scalar_one_or_none()

    async def start_cleanup_scheduler(self) -> None:
        """Start background task for periodic cleanup."""

        if self._cleanup_task and not self._cleanup_task.done():
            return

        self._cleanup_task = asyncio.create_task(self._periodic_cleanup())

    async def _periodic_cleanup(self) -> None:
        """Periodic cleanup task (runs every hour)."""

        while True:
            try:
                await asyncio.sleep(3600)  # 1 hour
                cleaned = await self.cleanup_old_jobs()
                if cleaned > 0:
                    print(f"Cleaned up {cleaned} old transcoding jobs")
            except Exception as e:
                print(f"Cleanup scheduler error: {e}")


# Global transcoder instance
_transcoder: FFmpegTranscoder | None = None


def get_transcoder() -> FFmpegTranscoder:
    """Get the global transcoder instance."""
    global _transcoder
    if _transcoder is None:
        _transcoder = FFmpegTranscoder()
    return _transcoder
