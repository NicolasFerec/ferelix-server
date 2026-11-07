"""Logical catalogue, including seasons and episodes without local files."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import String, case, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.dependencies import get_current_active_user
from app.models import Artwork, MediaItem, MediaItemFile, User
from app.models.metadata import ItemCardSchema, ItemDetailSchema, ItemKind
from app.services.item_catalogue import get_item_detail, item_cards, require_item, visible_item_filter
from app.services.metadata import artwork_path

router = APIRouter(prefix="/api/v1/items", tags=["items"])
Session = Annotated[AsyncSession, Depends(get_session)]
CurrentUser = Annotated[User, Depends(get_current_active_user)]


@router.get("", response_model=list[ItemCardSchema])
async def list_items(
    session: Session,
    user: CurrentUser,
    library_id: int | None = None,
    kind: ItemKind | None = None,
    parent_id: int | None = None,
    collection_id: int | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 48,
) -> list[ItemCardSchema]:
    query = select(MediaItem.id).where(visible_item_filter(library_id))
    for column, value in (
        (MediaItem.kind, kind),
        (MediaItem.parent_id, parent_id),
        (MediaItem.collection_id, collection_id),
    ):
        if value is not None:
            query = query.where(column == value)
    if q is not None:
        term = q.strip()
        if not term:
            return []
        query = query.where(
            or_(
                MediaItem.title.icontains(term, autoescape=True),
                MediaItem.original_title.icontains(term, autoescape=True),
                cast(MediaItem.aliases, String).icontains(term, autoescape=True),
            )
        )
        query = query.order_by(
            case(
                (func.lower(MediaItem.title) == term.lower(), 0),
                (MediaItem.title.istartswith(term, autoescape=True), 1),
                else_=2,
            ),
            func.length(MediaItem.title),
        )
    elif kind is None and parent_id is None and collection_id is None:
        query = query.where(MediaItem.kind.in_(("movie", "series")))
    if collection_id is not None:
        query = query.order_by(MediaItem.release_date.asc().nullslast())
    query = (
        query
        .order_by(
            MediaItem.season_number.asc().nullslast(),
            MediaItem.episode_number.asc().nullslast(),
            func.coalesce(MediaItem.sort_title, MediaItem.title),
            MediaItem.id,
        )
        .offset(skip)
        .limit(limit)
    )
    return await item_cards(session, user.id, list(await session.scalars(query)))


@router.get("/for-file/{media_id}", response_model=ItemDetailSchema | None)
async def item_for_file(media_id: int, session: Session, user: CurrentUser) -> ItemDetailSchema | None:
    item_id = await session.scalar(
        select(MediaItem.id)
        .join(MediaItemFile, MediaItemFile.item_id == MediaItem.id)
        .where(MediaItemFile.media_file_id == media_id, visible_item_filter())
        .order_by(MediaItemFile.position, MediaItem.id)
        .limit(1)
    )
    return await get_item_detail(session, user.id, item_id) if item_id else None


@router.get("/{item_id}", response_model=ItemDetailSchema)
async def item_detail(item_id: int, session: Session, user: CurrentUser) -> ItemDetailSchema:
    return await get_item_detail(session, user.id, item_id)


@router.get("/{item_id}/images/{role}")
async def item_image(item_id: int, role: str, session: Session, _user: CurrentUser) -> FileResponse:
    await require_item(session, item_id)
    artwork = await session.scalar(select(Artwork).where(Artwork.item_id == item_id, Artwork.role == role))
    if artwork is None:
        raise HTTPException(404, "Artwork not found")
    path = artwork_path(artwork.path)
    if not path.is_file():
        raise HTTPException(404, "Artwork file is unavailable")
    return FileResponse(path, headers={"Cache-Control": "private, max-age=86400", "ETag": f'"{artwork.sha256}"'})
