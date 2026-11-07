"""Bounded discovery query and concurrent-watchlist checks on 10,000 synthetic films.

Run: uv run python -m scripts.benchmark_discovery --output /tmp/discovery.json
Uses a temporary SQLite database; no library scanning or FFmpeg work.
"""

import argparse
import asyncio
import json
import statistics
import tempfile
import time
from pathlib import Path

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import get_session
from app.models import WatchlistEntry
from app.routers.v1.media import router
from app.services.auth import create_access_token
from scripts.benchmark_catalogue import seed


async def measure() -> dict:
    with tempfile.TemporaryDirectory(prefix="ferelix-discovery-") as directory:
        engine = create_async_engine(f"sqlite+aiosqlite:///{Path(directory) / 'discovery.db'}")
        await seed(engine, media_count=10000, row_count=1)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        async def sessions():
            async with factory() as session:
                yield session

        query_count = 0

        def count(_connection, _cursor, _statement, _parameters, _context, _executemany):
            nonlocal query_count
            query_count += 1

        event.listen(engine.sync_engine, "before_cursor_execute", count)
        application = FastAPI()
        application.include_router(router)
        application.dependency_overrides[get_session] = sessions
        headers = {"Authorization": f"Bearer {create_access_token({'sub': '1'})}"}
        results = {}
        try:
            async with AsyncClient(
                transport=ASGITransport(app=application), base_url="http://benchmark", headers=headers
            ) as client:
                first = await client.get("/api/v1/media-files?limit=49")
                first.raise_for_status()
                assert 10000 not in [card["id"] for card in first.json()]
                for query in ("Film 10000", "Film"):
                    elapsed = []
                    counts = []
                    sizes = []
                    ids = []
                    for repeat in range(8):
                        query_count = 0
                        started = time.perf_counter()
                        response = await client.get("/api/v1/media-files/search", params={"q": query, "limit": 49})
                        milliseconds = (time.perf_counter() - started) * 1000
                        response.raise_for_status()
                        ids = [card["id"] for card in response.json()]
                        if repeat:
                            elapsed.append(round(milliseconds, 3))
                            counts.append(query_count)
                            sizes.append(len(response.content))
                    results[query] = {
                        "sql_queries": counts,
                        "json_bytes": sizes[0],
                        "returned_ids": ids,
                        "median_ms": statistics.median(elapsed),
                        "samples_ms": elapsed,
                    }
                assert results["Film 10000"]["returned_ids"] == [10000]
                responses = await asyncio.gather(*[client.put("/api/v1/users/me/watchlist/10000") for _ in range(8)])
                async with factory() as session:
                    entries = await session.scalar(select(func.count()).select_from(WatchlistEntry))
                assert [response.status_code for response in responses] == [200] * 8
                assert entries == 1
                query_count = 0
                saved = await client.get("/api/v1/users/me/watchlist?limit=49")
                saved.raise_for_status()
                watchlist = {
                    "concurrent_put_statuses": [response.status_code for response in responses],
                    "persisted_entries": entries,
                    "list_sql_queries": query_count,
                    "list_json_bytes": len(saved.content),
                    "in_watchlist": saved.json()[0]["in_watchlist"],
                }
        finally:
            await engine.dispose()
        return {
            "media_count": 10000,
            "method": "Authenticated ASGI routes, temporary disk SQLite, one warm-up plus seven samples; SQL includes authentication",
            "limitations": "Synthetic metadata and local latency only; no previous search API to compare, no CPU claim. Separate-connection API test also synchronizes eight concurrent adds.",
            "search": results,
            "watchlist": watchlist,
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    content = json.dumps(asyncio.run(measure()), indent=2)
    if args.output:
        args.output.write_text(content + "\n")
    print(content)
