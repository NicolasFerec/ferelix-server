"""LibraryPath model and schema."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class LibraryPath(Base):
    """Configured folders to scan for media files."""

    __tablename__ = "librarypath"

    id: Mapped[int] = mapped_column(primary_key=True)
    path: Mapped[str] = mapped_column(String, index=True, unique=True)
    library_type: Mapped[str] = mapped_column(String, default="movie")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


class LibraryPathSchema(BaseModel):
    """Schema for LibraryPath API responses."""

    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    path: str
    library_type: str = "movie"
    enabled: bool = True
    created_at: datetime


class LibraryPathCreate(BaseModel):
    """Schema for creating a library path."""

    path: str
    library_type: str = "movie"
    enabled: bool = True


class LibraryPathUpdate(BaseModel):
    """Schema for updating a library path."""

    path: str | None = None
    library_type: str | None = None
    enabled: bool | None = None
