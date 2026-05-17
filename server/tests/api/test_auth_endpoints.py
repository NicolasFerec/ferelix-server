"""API tests for authentication endpoints."""

from io import BytesIO
from pathlib import Path

import pytest
from httpx import AsyncClient
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.services import profile_images


def make_png_bytes(width: int = 20, height: int = 12) -> bytes:
    """Create a small valid PNG image for upload tests."""
    buffer = BytesIO()
    Image.new("RGB", (width, height), (40, 100, 220)).save(buffer, format="PNG")
    return buffer.getvalue()


class TestRegister:
    """Tests for POST /api/v1/auth/register."""

    @pytest.mark.asyncio
    async def test_register_success(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        """Test successful user registration."""
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "username": "newuser",
                "email": "new@example.com",
                "password": "password123",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["username"] == "newuser"
        assert data["email"] == "new@example.com"
        assert "password" not in data

    @pytest.mark.asyncio
    async def test_register_duplicate_username(
        self,
        client: AsyncClient,
        test_user: User,
    ) -> None:
        """Test registration with existing username fails."""
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "username": test_user.username,
                "email": "different@example.com",
                "password": "password123",
            },
        )

        assert response.status_code == 400
        assert "already registered" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_register_duplicate_email(
        self,
        client: AsyncClient,
        test_user: User,
    ) -> None:
        """Test registration with existing email fails."""
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "username": "uniqueuser",
                "email": test_user.email,
                "password": "password123",
            },
        )

        assert response.status_code == 400
        assert "already registered" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_register_cannot_create_admin(
        self,
        client: AsyncClient,
    ) -> None:
        """Test public registration always creates reader accounts."""
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "username": "notadmin",
                "email": "notadmin@example.com",
                "password": "password123",
                "role": "admin",
                "is_admin": True,
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["role"] == "reader"
        assert data["is_admin"] is False


class TestLogin:
    """Tests for POST /api/v1/auth/login."""

    @pytest.mark.asyncio
    async def test_login_success(
        self,
        client: AsyncClient,
        test_user: User,
    ) -> None:
        """Test successful login."""
        response = await client.post(
            "/api/v1/auth/login",
            json={
                "username": test_user.username,
                "password": "testpassword123",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"
        assert data["user"]["username"] == test_user.username

    @pytest.mark.asyncio
    async def test_login_invalid_password(
        self,
        client: AsyncClient,
        test_user: User,
    ) -> None:
        """Test login with invalid password fails."""
        response = await client.post(
            "/api/v1/auth/login",
            json={
                "username": test_user.username,
                "password": "wrongpassword",
            },
        )

        assert response.status_code == 401
        assert "incorrect" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_login_invalid_username(
        self,
        client: AsyncClient,
    ) -> None:
        """Test login with invalid username fails."""
        response = await client.post(
            "/api/v1/auth/login",
            json={
                "username": "nonexistent",
                "password": "password123",
            },
        )

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_login_inactive_user(
        self,
        client: AsyncClient,
        inactive_user: User,
    ) -> None:
        """Test login with inactive user fails."""
        response = await client.post(
            "/api/v1/auth/login",
            json={
                "username": inactive_user.username,
                "password": "password123",
            },
        )

        assert response.status_code == 403
        assert "inactive" in response.json()["detail"].lower()


class TestRefresh:
    """Tests for POST /api/v1/auth/refresh."""

    @pytest.mark.asyncio
    async def test_refresh_success(
        self,
        client: AsyncClient,
        test_user: User,
    ) -> None:
        """Test successful token refresh."""
        # First login to get tokens
        login_response = await client.post(
            "/api/v1/auth/login",
            json={
                "username": test_user.username,
                "password": "testpassword123",
            },
        )
        refresh_token = login_response.json()["refresh_token"]

        # Then refresh
        response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_token},
        )

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        # New tokens should be different
        assert data["refresh_token"] != refresh_token

    @pytest.mark.asyncio
    async def test_refresh_invalid_token(
        self,
        client: AsyncClient,
    ) -> None:
        """Test refresh with invalid token fails."""
        response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": "invalid-token"},
        )

        assert response.status_code == 401


class TestLogout:
    """Tests for POST /api/v1/auth/logout."""

    @pytest.mark.asyncio
    async def test_logout_success(
        self,
        client: AsyncClient,
        test_user: User,
    ) -> None:
        """Test successful logout."""
        # First login to get tokens
        login_response = await client.post(
            "/api/v1/auth/login",
            json={
                "username": test_user.username,
                "password": "testpassword123",
            },
        )
        data = login_response.json()
        access_token = data["access_token"]
        refresh_token = data["refresh_token"]

        # Then logout
        response = await client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"refresh_token": refresh_token},
        )

        assert response.status_code == 204

    @pytest.mark.asyncio
    async def test_logout_unauthenticated(
        self,
        client: AsyncClient,
    ) -> None:
        """Test logout without authentication fails."""
        response = await client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": "some-token"},
        )

        assert response.status_code == 401


class TestCurrentUserProfileImage:
    """Tests for current-user profile image endpoints."""

    @pytest.mark.asyncio
    async def test_upload_and_delete_current_user_profile_image(
        self,
        client: AsyncClient,
        test_user: User,
        auth_headers: dict[str, str],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test users can manage their own profile image."""
        monkeypatch.setattr(profile_images, "DEFAULT_PROFILE_IMAGE_DIR", str(tmp_path))

        upload_response = await client.put(
            "/api/v1/users/me/profile-image",
            headers=auth_headers,
            files={"image": ("avatar.png", make_png_bytes(), "image/png")},
        )

        assert upload_response.status_code == 200
        data = upload_response.json()
        assert data["profile_image_url"] == f"/api/v1/users/{test_user.id}/profile-image"

        image_response = await client.get(
            data["profile_image_url"],
            headers=auth_headers,
        )
        assert image_response.status_code == 200
        assert image_response.headers["content-type"] == "image/jpeg"
        assert image_response.content.startswith(b"\xff\xd8")

        delete_response = await client.delete(
            "/api/v1/users/me/profile-image",
            headers=auth_headers,
        )

        assert delete_response.status_code == 200
        assert delete_response.json()["profile_image_url"] is None
