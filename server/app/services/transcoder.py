import asyncio
import logging
import os
import re
import shlex
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select, update

from app.database import async_session_maker
from app.models import MediaFile, TranscodingJob
from app.models.transcoding import TranscodingJobStatus
from app.services.transcoding.codecs import IMAGE_SUBTITLE_CODECS, TEXT_SUBTITLE_CODECS
from app.services.transcoding.commands import HlsCommandBuilder, HlsCommandOptions
from app.services.transcoding.files import remove_output_path, terminate_process
from app.services.transcoding.hardware import HardwareAcceleration, HardwareAccelerationStatus
from app.services.transcoding.subtitles import extract_subtitle_to_webvtt

logger = logging.getLogger(__name__)

STALE_RUNNING_JOB_AFTER = timedelta(minutes=10)
HLS_PLAYLIST_STARTUP_TIMEOUT = 120.0
HLS_REMUX_PLAYLIST_STARTUP_TIMEOUT = 60.0


def _float_from_env(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        return default
    return max(value, 1.0)


class FFmpegTranscoder:
    def __init__(self, temp_dir: str | None = None, ffmpeg_path: str | None = None):
        self.ffmpeg_path = ffmpeg_path or os.getenv("FERELIX_FFMPEG_PATH", "ffmpeg")
        self.temp_dir = Path(temp_dir or os.getenv("FERELIX_TRANSCODE_DIR", "/tmp/ferelix-transcode"))
        self.temp_dir.mkdir(parents=True, exist_ok=True, mode=0o755)
        self.temp_dir.chmod(0o755)

        self._active_jobs: dict[str, asyncio.subprocess.Process] = {}
        self._background_tasks: set[asyncio.Task[None]] = set()

        self.hw_accel = HardwareAcceleration(self.ffmpeg_path)
        self.hw_accel.detect()
        self.commands = HlsCommandBuilder(self.ffmpeg_path, self.hw_accel)

        self.progress_patterns = {
            "frame": re.compile(r"frame=\s*(\d+)"),
            "fps": re.compile(r"fps=\s*([\d.]+)"),
            "time": re.compile(r"time=(\d{2}):(\d{2}):([\d.]+)"),
            "bitrate": re.compile(r"bitrate=\s*([\d.]+)kbits/s"),
        }

    def set_hardware_device(self, device_id: str | None) -> None:
        """Select the hardware device to use for future transcoding jobs."""
        self.hw_accel.set_selected_device(device_id)

    def hardware_status(self) -> HardwareAccelerationStatus:
        """Return cached hardware acceleration detection status."""
        return self.hw_accel.status()

    def refresh_hardware_status(self) -> HardwareAccelerationStatus:
        """Refresh hardware acceleration detection status."""
        return self.hw_accel.refresh()

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
        hls_segment_type = self._copy_hls_segment_type(media_file) if video_codec == "copy" else "mpegts"
        job_dir, playlist_path, segment_pattern = self._prepare_job_paths(job_id, hls_segment_type)
        burn_subtitle, is_image_subtitle = self._subtitle_burn_options(media_file, subtitle_stream_index)
        cmd = self.commands.build_transcode(
            HlsCommandOptions(
                input_path=media_file.file_path,
                playlist_path=str(playlist_path),
                segment_pattern=segment_pattern,
                source_video_codec=self._source_video_codec(media_file),
                video_codec=video_codec,
                audio_codec=audio_codec,
                video_bitrate=video_bitrate,
                audio_bitrate=audio_bitrate,
                max_width=max_width,
                max_height=max_height,
                segment_duration=segment_duration,
                audio_stream_index=audio_stream_index,
                subtitle_stream_index=subtitle_stream_index if burn_subtitle else None,
                is_image_subtitle=is_image_subtitle,
                start_time=start_time,
                hls_segment_type=hls_segment_type,
            )
        )

        await self._mark_job_running(
            job_id,
            cmd,
            job_dir,
            playlist_path,
            session_id,
            client_ip,
            user_agent,
            start_time=start_time,
            video_codec=video_codec,
            audio_codec=audio_codec,
            video_bitrate=video_bitrate,
            audio_bitrate=audio_bitrate,
            max_width=max_width,
            max_height=max_height,
        )
        return await self._launch_ffmpeg(
            job_id,
            media_file.duration,
            cmd,
            playlist_path,
            _float_from_env("FERELIX_HLS_PLAYLIST_STARTUP_TIMEOUT", HLS_PLAYLIST_STARTUP_TIMEOUT),
            "transcoding",
        )

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
        hls_segment_type = self._copy_hls_segment_type(media_file)
        job_dir, playlist_path, segment_pattern = self._prepare_job_paths(job_id, hls_segment_type)
        cmd = self.commands.build_remux(
            input_path=media_file.file_path,
            playlist_path=str(playlist_path),
            segment_pattern=segment_pattern,
            segment_duration=segment_duration,
            audio_stream_index=audio_stream_index,
            start_time=start_time,
            hls_segment_type=hls_segment_type,
        )

        await self._mark_job_running(
            job_id,
            cmd,
            job_dir,
            playlist_path,
            session_id,
            client_ip,
            user_agent,
            start_time=start_time,
            video_codec="copy",
            audio_codec="copy",
        )
        return await self._launch_ffmpeg(
            job_id,
            media_file.duration,
            cmd,
            playlist_path,
            _float_from_env("FERELIX_HLS_REMUX_PLAYLIST_STARTUP_TIMEOUT", HLS_REMUX_PLAYLIST_STARTUP_TIMEOUT),
            "remuxing",
        )

    async def stop_job(self, job_id: str) -> bool:
        """Gracefully stop a running transcoding job."""
        process = self._active_jobs.get(job_id)
        if not process:
            output_path = await self._cancel_persisted_job(job_id, terminate_by_pid=True)
            if output_path is None:
                return False
            remove_output_path(output_path)
            return True

        try:
            if process.stdin and not process.stdin.is_closing():
                process.stdin.write(b"q\n")
                await process.stdin.drain()
                process.stdin.close()

            try:
                await asyncio.wait_for(process.wait(), timeout=10.0)
            except TimeoutError:
                process.kill()
                await process.wait()

            output_path = await self._set_terminal_status(job_id, TranscodingJobStatus.CANCELLED)
            remove_output_path(output_path)
            return True
        except Exception as exc:
            await self._mark_job_failed(job_id, f"Failed to stop job: {exc}")
            return False
        finally:
            self._active_jobs.pop(job_id, None)

    async def cleanup_transcode_files(self) -> int:
        """Clean up files and rows for terminal jobs and stale running jobs."""
        cleanup_count = 0
        now = datetime.now(UTC)
        async with async_session_maker() as session:
            result = await session.execute(
                select(TranscodingJob).where(
                    TranscodingJob.output_path.isnot(None),
                )
            )
            for job in result.scalars().all():
                if job.status == TranscodingJobStatus.RUNNING:
                    if not self._is_stale(job.last_accessed_at, now):
                        continue
                    if job.process_id:
                        terminate_process(job.process_id)
                    logger.info("Cleaning up stale transcoding job %s", job.id)

                remove_output_path(job.output_path)
                await session.delete(job)
                cleanup_count += 1

            await session.commit()

        if cleanup_count:
            logger.info("Cleaned up %s transcoding jobs and their files", cleanup_count)
        return cleanup_count

    async def cleanup_stalled_jobs(self) -> int:
        """Clean up all persisted transcode files after server restart."""
        cleanup_count = 0
        async with async_session_maker() as session:
            result = await session.execute(select(TranscodingJob).where(TranscodingJob.output_path.isnot(None)))
            for job in result.scalars().all():
                if job.status == TranscodingJobStatus.RUNNING and job.process_id:
                    terminate_process(job.process_id)

                remove_output_path(job.output_path)
                await session.delete(job)
                cleanup_count += 1

            await session.commit()

        if cleanup_count:
            logger.info("Cleaned up %s stalled transcoding jobs at startup", cleanup_count)
        return cleanup_count

    async def get_job_status(self, job_id: str) -> TranscodingJob | None:
        """Get current status of a transcoding job."""
        async with async_session_maker() as session:
            result = await session.execute(select(TranscodingJob).where(TranscodingJob.id == job_id))
            return result.scalar_one_or_none()

    async def extract_subtitle_to_webvtt(
        self,
        media_file_path: str,
        subtitle_stream_index: int,
        output_path: str,
    ) -> bool:
        """Extract a subtitle stream to WebVTT format."""
        return await extract_subtitle_to_webvtt(
            self.ffmpeg_path,
            media_file_path,
            subtitle_stream_index,
            output_path,
        )

    def _prepare_job_paths(self, job_id: str, hls_segment_type: str = "mpegts") -> tuple[Path, Path, str]:
        job_dir = self.temp_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True, mode=0o755)
        job_dir.chmod(0o755)
        playlist_path = job_dir / "playlist.m3u8"
        segment_extension = "m4s" if hls_segment_type == "fmp4" else "ts"
        return job_dir, playlist_path, str(job_dir / f"segment_%03d.{segment_extension}")

    def _copy_hls_segment_type(self, media_file: MediaFile) -> str:
        video_codec = (media_file.video_tracks[0].codec or "").lower() if media_file.video_tracks else ""
        return "fmp4" if video_codec in {"hevc", "h265", "av1", "vp9"} else "mpegts"

    def _source_video_codec(self, media_file: MediaFile) -> str | None:
        if media_file.video_tracks:
            return media_file.video_tracks[0].codec
        return media_file.codec

    def _subtitle_burn_options(
        self,
        media_file: MediaFile,
        subtitle_stream_index: int | None,
    ) -> tuple[bool, bool]:
        if subtitle_stream_index is None or not media_file.subtitle_tracks:
            return False, False

        for track in media_file.subtitle_tracks:
            if track.stream_index != subtitle_stream_index or not track.codec:
                continue

            codec = track.codec.lower()
            if codec in IMAGE_SUBTITLE_CODECS:
                logger.info("Burning image subtitle stream %s (%s)", subtitle_stream_index, codec)
                return True, True
            if codec in TEXT_SUBTITLE_CODECS:
                logger.info("Burning text subtitle stream %s (%s)", subtitle_stream_index, codec)
                return True, False

        logger.warning("Requested subtitle stream %s is not burnable", subtitle_stream_index)
        return False, False

    async def _mark_job_running(
        self,
        job_id: str,
        cmd: list[str],
        job_dir: Path,
        playlist_path: Path,
        session_id: str | None,
        client_ip: str | None,
        user_agent: str | None,
        **settings: Any,
    ) -> None:
        values = {
            "status": TranscodingJobStatus.RUNNING,
            "started_at": datetime.now(UTC),
            "ffmpeg_command": shlex.join(cmd),
            "output_path": str(job_dir),
            "playlist_path": str(playlist_path),
            "session_id": session_id,
            "client_ip": client_ip,
            "user_agent": user_agent,
            **settings,
        }
        async with async_session_maker() as session:
            await session.execute(update(TranscodingJob).where(TranscodingJob.id == job_id).values(**values))
            await session.commit()

    async def _launch_ffmpeg(
        self,
        job_id: str,
        total_duration: float | None,
        cmd: list[str],
        playlist_path: Path,
        playlist_timeout: float,
        operation: str,
    ) -> str:
        try:
            logger.info("Starting ffmpeg job %s: %s", job_id, " ".join(cmd))
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.PIPE,
            )
            await self._ensure_process_running(job_id, process)
            self._active_jobs[job_id] = process
            await self._set_process_id(job_id, process.pid)

            task = asyncio.create_task(self._monitor_progress(job_id, process, total_duration))
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

            task = asyncio.create_task(self._watch_playlist_startup(job_id, process, playlist_path, playlist_timeout))
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)
            return str(playlist_path)
        except Exception as exc:
            await self._mark_job_failed(job_id, str(exc))
            logger.error("Failed to start %s job %s: %s", operation, job_id, exc)
            raise HTTPException(status_code=500, detail=f"Failed to start {operation}: {exc}") from exc

    async def _ensure_process_running(self, job_id: str, process: asyncio.subprocess.Process) -> None:
        try:
            await asyncio.wait_for(process.wait(), timeout=0.1)
        except TimeoutError:
            logger.info("FFmpeg process %s started successfully for job %s", process.pid, job_id)
            return

        stderr = await process.stderr.read() if process.stderr else b""
        stderr_text = stderr.decode("utf-8", errors="ignore")
        logger.error("FFmpeg job %s exited immediately with code %s: %s", job_id, process.returncode, stderr_text)
        raise RuntimeError(f"FFmpeg exited immediately with code {process.returncode}: {stderr_text}")

    async def _watch_playlist_startup(
        self,
        job_id: str,
        process: asyncio.subprocess.Process,
        playlist_path: Path,
        timeout_seconds: float,
    ) -> None:
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        while asyncio.get_running_loop().time() < deadline:
            if playlist_path.exists():
                return
            if process.returncode is not None:
                return
            await asyncio.sleep(0.5)

        if process.returncode is None:
            message = f"FFmpeg did not create an HLS playlist within {int(timeout_seconds)} seconds"
            logger.error("%s for job %s at %s", message, job_id, playlist_path)
            await self._mark_job_failed(job_id, message)
            process.kill()
            await process.wait()

    async def _monitor_progress(
        self,
        job_id: str,
        process: asyncio.subprocess.Process,
        total_duration: float | None,
    ) -> None:
        stderr_lines: list[str] = []
        job_start_time = await self._get_job_start_time(job_id)

        try:
            while process.stderr:
                line_bytes = await process.stderr.readline()
                if not line_bytes:
                    break

                line = line_bytes.decode("utf-8", errors="ignore").strip()
                if not line:
                    continue

                stderr_lines.append(line)
                if progress_data := self._parse_ffmpeg_progress(line, total_duration, job_start_time):
                    await self._update_job_progress(job_id, progress_data)

            await process.wait()
            if await self._job_has_status(job_id, TranscodingJobStatus.CANCELLED):
                return
            if await self._job_has_status(job_id, TranscodingJobStatus.FAILED):
                return
            if process.returncode == 0:
                await self._mark_job_completed(job_id)
            else:
                summary = self._summarize_stderr(process.returncode, stderr_lines)
                logger.error("FFmpeg job %s failed: %s", job_id, summary)
                await self._mark_job_failed(job_id, summary)
        except Exception as exc:
            logger.error("Progress monitoring failed for FFmpeg job %s: %s", job_id, exc)
            await self._mark_job_failed(job_id, f"Progress monitoring failed: {exc}")
        finally:
            self._active_jobs.pop(job_id, None)

    def _parse_ffmpeg_progress(
        self,
        line: str,
        total_duration: float | None,
        job_start_time: float | None,
    ) -> dict[str, Any] | None:
        if "frame=" not in line or "time=" not in line:
            return None

        progress: dict[str, Any] = {}
        if match := self.progress_patterns["frame"].search(line):
            progress["frame"] = int(match.group(1))
        if match := self.progress_patterns["fps"].search(line):
            progress["current_fps"] = float(match.group(1))
        if match := self.progress_patterns["bitrate"].search(line):
            progress["current_bitrate"] = int(float(match.group(1)) * 1000)

        if match := self.progress_patterns["time"].search(line):
            hours, minutes, seconds = match.groups()
            current_seconds = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
            if job_start_time is not None:
                current_seconds = max(0.0, current_seconds - float(job_start_time))

            progress["transcoded_duration"] = current_seconds
            if total_duration and total_duration > 0:
                progress["progress_percent"] = min(100.0, (current_seconds / total_duration) * 100)

        return progress or None

    async def _get_job_start_time(self, job_id: str) -> float | None:
        try:
            async with async_session_maker() as session:
                result = await session.execute(select(TranscodingJob.start_time).where(TranscodingJob.id == job_id))
                return result.scalar_one_or_none()
        except Exception:
            return None

    async def _update_job_progress(self, job_id: str, progress_data: dict[str, Any]) -> None:
        async with async_session_maker() as session:
            await session.execute(
                update(TranscodingJob)
                .where(TranscodingJob.id == job_id)
                .values(
                    progress_percent=progress_data.get("progress_percent"),
                    transcoded_duration=progress_data.get("transcoded_duration"),
                    current_fps=progress_data.get("current_fps"),
                    current_bitrate=progress_data.get("current_bitrate"),
                    last_accessed_at=datetime.now(UTC),
                )
            )
            await session.commit()

    async def _mark_job_completed(self, job_id: str) -> None:
        async with async_session_maker() as session:
            await session.execute(
                update(TranscodingJob)
                .where(TranscodingJob.id == job_id)
                .values(
                    status=TranscodingJobStatus.COMPLETED,
                    completed_at=datetime.now(UTC),
                    progress_percent=100.0,
                )
            )
            await session.commit()

    async def _mark_job_failed(self, job_id: str, error_message: str) -> None:
        async with async_session_maker() as session:
            await session.execute(
                update(TranscodingJob)
                .where(TranscodingJob.id == job_id)
                .values(
                    status=TranscodingJobStatus.FAILED,
                    error_message=error_message,
                    completed_at=datetime.now(UTC),
                )
            )
            await session.commit()

    async def _set_process_id(self, job_id: str, process_id: int | None) -> None:
        async with async_session_maker() as session:
            await session.execute(
                update(TranscodingJob).where(TranscodingJob.id == job_id).values(process_id=process_id)
            )
            await session.commit()

    async def _set_terminal_status(self, job_id: str, status: TranscodingJobStatus) -> str | None:
        async with async_session_maker() as session:
            result = await session.execute(select(TranscodingJob.output_path).where(TranscodingJob.id == job_id))
            output_path = result.scalar_one_or_none()
            await session.execute(
                update(TranscodingJob)
                .where(TranscodingJob.id == job_id)
                .values(status=status, completed_at=datetime.now(UTC))
            )
            await session.commit()
            return output_path

    async def _cancel_persisted_job(self, job_id: str, terminate_by_pid: bool) -> str | None:
        async with async_session_maker() as session:
            job = await session.get(TranscodingJob, job_id)
            if not job:
                return None

            if terminate_by_pid and job.process_id:
                terminate_process(job.process_id)

            output_path = job.output_path
            job.status = TranscodingJobStatus.CANCELLED
            job.completed_at = datetime.now(UTC)
            await session.commit()
            return output_path

    async def _job_has_status(self, job_id: str, status: TranscodingJobStatus) -> bool:
        async with async_session_maker() as session:
            result = await session.execute(select(TranscodingJob.status).where(TranscodingJob.id == job_id))
            return result.scalar_one_or_none() == status

    def _is_stale(self, last_accessed_at: datetime | None, now: datetime) -> bool:
        if last_accessed_at is None:
            return True
        if last_accessed_at.tzinfo is None:
            last_accessed_at = last_accessed_at.replace(tzinfo=UTC)
        return last_accessed_at < now - STALE_RUNNING_JOB_AFTER

    def _summarize_stderr(self, returncode: int | None, stderr_lines: list[str]) -> str:
        if not stderr_lines:
            return f"FFmpeg exited with code {returncode}: No error output captured"

        error_lines: list[str] = []
        capture_errors = False
        for line in stderr_lines:
            if any(marker in line.lower() for marker in ["error", "failed", "invalid", "unable", "could not"]):
                capture_errors = True
            if capture_errors:
                error_lines.append(line)

        output = "\n".join(error_lines[-30:] if error_lines else stderr_lines[-20:])
        return f"FFmpeg exited with code {returncode}: {output}"


_transcoder: FFmpegTranscoder | None = None


def get_transcoder() -> FFmpegTranscoder:
    """Get the global transcoder instance."""
    global _transcoder
    if _transcoder is None:
        _transcoder = FFmpegTranscoder()
    return _transcoder
