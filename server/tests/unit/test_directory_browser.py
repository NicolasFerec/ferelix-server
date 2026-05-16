"""Tests for dashboard directory browsing helpers."""

import pytest
from fastapi import HTTPException, status

from app.services.directory_browser import browse_directory_items


def test_browse_directory_items_sorts_directories_before_files(tmp_path) -> None:
    (tmp_path / "z-file.txt").write_text("content")
    (tmp_path / "a-dir").mkdir()
    (tmp_path / ".hidden").write_text("hidden")

    items = browse_directory_items(str(tmp_path))

    assert [item.name for item in items] == ["a-dir", "z-file.txt"]
    assert items[0].is_directory is True
    assert items[1].is_directory is False


def test_browse_directory_items_rejects_missing_path(tmp_path) -> None:
    with pytest.raises(HTTPException) as exc_info:
        browse_directory_items(str(tmp_path / "missing"))

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


def test_browse_directory_items_rejects_file_path(tmp_path) -> None:
    file_path = tmp_path / "file.txt"
    file_path.write_text("content")

    with pytest.raises(HTTPException) as exc_info:
        browse_directory_items(str(file_path))

    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
