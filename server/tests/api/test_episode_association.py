"""Manual identification preserves file positions and revokes stale progress writes."""

from datetime import datetime

import pytest
from sqlalchemy import select

from app.models import MediaFile, MediaItem, MediaItemFile, MediaView, PlaybackSession, UserItemState
from app.services.viewing import record_playback_progress


@pytest.fixture
async def association(db_session, test_library, test_user):
    series = MediaItem(kind="series", title="Anime", metadata_library_id=test_library.id)
    db_session.add(series)
    await db_session.flush()
    season = MediaItem(
        kind="season",
        title="Season 1",
        metadata_library_id=test_library.id,
        parent_id=series.id,
        series_id=series.id,
        season_number=1,
    )
    db_session.add(season)
    await db_session.flush()
    source = MediaItem(
        kind="episode",
        title="Anime - 013",
        metadata_library_id=test_library.id,
        parent_id=series.id,
        series_id=series.id,
    )
    target = MediaItem(
        kind="episode",
        title="Episode 13",
        metadata_library_id=test_library.id,
        parent_id=season.id,
        series_id=series.id,
        season_number=1,
        episode_number=13,
        order_confirmed=True,
    )
    file = MediaFile(file_path=test_library.path + "/13.mkv", file_name="13.mkv", file_size=100, file_extension="mkv")
    db_session.add_all([source, target, file])
    await db_session.flush()
    db_session.add(MediaItemFile(item_id=source.id, media_file_id=file.id))
    db_session.add(
        UserItemState(
            user_id=test_user.id,
            item_id=source.id,
            state_revision=4,
            watched=True,
            last_activity_at=datetime(2025, 1, 1),
        )
    )
    db_session.add(
        UserItemState(
            user_id=test_user.id,
            item_id=target.id,
            state_revision=7,
            watched=False,
            last_activity_at=datetime(2026, 1, 1),
        )
    )
    view = MediaView(
        user_id=test_user.id,
        media_file_id=file.id,
        state_revision=4,
        position_seconds=420,
        duration_seconds=1000,
        resume_active=True,
        play_count=2,
    )
    playback = PlaybackSession(
        user_id=test_user.id,
        media_file_id=file.id,
        item_id=source.id,
        state_revision=4,
        position_seconds=950,
        duration_seconds=1000,
    )
    db_session.add_all([view, playback])
    await db_session.commit()
    return source, target, file, view, playback


async def test_association_preserves_position_and_latest_manual_state(
    client, db_session, association, test_user, admin_auth_headers
):
    source, target, file, view, playback = association
    source_id = source.id
    response = await client.post(
        f"/api/v1/dashboard/metadata/items/{source_id}/associate",
        headers=admin_auth_headers,
        json={"expected_revision": 0, "target_item_id": target.id, "target_expected_revision": 0},
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"item_id": target.id}
    assert await db_session.get(MediaItem, source_id) is None
    assert await db_session.get(MediaItemFile, (target.id, file.id)) is not None
    state = await db_session.get(UserItemState, (test_user.id, target.id), populate_existing=True)
    assert not state.watched  # More recent explicit unseen intent takes precedence.
    assert state.state_revision == 8
    assert not await record_playback_progress(db_session, playback)
    await db_session.refresh(view)
    assert (view.position_seconds, view.play_count, view.resume_active) == (420, 2, True)


async def test_association_requires_admin_and_both_current_revisions(
    client, db_session, association, auth_headers, admin_auth_headers
):
    source, target, file, _view, _playback = association
    file_id = file.id
    path = f"/api/v1/dashboard/metadata/items/{source.id}/associate"
    body = {"expected_revision": 0, "target_item_id": target.id, "target_expected_revision": 99}
    assert (await client.post(path, headers=auth_headers, json=body)).status_code == 403
    assert (await client.post(path, headers=admin_auth_headers, json=body)).status_code == 409
    await db_session.refresh(source)
    assert source.revision == 0  # The first CAS must roll back when the second fails.
    assert (
        await db_session.scalar(select(MediaItemFile.item_id).where(MediaItemFile.media_file_id == file_id))
        == source.id
    )


async def test_association_refuses_shared_file(client, db_session, association, admin_auth_headers):
    source, target, file, _view, _playback = association
    db_session.add(MediaItemFile(item_id=target.id, media_file_id=file.id))
    await db_session.commit()
    response = await client.post(
        f"/api/v1/dashboard/metadata/items/{source.id}/associate",
        headers=admin_auth_headers,
        json={"expected_revision": 0, "target_item_id": target.id, "target_expected_revision": 0},
    )
    assert response.status_code == 409


async def test_unidentified_episode_numbers_require_association(client, association, admin_auth_headers):
    source, _target, _file, _view, _playback = association
    response = await client.patch(
        f"/api/v1/dashboard/metadata/items/{source.id}",
        headers=admin_auth_headers,
        json={"expected_revision": 0, "changes": {"season_number": 1, "episode_number": 13}},
    )
    assert response.status_code == 422
