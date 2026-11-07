"""Rejected numeric inputs remain useful 422 responses and never persist progress."""

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MediaFile, MediaView, User


@pytest.fixture
async def media_for_validation(db_session: AsyncSession) -> MediaFile:
    media = MediaFile(file_path="/validation.mp4", file_name="validation.mp4", file_extension=".mp4", file_size=1)
    db_session.add(media)
    await db_session.commit()
    return media


@pytest.mark.parametrize("field", ["position_seconds", "duration_seconds"])
@pytest.mark.parametrize("number", ["NaN", "Infinity", "-Infinity", "1e309", "-1"])
async def test_invalid_progress_returns_json_422_without_mutating_watch_state(
    client: AsyncClient,
    db_session: AsyncSession,
    test_user: User,
    auth_headers: dict[str, str],
    media_for_validation: MediaFile,
    field: str,
    number: str,
) -> None:
    response = await client.patch(
        f"/api/v1/media/{media_for_validation.id}/view",
        headers={**auth_headers, "Content-Type": "application/json"},
        content=f'{{"{field}":{number}}}',
    )
    assert response.status_code == 422
    error = response.json()["detail"][0]
    assert error["loc"] == ["body", field]
    assert error["type"] == ("greater_than_equal" if number == "-1" else "finite_number")
    assert set(error) == {"loc", "msg", "type"}
    assert await db_session.scalar(select(func.count()).select_from(MediaView)) == 0


async def test_zero_position_and_unknown_duration_remain_valid(
    client: AsyncClient,
    test_user: User,
    auth_headers: dict[str, str],
    media_for_validation: MediaFile,
) -> None:
    response = await client.patch(
        f"/api/v1/media/{media_for_validation.id}/view",
        headers=auth_headers,
        json={"position_seconds": 0, "duration_seconds": None},
    )
    assert response.status_code == 200
    assert response.json()["position_seconds"] == 0
    assert response.json()["duration_seconds"] is None


async def test_validation_handler_preserves_normal_http_errors(
    client: AsyncClient,
    test_user: User,
    auth_headers: dict[str, str],
    media_for_validation: MediaFile,
) -> None:
    unauthorized = await client.get("/api/v1/users/me")
    assert unauthorized.status_code == 401
    assert isinstance(unauthorized.json()["detail"], str)
    missing = await client.get("/api/v1/media/999999", headers=auth_headers)
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Media file not found"}
    malformed = await client.patch(
        f"/api/v1/media/{media_for_validation.id}/view",
        headers={**auth_headers, "Content-Type": "application/json"},
        content="{",
    )
    assert malformed.status_code == 422
    assert malformed.json()["detail"][0]["type"] == "json_invalid"
    invalid_path = await client.get("/api/v1/media/not-an-integer", headers=auth_headers)
    assert invalid_path.status_code == 422
    assert invalid_path.json()["detail"][0]["loc"] == ["path", "media_id"]
