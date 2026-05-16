"""Tests for streaming I/O helpers."""

import pytest
from fastapi import HTTPException, status

from app.services.streaming_io import (
    append_api_key_to_playlist_segments,
    first_playlist_segment,
    is_playlist_ready,
    parse_range_header,
)


def test_parse_range_header_full_file_when_missing() -> None:
    assert parse_range_header(None, 1000) == (0, 999, False)


def test_parse_range_header_bounded_range() -> None:
    assert parse_range_header("bytes=100-199", 1000) == (100, 199, True)


def test_parse_range_header_open_ended_range() -> None:
    assert parse_range_header("bytes=900-", 1000) == (900, 999, True)


def test_parse_range_header_suffix_range() -> None:
    assert parse_range_header("bytes=-250", 1000) == (750, 999, True)


@pytest.mark.parametrize(
    "range_header",
    [
        "items=0-10",
        "bytes=900-100",
        "bytes=1000-1001",
        "bytes=0-1,10-11",
        "bytes=-0",
    ],
)
def test_parse_range_header_rejects_invalid_ranges(range_header: str) -> None:
    with pytest.raises(HTTPException) as exc_info:
        parse_range_header(range_header, 1000)

    assert exc_info.value.status_code == status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE
    assert exc_info.value.headers == {"Content-Range": "bytes */1000"}


def test_first_playlist_segment_ignores_tags() -> None:
    content = "#EXTM3U\n#EXT-X-VERSION:3\n#EXTINF:6.0,\nsegment_000.ts\n"

    assert first_playlist_segment(content) == "segment_000.ts"


def test_append_api_key_to_playlist_segments_rewrites_relative_segments() -> None:
    content = (
        '#EXTM3U\n#EXT-X-MAP:URI="init.mp4"\n#EXTINF:6.0,\nsegment_000.ts\n#EXTINF:6.0,\nsegment_001.ts?x=1\n/http.ts\n'
    )

    assert append_api_key_to_playlist_segments(content, "abc.def") == (
        "#EXTM3U\n"
        '#EXT-X-MAP:URI="init.mp4?api_key=abc.def"\n'
        "#EXTINF:6.0,\n"
        "segment_000.ts?api_key=abc.def\n"
        "#EXTINF:6.0,\n"
        "segment_001.ts?x=1&api_key=abc.def\n"
        "/http.ts\n"
    )


@pytest.mark.asyncio
async def test_is_playlist_ready_requires_manifest_and_first_segment(tmp_path) -> None:
    playlist = tmp_path / "playlist.m3u8"
    playlist.write_text("#EXTM3U\n#EXTINF:6.0,\nsegment_000.ts\n")

    assert await is_playlist_ready(playlist) is False

    (tmp_path / "segment_000.ts").write_bytes(b"data")

    assert await is_playlist_ready(playlist) is True
