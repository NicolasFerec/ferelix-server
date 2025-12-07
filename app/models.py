"""Database models for the media server."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

__all__ = [
    "LibraryPath",
    "LibraryPathSchema",
    "MediaFile",
    "MediaFileSchema",
    "Movie",
    "MovieSchema",
    "RefreshToken",
    "User",
    "UserCreate",
    "UserSchema",
    "UserUpdate",
]


# SQLAlchemy Base
class Base(DeclarativeBase):
    """Base class for all database models."""

    pass


# Database Models
class LibraryPath(Base):
    """Configured folders to scan for media files."""

    __tablename__ = "librarypath"

    id: Mapped[int] = mapped_column(primary_key=True)
    path: Mapped[str] = mapped_column(String, index=True, unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


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


class User(Base):
    """User accounts with authentication credentials."""

    __tablename__ = "user"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String, index=True, unique=True)
    email: Mapped[str] = mapped_column(String, index=True, unique=True)
    hashed_password: Mapped[str] = mapped_column(String)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


class RefreshToken(Base):
    """Refresh tokens for user session management."""

    __tablename__ = "refresh_token"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("user.id"))
    token: Mapped[str] = mapped_column(String, index=True, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    device_info: Mapped[str | None] = mapped_column(String, nullable=True)


# Pydantic Schemas for API
class LibraryPathSchema(BaseModel):
    """Schema for LibraryPath API responses."""

    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    path: str
    enabled: bool = True
    created_at: datetime


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


class UserSchema(BaseModel):
    """Schema for User API responses (excludes password)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str
    is_admin: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime


class UserCreate(BaseModel):
    """Schema for creating a new user."""

    username: str
    email: str
    password: str
    is_admin: bool = False


class UserUpdate(BaseModel):
    """Schema for updating user information."""

    email: str | None = None
    password: str | None = None
    is_active: bool | None = None
