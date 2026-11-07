"""Shared account invariants for self-service and administrator mutations."""

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RefreshToken, User


async def ensure_identity_available(
    session: AsyncSession, *, username: str | None = None, email: str | None = None, exclude_user_id: int | None = None
) -> None:
    for field, value in (("username", username), ("email", email)):
        if not value or not value.strip():
            continue
        column = User.username_normalized if field == "username" else User.email_normalized
        query = select(User.id).where(column == value.strip().casefold())
        if exclude_user_id is not None:
            query = query.where(User.id != exclude_user_id)
        with session.no_autoflush:
            existing_id = await session.scalar(query)
        if existing_id is not None:
            raise HTTPException(status_code=400, detail=f"{field.capitalize()} already in use")


async def commit_account_changes(session: AsyncSession) -> None:
    """Translate a DB uniqueness race into a usable conflict response."""
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Username or email already in use") from exc


async def flush_account_changes(session: AsyncSession) -> None:
    """Keep pending identity changes in the password transaction, including conflicts."""
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Username or email already in use") from exc


async def change_password(
    session: AsyncSession,
    user: User,
    password: str,
    *,
    current_password: str | None = None,
    require_current: bool = False,
) -> None:
    if require_current:
        if current_password is None:
            raise HTTPException(status_code=400, detail="Current password is required")
        if user.password != current_password:
            raise HTTPException(status_code=400, detail="Current password is incorrect")

    await flush_account_changes(session)

    # Compare-and-swap makes concurrent changes based on an old credential fail.
    # Every existing access/refresh/media token is tied to this version.
    version = await session.scalar(
        update(User)
        .where(User.id == user.id, User.credentials_version == user.credentials_version)
        .values(
            password=password,
            credentials_version=User.credentials_version + 1,
            updated_at=datetime.now(UTC).replace(tzinfo=None),
        )
        .returning(User.credentials_version)
        .execution_options(synchronize_session=False)
    )
    if version is None:
        raise HTTPException(status_code=409, detail="Credentials changed; sign in again before retrying")
    await session.execute(delete(RefreshToken).where(RefreshToken.user_id == user.id))
    await session.refresh(user)
