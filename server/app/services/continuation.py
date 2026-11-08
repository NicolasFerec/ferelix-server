"""Choose the logical successor before looking for playable files."""

import asyncio
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Literal

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.models import MediaFile, MediaView, Settings
from app.models.metadata import MediaItem, MediaItemFile, UserItemState
from app.services.catalogue import visible_media_filter
from app.services.item_catalogue import require_item, visible_item_filter

ContinuationStatus = Literal["ready", "missing", "upcoming", "unknown_order", "complete"]
_ORDER_FIELDS = (
    MediaItem.id,
    MediaItem.kind,
    MediaItem.metadata_library_id,
    MediaItem.parent_id,
    MediaItem.series_id,
    MediaItem.collection_id,
    MediaItem.release_date,
    MediaItem.season_number,
    MediaItem.episode_number,
    MediaItem.hierarchy_complete,
    MediaItem.order_confirmed,
    MediaItem.first_available_at,
)


@dataclass(slots=True)
class ContinuationChoice:
    status: ContinuationStatus
    item_id: int | None = None
    media_file_id: int | None = None
    position_seconds: float = 0


def _contiguous_numbers(numbers: list[int]) -> bool:
    return bool(numbers) and sorted(numbers) == list(range(1, len(numbers) + 1))


def ordered_leaves(root: MediaItem, items: list[MediaItem]) -> list[MediaItem] | None:
    """Do not use filenames, available files, IDs or scan order to invent an order."""
    if root.kind == "movie":
        return [root]
    if not root.hierarchy_complete or not root.order_confirmed:
        return None
    if root.kind == "collection":
        leaves = [item for item in items if item.kind == "movie" and item.collection_id == root.id]
        dates = [item.release_date for item in leaves]
        if None in dates or len(set(dates)) != len(dates):
            return None
        return sorted(leaves, key=lambda item: item.release_date or date.min)
    if root.kind not in {"series", "season"}:
        return None
    if root.kind == "season" and root.season_number == 0:
        return None
    seasons = {item.id: item for item in items if item.kind == "season"}
    if root.kind == "season":
        seasons[root.id] = root
    # Specials are isolated from the main sequence until an explicit supported
    # ordering is supplied; an autoplay request originating from one is refused.
    main_seasons = [season for season in seasons.values() if season.season_number != 0]
    numbers = [season.season_number for season in main_seasons]
    if None in numbers or len(set(numbers)) != len(numbers):
        return None
    ordered_numbers = sorted(number for number in numbers if number is not None)
    if root.kind == "series" and ordered_numbers != list(range(1, len(ordered_numbers) + 1)):
        return None
    if any(not season.hierarchy_complete or not season.order_confirmed for season in main_seasons):
        return None
    leaves = [item for item in items if item.kind == "episode" and item.season_number != 0]
    keys = []
    for item in leaves:
        parent = seasons.get(item.parent_id) if item.parent_id is not None else None
        if (
            item.season_number is None
            or item.season_number < 1
            or item.episode_number is None
            or item.episode_number < 1
            or parent is None
            or parent.season_number != item.season_number
            or (root.kind == "series" and (item.series_id != root.id or parent.parent_id != root.id))
        ):
            return None
        keys.append((item.season_number, item.episode_number))
    if len(set(keys)) != len(keys):
        return None
    if any(
        not _contiguous_numbers([episode for season, episode in keys if season == number]) for number in ordered_numbers
    ):
        return None
    return [item for _key, item in sorted(zip(keys, leaves, strict=True), key=lambda pair: pair[0])]


async def _hierarchy(session: AsyncSession, source: MediaItem) -> tuple[MediaItem, list[MediaItem]]:
    root = source
    if source.kind == "episode" and source.series_id is not None:
        root = await require_item(session, source.series_id)
    elif source.kind == "movie" and source.collection_id is not None:
        root = await require_item(session, source.collection_id)
    if root.kind == "series":
        condition = or_(MediaItem.series_id == root.id, MediaItem.parent_id == root.id)
    elif root.kind == "season":
        condition = MediaItem.parent_id == root.id
    elif root.kind == "collection":
        condition = MediaItem.collection_id == root.id
    else:
        return root, [root]
    items = list(
        await session.scalars(
            select(MediaItem)
            .options(load_only(*_ORDER_FIELDS))
            .where(
                condition,
                MediaItem.metadata_library_id == root.metadata_library_id,
            )
        )
    )
    return root, items


def choose_logical_target(
    root: MediaItem,
    items: list[MediaItem],
    watched: set[int],
    source: MediaItem,
    mode: Literal["next", "continue"],
) -> ContinuationChoice:
    if source.kind == "episode" and source.season_number == 0:
        return ContinuationChoice("unknown_order")
    leaves = ordered_leaves(root, items)
    if leaves is None:
        return ContinuationChoice("unknown_order")
    if mode == "next":
        index = next((index for index, item in enumerate(leaves) if item.id == source.id), None)
        if index is None:
            return ContinuationChoice("unknown_order")
        target = leaves[index + 1] if index + 1 < len(leaves) else None
    else:
        target = next((item for item in leaves if item.id not in watched), None)
        if root.kind == "movie":
            target = root  # Explicitly continuing a standalone movie also supports rewatching.
    return ContinuationChoice("missing", target.id) if target is not None else ContinuationChoice("complete")


async def _resolve_files(
    session: AsyncSession,
    user_id: int,
    choices: list[ContinuationChoice],
    *,
    resume: bool,
    check_files: bool = False,
    now: datetime | None = None,
) -> None:
    now = now or datetime.now(UTC).replace(tzinfo=None)
    ids = [choice.item_id for choice in choices if choice.item_id is not None]
    if not ids:
        return
    items = {
        item.id: item
        for item in await session.scalars(
            select(MediaItem).options(load_only(MediaItem.id, MediaItem.release_date)).where(MediaItem.id.in_(ids))
        )
    }
    rows = list(
        (
            await session.execute(
                select(MediaItemFile, MediaFile, MediaView)
                .join(MediaFile, MediaFile.id == MediaItemFile.media_file_id)
                .outerjoin(MediaView, and_(MediaView.media_file_id == MediaFile.id, MediaView.user_id == user_id))
                .where(MediaItemFile.item_id.in_(ids), visible_media_filter())
                .order_by(
                    MediaView.resume_active.desc().nullslast(),
                    MediaView.last_viewed_at.desc().nullslast(),
                    MediaItemFile.position,
                    MediaFile.id,
                )
            )
        ).all()
    )
    counts = dict(
        (
            await session.execute(
                select(MediaItemFile.media_file_id, func.count())
                .where(MediaItemFile.media_file_id.in_([row[1].id for row in rows]))
                .group_by(MediaItemFile.media_file_id)
            )
        ).all()
    )
    for choice in choices:
        item = items.get(choice.item_id) if choice.item_id is not None else None
        if item is None:
            continue
        if item.release_date and item.release_date > now.date():
            choice.status = "upcoming"
            continue
        ambiguous = False
        for link, file, view in rows:
            if link.item_id != item.id:
                continue
            bounded = (
                link.start_seconds is not None
                and link.end_seconds is not None
                and 0 <= link.start_seconds < link.end_seconds
            )
            if counts.get(file.id, 0) > 1 and not bounded:
                ambiguous = True
                continue
            if check_files and not await asyncio.to_thread(Path(file.file_path).is_file):
                continue
            position = link.start_seconds or 0
            if (
                resume
                and view is not None
                and view.resume_active
                and (
                    not bounded
                    or (
                        link.start_seconds is not None
                        and link.end_seconds is not None
                        and link.start_seconds <= view.position_seconds < link.end_seconds
                    )
                )
            ):
                position = view.position_seconds
            choice.status, choice.media_file_id, choice.position_seconds = "ready", file.id, position
            break
        else:
            choice.status = "unknown_order" if ambiguous else "missing"


async def resolve_continuation(
    session: AsyncSession,
    user_id: int,
    item_id: int,
    mode: Literal["next", "continue"] = "continue",
    *,
    check_files: bool = False,
) -> ContinuationChoice:
    source = await require_item(session, item_id)
    if mode == "next":
        shared_files = (
            select(MediaItemFile.media_file_id).group_by(MediaItemFile.media_file_id).having(func.count() > 1)
        )
        if (
            await session.scalar(
                select(MediaItemFile.media_file_id)
                .where(
                    MediaItemFile.item_id == source.id,
                    MediaItemFile.media_file_id.in_(shared_files),
                )
                .limit(1)
            )
            is not None
        ):
            # The player currently emits ended for the physical file, not for an
            # episode segment. Advancing from E1 after E1+E2 ended would replay E2.
            return ContinuationChoice("unknown_order")
    root, items = await _hierarchy(session, source)
    watched = set(
        await session.scalars(
            select(UserItemState.item_id).where(
                UserItemState.user_id == user_id,
                UserItemState.item_id.in_([item.id for item in items]),
                UserItemState.watched.is_(True),
            )
        )
    )
    choice = choose_logical_target(root, items, watched, source, mode)
    await _resolve_files(session, user_id, [choice], resume=mode == "continue", check_files=check_files)
    return choice


async def resume_choices(session: AsyncSession, user_id: int, limit: int | None = 24) -> list[ContinuationChoice]:
    rows = list(
        (
            await session.execute(
                select(MediaItemFile, MediaFile, MediaView)
                .join(MediaItem, MediaItem.id == MediaItemFile.item_id)
                .join(MediaFile, MediaFile.id == MediaItemFile.media_file_id)
                .join(MediaView, and_(MediaView.media_file_id == MediaFile.id, MediaView.user_id == user_id))
                .where(MediaView.resume_active.is_(True), visible_media_filter(), visible_item_filter())
                .order_by(MediaView.last_viewed_at.desc(), MediaItem.id)
            )
        ).all()
    )
    counts = dict(
        (
            await session.execute(
                select(MediaItemFile.media_file_id, func.count())
                .where(MediaItemFile.media_file_id.in_([row[1].id for row in rows]))
                .group_by(MediaItemFile.media_file_id)
            )
        ).all()
    )
    choices: dict[int, ContinuationChoice] = {}
    for link, file, view in rows:
        bounded = (
            link.start_seconds is not None
            and link.end_seconds is not None
            and 0 <= link.start_seconds < link.end_seconds
        )
        position = view.position_seconds
        if counts.get(file.id, 0) > 1 and not bounded:
            continue
        if bounded:
            assert link.start_seconds is not None and link.end_seconds is not None
            if not link.start_seconds <= position < link.end_seconds:
                continue
            position -= link.start_seconds
        if position <= 10:
            continue
        choices.setdefault(link.item_id, ContinuationChoice("ready", link.item_id, file.id, view.position_seconds))
        if limit is not None and len(choices) == limit:
            break
    return list(choices.values())


async def next_up_choices(
    session: AsyncSession, user_id: int, limit: int = 24, now: datetime | None = None
) -> list[ContinuationChoice]:
    """Batch hierarchies/states/files; expiry never depends on polling or a later candidate's availability."""
    now = now or datetime.now(UTC).replace(tzinfo=None)
    root_id = case(
        (MediaItem.kind == "episode", MediaItem.series_id), (MediaItem.kind == "movie", MediaItem.collection_id)
    )
    activity_rows = await session.execute(
        select(root_id, func.max(UserItemState.last_activity_at))
        .join(UserItemState, UserItemState.item_id == MediaItem.id)
        .where(
            UserItemState.user_id == user_id,
            UserItemState.last_activity_at.is_not(None),
            root_id.is_not(None),
            visible_item_filter(),
        )
        .group_by(root_id)
    )
    activity = {id_: timestamp for id_, timestamp in activity_rows if id_ is not None and timestamp is not None}
    if not activity:
        return []
    roots = list(
        await session.scalars(
            select(MediaItem)
            .options(load_only(*_ORDER_FIELDS))
            .where(MediaItem.id.in_(activity), MediaItem.kind.in_(["series", "collection"]), visible_item_filter())
        )
    )
    items = list(
        await session.scalars(
            select(MediaItem)
            .options(load_only(*_ORDER_FIELDS))
            .where(
                or_(
                    MediaItem.series_id.in_(activity),
                    MediaItem.collection_id.in_(activity),
                    MediaItem.parent_id.in_(activity),
                ),
                visible_item_filter(),
            )
        )
    )
    watched = set(
        await session.scalars(
            select(UserItemState.item_id).where(
                UserItemState.user_id == user_id,
                UserItemState.item_id.in_([item.id for item in items]),
                UserItemState.watched.is_(True),
            )
        )
    )
    settings = await session.get(Settings, 1)
    days = settings.next_up_retention_days if settings else 90
    candidates = []
    by_id = {item.id: item for item in items}
    roots_by_id = {root.id: root for root in roots}
    children_by_root: dict[int, list[MediaItem]] = {root.id: [] for root in roots}
    # Group once instead of scanning every episode for every active series.
    # Deduplicate parent/series IDs: a season belongs to the same root via both.
    for item in items:
        for id_ in {item.series_id, item.collection_id, item.parent_id}:
            root = roots_by_id.get(id_) if id_ is not None else None
            if root is not None and item.metadata_library_id == root.metadata_library_id:
                children_by_root[root.id].append(item)
    resume_ids = {choice.item_id for choice in await resume_choices(session, user_id, limit=None)}
    resuming_roots = {
        id_
        for item in items
        if item.id in resume_ids
        for id_ in (item.series_id, item.collection_id)
        if id_ is not None
    }
    for root in roots:
        if root.id in resuming_roots:
            continue
        choice = choose_logical_target(root, children_by_root[root.id], watched, root, "continue")
        selected = by_id.get(choice.item_id) if choice.item_id is not None else None
        if selected is None:
            continue
        relevant = max(activity[root.id], selected.first_available_at or datetime.min)
        if days and relevant < now - timedelta(days=days):
            continue
        candidates.append((relevant, choice))
    candidates.sort(key=lambda row: (row[0], row[1].item_id), reverse=True)
    choices = [choice for _activity, choice in candidates]
    await _resolve_files(session, user_id, choices, resume=True, now=now)
    # Missing/upcoming choices remain available on detail continuation, but are
    # masked from the home row; never replace them with a later available item.
    return [choice for choice in choices if choice.status == "ready"][:limit]
