"""LibraryPath model and schema."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .recommendation_row import RecommendationRow


class Library(Base):
    """Configured folders to scan for media files."""

    __tablename__ = "library"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    path: Mapped[str] = mapped_column(String, index=True, unique=True)
    library_type: Mapped[str] = mapped_column(String, default="movie")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    # Relationship
    recommendation_rows: Mapped[list["RecommendationRow"]] = relationship(
        "RecommendationRow", back_populates="library"
    )


class LibrarySchema(BaseModel):
    """Schema for Library API responses."""

    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    name: str
    path: str
    library_type: str = "movie"
    enabled: bool = True
    created_at: datetime


class LibraryCreate(BaseModel):
    """Schema for creating a library."""

    name: str
    path: str
    library_type: str = "movie"
    enabled: bool = True


class LibraryUpdate(BaseModel):
    """Schema for updating a library."""

    name: str | None = None
    path: str | None = None
    library_type: str | None = None
    enabled: bool | None = None
