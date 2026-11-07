"""Idempotent personal watchlist mutations, enforced by the database."""

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MediaFile, WatchlistEntry
from app.services.catalogue import visible_media_filter


async def add_to_watchlist(session: AsyncSession, user_id: int, media_id: int) -> None:
    visible = await session.scalar(select(MediaFile.id).where(MediaFile.id == media_id, visible_media_filter()))
    if visible is None:
        raise HTTPException(status_code=404, detail="Media file not found in an enabled library")
    insert = sqlite_insert if session.get_bind().dialect.name == "sqlite" else postgres_insert
    await session.execute(
        insert(WatchlistEntry)
        .values(user_id=user_id, media_file_id=media_id)
        .on_conflict_do_nothing(index_elements=["user_id", "media_file_id"])
    )
    await session.commit()


async def remove_from_watchlist(session: AsyncSession, user_id: int, media_id: int) -> None:
    # Removing a missing, deleted or disabled item is deliberately idempotent.
    await session.execute(
        delete(WatchlistEntry).where(
            WatchlistEntry.user_id == user_id,
            WatchlistEntry.media_file_id == media_id,
        )
    )
    await session.commit()
