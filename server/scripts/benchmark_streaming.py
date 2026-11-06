"""Measure direct-stream reader overhead against the same warm file range.

Run from server: uv run python -m scripts.benchmark_streaming /path/to/movie.mkv
No transcoding, database writes, or network requests are performed.
"""

import argparse
import asyncio
import json
import platform
import statistics
import time
from pathlib import Path

from app.services.streaming_io import range_reader


async def benchmark(path: Path, byte_count: int, iterations: int, chunk_sizes: list[int]) -> dict:
    byte_count = min(byte_count, (await asyncio.to_thread(path.stat)).st_size)
    if byte_count <= 0 or iterations <= 0 or any(size <= 0 for size in chunk_sizes):
        raise ValueError("File, byte count, iterations, and chunk sizes must be positive")

    samples: dict[int, list[dict]] = {size: [] for size in chunk_sizes}
    for iteration in range(iterations):
        # Alternate order to reduce systematic cache/CPU-frequency bias.
        ordered_sizes = chunk_sizes if iteration % 2 == 0 else list(reversed(chunk_sizes))
        for chunk_size in ordered_sizes:
            with path.open("rb") as source:
                remaining = byte_count
                while remaining:
                    data = source.read(min(1024 * 1024, remaining))
                    if not data:
                        raise RuntimeError("Input file changed during benchmark")
                    remaining -= len(data)

            chunks = total = 0
            cpu_start, wall_start = time.process_time(), time.perf_counter()
            async for chunk in range_reader(path, 0, byte_count - 1, chunk_size=chunk_size):
                total += len(chunk)
                chunks += 1
            wall_seconds = time.perf_counter() - wall_start
            cpu_seconds = time.process_time() - cpu_start
            if total != byte_count:
                raise RuntimeError(f"Expected {byte_count} bytes, read {total}")
            samples[chunk_size].append({"wall_seconds": wall_seconds, "cpu_seconds": cpu_seconds, "chunks": chunks})

    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "bytes_per_sample": byte_count,
        "iterations": iterations,
        "cache": "warm; same range before each sample",
        "results": [
            {
                "chunk_bytes": size,
                "median_wall_seconds": statistics.median(sample["wall_seconds"] for sample in rows),
                "median_cpu_seconds": statistics.median(sample["cpu_seconds"] for sample in rows),
                "samples": rows,
            }
            for size, rows in samples.items()
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--bytes", type=int, default=128 * 1024 * 1024)
    parser.add_argument("--iterations", type=int, default=7)
    parser.add_argument("--chunk-sizes", type=int, nargs="+", default=[8192, 65536, 262144])
    args = parser.parse_args()
    print(json.dumps(asyncio.run(benchmark(args.file, args.bytes, args.iterations, args.chunk_sizes)), indent=2))


if __name__ == "__main__":
    main()
