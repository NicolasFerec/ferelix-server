"""Per-user media view progress models and schemas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class MediaView(Base):
    """Persisted watch state for a media file and user."""

    __tablename__ = "media_view"
    __table_args__ = (UniqueConstraint("user_id", "media_file_id", name="uq_media_view_user_media"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    media_file_id: Mapped[int | None] = mapped_column(ForeignKey("mediafile.id", ondelete="SET NULL"), index=True)
    position_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    watched: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    play_count: Mapped[int] = mapped_column(Integer, default=0)
    first_viewed_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    last_viewed_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class MediaViewSchema(BaseModel):
    """API representation of a user's watch state for one media file."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    media_file_id: int | None
    position_seconds: float
    duration_seconds: float | None = None
    watched: bool
    play_count: int
    first_viewed_at: datetime
    last_viewed_at: datetime
    completed_at: datetime | None = None


class MediaViewUpdate(BaseModel):
    """Manual watch-state update payload."""

    position_seconds: float = 0.0
    duration_seconds: float | None = None
    watched: bool | None = None
