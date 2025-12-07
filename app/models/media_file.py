"""MediaFile model and schema."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict
from sqlalchemy import DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

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
