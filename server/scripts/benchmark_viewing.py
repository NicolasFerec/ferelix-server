"""Current viewing/catalogue costs on disposable synthetic SQLite data; no FFmpeg or network.

uv run python -m scripts.benchmark_viewing --output /tmp/viewing.json
"""

import argparse
import asyncio
import json
import math
import statistics
import tempfile
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import get_session
from app.models import Base, Library, MediaFile, MediaView, PlaybackSession, Settings, User
from app.models.metadata import MediaItem, MediaItemFile, UserItemState
from app.routers.v1 import items, streaming, viewing
from app.services.auth import create_access_token
from app.services.catalogue import media_card, media_card_query, visible_media_filter
from app.services.item_catalogue import enrich_file_cards, item_cards


async def seed(engine, series_count: int, episodes: int, movies: int) -> list[int]:
    now = datetime.now(UTC).replace(tzinfo=None)
    metadata, files, links, states, views = [], [], [], [], []
    episode_start = series_count * 2 + 1
    movie_start = episode_start + series_count * episodes
    resume_episode = min(13, episodes)
    for index in range(series_count):
        series_id, season_id = index + 1, series_count + index + 1
        common = {
            "metadata_library_id": 1,
            "hierarchy_complete": True,
            "order_confirmed": True,
            "metadata_status": "ready",
            "release_date": date(2020, 1, 1),
            "first_available_at": now - timedelta(days=180),
            "overview": "Synthetic synopsis. " * 30,
            "credits": [{"name": f"Actor {number}", "role": "cast"} for number in range(10)],
        }
        metadata.extend((
            {**common, "id": series_id, "kind": "series", "title": f"Series {series_id:04}"},
            {
                **common,
                "id": season_id,
                "kind": "season",
                "title": "Season 1",
                "parent_id": series_id,
                "series_id": series_id,
                "season_number": 1,
            },
        ))
        for number in range(1, episodes + 1):
            item_id, file_id = episode_start + index * episodes + number - 1, index * episodes + number
            metadata.append({
                **common,
                "id": item_id,
                "kind": "episode",
                "title": f"Episode {number:02}",
                "parent_id": season_id,
                "series_id": series_id,
                "season_number": 1,
                "episode_number": number,
            })
            files.append(_file(file_id, 3600, now))
            links.append({"item_id": item_id, "media_file_id": file_id})
            watched = number < resume_episode
            resume = number == resume_episode and index % 4 == 0
            if watched or resume:
                activity = now - timedelta(days=index)
                states.append({
                    "user_id": 1,
                    "item_id": item_id,
                    "watched": watched,
                    "state_revision": 1,
                    "last_activity_at": activity,
                    "watched_at": activity if watched else None,
                })
                views.append(_view(file_id, 3600, watched, resume, activity))
    for index in range(movies):
        item_id, file_id = movie_start + index, series_count * episodes + index + 1
        metadata.append({
            "id": item_id,
            "kind": "movie",
            "title": f"Film {index:05}",
            "metadata_library_id": 1,
            "metadata_status": "ready",
            "release_date": date(2000 + index % 20, 1, 1),
            "overview": "Synthetic synopsis. " * 30,
            "credits": [{"name": f"Actor {number}", "role": "cast"} for number in range(10)],
        })
        files.append(_file(file_id, 7200, now))
        links.append({"item_id": item_id, "media_file_id": file_id})
        watched, resume = index % 4 == 1, index % 4 == 0
        if watched or resume:
            activity = now - timedelta(days=index % 30)
            states.append({
                "user_id": 1,
                "item_id": item_id,
                "watched": watched,
                "state_revision": 1,
                "last_activity_at": activity,
                "watched_at": activity if watched else None,
            })
            views.append(_view(file_id, 7200, watched, resume, activity))
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await connection.execute(insert(User), [{"id": 1, "username": "benchmark", "username_normalized": "benchmark"}])
        await connection.execute(
            insert(Library), [{"id": 1, "path": "/synthetic", "name": "Synthetic", "enabled": True}]
        )
        await connection.execute(insert(Settings), [{"id": 1}])
        # Core executemany needs a consistent set of keys per batch.
        for table, rows in (
            (MediaItem, metadata),
            (MediaFile, files),
            (MediaItemFile, links),
            (UserItemState, states),
            (MediaView, views),
        ):
            keys = set().union(*(row.keys() for row in rows))
            normalized = [{key: row.get(key) for key in keys} for row in rows]
            # Optional per-kind fields are nullable; keep non-null defaults out of
            # batches instead of overriding them with None on another item kind.
            if table is MediaItem:
                for row in normalized:
                    for key in ("hierarchy_complete", "order_confirmed"):
                        row[key] = bool(row.get(key))
            for offset in range(0, len(normalized), 500):
                await connection.execute(insert(table), normalized[offset : offset + 500])
        await connection.execute(
            insert(PlaybackSession),
            [
                {
                    "id": "benchmark-playback",
                    "user_id": 1,
                    "media_file_id": resume_episode,
                    "item_id": episode_start + resume_episode - 1,
                    "state_revision": 1,
                    "duration_seconds": 3600,
                    "position_seconds": 900,
                }
            ],
        )
    return list(range(movie_start, movie_start + min(50, movies)))


def _file(id_: int, duration: int, now: datetime) -> dict:
    return {
        "id": id_,
        "file_path": f"/synthetic/Media {id_:05}.mkv",
        "file_name": f"Media {id_:05}.mkv",
        "file_extension": ".mkv",
        "file_size": 4_000_000_000,
        "duration": duration,
        "width": 1920,
        "height": 1080,
        "codec": "h264",
        "bitrate": 8_000_000,
        "created_at": now,
    }


def _view(file_id: int, duration: int, watched: bool, resume: bool, activity: datetime) -> dict:
    return {
        "user_id": 1,
        "media_file_id": file_id,
        "watched": watched,
        "resume_active": resume,
        "state_revision": 1,
        "position_seconds": duration if watched else 900,
        "duration_seconds": duration,
        "last_viewed_at": activity,
    }


async def benchmark(args) -> dict:
    with tempfile.TemporaryDirectory(prefix="ferelix-viewing-") as directory:
        engine = create_async_engine(f"sqlite+aiosqlite:///{Path(directory) / 'benchmark.db'}")
        try:
            card_ids = await seed(engine, args.series, args.episodes, args.movies)
            factory = async_sessionmaker(engine, expire_on_commit=False)

            async def sessions():
                async with factory() as session:
                    yield session

            app = FastAPI()
            app.include_router(viewing.router)
            app.include_router(streaming.router)
            app.include_router(items.router)
            app.dependency_overrides[get_session] = sessions
            count = 0

            def record(_conn, _cursor, _statement, _parameters, _context, _many):
                nonlocal count
                count += 1

            event.listen(engine.sync_engine, "before_cursor_execute", record)
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://benchmark",
                headers={"Authorization": f"Bearer {create_access_token({'sub': '1'})}"},
            ) as client:
                pulse = 900

                async def get(path):
                    response = await client.get(path)
                    response.raise_for_status()
                    return response.json()

                async def heartbeat():
                    nonlocal pulse
                    pulse += 1
                    response = await client.post(
                        "/api/v1/playback-sessions/benchmark-playback/heartbeat",
                        json={"position_seconds": pulse, "duration_seconds": 3600},
                    )
                    response.raise_for_status()
                    assert response.json()["session"]["position_seconds"] == pulse
                    return [response.json()]

                async def cards(number):
                    async with factory() as session:
                        return await item_cards(session, 1, card_ids[:number])

                async def legacy(enrich):
                    async with factory() as session:
                        rows = await session.execute(
                            media_card_query(1).where(visible_media_filter()).order_by(MediaFile.id).limit(50)
                        )
                        result = [media_card(*row) for row in rows]
                        return await enrich_file_cards(session, 1, result) if enrich else result

                operations = {
                    "http_resume_50": lambda: get("/api/v1/items/resume?limit=50"),
                    "http_next_up_50": lambda: get("/api/v1/items/next-up?limit=50"),
                    "http_heartbeat": heartbeat,
                    "item_cards_1": lambda: cards(1),
                    "item_cards_50": lambda: cards(50),
                    "http_list_items_50": lambda: get("/api/v1/items?limit=50"),
                    "legacy_cards_50_without_metadata": lambda: legacy(False),
                    "legacy_cards_50_with_metadata": lambda: legacy(True),
                }
                results = {}
                for name, operation in operations.items():
                    rows = await operation()  # Warm SQL compilation and filesystem caches once per operation.
                    samples, queries = [], []
                    cpu_started = time.process_time()
                    for _ in range(args.iterations):
                        count = 0
                        started = time.perf_counter()
                        rows = await operation()
                        samples.append((time.perf_counter() - started) * 1000)
                        queries.append(count)
                    results[name] = {
                        "p50_ms": round(statistics.median(samples), 3),
                        "p95_ms": round(sorted(samples)[math.ceil(len(samples) * 0.95) - 1], 3),
                        "sql_count_min": min(queries),
                        "sql_count_max": max(queries),
                        "returned_rows": len(rows),
                        "cpu_ms_total": round((time.process_time() - cpu_started) * 1000, 3),
                    }
                return {
                    "dataset": {"series": args.series, "episodes_per_series": args.episodes, "movies": args.movies},
                    "iterations": args.iterations,
                    "warmups_per_operation": 1,
                    "p95_method": "nearest_rank",
                    "notes": [
                        "Current implementation only; not a historical before/after comparison.",
                        "http_* includes ASGI, authentication and response serialization; other samples are service calls.",
                        "Legacy with/without metadata isolates current enrichment overhead on identical fixtures.",
                        "Temporary SQLite database; synthetic paths; no FFmpeg, networking, scans or production database.",
                    ],
                    "measurements": results,
                }
        finally:
            await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--series", type=int, default=100)
    parser.add_argument("--episodes", type=int, default=24)
    parser.add_argument("--movies", type=int, default=1000)
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--output", type=Path, default=Path("/tmp/viewing-benchmark.json"))
    args = parser.parse_args()
    if min(args.series, args.episodes, args.movies, args.iterations) < 1:
        parser.error("All counts must be positive")
    result = asyncio.run(benchmark(args))
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
