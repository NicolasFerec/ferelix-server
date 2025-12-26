"""API tests for dashboard endpoints."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Library, User


class TestDashboardAccess:
    """Tests for dashboard access control."""

    @pytest.mark.asyncio
    async def test_dashboard_requires_admin(
        self,
        client: AsyncClient,
        test_user: User,
        auth_headers: dict[str, str],
    ) -> None:
        """Test that non-admin users cannot access dashboard."""
        response = await client.get(
            "/api/v1/dashboard/libraries",
            headers=auth_headers,
        )

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_dashboard_admin_access(
        self,
        client: AsyncClient,
        admin_user: User,
        admin_auth_headers: dict[str, str],
    ) -> None:
        """Test that admin users can access dashboard."""
        response = await client.get(
            "/api/v1/dashboard/libraries",
            headers=admin_auth_headers,
        )

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_dashboard_unauthenticated(
        self,
        client: AsyncClient,
    ) -> None:
        """Test that unauthenticated requests are rejected."""
        response = await client.get("/api/v1/dashboard/libraries")

        assert response.status_code == 401


class TestLibraryManagement:
    """Tests for library management endpoints."""

    @pytest.mark.asyncio
    async def test_get_libraries_empty(
        self,
        client: AsyncClient,
        admin_user: User,
        admin_auth_headers: dict[str, str],
    ) -> None:
        """Test getting empty library list."""
        response = await client.get(
            "/api/v1/dashboard/libraries",
            headers=admin_auth_headers,
        )

        assert response.status_code == 200
        assert response.json() == []

    @pytest.mark.asyncio
    async def test_get_libraries_with_data(
        self,
        client: AsyncClient,
        admin_user: User,
        admin_auth_headers: dict[str, str],
        test_library: Library,
    ) -> None:
        """Test getting library list with data."""
        response = await client.get(
            "/api/v1/dashboard/libraries",
            headers=admin_auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == test_library.name
        assert data[0]["path"] == test_library.path

    @pytest.mark.asyncio
    async def test_create_library_success(
        self,
        client: AsyncClient,
        admin_user: User,
        admin_auth_headers: dict[str, str],
    ) -> None:
        """Test successful library creation."""
        response = await client.post(
            "/api/v1/dashboard/libraries",
            headers=admin_auth_headers,
            json={
                "name": "Movies",
                "path": "/media/movies",
                "library_type": "movie",
                "enabled": True,
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Movies"
        assert data["path"] == "/media/movies"
        assert data["library_type"] == "movie"
        assert data["enabled"] is True

    @pytest.mark.asyncio
    async def test_create_library_duplicate_path(
        self,
        client: AsyncClient,
        admin_user: User,
        admin_auth_headers: dict[str, str],
        test_library: Library,
    ) -> None:
        """Test library creation with duplicate path fails."""
        response = await client.post(
            "/api/v1/dashboard/libraries",
            headers=admin_auth_headers,
            json={
                "name": "Different Name",
                "path": test_library.path,
                "library_type": "movie",
            },
        )

        assert response.status_code == 409

    @pytest.mark.asyncio
    async def test_update_library(
        self,
        client: AsyncClient,
        admin_user: User,
        admin_auth_headers: dict[str, str],
        test_library: Library,
    ) -> None:
        """Test library update."""
        response = await client.patch(
            f"/api/v1/dashboard/libraries/{test_library.id}",
            headers=admin_auth_headers,
            json={
                "name": "Updated Library",
                "enabled": False,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Updated Library"
        assert data["enabled"] is False

    @pytest.mark.asyncio
    async def test_update_library_not_found(
        self,
        client: AsyncClient,
        admin_user: User,
        admin_auth_headers: dict[str, str],
    ) -> None:
        """Test library update with invalid ID."""
        response = await client.patch(
            "/api/v1/dashboard/libraries/99999",
            headers=admin_auth_headers,
            json={"name": "Updated"},
        )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_library(
        self,
        client: AsyncClient,
        admin_user: User,
        admin_auth_headers: dict[str, str],
        test_library: Library,
    ) -> None:
        """Test library deletion."""
        response = await client.delete(
            f"/api/v1/dashboard/libraries/{test_library.id}",
            headers=admin_auth_headers,
        )

        assert response.status_code == 204

        # Verify deletion
        get_response = await client.get(
            "/api/v1/dashboard/libraries",
            headers=admin_auth_headers,
        )
        assert len(get_response.json()) == 0


class TestUserManagement:
    """Tests for user management endpoints."""

    @pytest.mark.asyncio
    async def test_get_users(
        self,
        client: AsyncClient,
        admin_user: User,
        admin_auth_headers: dict[str, str],
        test_user: User,
    ) -> None:
        """Test getting user list."""
        response = await client.get(
            "/api/v1/dashboard/users",
            headers=admin_auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        # Should have both admin and test user
        assert len(data) >= 2

    @pytest.mark.asyncio
    async def test_get_user_by_id(
        self,
        client: AsyncClient,
        admin_user: User,
        admin_auth_headers: dict[str, str],
        test_user: User,
    ) -> None:
        """Test getting a specific user."""
        response = await client.get(
            f"/api/v1/dashboard/users/{test_user.id}",
            headers=admin_auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["username"] == test_user.username

    @pytest.mark.asyncio
    async def test_update_user(
        self,
        client: AsyncClient,
        admin_user: User,
        admin_auth_headers: dict[str, str],
        test_user: User,
    ) -> None:
        """Test updating a user."""
        response = await client.patch(
            f"/api/v1/dashboard/users/{test_user.id}",
            headers=admin_auth_headers,
            json={"is_active": False},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["is_active"] is False


class TestJobsManagement:
    """Tests for jobs management endpoints."""

    @pytest.mark.asyncio
    async def test_get_jobs(
        self,
        client: AsyncClient,
        admin_user: User,
        admin_auth_headers: dict[str, str],
    ) -> None:
        """Test getting jobs list."""
        response = await client.get(
            "/api/v1/dashboard/jobs",
            headers=admin_auth_headers,
        )

        assert response.status_code == 200
        # Should return a list (may be empty if scheduler not running)
        assert isinstance(response.json(), list)

    @pytest.mark.asyncio
    async def test_get_job_history(
        self,
        client: AsyncClient,
        admin_user: User,
        admin_auth_headers: dict[str, str],
    ) -> None:
        """Test getting job execution history."""
        response = await client.get(
            "/api/v1/dashboard/jobs/history",
            headers=admin_auth_headers,
        )

        assert response.status_code == 200
        assert isinstance(response.json(), list)
