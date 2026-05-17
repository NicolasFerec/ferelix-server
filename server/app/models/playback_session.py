"""Playback session models and schemas."""

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class PlaybackSessionStatus(StrEnum):
    """Lifecycle state for a user playback session."""

    ACTIVE = "active"
    ENDED = "ended"
    STOPPED_BY_ADMIN = "stopped_by_admin"


class PlaybackSession(Base):
    """A user-visible playback session, independent of whether FFmpeg is used."""

    __tablename__ = "playback_session"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), index=True)
    media_file_id: Mapped[int] = mapped_column(ForeignKey("mediafile.id"), index=True)
    transcoding_job_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)

    play_method: Mapped[str] = mapped_column(String, default="unknown")
    transcoding_type: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default=PlaybackSessionStatus.ACTIVE, index=True)
    stopped_reason: Mapped[str | None] = mapped_column(String, nullable=True)

    position_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_paused: Mapped[bool] = mapped_column(Boolean, default=False)
    audio_stream_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    subtitle_stream_index: Mapped[int | None] = mapped_column(Integer, nullable=True)

    client_ip: Mapped[str | None] = mapped_column(String, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String, nullable=True)

    started_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    last_heartbeat_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class PlaybackSessionCreate(BaseModel):
    """Payload used by the player to create a playback session."""

    media_file_id: int
    duration_seconds: float | None = None
    audio_stream_index: int | None = None
    subtitle_stream_index: int | None = None


class PlaybackSessionHeartbeat(BaseModel):
    """Periodic playback session update sent by the player."""

    position_seconds: float = 0.0
    duration_seconds: float | None = None
    is_paused: bool = False
    play_method: str | None = None
    transcoding_type: str | None = None
    transcoding_job_id: str | None = None
    audio_stream_index: int | None = None
    subtitle_stream_index: int | None = None


class PlaybackSessionSchema(BaseModel):
    """Playback session response."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: int
    media_file_id: int
    transcoding_job_id: str | None = None
    play_method: str
    transcoding_type: str | None = None
    status: PlaybackSessionStatus
    stopped_reason: str | None = None
    position_seconds: float
    duration_seconds: float | None = None
    is_paused: bool
    audio_stream_index: int | None = None
    subtitle_stream_index: int | None = None
    client_ip: str | None = None
    user_agent: str | None = None
    started_at: datetime
    last_heartbeat_at: datetime
    ended_at: datetime | None = None


class PlaybackSessionHeartbeatResponse(BaseModel):
    """Heartbeat response, including whether the player should stop itself."""

    session: PlaybackSessionSchema
    kicked: bool = False
    message: str | None = None
