"""Bounded editorial projections; physical playback continues to use file IDs."""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import cast

from fastapi import HTTPException
from sqlalchemy import ColumnElement, and_, case, func, or_, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, load_only

from app.models import Artwork, Library, MediaCardSchema, MediaFile, MediaItem, MediaItemFile, MediaView, UserItemState
from app.models.metadata import Availability, ItemCardSchema, ItemDetailSchema, ItemKind
from app.services.catalogue import visible_media_filter, watchlist_membership


def visible_item_filter(library_id: int | None = None) -> ColumnElement[bool]:
    """Metadata ownership never changes the existing nested-directory visibility rules."""
    owner, visible = aliased(Library), aliased(Library)
    prefix = func.rtrim(visible.path, "/").concat("/")
    libraries = (
        select(visible.id)
        .select_from(visible)
        .join(owner, owner.id == MediaItem.metadata_library_id)
        .where(
            visible.enabled.is_(True),
            or_(visible.id == owner.id, func.substr(owner.path, 1, func.length(prefix)) == prefix),
        )
    )
    if library_id is not None:
        libraries = libraries.where(visible.id == library_id)
    # An explicitly removed owner must not destroy the metadata of a still-visible physical file.
    linked = aliased(MediaItem)
    group = or_(
        linked.series_id == case((MediaItem.kind == "series", MediaItem.id), else_=MediaItem.series_id),
        linked.collection_id == case((MediaItem.kind == "collection", MediaItem.id), else_=MediaItem.collection_id),
    )
    physical = (
        select(MediaItemFile.item_id)
        .join(linked, linked.id == MediaItemFile.item_id)
        .join(MediaFile, MediaFile.id == MediaItemFile.media_file_id)
        .where(
            or_(linked.id == MediaItem.id, and_(MediaItem.metadata_library_id.is_(None), group)),
            visible_media_filter(library_id),
        )
        .exists()
    )
    return or_(libraries.exists(), physical)


async def require_item(session: AsyncSession, item_id: int) -> MediaItem:
    item = await session.scalar(select(MediaItem).where(MediaItem.id == item_id, visible_item_filter()))
    if item is None:
        raise HTTPException(404, "Media item not found")
    return item


def artwork_url(artwork: Artwork) -> str:
    return f"/api/v1/items/{artwork.item_id}/images/{artwork.role}?v={artwork.sha256}"


async def _container_states(session: AsyncSession, user_id: int, ids: Sequence[int]) -> dict[int, tuple[int, int, int]]:
    """Aggregate seen state in SQL without loading every episode's metadata."""
    today = datetime.now(UTC).date()
    children = union_all(*[
        select(column.label("container_id"), MediaItem.id.label("child_id")).where(
            column.in_(ids),
            MediaItem.kind.in_(("movie", "episode")),
            or_(MediaItem.release_date.is_(None), MediaItem.release_date <= today),
        )
        for column in (MediaItem.parent_id, MediaItem.series_id, MediaItem.collection_id)
    ]).subquery()
    rows = await session.execute(
        select(
            children.c.container_id,
            func.count(),
            func.sum(case((UserItemState.watched.is_(True), 1), else_=0)),
            func.coalesce(func.max(UserItemState.state_revision), 0),
        )
        .outerjoin(UserItemState, and_(UserItemState.item_id == children.c.child_id, UserItemState.user_id == user_id))
        .group_by(children.c.container_id)
    )
    return {row[0]: (row[1], row[2], row[3]) for row in rows}


async def item_cards(session: AsyncSession, user_id: int, item_ids: Sequence[int]) -> list[ItemCardSchema]:
    if not item_ids:
        return []
    rows = list(
        await session.execute(
            select(MediaItem, MediaItem.provider_data["year"].as_integer())
            .where(MediaItem.id.in_(item_ids), visible_item_filter())
            .options(
                load_only(
                    MediaItem.id,
                    MediaItem.kind,
                    MediaItem.title,
                    MediaItem.original_title,
                    MediaItem.release_date,
                    MediaItem.parent_id,
                    MediaItem.series_id,
                    MediaItem.collection_id,
                    MediaItem.season_number,
                    MediaItem.episode_number,
                    MediaItem.hierarchy_complete,
                    MediaItem.metadata_status,
                )
            )
        )
    )
    items = [row[0] for row in rows]
    discovered_years = {row[0].id: row[1] for row in rows}
    if not items:
        return []
    states = {
        state.item_id: state
        for state in await session.scalars(
            select(UserItemState).where(UserItemState.user_id == user_id, UserItemState.item_id.in_(item_ids))
        )
    }
    # Select the actual most recent resume edition, never carry seconds between editions.
    other_links = aliased(MediaItemFile)
    ranked = (
        select(
            MediaItemFile.item_id,
            MediaItemFile.start_seconds,
            MediaItemFile.end_seconds,
            select(func.count())
            .select_from(other_links)
            .where(other_links.media_file_id == MediaItemFile.media_file_id)
            .scalar_subquery()
            .label("link_count"),
            MediaFile.id.label("file_id"),
            MediaFile.duration,
            MediaView.position_seconds,
            MediaView.duration_seconds,
            MediaView.resume_active,
            func
            .row_number()
            .over(
                partition_by=MediaItemFile.item_id,
                order_by=(
                    MediaView.resume_active.desc().nullslast(),
                    MediaView.last_viewed_at.desc().nullslast(),
                    MediaFile.id,
                ),
            )
            .label("rank"),
        )
        .join(MediaFile, MediaFile.id == MediaItemFile.media_file_id)
        .outerjoin(MediaView, and_(MediaView.media_file_id == MediaFile.id, MediaView.user_id == user_id))
        .where(MediaItemFile.item_id.in_(item_ids), visible_media_filter())
        .subquery()
    )
    files = {row.item_id: row for row in await session.execute(select(ranked).where(ranked.c.rank == 1))}
    art_ids = set(item_ids)
    art_ids.update(id_ for item in items for id_ in (item.parent_id, item.series_id) if id_ is not None)
    artwork = {
        (art.item_id, art.role): art
        for art in await session.scalars(
            select(Artwork).where(Artwork.item_id.in_(art_ids), Artwork.role.in_(("poster", "still")))
        )
    }
    containers = [item.id for item in items if item.kind in ("series", "season", "collection")]
    aggregate = await _container_states(session, user_id, containers) if containers else {}
    available_containers: set[int] = set()
    if containers:
        available_rows = await session.execute(
            select(MediaItem.parent_id, MediaItem.series_id, MediaItem.collection_id)
            .join(MediaItemFile, MediaItemFile.item_id == MediaItem.id)
            .join(MediaFile, MediaFile.id == MediaItemFile.media_file_id)
            .where(
                or_(
                    MediaItem.parent_id.in_(containers),
                    MediaItem.series_id.in_(containers),
                    MediaItem.collection_id.in_(containers),
                ),
                visible_media_filter(),
            )
            .distinct()
        )
        available_containers = {id_ for row in available_rows for id_ in row if id_ is not None}
    cards: dict[int, ItemCardSchema] = {}
    today = datetime.now(UTC).date()
    for item in items:
        file = files.get(item.id)
        state = states.get(item.id)
        availability: Availability = "missing"
        if file is not None or item.id in available_containers:
            availability = "available"
        elif item.release_date and item.release_date > today:
            availability = "upcoming"
        elif item.metadata_status in ("pending", "error", "needs_identification"):
            availability = "incomplete"
        poster = next(
            (
                artwork[id_, "poster"]
                for id_ in (item.id, item.parent_id, item.series_id)
                if id_ is not None and (id_, "poster") in artwork
            ),
            None,
        )
        poster = poster or artwork.get((item.id, "still"))
        total, seen, revision = aggregate.get(item.id, (0, 0, 0))
        position = (file.position_seconds or 0) if file else 0
        duration = (file.duration_seconds or file.duration) if file else None
        active = bool(file and file.resume_active)
        progress = 0.0
        if file:
            if (
                file.start_seconds is not None
                and file.end_seconds is not None
                and file.start_seconds < file.end_seconds
            ):
                active = active and file.start_seconds <= position < file.end_seconds
                progress = 100 * max(0, position - file.start_seconds) / (file.end_seconds - file.start_seconds)
            elif file.link_count > 1:
                active = False
            elif duration and duration > 0:
                progress = 100 * position / duration
        cards[item.id] = ItemCardSchema(
            id=item.id,
            kind=cast("ItemKind", item.kind),
            title=item.title,
            original_title=item.original_title,
            year=item.release_date.year if item.release_date else discovered_years.get(item.id),
            release_date=item.release_date,
            parent_id=item.parent_id,
            series_id=item.series_id,
            collection_id=item.collection_id,
            season_number=item.season_number,
            episode_number=item.episode_number,
            poster_url=artwork_url(poster) if poster else (f"/api/v1/media/{file.file_id}/thumbnail" if file else None),
            availability=availability,
            playable_file_id=file.file_id if file else None,
            watched=(total > 0 and total == seen) if item.id in aggregate else bool(state and state.watched),
            state_revision=revision if item.id in aggregate else (state.state_revision if state else 0),
            position_seconds=position if active else ((file.start_seconds or 0) if file else 0),
            duration_seconds=duration,
            progress_percent=min(100, max(0, progress)) if active else 0,
            resume_active=active,
            hierarchy_complete=item.hierarchy_complete,
            metadata_status=item.metadata_status,
        )
    return [cards[id_] for id_ in item_ids if id_ in cards]


async def get_item_detail(session: AsyncSession, user_id: int, item_id: int) -> ItemDetailSchema:
    item = await require_item(session, item_id)
    cards = await item_cards(session, user_id, [item_id])
    file_ids = list(
        await session.scalars(
            select(MediaItemFile.media_file_id)
            .join(MediaFile, MediaFile.id == MediaItemFile.media_file_id)
            .where(MediaItemFile.item_id == item_id, visible_media_filter())
            .order_by(MediaItemFile.position, MediaFile.id)
        )
    )
    multi = bool(
        file_ids
        and await session.scalar(
            select(MediaItemFile.item_id)
            .where(MediaItemFile.media_file_id.in_(file_ids), MediaItemFile.item_id != item_id)
            .limit(1)
        )
    )
    backdrop = await session.scalar(
        select(Artwork)
        .where(Artwork.item_id.in_([item_id, item.series_id or item_id]), Artwork.role == "backdrop")
        .order_by((Artwork.item_id == item_id).desc())
        .limit(1)
    )
    return ItemDetailSchema(
        **cards[0].model_dump(),
        overview=item.overview,
        tagline=item.tagline,
        metadata_locale=item.metadata_locale,
        aliases=item.aliases,
        genres=item.genres,
        keywords=item.keywords,
        credits=item.credits,
        provider_ids=item.provider_ids,
        backdrop_url=artwork_url(backdrop) if backdrop else None,
        file_ids=file_ids,
        multi_episode_file=multi,
        order_confirmed=item.order_confirmed,
        in_watchlist=bool(
            cards[0].playable_file_id
            and await session.scalar(
                select(watchlist_membership(user_id))
                .select_from(MediaFile)
                .where(MediaFile.id == cards[0].playable_file_id)
            )
        ),
    )


async def refresh_library_metadata(session: AsyncSession, library: Library) -> None:
    from app.services.metadata import enqueue_metadata

    items = await session.scalars(select(MediaItem).where(MediaItem.metadata_library_id == library.id))
    for item in items:
        item.metadata_locale = library.metadata_locale
        item.generation += 1
        item.revision += 1
        if item.kind in ("movie", "series", "collection"):
            await enqueue_metadata(session, item)


async def enrich_file_cards[Card: MediaCardSchema](
    session: AsyncSession, user_id: int, cards: list[Card]
) -> list[Card]:
    """One bounded extra query for legacy file cards, never fetch full editorial payloads."""
    if not cards:
        return cards
    own_art, parent_art, series_art = aliased(Artwork), aliased(Artwork), aliased(Artwork)
    rows = await session.execute(
        select(
            MediaItemFile.media_file_id,
            MediaItem.id,
            MediaItem.title,
            MediaItem.release_date,
            MediaItem.provider_data["discovery"]["year"].as_integer(),
            UserItemState.watched,
            UserItemState.state_revision,
            func.coalesce(own_art.item_id, parent_art.item_id, series_art.item_id),
            func.coalesce(own_art.sha256, parent_art.sha256, series_art.sha256),
        )
        .join(MediaItem, MediaItem.id == MediaItemFile.item_id)
        .outerjoin(UserItemState, and_(UserItemState.item_id == MediaItem.id, UserItemState.user_id == user_id))
        .outerjoin(own_art, and_(own_art.item_id == MediaItem.id, own_art.role == "poster"))
        .outerjoin(parent_art, and_(parent_art.item_id == MediaItem.parent_id, parent_art.role == "poster"))
        .outerjoin(series_art, and_(series_art.item_id == MediaItem.series_id, series_art.role == "poster"))
        .where(MediaItemFile.media_file_id.in_([card.id for card in cards]))
        .order_by(MediaItemFile.media_file_id, MediaItemFile.position, MediaItem.id)
    )
    linked = {}
    for row in rows:
        linked.setdefault(row[0], row)
    for card in cards:
        row = linked.get(card.id)
        if row:
            _, item_id, title, released, year, watched, revision, art_id, digest = row
            card.item_id, card.title, card.year = item_id, title, released.year if released else year
            card.watched = bool(watched)
            card.state_revision = revision or 0
            if art_id:
                card.poster_url = f"/api/v1/items/{art_id}/images/poster?v={digest}"
        elif card.user_view:
            card.watched = card.user_view.watched
    return cards
