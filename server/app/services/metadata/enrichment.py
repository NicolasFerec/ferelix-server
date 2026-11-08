"""Provider selection and local NFO precedence, with no catalogue writes."""

from pathlib import Path

from app.models.library import Library
from app.models.metadata import MediaItem

from .files import find_nfo, metadata_directory, read_nfo
from .http import CachedHTTP
from .providers import TMDB, AniBridge, AniDB, select_match
from .types import IdentificationRequired, MetadataProposal, ProviderUnavailable


async def _fetch(
    item: MediaItem,
    library: Library | None,
    path: Path | None,
    http: CachedHTTP,
    child_files: dict[tuple[int, int], Path] | None = None,
    absolute_numbers: list[int] | None = None,
) -> MetadataProposal:
    local = read_nfo(nfo, item.kind, item.metadata_locale) if path and (nfo := find_nfo(path, item.kind)) else None
    if local and local.internal_export:
        local = None
    pinned_identity = item.locked or "provider_ids" in (item.locked_fields or [])
    if (
        local
        and pinned_identity
        and any(
            provider in (item.provider_ids or {}) and item.provider_ids[provider] != identifier
            for provider, identifier in local.fields.get("provider_ids", {}).items()
        )
    ):
        local = None
    if local and local.locked:
        return local
    ids = {**(item.provider_ids or {}), **(local.fields.get("provider_ids", {}) if local else {})}
    if pinned_identity:
        ids = {**ids, **(item.provider_ids or {})}
    try:
        remote = await _fetch_remote(item, library, ids, http, absolute_numbers or [])
    except ProviderUnavailable:
        if local:
            return local
        raise
    if local:
        identifiers = {**remote.fields.get("provider_ids", {}), **local.fields.get("provider_ids", {})}
        identity_provenance = {**remote.provenance.get("provider_ids", {}), **local.provenance.get("provider_ids", {})}
        remote.fields.update(local.fields)
        remote.provenance.update(local.provenance)
        remote.fields["provider_ids"] = identifiers
        remote.provenance["provider_ids"] = identity_provenance
        remote.artwork.update(local.artwork)
        remote.locked_fields = local.locked_fields
    _overlay_child_nfos(remote, child_files or {}, item.metadata_locale)
    return remote


async def _fetch_remote(
    item: MediaItem, library: Library | None, ids: dict[str, str], http: CachedHTTP, absolute_numbers: list[int]
) -> MetadataProposal:
    anime_profile = library is not None and library.metadata_profile == "anime" and item.kind != "collection"
    preferred = (item.provider_data or {}).get("identification_source")
    year = item.release_date.year if item.release_date else (item.provider_data or {}).get("year")
    if not ids and anime_profile:
        candidates = await AniDB(http).search(item.title, item.kind, item.metadata_locale)
        exact = [candidate for candidate in candidates if candidate.original_title == item.title]
        if len(exact) != 1:
            raise IdentificationRequired("Select the anime; its title does not identify one entry")
        ids["anidb"] = exact[0].provider_id
    if "anidb" in ids and (preferred == "anidb" or "tmdb" not in ids):
        remote = await AniDB(http).fetch(ids["anidb"], item.kind, item.metadata_locale)
        released = remote.fields.get("release_date")
        if not item.provider_ids and year and released and year != released.year:
            raise IdentificationRequired("The anime release year conflicts with the filename")
        if absolute_numbers:
            _confirm_anidb_entry_order(remote, absolute_numbers)
        return remote
    tmdb = TMDB(http)
    imdb_lookup = ids.get("imdb") if "tmdb" not in ids else None
    if "tmdb" not in ids:
        if imdb_lookup is not None:
            ids["tmdb"] = await tmdb.find_imdb(imdb_lookup, item.kind, item.metadata_locale)
        else:
            match = select_match(await tmdb.search(item.title, item.kind, item.metadata_locale), item.title, year)
            ids["tmdb"] = match.provider_id
    remote = await tmdb.fetch(ids["tmdb"], item.kind, item.metadata_locale)
    if imdb_lookup is not None:
        identifiers = remote.fields.setdefault("provider_ids", {})
        if identifiers.get("imdb", imdb_lookup) != imdb_lookup:
            raise IdentificationRequired("The retrieved work contradicts the supplied IMDb identifier")
        identifiers["imdb"] = imdb_lookup
        remote.provenance.setdefault("provider_ids", {})["resolved_from"] = {
            "provider": "imdb",
            "id": imdb_lookup,
            "source": "tmdb/find",
            "provenance": (item.provenance or {}).get("provider_ids", {}),
        }
    if anime_profile:
        await _enrich_anime(item, ids, remote, http, absolute_numbers)
    return remote


def _confirm_anidb_entry_order(remote: MetadataProposal, absolute_numbers: list[int]) -> None:
    known = {
        child.fields["episode_number"]
        for season in remote.children
        if season.fields.get("season_number") == 1
        for child in season.children
    }
    remote.absolute_placements = {number: (1, number) for number in absolute_numbers if number in known}
    remote.order_confirmed = True
    for season in remote.children:
        season.order_confirmed = True
        for episode in season.children:
            episode.order_confirmed = True


async def _enrich_anime(
    item: MediaItem, ids: dict[str, str], remote: MetadataProposal, http: CachedHTTP, absolute_numbers: list[int]
) -> None:
    anime_ids = [ids["anidb"]] if "anidb" in ids else await AniBridge(http).anime_ids(ids["tmdb"], item.kind)
    if len(anime_ids) > 1:
        raise IdentificationRequired("Several AniDB entries match; select the anime mapping")
    if not anime_ids:
        return
    anime = await AniDB(http).fetch(anime_ids[0], item.kind, item.metadata_locale)
    for key in ("keywords", "aliases"):
        remote.fields[key] = anime.fields.get(key, remote.fields.get(key, []))
        remote.provenance[key] = anime.provenance.get(key, {})
    remote.fields["provider_ids"]["anidb"] = anime_ids[0]
    for number in absolute_numbers:
        placement = await AniBridge(http).map_absolute_episode(anime_ids[0], number, ids["tmdb"])
        if placement:
            remote.absolute_placements[number] = placement


def _overlay_child_nfos(proposal: MetadataProposal, files: dict[tuple[int, int], Path], locale: str) -> None:
    for season in proposal.children:
        if season.kind != "season":
            continue
        number = season.fields.get("season_number")
        paths = [path for (season_number, _), path in files.items() if season_number == number]
        if paths and (nfo := paths[0].parent / "season.nfo").is_file():
            _overlay_local(season, read_nfo(nfo, "season", locale), nfo.parent)
        for episode in season.children:
            path = files.get((int(number), int(episode.fields["episode_number"]))) if number is not None else None
            if path and (nfo := find_nfo(path, "episode")):
                _overlay_local(episode, read_nfo(nfo, "episode", locale), nfo.parent)


def _overlay_local(target: MetadataProposal, local: MetadataProposal, directory: Path) -> None:
    if local.internal_export:
        return
    for provider, identifier in local.fields.get("provider_ids", {}).items():
        current = target.fields.get("provider_ids", {}).get(provider)
        if current and current != identifier:
            raise IdentificationRequired("Local episode NFO identity conflicts with the series numbering")
    target.fields.update(local.fields)
    target.provenance.update(local.provenance)
    target.locked_fields = local.locked_fields
    target.locked = local.locked
    for role, source in local.artwork.items():
        if not source.startswith(("https://", "http://")):
            candidate = (directory / source).resolve()
            if not candidate.is_relative_to(directory.resolve()) and not candidate.is_relative_to(
                (metadata_directory() / "artwork").resolve()
            ):
                raise ValueError("NFO artwork must be in the media directory")
            source = str(candidate)
        target.artwork[role] = source
