"""User model and schemas."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy_utils import PasswordType

from .base import Base


class UserRole(StrEnum):
    """Application roles currently supported by Ferelix."""

    READER = "reader"
    ADMIN = "admin"


class User(Base):
    """User accounts with authentication credentials."""

    __tablename__ = "user"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String, index=True, unique=True)
    email: Mapped[str | None]
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

    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

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
    created_at: datetime
    updated_at: datetime


class UserCreate(BaseModel):
    """Schema for creating a new user."""

    username: str
    email: str | None
    password: str
    role: UserRole = UserRole.READER
    is_admin: bool = False
    language: str = "en"


class UserUpdate(BaseModel):
    """Schema for updating user information."""

    username: str | None = None
    email: str | None = None
    password: str | None = None
    role: UserRole | None = None
    language: str | None = None
    is_admin: bool | None = None
    is_active: bool | None = None
