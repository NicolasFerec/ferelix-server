"""Administrator-only metadata maintenance. Provider credentials never reach the browser."""

import os
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.dependencies import require_admin
from app.models import MediaItem, MetadataJob
from app.models.metadata import MetadataItemSchema, MetadataJobSchema, MetadataPatch
from app.services.metadata import (
    MetadataConflict,
    ProviderUnavailable,
    apply_metadata_patch,
    identify_metadata,
    metadata_directory,
    queue_nfo_export,
    refresh_metadata,
    restore_metadata_fields,
    save_manual_artwork,
    search_metadata,
)
from app.services.metadata.types import MatchCandidate

router = APIRouter(prefix="/api/v1/dashboard/metadata", tags=["metadata"], dependencies=[Depends(require_admin)])
Session = Annotated[AsyncSession, Depends(get_session)]


class RevisionRequest(BaseModel):
    expected_revision: int = Field(ge=0)


class IdentifyRequest(RevisionRequest):
    provider: Literal["tmdb", "anidb"]
    provider_id: str = Field(min_length=1, max_length=100)


class RefreshRequest(RevisionRequest):
    mode: Literal["missing", "unlocked"] = "unlocked"


class RestoreRequest(RevisionRequest):
    fields: list[str] = Field(min_length=1, max_length=100)


class ProviderStatus(BaseModel):
    tmdb_configured: bool
    anidb_configured: bool
    metadata_dir: str


async def admin_item(session: AsyncSession, item_id: int) -> MediaItem:
    item = await session.get(MediaItem, item_id)
    if item is None:
        raise HTTPException(404, "Metadata item not found")
    return item


def metadata_error(error: Exception) -> HTTPException:
    if isinstance(error, MetadataConflict):
        return HTTPException(409, str(error))
    if isinstance(error, ProviderUnavailable):
        return HTTPException(503, str(error))
    return HTTPException(422, str(error))


@router.get("/providers", response_model=ProviderStatus)
async def providers() -> ProviderStatus:
    return ProviderStatus(
        tmdb_configured=bool(os.getenv("FERELIX_TMDB_TOKEN")),
        anidb_configured=bool(os.getenv("FERELIX_ANIDB_CLIENT")),
        metadata_dir=str(metadata_directory()),
    )


@router.get("/search", response_model=list[MatchCandidate])
async def search(
    q: Annotated[str, Query(min_length=1, max_length=200)],
    kind: Literal["movie", "series"] = "movie",
    locale: str = "fr-FR",
    provider: Literal["tmdb", "anidb"] = "tmdb",
) -> list[MatchCandidate]:
    try:
        return await search_metadata(q, kind, locale, provider)
    except (ValueError, ProviderUnavailable) as error:
        raise metadata_error(error) from error


@router.get("/jobs", response_model=list[MetadataJobSchema])
async def jobs(
    session: Session,
    status: str | None = None,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[MetadataJob]:
    query = select(MetadataJob)
    if status:
        query = query.where(MetadataJob.status == status)
    return list(
        await session.scalars(
            query.order_by(MetadataJob.updated_at.desc(), MetadataJob.id.desc()).offset(skip).limit(limit)
        )
    )


@router.get("/items/{item_id}", response_model=MetadataItemSchema)
async def get_metadata(item_id: int, session: Session) -> MediaItem:
    return await admin_item(session, item_id)


@router.patch("/items/{item_id}", response_model=MetadataItemSchema)
async def edit_metadata(item_id: int, payload: MetadataPatch, session: Session) -> MediaItem:
    await admin_item(session, item_id)
    if "metadata_locale" in payload.changes:
        raise HTTPException(422, "Configure the metadata language on the library")
    try:
        item = await apply_metadata_patch(
            session,
            item_id,
            payload.expected_revision,
            payload.changes,
            locks=payload.locked_fields,
            locked=payload.locked,
        )
        await queue_nfo_export(session, item)
        await session.commit()
        return item
    except (ValueError, ProviderUnavailable) as error:
        raise metadata_error(error) from error


@router.post("/items/{item_id}/identify", response_model=MetadataJobSchema)
async def identify(item_id: int, payload: IdentifyRequest, session: Session) -> MetadataJob:
    await admin_item(session, item_id)
    try:
        job = await identify_metadata(
            session, item_id, payload.expected_revision, payload.provider, payload.provider_id
        )
        await session.commit()
        return job
    except (ValueError, ProviderUnavailable) as error:
        raise metadata_error(error) from error


@router.post("/items/{item_id}/refresh", response_model=MetadataJobSchema)
async def refresh(item_id: int, payload: RefreshRequest, session: Session) -> MetadataJob:
    await admin_item(session, item_id)
    try:
        job = await refresh_metadata(session, item_id, payload.expected_revision, payload.mode)
        await session.commit()
        return job
    except (ValueError, ProviderUnavailable) as error:
        raise metadata_error(error) from error


@router.post("/items/{item_id}/restore", response_model=MetadataItemSchema)
async def restore(item_id: int, payload: RestoreRequest, session: Session) -> MediaItem:
    await admin_item(session, item_id)
    try:
        item = await restore_metadata_fields(session, item_id, payload.expected_revision, payload.fields)
        await queue_nfo_export(session, item)
        await session.commit()
        return item
    except (ValueError, ProviderUnavailable) as error:
        raise metadata_error(error) from error


@router.post("/items/{item_id}/images/{role}", response_model=MetadataItemSchema)
async def upload_image(
    item_id: int,
    role: Literal["poster", "backdrop"],
    session: Session,
    expected_revision: Annotated[int, Form(ge=0)],
    file: Annotated[UploadFile, File()],
) -> MediaItem:
    await admin_item(session, item_id)
    payload = await file.read(12_000_001)
    if len(payload) > 12_000_000:
        raise HTTPException(413, "Artwork exceeds 12 MB")
    try:
        await save_manual_artwork(session, item_id, expected_revision, role, payload)
        await queue_nfo_export(session, await admin_item(session, item_id))
        await session.commit()
        return await admin_item(session, item_id)
    except (ValueError, ProviderUnavailable) as error:
        raise metadata_error(error) from error
