"""Editorial catalogue, independent from physical files and playback sessions."""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field
from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

ItemKind = Literal["movie", "series", "season", "episode", "collection"]
Availability = Literal["available", "missing", "upcoming", "incomplete"]


class MediaItem(Base):
    __tablename__ = "media_item"
    __table_args__ = (Index("ix_media_item_series_order", "series_id", "season_number", "episode_number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String, index=True)
    metadata_library_id: Mapped[int | None] = mapped_column(ForeignKey("library.id", ondelete="SET NULL"), index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("media_item.id", ondelete="SET NULL"), index=True)
    series_id: Mapped[int | None] = mapped_column(ForeignKey("media_item.id", ondelete="SET NULL"), index=True)
    collection_id: Mapped[int | None] = mapped_column(ForeignKey("media_item.id", ondelete="SET NULL"), index=True)
    title: Mapped[str] = mapped_column(String, default="")
    original_title: Mapped[str | None] = mapped_column(String)
    sort_title: Mapped[str | None] = mapped_column(String)
    overview: Mapped[str | None] = mapped_column(String)
    tagline: Mapped[str | None] = mapped_column(String)
    original_language: Mapped[str | None] = mapped_column(String)
    release_date: Mapped[date | None] = mapped_column(Date)
    season_number: Mapped[int | None] = mapped_column(Integer)
    episode_number: Mapped[int | None] = mapped_column(Integer)
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list)
    genres: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    keywords: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    credits: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    studios: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    countries: Mapped[list[str]] = mapped_column(JSON, default=list)
    provider_ids: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    metadata_locale: Mapped[str] = mapped_column(String, default="fr-FR")
    locked_fields: Mapped[list[str]] = mapped_column(JSON, default=list)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    provider_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    generation: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    content_hash: Mapped[str] = mapped_column(String, default="")
    metadata_status: Mapped[str] = mapped_column(String, default="pending", index=True)
    hierarchy_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    order_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    first_available_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())


class MediaItemFile(Base):
    __tablename__ = "media_item_file"

    item_id: Mapped[int] = mapped_column(ForeignKey("media_item.id", ondelete="CASCADE"), primary_key=True)
    media_file_id: Mapped[int] = mapped_column(
        ForeignKey("mediafile.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    start_seconds: Mapped[float | None] = mapped_column(Float)
    end_seconds: Mapped[float | None] = mapped_column(Float)


class UserItemState(Base):
    __tablename__ = "user_item_state"

    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("media_item.id", ondelete="CASCADE"), primary_key=True, index=True)
    watched: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    watched_at: Mapped[datetime | None] = mapped_column(DateTime)
    state_revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)


class MetadataJob(Base):
    __tablename__ = "metadata_job"
    __table_args__ = (UniqueConstraint("item_id", "generation", name="uq_metadata_job_generation"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("media_item.id", ondelete="CASCADE"), index=True)
    generation: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String, default="pending", index=True)
    mode: Mapped[str] = mapped_column(String, default="unlocked", server_default="unlocked")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), index=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime)
    error: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())


class MetadataCache(Base):
    __tablename__ = "metadata_cache"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    provider: Mapped[str] = mapped_column(String, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)


class Artwork(Base):
    __tablename__ = "metadata_artwork"
    __table_args__ = (UniqueConstraint("item_id", "role", name="uq_metadata_artwork_role"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("media_item.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String)
    language: Mapped[str | None] = mapped_column(String)
    path: Mapped[str] = mapped_column(String)
    sha256: Mapped[str] = mapped_column(String)
    source: Mapped[str] = mapped_column(String)


class ItemCardSchema(BaseModel):
    """Bounded projection used by catalogue, search and viewing rows."""

    id: int
    kind: ItemKind
    title: str
    original_title: str | None = None
    year: int | None = None
    release_date: date | None = None
    parent_id: int | None = None
    series_id: int | None = None
    collection_id: int | None = None
    season_number: int | None = None
    episode_number: int | None = None
    poster_url: str | None = None
    availability: Availability
    playable_file_id: int | None = None
    watched: bool = False
    state_revision: int = 0
    position_seconds: float = 0
    duration_seconds: float | None = None
    progress_percent: float = 0
    resume_active: bool = False
    hierarchy_complete: bool = False
    metadata_status: str = "pending"


class ItemDetailSchema(ItemCardSchema):
    in_watchlist: bool = False
    overview: str | None = None
    tagline: str | None = None
    release_date: date | None = None
    metadata_locale: str
    aliases: list[str] = Field(default_factory=list)
    genres: list[dict[str, Any]] = Field(default_factory=list)
    keywords: list[dict[str, Any]] = Field(default_factory=list)
    credits: list[dict[str, Any]] = Field(default_factory=list)
    provider_ids: dict[str, str] = Field(default_factory=dict)
    backdrop_url: str | None = None
    file_ids: list[int] = Field(default_factory=list)
    multi_episode_file: bool = False
    order_confirmed: bool = False


class MetadataItemSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    metadata_library_id: int | None
    kind: ItemKind
    title: str
    original_title: str | None
    sort_title: str | None
    overview: str | None
    tagline: str | None
    original_language: str | None
    release_date: date | None
    season_number: int | None
    episode_number: int | None
    aliases: list[str]
    genres: list[dict[str, Any]]
    keywords: list[dict[str, Any]]
    credits: list[dict[str, Any]]
    studios: list[dict[str, Any]]
    countries: list[str]
    provider_ids: dict[str, str]
    metadata_locale: str
    locked_fields: list[str]
    locked: bool
    provenance: dict[str, Any]
    provider_data: dict[str, Any]
    revision: int
    generation: int
    content_hash: str
    metadata_status: str
    hierarchy_complete: bool
    order_confirmed: bool

    @computed_field
    @property
    def can_associate_episode(self) -> bool:
        return self.kind == "episode" and (self.season_number is None or self.episode_number is None)


class MetadataPatch(BaseModel):
    expected_revision: int = Field(ge=0)
    changes: dict[str, Any] = Field(default_factory=dict)
    locked_fields: list[str] | None = None
    locked: bool | None = None


class MetadataJobSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    item_id: int
    generation: int
    status: str
    attempts: int
    error: str | None
    next_attempt_at: datetime
    updated_at: datetime
