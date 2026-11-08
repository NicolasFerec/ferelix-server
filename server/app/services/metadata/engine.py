"""Durable metadata processing: fetch outside SQL, then apply one atomic catalogue update."""

import asyncio
import hashlib
import logging
from datetime import timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import or_, select, update

from app.database import async_session_maker
from app.models.library import Library
from app.models.media_file import MediaFile
from app.models.metadata import Artwork, MediaItem, MediaItemFile, MetadataJob

from .enrichment import _fetch
from .files import artwork_path, export_nfo, metadata_directory, store_artwork
from .http import CachedHTTP, download, utcnow
from .merge import _save_artwork, _save_children, _save_collection, _save_proposal
from .providers import TMDB, AniDB
from .types import IdentificationRequired, MatchCandidate, MetadataConflict, MetadataProposal, ProviderUnavailable

logger = logging.getLogger(__name__)
_worker = asyncio.Lock()


async def search_metadata(
    query: str, kind: str = "movie", locale: str = "fr-FR", provider: str = "tmdb"
) -> list[MatchCandidate]:
    if kind not in {"movie", "series"} or not query.strip() or len(query) > 200:
        raise ValueError("Search requires a movie/series title of at most 200 characters")
    if provider == "anidb":
        return await AniDB(CachedHTTP()).search(query, kind, locale)
    if provider != "tmdb":
        raise ValueError("Unsupported metadata provider")
    return await TMDB(CachedHTTP()).search(query, kind, locale)


async def _one_artwork(source: str, path: Path | None, http: CachedHTTP | None) -> tuple[str, str, str]:
    if source.startswith(("https://", "http://")):
        key = f"artwork:{hashlib.sha256(source.encode()).hexdigest()}"
        if (
            http
            and (cached := await http.cached(key))
            and await asyncio.to_thread(artwork_path(cached["path"]).is_file)
        ):
            return cached["path"], cached["sha256"], source
        content = await asyncio.to_thread(download, source)
    elif path:
        directory = path if await asyncio.to_thread(path.is_dir) else path.parent
        candidate = (directory / source).resolve()
        if (
            not candidate.is_relative_to(directory.resolve())
            and not candidate.is_relative_to((metadata_directory() / "artwork").resolve())
        ) or candidate.stat().st_size > 20_000_000:
            raise ValueError("NFO artwork must be inside the media directory")
        content = await asyncio.to_thread(candidate.read_bytes)
        key = None
    else:
        raise ValueError("Local artwork has no associated media directory")
    location, digest = await asyncio.to_thread(store_artwork, content)
    if http and key:
        await http.put(key, "artwork", {"path": location, "sha256": digest}, 30 * 86400)
    return location, digest, source


async def _prepare_artwork(
    proposal: MetadataProposal, path: Path | None, http: CachedHTTP | None = None
) -> dict[str, tuple[str, str, str]]:
    results = {}
    for role, source in proposal.artwork.items():
        try:
            results[role] = await _one_artwork(source, path, http)
        except (ProviderUnavailable, ValueError, OSError) as error:
            proposal.artwork_errors.append(f"{role}: {error}")
    proposal.prepared_artwork = results
    for child in proposal.children:
        await _prepare_artwork(child, path, http)
        proposal.artwork_errors.extend(child.artwork_errors)
    if proposal.collection:
        await _prepare_artwork(proposal.collection, path, http)
        proposal.artwork_errors.extend(proposal.collection.artwork_errors)
    return results


async def _claim(
    session_factory: Any,
) -> tuple[int, MediaItem, Library | None, Path | None, dict, list[int], str] | None:
    async with session_factory() as session:
        now = utcnow()
        stale = (
            select(MediaItem.id)
            .where(MediaItem.id == MetadataJob.item_id, MediaItem.generation != MetadataJob.generation)
            .exists()
        )
        await session.execute(
            update(MetadataJob)
            .where(MetadataJob.status == "pending", stale)
            .values(status="cancelled", error="Superseded metadata generation")
            .execution_options(synchronize_session=False)
        )
        eligible = or_(
            (MetadataJob.status == "pending") & (MetadataJob.next_attempt_at <= now),
            (MetadataJob.status == "running") & (MetadataJob.lease_until < now),
        )
        job = await session.scalar(select(MetadataJob).where(eligible).order_by(MetadataJob.next_attempt_at).limit(1))
        if job is None:
            await session.commit()
            return None
        claimed = await session.execute(
            update(MetadataJob)
            .where(MetadataJob.id == job.id, eligible)
            .values(status="running", attempts=MetadataJob.attempts + 1, lease_until=now + timedelta(minutes=5))
            .execution_options(synchronize_session=False)
        )
        if claimed.rowcount != 1:
            await session.rollback()
            return None
        item = await session.get(MediaItem, job.item_id)
        if item is None or item.generation != job.generation:
            job.status = "cancelled"
            await session.commit()
            return None
        library = await session.get(Library, item.metadata_library_id) if item.metadata_library_id else None
        file = await session.scalar(
            select(MediaFile)
            .join(MediaItemFile, MediaItemFile.media_file_id == MediaFile.id)
            .where(MediaItemFile.item_id == item.id)
            .limit(1)
        )
        path = Path(file.file_path) if file else None
        if path is None and item.kind == "series":
            raw_path = (item.provider_data or {}).get("directory")
            path = Path(raw_path) if raw_path else None
        child_files = {}
        absolute_numbers = []
        if item.kind == "series":
            rows = await session.execute(
                select(MediaItem, MediaFile.file_path)
                .join(MediaItemFile, MediaItemFile.item_id == MediaItem.id)
                .join(MediaFile, MediaFile.id == MediaItemFile.media_file_id)
                .where(MediaItem.series_id == item.id)
            )
            for child, file_path in rows:
                if child.season_number is not None and child.episode_number is not None:
                    child_files[child.season_number, child.episode_number] = Path(file_path)
                elif isinstance((child.provider_data or {}).get("absolute_number"), int):
                    absolute_numbers.append(child.provider_data["absolute_number"])
        await session.commit()
        return job.id, item, library, path, child_files, absolute_numbers, job.mode


async def process_metadata_jobs(
    limit: int = 1, session_factory: Any = async_session_maker, http: CachedHTTP | None = None
) -> int:
    """Process bounded durable jobs; safe to schedule repeatedly in the single API worker."""
    if _worker.locked():
        return 0
    completed = 0
    async with _worker:
        for _ in range(min(max(limit, 0), 10)):
            claimed = await _claim(session_factory)
            if not claimed:
                break
            job_id, item, library, path, child_files, absolute_numbers, mode = claimed
            try:
                if mode == "export":
                    await _finish_export(job_id, item, session_factory)
                    completed += 1
                    continue
                async with asyncio.timeout(120):
                    proposal = (
                        MetadataProposal(item.kind)
                        if item.locked
                        and (item.kind not in {"series", "collection"} or "order" in (item.locked_fields or []))
                        else await _fetch(
                            item, library, path, http or CachedHTTP(session_factory), child_files, absolute_numbers
                        )
                    )
                    proposal.artwork = {
                        role: source
                        for role, source in proposal.artwork.items()
                        if not item.locked and role not in (item.locked_fields or [])
                    }
                try:
                    async with asyncio.timeout(60):
                        assets = await _prepare_artwork(proposal, path, http or CachedHTTP(session_factory))
                except TimeoutError:
                    proposal.artwork_errors.append("Artwork download deadline reached; remaining images will retry")
                    assets = proposal.prepared_artwork
                await _apply_downloaded(session_factory, job_id, item, library, proposal, assets)
                if library and library.metadata_export_nfo:
                    if proposal.artwork_errors:
                        await export_metadata_nfo(item.id, session_factory)
                    else:
                        await _finish_export(job_id, item, session_factory)
                completed += int(not proposal.artwork_errors)
            except (
                ProviderUnavailable,
                IdentificationRequired,
                MetadataConflict,
                ValueError,
                OSError,
                TimeoutError,
            ) as error:
                await _record_failure(session_factory, job_id, item, error)
            except Exception as error:
                logger.exception("Unexpected metadata processing failure for job %s", job_id)
                await _record_failure(session_factory, job_id, item, error)
    return completed


async def _apply_downloaded(
    session_factory: Any,
    job_id: int,
    item: MediaItem,
    library: Library | None,
    proposal: MetadataProposal,
    assets: dict[str, tuple[str, str, str]],
) -> None:
    async with session_factory() as session:
        current = await session.get(MediaItem, item.id)
        if current is None or current.revision != item.revision or current.generation != item.generation:
            raise MetadataConflict("Item changed while metadata was downloading")
        job = await session.get(MetadataJob, job_id)
        mode = getattr(job, "mode", "unlocked")
        await _save_proposal(session, current, proposal, item.generation, item.revision, mode)
        if current.locked:
            current.metadata_status = "ready"
        if "order" not in (current.locked_fields or []) and proposal.children:
            if current.kind == "collection":
                await _save_collection(session, current, proposal, mode)
            else:
                placeholders = list(
                    await session.scalars(
                        select(MediaItem).where(
                            MediaItem.series_id == current.id,
                            MediaItem.season_number.is_(None),
                            MediaItem.kind == "episode",
                        )
                    )
                )
                await _save_children(
                    session, current, proposal, current.id, mode, placeholders, proposal.absolute_placements
                )
        if "order" not in (current.locked_fields or []) and proposal.collection:
            await _save_collection(session, current, proposal.collection, mode)
        await _save_artwork(session, current, assets, mode)
        if job:
            job.status, job.error, job.lease_until = "done", None, None
            if proposal.artwork_errors:
                job.status = "pending" if job.attempts < 5 else "failed"
                job.error = "; ".join(proposal.artwork_errors)[:500]
                job.next_attempt_at = utcnow() + timedelta(seconds=min(3600, 60 * 2 ** min(job.attempts, 6)))
                current.metadata_status = "partial"
            elif library and library.metadata_export_nfo:
                job.mode, job.status = "export", "pending"
        await session.commit()


async def _finish_export(job_id: int, snapshot: MediaItem, session_factory: Any) -> None:
    async with asyncio.timeout(60):
        await export_metadata_nfo(snapshot.id, session_factory)
    async with session_factory() as session:
        job = await session.get(MetadataJob, job_id)
        current = await session.get(MediaItem, snapshot.id)
        if job:
            job.status = "done" if current and current.generation == snapshot.generation else "cancelled"
            job.error, job.lease_until = None, None
            await session.commit()


async def export_metadata_nfo(item_id: int, session_factory: Any = async_session_maker) -> int:
    """Export configured local sidecars, including child episodes, without a database write transaction."""
    writes: list[tuple[MediaItem, Path]] = []
    images: dict[int, dict[str, str]] = {}
    async with session_factory() as session:
        item = await session.get(MediaItem, item_id)
        if item is None or not item.metadata_library_id:
            return 0
        library = await session.get(Library, item.metadata_library_id)
        if library is None or not library.metadata_export_nfo:
            return 0
        nodes = list(
            await session.scalars(
                select(MediaItem).where(
                    or_(MediaItem.id == item_id, MediaItem.series_id == item_id, MediaItem.parent_id == item_id)
                )
            )
        )
        for image in await session.scalars(select(Artwork).where(Artwork.item_id.in_([node.id for node in nodes]))):
            images.setdefault(image.item_id, {})[image.role] = str(artwork_path(image.path))
        paths = dict(
            (
                await session.execute(
                    select(MediaItemFile.item_id, MediaFile.file_path)
                    .join(MediaFile, MediaFile.id == MediaItemFile.media_file_id)
                    .where(MediaItemFile.item_id.in_([node.id for node in nodes]))
                )
            ).all()
        )
        for node in nodes:
            if node.kind in {"movie", "episode"} and node.id in paths:
                writes.append((node, Path(paths[node.id]).with_suffix(".nfo")))
            elif node.kind == "series" and (node.provider_data or {}).get("directory"):
                writes.append((node, Path(node.provider_data["directory"]) / "tvshow.nfo"))
            elif node.kind == "season":
                episode = next((child for child in nodes if child.parent_id == node.id and child.id in paths), None)
                if episode:
                    writes.append((node, Path(paths[episode.id]).parent / "season.nfo"))
    for node, path in writes:
        await asyncio.to_thread(export_nfo, node, path, images.get(node.id))
    return len(writes)


async def _record_failure(session_factory: Any, job_id: int, snapshot: MediaItem, error: Exception) -> None:
    async with session_factory() as session:
        job = await session.get(MetadataJob, job_id)
        item = await session.get(MediaItem, snapshot.id)
        if not job:
            return
        stale = isinstance(error, MetadataConflict) or item is None or item.generation != snapshot.generation
        needs_match = isinstance(error, IdentificationRequired)
        job.status = (
            "cancelled"
            if stale
            else "needs_identification"
            if needs_match
            else "pending"
            if job.attempts < 5
            else "failed"
        )
        job.error = str(error)[:500]
        job.lease_until = None
        job.next_attempt_at = utcnow() + timedelta(seconds=min(3600, 60 * 2 ** min(job.attempts, 6)))
        if item and not stale and job.mode != "export":
            item.metadata_status = "needs_identification" if needs_match else "error"
            if item.kind == "series":
                item.hierarchy_complete = False
        await session.commit()
        logger.info("Metadata job %s: %s", job_id, job.error)
