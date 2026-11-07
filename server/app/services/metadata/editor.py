"""Administrator metadata mutations, optimistic concurrency, and explicit restoration."""

import asyncio
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.metadata import Artwork, MediaItem, MetadataJob

from .files import store_artwork
from .http import utcnow
from .merge import content_hash
from .queue import enqueue_metadata
from .types import EDITABLE_FIELDS, LOCKABLE_FIELDS, MetadataConflict, parse_date, positive_id


def _validate_changes(changes: dict[str, Any]) -> dict[str, Any]:  # ruff: ignore[complex-structure]
    unknown = set(changes) - EDITABLE_FIELDS
    if "metadata_locale" in changes:
        raise ValueError("Metadata language is configured on the library")
    if unknown:
        raise ValueError(f"Unsupported metadata fields: {', '.join(sorted(unknown))}")
    changes = dict(changes)
    for name, value in changes.items():
        if name in {"season_number", "episode_number"}:
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError("Episode and season numbers must be nonnegative integers")
        elif name in {"aliases", "genres", "keywords", "credits", "studios", "countries"}:
            if not isinstance(value, list) or len(value) > 1000:
                raise ValueError(f"{name} must be a bounded list")
            expected = str if name in {"aliases", "countries"} else dict
            if any(not isinstance(entry, expected) for entry in value):
                raise ValueError(f"Invalid {name} entries")
        elif name == "provider_ids":
            if not isinstance(value, dict) or any(
                not isinstance(key, str) or not isinstance(identifier, str) for key, identifier in value.items()
            ):
                raise ValueError("Provider identifiers must map names to strings")
            for provider in ("tmdb", "anidb", "tvdb"):
                if provider in value:
                    positive_id(value[provider])
        elif name == "release_date":
            parsed = parse_date(value)
            if value is not None and parsed is None:
                raise ValueError("Invalid release date")
            changes[name] = parsed
        elif value is not None and (not isinstance(value, str) or len(value) > 100_000):
            raise ValueError(f"Invalid {name}")
    if changes.get("title") is None and "title" in changes:
        raise ValueError("Title cannot be null")
    return changes


async def apply_metadata_patch(
    session: AsyncSession,
    item_id: int,
    expected_revision: int,
    changes: dict[str, Any],
    locks: list[str] | None = None,
    locked: bool | None = None,
    locale: str | None = None,
) -> MediaItem:
    changes = _validate_changes(changes)
    item = await session.get(MediaItem, item_id, populate_existing=True)
    if item is None:
        raise ValueError("Metadata item does not exist")
    if (
        item.kind == "episode"
        and (item.season_number is None or item.episode_number is None)
        and any(changes.get(field) is not None for field in ("season_number", "episode_number"))
    ):
        raise ValueError("Associate the unidentified file with a catalogue episode before editing its numbering")
    selected_locks: set[str] = set(locks if locks is not None else item.locked_fields or []) | set(changes)
    if selected_locks - LOCKABLE_FIELDS:
        raise ValueError("Unknown metadata lock")
    provenance = dict(item.provenance or {})
    for name in changes:
        provenance[name] = {
            "source": "manual",
            "locale": locale or item.metadata_locale,
            "updated_at": utcnow().isoformat(),
        }
    fields = {name: changes.get(name, getattr(item, name)) for name in EDITABLE_FIELDS}
    values = {
        **changes,
        "locked_fields": sorted(selected_locks),
        "provenance": provenance,
        "revision": expected_revision + 1,
        "generation": item.generation + 1,
        "content_hash": content_hash(fields),
        "updated_at": utcnow(),
    }
    if locked is not None:
        values["locked"] = locked
    result = await session.execute(
        update(MediaItem)
        .where(MediaItem.id == item_id, MediaItem.revision == expected_revision)
        .values(**values)
        .returning(MediaItem.id)
        .execution_options(synchronize_session=False)
    )
    if result.scalar_one_or_none() is None:
        raise MetadataConflict("Metadata changed; reload before saving")
    await session.refresh(item)
    return item


async def identify_metadata(
    session: AsyncSession, item_id: int, expected_revision: int, provider: str, provider_id: str
) -> MetadataJob:
    if provider not in {"tmdb", "anidb"}:
        raise ValueError("Unsupported identification provider")
    current = await session.get(MediaItem, item_id)
    if current is None or current.kind not in {"movie", "series"}:
        raise ValueError("Identify the containing series rather than an individual season or episode")
    item = await apply_metadata_patch(
        session, item_id, expected_revision, {"provider_ids": {provider: positive_id(provider_id)}}
    )
    item.provider_data = {**(item.provider_data or {}), "identification_source": provider}
    return await enqueue_metadata(session, item)


async def refresh_metadata(
    session: AsyncSession, item_id: int, expected_revision: int, mode: str = "unlocked"
) -> MetadataJob:
    if mode not in {"missing", "unlocked"}:
        raise ValueError("Refresh mode must be missing or unlocked")
    item = await apply_metadata_patch(session, item_id, expected_revision, {})
    if item.kind in {"season", "episode"} and item.series_id:
        series = await session.get(MediaItem, item.series_id)
        if series is None:
            raise ValueError("Containing series is unavailable")
        item = series
        item.generation += 1
        item.revision += 1
    job = await enqueue_metadata(session, item)
    job.mode = mode
    return job


async def restore_metadata_fields(
    session: AsyncSession, item_id: int, expected_revision: int, fields: list[str]
) -> MediaItem:
    item = await session.get(MediaItem, item_id)
    if item is None or set(fields) - EDITABLE_FIELDS:
        raise ValueError("Invalid item or restoration fields")
    proposal = (item.provider_data or {}).get("last_proposal", {})
    if any(name not in proposal.get("fields", {}) for name in fields):
        raise ValueError("Refresh the provider metadata before restoring these fields")
    changes = {name: proposal["fields"][name] for name in fields}
    item = await apply_metadata_patch(
        session, item_id, expected_revision, changes, locks=[name for name in item.locked_fields if name not in fields]
    )
    provenance = dict(item.provenance or {})
    for name in fields:
        provenance[name] = proposal.get("provenance", {}).get(name, {"source": "provider"})
    item.provenance = provenance
    item.locked_fields = [name for name in item.locked_fields if name not in fields]
    return item


async def save_manual_artwork(
    session: AsyncSession, item_id: int, expected_revision: int, role: str, payload: bytes
) -> Artwork:
    if role not in {"poster", "backdrop"}:
        raise ValueError("Artwork role must be poster or backdrop")
    location, digest = await asyncio.to_thread(store_artwork, payload)
    current = await session.get(MediaItem, item_id)
    if current is None:
        raise ValueError("Metadata item does not exist")
    await apply_metadata_patch(
        session, item_id, expected_revision, {}, locks=sorted(set(current.locked_fields or []) | {role})
    )
    art = await session.scalar(select(Artwork).where(Artwork.item_id == item_id, Artwork.role == role))
    if art is None:
        art = Artwork(item_id=item_id, role=role)
        session.add(art)
    art.path, art.sha256, art.source = location, digest, "manual"
    art.language = current.metadata_locale
    await session.flush()
    return art
