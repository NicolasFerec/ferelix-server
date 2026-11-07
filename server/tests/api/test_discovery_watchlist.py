"""Whole-catalogue discovery and isolated, idempotent saved-film operations."""

import asyncio
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import get_session
from app.models import Base, Library, MediaFile, MediaView, User, WatchlistEntry
from app.routers.v1.media import router
from app.services.auth import create_access_token


async def add_media(session: AsyncSession, path: str, *, deleted: bool = False) -> MediaFile:
    media = MediaFile(
        file_path=path,
        file_name=path.rsplit("/", 1)[-1],
        file_size=1,
        file_extension=".mkv",
        deleted_at=datetime.now(UTC).replace(tzinfo=None) if deleted else None,
    )
    session.add(media)
    await session.flush()
    return media


async def test_search_finds_title_outside_first_page_and_preserves_user_progress(
    client,
    db_session,
    test_library,
    test_user,
    auth_headers,
):
    for index in range(60):
        await add_media(db_session, f"{test_library.path}/ordinary-{index:03}.mkv")
    target = await add_media(db_session, f"{test_library.path}/Needle.mkv")
    db_session.add(MediaView(user_id=test_user.id, media_file_id=target.id, position_seconds=120))
    await db_session.commit()
    first = await client.get(f"/api/v1/libraries/{test_library.id}/items?limit=49", headers=auth_headers)
    assert target.id not in [item["id"] for item in first.json()]
    found = await client.get("/api/v1/media-files/search", params={"q": " nEeDlE "}, headers=auth_headers)
    assert found.status_code == 200
    assert [item["id"] for item in found.json()] == [target.id]
    assert found.json()[0]["user_view"]["position_seconds"] == 120
    assert "audio_tracks" not in found.json()[0]


@pytest.mark.parametrize("literal", ["%", "_", "/", "%_", "'"])
async def test_search_treats_sql_wildcards_as_text(client, db_session, test_library, auth_headers, literal):
    target = await add_media(db_session, f"{test_library.path}/literal.mkv")
    target.file_name = f"100{literal}complete.mkv"
    await add_media(db_session, f"{test_library.path}/100Xcomplete.mkv")
    await db_session.commit()
    response = await client.get("/api/v1/media-files/search", params={"q": literal}, headers=auth_headers)
    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [target.id]


async def test_search_and_watchlist_hide_disabled_deleted_and_sibling_paths(
    client,
    db_session,
    test_user,
    auth_headers,
):
    enabled = Library(name="Enabled", path="/films%_", enabled=True)
    disabled = Library(name="Disabled", path="/disabled", enabled=False)
    db_session.add_all([enabled, disabled])
    await db_session.flush()
    visible = await add_media(db_session, "/films%_/Target visible.mkv")
    hidden = [
        await add_media(db_session, path, deleted=deleted)
        for path, deleted in [
            ("/films%_/Target deleted.mkv", True),
            ("/disabled/Target disabled.mkv", False),
            ("/films%_sibling/Target sibling.mkv", False),
            ("/filmsXX/Target wildcard.mkv", False),
        ]
    ]
    db_session.add_all([WatchlistEntry(user_id=test_user.id, media_file_id=media.id) for media in [visible, *hidden]])
    await db_session.commit()
    for endpoint, params in [("/media-files/search", {"q": "target"}), ("/users/me/watchlist", {})]:
        response = await client.get(f"/api/v1{endpoint}", params=params, headers=auth_headers)
        assert [item["id"] for item in response.json()] == [visible.id]
    restricted = await client.get(
        "/api/v1/media-files/search", params={"q": "target", "library_id": disabled.id}, headers=auth_headers
    )
    assert restricted.json() == []
    for media in hidden:
        assert (await client.put(f"/api/v1/users/me/watchlist/{media.id}", headers=auth_headers)).status_code == 404
        assert (await client.delete(f"/api/v1/users/me/watchlist/{media.id}", headers=auth_headers)).status_code == 200


async def test_watchlist_is_personal_idempotent_and_visible_in_card_and_detail(
    client,
    db_session,
    test_library,
    test_user,
    auth_headers,
    admin_auth_headers,
):
    media = await add_media(db_session, f"{test_library.path}/saved.mkv")
    await db_session.commit()
    endpoint = f"/api/v1/users/me/watchlist/{media.id}"
    for _ in range(2):
        added = await client.put(endpoint, headers=auth_headers)
        assert added.status_code == 200
        assert added.json() == {"media_file_id": media.id, "in_watchlist": True}
    assert await db_session.scalar(select(func.count()).select_from(WatchlistEntry)) == 1
    own = await client.get("/api/v1/users/me/watchlist", headers=auth_headers)
    assert [item["id"] for item in own.json()] == [media.id]
    assert own.json()[0]["in_watchlist"] is True
    assert (await client.get("/api/v1/users/me/watchlist", headers=admin_auth_headers)).json() == []
    for headers, expected in [(auth_headers, True), (admin_auth_headers, False)]:
        detail = await client.get(f"/api/v1/media/{media.id}", headers=headers)
        assert detail.json()["in_watchlist"] is expected
        cards = await client.get("/api/v1/media-files", headers=headers)
        assert cards.json()[0]["in_watchlist"] is expected
    await client.delete(endpoint, headers=admin_auth_headers)
    assert await db_session.scalar(select(func.count()).select_from(WatchlistEntry)) == 1
    for _ in range(2):
        removed = await client.delete(endpoint, headers=auth_headers)
        assert removed.status_code == 200
        assert removed.json()["in_watchlist"] is False
    assert await db_session.scalar(select(func.count()).select_from(WatchlistEntry)) == 0


@pytest.mark.parametrize("endpoint", ["media-files/search?q=film&", "users/me/watchlist?"])
async def test_discovery_keyset_is_stable_after_earlier_deletion(
    client,
    db_session,
    test_library,
    test_user,
    auth_headers,
    endpoint,
):
    films = [await add_media(db_session, f"{test_library.path}/film-{index}.mkv") for index in range(5)]
    db_session.add_all([WatchlistEntry(user_id=test_user.id, media_file_id=film.id) for film in films])
    await db_session.commit()
    first = await client.get(f"/api/v1/{endpoint}limit=2", headers=auth_headers)
    assert [item["id"] for item in first.json()] == [film.id for film in films[:2]]
    await db_session.delete(films[0])
    await db_session.commit()
    after = await client.get(f"/api/v1/{endpoint}limit=2&after_id={films[1].id}", headers=auth_headers)
    assert [item["id"] for item in after.json()] == [film.id for film in films[2:4]]
    offset = await client.get(f"/api/v1/{endpoint}limit=2&skip=1", headers=auth_headers)
    assert [item["id"] for item in offset.json()] == [film.id for film in films[2:4]]


@pytest.mark.parametrize(
    "params",
    [
        {"q": ""},
        {"q": "   "},
        {"q": "x" * 201},
        {"q": "film", "limit": 101},
        {"q": "film", "skip": -1},
        {"q": "film", "skip": 1, "after_id": 2},
    ],
)
async def test_search_rejects_unbounded_or_ambiguous_requests(client, auth_headers, params):
    assert (await client.get("/api/v1/media-files/search", params=params, headers=auth_headers)).status_code == 422


async def test_concurrent_watchlist_adds_are_successful_and_unique(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'watchlist.db'}")

    @event.listens_for(engine.sync_engine, "connect")
    def foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        user = User(username="viewer", password="password")
        session.add_all([user, Library(name="Films", path="/films", enabled=True)])
        media = await add_media(session, "/films/concurrent.mkv")
        await session.commit()
    ready = asyncio.Barrier(8)

    async def sessions():
        async with factory() as session:
            await ready.wait()
            yield session

    application = FastAPI()
    application.include_router(router)
    application.dependency_overrides[get_session] = sessions
    try:
        headers = {"Authorization": f"Bearer {create_access_token({'sub': str(user.id)})}"}
        async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
            responses = await asyncio.gather(*[
                client.put(f"/api/v1/users/me/watchlist/{media.id}", headers=headers) for _ in range(8)
            ])
            assert [response.status_code for response in responses] == [200] * 8
            assert all(response.json()["in_watchlist"] for response in responses)
        async with factory() as session:
            assert await session.scalar(select(func.count()).select_from(WatchlistEntry)) == 1
            await session.delete(await session.get(User, user.id))
            await session.commit()
            assert await session.scalar(select(func.count()).select_from(WatchlistEntry)) == 0
    finally:
        await engine.dispose()


async def test_relevance_orders_before_limit_and_paginates_stably(client, db_session, test_library, auth_headers):
    names = ["Animatrix.mkv", "The Matrix Revolutions.mkv", "Matrix Reloaded.mkv", "Matrix.mkv"]
    films = [await add_media(db_session, f"{test_library.path}/{name}") for name in names]
    await db_session.commit()
    ordered = []
    for skip in (0, 2):
        response = await client.get(
            "/api/v1/media-files/search",
            params={"q": "mAtRiX", "sort": "relevance", "limit": 2, "skip": skip},
            headers=auth_headers,
        )
        assert response.status_code == 200
        ordered.extend(item["id"] for item in response.json())
    assert ordered == [films[3].id, films[2].id, films[1].id, films[0].id]
    invalid = await client.get(
        "/api/v1/media-files/search", params={"q": "matrix", "sort": "relevance", "after_id": 1}, headers=auth_headers
    )
    assert invalid.status_code == 422
