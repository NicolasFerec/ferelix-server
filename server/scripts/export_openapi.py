#!/usr/bin/env python
"""Export OpenAPI schema to JSON file."""

import json
import sys
from pathlib import Path

from app.main import app


def main():
    output_path = Path(__file__).parent.parent.parent / "web" / "src" / "api" / "openapi.json"
    new_content = json.dumps(app.openapi(), indent=2) + "\n"

    if output_path.exists():
        old_content = output_path.read_text()
        if old_content == new_content:
            print("OpenAPI schema is up to date")
            return 0

    output_path.write_text(new_content)
    print(f"OpenAPI schema exported to {output_path}")
    return 1  # Signal that file was modified


if __name__ == "__main__":
    sys.exit(main())
