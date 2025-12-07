"""Movie model and schema."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict
from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Movie(Base):
    """Movie metadata and information."""

    __tablename__ = "movie"

    id: Mapped[int] = mapped_column(primary_key=True)
    media_file_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("mediafile.id"), nullable=True
    )

    title: Mapped[str] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    poster_url: Mapped[str | None] = mapped_column(String, nullable=True)
    backdrop_url: Mapped[str | None] = mapped_column(String, nullable=True)
    duration: Mapped[int] = mapped_column(Integer)  # in seconds
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    genre: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


class MovieSchema(BaseModel):
    """Schema for Movie API responses."""

    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    media_file_id: int | None = None
    title: str
    description: str | None = None
    poster_url: str | None = None
    backdrop_url: str | None = None
    duration: int
    year: int | None = None
    genre: str | None = None
    created_at: datetime
    updated_at: datetime
