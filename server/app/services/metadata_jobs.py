"""Scheduler integration for durable discovery and periodic editorial refresh."""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select

from app.database import async_session_maker
from app.models import Library, MediaItem, MetadataJob
from app.services.item_discovery import discover_items
from app.services.metadata import enqueue_metadata, process_metadata_jobs

logger = logging.getLogger(__name__)


async def enqueue_due_metadata(limit: int = 20) -> int:
    now = datetime.now(UTC).replace(tzinfo=None)
    async with async_session_maker() as session:
        latest = select(MetadataJob.item_id, func.max(MetadataJob.updated_at).label("last_attempt"))
        latest = latest.group_by(MetadataJob.item_id).subquery()
        active = (
            select(MetadataJob.id)
            .where(MetadataJob.item_id == MediaItem.id, MetadataJob.status.in_(("pending", "running")))
            .exists()
        )
        items = list(
            await session.scalars(
                select(MediaItem)
                .join(Library, Library.id == MediaItem.metadata_library_id)
                .outerjoin(latest, latest.c.item_id == MediaItem.id)
                .where(
                    Library.enabled.is_(True),
                    MediaItem.kind.in_(("movie", "series", "collection")),
                    or_(MediaItem.locked.is_(False), MediaItem.kind.in_(("series", "collection"))),
                    ~active,
                    func.coalesce(latest.c.last_attempt, MediaItem.updated_at) < now - timedelta(days=1),
                )
                .order_by(latest.c.last_attempt.asc().nullsfirst(), MediaItem.id)
                .limit(limit)
            )
        )
        for item in items:
            await enqueue_metadata(session, item, force=True)
        await session.commit()
        return len(items)


async def metadata_tick() -> None:
    try:
        await discover_items()
        await enqueue_due_metadata()
        await process_metadata_jobs(limit=2)
    except Exception:
        # A provider or one malformed item must never stop the scheduler/streaming service.
        logger.exception("Metadata maintenance failed; durable work will be retried")
