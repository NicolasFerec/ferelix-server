"""Incrementally attach physical files to local editorial identities, without networking."""

import asyncio
import re
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_maker
from app.models import Library, MediaFile, MediaItem, MediaItemFile, MediaView, UserItemState
from app.services.metadata import enqueue_metadata

_discovery_lock = asyncio.Lock()
_EPISODES = re.compile(r"(?i)(?<![a-z0-9])S(\d{1,3})[ ._-]*E(\d{1,4})(?:[ ._-]*(?:E|-E?)(\d{1,4}))?")
_ABSOLUTE = re.compile(r"(?:^|\s-\s)(\d{1,4})(?:v\d+)?(?:$|\s|\[)", re.IGNORECASE)
_YEAR = re.compile(r"(?:^|[ ._(\[])((?:19|20)\d{2})(?:$|[ ._)\]])")
_PROVIDER_ID = re.compile(r"(?i)[\[{](tmdb|imdb|anidb)(?:id)?[=:-]([a-z0-9]+)[\]}]")
_RELEASE_SUFFIX = re.compile(
    r"(?i)(?:^|[ ._-])(?:2160p|1080p|720p|480p|bluray|bdrip|webrip|web-dl|hdtv|x26[45]|h26[45]|hevc)\b.*$"
)


def parse_name(value: str) -> tuple[str, int | None, dict[str, str]]:
    provider_ids = {match[0].lower(): match[1] for match in _PROVIDER_ID.findall(value)}
    value = _PROVIDER_ID.sub("", value)
    years = list(_YEAR.finditer(value))
    year = years[-1] if years else None
    title = value[: year.start()] if year else _RELEASE_SUFFIX.sub("", value)
    title = re.sub(r"[._]+", " ", title).strip(" -_()[]")
    return title or value, int(year[1]) if year else None, provider_ids


async def _local_item(
    session: AsyncSession,
    library: Library,
    kind: str,
    title: str,
    *,
    parent: MediaItem | None = None,
    series: MediaItem | None = None,
    season: int | None = None,
    episode: int | None = None,
    year: int | None = None,
    provider_ids: dict[str, str] | None = None,
) -> tuple[MediaItem, bool]:
    query = select(MediaItem).where(MediaItem.metadata_library_id == library.id, MediaItem.kind == kind)
    if kind in ("season", "episode"):
        query = query.where(
            MediaItem.parent_id == (parent.id if parent else None),
            MediaItem.season_number == season,
            MediaItem.episode_number == episode,
        )
    else:
        title_match = (
            (func.lower(MediaItem.title) == title.lower())
            | (func.lower(MediaItem.original_title) == title.lower())
            | (func.lower(MediaItem.provider_data["discovery"]["title"].as_string()) == title.lower())
        )
        if year:
            title_match = and_(
                title_match,
                (MediaItem.provider_data["discovery"]["year"].as_integer() == year)
                | (func.extract("year", MediaItem.release_date) == year),
            )
        if provider_ids:
            matches = []
            conflicts = []
            for provider, identifier in provider_ids.items():
                current = MediaItem.provider_ids[provider].as_string()
                matches.append(current == identifier)
                conflicts.append(and_(current.is_not(None), current != identifier))
            query = query.where(~or_(*conflicts))
            exact = list(await session.scalars(query.where(or_(*matches)).limit(2)))
            if len(exact) == 1:
                return exact[0], False
        query = query.where(title_match)
    candidates = list(await session.scalars(query.order_by(MediaItem.id).limit(2)))
    existing = candidates[0] if len(candidates) == 1 else None
    if existing:
        if provider_ids and "provider_ids" not in existing.locked_fields and not existing.locked:
            combined = {**existing.provider_ids, **provider_ids}
            if combined != existing.provider_ids:
                existing.provider_ids = combined
                await enqueue_metadata(session, existing, force=True)
        return existing, False
    item = MediaItem(
        kind=kind,
        title=title,
        metadata_library_id=library.id,
        metadata_locale=library.metadata_locale,
        parent_id=parent.id if parent else None,
        series_id=series.id if series else None,
        season_number=season,
        episode_number=episode,
        provider_ids=provider_ids or {},
        provider_data={"year": year, "discovery": {"year": year, "title": title}},
    )
    session.add(item)
    await session.flush()
    return item, True


async def attach_file(session: AsyncSession, file: MediaFile, libraries: list[Library]) -> list[MediaItem]:  # ruff: ignore[complex-structure]
    existing_ids = list(
        await session.scalars(select(MediaItemFile.item_id).where(MediaItemFile.media_file_id == file.id))
    )
    if existing_ids:
        return list(await session.scalars(select(MediaItem).where(MediaItem.id.in_(existing_ids))))
    owners = [library for library in libraries if file.file_path.startswith(library.path.rstrip("/") + "/")]
    if not owners:
        return []
    library = max(owners, key=lambda entry: len(entry.path.rstrip("/")))
    path = Path(file.file_path)
    match = _EPISODES.search(path.stem)
    if match and match[3] and not 0 <= int(match[3]) - int(match[2]) <= 20:
        # Keep ambiguous ranges in the catalogue for manual association instead
        # of repeatedly starving the durable backlog with the same invalid file.
        match = None
    items: list[MediaItem] = []
    if library.library_type == "show" and match:
        relative = path.relative_to(Path(library.path))
        series_name = relative.parts[0] if len(relative.parts) > 1 else path.stem[: match.start()]
        title, year, identifiers = parse_name(series_name)
        series, new = await _local_item(session, library, "series", title, year=year, provider_ids=identifiers)
        if new:
            directory = Path(library.path) / relative.parts[0] if len(relative.parts) > 1 else Path(library.path)
            series.provider_data = {**series.provider_data, "directory": str(directory)}
        if new:
            await enqueue_metadata(session, series)
        season_number, first = int(match[1]), int(match[2])
        last = int(match[3]) if match[3] else first
        season, _ = await _local_item(
            session, library, "season", f"Season {season_number}", parent=series, series=series, season=season_number
        )
        for number in range(first, last + 1):
            item, _ = await _local_item(
                session,
                library,
                "episode",
                f"{title} — S{season_number:02d}E{number:02d}",
                parent=season,
                series=series,
                season=season_number,
                episode=number,
            )
            items.append(item)
    elif library.library_type == "show":
        relative = path.relative_to(Path(library.path))
        title, year, identifiers = parse_name(relative.parts[0] if len(relative.parts) > 1 else library.name)
        series, new = await _local_item(session, library, "series", title, year=year, provider_ids=identifiers)
        if new:
            directory = Path(library.path) / relative.parts[0] if len(relative.parts) > 1 else Path(library.path)
            series.provider_data = {**series.provider_data, "directory": str(directory)}
        absolute = _ABSOLUTE.search(path.stem) if library.metadata_profile == "anime" else None
        item = MediaItem(
            kind="episode",
            parent_id=series.id,
            series_id=series.id,
            title=path.stem,
            metadata_library_id=library.id,
            metadata_locale=library.metadata_locale,
            metadata_status="needs_identification",
            provider_data={"absolute_number": int(absolute[1]) if absolute else None},
        )
        session.add(item)
        await session.flush()
        if new or series.metadata_status != "pending":
            await enqueue_metadata(session, series, force=not new)
        items.append(item)
    else:
        title, year, identifiers = parse_name(path.stem)
        item, new = await _local_item(session, library, "movie", title, year=year, provider_ids=identifiers)
        if new:
            await enqueue_metadata(session, item)
        items.append(item)
    for position, item in enumerate(items):
        session.add(MediaItemFile(item_id=item.id, media_file_id=file.id, position=position))
        if item.first_available_at is None and file.deleted_at is None:
            item.first_available_at = file.created_at or datetime.now(UTC).replace(tzinfo=None)
    await session.flush()
    if len(items) == 1:
        # Seed only unambiguous associations; keep physical positions untouched.
        for old in await session.scalars(select(MediaView).where(MediaView.media_file_id == file.id)):
            state = await session.get(UserItemState, (old.user_id, items[0].id))
            if state is None:
                session.add(
                    UserItemState(
                        user_id=old.user_id,
                        item_id=items[0].id,
                        watched=old.watched,
                        watched_at=old.completed_at,
                        last_activity_at=old.last_viewed_at
                        if old.position_seconds > 0 or old.watched or old.resume_active
                        else None,
                        state_revision=old.state_revision,
                    )
                )
            elif old.watched and state.state_revision == 0:
                state.watched = True
                state.watched_at = state.watched_at or old.completed_at
    return items


async def discover_items(limit: int = 100, session_factory=async_session_maker) -> int:
    """Physical rows form a durable discovery backlog, including after restart."""
    async with _discovery_lock, session_factory() as session:
        libraries = list(await session.scalars(select(Library)))
        files = list(
            await session.scalars(
                select(MediaFile)
                .where(
                    MediaFile.deleted_at.is_(None),
                    select(Library.id)
                    .where(
                        func.substr(MediaFile.file_path, 1, func.length(func.rtrim(Library.path, "/")) + 1)
                        == func.rtrim(Library.path, "/").concat("/")
                    )
                    .exists(),
                    ~select(MediaItemFile.item_id).where(MediaItemFile.media_file_id == MediaFile.id).exists(),
                )
                .order_by(MediaFile.id)
                .limit(limit)
            )
        )
        for file in files:
            await attach_file(session, file, libraries)
        await session.commit()
        return len(files)
