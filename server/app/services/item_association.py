"""Explicit administrator resolution of an unidentified single-episode file."""

from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MediaItem, MediaItemFile, MediaView, PlaybackSession, UserItemState


async def associate_episode(
    session: AsyncSession, source_id: int, target_id: int, source_revision: int, target_revision: int
) -> int:
    if source_id == target_id:
        raise HTTPException(422, "Select another catalogue episode")
    # Acquire the write lock before reading user state; a concurrent heartbeat or
    # metadata response must either finish before this operation or lose its CAS.
    for item_id, revision in sorted(((source_id, source_revision), (target_id, target_revision))):
        changed = await session.scalar(
            update(MediaItem)
            .where(MediaItem.id == item_id, MediaItem.revision == revision)
            .values(revision=MediaItem.revision + 1, generation=MediaItem.generation + 1)
            .returning(MediaItem.id)
        )
        if changed is None:
            raise HTTPException(409, "Metadata changed; reload both episodes")
    source = await session.get(MediaItem, source_id, populate_existing=True)
    target = await session.get(MediaItem, target_id, populate_existing=True)
    assert source is not None and target is not None
    parent = await session.get(MediaItem, target.parent_id) if target.parent_id else None
    if (
        source.kind != "episode"
        or target.kind != "episode"
        or source.metadata_library_id != target.metadata_library_id
        or source.metadata_library_id is None
        or parent is None
        or parent.kind != "season"
        or target.series_id is None
        or parent.parent_id != target.series_id
        or target.season_number != parent.season_number
        or target.episode_number is None
        or not target.order_confirmed
    ):
        raise HTTPException(422, "Select an identified episode in the same library")
    if source.season_number is not None and source.episode_number is not None:
        raise HTTPException(409, "Only unidentified episode placeholders can be associated")
    if source.locked or source.locked_fields:
        raise HTTPException(409, "Unlock the placeholder's edited metadata before associating it")
    source_links = list(await session.scalars(select(MediaItemFile).where(MediaItemFile.item_id == source_id)))
    if not source_links:
        raise HTTPException(422, "The unidentified episode has no file to associate")
    source_files = [link.media_file_id for link in source_links]
    if await session.scalar(
        select(MediaItemFile.item_id)
        .where(MediaItemFile.media_file_id.in_(source_files), MediaItemFile.item_id != source_id)
        .limit(1)
    ):
        raise HTTPException(409, "A shared multi-episode file cannot be reassigned as a single episode")
    states = list(await session.scalars(select(UserItemState).where(UserItemState.item_id.in_((source_id, target_id)))))
    grouped: dict[int, list[UserItemState]] = {}
    for state in states:
        grouped.setdefault(state.user_id, []).append(state)
    for user_id, versions in grouped.items():
        winner = max(
            versions,
            key=lambda state: (state.last_activity_at or state.watched_at or datetime.min, state.item_id == target_id),
        )
        destination = next((state for state in versions if state.item_id == target_id), None)
        revision = max(state.state_revision for state in versions) + 1
        if destination is None:
            destination = UserItemState(user_id=user_id, item_id=target_id)
            session.add(destination)
        destination.watched = winner.watched
        destination.watched_at = winner.watched_at
        destination.last_activity_at = winner.last_activity_at
        destination.state_revision = revision
    await session.flush()
    # Sessions remain playable, but their captured revision is now obsolete.
    await session.execute(update(PlaybackSession).where(PlaybackSession.item_id == source_id).values(item_id=target_id))
    await session.execute(
        update(MediaView)
        .where(MediaView.media_file_id.in_(source_files))
        .values(state_revision=MediaView.state_revision + 1)
    )
    for link in source_links:
        link.item_id = target_id
    if source.first_available_at is not None:
        target.first_available_at = min(
            target.first_available_at or source.first_available_at, source.first_available_at
        )
    target.provenance = {
        **target.provenance,
        "file_association": {"source": "admin", "previous_item_id": source_id, "file_ids": source_files},
    }
    await session.flush()
    await session.delete(source)
    await session.flush()
    return target_id
