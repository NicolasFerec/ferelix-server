"""Playback session helpers for direct, remux, and transcoded streaming."""

import logging
import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import MediaFile, Settings, TranscodingJob
from app.models.playback import PlayMethod, StreamInfo
from app.models.transcoding import TranscodingJobStatus, TranscodingJobType
from app.services.transcoder import get_transcoder

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ClientContext:
    """Request metadata stored on a transcoding job."""

    client_ip: str | None = None
    user_agent: str | None = None


@dataclass(slots=True)
class HlsStartOptions:
    """Options used to start an HLS job."""

    job_type: TranscodingJobType
    video_codec: str = "h264"
    audio_codec: str = "aac"
    video_bitrate: int | None = None
    audio_bitrate: int | None = None
    max_width: int | None = None
    max_height: int | None = None
    audio_stream_index: int | None = None
    subtitle_stream_index: int | None = None
    start_time: float | None = None
    playback_session_id: str | None = None


class PlaybackSessionService:
    """Create and manage playback-oriented transcoding jobs."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.transcoder = get_transcoder()

    async def get_media_file(self, media_id: int) -> MediaFile:
        """Load a media file with all stream metadata and verify it still exists."""
        result = await self.session.execute(
            select(MediaFile)
            .options(
                selectinload(MediaFile.video_tracks),
                selectinload(MediaFile.audio_tracks),
                selectinload(MediaFile.subtitle_tracks),
            )
            .where(MediaFile.id == media_id)
        )
        media_file = result.scalar_one_or_none()

        if not media_file:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media file not found")

        if not Path(media_file.file_path).exists():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media file not found on disk")

        return media_file

    async def cleanup_previous_sessions(self, media_id: int, exclude_job_id: str | None = None) -> int:
        """Stop previous running HLS jobs for the same media file.

        Ferelix currently runs one active generated HLS timeline per media item,
        similar to Jellyfin restarting an active encoding when a player jumps to
        a new segment range.
        """
        query = select(TranscodingJob).where(
            TranscodingJob.media_file_id == media_id,
            TranscodingJob.status == TranscodingJobStatus.RUNNING,
        )
        if exclude_job_id:
            query = query.where(TranscodingJob.id != exclude_job_id)

        result = await self.session.execute(query)
        previous_jobs = result.scalars().all()
        cleanup_count = 0

        for job in previous_jobs:
            try:
                await self.transcoder.stop_job(job.id)
                job.status = TranscodingJobStatus.CANCELLED
                job.completed_at = func.now()
                cleanup_count += 1
            except Exception as exc:
                logger.warning("Failed to clean up previous job %s: %s", job.id, exc)

        if cleanup_count:
            await self.session.commit()

        return cleanup_count

    async def start_hls_job(
        self,
        media_id: int,
        options: HlsStartOptions,
        client: ClientContext | None = None,
    ) -> TranscodingJob:
        """Create and start a transcoding job for a media item."""
        client = client or ClientContext()
        media_file = await self.get_media_file(media_id)
        session_id = options.playback_session_id or str(uuid.uuid4())
        job_id = str(uuid.uuid4())

        job = TranscodingJob(
            id=job_id,
            media_file_id=media_id,
            type=options.job_type,
            status=TranscodingJobStatus.PENDING,
            session_id=session_id,
            client_ip=client.client_ip,
            user_agent=client.user_agent,
            video_codec=options.video_codec,
            audio_codec=options.audio_codec,
            video_bitrate=options.video_bitrate,
            audio_bitrate=options.audio_bitrate,
            max_width=options.max_width,
            max_height=options.max_height,
            start_time=options.start_time,
        )

        self.session.add(job)
        await self.session.commit()
        await self.session.refresh(job)

        try:
            if options.job_type != TranscodingJobType.REMUX:
                await self._sync_hardware_device()

            if options.job_type == TranscodingJobType.REMUX:
                await self.transcoder.start_remux_hls(
                    job_id=job_id,
                    media_file=media_file,
                    session_id=session_id,
                    client_ip=client.client_ip,
                    user_agent=client.user_agent,
                    audio_stream_index=options.audio_stream_index,
                    start_time=options.start_time,
                )
            else:
                await self.transcoder.start_hls_transcode(
                    job_id=job_id,
                    media_file=media_file,
                    video_codec=options.video_codec,
                    audio_codec=options.audio_codec,
                    video_bitrate=options.video_bitrate,
                    audio_bitrate=options.audio_bitrate,
                    max_width=options.max_width,
                    max_height=options.max_height,
                    session_id=session_id,
                    client_ip=client.client_ip,
                    user_agent=client.user_agent,
                    audio_stream_index=options.audio_stream_index,
                    subtitle_stream_index=options.subtitle_stream_index,
                    start_time=options.start_time,
                )

            await self.session.refresh(job)
            return job
        except Exception:
            await self.session.refresh(job)
            raise

    async def _sync_hardware_device(self) -> None:
        settings = await self.session.get(Settings, 1)
        self.transcoder.set_hardware_device(settings.hardware_transcoding_device if settings else "auto")

    async def start_from_stream_info(
        self,
        media_id: int,
        stream_info: StreamInfo,
        client: ClientContext | None = None,
    ) -> dict[str, str]:
        """Start the server-side work implied by a playback decision."""
        if stream_info.PlayMethod == PlayMethod.DIRECT_PLAY:
            return {
                "method": "direct_play",
                "url": f"/api/v1/stream/{media_id}",
                "message": "Use direct streaming endpoint",
            }

        settings = stream_info.TranscodeSettings
        if stream_info.PlayMethod == PlayMethod.DIRECT_STREAM and stream_info.IsRemuxOnly:
            job = await self.start_hls_job(
                media_id,
                HlsStartOptions(
                    job_type=TranscodingJobType.REMUX,
                    audio_stream_index=getattr(settings, "AudioStreamIndex", None),
                ),
                client,
            )
            return _hls_response("hls_remux", job.id, "HLS remuxing started")

        job_type = (
            TranscodingJobType.AUDIO_TRANSCODE
            if stream_info.TranscodingType == "audio-only"
            else TranscodingJobType.HLS
        )
        job = await self.start_hls_job(
            media_id,
            HlsStartOptions(
                job_type=job_type,
                video_codec=getattr(settings, "VideoCodec", None) or stream_info.TranscodingVideoCodec or "h264",
                audio_codec=getattr(settings, "AudioCodec", None) or stream_info.TranscodingAudioCodec or "aac",
                video_bitrate=getattr(settings, "VideoBitrate", None),
                audio_bitrate=getattr(settings, "AudioBitrate", None),
                max_width=getattr(settings, "MaxWidth", None),
                max_height=getattr(settings, "MaxHeight", None),
            ),
            client,
        )
        return _hls_response("hls_transcode", job.id, "HLS transcoding started")


def _hls_response(method: str, job_id: str, message: str) -> dict[str, str]:
    return {
        "method": method,
        "job_id": job_id,
        "playlist_url": f"/api/v1/hls/{job_id}/playlist.m3u8",
        "status_url": f"/api/v1/hls/{job_id}/status",
        "message": message,
    }
