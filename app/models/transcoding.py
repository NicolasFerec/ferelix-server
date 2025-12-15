"""Transcoding models and schemas."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict
from sqlalchemy import DateTime, Enum as SQLEnum, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class TranscodingStatus(str, Enum):
    """Status of a transcoding session."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TranscodingFormat(str, Enum):
    """Output format for transcoding."""

    HLS = "hls"  # HTTP Live Streaming
    PROGRESSIVE = "progressive"  # Progressive download


class TranscodingSession(Base):
    """Active transcoding sessions."""

    __tablename__ = "transcoding_session"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    media_file_id: Mapped[int] = mapped_column(Integer)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Transcoding parameters
    output_format: Mapped[TranscodingFormat] = mapped_column(
        SQLEnum(TranscodingFormat), default=TranscodingFormat.HLS
    )
    video_codec: Mapped[str | None] = mapped_column(String, nullable=True)
    audio_codec: Mapped[str | None] = mapped_column(String, nullable=True)
    audio_track_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    subtitle_track_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    burn_subtitles: Mapped[bool] = mapped_column(default=False)

    # Progress tracking
    status: Mapped[TranscodingStatus] = mapped_column(
        SQLEnum(TranscodingStatus), default=TranscodingStatus.PENDING
    )
    progress: Mapped[float] = mapped_column(Float, default=0.0)  # 0.0 to 100.0
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Output paths
    output_path: Mapped[str | None] = mapped_column(String, nullable=True)
    manifest_path: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # For HLS m3u8

    # Process management
    process_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now()
    )
    last_accessed_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


class TranscodingSessionSchema(BaseModel):
    """Schema for TranscodingSession API responses."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: str
    media_file_id: int
    user_id: int | None
    output_format: TranscodingFormat
    video_codec: str | None
    audio_codec: str | None
    audio_track_index: int | None
    subtitle_track_index: int | None
    burn_subtitles: bool
    status: TranscodingStatus
    progress: float
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    last_accessed_at: datetime


class TranscodingProfile(Base):
    """Predefined transcoding profiles for different client capabilities."""

    __tablename__ = "transcoding_profile"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Video settings
    video_codec: Mapped[str] = mapped_column(String)  # h264, hevc, vp9, av1
    max_video_bitrate: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )  # in kbps

    # Audio settings
    audio_codec: Mapped[str] = mapped_column(String)  # aac, mp3, opus
    max_audio_bitrate: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )  # in kbps

    # Container format
    container: Mapped[str] = mapped_column(String)  # mp4, webm, mkv

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now()
    )


class TranscodingProfileSchema(BaseModel):
    """Schema for TranscodingProfile API responses."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    video_codec: str
    max_video_bitrate: int | None
    audio_codec: str
    max_audio_bitrate: int | None
    container: str
    created_at: datetime
    updated_at: datetime


class ClientCapabilities(BaseModel):
    """Client-declared media format capabilities."""

    # Video codecs supported (e.g., ["h264", "hevc", "vp9"])
    video_codecs: list[str]
    # Audio codecs supported (e.g., ["aac", "mp3", "opus"])
    audio_codecs: list[str]
    # Container formats supported (e.g., ["mp4", "webm", "mkv"])
    containers: list[str]
    # Subtitle formats supported (e.g., ["srt", "vtt", "ass"])
    subtitle_codecs: list[str] = []
    # Maximum resolution (e.g., 1920x1080)
    max_width: int | None = None
    max_height: int | None = None


class CompatibilityCheckRequest(BaseModel):
    """Request to check media compatibility with client."""

    media_file_id: int
    client_capabilities: ClientCapabilities


class CompatibilityCheckResponse(BaseModel):
    """Response indicating if direct play is possible or transcoding is needed."""

    can_direct_play: bool
    requires_transcoding: bool
    reasons: list[str] = []  # Reasons why transcoding is needed
    suggested_profile: TranscodingProfileSchema | None = None


class StartTranscodingRequest(BaseModel):
    """Request to start a transcoding session."""

    media_file_id: int
    output_format: TranscodingFormat = TranscodingFormat.HLS
    audio_track_index: int | None = None
    subtitle_track_index: int | None = None
    client_capabilities: ClientCapabilities | None = None


class TranscodingProgressResponse(BaseModel):
    """Response with transcoding progress information."""

    session_id: str
    status: TranscodingStatus
    progress: float  # 0.0 to 100.0
    error_message: str | None = None
