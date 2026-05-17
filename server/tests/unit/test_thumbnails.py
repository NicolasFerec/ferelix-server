"""Unit tests for thumbnail helper behavior."""

from pathlib import Path

from app.services.thumbnails import screenshot_timestamp, thumbnail_path_for_media


def test_screenshot_timestamp_uses_middle_frame_for_short_media() -> None:
    assert screenshot_timestamp(20.0) == 7.0


def test_screenshot_timestamp_avoids_start_and_credits_for_long_media() -> None:
    assert screenshot_timestamp(7200.0) == 1440.0


def test_thumbnail_path_is_deterministic(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FERELIX_THUMBNAIL_DIR", str(tmp_path))

    first_path = thumbnail_path_for_media("/media/movie.mkv")
    second_path = thumbnail_path_for_media("/media/movie.mkv")

    assert first_path == second_path
    assert first_path.parent == tmp_path
    assert first_path.suffix == ".jpg"
