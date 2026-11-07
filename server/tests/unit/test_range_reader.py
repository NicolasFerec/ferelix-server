"""Exact HTTP byte-range delivery, including partial final chunks and disconnects."""

from pathlib import Path

import pytest

from app.services.streaming_io import range_reader


@pytest.mark.parametrize("start,end", [(0, 799_999), (17, 600_012), (799_999, 799_999), (100, 99)])
async def test_delivers_only_requested_bytes(tmp_path: Path, start: int, end: int) -> None:
    contents = bytes(range(256)) * 3125
    source = tmp_path / "movie.mkv"
    source.write_bytes(contents)

    received = b"".join([chunk async for chunk in range_reader(source, start, end)])

    assert received == contents[start : end + 1]


async def test_truncated_file_stops_at_eof(tmp_path: Path) -> None:
    source = tmp_path / "movie.mkv"
    source.write_bytes(b"short")

    assert b"".join([chunk async for chunk in range_reader(source, 0, 1000)]) == b"short"


async def test_reader_can_close_after_first_chunk(tmp_path: Path) -> None:
    source = tmp_path / "movie.mkv"
    source.write_bytes(b"a" * 800_000)
    reader = range_reader(source, 0, 799_999)

    assert await anext(reader)
    await reader.aclose()

    with pytest.raises(StopAsyncIteration):
        await anext(reader)
