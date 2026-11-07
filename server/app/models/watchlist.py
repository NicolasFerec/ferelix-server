"""A user's explicitly saved media, independent from watch progress."""

from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class WatchlistEntry(Base):
    __tablename__ = "watchlist"
    __table_args__ = (UniqueConstraint("user_id", "media_file_id", name="uq_watchlist_user_media"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"))
    media_file_id: Mapped[int] = mapped_column(ForeignKey("mediafile.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), server_default=func.now())


class WatchlistState(BaseModel):
    media_file_id: int
    in_watchlist: bool
