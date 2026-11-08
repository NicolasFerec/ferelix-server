"""Watch history and resume state, guarded against obsolete playback sessions."""

import hashlib
import json
import math
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import and_, case, func, or_, select, tuple_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MediaFile, MediaView, PlaybackSession, PlaybackSessionStatus, Settings
from app.models.metadata import MediaItem, MediaItemFile, UserItemState
from app.services.item_catalogue import require_item as visible_item_or_404


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def is_media_watched(position_seconds: float, duration_seconds: float | None, threshold_percent: float = 90) -> bool:
    return bool(
        duration_seconds
        and duration_seconds > 0
        and math.isfinite(duration_seconds)
        and math.isfinite(position_seconds)
        and 0 < threshold_percent <= 100
        and position_seconds >= duration_seconds * threshold_percent / 100
    )


async def get_watched_threshold(session: AsyncSession) -> float:
    settings = await session.get(Settings, 1)
    return settings.watched_threshold_percent if settings is not None else 90


async def get_or_create_media_view(session: AsyncSession, user_id: int, media_file_id: int) -> MediaView:
    query = select(MediaView).where(MediaView.user_id == user_id, MediaView.media_file_id == media_file_id)
    view = await session.scalar(query)
    if view is not None:
        return view
    try:
        async with session.begin_nested():
            view = MediaView(user_id=user_id, media_file_id=media_file_id)
            session.add(view)
            await session.flush()
        return view
    except IntegrityError:
        view = await session.scalar(query)
        if view is None:
            raise
        return view


async def get_or_create_item_state(session: AsyncSession, user_id: int, item_id: int) -> UserItemState:
    state = await session.get(UserItemState, (user_id, item_id))
    if state is not None:
        return state
    try:
        async with session.begin_nested():
            state = UserItemState(user_id=user_id, item_id=item_id)
            session.add(state)
            await session.flush()
        return state
    except IntegrityError:
        state = await session.get(UserItemState, (user_id, item_id))
        if state is None:
            raise
        return state


async def record_playback_started(session: AsyncSession, playback: PlaybackSession, item_id: int | None) -> None:
    """Capture a revision without clearing a previous resume point or inventing activity."""
    links = list(
        await session.scalars(select(MediaItemFile).where(MediaItemFile.media_file_id == playback.media_file_id))
    )
    if item_id is not None:
        item = await visible_item_or_404(session, item_id)
        if item.kind not in {"movie", "episode"} or not any(link.item_id == item_id for link in links):
            raise HTTPException(status_code=422, detail="File does not belong to this playable item")
    elif len(links) == 1:
        item = await visible_item_or_404(session, links[0].item_id)
        item_id = item.id
    view = await get_or_create_media_view(session, playback.user_id, playback.media_file_id)
    playback.item_id = item_id
    if item_id is not None:
        await get_or_create_item_state(session, playback.user_id, item_id)
        revision = await session.scalar(
            update(UserItemState)
            .where(
                UserItemState.user_id == playback.user_id,
                UserItemState.item_id == item_id,
            )
            .values(state_revision=UserItemState.state_revision + 1)
            .returning(UserItemState.state_revision)
        )
        assert revision is not None
        playback.state_revision = revision
    file_revision = await session.scalar(
        update(MediaView)
        .where(MediaView.id == view.id)
        .values(
            state_revision=MediaView.state_revision + 1,
            play_count=MediaView.play_count + 1,
        )
        .returning(MediaView.state_revision)
    )
    if item_id is None:
        assert file_revision is not None
        playback.state_revision = file_revision


async def _logical_progress(
    session: AsyncSession, playback: PlaybackSession, position: float, duration: float | None
) -> tuple[float, float | None] | None:
    links = list(
        await session.scalars(select(MediaItemFile).where(MediaItemFile.media_file_id == playback.media_file_id))
    )
    link = next((link for link in links if link.item_id == playback.item_id), None)
    if link is None:
        return None
    bounded = (
        link.start_seconds is not None and link.end_seconds is not None and 0 <= link.start_seconds < link.end_seconds
    )
    if len(links) > 1 and not bounded:
        return None  # An explicit item alone cannot identify its portion in a multi-episode file.
    if bounded:
        assert link.start_seconds is not None and link.end_seconds is not None
        return max(0, position - link.start_seconds), link.end_seconds - link.start_seconds
    return position, duration


async def record_playback_progress(session: AsyncSession, playback: PlaybackSession) -> bool:
    """Persist progress only while the session's manual-state revision is current."""
    view = await get_or_create_media_view(session, playback.user_id, playback.media_file_id)
    if playback.item_id is None:
        links = list(
            await session.scalars(
                select(MediaItemFile.item_id)
                .where(
                    MediaItemFile.media_file_id == playback.media_file_id,
                )
                .limit(2)
            )
        )
        if len(links) == 1:
            discovered = await session.get(UserItemState, (playback.user_id, links[0]), populate_existing=True)
            if (
                discovered is None
                or discovered.state_revision != playback.state_revision
                or view.state_revision != playback.state_revision
            ):
                return False
            playback.item_id = links[0]
    position = playback.position_seconds
    duration = playback.duration_seconds
    if duration is None:
        media = await session.get(MediaFile, playback.media_file_id)
        duration = media.duration if media is not None else None
    threshold = await get_watched_threshold(session)
    completed = is_media_watched(position, duration, threshold)
    resume_position, resume_completed = position, completed
    moved = position != view.position_seconds
    now = utcnow()
    guard = MediaView.state_revision == playback.state_revision
    if playback.item_id is not None:
        logical = await _logical_progress(session, playback, position, duration)
        item_completed = logical is not None and is_media_watched(*logical, threshold)
        if logical is not None:
            resume_position, resume_completed = logical[0], item_completed
        values: dict[str, Any] = {
            "watched": True if item_completed else UserItemState.watched,
            "watched_at": func.coalesce(UserItemState.watched_at, now) if item_completed else UserItemState.watched_at,
        }
        if moved and logical is not None:
            values["last_activity_at"] = now
        claimed = await session.scalar(
            update(UserItemState)
            .where(
                UserItemState.user_id == playback.user_id,
                UserItemState.item_id == playback.item_id,
                UserItemState.state_revision == playback.state_revision,
            )
            .values(**values)
            .returning(UserItemState.item_id)
        )
        if claimed is None:
            return False
        guard = (
            select(UserItemState.item_id)
            .where(
                UserItemState.user_id == playback.user_id,
                UserItemState.item_id == playback.item_id,
                UserItemState.state_revision == playback.state_revision,
            )
            .exists()
        )
    values = {
        "position_seconds": position,
        "duration_seconds": duration,
        "resume_active": resume_position > 10 and not resume_completed,
        "watched": True if completed else MediaView.watched,
        "completed_at": func.coalesce(MediaView.completed_at, now) if completed else MediaView.completed_at,
    }
    if moved:
        values["last_viewed_at"] = now
    return (
        await session.scalar(
            update(MediaView).where(MediaView.id == view.id, guard).values(**values).returning(MediaView.id)
        )
        is not None
    )


async def _clear_item_resumes(
    session: AsyncSession,
    user_id: int,
    item_ids: list[int],
    now: datetime,
    *,
    reset_position: bool,
) -> None:
    file_ids = select(MediaItemFile.media_file_id).where(MediaItemFile.item_id.in_(item_ids))
    unseen = (
        select(MediaItemFile.item_id)
        .outerjoin(
            UserItemState,
            and_(
                UserItemState.item_id == MediaItemFile.item_id,
                UserItemState.user_id == user_id,
            ),
        )
        .where(
            MediaItemFile.media_file_id == MediaView.media_file_id,
            or_(UserItemState.item_id.is_(None), UserItemState.watched.is_(False)),
        )
        .exists()
    )
    await session.execute(
        update(MediaView)
        .where(MediaView.user_id == user_id, MediaView.media_file_id.in_(file_ids))
        .values(
            watched=~unseen,
            position_seconds=0 if reset_position else MediaView.position_seconds,
            resume_active=False,
            completed_at=case((~unseen, now), else_=None),
            state_revision=MediaView.state_revision + 1,
        )
    )


async def set_item_watch_state(
    session: AsyncSession,
    user_id: int,
    item_id: int,
    watched: bool,
    expected_revision: int | None = None,
    *,
    clear_resumes: bool = True,
) -> UserItemState:
    item = await visible_item_or_404(session, item_id)
    if item.kind not in {"movie", "episode"}:
        raise HTTPException(status_code=400, detail="Use bulk preview to change a container's watch state")
    state = await get_or_create_item_state(session, user_id, item_id)
    revision = state.state_revision
    if expected_revision is not None and expected_revision != revision:
        raise HTTPException(status_code=409, detail="Watch state changed")
    linked_files = select(MediaItemFile.media_file_id).where(MediaItemFile.item_id == item_id)
    current_file_revision = (
        select(MediaView.id)
        .where(
            MediaView.user_id == user_id,
            MediaView.media_file_id == PlaybackSession.media_file_id,
            MediaView.state_revision == PlaybackSession.state_revision,
        )
        .exists()
    )
    active = await session.scalar(
        select(PlaybackSession.id)
        .where(
            PlaybackSession.user_id == user_id,
            PlaybackSession.status == PlaybackSessionStatus.ACTIVE,
            or_(
                and_(PlaybackSession.item_id == item_id, PlaybackSession.state_revision == revision),
                and_(
                    PlaybackSession.item_id.is_(None),
                    PlaybackSession.media_file_id.in_(linked_files),
                    current_file_revision,
                ),
            ),
        )
        .limit(1)
    )
    resume = await session.scalar(
        select(MediaView.id)
        .join(MediaItemFile, MediaItemFile.media_file_id == MediaView.media_file_id)
        .where(MediaItemFile.item_id == item_id, MediaView.user_id == user_id, MediaView.resume_active.is_(True))
        .limit(1)
    )
    if state.watched == watched and active is None and resume is None:
        unchanged = await session.scalar(
            update(UserItemState)
            .where(
                UserItemState.user_id == user_id,
                UserItemState.item_id == item_id,
                UserItemState.state_revision == revision,
                UserItemState.watched == watched,
            )
            .values(state_revision=UserItemState.state_revision)
            .returning(UserItemState.item_id)
        )
        if unchanged is None:
            raise HTTPException(status_code=409, detail="Watch state changed")
        return state
    now = utcnow()
    changed = await session.scalar(
        update(UserItemState)
        .where(
            UserItemState.user_id == user_id,
            UserItemState.item_id == item_id,
            UserItemState.state_revision == revision,
        )
        .values(
            watched=watched,
            watched_at=now if watched else None,
            state_revision=UserItemState.state_revision + 1,
            last_activity_at=now,
        )
        .returning(UserItemState.item_id)
    )
    if changed is None:
        raise HTTPException(status_code=409, detail="Watch state changed")
    if clear_resumes:
        await _clear_item_resumes(session, user_id, [item_id], now, reset_position=not watched)
    await session.refresh(state)
    return state


async def set_file_watch_state(session: AsyncSession, user_id: int, media_file_id: int, watched: bool) -> MediaView:
    """Legacy explicit file action; unlike automatic progress it can cover all mapped items."""
    view = await get_or_create_media_view(session, user_id, media_file_id)
    links = list(
        await session.scalars(select(MediaItemFile.item_id).where(MediaItemFile.media_file_id == media_file_id))
    )
    if links:
        changed_items = []
        for item_id in sorted(links):
            previous = await get_or_create_item_state(session, user_id, item_id)
            revision = previous.state_revision
            state = await set_item_watch_state(session, user_id, item_id, watched, clear_resumes=False)
            if state.state_revision != revision:
                changed_items.append(item_id)
        if changed_items:
            await _clear_item_resumes(session, user_id, changed_items, utcnow(), reset_position=not watched)
    else:
        active = await session.scalar(
            select(PlaybackSession.id)
            .where(
                PlaybackSession.user_id == user_id,
                PlaybackSession.media_file_id == media_file_id,
                PlaybackSession.state_revision == view.state_revision,
                PlaybackSession.status == PlaybackSessionStatus.ACTIVE,
            )
            .limit(1)
        )
        if view.watched != watched or view.resume_active or active is not None:
            changed = await session.scalar(
                update(MediaView)
                .where(MediaView.id == view.id, MediaView.state_revision == view.state_revision)
                .values(
                    watched=watched,
                    position_seconds=0 if not watched else MediaView.position_seconds,
                    resume_active=False,
                    completed_at=utcnow() if watched else None,
                    state_revision=MediaView.state_revision + 1,
                )
                .returning(MediaView.id)
            )
        else:
            changed = await session.scalar(
                update(MediaView)
                .where(
                    MediaView.id == view.id,
                    MediaView.state_revision == view.state_revision,
                    MediaView.watched == watched,
                    MediaView.resume_active.is_(False),
                )
                .values(state_revision=MediaView.state_revision)
                .returning(MediaView.id)
            )
        if changed is None:
            raise HTTPException(status_code=409, detail="Watch state changed")
    await session.refresh(view)
    return view


async def bulk_targets(session: AsyncSession, item: MediaItem) -> list[int]:
    conditions = {
        "series": MediaItem.series_id == item.id,
        "season": MediaItem.parent_id == item.id,
        "collection": MediaItem.collection_id == item.id,
    }
    if item.kind not in conditions:
        return [item.id]
    return list(
        await session.scalars(
            select(MediaItem.id)
            .where(
                conditions[item.kind],
                MediaItem.kind.in_(["movie", "episode"]),
                MediaItem.metadata_library_id == item.metadata_library_id,
            )
            .order_by(MediaItem.id)
        )
    )


async def apply_file_progress_patch(
    session: AsyncSession,
    user_id: int,
    media_file_id: int,
    position_seconds: float,
    duration_seconds: float | None,
) -> MediaView:
    """An explicit legacy seek/progress edit invalidates older session writes too."""
    view = await get_or_create_media_view(session, user_id, media_file_id)
    links = list(
        await session.scalars(
            select(MediaItemFile).where(MediaItemFile.media_file_id == media_file_id).order_by(MediaItemFile.item_id)
        )
    )
    revisions = {}
    for link in links:
        state = await get_or_create_item_state(session, user_id, link.item_id)
        revision = await session.scalar(
            update(UserItemState)
            .where(
                UserItemState.user_id == user_id,
                UserItemState.item_id == link.item_id,
                UserItemState.state_revision == state.state_revision,
            )
            .values(state_revision=UserItemState.state_revision + 1)
            .returning(UserItemState.state_revision)
        )
        if revision is None:
            raise HTTPException(status_code=409, detail="Watch state changed")
        revisions[link.item_id] = revision
    revision = await session.scalar(
        update(MediaView)
        .where(
            MediaView.id == view.id,
            MediaView.state_revision == view.state_revision,
        )
        .values(state_revision=MediaView.state_revision + 1)
        .returning(MediaView.state_revision)
    )
    if revision is None:
        raise HTTPException(status_code=409, detail="Watch state changed")
    item_id = (
        links[0].item_id
        if len(links) == 1
        else next(
            (
                link.item_id
                for link in links
                if link.start_seconds is not None
                and link.end_seconds is not None
                and link.start_seconds <= position_seconds < link.end_seconds
            ),
            None,
        )
    )
    snapshot = PlaybackSession(
        user_id=user_id,
        media_file_id=media_file_id,
        item_id=item_id,
        state_revision=revisions[item_id] if item_id is not None else revision,
        position_seconds=position_seconds,
        duration_seconds=duration_seconds,
    )
    await record_playback_progress(session, snapshot)
    await session.refresh(view)
    return view


async def bulk_watch_state(
    session: AsyncSession,
    user_id: int,
    item_id: int,
    watched: bool,
    *,
    preview: bool = True,
    revision_token: str | None = None,
) -> dict:
    item = await visible_item_or_404(session, item_id)
    if not preview:
        # Lock before taking the snapshot (also obtains SQLite's write lock).
        # Keep metadata timestamps unchanged: this is a coordination write only.
        await session.execute(
            update(MediaItem)
            .where(MediaItem.id == item.id)
            .values(
                revision=MediaItem.revision,
                updated_at=MediaItem.updated_at,
            )
        )
        await session.refresh(item)
    targets = await bulk_targets(session, item)
    states = list(
        await session.scalars(
            select(UserItemState).where(UserItemState.user_id == user_id, UserItemState.item_id.in_(targets))
        )
    )
    states_by_id = {state.item_id: state for state in states}
    links = list(
        (
            await session.execute(
                select(
                    MediaItemFile.item_id,
                    MediaItemFile.media_file_id,
                    MediaItemFile.start_seconds,
                    MediaItemFile.end_seconds,
                )
                .where(MediaItemFile.item_id.in_(targets))
                .order_by(MediaItemFile.item_id, MediaItemFile.media_file_id)
            )
        ).all()
    )
    views = list(
        (
            await session.execute(
                select(
                    MediaView.media_file_id,
                    MediaView.state_revision,
                    MediaView.position_seconds,
                    MediaView.resume_active,
                )
                .where(
                    MediaView.user_id == user_id, MediaView.media_file_id.in_([link.media_file_id for link in links])
                )
                .order_by(MediaView.media_file_id)
            )
        ).all()
    )
    snapshot = [
        user_id,
        item_id,
        item.revision,
        watched,
        [
            (target, states_by_id[target].state_revision, states_by_id[target].watched)
            if target in states_by_id
            else (target, 0, False)
            for target in targets
        ],
        [tuple(row) for row in links],
        [tuple(row) for row in views],
    ]
    token = hashlib.sha256(json.dumps(snapshot, separators=(",", ":")).encode()).hexdigest()
    if preview:
        return {"count": len(targets), "revision_token": token, "applied": False}
    if revision_token != token:
        raise HTTPException(status_code=409, detail="Watch-state preview changed; preview again")
    await _apply_bulk_targets(session, user_id, targets, states_by_id, links, views, watched)
    return {"count": len(targets), "revision_token": token, "applied": True}


async def _apply_bulk_targets(
    session: AsyncSession,
    user_id: int,
    targets: list[int],
    states: dict[int, UserItemState],
    links: list[Any],
    views: list[Any],
    watched: bool,
) -> None:
    changed = {id_ for id_ in targets if bool(states.get(id_) and states[id_].watched) != watched}
    file_items: dict[int, set[int]] = {}
    for link in links:
        file_items.setdefault(link.media_file_id, set()).add(link.item_id)
    file_revisions = {view.media_file_id: view.state_revision for view in views}
    for view in views:
        if view.resume_active:
            changed.update(file_items.get(view.media_file_id, set()))
    active = await session.execute(
        select(PlaybackSession.item_id, PlaybackSession.media_file_id, PlaybackSession.state_revision).where(
            PlaybackSession.user_id == user_id,
            PlaybackSession.status == PlaybackSessionStatus.ACTIVE,
            or_(PlaybackSession.item_id.in_(targets), PlaybackSession.media_file_id.in_(file_items)),
        )
    )
    for item_id, file_id, revision in active:
        if item_id in targets and revision == (states[item_id].state_revision if item_id in states else 0):
            changed.add(item_id)
        elif item_id is None and revision == file_revisions.get(file_id):
            changed.update(file_items.get(file_id, set()))
    if not changed:
        return
    now = utcnow()
    missing = changed - states.keys()
    session.add_all([
        UserItemState(
            user_id=user_id,
            item_id=id_,
            watched=watched,
            watched_at=now if watched else None,
            state_revision=1,
            last_activity_at=now,
        )
        for id_ in sorted(missing)
    ])
    try:
        await session.flush()
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Watch state changed; preview again") from exc
    existing = sorted(changed & states.keys())
    if existing:
        applied = list(
            await session.scalars(
                update(UserItemState)
                .where(
                    UserItemState.user_id == user_id,
                    tuple_(UserItemState.item_id, UserItemState.state_revision, UserItemState.watched).in_([
                        (id_, states[id_].state_revision, states[id_].watched) for id_ in existing
                    ]),
                )
                .values(
                    watched=watched,
                    watched_at=now if watched else None,
                    state_revision=UserItemState.state_revision + 1,
                    last_activity_at=now,
                )
                .returning(UserItemState.item_id)
            )
        )
        if len(applied) != len(existing):
            raise HTTPException(status_code=409, detail="Watch state changed; preview again")
    await _clear_item_resumes(session, user_id, sorted(changed), now, reset_position=not watched)
