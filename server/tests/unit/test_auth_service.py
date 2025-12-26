"""Unit tests for the auth service."""

from datetime import timedelta

import pytest

from app.services.auth import (
    create_access_token,
    create_refresh_token,
    hash_token,
    verify_token,
)


class TestCreateAccessToken:
    """Tests for create_access_token function."""

    def test_creates_valid_token(self) -> None:
        """Test that create_access_token creates a valid JWT."""
        token = create_access_token(data={"sub": "123"})

        assert token is not None
        assert isinstance(token, str)
        assert len(token) > 0

    def test_token_contains_user_id(self) -> None:
        """Test that token contains the user ID in payload."""
        token = create_access_token(data={"sub": "456"})

        payload = verify_token(token, token_type="access")
        assert payload is not None
        assert payload["sub"] == "456"

    def test_token_has_access_type(self) -> None:
        """Test that token has type 'access'."""
        token = create_access_token(data={"sub": "789"})

        payload = verify_token(token, token_type="access")
        assert payload is not None
        assert payload["type"] == "access"

    def test_custom_expiration(self) -> None:
        """Test that custom expiration is applied."""
        token = create_access_token(
            data={"sub": "123"},
            expires_delta=timedelta(hours=1),
        )

        payload = verify_token(token, token_type="access")
        assert payload is not None
        assert "exp" in payload


class TestCreateRefreshToken:
    """Tests for create_refresh_token function."""

    def test_creates_valid_token(self) -> None:
        """Test that create_refresh_token creates a valid JWT."""
        token = create_refresh_token(data={"sub": "123"})

        assert token is not None
        assert isinstance(token, str)
        assert len(token) > 0

    def test_token_contains_user_id(self) -> None:
        """Test that refresh token contains the user ID."""
        token = create_refresh_token(data={"sub": "999"})

        payload = verify_token(token, token_type="refresh")
        assert payload is not None
        assert payload["sub"] == "999"

    def test_token_has_refresh_type(self) -> None:
        """Test that token has type 'refresh'."""
        token = create_refresh_token(data={"sub": "123"})

        payload = verify_token(token, token_type="refresh")
        assert payload is not None
        assert payload["type"] == "refresh"

    def test_custom_expiration(self) -> None:
        """Test that custom expiration is applied."""
        token = create_refresh_token(
            data={"sub": "123"},
            expires_delta=timedelta(days=14),
        )

        payload = verify_token(token, token_type="refresh")
        assert payload is not None
        assert "exp" in payload


class TestVerifyToken:
    """Tests for verify_token function."""

    def test_valid_access_token(self) -> None:
        """Test verification of valid access token."""
        token = create_access_token(data={"sub": "123"})

        payload = verify_token(token, token_type="access")

        assert payload is not None
        assert payload["sub"] == "123"

    def test_valid_refresh_token(self) -> None:
        """Test verification of valid refresh token."""
        token = create_refresh_token(data={"sub": "456"})

        payload = verify_token(token, token_type="refresh")

        assert payload is not None
        assert payload["sub"] == "456"

    def test_wrong_token_type_returns_none(self) -> None:
        """Test that verifying with wrong type returns None."""
        access_token = create_access_token(data={"sub": "123"})
        refresh_token = create_refresh_token(data={"sub": "456"})

        # Access token verified as refresh should fail
        assert verify_token(access_token, token_type="refresh") is None
        # Refresh token verified as access should fail
        assert verify_token(refresh_token, token_type="access") is None

    def test_invalid_token_returns_none(self) -> None:
        """Test that invalid token returns None."""
        payload = verify_token("invalid-token", token_type="access")

        assert payload is None

    def test_tampered_token_returns_none(self) -> None:
        """Test that tampered token returns None."""
        token = create_access_token(data={"sub": "123"})
        # Tamper with the token
        tampered = token[:-5] + "xxxxx"

        payload = verify_token(tampered, token_type="access")

        assert payload is None


class TestHashToken:
    """Tests for hash_token function."""

    def test_returns_hex_string(self) -> None:
        """Test that hash_token returns a hex string."""
        hashed = hash_token("test-token")

        assert isinstance(hashed, str)
        assert len(hashed) == 64  # SHA256 produces 64 hex chars

    def test_same_input_same_output(self) -> None:
        """Test that same input produces same hash."""
        token = "my-refresh-token"

        hash1 = hash_token(token)
        hash2 = hash_token(token)

        assert hash1 == hash2

    def test_different_input_different_output(self) -> None:
        """Test that different inputs produce different hashes."""
        hash1 = hash_token("token-1")
        hash2 = hash_token("token-2")

        assert hash1 != hash2

    def test_hashes_are_deterministic(self) -> None:
        """Test that hashing is deterministic."""
        known_token = "known-test-token"
        expected_hash = hash_token(known_token)

        # Hash should always be the same for the same input
        for _ in range(10):
            assert hash_token(known_token) == expected_hash
