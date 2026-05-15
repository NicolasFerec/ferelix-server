"""Filesystem browsing helpers used by the admin dashboard."""

import contextlib
from pathlib import Path

from fastapi import HTTPException, status
from pydantic import BaseModel


class DirectoryItem(BaseModel):
    """Schema for directory browser items."""

    name: str
    path: str
    is_directory: bool
    is_symlink: bool = False
    symlink_target: str | None = None


def browse_directory_items(path: str) -> list[DirectoryItem]:
    """Return visible filesystem entries for a directory, sorted for display."""
    try:
        dir_path = validate_directory_path(path)
        current_real_path = dir_path.resolve()
        visited_resolved_paths = parent_resolved_paths(current_real_path)

        items = [
            item
            for child_path in dir_path.iterdir()
            if (item := directory_item_from_path(child_path, current_real_path, visited_resolved_paths)) is not None
        ]
        items.sort(key=lambda item: (not item.is_directory, item.name.lower()))
        return items
    except HTTPException:
        raise
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Permission denied: {path}",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error browsing directory: {exc!s}",
        ) from exc


def validate_directory_path(path: str) -> Path:
    dir_path = Path(path)
    if not dir_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Path does not exist: {path}",
        )
    if not dir_path.is_dir():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Path is not a directory: {path}",
        )
    return dir_path


def parent_resolved_paths(current_real_path: Path) -> set[str]:
    visited_resolved_paths: set[str] = set()
    path_parts = str(current_real_path).split("/")

    for i in range(1, len(path_parts) + 1):
        path_to_check = "/" + "/".join(path_parts[1:i])
        with contextlib.suppress(OSError, RuntimeError):
            visited_resolved_paths.add(str(Path(path_to_check).resolve()))

    return visited_resolved_paths


def directory_item_from_path(
    path: Path,
    current_real_path: Path,
    visited_resolved_paths: set[str],
) -> DirectoryItem | None:
    if path.name.startswith("."):
        return None

    is_symlink = path.is_symlink()
    symlink_target = None

    if is_symlink:
        try:
            resolved_path = path.resolve()
            symlink_target = str(resolved_path)
        except OSError, RuntimeError:
            return None

        if symlink_creates_loop(resolved_path, current_real_path, visited_resolved_paths):
            return None

    return DirectoryItem(
        name=path.name,
        path=str(path.absolute()),
        is_directory=path.is_dir(),
        is_symlink=is_symlink,
        symlink_target=symlink_target,
    )


def symlink_creates_loop(
    resolved_path: Path,
    current_real_path: Path,
    visited_resolved_paths: set[str],
) -> bool:
    symlink_target = str(resolved_path)
    return (
        symlink_target in visited_resolved_paths
        or resolved_path == current_real_path
        or str(current_real_path).startswith(f"{symlink_target}/")
    )
