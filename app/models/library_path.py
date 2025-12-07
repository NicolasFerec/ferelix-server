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
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


class LibraryPathSchema(BaseModel):
    """Schema for LibraryPath API responses."""

    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    path: str
    enabled: bool = True
    created_at: datetime
