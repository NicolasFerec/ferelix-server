"""Unit tests for library scanner change detection."""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Library, MediaFile
from app.services.scanner import scan_library_path


def _write_media_file(path: Path, content: bytes = b"video") -> None:
    path.write_bytes(content)


async def _create_library(db_session: AsyncSession, path: Path) -> Library:
    library = Library(name="Movies", path=str(path), library_type="movie", enabled=True)
    db_session.add(library)
    await db_session.commit()
    await db_session.refresh(library)
    return library


async def _create_media_file(db_session: AsyncSession, file_path: Path, **overrides: object) -> MediaFile:
    file_stat = file_path.stat()
    values = {
        "file_path": str(file_path),
        "file_name": file_path.name,
        "file_size": file_stat.st_size,
        "file_extension": file_path.suffix,
        "duration": 120.0,
        "width": 1920,
        "height": 1080,
        "codec": "h264",
        "bitrate": 4_000_000,
        "scanned_at": datetime.now(UTC),
    }
    values.update(overrides)
    media_file = MediaFile(**values)
    db_session.add(media_file)
    await db_session.commit()
    await db_session.refresh(media_file)
    return media_file


@pytest.mark.asyncio
async def test_scan_skips_metadata_and_thumbnail_for_unchanged_existing_file(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    media_path = tmp_path / "movie.mkv"
    _write_media_file(media_path)
    library = await _create_library(db_session, tmp_path)
    media_file = await _create_media_file(db_session, media_path)

    with (
        patch("app.services.scanner.extract_video_metadata") as extract_metadata,
        patch("app.services.scanner.generate_video_thumbnail") as generate_thumbnail,
    ):
        stats = await scan_library_path(db_session, library)

    await db_session.refresh(media_file)

    assert stats == {"new": 0, "updated": 0, "deleted": 0, "restored": 0, "cancelled": False}
    extract_metadata.assert_not_called()
    generate_thumbnail.assert_not_called()
    assert media_file.file_modified_at is not None


@pytest.mark.asyncio
async def test_scan_reextracts_metadata_and_regenerates_thumbnail_for_changed_file(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    media_path = tmp_path / "movie.mkv"
    _write_media_file(media_path)
    library = await _create_library(db_session, tmp_path)
    media_file = await _create_media_file(
        db_session,
        media_path,
        file_size=1,
        file_modified_at=datetime.fromtimestamp(1, UTC).replace(tzinfo=None),
        thumbnail_path=str(tmp_path / "old.jpg"),
    )
    metadata = {
        "duration": 240.0,
        "width": 3840,
        "height": 2160,
        "codec": "hevc",
        "bitrate": 8_000_000,
        "video_tracks": [],
        "audio_tracks": [],
        "subtitle_tracks": [],
    }

    with (
        patch("app.services.scanner.extract_video_metadata", return_value=metadata) as extract_metadata,
        patch(
            "app.services.scanner.generate_video_thumbnail", return_value=str(tmp_path / "new.jpg")
        ) as generate_thumbnail,
    ):
        stats = await scan_library_path(db_session, library)

    await db_session.refresh(media_file)

    assert stats["updated"] == 1
    extract_metadata.assert_called_once_with(media_path)
    generate_thumbnail.assert_called_once_with(media_path, 240.0, force=True)
    assert media_file.file_size == media_path.stat().st_size
    assert media_file.duration == 240.0
    assert media_file.width == 3840
    assert media_file.height == 2160
    assert media_file.codec == "hevc"
    assert media_file.bitrate == 8_000_000
    assert media_file.thumbnail_path == str(tmp_path / "new.jpg")


@pytest.mark.asyncio
async def test_scan_processes_existing_file_without_metadata(db_session: AsyncSession, tmp_path: Path) -> None:
    media_path = tmp_path / "movie.mkv"
    _write_media_file(media_path)
    library = await _create_library(db_session, tmp_path)
    media_file = await _create_media_file(
        db_session,
        media_path,
        duration=None,
        width=None,
        height=None,
        codec=None,
        bitrate=None,
    )
    metadata = {
        "duration": 90.0,
        "width": 1280,
        "height": 720,
        "codec": "h264",
        "bitrate": 2_000_000,
        "video_tracks": [],
        "audio_tracks": [],
        "subtitle_tracks": [],
    }

    with (
        patch("app.services.scanner.extract_video_metadata", return_value=metadata) as extract_metadata,
        patch("app.services.scanner.generate_video_thumbnail", return_value=None) as generate_thumbnail,
    ):
        stats = await scan_library_path(db_session, library)

    await db_session.refresh(media_file)

    assert stats["updated"] == 1
    extract_metadata.assert_called_once_with(media_path)
    generate_thumbnail.assert_called_once_with(media_path, 90.0, force=False)
    assert media_file.duration == 90.0
