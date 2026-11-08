"""LibraryPath model and schema."""

from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field
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
    metadata_locale: Mapped[str] = mapped_column(String, default="fr-FR", server_default="fr-FR")
    metadata_profile: Mapped[str] = mapped_column(String, default="standard", server_default="standard")
    metadata_export_nfo: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    # Relationship
    recommendation_rows: Mapped[list[RecommendationRow]] = relationship(
        "RecommendationRow", back_populates="library", cascade="all, delete-orphan"
    )


class LibrarySchema(BaseModel):
    """Schema for Library API responses."""

    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    name: str
    path: str
    library_type: str = "movie"
    enabled: bool = True
    metadata_locale: str = "fr-FR"
    metadata_profile: str = "standard"
    metadata_export_nfo: bool = False
    created_at: datetime


class LibraryCreate(BaseModel):
    """Schema for creating a library."""

    name: str
    path: str
    library_type: str = "movie"
    enabled: bool = True
    metadata_locale: str = Field(default="fr-FR", pattern=r"^[a-z]{2,3}(?:-[A-Z]{2})?$")
    metadata_profile: str = Field(default="standard", pattern=r"^(standard|anime)$")
    metadata_export_nfo: bool = False


class LibraryUpdate(BaseModel):
    """Schema for updating a library."""

    name: str | None = None
    path: str | None = None
    library_type: str | None = None
    enabled: bool | None = None
    metadata_locale: str | None = Field(default=None, pattern=r"^[a-z]{2,3}(?:-[A-Z]{2})?$")
    metadata_profile: str | None = Field(default=None, pattern=r"^(standard|anime)$")
    metadata_export_nfo: bool | None = None
