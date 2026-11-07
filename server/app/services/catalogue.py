"""Bounded catalogue queries, independent from playback detail loading."""

from collections.abc import Sequence

from sqlalchemy import ColumnElement, Select, and_, func, literal, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only, raiseload

from app.models import (
    Library,
    MediaCardSchema,
    MediaFile,
    MediaView,
    MediaViewSchema,
    RecommendationRow,
    WatchlistEntry,
)
from app.services.recommendation_row import apply_filter_criteria, recommendation_ordering


def watchlist_membership(user_id: int) -> ColumnElement[bool]:
    return (
        select(WatchlistEntry.id)
        .where(WatchlistEntry.user_id == user_id, WatchlistEntry.media_file_id == MediaFile.id)
        .exists()
    )


def visible_media_filter(library_id: int | None = None) -> ColumnElement[bool]:
    """Match an enabled library by a literal directory prefix, never a LIKE pattern."""
    prefix = func.rtrim(Library.path, "/").concat("/")
    library = select(Library.id).where(
        Library.enabled.is_(True),
        func.substr(MediaFile.file_path, 1, func.length(prefix)) == prefix,
    )
    if library_id is not None:
        library = library.where(Library.id == library_id)
    return and_(MediaFile.deleted_at.is_(None), library.exists())


def media_card_query(user_id: int) -> Select[MediaFile, MediaView, bool]:
    return (
        select(MediaFile, MediaView, watchlist_membership(user_id))
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


def media_card(media_file: MediaFile, view: MediaView | None, in_watchlist: bool = False) -> MediaCardSchema:
    card = MediaCardSchema.model_validate(media_file)
    card.user_view = MediaViewSchema.model_validate(view) if view else None
    card.in_watchlist = in_watchlist
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
    for media_file, view, in_watchlist, row_id in result:
        cards[row_id].append(media_card(media_file, view, in_watchlist))
    return cards
