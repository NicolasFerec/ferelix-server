"""Regression checks for editorial locks, provider ambiguity, and durable metadata jobs."""

import gzip
import io
from datetime import date, timedelta
from unittest.mock import AsyncMock

import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.media_file import MediaFile
from app.models.metadata import Artwork, MediaItem, MediaItemFile, MetadataJob, UserItemState
from app.services.metadata import (
    apply_metadata_patch,
    engine,
    enqueue_metadata,
    enrichment,
    process_metadata_jobs,
    providers,
    queue_nfo_export,
    restore_metadata_fields,
)
from app.services.metadata import http as metadata_http
from app.services.metadata.files import export_nfo, parse_xml, read_nfo, store_artwork
from app.services.metadata.http import CachedHTTP, utcnow, validate_url
from app.services.metadata.merge import merge_proposal
from app.services.metadata.providers import TMDB, AniBridge, select_match, tmdb_proposal
from app.services.metadata.types import (
    IdentificationRequired,
    MatchCandidate,
    MetadataConflict,
    MetadataProposal,
    ProviderUnavailable,
)


async def make_item(session, kind="movie", **values):
    item = MediaItem(kind=kind, title="Original", metadata_locale="fr-FR", **values)
    session.add(item)
    await session.commit()
    return item


@pytest.mark.asyncio
async def test_manual_empty_value_survives_automatic_refresh(db_session):
    item = await make_item(db_session)
    await apply_metadata_patch(db_session, item.id, 0, {"overview": ""})
    await db_session.commit()
    values = merge_proposal(item, MetadataProposal("movie", {"overview": "Remote summary", "title": "New title"}))
    assert "overview" not in values
    assert values["title"] == "New title"
    assert item.locked_fields == ["overview"]


@pytest.mark.asyncio
async def test_stale_admin_revision_is_rejected(db_session):
    item = await make_item(db_session)
    await apply_metadata_patch(db_session, item.id, 0, {"title": "Admin"})
    with pytest.raises(MetadataConflict):
        await apply_metadata_patch(db_session, item.id, 0, {"title": "Obsolete"})


@pytest.mark.asyncio
async def test_missing_mode_preserves_existing_and_fills_missing(db_session):
    item = await make_item(db_session)
    proposal = MetadataProposal("movie", {"title": "Remote", "overview": "New summary"})
    values = merge_proposal(item, proposal, "missing")
    assert "title" not in values
    assert values["overview"] == "New summary"


@pytest.mark.asyncio
async def test_global_lock_blocks_all_automatic_fields(db_session):
    item = await make_item(db_session, locked=True)
    assert merge_proposal(item, MetadataProposal("movie", {"title": "Remote"})) == {}


@pytest.mark.asyncio
async def test_unlock_reenables_automatic_changes(db_session):
    item = await make_item(db_session)
    await apply_metadata_patch(db_session, item.id, 0, {"title": "Manual"})
    await apply_metadata_patch(db_session, item.id, 1, {}, locks=[])
    assert merge_proposal(item, MetadataProposal("movie", {"title": "Provider"}))["title"] == "Provider"


@pytest.mark.asyncio
async def test_enqueue_deduplicates_and_force_invalidates_old_generation(db_session):
    item = await make_item(db_session)
    first = await enqueue_metadata(db_session, item)
    assert (await enqueue_metadata(db_session, item)).id == first.id
    second = await enqueue_metadata(db_session, item, force=True)
    assert second.id != first.id
    assert second.generation == first.generation + 1


@pytest.mark.asyncio
async def test_network_result_cannot_overwrite_concurrent_manual_edit(db_session, monkeypatch):
    item = await make_item(db_session)
    await enqueue_metadata(db_session, item)
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)

    async def fetch(*args):
        async with factory() as admin:
            await apply_metadata_patch(admin, item.id, 0, {"title": "Edited during network"})
            await admin.commit()
        return MetadataProposal("movie", {"title": "Old provider result"})

    monkeypatch.setattr(engine, "_fetch", fetch)
    assert await process_metadata_jobs(session_factory=factory) == 0
    await db_session.refresh(item)
    assert item.title == "Edited during network"
    job = await db_session.scalar(select(MetadataJob))
    assert job.status == "cancelled"


@pytest.mark.asyncio
async def test_complete_hierarchy_created_without_media_files(db_session, monkeypatch):
    item = await make_item(db_session, kind="series")
    await enqueue_metadata(db_session, item)
    await db_session.commit()
    episode = MetadataProposal(
        "episode",
        {"title": "Episode", "episode_number": 1, "season_number": 1, "provider_ids": {"tmdb": "103"}},
        order_confirmed=True,
    )
    season = MetadataProposal(
        "season",
        {"title": "Season", "season_number": 1, "provider_ids": {"tmdb": "102"}},
        children=[episode],
        hierarchy_complete=True,
        order_confirmed=True,
    )
    proposal = MetadataProposal(
        "series",
        {"title": "Show", "provider_ids": {"tmdb": "101"}},
        children=[season],
        hierarchy_complete=True,
        order_confirmed=True,
    )
    monkeypatch.setattr(engine, "_fetch", AsyncMock(return_value=proposal))
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    assert await process_metadata_jobs(session_factory=factory) == 1
    items = list(await db_session.scalars(select(MediaItem).order_by(MediaItem.id)))
    assert [row.kind for row in items] == ["series", "season", "episode"]
    assert items[2].series_id == item.id
    assert items[2].order_confirmed
    await db_session.refresh(item)
    assert item.hierarchy_complete


@pytest.mark.asyncio
async def test_provider_snapshot_can_restore_locked_field(db_session):
    item = await make_item(
        db_session,
        provider_data={
            "last_proposal": {
                "fields": {"overview": "Provider synopsis"},
                "provenance": {"overview": {"source": "tmdb"}},
            }
        },
    )
    await apply_metadata_patch(db_session, item.id, 0, {"overview": "Local"})
    await restore_metadata_fields(db_session, item.id, 1, ["overview"])
    assert item.overview == "Provider synopsis"
    assert "overview" not in item.locked_fields
    assert item.provenance["overview"]["source"] == "tmdb"


@pytest.mark.asyncio
async def test_cache_survives_new_client_instance(db_session):
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    await CachedHTTP(factory).put("test", "tmdb", {"id": 9}, 600)
    assert await CachedHTTP(factory).cached("test") == {"id": 9}


@pytest.mark.asyncio
async def test_expired_lease_is_recovered(db_session, monkeypatch):
    item = await make_item(db_session)
    job = await enqueue_metadata(db_session, item)
    job.status = "running"
    job.lease_until = utcnow() - timedelta(seconds=1)
    await db_session.commit()
    monkeypatch.setattr(engine, "_fetch", AsyncMock(return_value=MetadataProposal("movie", {"title": "Recovered"})))
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    assert await process_metadata_jobs(session_factory=factory) == 1
    await db_session.refresh(job)
    assert job.status == "done"


def test_identification_requires_unique_exact_title_and_year():
    first = MatchCandidate("tmdb", "1", "movie", "Dune", year=1984)
    second = MatchCandidate("tmdb", "2", "movie", "Dune", year=2021)
    assert select_match([first, second], "Dune", 2021) == second
    with pytest.raises(IdentificationRequired):
        select_match([first, second], "Dune", None)
    with pytest.raises(IdentificationRequired):
        select_match([second, second], "Dune", 2021)


def test_translation_fallback_records_actual_language():
    proposal = tmdb_proposal(
        {
            "id": 1,
            "title": "Fallback",
            "overview": "",
            "translations": {
                "translations": [
                    {
                        "iso_639_1": "en",
                        "iso_3166_1": "US",
                        "data": {"title": "English", "overview": "English overview"},
                    }
                ]
            },
        },
        "movie",
        "fr-FR",
    )
    assert proposal.fields["overview"] == "English overview"
    assert proposal.provenance["overview"]["locale"] == "en-US"


@pytest.mark.parametrize("source,target", [("1-12", "1-6|2"), ("1-12", "1-6,8-13"), ("1-12", "1-6")])
def test_complex_anime_mapping_is_not_guessed(source, target):
    with pytest.raises(IdentificationRequired):
        AniBridge.map_episode({source: target}, 3)


def test_explicit_anime_mapping_and_unknown_episode():
    assert AniBridge.map_episode({"1-12": "13-24"}, 2) == 14
    assert AniBridge.map_episode({"1-12": "13-24"}, 25) is None
    assert AniBridge.map_episode({"14-": "13-"}, 14) == 13
    assert AniBridge.map_episode({"14-": "13-"}, 120) == 119
    assert AniBridge.map_episode({"1-": "1-"}, 123) == 123
    assert AniBridge.map_episode({"5": "6"}, 5) == 6
    assert AniBridge.map_episode({"5": "6"}, 6) is None
    assert AniBridge.map_episode({"1-12": None, "14-": "13-"}, 3) is None


def test_nfo_roundtrip_preserves_manual_empty_and_lock(tmp_path):
    item = MediaItem(
        kind="movie",
        title="Example",
        overview="",
        release_date=date(2020, 1, 2),
        locked_fields=["overview"],
        locked=False,
        provider_ids={"tmdb": "123"},
    )
    path = tmp_path / "movie.nfo"
    export_nfo(item, path)
    proposal = read_nfo(path, "movie", "fr-FR")
    assert proposal.fields["overview"] == ""
    assert proposal.locked_fields == ["overview"]
    assert proposal.fields["provider_ids"] == {"tmdb": "123"}
    assert proposal.fields["release_date"] == date(2020, 1, 2)
    assert proposal.internal_export
    path.write_text(path.read_text().replace("Example", "Changed by administrator"))
    assert not read_nfo(path, "movie", "fr-FR").internal_export


def test_nfo_does_not_expand_external_entities():
    with pytest.raises(ValueError):
        parse_xml('<!DOCTYPE movie [<!ENTITY secret SYSTEM "file:///etc/passwd">]><movie>&secret;</movie>')


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "https://api.themoviedb.org.evil.example/",
        "https://user:password@api.themoviedb.org/",
        "file:///etc/passwd",
    ],
)
def test_metadata_network_rejects_untrusted_hosts(url):
    with pytest.raises(ValueError):
        validate_url(url)


def test_invalid_artwork_is_not_saved(tmp_path, monkeypatch):
    monkeypatch.setenv("FERELIX_METADATA_DIR", str(tmp_path))
    with pytest.raises(OSError):
        store_artwork(b"not an image")
    assert not list(tmp_path.iterdir())


@pytest.mark.asyncio
async def test_incomplete_remote_season_fails_instead_of_claiming_complete():
    tmdb = TMDB(AsyncMock(), "token")
    tmdb.get = AsyncMock(
        side_effect=[{"id": 1, "name": "Series", "seasons": [{"season_number": 1}]}, {"id": 2, "name": "Season"}]
    )
    with pytest.raises(Exception, match="complete episode catalogue"):
        await tmdb.fetch("1", "series", "fr-FR")


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["movie", "series"])
@pytest.mark.parametrize("source", ["filename", "nfo"])
async def test_explicit_imdb_identifies_correct_work_despite_conflicting_title(
    db_session, tmp_path, monkeypatch, kind, source
):
    identifier = "tt0133093"
    provenance = {"source": "filename", "path": "Completely unrelated title [imdb-tt0133093].mkv"}
    item = await make_item(
        db_session,
        kind=kind,
        provider_ids={"imdb": identifier} if source == "filename" else {},
        provenance={"provider_ids": provenance} if source == "filename" else {},
    )
    path = tmp_path / "Completely unrelated title.mkv" if kind == "movie" else tmp_path
    nfo = path.with_suffix(".nfo") if kind == "movie" else tmp_path / "tvshow.nfo"
    if source == "nfo":
        nfo.write_text(f'<movie><uniqueid type="imdb">{identifier}</uniqueid></movie>')
    result_key = "movie_results" if kind == "movie" else "tv_results"
    request = AsyncMock(
        side_effect=[
            {result_key: [{"id": 123}]},
            {"id": 123, "title" if kind == "movie" else "name": "Correct work", "seasons": []},
        ]
    )
    monkeypatch.setattr(TMDB, "get", request)
    search = AsyncMock(side_effect=AssertionError("Explicit IMDb identity must never fall back to a title search"))
    monkeypatch.setattr(TMDB, "search", search)
    result = await enrichment._fetch(item, None, path, CachedHTTP())
    search.assert_not_awaited()
    assert request.await_args_list[0].args == (f"find/{identifier}",)
    assert request.await_args_list[0].kwargs == {"external_source": "imdb_id", "language": "fr-FR"}
    assert request.await_args_list[1].args == ("movie/123" if kind == "movie" else "tv/123",)
    assert result.fields["provider_ids"] == {"tmdb": "123", "imdb": identifier}
    assert result.fields["title"] == "Correct work"
    assert result.provenance["provider_ids"]["resolved_from"]["id"] == identifier
    if source == "filename":
        assert result.provenance["provider_ids"]["resolved_from"]["provenance"] == provenance
    else:
        assert result.provenance["provider_ids"]["source"] == "nfo"
        assert result.provenance["provider_ids"]["path"] == str(nfo)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "results",
    [
        {"movie_results": []},
        {"movie_results": [{"id": 123}, {"id": 456}]},
        {"movie_results": [], "tv_results": [{"id": 123}]},
        {"movie_results": [{"id": 0}]},
    ],
)
async def test_unresolved_imdb_requires_identification_without_title_fallback(db_session, monkeypatch, results):
    item = await make_item(db_session, provider_ids={"imdb": "tt0133093"})
    await enqueue_metadata(db_session, item)
    await db_session.commit()
    monkeypatch.setattr(TMDB, "get", AsyncMock(return_value=results))
    search = AsyncMock(side_effect=AssertionError("No title fallback is allowed"))
    fetch = AsyncMock(side_effect=AssertionError("Unresolved identity must not download another work"))
    monkeypatch.setattr(TMDB, "search", search)
    monkeypatch.setattr(TMDB, "fetch", fetch)
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    assert await process_metadata_jobs(session_factory=factory) == 0
    search.assert_not_awaited()
    fetch.assert_not_awaited()
    await db_session.refresh(item)
    assert item.metadata_status == "needs_identification" and item.title == "Original"
    assert item.provider_ids == {"imdb": "tt0133093"}


@pytest.mark.asyncio
@pytest.mark.parametrize("identifier", ["", "../movie/123", "nm0000001"])
async def test_invalid_explicit_imdb_never_falls_back_to_title(db_session, monkeypatch, identifier):
    item = await make_item(db_session, provider_ids={"imdb": identifier})
    request = AsyncMock(side_effect=AssertionError("Invalid identifiers must not make a provider request"))
    monkeypatch.setattr(TMDB, "get", request)
    with pytest.raises(IdentificationRequired):
        await enrichment._fetch_remote(item, None, dict(item.provider_ids), CachedHTTP(), [])
    request.assert_not_awaited()


@pytest.mark.asyncio
async def test_imdb_resolution_rejects_conflicting_detail_identity(db_session, monkeypatch):
    item = await make_item(db_session, provider_ids={"imdb": "tt0133093"})
    monkeypatch.setattr(
        TMDB,
        "get",
        AsyncMock(
            side_effect=[
                {"movie_results": [{"id": 123}]},
                {"id": 123, "title": "Wrong identity", "external_ids": {"imdb_id": "tt9999999"}},
            ]
        ),
    )
    with pytest.raises(IdentificationRequired, match="contradicts"):
        await enrichment._fetch_remote(item, None, dict(item.provider_ids), CachedHTTP(), [])


@pytest.mark.asyncio
async def test_collection_import_keeps_existing_movie_and_creates_missing_parts(db_session, monkeypatch):
    item = await make_item(db_session, provider_ids={"tmdb": "10"})
    await enqueue_metadata(db_session, item)
    await db_session.commit()
    collection = MetadataProposal(
        "collection",
        {"title": "Saga", "provider_ids": {"tmdb": "50"}},
        children=[
            MetadataProposal(
                "movie", {"title": "Short", "provider_ids": {"tmdb": "10"}, "release_date": date(2020, 1, 1)}
            ),
            MetadataProposal(
                "movie", {"title": "Sequel", "provider_ids": {"tmdb": "11"}, "release_date": date(2021, 1, 1)}
            ),
        ],
        hierarchy_complete=True,
        order_confirmed=True,
    )
    proposal = MetadataProposal(
        "movie", {"title": "Detailed original", "provider_ids": {"tmdb": "10"}}, collection=collection
    )
    monkeypatch.setattr(engine, "_fetch", AsyncMock(return_value=proposal))
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    assert await process_metadata_jobs(session_factory=factory) == 1
    await db_session.refresh(item)
    movies = list(await db_session.scalars(select(MediaItem).where(MediaItem.kind == "movie")))
    assert len(movies) == 2
    assert item.title == "Detailed original"
    saga = await db_session.get(MediaItem, item.collection_id)
    assert saga.hierarchy_complete and saga.order_confirmed
    assert all(movie.collection_id == saga.id for movie in movies)


@pytest.mark.asyncio
async def test_absolute_placeholder_preserves_identity_and_file_link(db_session, monkeypatch):
    root = await make_item(db_session, kind="series")
    local = await make_item(
        db_session, kind="episode", parent_id=root.id, series_id=root.id, provider_data={"absolute_number": 2}
    )
    file = MediaFile(file_path="/test/Anime - 002.mkv", file_name="Anime - 002.mkv", file_size=1, file_extension=".mkv")
    db_session.add(file)
    await db_session.flush()
    db_session.add(MediaItemFile(item_id=local.id, media_file_id=file.id))
    await enqueue_metadata(db_session, root)
    await db_session.commit()
    episode = MetadataProposal(
        "episode",
        {"title": "Episode two", "season_number": 3, "episode_number": 2, "provider_ids": {"tmdb": "55"}},
        order_confirmed=True,
    )
    season = MetadataProposal("season", {"title": "Season three", "season_number": 3}, children=[episode])
    proposal = MetadataProposal("series", {"title": "Anime"}, children=[season], absolute_placements={2: (3, 2)})
    monkeypatch.setattr(engine, "_fetch", AsyncMock(return_value=proposal))
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    assert await process_metadata_jobs(session_factory=factory) == 1
    await db_session.refresh(local)
    assert local.season_number == 3 and local.episode_number == 2
    assert local.title == "Episode two" and local.order_confirmed
    assert await db_session.get(MediaItemFile, (local.id, file.id)) is not None
    assert len(list(await db_session.scalars(select(MediaItem).where(MediaItem.kind == "episode")))) == 1


@pytest.mark.asyncio
async def test_anidb_ban_survives_new_client_without_second_request(db_session, monkeypatch):
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    calls = []

    def request(*args):
        calls.append(args)
        return b'<error code="500">banned</error>'

    monkeypatch.setattr(metadata_http, "download", request)
    monkeypatch.setattr(metadata_http, "_next_anidb_request", 0)
    with pytest.raises(ProviderUnavailable):
        await CachedHTTP(factory).anidb("http://api.anidb.net:9001/httpapi?aid=1", "1")
    with pytest.raises(ProviderUnavailable):
        await CachedHTTP(factory).anidb("http://api.anidb.net:9001/httpapi?aid=2", "2")
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_anidb_title_index_downloaded_once_then_searched_locally(db_session, monkeypatch):
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    payload = gzip.compress(
        b'<animetitles><anime aid="1"><title xml:lang="en" type="official">My Anime</title></anime></animetitles>'
    )
    calls = []

    def request(*args):
        calls.append(args)
        return payload

    monkeypatch.setattr(providers, "download", request)
    client = providers.AniDB(CachedHTTP(factory))
    assert (await client.search("My Anime", "series", "fr-FR"))[0].provider_id == "1"
    assert (await client.search("Anime", "series", "fr-FR"))[0].title == "My Anime"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_manual_identification_overrides_conflicting_locked_nfo(db_session, tmp_path, monkeypatch):
    item = await make_item(db_session, provider_ids={"tmdb": "2"}, locked_fields=["provider_ids"])
    path = tmp_path / "movie.mkv"
    path.with_suffix(".nfo").write_text(
        "<movie><title>Wrong film</title><tmdbid>1</tmdbid><lockdata>true</lockdata></movie>"
    )
    fetch = AsyncMock(return_value=MetadataProposal("movie", {"title": "Correct film", "provider_ids": {"tmdb": "2"}}))
    monkeypatch.setattr(TMDB, "fetch", fetch)
    result = await engine._fetch(item, None, path, AsyncMock())
    assert result.fields["title"] == "Correct film"
    assert fetch.call_args.args[0] == "2"


@pytest.mark.asyncio
async def test_child_artwork_is_downloaded_and_saved_locally(db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("FERELIX_METADATA_DIR", str(tmp_path))
    image = io.BytesIO()
    Image.new("RGB", (4, 4), color="blue").save(image, format="PNG")
    monkeypatch.setattr(engine, "download", lambda *args: image.getvalue())
    root = await make_item(db_session, kind="series")
    await enqueue_metadata(db_session, root)
    await db_session.commit()
    episode = MetadataProposal(
        "episode",
        {"title": "Episode", "season_number": 1, "episode_number": 1},
        artwork={"backdrop": "https://image.tmdb.org/t/p/w780/still.jpg"},
    )
    proposal = MetadataProposal(
        "series",
        {"title": "Series"},
        children=[MetadataProposal("season", {"title": "Season", "season_number": 1}, children=[episode])],
    )
    monkeypatch.setattr(engine, "_fetch", AsyncMock(return_value=proposal))
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    assert await process_metadata_jobs(session_factory=factory) == 1
    art = await db_session.scalar(select(Artwork))
    assert art.role == "backdrop" and (tmp_path / art.path).is_file()


def test_descendant_nfo_overrides_remote_fields(tmp_path):
    path = tmp_path / "S01E01.mkv"
    path.with_suffix(".nfo").write_text(
        "<episodedetails><title>Local episode</title><lockedfields>Name</lockedfields></episodedetails>"
    )
    episode = MetadataProposal("episode", {"title": "Remote", "episode_number": 1, "season_number": 1})
    root = MetadataProposal("series", children=[MetadataProposal("season", {"season_number": 1}, children=[episode])])
    enrichment._overlay_child_nfos(root, {(1, 1): path}, "fr-FR")
    assert episode.fields["title"] == "Local episode"
    assert episode.locked_fields == ["title"]


@pytest.mark.asyncio
async def test_edited_fields_are_locked_even_if_lock_list_is_empty(db_session):
    item = await make_item(db_session)
    await apply_metadata_patch(db_session, item.id, 0, {"title": "Manual"}, locks=[])
    assert item.locked_fields == ["title"]


@pytest.mark.asyncio
async def test_item_language_cannot_override_library_configuration(db_session):
    item = await make_item(db_session)
    with pytest.raises(ValueError, match="library"):
        await apply_metadata_patch(db_session, item.id, 0, {"metadata_locale": "en-US"})


@pytest.mark.asyncio
async def test_artwork_failure_keeps_metadata_and_schedules_image_retry(db_session, monkeypatch):
    item = await make_item(db_session)
    await enqueue_metadata(db_session, item)
    await db_session.commit()
    proposal = MetadataProposal(
        "movie", {"title": "Retrieved metadata"}, artwork={"poster": "https://image.tmdb.org/t/p/w780/missing.jpg"}
    )
    monkeypatch.setattr(engine, "_fetch", AsyncMock(return_value=proposal))

    def unavailable(*args):
        raise ProviderUnavailable("Provider HTTP 503")

    monkeypatch.setattr(engine, "download", unavailable)
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    assert await process_metadata_jobs(session_factory=factory) == 0
    await db_session.refresh(item)
    assert item.title == "Retrieved metadata" and item.metadata_status == "partial"
    job = await db_session.scalar(select(MetadataJob))
    assert job.status == "pending" and job.next_attempt_at > utcnow()
    assert "503" in job.error


@pytest.mark.asyncio
async def test_repeated_artwork_refresh_uses_local_cache(db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("FERELIX_METADATA_DIR", str(tmp_path))
    image = io.BytesIO()
    Image.new("RGB", (4, 4), color="blue").save(image, format="PNG")
    calls = []

    def request(*args):
        calls.append(args)
        return image.getvalue()

    monkeypatch.setattr(engine, "download", request)
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    for _ in range(2):
        proposal = MetadataProposal("movie", artwork={"poster": "https://image.tmdb.org/t/p/w780/test.jpg"})
        await engine._prepare_artwork(proposal, None, CachedHTTP(factory))
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_global_lock_does_not_contact_providers(db_session, monkeypatch):
    item = await make_item(db_session, locked=True)
    await enqueue_metadata(db_session, item)
    await db_session.commit()
    fetch = AsyncMock(side_effect=AssertionError("Locked item should not fetch metadata"))
    monkeypatch.setattr(engine, "_fetch", fetch)
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    assert await process_metadata_jobs(session_factory=factory) == 1
    fetch.assert_not_awaited()
    await db_session.refresh(item)
    assert item.title == "Original" and item.metadata_status == "ready"


@pytest.mark.asyncio
async def test_nfo_exports_series_season_and_episode(db_session, test_library, tmp_path):
    test_library.metadata_export_nfo = True
    root = await make_item(
        db_session, kind="series", metadata_library_id=test_library.id, provider_data={"directory": str(tmp_path)}
    )
    season = await make_item(
        db_session,
        kind="season",
        metadata_library_id=test_library.id,
        parent_id=root.id,
        series_id=root.id,
        season_number=1,
    )
    episode = await make_item(
        db_session,
        kind="episode",
        metadata_library_id=test_library.id,
        parent_id=season.id,
        series_id=root.id,
        season_number=1,
        episode_number=1,
    )
    folder = tmp_path / "Season 01"
    folder.mkdir()
    path = folder / "Show S01E01.mkv"
    file = MediaFile(file_path=str(path), file_name=path.name, file_size=1, file_extension=".mkv")
    db_session.add(file)
    await db_session.flush()
    db_session.add(MediaItemFile(item_id=episode.id, media_file_id=file.id))
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    assert await engine.export_metadata_nfo(root.id, factory) == 3
    assert (tmp_path / "tvshow.nfo").is_file()
    assert (folder / "season.nfo").is_file()
    assert path.with_suffix(".nfo").is_file()
    (folder / "season.nfo").unlink()
    assert await engine.export_metadata_nfo(season.id, factory) == 2
    assert (folder / "season.nfo").is_file()


@pytest.mark.asyncio
async def test_generated_nfo_does_not_freeze_automatic_metadata(db_session, tmp_path, monkeypatch):
    item = await make_item(db_session, provider_ids={"tmdb": "123"})
    path = tmp_path / "Movie.mkv"
    export_nfo(item, path.with_suffix(".nfo"))
    remote = MetadataProposal("movie", {"title": "Updated provider title", "provider_ids": {"tmdb": "123"}})
    monkeypatch.setattr(enrichment, "_fetch_remote", AsyncMock(return_value=remote))
    proposal = await enrichment._fetch(item, None, path, CachedHTTP())
    assert proposal.fields["title"] == "Updated provider title"


@pytest.mark.asyncio
async def test_global_series_lock_preserves_title_but_discovers_new_seasons(db_session, monkeypatch):
    item = await make_item(db_session, kind="series", locked=True)
    await enqueue_metadata(db_session, item)
    await db_session.commit()
    proposal = MetadataProposal(
        "series",
        {"title": "Provider title"},
        hierarchy_complete=True,
        order_confirmed=True,
        children=[MetadataProposal("season", {"title": "Season 2", "season_number": 2})],
        artwork={"poster": "https://image.tmdb.org/t/p/w780/ignored.jpg"},
    )
    monkeypatch.setattr(engine, "_fetch", AsyncMock(return_value=proposal))
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    assert await process_metadata_jobs(session_factory=factory) == 1
    await db_session.refresh(item)
    assert item.title == "Original" and item.locked and item.hierarchy_complete
    season = await db_session.scalar(select(MediaItem).where(MediaItem.parent_id == item.id))
    assert season and season.season_number == 2
    assert await db_session.scalar(select(Artwork)) is None


@pytest.mark.asyncio
async def test_admin_edit_queues_durable_nfo_export_without_provider_fetch(
    db_session, test_library, tmp_path, monkeypatch
):
    test_library.metadata_export_nfo = True
    item = await make_item(db_session, metadata_library_id=test_library.id)
    path = tmp_path / "Movie.mkv"
    file = MediaFile(file_path=str(path), file_name=path.name, file_size=1, file_extension=".mkv")
    db_session.add(file)
    await db_session.flush()
    db_session.add(MediaItemFile(item_id=item.id, media_file_id=file.id))
    db_session.add(Artwork(item_id=item.id, role="poster", path="artwork/test.webp", sha256="test", source="manual"))
    item = await apply_metadata_patch(db_session, item.id, item.revision, {"title": "Admin title"})
    revision = item.revision
    job = await queue_nfo_export(db_session, item)
    assert job and job.mode == "export"
    await db_session.commit()
    fetch = AsyncMock(side_effect=AssertionError("NFO exports must not contact providers"))
    monkeypatch.setattr(engine, "_fetch", fetch)
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    assert await process_metadata_jobs(session_factory=factory) == 1
    fetch.assert_not_awaited()
    await db_session.refresh(item)
    await db_session.refresh(job)
    exported = read_nfo(path.with_suffix(".nfo"), "movie", "fr-FR")
    assert exported.fields["title"] == "Admin title" and exported.internal_export
    assert exported.artwork["poster"].endswith("/artwork/test.webp")
    assert item.revision == revision and job.status == "done"


@pytest.mark.asyncio
async def test_failed_export_retries_without_damaging_editorial_metadata(db_session, test_library, monkeypatch):
    test_library.metadata_export_nfo = True
    item = await make_item(db_session, metadata_library_id=test_library.id, metadata_status="ready")
    job = await queue_nfo_export(db_session, item)
    assert job
    await db_session.commit()
    monkeypatch.setattr(engine, "export_metadata_nfo", AsyncMock(side_effect=OSError("read-only media directory")))
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    assert await process_metadata_jobs(session_factory=factory) == 0
    await db_session.refresh(item)
    await db_session.refresh(job)
    assert job.status == "pending" and job.mode == "export"
    assert job.error is not None and "read-only" in job.error
    assert item.metadata_status == "ready" and item.revision == 0


@pytest.mark.asyncio
async def test_explicit_order_lock_prevents_inventory_changes(db_session, monkeypatch):
    item = await make_item(db_session, kind="series", locked_fields=["order"])
    await enqueue_metadata(db_session, item)
    await db_session.commit()
    proposal = MetadataProposal(
        "series",
        {"title": "New title"},
        children=[MetadataProposal("season", {"title": "Season 2", "season_number": 2})],
    )
    monkeypatch.setattr(engine, "_fetch", AsyncMock(return_value=proposal))
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    assert await process_metadata_jobs(session_factory=factory) == 1
    await db_session.refresh(item)
    assert item.title == "New title"
    assert await db_session.scalar(select(MediaItem).where(MediaItem.parent_id == item.id)) is None


@pytest.mark.asyncio
async def test_absolute_mapping_does_not_replace_target_with_user_history(db_session, test_user, monkeypatch):
    root = await make_item(db_session, kind="series")
    season = await make_item(db_session, kind="season", parent_id=root.id, series_id=root.id, season_number=1)
    target = await make_item(
        db_session,
        kind="episode",
        parent_id=season.id,
        series_id=root.id,
        season_number=1,
        episode_number=1,
        provider_ids={"tmdb": "55"},
    )
    source = await make_item(
        db_session, kind="episode", parent_id=root.id, series_id=root.id, provider_data={"absolute_number": 1}
    )
    db_session.add(UserItemState(user_id=test_user.id, item_id=target.id, watched=True))
    await enqueue_metadata(db_session, root)
    await db_session.commit()
    episode = MetadataProposal(
        "episode",
        {"title": "Episode", "season_number": 1, "episode_number": 1, "provider_ids": {"tmdb": "55"}},
        order_confirmed=True,
    )
    proposal = MetadataProposal(
        "series",
        {"title": "Anime"},
        children=[MetadataProposal("season", {"season_number": 1}, children=[episode])],
        absolute_placements={1: (1, 1)},
    )
    monkeypatch.setattr(engine, "_fetch", AsyncMock(return_value=proposal))
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    assert await process_metadata_jobs(session_factory=factory) == 1
    await db_session.refresh(source)
    assert source.parent_id == root.id and source.season_number is None
    state = await db_session.get(UserItemState, (test_user.id, target.id))
    assert state.watched


@pytest.mark.asyncio
async def test_force_refresh_never_rewinds_generation_from_stale_orm_object(db_session):
    item = await make_item(db_session)
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    async with factory() as admin:
        await apply_metadata_patch(admin, item.id, 0, {"title": "First edit"})
        await admin.commit()
        await apply_metadata_patch(admin, item.id, 1, {"title": "Second edit"})
        await admin.commit()
    assert item.generation == 0
    job = await enqueue_metadata(db_session, item, force=True)
    assert job.generation == 3
    assert item.revision == 3 and item.title == "Second edit"


@pytest.mark.asyncio
async def test_stale_queue_entries_do_not_delay_the_current_job(db_session, monkeypatch):
    item = await make_item(db_session)
    old = await enqueue_metadata(db_session, item)
    current = await enqueue_metadata(db_session, item, force=True)
    await db_session.commit()
    monkeypatch.setattr(engine, "_fetch", AsyncMock(return_value=MetadataProposal("movie", {"title": "Current"})))
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    assert await process_metadata_jobs(limit=1, session_factory=factory) == 1
    await db_session.refresh(old)
    await db_session.refresh(current)
    assert old.status == "cancelled" and current.status == "done"
