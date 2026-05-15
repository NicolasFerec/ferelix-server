"""I/O helpers for direct file streaming and generated HLS assets."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

import aiofiles
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TranscodingJob
from app.models.transcoding import TranscodingJobStatus

HLS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "*",
    "Cache-Control": "no-cache",
}

SEGMENT_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "*",
    "Cache-Control": "public, max-age=3600",
}

VIDEO_CONTENT_TYPES = {
    ".mp4": "video/mp4",
    ".mkv": "video/x-matroska",
    ".avi": "video/x-msvideo",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".m4v": "video/x-m4v",
}


def parse_range_header(range_header: str | None, file_size: int) -> tuple[int, int, bool]:
    """Parse a single HTTP byte range header."""
    if not range_header:
        return 0, file_size - 1, False

    if not range_header.startswith("bytes=") or "," in range_header:
        raise_invalid_range(file_size)

    start_text, separator, end_text = range_header.removeprefix("bytes=").partition("-")
    if not separator:
        raise_invalid_range(file_size)

    start = 0
    end = file_size - 1
    try:
        if start_text:
            start = int(start_text)
            end = int(end_text) if end_text else file_size - 1
        else:
            suffix_length = int(end_text)
            if suffix_length <= 0:
                raise ValueError
            start = max(file_size - suffix_length, 0)
            end = file_size - 1
    except ValueError:
        raise_invalid_range(file_size)

    if start < 0 or end < start or start >= file_size:
        raise_invalid_range(file_size)

    return start, min(end, file_size - 1), True


async def range_reader(file_path: Path, start: int, end: int, chunk_size: int = 8192):
    """Yield chunks from a byte range."""
    async with aiofiles.open(file_path, mode="rb") as f:
        await f.seek(start)
        remaining = end - start + 1

        while remaining > 0:
            data = await f.read(min(chunk_size, remaining))
            if not data:
                break
            remaining -= len(data)
            yield data


async def touch_job(session: AsyncSession, job: TranscodingJob) -> None:
    """Update a transcoding job heartbeat/access timestamp."""
    job.last_accessed_at = datetime.now(UTC)
    await session.commit()


async def wait_for_playlist(job: TranscodingJob, session: AsyncSession, timeout_seconds: float = 15.0) -> Path:
    """Wait briefly for ffmpeg to create a readable HLS playlist and first segment."""
    if not job.playlist_path:
        raise HTTPException(status_code=404, detail="Playlist path not set")

    playlist_path = Path(job.playlist_path)
    deadline = asyncio.get_running_loop().time() + timeout_seconds

    while asyncio.get_running_loop().time() < deadline:
        if await is_playlist_ready(playlist_path):
            return playlist_path

        await session.refresh(job)
        raise_if_job_failed(job)
        await asyncio.sleep(0.25)

    raise HTTPException(status_code=404, detail="Playlist not ready yet")


async def wait_for_segment(
    job: TranscodingJob,
    segment_num: int,
    session: AsyncSession,
    timeout_seconds: float = 20.0,
) -> Path:
    """Wait for a requested HLS segment to become readable."""
    if not job.output_path:
        raise HTTPException(status_code=404, detail="Job output path not set")

    segment_path = Path(job.output_path) / f"segment_{segment_num:03d}.ts"
    deadline = asyncio.get_running_loop().time() + timeout_seconds

    while asyncio.get_running_loop().time() < deadline:
        await session.refresh(job)
        raise_if_job_failed(job)

        segment_ready = segment_path.exists() and segment_path.stat().st_size > 0
        if segment_ready:
            return segment_path

        await asyncio.sleep(0.25)

    if segment_path.exists() and segment_path.stat().st_size > 0:
        return segment_path

    raise HTTPException(status_code=404, detail=f"Segment {segment_num} not ready")


async def wait_for_hls_asset(
    job: TranscodingJob,
    asset_name: str,
    session: AsyncSession,
    timeout_seconds: float = 20.0,
) -> Path:
    """Wait for a generated HLS asset, such as fMP4 init or media segments."""
    if not job.output_path:
        raise HTTPException(status_code=404, detail="Job output path not set")

    asset_path = Path(job.output_path) / asset_name
    deadline = asyncio.get_running_loop().time() + timeout_seconds

    while asyncio.get_running_loop().time() < deadline:
        await session.refresh(job)
        raise_if_job_failed(job)

        if asset_path.exists() and asset_path.stat().st_size > 0:
            return asset_path

        await asyncio.sleep(0.25)

    if asset_path.exists() and asset_path.stat().st_size > 0:
        return asset_path

    raise HTTPException(status_code=404, detail=f"HLS asset {asset_name} not ready")


def raise_if_job_failed(job: TranscodingJob) -> None:
    if job.status == TranscodingJobStatus.CANCELLED:
        raise HTTPException(status_code=410, detail="Transcoding job was cancelled")
    if job.status == TranscodingJobStatus.FAILED:
        detail = f"Transcoding failed: {job.error_message}" if job.error_message else "Transcoding failed"
        raise HTTPException(status_code=500, detail=detail)


async def is_playlist_ready(playlist_path: Path) -> bool:
    """Return true when the playlist is parseable and its first media segment exists."""
    if not playlist_path.exists() or playlist_path.stat().st_size == 0:
        return False

    try:
        async with aiofiles.open(playlist_path) as f:
            content = await f.read()
    except OSError:
        return False

    if "#EXTM3U" not in content or "#EXTINF" not in content:
        return False

    first_segment = first_playlist_segment(content)
    if not first_segment:
        return False

    segment_path = playlist_path.parent / first_segment
    return segment_path.exists() and segment_path.stat().st_size > 0


def first_playlist_segment(content: str) -> str | None:
    """Extract the first relative media segment URI from a playlist."""
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "://" in line or line.startswith("/"):
            return None
        return line.split("?", 1)[0]
    return None


def append_api_key_to_playlist_segments(content: str, api_key: str | None) -> str:
    """Append query auth to relative HLS segment URLs for native HLS players."""
    if not api_key:
        return content

    encoded_key = quote(api_key, safe="")
    rewritten_lines: list[str] = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if line.startswith("#EXT-X-MAP:"):
            rewritten_lines.append(_append_api_key_to_ext_x_map(raw_line, encoded_key))
            continue
        if not line or line.startswith("#") or "://" in line or line.startswith("/") or "api_key=" in line:
            rewritten_lines.append(raw_line)
            continue

        separator = "&" if "?" in line else "?"
        rewritten_lines.append(f"{line}{separator}api_key={encoded_key}")

    suffix = "\n" if content.endswith("\n") else ""
    return "\n".join(rewritten_lines) + suffix


def _append_api_key_to_ext_x_map(line: str, encoded_key: str) -> str:
    uri_marker = 'URI="'
    marker_start = line.find(uri_marker)
    if marker_start == -1:
        return line

    uri_start = marker_start + len(uri_marker)
    uri_end = line.find('"', uri_start)
    if uri_end == -1:
        return line

    uri = line[uri_start:uri_end]
    if not uri or "://" in uri or uri.startswith("/") or "api_key=" in uri:
        return line

    separator = "&" if "?" in uri else "?"
    return f"{line[:uri_start]}{uri}{separator}api_key={encoded_key}{line[uri_end:]}"


def raise_invalid_range(file_size: int) -> None:
    raise HTTPException(
        status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
        detail="Invalid range",
        headers={"Content-Range": f"bytes */{file_size}"},
    )
