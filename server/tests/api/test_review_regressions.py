"""Regression coverage for authorization, library isolation, and library deletion."""

from pathlib import Path
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Library, MediaFile, RecommendationRow
from app.services.scanner import scan_library_path


@pytest.mark.parametrize("authenticated", [False, True])
async def test_registration_requires_admin(client: AsyncClient, auth_headers, authenticated: bool) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        headers=auth_headers if authenticated else {},
        json={"username": "intruder", "email": None, "password": "password123"},
    )
    assert response.status_code == (403 if authenticated else 401)


async def test_delete_library_removes_its_recommendation_rows(client, db_session, test_library, admin_auth_headers):
    row = RecommendationRow(library_id=test_library.id, name="Recently added", filter_criteria={})
    db_session.add(row)
    await db_session.commit()
    row_id = row.id
    response = await client.delete(f"/api/v1/dashboard/libraries/{test_library.id}", headers=admin_auth_headers)
    assert response.status_code == 204
    assert await db_session.scalar(select(RecommendationRow.id).where(RecommendationRow.id == row_id)) is None


@pytest.mark.parametrize("name", ["movies", "movies_1", "movies%1"])
async def test_library_scan_does_not_delete_sibling_media(db_session: AsyncSession, tmp_path: Path, name: str) -> None:
    directory = tmp_path / name
    directory.mkdir()
    sibling = tmp_path / (name + "-other") / "movie.mp4"
    wildcard_sibling = tmp_path / name.replace("_", "x").replace("%", "x") / "movie.mp4"
    library = Library(name="Movies", path=str(directory), enabled=True)
    media = [
        MediaFile(file_path=str(path), file_name=path.name, file_size=1, file_extension=".mp4")
        for path in {sibling, wildcard_sibling}
        if path.parent != directory
    ]
    db_session.add_all([library, *media])
    await db_session.commit()
    with patch("app.services.scanner.extract_video_metadata"), patch("app.services.scanner.generate_video_thumbnail"):
        stats = await scan_library_path(db_session, library)
    assert stats["deleted"] == 0
    for item in media:
        await db_session.refresh(item)
        assert item.deleted_at is None


async def test_hls_start_keeps_not_found_status(client, auth_headers, monkeypatch):

    monkeypatch.setattr("app.services.playback_session.get_transcoder", object)
    response = await client.post("/api/v1/hls/999999/remux", headers=auth_headers)
    assert response.status_code == 404


async def test_unreadable_directory_does_not_soft_delete_media(db_session, tmp_path, monkeypatch):
    library = Library(name="Movies", path=str(tmp_path), enabled=True)
    media = MediaFile(file_path=str(tmp_path / "movie.mp4"), file_name="movie.mp4", file_size=1, file_extension=".mp4")
    db_session.add_all([library, media])
    await db_session.commit()

    def unreadable_walk(path, *, onerror):
        onerror(PermissionError("directory unavailable"))
        return iter(())

    monkeypatch.setattr("app.services.scanner.os.walk", unreadable_walk)
    with pytest.raises(PermissionError, match="directory unavailable"):
        await scan_library_path(db_session, library)
    await db_session.refresh(media)
    assert media.deleted_at is None


async def test_profile_cannot_take_another_users_email(client, auth_headers, admin_user):
    response = await client.patch("/api/v1/users/me", headers=auth_headers, json={"email": admin_user.email})
    assert response.status_code == 400
