"""Catalogue query counts and pagination behavior with realistic user progress."""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Library, MediaFile, MediaView, RecommendationRow, User
from app.routers.v1.media import get_continue_watching_media_files, get_homepage_rows


async def seed_media(session: AsyncSession, count: int) -> list[MediaFile]:
    files = [
        MediaFile(
            file_path=f"/test/media/path/{index}.mp4",
            file_name=f"Film {index}",
            file_extension=".mp4",
            file_size=1000,
            duration=1000,
        )
        for index in range(count)
    ]
    session.add_all(files)
    await session.commit()
    return files


async def test_homepage_batches_rows_and_current_user_progress(
    db_session: AsyncSession,
    test_library: Library,
    test_user: User,
    admin_user: User,
) -> None:
    files = await seed_media(db_session, 30)
    db_session.add_all([
        RecommendationRow(
            library_id=test_library.id,
            name=f"Row {index}",
            visible_on_homepage=True,
            filter_criteria={"order_by": "duration", "order": "DESC", "limit": 3, "offset": index},
        )
        for index in range(10)
    ])
    db_session.add_all([
        MediaView(user_id=test_user.id, media_file_id=files[0].id, position_seconds=100),
        MediaView(user_id=admin_user.id, media_file_id=files[1].id, position_seconds=200),
    ])
    await db_session.commit()
    statements: list[str] = []
    engine = db_session.bind
    assert engine is not None

    def record(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", record)
    try:
        rows = await get_homepage_rows(test_user, db_session)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record)
    assert len(statements) == 2
    assert len(rows) == 10
    assert [card.id for card in rows[0].items] == [file.id for file in files[:3]]
    assert rows[0].items[0].user_view is not None
    assert rows[0].items[0].user_view.position_seconds == 100
    assert rows[0].items[1].user_view is None
    assert not any("audio_track" in sql or "subtitle_track" in sql or "video_track" in sql for sql in statements)
    assert "file_path" not in rows[0].items[0].model_dump()
    assert "scan_error" not in rows[0].items[0].model_dump()


async def test_recommendation_rows_have_default_and_maximum_limits(
    db_session: AsyncSession,
    test_library: Library,
    test_user: User,
) -> None:
    await seed_media(db_session, 140)
    db_session.add_all([
        RecommendationRow(library_id=test_library.id, name="default", visible_on_homepage=True, filter_criteria={}),
        RecommendationRow(
            library_id=test_library.id, name="maximum", visible_on_homepage=True, filter_criteria={"limit": 10000}
        ),
    ])
    await db_session.commit()
    rows = await get_homepage_rows(test_user, db_session)
    assert [len(row.items) for row in rows] == [24, 100]


async def test_continue_watching_filters_completion_before_limit(
    db_session: AsyncSession,
    test_user: User,
) -> None:
    files = await seed_media(db_session, 10)
    now = datetime.now(UTC).replace(tzinfo=None)
    db_session.add_all([
        MediaView(
            user_id=test_user.id,
            media_file_id=file.id,
            position_seconds=950 if index < 9 else 100,
            last_viewed_at=now - timedelta(minutes=index),
        )
        for index, file in enumerate(files)
    ])
    await db_session.commit()
    cards = await get_continue_watching_media_files(test_user, db_session, limit=1)
    assert [card.id for card in cards] == [files[-1].id]


async def test_keyset_page_survives_deletion_before_cursor(
    client: AsyncClient,
    db_session: AsyncSession,
    test_user: User,
    auth_headers: dict[str, str],
) -> None:
    files = await seed_media(db_session, 5)
    response = await client.get("/api/v1/media-files?limit=2", headers=auth_headers)
    assert response.status_code == 200
    first = response.json()
    assert [item["id"] for item in first] == [file.id for file in files[:2]]
    await db_session.delete(files[0])
    await db_session.commit()
    response = await client.get(f"/api/v1/media-files?limit=2&after_id={first[-1]['id']}", headers=auth_headers)
    assert [item["id"] for item in response.json()] == [file.id for file in files[2:4]]


@pytest.mark.parametrize("params", ["limit=0", "limit=101", "skip=-1", "after_id=-1", "skip=1&after_id=2"])
async def test_catalogue_rejects_unbounded_or_ambiguous_pages(
    client: AsyncClient,
    test_user: User,
    auth_headers: dict[str, str],
    params: str,
) -> None:
    assert (await client.get(f"/api/v1/media-files?{params}", headers=auth_headers)).status_code == 422
