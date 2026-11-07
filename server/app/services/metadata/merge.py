"""Lock-aware provider merges and identity-preserving catalogue reconciliation."""

import hashlib
import json
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.metadata import Artwork, MediaItem, MediaItemFile, UserItemState

from .types import EDITABLE_FIELDS, IdentificationRequired, MetadataConflict, MetadataProposal


def content_hash(fields: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(fields, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def merge_proposal(item: MediaItem, proposal: MetadataProposal, mode: str = "unlocked") -> dict[str, Any]:
    """Pure merge preserves manual empty values and every locked field, including identity."""
    if item.locked:
        return {}
    values: dict[str, Any] = {}
    provenance = dict(item.provenance or {})
    for name, value in proposal.fields.items():
        if name not in EDITABLE_FIELDS or name in (item.locked_fields or []):
            continue
        if mode == "missing" and getattr(item, name) not in (None, "", [], {}):
            continue
        if value is None or (name == "title" and not value):
            continue
        if name == "provider_ids":
            value = {**(item.provider_ids or {}), **value}
        values[name] = value
        provenance[name] = proposal.provenance.get(name, {"source": "provider"})
    values["provenance"] = provenance
    values["locked_fields"] = sorted(set(item.locked_fields or []) | set(proposal.locked_fields))
    values["locked"] = proposal.locked
    if "order" not in (item.locked_fields or []):
        values["order_confirmed"] = proposal.order_confirmed or item.order_confirmed
    values["hierarchy_complete"] = proposal.hierarchy_complete or item.hierarchy_complete
    values["revision"] = item.revision + 1
    values["content_hash"] = content_hash({name: values.get(name, getattr(item, name)) for name in EDITABLE_FIELDS})
    values["metadata_status"] = "ready"
    values["provider_data"] = {
        **(item.provider_data or {}),
        "last_proposal": {
            "fields": json.loads(json.dumps(proposal.fields, default=str)),
            "provenance": proposal.provenance,
        },
    }
    return values


async def _save_proposal(
    session: AsyncSession,
    item: MediaItem,
    proposal: MetadataProposal,
    generation: int,
    revision: int,
    mode: str = "unlocked",
) -> None:
    values = merge_proposal(item, proposal, mode)
    if item.locked and item.kind in {"series", "season", "collection"} and "order" not in (item.locked_fields or []):
        values = {
            "revision": item.revision + 1,
            "hierarchy_complete": proposal.hierarchy_complete or item.hierarchy_complete,
            "order_confirmed": proposal.order_confirmed or item.order_confirmed,
            "metadata_status": "ready",
        }
    if not values:
        return
    result = await session.execute(
        update(MediaItem)
        .where(MediaItem.id == item.id, MediaItem.generation == generation, MediaItem.revision == revision)
        .values(**values)
        .returning(MediaItem.id)
        .execution_options(synchronize_session=False)
    )
    if result.scalar_one_or_none() is None:
        raise MetadataConflict("Discarded metadata fetched before an administrator change")
    await session.refresh(item)


async def _save_children(
    session: AsyncSession,
    parent: MediaItem,
    proposal: MetadataProposal,
    series_id: int,
    mode: str = "unlocked",
    placeholders: list[MediaItem] | None = None,
    placements: dict[int, tuple[int, int]] | None = None,
) -> None:
    if "order" in (parent.locked_fields or []):
        return
    existing = list(await session.scalars(select(MediaItem).where(MediaItem.parent_id == parent.id)))
    for child in proposal.children:
        identifiers = child.fields.get("provider_ids", {})
        match = next(
            (
                item
                for item in existing
                if item.kind == child.kind
                and any(
                    identifier == (item.provider_ids or {}).get(provider)
                    for provider, identifier in identifiers.items()
                    if provider != "anidb"
                )
            ),
            None,
        )
        if match is None:
            number_field = "season_number" if child.kind == "season" else "episode_number"
            match = next(
                (
                    item
                    for item in existing
                    if item.kind == child.kind and getattr(item, number_field) == child.fields.get(number_field)
                ),
                None,
            )
            if match and any(
                provider in (match.provider_ids or {}) and match.provider_ids[provider] != identifier
                for provider, identifier in identifiers.items()
            ):
                raise IdentificationRequired("Episode numbering conflicts with existing identification")
        if child.kind == "episode" and placeholders and placements:
            match = await _adopt_absolute(session, match, parent, child, placeholders, placements)
        if match is None:
            match = MediaItem(
                kind=child.kind,
                parent_id=parent.id,
                series_id=series_id,
                metadata_library_id=parent.metadata_library_id,
                title="",
                metadata_locale=parent.metadata_locale,
            )
            session.add(match)
            await session.flush()
            existing.append(match)
        await _save_proposal(session, match, child, match.generation, match.revision, mode)
        await _save_artwork(session, match, child.prepared_artwork, mode)
        if child.children:
            await _save_children(session, match, child, series_id, mode, placeholders, placements)


async def _adopt_absolute(
    session: AsyncSession,
    target: MediaItem | None,
    parent: MediaItem,
    child: MetadataProposal,
    placeholders: list[MediaItem],
    placements: dict[int, tuple[int, int]],
) -> MediaItem | None:
    coordinate = (child.fields.get("season_number"), child.fields.get("episode_number"))
    candidates = [
        item
        for item in placeholders
        if placements.get((item.provider_data or {}).get("absolute_number", -1)) == coordinate
    ]
    if len(candidates) != 1:
        return target
    source = candidates[0]
    if source.locked or set(source.locked_fields or []) & {"order", "season_number", "episode_number"}:
        return target
    if target is not None and target.id != source.id:
        has_files = await session.scalar(
            select(MediaItemFile.item_id).where(MediaItemFile.item_id == target.id).limit(1)
        )
        has_state = await session.scalar(
            select(UserItemState.item_id).where(UserItemState.item_id == target.id).limit(1)
        )
        if target.locked or target.locked_fields or has_files or has_state:
            source.metadata_status = "needs_identification"
            return target
        await session.delete(target)
        await session.flush()
    source.parent_id = parent.id
    source.season_number, source.episode_number = coordinate
    placeholders.remove(source)
    return source


async def _save_artwork(
    session: AsyncSession, item: MediaItem, assets: dict[str, tuple[str, str, str]], mode: str
) -> None:
    for role, (location, digest, source) in assets.items():
        if item.locked or role in (item.locked_fields or []):
            continue
        art = await session.scalar(select(Artwork).where(Artwork.item_id == item.id, Artwork.role == role))
        if mode == "missing" and art is not None:
            continue
        if art is None:
            art = Artwork(item_id=item.id, role=role)
            session.add(art)
        art.path, art.sha256, art.source = location, digest, source
        art.language = None


async def _save_collection(session: AsyncSession, owner: MediaItem, proposal: MetadataProposal, mode: str) -> None:
    identifier = proposal.fields["provider_ids"]["tmdb"]
    existing = list(
        await session.scalars(
            select(MediaItem).where(
                MediaItem.metadata_library_id == owner.metadata_library_id, MediaItem.kind.in_(["collection", "movie"])
            )
        )
    )
    collection = next(
        (row for row in existing if row.kind == "collection" and (row.provider_ids or {}).get("tmdb") == identifier),
        None,
    )
    if collection is None:
        collection = MediaItem(
            kind="collection",
            metadata_library_id=owner.metadata_library_id,
            title="",
            metadata_locale=owner.metadata_locale,
        )
        session.add(collection)
        await session.flush()
    await _save_proposal(session, collection, proposal, collection.generation, collection.revision, mode)
    await _save_artwork(session, collection, proposal.prepared_artwork, mode)
    if "order" in (collection.locked_fields or []):
        return
    for child in proposal.children:
        movie_id = child.fields["provider_ids"]["tmdb"]
        movie = next(
            (row for row in existing if row.kind == "movie" and (row.provider_ids or {}).get("tmdb") == movie_id), None
        )
        if movie is None:
            movie = MediaItem(
                kind="movie",
                metadata_library_id=owner.metadata_library_id,
                title="",
                metadata_locale=owner.metadata_locale,
            )
            session.add(movie)
            await session.flush()
            existing.append(movie)
        if not movie.locked and "order" not in (movie.locked_fields or []):
            movie.collection_id = collection.id
        await _save_proposal(session, movie, child, movie.generation, movie.revision, "missing")
        await _save_artwork(session, movie, child.prepared_artwork, "missing")
