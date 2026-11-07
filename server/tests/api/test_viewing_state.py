"""Manual state, rewatch resume and last-intent playback must remain independent."""

from datetime import date

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.sql.dml import Update

from app.models import Library, MediaFile, MediaView, PlaybackSession, Settings
from app.models.metadata import MediaItem, MediaItemFile, UserItemState
from app.services.viewing import is_media_watched


@pytest.fixture
async def watched_movie(db_session, tmp_path):
    library = Library(name="Movies", path=str(tmp_path), enabled=True)
    db_session.add(library)
    await db_session.flush()
    item = MediaItem(kind="movie", title="Movie", metadata_library_id=library.id, release_date=date(2000, 1, 1))
    source = tmp_path / "movie.mkv"
    source.touch()
    file = MediaFile(file_path=str(source), file_name=source.name, file_extension=".mkv", file_size=0, duration=100)
    db_session.add_all([item, file])
    await db_session.flush()
    db_session.add(MediaItemFile(item_id=item.id, media_file_id=file.id))
    await db_session.commit()
    return item, file


async def start(client, headers, item, file):
    response = await client.post(
        "/api/v1/playback-sessions",
        headers=headers,
        json={"media_file_id": file.id, "item_id": item.id, "duration_seconds": 100},
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize(
    "position,duration,threshold,expected",
    [
        (89.999, 100, 90, False),
        (90, 100, 90, True),
        (90, 100, 95, False),
        (95, 100, 95, True),
        (60, 120, 90, False),
        (100, None, 90, False),
        (1, 0, 90, False),
        (float("inf"), 100, 90, False),
        (100, float("inf"), 90, False),
        (-1, 100, 90, False),
    ],
)
def test_threshold_has_no_last_minute_exception(position, duration, threshold, expected):
    assert is_media_watched(position, duration, threshold) is expected


@pytest.mark.parametrize("watched", [False, True])
async def test_manual_state_survives_old_heartbeat_and_close(
    client, db_session, auth_headers, test_user, watched_movie, watched
):
    item, file = watched_movie
    playback = await start(client, auth_headers, item, file)
    assert (
        await client.post(
            f"/api/v1/playback-sessions/{playback['id']}/heartbeat",
            headers=auth_headers,
            json={"position_seconds": 20, "duration_seconds": 100},
        )
    ).status_code == 200
    changed = await client.put(
        f"/api/v1/items/{item.id}/watch-state",
        headers=auth_headers,
        json={"watched": watched, "expected_revision": playback["state_revision"]},
    )
    assert changed.status_code == 200, changed.text
    revision = changed.json()["state_revision"]
    assert revision > playback["state_revision"]
    assert (
        await client.post(
            f"/api/v1/playback-sessions/{playback['id']}/heartbeat",
            headers=auth_headers,
            json={"position_seconds": 95, "duration_seconds": 100},
        )
    ).status_code == 200
    assert (await client.delete(f"/api/v1/playback-sessions/{playback['id']}", headers=auth_headers)).status_code == 204
    view = await db_session.scalar(
        select(MediaView).where(MediaView.user_id == test_user.id, MediaView.media_file_id == file.id)
    )
    state = await db_session.get(UserItemState, (test_user.id, item.id), populate_existing=True)
    assert view.position_seconds == (20 if watched else 0)
    assert view.resume_active is False
    assert state.watched is watched
    assert state.state_revision == revision
    repeated = await client.put(
        f"/api/v1/items/{item.id}/watch-state",
        headers=auth_headers,
        json={"watched": watched, "expected_revision": revision},
    )
    assert repeated.json()["state_revision"] == revision


async def test_seen_movie_can_be_resumed_during_rewatch_without_losing_seen_history(
    client, db_session, auth_headers, test_user, watched_movie
):
    item, file = watched_movie
    assert (
        await client.put(f"/api/v1/items/{item.id}/watch-state", headers=auth_headers, json={"watched": True})
    ).status_code == 200
    playback = await start(client, auth_headers, item, file)
    response = await client.post(
        f"/api/v1/playback-sessions/{playback['id']}/heartbeat",
        headers=auth_headers,
        json={"position_seconds": 20, "duration_seconds": 100},
    )
    assert response.status_code == 200
    state = await db_session.get(UserItemState, (test_user.id, item.id), populate_existing=True)
    assert state.watched
    rows = (await client.get("/api/v1/items/resume", headers=auth_headers)).json()
    assert [row["id"] for row in rows] == [item.id]
    assert rows[0]["watched"] is True
    assert rows[0]["position_seconds"] == 20
    await client.post(
        f"/api/v1/playback-sessions/{playback['id']}/heartbeat",
        headers=auth_headers,
        json={"position_seconds": 90, "duration_seconds": 100},
    )
    assert (await client.get("/api/v1/items/resume", headers=auth_headers)).json() == []


async def test_new_edition_session_supersedes_old_session_without_copying_resume_seconds(
    client, db_session, auth_headers, test_user, watched_movie, tmp_path
):
    item, file = watched_movie
    source = tmp_path / "edition.mkv"
    source.touch()
    second = MediaFile(file_path=str(source), file_name=source.name, file_size=0, file_extension=".mkv", duration=120)
    db_session.add(second)
    await db_session.flush()
    db_session.add(MediaItemFile(item_id=item.id, media_file_id=second.id))
    await db_session.commit()
    old = await start(client, auth_headers, item, file)
    latest = await start(client, auth_headers, item, second)
    assert latest["state_revision"] > old["state_revision"]
    await client.post(
        f"/api/v1/playback-sessions/{old['id']}/heartbeat",
        headers=auth_headers,
        json={"position_seconds": 95, "duration_seconds": 100},
    )
    await client.post(
        f"/api/v1/playback-sessions/{latest['id']}/heartbeat",
        headers=auth_headers,
        json={"position_seconds": 30, "duration_seconds": 120},
    )
    old_view = await db_session.scalar(
        select(MediaView).where(MediaView.media_file_id == file.id, MediaView.user_id == test_user.id)
    )
    assert old_view.position_seconds == 0
    rows = (await client.get("/api/v1/items/resume", headers=auth_headers)).json()
    assert rows[0]["playable_file_id"] == second.id
    assert rows[0]["position_seconds"] == 30


@pytest.mark.parametrize("ending", [False, True])
async def test_sql_guard_rechecks_revision_after_progress_was_loaded(
    client, db_session, auth_headers, test_user, watched_movie, monkeypatch, ending
):
    item, file = watched_movie
    playback = await start(client, auth_headers, item, file)
    stored = await db_session.get(PlaybackSession, playback["id"])
    stored.position_seconds = 95
    await db_session.commit()
    original = db_session.scalar
    intercepted = False

    async def race(statement, *args, **kwargs):
        nonlocal intercepted
        if (
            not intercepted
            and isinstance(statement, Update)
            and getattr(statement.table, "name", None) == "user_item_state"
        ):
            intercepted = True
            await db_session.execute(
                update(UserItemState)
                .where(UserItemState.user_id == test_user.id, UserItemState.item_id == item.id)
                .values(state_revision=UserItemState.state_revision + 1, watched=False)
            )
        return await original(statement, *args, **kwargs)

    monkeypatch.setattr(db_session, "scalar", race)
    if ending:
        response = await client.delete(f"/api/v1/playback-sessions/{playback['id']}", headers=auth_headers)
        assert response.status_code == 204
    else:
        response = await client.post(
            f"/api/v1/playback-sessions/{playback['id']}/heartbeat",
            headers=auth_headers,
            json={"position_seconds": 95, "duration_seconds": 100},
        )
        assert response.status_code == 200
    assert intercepted
    view = await original(
        select(MediaView).where(MediaView.user_id == test_user.id, MediaView.media_file_id == file.id)
    )
    assert view.position_seconds == 0
    state = await db_session.get(UserItemState, (test_user.id, item.id), populate_existing=True)
    assert state.watched is False
    assert state.last_activity_at is None


async def test_current_setting_is_used_on_next_heartbeat(client, db_session, auth_headers, test_user, watched_movie):
    item, file = watched_movie
    playback = await start(client, auth_headers, item, file)
    db_session.add(Settings(id=1, watched_threshold_percent=95))
    await db_session.commit()
    await client.post(
        f"/api/v1/playback-sessions/{playback['id']}/heartbeat",
        headers=auth_headers,
        json={"position_seconds": 90, "duration_seconds": 100},
    )
    assert not (await db_session.get(UserItemState, (test_user.id, item.id), populate_existing=True)).watched


@pytest.mark.parametrize("bounded", [False, True])
async def test_multi_episode_file_requires_real_bounds_even_with_explicit_item(
    client, db_session, auth_headers, test_user, watched_movie, bounded
):
    item, file = watched_movie
    second = MediaItem(kind="episode", title="E2", metadata_library_id=item.metadata_library_id)
    db_session.add(second)
    await db_session.flush()
    db_session.add(
        MediaItemFile(
            item_id=second.id,
            media_file_id=file.id,
            start_seconds=50 if bounded else None,
            end_seconds=100 if bounded else None,
        )
    )
    first_link = await db_session.get(MediaItemFile, (item.id, file.id))
    first_link.start_seconds = 0 if bounded else None
    first_link.end_seconds = 50 if bounded else None
    await db_session.commit()
    playback = await start(client, auth_headers, item, file)
    await client.post(
        f"/api/v1/playback-sessions/{playback['id']}/heartbeat",
        headers=auth_headers,
        json={"position_seconds": 45 if bounded else 95, "duration_seconds": 100},
    )
    assert (await db_session.get(UserItemState, (test_user.id, item.id), populate_existing=True)).watched is bounded
    assert await db_session.get(UserItemState, (test_user.id, second.id)) is None


@pytest.mark.parametrize("newer_intent", [False, True])
async def test_session_can_adopt_metadata_discovered_during_playback_only_at_same_revision(
    client, db_session, auth_headers, test_user, watched_movie, newer_intent
):
    item, file = watched_movie
    await db_session.execute(delete(MediaItemFile).where(MediaItemFile.item_id == item.id))
    await db_session.commit()
    response = await client.post(
        "/api/v1/playback-sessions", headers=auth_headers, json={"media_file_id": file.id, "duration_seconds": 100}
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["item_id"] is None
    db_session.add(MediaItemFile(item_id=item.id, media_file_id=file.id))
    db_session.add(
        UserItemState(
            user_id=test_user.id, item_id=item.id, state_revision=payload["state_revision"] + int(newer_intent)
        )
    )
    await db_session.commit()
    response = await client.post(
        f"/api/v1/playback-sessions/{payload['id']}/heartbeat",
        headers=auth_headers,
        json={"position_seconds": 95, "duration_seconds": 100},
    )
    assert response.status_code == 200
    state = await db_session.get(UserItemState, (test_user.id, item.id), populate_existing=True)
    view = await db_session.scalar(
        select(MediaView).where(MediaView.user_id == test_user.id, MediaView.media_file_id == file.id)
    )
    assert state.watched is not newer_intent
    assert view.position_seconds == (0 if newer_intent else 95)
    assert response.json()["session"]["item_id"] == (None if newer_intent else item.id)


async def test_paused_heartbeats_and_session_creation_do_not_invent_business_activity(
    client, db_session, auth_headers, test_user, watched_movie, monkeypatch
):
    from datetime import datetime, timedelta

    item, file = watched_movie
    payload = await start(client, auth_headers, item, file)
    state = await db_session.get(UserItemState, (test_user.id, item.id))
    assert state.last_activity_at is None
    await client.post(
        f"/api/v1/playback-sessions/{payload['id']}/heartbeat",
        headers=auth_headers,
        json={"position_seconds": 20, "duration_seconds": 100},
    )
    await db_session.refresh(state)
    activity = state.last_activity_at
    monkeypatch.setattr("app.services.viewing.utcnow", lambda: datetime.now() + timedelta(days=120))
    await client.post(
        f"/api/v1/playback-sessions/{payload['id']}/heartbeat",
        headers=auth_headers,
        json={"position_seconds": 20, "duration_seconds": 100, "is_paused": True},
    )
    await db_session.refresh(state)
    assert state.last_activity_at == activity
