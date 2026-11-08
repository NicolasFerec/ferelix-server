"""Concurrent bulk confirmations cannot partially apply overlapping snapshots."""

import asyncio

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Base, Library, User
from app.models.metadata import MediaItem, UserItemState
from app.services.viewing import bulk_watch_state


async def test_overlapping_series_and_season_confirmations_are_atomic(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'viewing.db'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        async with factory() as session:
            user = User(username="viewer", password="password", is_active=True)
            library = Library(name="Series", path=str(tmp_path))
            session.add_all([user, library])
            await session.flush()
            series = MediaItem(kind="series", title="Series", metadata_library_id=library.id)
            session.add(series)
            await session.flush()
            season = MediaItem(kind="season", title="S1", metadata_library_id=library.id, parent_id=series.id)
            session.add(season)
            await session.flush()
            episodes = [
                MediaItem(
                    kind="episode",
                    title=str(index),
                    metadata_library_id=library.id,
                    parent_id=season.id,
                    series_id=series.id,
                )
                for index in range(5)
            ]
            session.add_all(episodes)
            await session.flush()
            session.add_all([UserItemState(user_id=user.id, item_id=item.id) for item in episodes])
            await session.commit()
            first = await bulk_watch_state(session, user.id, series.id, True)
            second = await bulk_watch_state(session, user.id, season.id, True)
        gate = asyncio.Event()

        async def confirm(item_id, token):
            await gate.wait()
            async with factory() as session:
                try:
                    await bulk_watch_state(session, user.id, item_id, True, preview=False, revision_token=token)
                    await session.commit()
                    return 200
                except HTTPException as exc:
                    await session.rollback()
                    return exc.status_code

        tasks = [
            asyncio.create_task(confirm(series.id, first["revision_token"])),
            asyncio.create_task(confirm(season.id, second["revision_token"])),
        ]
        gate.set()
        async with asyncio.timeout(5):
            assert sorted(await asyncio.gather(*tasks)) == [200, 409]
        async with factory() as session:
            states = list(await session.scalars(select(UserItemState)))
            assert len(states) == 5
            assert all(state.watched and state.state_revision == 1 for state in states)
    finally:
        await engine.dispose()
