"""Playback session helpers for direct, remux, and transcoded streaming."""

import asyncio
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from weakref import WeakValueDictionary

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import MediaFile, PlaybackSession, PlaybackSessionStatus, Settings, TranscodingJob
from app.models.playback import PlayMethod, StreamInfo
from app.models.transcoding import TranscodingJobStatus, TranscodingJobType
from app.services.scanner import MetadataExtractionError, extract_video_metadata
from app.services.stream_builder import select_audio_track, select_video_track
from app.services.transcoder import get_transcoder

logger = logging.getLogger(__name__)
_session_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()


@dataclass(slots=True)
class ClientContext:
    """Request metadata stored on a transcoding job."""

    client_ip: str | None = None
    user_agent: str | None = None


@dataclass(slots=True)
class HlsStartOptions:
    """Options used to start an HLS job."""

    job_type: TranscodingJobType
    playback_session_id: str
    playback_generation: int
    video_codec: str = "h264"
    audio_codec: str = "aac"
    video_bitrate: int | None = None
    audio_bitrate: int | None = None
    max_width: int | None = None
    max_height: int | None = None
    max_frame_rate: float | None = None
    video_stream_index: int | None = None
    audio_stream_index: int | None = None
    subtitle_stream_index: int | None = None
    start_time: float | None = None


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

        if not (await asyncio.to_thread(Path(media_file.file_path).exists)):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media file not found on disk")

        return media_file

    async def start_hls_job(
        self,
        media_id: int,
        options: HlsStartOptions,
        client: ClientContext | None = None,
    ) -> TranscodingJob:
        """Claim a monotone playback intent, then replace its encoder under a local lock."""
        media_file = await self.get_media_file(media_id)
        await self._claim_playback_intent(media_id, options.playback_session_id, options.playback_generation)
        lock = _session_locks.setdefault(options.playback_session_id, asyncio.Lock())
        async with lock:
            await self._require_current_intent(options.playback_session_id, options.playback_generation)
            await self._stop_previous_jobs(options.playback_session_id)
            await self._require_current_intent(options.playback_session_id, options.playback_generation)
            return await self._start_hls_job_locked(media_id, media_file, options, client or ClientContext())

    async def _claim_playback_intent(self, media_id: int, session_id: str, generation: int) -> None:
        claimed = await self.session.scalar(
            update(PlaybackSession)
            .where(
                PlaybackSession.id == session_id,
                PlaybackSession.media_file_id == media_id,
                PlaybackSession.status == PlaybackSessionStatus.ACTIVE,
                PlaybackSession.playback_generation < generation,
            )
            .values(playback_generation=generation)
            .returning(PlaybackSession.id)
        )
        await self.session.commit()
        if claimed is None:
            raise HTTPException(status_code=410, detail="Playback intent was superseded or session ended")

    async def _stop_previous_jobs(self, session_id: str) -> None:
        jobs = list(
            await self.session.scalars(select(TranscodingJob.id).where(TranscodingJob.session_id == session_id))
        )
        # Release any read transaction before waiting for FFmpeg's monitor.
        await self.session.commit()
        for job_id in jobs:
            if not await self.transcoder.stop_job(job_id):
                raise HTTPException(status_code=503, detail="Could not stop the previous playback timeline")

    async def _require_current_intent(self, session_id: str, generation: int) -> PlaybackSession:
        playback = await self.session.get(PlaybackSession, session_id, populate_existing=True)
        if (
            playback is None
            or playback.status != PlaybackSessionStatus.ACTIVE
            or playback.playback_generation != generation
        ):
            raise HTTPException(status_code=410, detail="Playback intent was superseded or session ended")
        return playback

    async def _start_hls_job_locked(
        self, media_id: int, media_file: MediaFile, options: HlsStartOptions, client: ClientContext
    ) -> TranscodingJob:
        # Older scans read the wrong ffprobe field for transfer characteristics.
        # Repair wide-gamut metadata before deciding how to convert HDR to SDR.
        if options.video_codec != "copy" and any(
            track.color_transfer is None and track.color_space == "bt2020nc" for track in media_file.video_tracks
        ):
            try:
                metadata = await asyncio.to_thread(extract_video_metadata, Path(media_file.file_path))
            except MetadataExtractionError:
                logger.warning("Could not refresh HDR metadata for media %s; keeping scanned tracks", media_id)
                metadata = {}
            for track in media_file.video_tracks:
                for scanned in metadata.get("video_tracks", []):
                    if scanned.get("stream_index") == track.stream_index:
                        track.color_transfer = scanned.get("color_transfer") or "unknown"
            await self.session.commit()
        session_id = options.playback_session_id
        playback = await self.session.get(PlaybackSession, session_id, populate_existing=True)
        if playback is None or playback.media_file_id != media_id:
            raise HTTPException(status_code=404, detail="Playback session not found")
        if playback.status != PlaybackSessionStatus.ACTIVE:
            raise HTTPException(status_code=410, detail="Playback session has ended")
        try:
            video = select_video_track(media_file, options.video_stream_index)
            audio = select_audio_track(media_file, options.audio_stream_index)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        options.video_stream_index = video.stream_index if video is not None else None
        options.audio_stream_index = audio.stream_index if audio is not None else None
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
            video_stream_index=options.video_stream_index,
            playback_generation=options.playback_generation,
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
                    video_stream_index=options.video_stream_index,
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
                    max_frame_rate=options.max_frame_rate,
                    session_id=session_id,
                    client_ip=client.client_ip,
                    user_agent=client.user_agent,
                    video_stream_index=options.video_stream_index,
                    audio_stream_index=options.audio_stream_index,
                    subtitle_stream_index=options.subtitle_stream_index,
                    start_time=options.start_time,
                )

            if options.playback_session_id:
                playback = await self.session.get(PlaybackSession, options.playback_session_id, populate_existing=True)
                if (
                    playback is None
                    or playback.status != PlaybackSessionStatus.ACTIVE
                    or playback.playback_generation != options.playback_generation
                ):
                    await self.transcoder.stop_job(job_id)
                    raise HTTPException(status_code=410, detail="Playback session ended during startup")
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
        playback_session_id: str,
        playback_generation: int,
        client: ClientContext | None = None,
    ) -> dict[str, str]:
        """Start the server-side work implied by a playback decision."""
        if stream_info.PlayMethod == PlayMethod.NONE:
            raise HTTPException(status_code=422, detail="No compatible playback method is enabled")
        if stream_info.PlayMethod == PlayMethod.DIRECT_PLAY:
            await self.get_media_file(media_id)
            await self._claim_playback_intent(media_id, playback_session_id, playback_generation)
            lock = _session_locks.setdefault(playback_session_id, asyncio.Lock())
            async with lock:
                await self._require_current_intent(playback_session_id, playback_generation)
                await self._stop_previous_jobs(playback_session_id)
                await self._require_current_intent(playback_session_id, playback_generation)
            return {
                "method": "direct_play",
                "url": f"/api/v1/stream/{media_id}?session_id={playback_session_id}",
                "message": "Use direct streaming endpoint",
            }

        settings = stream_info.TranscodeSettings
        if stream_info.PlayMethod == PlayMethod.DIRECT_STREAM and stream_info.IsRemuxOnly:
            job = await self.start_hls_job(
                media_id,
                HlsStartOptions(
                    playback_session_id=playback_session_id,
                    playback_generation=playback_generation,
                    video_stream_index=stream_info.VideoStreamIndex,
                    job_type=TranscodingJobType.REMUX,
                    audio_stream_index=stream_info.AudioStreamIndex,
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
                playback_session_id=playback_session_id,
                playback_generation=playback_generation,
                video_stream_index=stream_info.VideoStreamIndex,
                job_type=job_type,
                video_codec=getattr(settings, "VideoCodec", None) or stream_info.TranscodingVideoCodec or "h264",
                audio_codec=getattr(settings, "AudioCodec", None) or stream_info.TranscodingAudioCodec or "aac",
                video_bitrate=getattr(settings, "VideoBitrate", None),
                audio_bitrate=getattr(settings, "AudioBitrate", None),
                max_width=getattr(settings, "MaxWidth", None),
                max_height=getattr(settings, "MaxHeight", None),
                max_frame_rate=getattr(settings, "MaxFrameRate", None),
                audio_stream_index=stream_info.AudioStreamIndex,
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
