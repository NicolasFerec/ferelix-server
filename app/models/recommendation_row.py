"""RecommendationRow model and schema."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .library import Library


class RecommendationRow(Base):
    """Admin-managed recommendation rows for libraries."""

    __tablename__ = "recommendation_row"

    id: Mapped[int] = mapped_column(primary_key=True)
    library_id: Mapped[int] = mapped_column(ForeignKey("library.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    filter_criteria: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    visible_on_homepage: Mapped[bool] = mapped_column(Boolean, default=False)
    visible_on_recommend: Mapped[bool] = mapped_column(Boolean, default=False)
    is_special: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now()
    )

    # Relationship
    library: Mapped["Library"] = relationship(
        "Library", back_populates="recommendation_rows"
    )  # type: ignore[type-arg]


class RecommendationRowSchema(BaseModel):
    """Schema for RecommendationRow API responses."""

    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    library_id: int
    name: str
    filter_criteria: dict[str, Any]
    visible_on_homepage: bool = False
    visible_on_recommend: bool = False
    is_special: bool = False
    created_at: datetime
    updated_at: datetime


class RecommendationRowCreate(BaseModel):
    """Schema for creating a recommendation row."""

    library_id: int
    name: str = Field(..., min_length=1)
    filter_criteria: dict[str, Any] = Field(..., description="Filter criteria JSON")
    visible_on_homepage: bool = False
    visible_on_recommend: bool = False


class RecommendationRowUpdate(BaseModel):
    """Schema for updating a recommendation row."""

    name: str | None = Field(None, min_length=1)
    filter_criteria: dict[str, Any] | None = Field(
        None, description="Filter criteria JSON"
    )
    visible_on_homepage: bool | None = None
    visible_on_recommend: bool | None = None
