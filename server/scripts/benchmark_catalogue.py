"""Compare actual catalogue routes against a Git baseline on synthetic SQLite data.

Run from server: uv run python -m scripts.benchmark_catalogue --output /tmp/catalogue.json
No library scan, media file, FFmpeg process, or production database is used.
"""

import argparse
import asyncio
import importlib.util
import json
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import get_session
from app.models import (
    AudioTrack,
    Base,
    Library,
    MediaFile,
    MediaView,
    RecommendationRow,
    SubtitleTrack,
    User,
    VideoTrack,
)
from app.routers.v1.media import router as current_router
from app.services.auth import create_access_token


def baseline_router(reference: str):
    """Execute the requested, locally available repository revision in isolation."""
    source = subprocess.run(
        ["git", "show", f"{reference}:server/app/routers/v1/media.py"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    spec = importlib.util.spec_from_loader("ferelix_catalogue_baseline", loader=None)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    exec(compile(source, f"{reference}:media.py", "exec"), module.__dict__)
    return module.router


async def seed(engine, media_count: int, row_count: int) -> None:
    now = datetime(2026, 11, 7)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await connection.execute(insert(User), [{"id": 1, "username": "benchmark", "username_normalized": "benchmark"}])
        await connection.execute(
            insert(Library), [{"id": 1, "path": "/synthetic/films", "name": "Films", "enabled": True}]
        )
        for start in range(1, media_count + 1, 1000):
            ids = range(start, min(start + 1000, media_count + 1))
            await connection.execute(
                insert(MediaFile),
                [
                    {
                        "id": index,
                        "file_path": f"/synthetic/films/Film {index:05}.mkv",
                        "file_name": f"Film {index:05}.mkv",
                        "file_size": 8_000_000_000,
                        "file_extension": ".mkv",
                        "duration": 7200,
                        "width": 1920,
                        "height": 1080,
                        "codec": "h264",
                        "bitrate": 8_000_000,
                        "created_at": now,
                        "updated_at": now,
                        "scanned_at": now,
                    }
                    for index in ids
                ],
            )
            await connection.execute(
                insert(VideoTrack),
                [
                    {
                        "media_file_id": index,
                        "stream_index": 0,
                        "codec": "h264",
                        "width": 1920,
                        "height": 1080,
                        "bitrate": 7_000_000,
                        "fps": 24,
                        "profile": "High",
                        "pixel_format": "yuv420p",
                        "is_default": True,
                    }
                    for index in ids
                ],
            )
            await connection.execute(
                insert(AudioTrack),
                [
                    {
                        "media_file_id": index,
                        "stream_index": track + 1,
                        "codec": "aac",
                        "channels": 6,
                        "sample_rate": 48000,
                        "bitrate": 384000,
                        "language": language,
                        "is_default": track == 0,
                    }
                    for index in ids
                    for track, language in enumerate(("fr", "en"))
                ],
            )
            await connection.execute(
                insert(SubtitleTrack),
                [
                    {"media_file_id": index, "stream_index": track + 3, "codec": "subrip", "language": language}
                    for index in ids
                    for track, language in enumerate(("fr", "en", "es"))
                ],
            )
            await connection.execute(
                insert(MediaView),
                [
                    {"media_file_id": index, "user_id": 1, "position_seconds": 1200, "duration_seconds": 7200}
                    for index in ids
                    if index % 3 == 0
                ],
            )
        await connection.execute(
            insert(RecommendationRow),
            [
                {
                    "library_id": 1,
                    "name": f"Row {index:02}",
                    "visible_on_homepage": True,
                    "filter_criteria": {"order_by": "file_name", "order": "ASC", "limit": 24, "offset": index * 24},
                }
                for index in range(row_count)
            ],
        )


async def benchmark(args) -> dict:
    with tempfile.TemporaryDirectory(prefix="ferelix-catalogue-") as directory:
        engine = create_async_engine(f"sqlite+aiosqlite:///{Path(directory) / 'benchmark.db'}")
        await seed(engine, args.media, args.rows)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        async def sessions():
            async with factory() as session:
                yield session

        query_count = 0

        def record(_connection, _cursor, _statement, _parameters, _context, _executemany):
            nonlocal query_count
            query_count += 1

        event.listen(engine.sync_engine, "before_cursor_execute", record)
        clients = {}
        for name, router in (("before", baseline_router(args.baseline)), ("after", current_router)):
            application = FastAPI()
            application.include_router(router)
            application.dependency_overrides[get_session] = sessions
            clients[name] = AsyncClient(
                transport=ASGITransport(app=application),
                base_url="http://benchmark",
                headers={"Authorization": f"Bearer {create_access_token({'sub': '1'})}"},
            )
        results = {}
        try:
            for endpoint in ("/api/v1/media-files?limit=48", "/api/v1/homepage/rows"):
                samples = {name: [] for name in clients}
                item_ids = {}
                for repeat in range(args.repeats + 1):
                    for name, client in clients.items():
                        query_count = 0
                        started = time.perf_counter()
                        response = await client.get(endpoint)
                        elapsed = (time.perf_counter() - started) * 1000
                        response.raise_for_status()
                        data = response.json()
                        # The baseline runs its original routes with current ORM models;
                        # exclude the two new detail-only fields from baseline byte counts.
                        if name == "before":
                            cards = (
                                [card for row in data for card in row["items"]] if endpoint.endswith("rows") else data
                            )
                            for card in cards:
                                card.pop("last_scan_attempt_at", None)
                                card.pop("scan_error", None)
                        item_ids[name] = (
                            [[card["id"] for card in row["items"]] for row in data]
                            if endpoint.endswith("rows")
                            else [card["id"] for card in data]
                        )
                        size = len(json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode())
                        if repeat:
                            samples[name].append({
                                "sql_queries": query_count,
                                "json_bytes": size,
                                "elapsed_ms": elapsed,
                            })
                assert item_ids["before"] == item_ids["after"], (
                    "Compared pages must contain the same media in the same order"
                )
                results[endpoint] = {
                    name: {
                        "sql_queries": trials[0]["sql_queries"],
                        "json_bytes": trials[0]["json_bytes"],
                        "median_ms": round(statistics.median(trial["elapsed_ms"] for trial in trials), 3),
                        "samples_ms": [round(trial["elapsed_ms"], 3) for trial in trials],
                    }
                    for name, trials in samples.items()
                }
        finally:
            for client in clients.values():
                await client.aclose()
            await engine.dispose()
        return {
            "baseline": args.baseline,
            "media": args.media,
            "homepage_rows": args.rows,
            "tracks_per_media": {"video": 1, "audio": 2, "subtitles": 3},
            "repeats": args.repeats,
            "method": "Actual authenticated ASGI routes, disk SQLite, warm-cache alternating before/after; SQL includes auth; no network or FFmpeg",
            "limitations": "Synthetic metadata, timing includes current runtime/models. Two new diagnostic fields removed from baseline JSON byte count. Not a production latency or CPU estimate.",
            "results": results,
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", default="db5fede")
    parser.add_argument("--media", type=int, default=10000)
    parser.add_argument("--rows", type=int, default=20)
    parser.add_argument("--repeats", type=int, default=7)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    if min(arguments.media, arguments.rows, arguments.repeats) < 1:
        parser.error("media, rows, and repeats must be positive")
    report = json.dumps(asyncio.run(benchmark(arguments)), indent=2)
    if arguments.output:
        arguments.output.write_text(report + "\n")
    print(report)
