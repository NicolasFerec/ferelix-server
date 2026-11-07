"""Playback-scoped media credentials, renewed by the authenticated session heartbeat."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.dependencies import get_current_user, security
from app.models import PlaybackSession, PlaybackSessionStatus, TranscodingJob, User

MEDIA_ACCESS_IDLE_TIMEOUT = timedelta(minutes=10)


def issue_media_token() -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    return token, hash_media_token(token)


def hash_media_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def session_is_live(playback: PlaybackSession) -> bool:
    heartbeat = playback.last_heartbeat_at
    if heartbeat.tzinfo is None:
        heartbeat = heartbeat.replace(tzinfo=UTC)
    return playback.status == PlaybackSessionStatus.ACTIVE and heartbeat > datetime.now(UTC) - MEDIA_ACCESS_IDLE_TIMEOUT


async def get_playback_media_session(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    session_id: Annotated[str, Query()],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)] = None,
    media_token: Annotated[str | None, Query()] = None,
) -> PlaybackSession:
    """Authorize only the media and HLS timelines owned by this active session.

    A stable opaque token allows native HLS/HTML video range requests to outlive
    an API access JWT. Its authority expires with the session's heartbeat lease;
    it cannot authenticate catalogue, account, session mutation or admin routes.
    """
    playback = await session.get(PlaybackSession, session_id)
    if playback is None:
        raise HTTPException(status_code=404, detail="Playback session not found")
    user = await session.get(User, playback.user_id)
    if user is None or not user.is_active or playback.credentials_version != user.credentials_version:
        raise HTTPException(status_code=401, detail="Playback credentials have been revoked")

    if media_token:
        authorized = bool(
            playback.media_token_hash
            and secrets.compare_digest(hash_media_token(media_token), playback.media_token_hash)
        )
    elif credentials:
        requesting_user = await get_current_user(session, credentials, None)
        authorized = requesting_user.id == playback.user_id
    else:
        authorized = False
    if not authorized:
        raise HTTPException(status_code=404 if credentials else 401, detail="Invalid playback media credential")
    if not session_is_live(playback):
        raise HTTPException(status_code=410, detail="Playback session has ended or expired")

    media_id = request.path_params.get("media_id")
    if media_id is not None and int(media_id) != playback.media_file_id:
        raise HTTPException(status_code=404, detail="Media does not belong to this playback session")
    job_id = request.path_params.get("job_id")
    if job_id is not None:
        job = await session.get(TranscodingJob, job_id)
        if job is None or job.session_id != playback.id:
            raise HTTPException(status_code=404, detail="Transcoding job not found")
    return playback


async def require_owned_playback_session(
    session: AsyncSession, session_id: str, media_id: int, user: User
) -> PlaybackSession:
    playback = await session.get(PlaybackSession, session_id)
    if playback is None or playback.user_id != user.id:
        raise HTTPException(status_code=404, detail="Playback session not found")
    if playback.media_file_id != media_id:
        raise HTTPException(status_code=400, detail="Session belongs to another media file")
    if playback.credentials_version != user.credentials_version:
        raise HTTPException(status_code=401, detail="Playback credentials have been revoked")
    if playback.status != PlaybackSessionStatus.ACTIVE:
        raise HTTPException(status_code=410, detail="Playback session has ended")
    return playback
