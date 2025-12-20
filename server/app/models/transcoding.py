"""Transcoding job models and schemas."""

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class TranscodingJobType(StrEnum):
    """Types of transcoding jobs."""

    HLS = "hls"  # HLS segmented transcoding
    PROGRESSIVE = "progressive"  # Progressive download transcoding
    REMUX = "remux"  # Container conversion only (no re-encoding)
    AUDIO_TRANSCODE = "audio_transcode"  # Transcode audio while copying video (video copy + audio re-encode)


class TranscodingJobStatus(StrEnum):
    """Status of transcoding jobs."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TranscodingJob(Base):
    """Transcoding job tracking."""

    __tablename__ = "transcoding_job"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    media_file_id: Mapped[int] = mapped_column(Integer, index=True)

    # Job configuration
    type: Mapped[str] = mapped_column(String)  # TranscodingJobType enum values
    status: Mapped[str] = mapped_column(
        String, default=TranscodingJobStatus.PENDING
    )  # TranscodingJobStatus enum values

    # Transcoding settings
    video_codec: Mapped[str | None] = mapped_column(String, nullable=True)  # h264, hevc, copy
    audio_codec: Mapped[str | None] = mapped_column(String, nullable=True)  # aac, mp3, copy
    video_bitrate: Mapped[int | None] = mapped_column(Integer, nullable=True)  # bps
    audio_bitrate: Mapped[int | None] = mapped_column(Integer, nullable=True)  # bps
    max_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_height: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Output info
    output_path: Mapped[str | None] = mapped_column(String, nullable=True)
    playlist_path: Mapped[str | None] = mapped_column(String, nullable=True)  # For HLS

    # Progress tracking
    progress_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    transcoded_duration: Mapped[float | None] = mapped_column(Float, nullable=True)  # seconds
    current_fps: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_bitrate: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Process info
    process_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ffmpeg_command: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Error handling
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)

    # Session info
    session_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    client_ip: Mapped[str | None] = mapped_column(String, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_accessed_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    # Cleanup flags
    auto_cleanup: Mapped[bool] = mapped_column(Boolean, default=True)
    keep_segments: Mapped[bool] = mapped_column(Boolean, default=False)


class TranscodingJobSchema(BaseModel):
    """Schema for TranscodingJob API responses."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    media_file_id: int
    type: TranscodingJobType
    status: TranscodingJobStatus

    # Transcoding settings
    video_codec: str | None = None
    audio_codec: str | None = None
    video_bitrate: int | None = None
    audio_bitrate: int | None = None
    max_width: int | None = None
    max_height: int | None = None

    # Progress info
    progress_percent: float | None = None
    transcoded_duration: float | None = None
    current_fps: float | None = None
    current_bitrate: int | None = None

    # Error info
    error_message: str | None = None
    retry_count: int = 0

    # Timestamps
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    last_accessed_at: datetime


class TranscodingProgressUpdate(BaseModel):
    """Schema for transcoding progress updates."""

    job_id: str
    progress_percent: float | None = None
    transcoded_duration: float | None = None
    current_fps: float | None = None
    current_bitrate: int | None = None
    status: TranscodingJobStatus | None = None
    error_message: str | None = None
