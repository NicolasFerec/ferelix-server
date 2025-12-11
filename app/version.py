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
    version_file = Path(__file__).parent.parent / "version.json"
    if version_file.exists():
        try:
            with open(version_file) as f:
                return json.load(f)
        except OSError, json.JSONDecodeError:
            pass

    # Final fallback
    return {"commit": "unknown", "branch": "unknown"}
