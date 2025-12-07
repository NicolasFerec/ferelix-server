"""Video streaming endpoint with HTTP Range request support (v1 with optional authentication)."""

from pathlib import Path
from typing import Annotated

import aiofiles
from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.dependencies import get_optional_user
from app.models import MediaFile, User

router = APIRouter(prefix="/api/v1", tags=["streaming"])


async def range_reader(file_path: Path, start: int, end: int, chunk_size: int = 8192):
    """Async generator to stream file chunks within a byte range.

    Args:
        file_path: Path to the file to stream
        start: Start byte position
        end: End byte position (inclusive)
        chunk_size: Size of chunks to read

    Yields:
        File chunks as bytes
    """
    async with aiofiles.open(file_path, mode="rb") as f:
        await f.seek(start)
        remaining = end - start + 1

        while remaining > 0:
            chunk_size_to_read = min(chunk_size, remaining)
            data = await f.read(chunk_size_to_read)
            if not data:
                break
            remaining -= len(data)
            yield data


@router.get("/stream/{media_id}")
async def stream_video(
    media_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User | None, Depends(get_optional_user)] = None,
    range_header: Annotated[str | None, Header(alias="Range")] = None,
) -> StreamingResponse:
    """Stream video file with HTTP Range request support for seeking.

    Authentication is optional but recommended. Supports both:
    - Authorization: Bearer <token> header
    - ?api_key=<token> query parameter (for browser video tags)

    Args:
        media_id: Media file ID
        session: Database session
        user: Optional authenticated user
        range_header: HTTP Range header for partial content requests

    Returns:
        Streaming response with video content

    Raises:
        HTTPException: If media file not found or range invalid
    """
    # Note: Authentication is optional for streaming to support public access
    # In production, you may want to require authentication

    # Fetch media file from database
    media_file = await session.get(MediaFile, media_id)

    if not media_file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Media file not found"
        )

    file_path = Path(media_file.file_path)
    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Media file not found on disk",
        )

    file_size = media_file.file_size

    # Parse Range header
    start = 0
    end = file_size - 1

    if range_header:
        # Range header format: "bytes=start-end"
        range_str = range_header.replace("bytes=", "")
        range_parts = range_str.split("-")

        if range_parts[0]:
            start = int(range_parts[0])
        end = int(range_parts[1]) if range_parts[1] else file_size - 1

        # Validate range
        if start >= file_size or end >= file_size or start > end:
            raise HTTPException(
                status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
                detail="Invalid range",
            )

    # Determine content type based on file extension
    content_type_map = {
        ".mp4": "video/mp4",
        ".mkv": "video/x-matroska",
        ".avi": "video/x-msvideo",
        ".mov": "video/quicktime",
        ".webm": "video/webm",
        ".m4v": "video/x-m4v",
    }
    content_type = content_type_map.get(
        media_file.file_extension.lower(), "application/octet-stream"
    )

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Type": content_type,
        "Content-Length": str(end - start + 1),
    }

    # Return partial content if range was requested
    if range_header:
        headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
        return StreamingResponse(
            range_reader(file_path, start, end),
            status_code=status.HTTP_206_PARTIAL_CONTENT,
            headers=headers,
        )

    # Return full content
    return StreamingResponse(
        range_reader(file_path, start, end),
        status_code=status.HTTP_200_OK,
        headers=headers,
    )
