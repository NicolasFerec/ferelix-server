"""Transactional metadata queue creation and generation deduplication."""

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.library import Library
from app.models.metadata import MediaItem, MetadataJob

from .http import utcnow


async def enqueue_metadata(
    session: AsyncSession, item: MediaItem, force: bool = False, mode: str = "unlocked"
) -> MetadataJob:
    await session.flush()
    if force:
        await session.execute(
            update(MediaItem)
            .where(MediaItem.id == item.id)
            .values(generation=MediaItem.generation + 1, revision=MediaItem.revision + 1)
            .execution_options(synchronize_session=False)
        )
        await session.refresh(item)
    existing = await session.scalar(
        select(MetadataJob).where(MetadataJob.item_id == item.id, MetadataJob.generation == item.generation)
    )
    if existing:
        return existing
    job = MetadataJob(
        item_id=item.id, generation=item.generation, mode=mode, status="pending", attempts=0, next_attempt_at=utcnow()
    )
    if mode != "export":
        item.metadata_status = "pending"
    try:
        async with session.begin_nested():
            session.add(job)
            await session.flush()
    except IntegrityError:
        concurrent = await session.scalar(
            select(MetadataJob).where(MetadataJob.item_id == item.id, MetadataJob.generation == item.generation)
        )
        if concurrent is None:
            raise
        return concurrent
    return job


async def queue_nfo_export(session: AsyncSession, item: MediaItem) -> MetadataJob | None:
    """Persist an export beside the admin edit; the worker needs no provider request."""
    library = await session.get(Library, item.metadata_library_id) if item.metadata_library_id else None
    if library and library.metadata_export_nfo:
        return await enqueue_metadata(session, item, mode="export")
    return None
