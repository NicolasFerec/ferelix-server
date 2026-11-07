"""User model and schemas."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, validates
from sqlalchemy_utils import PasswordType

from .base import Base


class UserRole(StrEnum):
    """Application roles currently supported by Ferelix."""

    READER = "reader"
    ADMIN = "admin"


class SubtitleMode(StrEnum):
    """Initial subtitle selection; explicit playback choices always take priority."""

    OFF = "off"
    FORCED = "forced"
    ALWAYS = "always"


class User(Base):
    """User accounts with authentication credentials."""

    __tablename__ = "user"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String, index=True, unique=True)
    username_normalized: Mapped[str] = mapped_column(String, unique=True)
    email: Mapped[str | None]
    email_normalized: Mapped[str | None] = mapped_column(String, unique=True)
    credentials_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    profile_image_path: Mapped[str | None] = mapped_column(String, nullable=True)
    password: Mapped[str | None] = mapped_column(
        PasswordType(
            schemes=["pbkdf2_sha512", "md5_crypt"],
            deprecated=["md5_crypt"],
        )
    )
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    language: Mapped[str] = mapped_column(String, default="en")
    preferred_audio_language: Mapped[str | None] = mapped_column(String, nullable=True)
    preferred_subtitle_language: Mapped[str | None] = mapped_column(String, nullable=True)
    subtitle_mode: Mapped[str] = mapped_column(String, default=SubtitleMode.OFF, server_default="off")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    @validates("username")
    def normalize_username(self, _key: str, value: str) -> str:
        value = value.strip()
        self.username_normalized = value.casefold()
        return value

    @validates("email")
    def normalize_email(self, _key: str, value: str | None) -> str | None:
        normalized = value.strip().casefold() if value and value.strip() else None
        self.email_normalized = normalized
        return normalized

    @property
    def role(self) -> UserRole:
        """Expose the boolean admin flag as a user-facing role."""
        return UserRole.ADMIN if self.is_admin else UserRole.READER

    @property
    def profile_image_url(self) -> str | None:
        """Authenticated profile image endpoint for this user."""
        if self.id is None or not self.profile_image_path:
            return None
        return f"/api/v1/users/{self.id}/profile-image"


class UserSchema(BaseModel):
    """Schema for User API responses (excludes password)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str | None
    profile_image_url: str | None = None
    role: UserRole
    is_admin: bool
    is_active: bool
    language: str
    preferred_audio_language: str | None = None
    preferred_subtitle_language: str | None = None
    subtitle_mode: SubtitleMode = SubtitleMode.OFF
    created_at: datetime
    updated_at: datetime


class UserCreate(BaseModel):
    """Schema for creating a new user."""

    username: str = Field(min_length=1, max_length=255)
    email: str | None
    password: str = Field(min_length=1, max_length=1024)
    role: UserRole = UserRole.READER
    is_admin: bool = False
    language: str = "en"

    @field_validator("username", mode="before")
    @classmethod
    def strip_username(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value


class UserUpdate(BaseModel):
    """Schema for updating user information."""

    username: str | None = Field(default=None, min_length=1, max_length=255)
    email: str | None = None
    password: str | None = Field(default=None, min_length=1, max_length=1024)
    current_password: str | None = None
    role: UserRole | None = None
    language: str | None = None
    is_admin: bool | None = None
    is_active: bool | None = None
    preferred_audio_language: str | None = Field(
        default=None, pattern=r"^[a-z]{2,3}(?:-[a-z0-9]{2,8})*$", max_length=35
    )
    preferred_subtitle_language: str | None = Field(
        default=None, pattern=r"^[a-z]{2,3}(?:-[a-z0-9]{2,8})*$", max_length=35
    )
    subtitle_mode: SubtitleMode | None = None

    @field_validator("preferred_audio_language", "preferred_subtitle_language", mode="before")
    @classmethod
    def normalize_preference_language(cls, value: str | None) -> str | None:
        return value.strip().lower().replace("_", "-") or None if isinstance(value, str) else value

    @field_validator("username", mode="before")
    @classmethod
    def strip_username(cls, value: str | None) -> str | None:
        return value.strip() if isinstance(value, str) else value
