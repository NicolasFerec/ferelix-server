"""MediaFile model and schema."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class MediaFile(Base):
    """Media files discovered by the scanner."""

    __tablename__ = "mediafile"

    id: Mapped[int] = mapped_column(primary_key=True)
    file_path: Mapped[str] = mapped_column(String, index=True, unique=True)
    file_name: Mapped[str] = mapped_column(String)
    file_size: Mapped[int] = mapped_column(Integer)
    file_extension: Mapped[str] = mapped_column(String)

    # Video metadata (extracted via ffprobe)
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    codec: Mapped[str | None] = mapped_column(String, nullable=True)
    bitrate: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    scanned_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, default=None
    )

    # Relationships
    video_tracks: Mapped[list["VideoTrack"]] = relationship(
        back_populates="media_file", cascade="all, delete-orphan"
    )
    audio_tracks: Mapped[list["AudioTrack"]] = relationship(
        back_populates="media_file", cascade="all, delete-orphan"
    )
    subtitle_tracks: Mapped[list["SubtitleTrack"]] = relationship(
        back_populates="media_file", cascade="all, delete-orphan"
    )


class MediaFileSchema(BaseModel):
    """Schema for MediaFile API responses."""

    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    file_path: str
    file_name: str
    file_size: int
    file_extension: str
    duration: float | None = None
    width: int | None = None
    height: int | None = None
    codec: str | None = None
    bitrate: int | None = None
    created_at: datetime
    updated_at: datetime
    scanned_at: datetime
    deleted_at: datetime | None = None
    video_tracks: list["VideoTrackSchema"] = []
    audio_tracks: list["AudioTrackSchema"] = []
    subtitle_tracks: list["SubtitleTrackSchema"] = []


class VideoTrack(Base):
    """Video track information extracted from media files."""

    __tablename__ = "video_track"

    id: Mapped[int] = mapped_column(primary_key=True)
    media_file_id: Mapped[int] = mapped_column(ForeignKey("mediafile.id"))
    stream_index: Mapped[int] = mapped_column(Integer)
    codec: Mapped[str] = mapped_column(String)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bitrate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fps: Mapped[float | None] = mapped_column(Float, nullable=True)
    language: Mapped[str | None] = mapped_column(String, nullable=True)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)

    # Relationship
    media_file: Mapped["MediaFile"] = relationship(back_populates="video_tracks")


class AudioTrack(Base):
    """Audio track information extracted from media files."""

    __tablename__ = "audio_track"

    id: Mapped[int] = mapped_column(primary_key=True)
    media_file_id: Mapped[int] = mapped_column(ForeignKey("mediafile.id"))
    stream_index: Mapped[int] = mapped_column(Integer)
    codec: Mapped[str] = mapped_column(String)
    language: Mapped[str | None] = mapped_column(String, nullable=True)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    channels: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bitrate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)

    # Relationship
    media_file: Mapped["MediaFile"] = relationship(back_populates="audio_tracks")


class SubtitleTrack(Base):
    """Subtitle track information extracted from media files."""

    __tablename__ = "subtitle_track"

    id: Mapped[int] = mapped_column(primary_key=True)
    media_file_id: Mapped[int] = mapped_column(ForeignKey("mediafile.id"))
    stream_index: Mapped[int] = mapped_column(Integer)
    codec: Mapped[str] = mapped_column(String)
    language: Mapped[str | None] = mapped_column(String, nullable=True)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    is_forced: Mapped[bool] = mapped_column(Boolean, default=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)

    # Relationship
    media_file: Mapped["MediaFile"] = relationship(back_populates="subtitle_tracks")


class VideoTrackSchema(BaseModel):
    """Schema for VideoTrack API responses."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    media_file_id: int
    stream_index: int
    codec: str
    width: int | None = None
    height: int | None = None
    bitrate: int | None = None
    fps: float | None = None
    language: str | None = None
    title: str | None = None
    is_default: bool


class AudioTrackSchema(BaseModel):
    """Schema for AudioTrack API responses."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    media_file_id: int
    stream_index: int
    codec: str
    language: str | None = None
    title: str | None = None
    channels: int | None = None
    bitrate: int | None = None
    is_default: bool


class SubtitleTrackSchema(BaseModel):
    """Schema for SubtitleTrack API responses."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    media_file_id: int
    stream_index: int
    codec: str
    language: str | None = None
    title: str | None = None
    is_forced: bool
    is_default: bool
