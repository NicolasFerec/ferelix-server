"""Settings model and schemas for application configuration."""

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Settings(Base):
    """Application settings (singleton pattern - only one record)."""

    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    # Library scanner settings
    library_scan_interval_minutes: Mapped[int] = mapped_column(
        Integer, default=120
    )  # Default: 2 hours
    # Cleanup job settings
    cleanup_schedule_hour: Mapped[int] = mapped_column(
        Integer, default=3
    )  # Default: 3 AM
    cleanup_schedule_minute: Mapped[int] = mapped_column(Integer, default=0)
    cleanup_grace_period_days: Mapped[int] = mapped_column(Integer, default=30)


class SettingsSchema(BaseModel):
    """Schema for Settings API responses."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    library_scan_interval_minutes: int
    cleanup_schedule_hour: int
    cleanup_schedule_minute: int
    cleanup_grace_period_days: int


class SettingsUpdate(BaseModel):
    """Schema for updating settings."""

    library_scan_interval_minutes: int | None = None
    cleanup_schedule_hour: int | None = None
    cleanup_schedule_minute: int | None = None
    cleanup_grace_period_days: int | None = None
