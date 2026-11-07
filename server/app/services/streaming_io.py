"""I/O helpers for direct file streaming and generated HLS assets."""

import asyncio
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode

import aiofiles
from fastapi import HTTPException, status
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TranscodingJob
from app.models.transcoding import TranscodingJobStatus

HLS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "*",
    "Cache-Control": "private, no-store",
}

SEGMENT_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "*",
    "Cache-Control": "private, no-store",
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


async def range_reader(file_path: Path, start: int, end: int, chunk_size: int = 256 * 1024):
    """Yield bounded chunks, amortizing threadpool overhead for high-bitrate video."""
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
    touched_id = await session.scalar(
        update(TranscodingJob)
        .where(TranscodingJob.id == job.id, TranscodingJob.status != TranscodingJobStatus.STOPPING)
        .values(last_accessed_at=datetime.now(UTC))
        .returning(TranscodingJob.id)
    )
    await session.commit()
    if touched_id is None:
        raise HTTPException(status_code=410, detail="Transcoding job is stopping")


async def wait_for_playlist(job: TranscodingJob, session: AsyncSession, timeout_seconds: float = 15.0) -> Path:
    """Wait briefly for ffmpeg to create a readable HLS playlist and first segment."""
    if not job.playlist_path:
        raise HTTPException(status_code=404, detail="Playlist path not set")

    playlist_path = Path(job.playlist_path)
    deadline = asyncio.get_running_loop().time() + timeout_seconds

    while asyncio.get_running_loop().time() < deadline:
        await session.refresh(job)
        raise_if_job_failed(job)
        if await is_playlist_ready(playlist_path):
            return playlist_path
        if job.status == TranscodingJobStatus.COMPLETED:
            raise HTTPException(status_code=404, detail="Completed job has no readable playlist")
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

        segment_ready = await asyncio.to_thread(_is_nonempty_file, segment_path)
        if segment_ready:
            return segment_path

        await asyncio.sleep(0.25)

    if await asyncio.to_thread(_is_nonempty_file, segment_path):
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

        if await asyncio.to_thread(_is_nonempty_file, asset_path):
            return asset_path

        await asyncio.sleep(0.25)

    if await asyncio.to_thread(_is_nonempty_file, asset_path):
        return asset_path

    raise HTTPException(status_code=404, detail=f"HLS asset {asset_name} not ready")


def raise_if_job_failed(job: TranscodingJob) -> None:
    if job.status == TranscodingJobStatus.STOPPING:
        raise HTTPException(status_code=410, detail="Transcoding job is stopping")
    if job.status == TranscodingJobStatus.CANCELLED:
        raise HTTPException(status_code=410, detail="Transcoding job was cancelled")
    if job.status == TranscodingJobStatus.FAILED:
        detail = f"Transcoding failed: {job.error_message}" if job.error_message else "Transcoding failed"
        raise HTTPException(status_code=500, detail=detail)


async def is_playlist_ready(playlist_path: Path) -> bool:
    """Check a manifest and its required assets together, outside the event loop."""
    return await asyncio.to_thread(_is_playlist_ready, playlist_path)


def _is_nonempty_file(path: Path) -> bool:
    try:
        return path.stat().st_size > 0
    except OSError:
        # A concurrent stop/cleanup can remove any asset at any point.
        return False


def _is_playlist_ready(playlist_path: Path) -> bool:
    try:
        content = playlist_path.read_text()
    except OSError:
        return False

    if "#EXTM3U" not in content or "#EXTINF" not in content:
        return False
    first_segment = first_playlist_segment(content)
    if not first_segment or not _is_nonempty_file(playlist_path.parent / first_segment):
        return False

    # fMP4 cannot decode media fragments without the initialization segment.
    for line in content.splitlines():
        if line.startswith("#EXT-X-MAP:"):
            match = re.search(r'URI="([^"\n]+)"', line)
            if not match:
                return False
            init_name = first_playlist_segment(match.group(1))
            if not init_name or not _is_nonempty_file(playlist_path.parent / init_name):
                return False
    return True


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


def append_media_token_to_playlist(content: str, session_id: str, media_token: str | None) -> str:
    """Propagate only the playback-scoped credential to relative native HLS assets."""
    query = urlencode({"session_id": session_id, **({"media_token": media_token} if media_token else {})})

    def scoped_uri(uri: str) -> str:
        if not uri or "://" in uri or uri.startswith("/"):
            return uri
        return f"{uri}{'&' if '?' in uri else '?'}{query}"

    lines = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if line.startswith("#EXT-X-MAP:"):
            lines.append(re.sub(r'URI="([^"\n]+)"', lambda match: f'URI="{scoped_uri(match.group(1))}"', raw_line))
        elif line and not line.startswith("#"):
            lines.append(scoped_uri(line))
        else:
            lines.append(raw_line)
    return "\n".join(lines) + ("\n" if content.endswith("\n") else "")


def raise_invalid_range(file_size: int) -> None:
    raise HTTPException(
        status_code=status.HTTP_416_RANGE_NOT_SATISFIABLE,
        detail="Invalid range",
        headers={"Content-Range": f"bytes */{file_size}"},
    )
