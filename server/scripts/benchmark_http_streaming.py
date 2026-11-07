"""Measure authenticated direct streaming over HTTP, without starting FFmpeg.

Export FERELIX_BENCHMARK_TOKEN, then run from server:
uv run python -m scripts.benchmark_http_streaming --media-id 1 --server-pid PID
Uses Linux /proc to measure CPU of the server process, excluding the HTTP client.
"""

import argparse
import asyncio
import json
import os
import statistics
import time
from pathlib import Path

import httpx


def server_cpu_seconds(pid: int) -> float:
    # comm may contain spaces, so split fields only after its closing parenthesis.
    fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    return (int(fields[11]) + int(fields[12])) / os.sysconf("SC_CLK_TCK")


async def benchmark(url: str, media_id: int, pid: int, byte_count: int, iterations: int) -> dict:
    if byte_count <= 0 or iterations <= 0:
        raise ValueError("Bytes and iterations must be positive")
    token = os.environ["FERELIX_BENCHMARK_TOKEN"]
    samples = []
    async with httpx.AsyncClient(base_url=url, headers={"Authorization": f"Bearer {token}"}, timeout=30) as client:
        created = await client.post("/api/v1/playback-sessions", json={"media_file_id": media_id})
        created.raise_for_status()
        session_id = created.json()["id"]
        try:
            for iteration in range(iterations + 1):
                cpu_start, wall_start = server_cpu_seconds(pid), time.perf_counter()
                received = 0
                async with client.stream(
                    "GET",
                    f"/api/v1/stream/{media_id}",
                    params={"session_id": session_id},
                    headers={"Range": f"bytes=0-{byte_count - 1}"},
                ) as response:
                    response.raise_for_status()
                    if response.status_code != 206:
                        raise RuntimeError("Expected HTTP 206 Partial Content")
                    async for chunk in response.aiter_bytes():
                        received += len(chunk)
                wall_seconds = time.perf_counter() - wall_start
                cpu_seconds = server_cpu_seconds(pid) - cpu_start
                if received != byte_count:
                    raise RuntimeError(f"Expected {byte_count} bytes, received {received}")
                if iteration:  # First download warms the page cache and connection.
                    samples.append({"wall_seconds": wall_seconds, "server_cpu_seconds": cpu_seconds, "bytes": received})
        finally:
            stopped = await client.delete(f"/api/v1/playback-sessions/{session_id}")
            stopped.raise_for_status()
    return {
        "mode": "HTTP range with one unmeasured warmup",
        "samples": samples,
        "median_wall_seconds": statistics.median(sample["wall_seconds"] for sample in samples),
        "median_server_cpu_seconds": statistics.median(sample["server_cpu_seconds"] for sample in samples),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8005")
    parser.add_argument("--media-id", type=int, required=True)
    parser.add_argument("--server-pid", type=int, required=True)
    parser.add_argument("--bytes", type=int, default=128 * 1024 * 1024)
    parser.add_argument("--iterations", type=int, default=7)
    args = parser.parse_args()
    print(
        json.dumps(
            asyncio.run(benchmark(args.url, args.media_id, args.server_pid, args.bytes, args.iterations)), indent=2
        )
    )


if __name__ == "__main__":
    main()
