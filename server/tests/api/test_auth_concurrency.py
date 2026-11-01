"""Exercise auth races with separate database connections and real transactions."""

import asyncio

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import get_session
from app.models import Base, RefreshToken, User
from app.routers.v1.auth import router as auth_router
from app.services.setup import router as setup_router


async def test_setup_and_refresh_are_single_use_across_connections(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'race.db'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async def sessions():
        async with factory() as session:
            yield session

    application = FastAPI()
    application.include_router(setup_router)
    application.include_router(auth_router)
    application.dependency_overrides[get_session] = sessions
    try:
        async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
            responses = await asyncio.gather(*[
                client.post("/api/v1/setup/admin", json={"username": name, "password": "password123"})
                for name in ("first", "second")
            ])
            assert sorted(response.status_code for response in responses) == [201, 403]
            token = next(response.json()["refresh_token"] for response in responses if response.status_code == 201)
            refreshed = await asyncio.gather(*[
                client.post("/api/v1/auth/refresh", json={"refresh_token": token}) for _ in range(2)
            ])
            assert sorted(response.status_code for response in refreshed) == [200, 401]
        async with factory() as session:
            assert await session.scalar(select(func.count()).select_from(User)) == 1
            assert await session.scalar(select(func.count()).select_from(RefreshToken)) == 1
    finally:
        await engine.dispose()
