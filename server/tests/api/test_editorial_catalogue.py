"""Editorial catalogue remains useful without files and never loads full payloads on cards."""

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models import Library, MediaFile, MediaItem, MediaItemFile, MediaView, UserItemState
from app.services.item_catalogue import item_cards
from app.services.item_discovery import attach_file, discover_items, parse_name


@pytest.mark.parametrize(
    ("filename", "title", "year"),
    [
        ("The.Matrix.1999.1080p.BluRay", "The Matrix", 1999),
        ("2001.A.Space.Odyssey.1968.1080p", "2001 A Space Odyssey", 1968),
        ("1917 (2019) [tmdbid=530915]", "1917", 2019),
    ],
)
def test_discovery_does_not_confuse_title_numbers_with_year(filename, title, year):
    result, actual_year, _ = parse_name(filename)
    assert (result, actual_year) == (title, year)


async def test_discovery_preserves_file_progress_and_owner(db_session, test_user, test_library):
    nested = Library(name="Nested", path=test_library.path + "/films", library_type="movie", metadata_locale="en-US")
    db_session.add(nested)
    await db_session.flush()
    file = MediaFile(
        file_path=nested.path + "/Movie.2020.mkv",
        file_name="Movie.2020.mkv",
        file_size=100,
        file_extension="mkv",
        created_at=datetime(2025, 1, 1),
    )
    db_session.add(file)
    await db_session.flush()
    db_session.add(
        MediaView(
            user_id=test_user.id,
            media_file_id=file.id,
            position_seconds=123,
            duration_seconds=1000,
            resume_active=True,
            watched=False,
        )
    )
    await db_session.flush()
    items = await attach_file(db_session, file, [test_library, nested])
    assert items[0].metadata_library_id == nested.id
    assert items[0].metadata_locale == "en-US"
    assert items[0].first_available_at == datetime(2025, 1, 1)
    assert (await attach_file(db_session, file, [nested, test_library]))[0].id == items[0].id
    view = await db_session.scalar(select(MediaView).where(MediaView.media_file_id == file.id))
    assert view.position_seconds == 123
    assert await db_session.get(UserItemState, (test_user.id, items[0].id)) is not None
    cards = await item_cards(db_session, test_user.id, [items[0].id])
    assert cards[0].year == 2020
    assert cards[0].progress_percent == pytest.approx(12.3)


async def test_all_episodes_visible_including_missing_and_upcoming(client, db_session, test_library, auth_headers):
    series = MediaItem(
        kind="series",
        title="Show",
        metadata_library_id=test_library.id,
        metadata_status="ready",
        hierarchy_complete=True,
        order_confirmed=True,
    )
    db_session.add(series)
    await db_session.flush()
    season = MediaItem(
        kind="season",
        title="Season 1",
        metadata_library_id=test_library.id,
        parent_id=series.id,
        series_id=series.id,
        season_number=1,
        hierarchy_complete=True,
        order_confirmed=True,
    )
    db_session.add(season)
    await db_session.flush()
    episodes = [
        MediaItem(
            kind="episode",
            title=f"Episode {number}",
            metadata_library_id=test_library.id,
            parent_id=season.id,
            series_id=series.id,
            season_number=1,
            episode_number=number,
            metadata_status="ready",
            order_confirmed=True,
            release_date=date.today() + timedelta(days=10) if number == 3 else date(2020, 1, 1),
        )
        for number in range(1, 4)
    ]
    db_session.add_all(episodes)
    await db_session.flush()
    file = MediaFile(file_path=test_library.path + "/e1.mkv", file_name="e1.mkv", file_size=100, file_extension="mkv")
    db_session.add(file)
    await db_session.flush()
    db_session.add(MediaItemFile(item_id=episodes[0].id, media_file_id=file.id))
    await db_session.commit()
    response = await client.get("/api/v1/items", params={"parent_id": season.id}, headers=auth_headers)
    assert response.status_code == 200
    assert [row["availability"] for row in response.json()] == ["available", "missing", "upcoming"]
    missing = await client.get(f"/api/v1/items/{episodes[1].id}", headers=auth_headers)
    assert missing.json()["playable_file_id"] is None


async def test_cards_batch_queries_independent_of_card_count(db_session, test_user, test_library):
    items = [
        MediaItem(
            kind="movie", title=f"Movie {n}", metadata_library_id=test_library.id, overview="large overview" * 10000
        )
        for n in range(50)
    ]
    db_session.add_all(items)
    await db_session.commit()
    counts = []
    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    engine = db_session.bind.sync_engine
    event.listen(engine, "before_cursor_execute", capture)
    try:
        for size in (1, 50):
            statements.clear()
            await item_cards(db_session, test_user.id, [item.id for item in items[:size]])
            counts.append(len(statements))
            assert not any("media_item.overview" in sql for sql in statements)
        assert counts[0] == counts[1] == 4
    finally:
        event.remove(engine, "before_cursor_execute", capture)


async def test_metadata_mutations_admin_only_and_conflicts(
    client, db_session, test_library, auth_headers, admin_auth_headers
):
    item = MediaItem(kind="movie", title="Before", metadata_library_id=test_library.id)
    db_session.add(item)
    await db_session.commit()
    path = f"/api/v1/dashboard/metadata/items/{item.id}"
    payload = {"expected_revision": 0, "changes": {"overview": ""}, "locked_fields": []}
    assert (await client.patch(path, json=payload, headers=auth_headers)).status_code == 403
    response = await client.patch(path, json=payload, headers=admin_auth_headers)
    assert response.status_code == 200
    assert "overview" in response.json()["locked_fields"]
    assert (await client.patch(path, json=payload, headers=admin_auth_headers)).status_code == 409


async def test_unknown_anime_number_stays_unresolved(db_session, test_library):
    test_library.library_type = "show"
    test_library.metadata_profile = "anime"
    file = MediaFile(
        file_path=test_library.path + "/Anime/Anime - 013.mkv",
        file_name="Anime - 013.mkv",
        file_size=100,
        file_extension="mkv",
    )
    db_session.add(file)
    await db_session.flush()
    item = (await attach_file(db_session, file, [test_library]))[0]
    assert item.kind == "episode"
    assert item.season_number is None
    assert item.episode_number is None
    assert item.provider_data["absolute_number"] == 13
    assert not item.order_confirmed


async def test_nested_owner_remains_visible_through_enabled_parent(client, db_session, test_library, auth_headers):
    nested = Library(name="Nested", path=test_library.path + "/nested", library_type="show", enabled=False)
    db_session.add(nested)
    await db_session.flush()
    missing = MediaItem(kind="episode", title="Missing", metadata_library_id=nested.id)
    db_session.add(missing)
    await db_session.commit()
    response = await client.get(
        "/api/v1/items", params={"library_id": test_library.id, "kind": "episode"}, headers=auth_headers
    )
    assert [row["id"] for row in response.json()] == [missing.id]
    test_library.enabled = False
    await db_session.commit()
    assert (await client.get(f"/api/v1/items/{missing.id}", headers=auth_headers)).status_code == 404


async def test_discovery_backlog_ignores_orphans_and_zero_position_is_not_activity(db_session, test_library, test_user):
    orphan = MediaFile(file_path="/orphan/old.mkv", file_name="old.mkv", file_size=100, file_extension="mkv")
    file = MediaFile(file_path=test_library.path + "/New.mkv", file_name="New.mkv", file_size=100, file_extension="mkv")
    db_session.add_all([orphan, file])
    await db_session.flush()
    db_session.add(MediaView(user_id=test_user.id, media_file_id=file.id, position_seconds=0))
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    assert await discover_items(limit=1, session_factory=factory) == 1
    state = await db_session.scalar(select(UserItemState).where(UserItemState.user_id == test_user.id))
    assert state is not None
    assert state.last_activity_at is None
    assert await discover_items(limit=1, session_factory=factory) == 0


async def test_bounded_episode_starts_at_physical_offset_without_resume(db_session, test_library, test_user):
    episodes = [MediaItem(kind="episode", title=f"Episode {n}", metadata_library_id=test_library.id) for n in (1, 2)]
    file = MediaFile(
        file_path=test_library.path + "/double.mkv", file_name="double.mkv", file_size=100, file_extension="mkv"
    )
    db_session.add_all([*episodes, file])
    await db_session.flush()
    db_session.add_all([
        MediaItemFile(item_id=episodes[0].id, media_file_id=file.id, start_seconds=0, end_seconds=1200),
        MediaItemFile(item_id=episodes[1].id, media_file_id=file.id, start_seconds=1200, end_seconds=2400),
    ])
    await db_session.commit()
    cards = await item_cards(db_session, test_user.id, [episodes[1].id])
    assert cards[0].position_seconds == 1200
    assert cards[0].progress_percent == 0
    assert not cards[0].resume_active


async def test_ambiguous_range_does_not_starve_next_discovery_batch(db_session, test_library):
    test_library.library_type = "show"
    for name in ("Show.S01E01-E99.mkv", "Show.S01E02.mkv"):
        db_session.add(
            MediaFile(
                file_path=test_library.path + "/Show/" + name, file_name=name, file_size=100, file_extension="mkv"
            )
        )
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    assert await discover_items(limit=1, session_factory=factory) == 1
    assert await discover_items(limit=1, session_factory=factory) == 1
    assert await discover_items(limit=1, session_factory=factory) == 0
    episodes = list(
        await db_session.scalars(select(MediaItem).where(MediaItem.kind == "episode").order_by(MediaItem.id))
    )
    assert episodes[0].metadata_status == "needs_identification"
    assert episodes[0].episode_number is None
    assert episodes[1].episode_number == 2


async def test_removing_nested_library_keeps_series_visible_through_parent(
    client, db_session, test_library, auth_headers, admin_auth_headers
):
    nested = Library(name="Nested", path=test_library.path + "/nested", library_type="show")
    db_session.add(nested)
    await db_session.flush()
    file = MediaFile(
        file_path=nested.path + "/Show/Show.S01E01.mkv",
        file_name="Show.S01E01.mkv",
        file_size=100,
        file_extension="mkv",
    )
    db_session.add(file)
    await db_session.flush()
    episode = (await attach_file(db_session, file, [test_library, nested]))[0]
    series_id, season_id = episode.series_id, episode.parent_id
    missing = MediaItem(
        kind="episode",
        title="Missing E2",
        metadata_library_id=nested.id,
        parent_id=season_id,
        series_id=series_id,
        season_number=1,
        episode_number=2,
    )
    db_session.add(missing)
    await db_session.commit()
    missing_id = missing.id
    assert (
        await client.delete(f"/api/v1/dashboard/libraries/{nested.id}", headers=admin_auth_headers)
    ).status_code == 204
    for item_id in (series_id, season_id, missing_id):
        assert (await client.get(f"/api/v1/items/{item_id}", headers=auth_headers)).status_code == 200
    response = await client.get("/api/v1/items", params={"library_id": test_library.id}, headers=auth_headers)
    assert [item["id"] for item in response.json()] == [series_id]


async def test_explicit_provider_ids_override_title_similarity(db_session, test_library):
    linked = []
    for name in (
        "The Same Title (2025) [tmdb-101].mkv",
        "The Same Title (2025) [tmdb-202].mkv",
        "A Renamed Edition (2024) [tmdb-101].mkv",
    ):
        file = MediaFile(file_path=test_library.path + "/" + name, file_name=name, file_size=100, file_extension="mkv")
        db_session.add(file)
        await db_session.flush()
        linked.append((await attach_file(db_session, file, [test_library]))[0])
    assert linked[0].id != linked[1].id
    assert linked[0].id == linked[2].id
    assert linked[1].provider_ids == {"tmdb": "202"}
