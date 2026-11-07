"""Bounded catalogue queries, independent from playback detail loading."""

from collections.abc import Sequence

from sqlalchemy import Select, and_, func, literal, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only, raiseload

from app.models import Library, MediaCardSchema, MediaFile, MediaView, MediaViewSchema, RecommendationRow
from app.services.recommendation_row import apply_filter_criteria, recommendation_ordering


def media_card_query(user_id: int) -> Select[MediaFile, MediaView]:
    return (
        select(MediaFile, MediaView)
        .outerjoin(MediaView, and_(MediaView.media_file_id == MediaFile.id, MediaView.user_id == user_id))
        .options(
            load_only(
                MediaFile.id,
                MediaFile.file_name,
                MediaFile.file_extension,
                MediaFile.duration,
                MediaFile.width,
                MediaFile.height,
                MediaFile.codec,
                MediaFile.bitrate,
                MediaFile.created_at,
                raiseload=True,
            ),
            raiseload("*"),
        )
    )


def media_card(media_file: MediaFile, view: MediaView | None) -> MediaCardSchema:
    card = MediaCardSchema.model_validate(media_file)
    card.user_view = MediaViewSchema.model_validate(view) if view else None
    return card


async def recommendation_cards(
    session: AsyncSession, user_id: int, rows: Sequence[tuple[RecommendationRow, Library]]
) -> dict[int, list[MediaCardSchema]]:
    """Fetch all row cards and current-user progress in one bounded SQL request."""
    if not rows:
        return {}
    selections = []
    for row, library in rows:
        criteria = {**row.filter_criteria, "limit": min(row.filter_criteria.get("limit", 24), 100)}
        ranked = apply_filter_criteria(
            select(MediaFile.id, func.row_number().over(order_by=recommendation_ordering(criteria)).label("position")),
            criteria,
            library.path,
        ).subquery()
        selections.append(select(literal(row.id).label("row_id"), ranked.c.id, ranked.c.position))
    candidates = union_all(*selections).subquery()
    result = await session.execute(
        media_card_query(user_id)
        .join(candidates, candidates.c.id == MediaFile.id)
        .add_columns(candidates.c.row_id)
        .order_by(candidates.c.row_id, candidates.c.position)
    )
    cards: dict[int, list[MediaCardSchema]] = {row.id: [] for row, _library in rows}
    for media_file, view, row_id in result:
        cards[row_id].append(media_card(media_file, view))
    return cards
