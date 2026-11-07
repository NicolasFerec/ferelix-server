"""Administrator resolution of files whose episode numbering was ambiguous."""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.dependencies import require_admin
from app.services.item_association import associate_episode

router = APIRouter(prefix="/api/v1/dashboard/metadata", tags=["metadata"], dependencies=[Depends(require_admin)])


class EpisodeAssociationRequest(BaseModel):
    expected_revision: int = Field(ge=0)
    target_item_id: int = Field(gt=0)
    target_expected_revision: int = Field(ge=0)


class EpisodeAssociationResponse(BaseModel):
    item_id: int


@router.post("/items/{item_id}/associate", response_model=EpisodeAssociationResponse)
async def associate(
    item_id: int, payload: EpisodeAssociationRequest, session: Annotated[AsyncSession, Depends(get_session)]
) -> EpisodeAssociationResponse:
    try:
        target_id = await associate_episode(
            session, item_id, payload.target_item_id, payload.expected_revision, payload.target_expected_revision
        )
        await session.commit()
        return EpisodeAssociationResponse(item_id=target_id)
    except Exception:
        await session.rollback()
        raise
