"""Personal viewing state and safe editorial continuation."""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.dependencies import get_current_active_user
from app.models import User
from app.models.metadata import ItemCardSchema
from app.services.continuation import (
    ContinuationChoice,
    ContinuationStatus,
    next_up_choices,
    resolve_continuation,
    resume_choices,
)
from app.services.item_catalogue import item_cards
from app.services.viewing import bulk_watch_state, set_item_watch_state

router = APIRouter(prefix="/api/v1/items", tags=["viewing"])


class WatchStateUpdate(BaseModel):
    watched: bool
    expected_revision: int | None = Field(default=None, ge=0)


class WatchStateSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    item_id: int
    watched: bool
    watched_at: datetime | None = None
    state_revision: int


class BulkWatchStateRequest(BaseModel):
    watched: bool
    preview: bool = True
    revision_token: str | None = Field(default=None, max_length=64)


class BulkWatchStateResponse(BaseModel):
    count: int
    revision_token: str
    applied: bool


class ContinuationResponse(BaseModel):
    status: ContinuationStatus
    item: ItemCardSchema | None = None
    media_file_id: int | None = None
    position_seconds: float = 0


async def _choice_cards(session: AsyncSession, user_id: int, choices: list[ContinuationChoice]) -> list[ItemCardSchema]:
    ids = [choice.item_id for choice in choices if choice.item_id is not None]
    by_id = {choice.item_id: choice for choice in choices}
    cards = await item_cards(session, user_id, ids)
    return [
        card.model_copy(
            update={
                "playable_file_id": by_id[card.id].media_file_id,
                "position_seconds": by_id[card.id].position_seconds,
            }
        )
        for card in cards
    ]


@router.get("/resume", response_model=list[ItemCardSchema])
async def get_resume_items(
    user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 24,
) -> list[ItemCardSchema]:
    return await _choice_cards(session, user.id, await resume_choices(session, user.id, limit))


@router.get("/next-up", response_model=list[ItemCardSchema])
async def get_next_up_items(
    user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 24,
) -> list[ItemCardSchema]:
    return await _choice_cards(session, user.id, await next_up_choices(session, user.id, limit))


@router.put("/{item_id}/watch-state", response_model=WatchStateSchema)
async def put_watch_state(
    item_id: int,
    payload: WatchStateUpdate,
    user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> WatchStateSchema:
    try:
        state = await set_item_watch_state(session, user.id, item_id, payload.watched, payload.expected_revision)
        await session.commit()
        return WatchStateSchema.model_validate(state)
    except HTTPException:
        await session.rollback()
        raise


@router.post("/{item_id}/watch-state/bulk", response_model=BulkWatchStateResponse)
async def post_bulk_watch_state(
    item_id: int,
    payload: BulkWatchStateRequest,
    user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> BulkWatchStateResponse:
    if not payload.preview and not payload.revision_token:
        raise HTTPException(status_code=422, detail="Preview revision_token is required")
    try:
        result = await bulk_watch_state(
            session, user.id, item_id, payload.watched, preview=payload.preview, revision_token=payload.revision_token
        )
        if not payload.preview:
            await session.commit()
        return BulkWatchStateResponse.model_validate(result)
    except HTTPException:
        await session.rollback()
        raise


@router.get("/{item_id}/continuation", response_model=ContinuationResponse)
async def get_continuation(
    item_id: int,
    user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    mode: Literal["next", "continue"] = "continue",
) -> ContinuationResponse:
    choice = await resolve_continuation(session, user.id, item_id, mode)
    cards = await _choice_cards(session, user.id, [choice])
    return ContinuationResponse(
        status=choice.status,
        item=cards[0] if cards else None,
        media_file_id=choice.media_file_id,
        position_seconds=choice.position_seconds,
    )
