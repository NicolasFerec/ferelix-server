"""FFmpeg transcoding service for HLS streaming."""

import asyncio
import logging
import re
import shutil
import subprocess
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

logger = logging.getLogger(__name__)

# Text-based subtitle codecs that can be extracted to WebVTT
TEXT_SUBTITLE_CODECS = {"subrip", "srt", "ass", "ssa", "webvtt", "mov_text", "text"}

# Image-based subtitle codecs that must be burned into video
IMAGE_SUBTITLE_CODECS = {"hdmv_pgs_subtitle", "pgssub", "dvd_subtitle", "dvdsub", "dvb_subtitle", "xsub", "vobsub"}


class HardwareAcceleration:
    """Hardware acceleration capabilities detection."""

    def __init__(self):
        self.nvenc_available = False
        self.qsv_available = False
        self.vaapi_available = False
        self.vaapi_device: str | None = None
        self._detected = False

    def detect(self) -> None:
        """Detect available hardware encoders."""
        if self._detected:
            return

        self._detected = True

        # Check for available encoders
        try:
            result = subprocess.run(
                ["ffmpeg", "-hide_banner", "-encoders"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            encoders_output = result.stdout

            # Check NVENC (Nvidia)
            if "h264_nvenc" in encoders_output and self._test_encoder("h264_nvenc"):
                self.nvenc_available = True
                logger.info("NVENC hardware acceleration available")

            # Check Intel Quick Sync
            if "h264_qsv" in encoders_output and self._test_encoder("h264_qsv"):
                self.qsv_available = True
                logger.info("Intel Quick Sync hardware acceleration available")

            # Check VAAPI (Linux)
            if "h264_vaapi" in encoders_output:
                # Find VAAPI device
                vaapi_devices = ["/dev/dri/renderD128", "/dev/dri/renderD129"]
                for device in vaapi_devices:
                    if Path(device).exists():
                        self.vaapi_device = device
                        if self._test_vaapi_encoder(device):
                            self.vaapi_available = True
                            logger.info(f"VAAPI hardware acceleration available on {device}")
                            break

        except Exception as e:
            logger.warning(f"Hardware acceleration detection failed: {e}")

        if not any([self.nvenc_available, self.qsv_available, self.vaapi_available]):
            logger.info("No hardware acceleration available, using software encoding")

    def _test_encoder(self, encoder: str) -> bool:
        """Test if an encoder actually works."""
        try:
            result = subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=black:s=64x64:d=0.1",
                    "-c:v",
                    encoder,
                    "-f",
                    "null",
                    "-",
                ],
                capture_output=True,
                timeout=10,
            )
            return result.returncode == 0
        except Exception:
            return False

    def _test_vaapi_encoder(self, device: str) -> bool:
        """Test if VAAPI encoder works with specific device."""
        try:
            result = subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-vaapi_device",
                    device,
                    "-f",
                    "lavfi",
                    "-i",
                    "color=black:s=64x64:d=0.1",
                    "-vf",
                    "format=nv12,hwupload",
                    "-c:v",
                    "h264_vaapi",
                    "-f",
                    "null",
                    "-",
                ],
                capture_output=True,
                timeout=10,
            )
            return result.returncode == 0
        except Exception:
            return False

    def get_video_encoder(self, codec: str = "h264") -> tuple[str, list[str]]:
        """Get the best available encoder for the codec.

        Returns:
            Tuple of (encoder_name, extra_args)
        """
        if codec == "copy":
            return "copy", []

        if codec in ("h264", "libx264"):
            if self.nvenc_available:
                return "h264_nvenc", ["-preset", "p4", "-tune", "ll"]
            if self.qsv_available:
                return "h264_qsv", ["-preset", "faster"]
            if self.vaapi_available and self.vaapi_device:
                return "h264_vaapi", []
            # Software fallback
            return "libx264", ["-preset", "veryfast", "-profile:v", "high", "-level", "4.1"]

        if codec in ("hevc", "h265", "libx265"):
            if self.nvenc_available:
                return "hevc_nvenc", ["-preset", "p4", "-tune", "ll"]
            if self.qsv_available:
                return "hevc_qsv", ["-preset", "faster"]
            if self.vaapi_available and self.vaapi_device:
                return "hevc_vaapi", []
            # Software fallback
            return "libx265", ["-preset", "veryfast"]

        return codec, []


class FFmpegTranscoder:
    """FFmpeg transcoding service with HLS support."""

    def __init__(self, temp_dir: str = "/tmp/ferelix-transcode"):
        self.temp_dir = Path(temp_dir)
        self.temp_dir.mkdir(parents=True, exist_ok=True, mode=0o755)
        self.temp_dir.chmod(0o755)
        self._active_jobs: dict[str, Any] = {}
        self._cleanup_task: asyncio.Task | None = None

        # Hardware acceleration
        self.hw_accel = HardwareAcceleration()
        self.hw_accel.detect()

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
        audio_stream_index: int | None = None,
        subtitle_stream_index: int | None = None,
        start_time: float | None = None,
    ) -> str:
        """Start HLS transcoding job for a media file.

        Args:
            job_id: Unique job identifier
            media_file: Media file to transcode
            video_codec: Target video codec (h264, hevc, copy)
            audio_codec: Target audio codec (aac, mp3, copy)
            video_bitrate: Target video bitrate
            audio_bitrate: Target audio bitrate
            max_width: Maximum width for scaling
            max_height: Maximum height for scaling
            segment_duration: HLS segment duration in seconds
            session_id: Streaming session ID
            client_ip: Client IP address
            user_agent: Client user agent
            audio_stream_index: Specific audio stream to include (None = default)
            subtitle_stream_index: Subtitle stream to burn (None = no subtitles)
            start_time: Start time in seconds for seeking
        """

        # Create job directory
        job_dir = self.temp_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True, mode=0o755)
        job_dir.chmod(0o755)

        playlist_path = job_dir / "playlist.m3u8"
        segment_pattern = str(job_dir / "segment_%03d.ts")

        # Check if subtitle needs burning (image-based)
        burn_subtitle = False
        subtitle_codec = None
        if subtitle_stream_index is not None and media_file.subtitle_tracks:
            for track in media_file.subtitle_tracks:
                if track.stream_index == subtitle_stream_index:
                    subtitle_codec = track.codec
                    if subtitle_codec and subtitle_codec.lower() in IMAGE_SUBTITLE_CODECS:
                        burn_subtitle = True
                    break

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
            audio_stream_index=audio_stream_index,
            subtitle_stream_index=subtitle_stream_index if burn_subtitle else None,
            start_time=start_time,
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
                    update(TranscodingJob).where(TranscodingJob.id == job_id).values(process_id=process.pid)
                )
                await session.commit()

            # Start progress monitoring
            task = asyncio.create_task(self._monitor_progress(job_id, process, media_file.duration))
            # Store task reference to prevent garbage collection
            if not hasattr(self, "_background_tasks"):
                self._background_tasks = set()
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

            # Wait for playlist to be created (max 30 seconds for transcode)
            for _ in range(60):
                if playlist_path.exists():
                    break
                await asyncio.sleep(0.5)

            return str(playlist_path)

        except Exception as e:
            await self._mark_job_failed(job_id, str(e))
            raise HTTPException(status_code=500, detail=f"Failed to start transcoding: {e}")

    async def start_remux_hls(
        self,
        job_id: str,
        media_file: MediaFile,
        segment_duration: int = 6,
        session_id: str | None = None,
        client_ip: str | None = None,
        user_agent: str | None = None,
        audio_stream_index: int | None = None,
        start_time: float | None = None,
    ) -> str:
        """Start HLS remuxing (container conversion only, no re-encoding).

        Args:
            job_id: Unique job identifier
            media_file: Media file to remux
            segment_duration: HLS segment duration in seconds
            session_id: Streaming session ID
            client_ip: Client IP address
            user_agent: Client user agent
            audio_stream_index: Specific audio stream to include (None = all)
            start_time: Start time in seconds for seeking
        """

        # Create job directory
        job_dir = self.temp_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True, mode=0o755)
        job_dir.chmod(0o755)

        playlist_path = job_dir / "playlist.m3u8"
        segment_pattern = str(job_dir / "segment_%03d.ts")

        # Build FFmpeg remux command (copy codecs, no re-encoding)
        cmd = self._build_remux_hls_command(
            input_path=media_file.file_path,
            playlist_path=str(playlist_path),
            segment_pattern=segment_pattern,
            segment_duration=segment_duration,
            audio_stream_index=audio_stream_index,
            start_time=start_time,
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
                    update(TranscodingJob).where(TranscodingJob.id == job_id).values(process_id=process.pid)
                )
                await session.commit()

            # Start progress monitoring
            task = asyncio.create_task(self._monitor_progress(job_id, process, media_file.duration))
            # Store task reference to prevent garbage collection
            if not hasattr(self, "_background_tasks"):
                self._background_tasks = set()
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

            # Wait for playlist to be created (max 15 seconds for remux)
            for _ in range(30):
                if playlist_path.exists():
                    break
                await asyncio.sleep(0.5)

            return str(playlist_path)

        except Exception as e:
            await self._mark_job_failed(job_id, str(e))
            raise HTTPException(status_code=500, detail=f"Failed to start remuxing: {e}")

    def _build_remux_hls_command(
        self,
        input_path: str,
        playlist_path: str,
        segment_pattern: str,
        segment_duration: int = 6,
        audio_stream_index: int | None = None,
        start_time: float | None = None,
    ) -> list[str]:
        """Build FFmpeg command for HLS remuxing (no re-encoding).

        Args:
            input_path: Path to input media file
            playlist_path: Path for HLS playlist
            segment_pattern: Pattern for HLS segments
            segment_duration: Segment duration in seconds
            audio_stream_index: Specific audio stream index (None = default)
            start_time: Seek position in seconds
        """

        cmd = ["ffmpeg", "-y"]

        # Fast seek (before input for speed)
        if start_time and start_time > 0:
            cmd.extend(["-ss", str(start_time)])

        cmd.extend(["-i", input_path])

        # Stream mapping (using absolute stream indices from database)
        if audio_stream_index is not None:
            # Map specific video and audio streams
            cmd.extend(["-map", "0:v:0", "-map", f"0:{audio_stream_index}"])
        else:
            # Map first video and all audio by default
            cmd.extend(["-map", "0:v:0", "-map", "0:a?"])

        # Copy codecs (no re-encoding)
        cmd.extend(["-c", "copy"])

        # Fix timestamp issues and preserve duration metadata
        cmd.extend(["-copyts", "-start_at_zero", "-avoid_negative_ts", "make_zero"])

        # HLS specific settings optimized for remux
        cmd.extend([
            "-f",
            "hls",
            "-hls_time",
            str(segment_duration),
            "-hls_playlist_type",
            "event",
            "-hls_segment_filename",
            segment_pattern,
            "-start_number",
            "0",
            "-hls_allow_cache",
            "1",
            "-hls_flags",
            "delete_segments+append_list+program_date_time",
            playlist_path,
        ])

        return cmd

    def _build_hls_command(  # noqa: C901
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
        audio_stream_index: int | None = None,
        subtitle_stream_index: int | None = None,
        start_time: float | None = None,
    ) -> list[str]:
        """Build FFmpeg command for HLS transcoding.

        Args:
            input_path: Path to input media file
            playlist_path: Path for HLS playlist
            segment_pattern: Pattern for HLS segments
            video_codec: Target video codec (h264, hevc, copy)
            audio_codec: Target audio codec (aac, mp3, copy)
            video_bitrate: Target video bitrate
            audio_bitrate: Target audio bitrate
            max_width: Maximum width for scaling
            max_height: Maximum height for scaling
            segment_duration: Segment duration in seconds
            audio_stream_index: Specific audio stream index (None = default)
            subtitle_stream_index: Subtitle stream to burn (None = no burn)
            start_time: Seek position in seconds
        """

        cmd = ["ffmpeg", "-y"]

        # Hardware acceleration initialization for VAAPI
        if self.hw_accel.vaapi_available and self.hw_accel.vaapi_device and video_codec != "copy":
            cmd.extend(["-vaapi_device", self.hw_accel.vaapi_device])

        # Fast seek (before input for speed)
        if start_time and start_time > 0:
            cmd.extend(["-ss", str(start_time)])

        cmd.extend(["-i", input_path])

        # Stream mapping (using absolute stream indices from database)
        if audio_stream_index is not None:
            cmd.extend(["-map", "0:v:0", "-map", f"0:{audio_stream_index}"])
        else:
            cmd.extend(["-map", "0:v:0", "-map", "0:a:0?"])

        # Get the best encoder for video
        encoder, encoder_args = self.hw_accel.get_video_encoder(video_codec)
        cmd.extend(["-c:v", encoder])

        # Video encoding settings
        if encoder != "copy":
            cmd.extend(encoder_args)

            # Add pixel format for compatibility
            if "vaapi" in encoder:
                # VAAPI needs format conversion
                pass  # Will be handled in filter
            else:
                cmd.extend(["-pix_fmt", "yuv420p"])

        # Audio codec
        cmd.extend(["-c:a", audio_codec])

        # Audio encoding settings
        if audio_codec == "aac":
            cmd.extend([
                "-profile:a",
                "aac_low",
                "-ar",
                "48000",  # Sample rate for better HLS compatibility
                "-ac",
                "2",  # Stereo output for compatibility
            ])
        if audio_bitrate and audio_codec != "copy":
            cmd.extend(["-b:a", str(audio_bitrate)])

        # Video bitrate
        if video_bitrate and encoder != "copy":
            cmd.extend([
                "-b:v",
                str(video_bitrate),
                "-maxrate",
                str(int(video_bitrate * 1.2)),
                "-bufsize",
                str(video_bitrate * 2),
            ])

        # Build video filter chain
        vf_filters = []

        # VAAPI upload filter
        if "vaapi" in encoder:
            vf_filters.append("format=nv12")
            vf_filters.append("hwupload")

        # Resolution scaling
        if (max_width or max_height) and encoder != "copy":
            if "vaapi" in encoder:
                if max_width and max_height:
                    vf_filters.append(
                        f"scale_vaapi=w='min({max_width},iw)':h='min({max_height},ih)':force_original_aspect_ratio=decrease"
                    )
                elif max_width:
                    vf_filters.append(f"scale_vaapi=w={max_width}:h=-2")
                else:
                    vf_filters.append(f"scale_vaapi=w=-2:h={max_height}")
            else:
                if max_width and max_height:
                    vf_filters.append(
                        f"scale='min({max_width},iw)':'min({max_height},ih)':force_original_aspect_ratio=decrease"
                    )
                elif max_width:
                    vf_filters.append(f"scale={max_width}:-2")
                else:
                    vf_filters.append(f"scale=-2:{max_height}")

        # Subtitle burning (for image-based subtitles)
        if subtitle_stream_index is not None and encoder != "copy":
            # Use subtitles filter for burning
            # Note: For VAAPI, we need to download, burn, and re-upload
            if "vaapi" in encoder:
                # Insert before hwupload
                vf_filters.insert(0, f"subtitles='{input_path}':stream_index={subtitle_stream_index}")
            else:
                vf_filters.append(f"subtitles='{input_path}':stream_index={subtitle_stream_index}")

        # Apply video filters
        if vf_filters and encoder != "copy":
            cmd.extend(["-vf", ",".join(vf_filters)])

        # Preserve timestamps for accurate duration
        cmd.extend(["-copyts", "-start_at_zero"])

        # HLS specific settings
        cmd.extend([
            "-f",
            "hls",
            "-hls_time",
            str(segment_duration),
            "-hls_playlist_type",
            "event",
            "-hls_segment_type",
            "mpegts",  # Explicit TS segments for better compatibility
            "-hls_segment_filename",
            segment_pattern,
            "-start_number",
            "0",
            "-hls_allow_cache",
            "1",
            "-hls_flags",
            "delete_segments+append_list+program_date_time",
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
                    stderr_output = (await process.stderr.read()).decode("utf-8", errors="ignore")
                await self._mark_job_failed(
                    job_id,
                    f"FFmpeg exited with code {process.returncode}: {stderr_output}",
                )

        except Exception as e:
            await self._mark_job_failed(job_id, f"Progress monitoring failed: {e}")

        finally:
            # Remove from active jobs
            self._active_jobs.pop(job_id, None)

    def _parse_ffmpeg_progress(self, line: str, total_duration: float | None) -> dict[str, Any] | None:
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
                progress["progress_percent"] = min(100.0, (current_seconds / total_duration) * 100)

        # Extract current bitrate
        if match := self.progress_patterns["bitrate"].search(line):
            bitrate_kbps = float(match.group(1))
            progress["current_bitrate"] = int(bitrate_kbps * 1000)  # Convert to bps

        return progress if progress else None

    async def _update_job_progress(self, job_id: str, progress_data: dict[str, Any]) -> None:
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
            result = await session.execute(select(TranscodingJob).where(TranscodingJob.id == job_id))
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
                    logger.info(f"Cleaned up {cleaned} old transcoding jobs")
            except Exception as e:
                logger.error(f"Cleanup scheduler error: {e}")

    async def extract_subtitle_to_webvtt(
        self,
        media_file_path: str,
        subtitle_stream_index: int,
        output_path: str,
    ) -> bool:
        """Extract a subtitle stream to WebVTT format.

        Args:
            media_file_path: Path to the media file
            subtitle_stream_index: Absolute stream index of the subtitle to extract
            output_path: Path for the output WebVTT file

        Returns:
            True if extraction succeeded, False otherwise
        """
        # Use absolute stream index (0:{index}) not relative (0:s:{index})
        cmd = [
            "ffmpeg",
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
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(process.communicate(), timeout=120)

            if process.returncode != 0:
                logger.error(f"Subtitle extraction failed: {stderr.decode()}")
                return False

            return Path(output_path).exists()

        except TimeoutError:
            logger.error("Subtitle extraction timed out")
            return False
        except Exception as e:
            logger.error(f"Subtitle extraction error: {e}")
            return False

    def is_text_subtitle(self, codec: str) -> bool:
        """Check if a subtitle codec is text-based (can be extracted to WebVTT)."""
        return codec.lower() in TEXT_SUBTITLE_CODECS

    def is_image_subtitle(self, codec: str) -> bool:
        """Check if a subtitle codec is image-based (must be burned)."""
        return codec.lower() in IMAGE_SUBTITLE_CODECS


# Global transcoder instance
_transcoder: FFmpegTranscoder | None = None


def get_transcoder() -> FFmpegTranscoder:
    """Get the global transcoder instance."""
    global _transcoder
    if _transcoder is None:
        _transcoder = FFmpegTranscoder()
    return _transcoder
