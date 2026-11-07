"""Credential revocation and normalized identities across actual DB transactions."""

import asyncio

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import Base, RefreshToken, User
from app.services.accounts import change_password, commit_account_changes, ensure_identity_available


async def sign_in(client: AsyncClient, username: str, password: str) -> dict:
    response = await client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("admin_reset", [False, True])
async def test_password_change_revokes_every_old_access_and_refresh(
    client: AsyncClient,
    db_session: AsyncSession,
    test_user: User,
    admin_auth_headers: dict[str, str],
    admin_reset: bool,
) -> None:
    tokens = [await sign_in(client, "testuser", "testpassword123") for _ in range(2)]
    headers = {"Authorization": f"Bearer {tokens[0]['access_token']}"}
    response = await client.patch(
        f"/api/v1/dashboard/users/{test_user.id}" if admin_reset else "/api/v1/users/me",
        headers=admin_auth_headers if admin_reset else headers,
        json={"password": "replacement", "current_password": "testpassword123", "username": "Renamed"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["username"] == "Renamed"
    assert test_user.credentials_version == 1
    assert (
        await db_session.scalar(
            select(func.count()).select_from(RefreshToken).where(RefreshToken.user_id == test_user.id)
        )
        == 0
    )
    for old in tokens:
        assert (
            await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {old['access_token']}"})
        ).status_code == 401
        assert (await client.get("/api/v1/users/me", params={"api_key": old["access_token"]})).status_code == 401
        assert (
            await client.post("/api/v1/auth/refresh", json={"refresh_token": old["refresh_token"]})
        ).status_code == 401
    fresh = await sign_in(client, " renamed ", "replacement")
    assert (
        await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {fresh['access_token']}"})
    ).status_code == 200


@pytest.mark.parametrize("current_password,detail", [(None, "required"), ("incorrect", "incorrect")])
async def test_self_change_requires_current_password(
    client: AsyncClient,
    test_user: User,
    auth_headers: dict[str, str],
    current_password: str | None,
    detail: str,
) -> None:
    response = await client.patch(
        "/api/v1/users/me", headers=auth_headers, json={"password": "replacement", "current_password": current_password}
    )
    assert response.status_code == 400
    assert detail in response.json()["detail"]
    assert test_user.credentials_version == 0
    assert test_user.password == "testpassword123"


async def test_admin_cannot_bypass_current_password_using_dashboard(
    client: AsyncClient,
    admin_user: User,
    admin_auth_headers: dict[str, str],
) -> None:
    endpoint = f"/api/v1/dashboard/users/{admin_user.id}"
    response = await client.patch(endpoint, headers=admin_auth_headers, json={"password": "replacement"})
    assert response.status_code == 400
    assert response.json()["detail"] == "Current password is required"
    assert admin_user.credentials_version == 0
    response = await client.patch(
        endpoint, headers=admin_auth_headers, json={"password": "replacement", "current_password": "adminpassword123"}
    )
    assert response.status_code == 200
    assert admin_user.credentials_version == 1


@pytest.mark.parametrize("identity", ["username", "email"])
async def test_normalized_identity_unique_under_concurrent_creation(tmp_path, identity: str) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'identities.db'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    checked = asyncio.Barrier(2)

    async def create(index: int) -> int:
        async with factory() as session:
            username = ("Straße", " STRASSE ")[index] if identity == "username" else f"reader{index}"
            email = (" Reader@Example.com ", "reader@example.com")[index] if identity == "email" else None
            await ensure_identity_available(session, username=username, email=email)
            await checked.wait()
            session.add(User(username=username, email=email, password="password"))
            try:
                await commit_account_changes(session)
                return 201
            except HTTPException as exc:
                return exc.status_code

    try:
        assert sorted(await asyncio.gather(create(0), create(1))) == [201, 409]
        async with factory() as session:
            assert await session.scalar(select(func.count()).select_from(User)) == 1
    finally:
        await engine.dispose()


async def test_concurrent_password_changes_do_not_overwrite_each_other(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'passwords.db'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        session.add(User(username="reader", password="original"))
        await session.commit()
    loaded = asyncio.Barrier(2)

    async def change(password: str) -> int:
        async with factory() as session:
            user = await session.get(User, 1)
            assert user is not None
            await loaded.wait()
            try:
                await change_password(session, user, password, current_password="original", require_current=True)
                await commit_account_changes(session)
                return 200
            except HTTPException as exc:
                return exc.status_code

    try:
        assert sorted(await asyncio.gather(change("first"), change("second"))) == [200, 409]
        async with factory() as session:
            user = await session.get(User, 1)
            assert user is not None and user.credentials_version == 1
    finally:
        await engine.dispose()
