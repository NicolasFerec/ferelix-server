"""Version information module for Ferelix server.

This module provides version information by trying git commands first (for local dev),
then falling back to a version.json file (for production Docker builds).
"""

import json
import subprocess
from pathlib import Path


def get_version_info() -> dict[str, str]:
    """Get version info: try git commands first, fallback to version.json file.

    Returns:
        Dictionary with 'commit' and 'branch' keys. Values are 'unknown' if
        git is unavailable and no version.json file exists.
    """
    # Try git commands (works in local dev)
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return {"commit": commit, "branch": branch}
    except subprocess.CalledProcessError, FileNotFoundError:
        pass

    # Fallback to version.json (generated at build time in CI/CD)
    # version.json is copied to /app/version.json in Docker container
    # Since WORKDIR is /app, we can use cwd() or check relative to __file__
    # Try multiple possible locations for robustness
    possible_paths = [
        Path.cwd() / "version.json",  # /app/version.json (most reliable for Docker)
        Path(__file__).parent.parent
        / "version.json",  # /app/version.json if __file__ is /app/app/version.py
        Path(__file__).parent / "version.json",  # Fallback if structure differs
    ]

    for version_file in possible_paths:
        if version_file.exists():
            try:
                with open(version_file) as f:
                    return json.load(f)
            except OSError, json.JSONDecodeError:
                continue

    # Final fallback
    return {"commit": "unknown", "branch": "unknown"}
