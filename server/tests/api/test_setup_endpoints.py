"""API tests for setup endpoints."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User


class TestGetSetupStatus:
    """Tests for GET /api/v1/setup/status."""

    @pytest.mark.asyncio
    async def test_setup_status_incomplete(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        """Test setup status when no users exist."""
        response = await client.get("/api/v1/setup/status")

        assert response.status_code == 200
        data = response.json()
        assert data["setup_complete"] is False

    @pytest.mark.asyncio
    async def test_setup_status_complete(
        self,
        client: AsyncClient,
        test_user: User,
    ) -> None:
        """Test setup status when users exist."""
        response = await client.get("/api/v1/setup/status")

        assert response.status_code == 200
        data = response.json()
        assert data["setup_complete"] is True


class TestCreateFirstAdmin:
    """Tests for POST /api/v1/setup/admin."""

    @pytest.mark.asyncio
    async def test_create_first_admin_success(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        """Test successful first admin creation."""
        response = await client.post(
            "/api/v1/setup/admin",
            json={
                "username": "admin",
                "password": "adminpassword123",
                "language": "en",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["user"]["username"] == "admin"
        assert data["user"]["is_admin"] is True

    @pytest.mark.asyncio
    async def test_create_first_admin_with_french_language(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        """Test first admin creation with French language."""
        response = await client.post(
            "/api/v1/setup/admin",
            json={
                "username": "admin_fr",
                "password": "adminpassword123",
                "language": "fr",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["user"]["language"] == "fr"

    @pytest.mark.asyncio
    async def test_create_first_admin_already_setup(
        self,
        client: AsyncClient,
        test_user: User,
    ) -> None:
        """Test admin creation when setup already complete."""
        response = await client.post(
            "/api/v1/setup/admin",
            json={
                "username": "another_admin",
                "password": "adminpassword123",
            },
        )

        assert response.status_code == 403
        assert "already complete" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_create_first_admin_missing_username(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        """Test admin creation with missing username."""
        response = await client.post(
            "/api/v1/setup/admin",
            json={
                "password": "adminpassword123",
            },
        )

        assert response.status_code == 422  # Validation error

    @pytest.mark.asyncio
    async def test_create_first_admin_missing_password(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        """Test admin creation with missing password."""
        response = await client.post(
            "/api/v1/setup/admin",
            json={
                "username": "admin",
            },
        )

        assert response.status_code == 422  # Validation error
