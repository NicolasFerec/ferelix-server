"""Logical ordering precedes availability, and polling does not extend next-up activity."""

import asyncio
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal

import pytest
from sqlalchemy import event, select

from app.models import Library, MediaFile, MediaView, Settings
from app.models.metadata import MediaItem, MediaItemFile, UserItemState
from app.services.continuation import next_up_choices, resolve_continuation, resume_choices


@pytest.fixture
async def series(db_session, tmp_path):
    library = Library(name="Series", path=str(tmp_path), enabled=True)
    db_session.add(library)
    await db_session.flush()
    root = MediaItem(
        kind="series", title="Series", metadata_library_id=library.id, hierarchy_complete=True, order_confirmed=True
    )
    db_session.add(root)
    await db_session.flush()
    season = MediaItem(
        kind="season",
        title="S1",
        metadata_library_id=library.id,
        parent_id=root.id,
        series_id=root.id,
        season_number=1,
        hierarchy_complete=True,
        order_confirmed=True,
    )
    db_session.add(season)
    await db_session.flush()
    episodes = [
        MediaItem(
            kind="episode",
            title=f"E{number}",
            metadata_library_id=library.id,
            parent_id=season.id,
            series_id=root.id,
            season_number=1,
            episode_number=number,
            release_date=date(2000, 1, 1),
        )
        for number in range(1, 4)
    ]
    db_session.add_all(episodes)
    await db_session.flush()
    files = []
    for episode in episodes:
        path = tmp_path / f"{episode.title}.mkv"
        path.touch()
        file = MediaFile(file_path=str(path), file_name=path.name, file_extension=".mkv", file_size=0, duration=100)
        db_session.add(file)
        await db_session.flush()
        db_session.add(MediaItemFile(item_id=episode.id, media_file_id=file.id))
        files.append(file)
    await db_session.commit()
    return root, season, episodes, files


async def test_first_unseen_and_immediate_successor_are_distinct(db_session, test_user, series):
    root, _season, episodes, files = series
    db_session.add_all([
        UserItemState(user_id=test_user.id, item_id=episode.id, watched=True) for episode in episodes[:2]
    ])
    await db_session.commit()
    homepage = await resolve_continuation(db_session, test_user.id, root.id)
    autoplay = await resolve_continuation(db_session, test_user.id, episodes[0].id, "next")
    assert (homepage.status, homepage.item_id, homepage.media_file_id) == ("ready", episodes[2].id, files[2].id)
    assert (autoplay.status, autoplay.item_id, autoplay.position_seconds) == ("ready", episodes[1].id, 0)


@pytest.mark.parametrize("unavailable,expected", [("missing", "missing"), ("upcoming", "upcoming")])
async def test_unavailable_successor_never_skips_to_later_file(db_session, test_user, series, unavailable, expected):
    root, _season, episodes, files = series
    db_session.add(
        UserItemState(user_id=test_user.id, item_id=episodes[0].id, watched=True, last_activity_at=datetime.now())
    )
    if unavailable == "missing":
        files[1].deleted_at = datetime.now()
    else:
        episodes[1].release_date = date.today() + timedelta(days=30)
    await db_session.commit()
    requests: list[tuple[int, Literal["next", "continue"]]] = [(root.id, "continue"), (episodes[0].id, "next")]
    for item_id, mode in requests:
        choice = await resolve_continuation(db_session, test_user.id, item_id, mode)
        assert (choice.status, choice.item_id, choice.media_file_id) == (expected, episodes[1].id, None)
    assert await next_up_choices(db_session, test_user.id) == []


@pytest.mark.parametrize(
    "damage", ["series_incomplete", "season_incomplete", "unknown_order", "duplicate", "missing_number", "wrong_parent"]
)
async def test_unsafe_hierarchy_has_no_inferred_order(db_session, test_user, series, damage):
    root, season, episodes, _files = series
    if damage == "series_incomplete":
        root.hierarchy_complete = False
    elif damage == "season_incomplete":
        season.hierarchy_complete = False
    elif damage == "unknown_order":
        root.order_confirmed = False
    elif damage == "duplicate":
        episodes[1].episode_number = 1
    elif damage == "missing_number":
        episodes[1].episode_number = None
    else:
        episodes[1].parent_id = root.id
    await db_session.commit()
    choice = await resolve_continuation(db_session, test_user.id, episodes[0].id, "next")
    assert choice.status == "unknown_order"
    assert choice.media_file_id is None


async def test_next_up_expiry_uses_selected_candidate_not_later_newly_available_item(db_session, test_user, series):
    _root, _season, episodes, _files = series
    now = datetime(2026, 11, 7, 12)
    activity = now - timedelta(days=100)
    db_session.add(UserItemState(user_id=test_user.id, item_id=episodes[0].id, watched=True, last_activity_at=activity))
    episodes[2].first_available_at = now - timedelta(days=1)
    await db_session.commit()
    assert await next_up_choices(db_session, test_user.id, now=now) == []
    episodes[1].first_available_at = now - timedelta(days=1)
    await db_session.commit()
    assert [choice.item_id for choice in await next_up_choices(db_session, test_user.id, now=now)] == [episodes[1].id]
    assert [choice.item_id for choice in await next_up_choices(db_session, test_user.id, now=now)] == [episodes[1].id]
    state = await db_session.get(UserItemState, (test_user.id, episodes[0].id), populate_existing=True)
    assert state.last_activity_at == activity
    db_session.add(Settings(id=1, next_up_retention_days=0))
    episodes[1].first_available_at = None
    await db_session.commit()
    assert [choice.item_id for choice in await next_up_choices(db_session, test_user.id, now=now)] == [episodes[1].id]


async def test_autoplay_start_rechecks_source_availability_at_the_last_moment(client, db_session, auth_headers, series):
    _root, _season, episodes, files = series
    payload = {"item_id": episodes[1].id, "media_file_id": files[1].id, "continuation_from_item_id": episodes[0].id}
    await asyncio.to_thread(Path(files[1].file_path).unlink)
    response = await client.post("/api/v1/playback-sessions", headers=auth_headers, json=payload)
    assert response.status_code == 409
    payload.update(item_id=episodes[2].id, media_file_id=files[2].id)
    response = await client.post("/api/v1/playback-sessions", headers=auth_headers, json=payload)
    assert response.status_code == 409


async def test_collection_uses_release_date_and_refuses_ambiguous_dates(db_session, test_user, series):
    root, _season, episodes, _files = series
    collection = MediaItem(
        kind="collection",
        title="Collection",
        metadata_library_id=root.metadata_library_id,
        hierarchy_complete=True,
        order_confirmed=True,
    )
    db_session.add(collection)
    await db_session.flush()
    for index, episode in enumerate(episodes):
        episode.kind = "movie"
        episode.collection_id = collection.id
        episode.release_date = date(2000 + (2 - index), 1, 1)
    await db_session.commit()
    choice = await resolve_continuation(db_session, test_user.id, collection.id)
    assert choice.item_id == episodes[2].id
    episodes[1].release_date = episodes[2].release_date
    await db_session.commit()
    assert (await resolve_continuation(db_session, test_user.id, collection.id)).status == "unknown_order"


async def test_bulk_preview_guards_descendants_and_states_then_applies_atomically(
    client, db_session, auth_headers, test_user, series
):
    root, season, episodes, _files = series
    user_id, library_id, root_id, season_id = test_user.id, root.metadata_library_id, root.id, season.id
    episode_ids = [episode.id for episode in episodes]
    endpoint = f"/api/v1/items/{root.id}/watch-state/bulk"
    preview = await client.post(endpoint, headers=auth_headers, json={"watched": True})
    assert preview.status_code == 200
    assert preview.json()["count"] == 3
    assert list(await db_session.scalars(select(UserItemState))) == []
    await client.put(f"/api/v1/items/{episodes[0].id}/watch-state", headers=auth_headers, json={"watched": True})
    stale = await client.post(
        endpoint,
        headers=auth_headers,
        json={"watched": True, "preview": False, "revision_token": preview.json()["revision_token"]},
    )
    assert stale.status_code == 409
    assert await db_session.get(UserItemState, (user_id, episode_ids[1])) is None
    preview = (await client.post(endpoint, headers=auth_headers, json={"watched": True})).json()
    applied = await client.post(
        endpoint,
        headers=auth_headers,
        json={"watched": True, "preview": False, "revision_token": preview["revision_token"]},
    )
    assert applied.status_code == 200
    states = list(await db_session.scalars(select(UserItemState).where(UserItemState.user_id == user_id)))
    assert len(states) == 3 and all(state.watched for state in states)
    before = {state.item_id: state.state_revision for state in states}
    preview = (await client.post(endpoint, headers=auth_headers, json={"watched": True})).json()
    await client.post(
        endpoint,
        headers=auth_headers,
        json={"watched": True, "preview": False, "revision_token": preview["revision_token"]},
    )
    assert {state.item_id: state.state_revision for state in await db_session.scalars(select(UserItemState))} == before
    new = MediaItem(
        kind="episode",
        title="E4",
        metadata_library_id=library_id,
        parent_id=season_id,
        series_id=root_id,
        season_number=1,
        episode_number=4,
    )
    db_session.add(new)
    await db_session.commit()
    stale = await client.post(
        endpoint,
        headers=auth_headers,
        json={"watched": True, "preview": False, "revision_token": preview["revision_token"]},
    )
    assert stale.status_code == 409


async def test_bulk_query_count_does_not_grow_per_episode(client, db_session, auth_headers, series):
    root, season, _episodes, _files = series
    db_session.add_all([
        MediaItem(
            kind="episode",
            title=f"E{number}",
            metadata_library_id=root.metadata_library_id,
            parent_id=season.id,
            series_id=root.id,
            season_number=1,
            episode_number=number,
        )
        for number in range(4, 104)
    ])
    await db_session.commit()
    endpoint = f"/api/v1/items/{root.id}/watch-state/bulk"
    preview = (await client.post(endpoint, headers=auth_headers, json={"watched": True})).json()
    statements = []
    engine = db_session.bind.sync_engine

    def capture(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        response = await client.post(
            endpoint,
            headers=auth_headers,
            json={"watched": True, "preview": False, "revision_token": preview["revision_token"]},
        )
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert response.status_code == 200, response.text
    assert response.json()["count"] == 103
    assert len(statements) <= 12, statements


async def test_seen_rewatch_resume_suppresses_the_whole_series_from_next_up(db_session, test_user, series):
    _root, _season, episodes, files = series
    db_session.add(
        UserItemState(user_id=test_user.id, item_id=episodes[0].id, watched=True, last_activity_at=datetime.now())
    )
    view = MediaView(
        user_id=test_user.id,
        media_file_id=files[0].id,
        watched=True,
        resume_active=True,
        position_seconds=20,
        duration_seconds=100,
    )
    db_session.add(view)
    await db_session.commit()
    assert [choice.item_id for choice in await resume_choices(db_session, test_user.id)] == [episodes[0].id]
    assert await next_up_choices(db_session, test_user.id) == []


async def test_threshold_setting_does_not_rewrite_persisted_resume_during_a_read(db_session, test_user, series):
    _root, _season, episodes, files = series
    db_session.add_all([
        Settings(id=1, watched_threshold_percent=50),
        MediaView(
            user_id=test_user.id,
            media_file_id=files[0].id,
            resume_active=True,
            position_seconds=80,
            duration_seconds=100,
        ),
    ])
    await db_session.commit()
    assert [choice.item_id for choice in await resume_choices(db_session, test_user.id)] == [episodes[0].id]


async def test_physical_end_of_shared_episode_file_cannot_replay_its_second_episode(
    client, db_session, auth_headers, test_user, series
):
    _root, _season, episodes, files = series
    second_link = await db_session.get(MediaItemFile, (episodes[1].id, files[1].id))
    await db_session.delete(second_link)
    first_link = await db_session.get(MediaItemFile, (episodes[0].id, files[0].id))
    first_link.start_seconds, first_link.end_seconds = 0, 50
    db_session.add(MediaItemFile(item_id=episodes[1].id, media_file_id=files[0].id, start_seconds=50, end_seconds=100))
    await db_session.commit()
    assert (await resolve_continuation(db_session, test_user.id, episodes[0].id, "next")).status == "unknown_order"
    response = await client.post(
        "/api/v1/playback-sessions",
        headers=auth_headers,
        json={"item_id": episodes[1].id, "media_file_id": files[0].id, "continuation_from_item_id": episodes[0].id},
    )
    assert response.status_code == 409


async def test_bulk_preview_cannot_be_reused_by_another_user(
    client, db_session, auth_headers, admin_auth_headers, admin_user, series
):
    root, _season, episodes, _files = series
    root_id, second_id, admin_id = root.id, episodes[1].id, admin_user.id
    endpoint = f"/api/v1/items/{root_id}/watch-state/bulk"
    preview = (await client.post(endpoint, headers=auth_headers, json={"watched": True})).json()
    response = await client.post(
        endpoint,
        headers=admin_auth_headers,
        json={"watched": True, "preview": False, "revision_token": preview["revision_token"]},
    )
    assert response.status_code == 409
    assert await db_session.get(UserItemState, (admin_id, second_id)) is None


@pytest.mark.parametrize("missing", ["episode", "season"])
async def test_complete_flag_cannot_hide_a_numeric_gap(db_session, test_user, series, missing):
    root, _season, episodes, _files = series
    if missing == "episode":
        # The metadata catalogue itself contains E1,E3: even the provider's
        # complete flag cannot authorize skipping the unrepresented E2.
        await db_session.delete(episodes[1])
    else:
        season_three = MediaItem(
            kind="season",
            title="S3",
            metadata_library_id=root.metadata_library_id,
            parent_id=root.id,
            series_id=root.id,
            season_number=3,
            hierarchy_complete=True,
            order_confirmed=True,
        )
        db_session.add(season_three)
        await db_session.flush()
        db_session.add(
            MediaItem(
                kind="episode",
                title="S3E1",
                metadata_library_id=root.metadata_library_id,
                parent_id=season_three.id,
                series_id=root.id,
                season_number=3,
                episode_number=1,
            )
        )
    await db_session.commit()
    choice = await resolve_continuation(db_session, test_user.id, episodes[0].id, "next")
    assert choice.status == "unknown_order"
    assert choice.item_id is None
