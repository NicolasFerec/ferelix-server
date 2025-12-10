"""User profile endpoints (authenticated users)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.dependencies import get_current_active_user
from app.models import User, UserSchema, UserUpdate

router = APIRouter(prefix="/api/v1/users", tags=["users"])


@router.get("/me", response_model=UserSchema)
async def get_current_user_info(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> User:
    """Get current user's information.

    Args:
        current_user: The authenticated user

    Returns:
        Current user's profile
    """
    return current_user


@router.patch("/me", response_model=UserSchema)
async def update_current_user(
    user_update: UserUpdate,
    current_user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    """Update current user's information.

    Args:
        user_update: User update data
        current_user: The authenticated user
        session: Database session

    Returns:
        Updated user profile
    """
    if user_update.username is not None:
        # Check if username is already taken by another user (case-insensitive)
        existing = await session.scalar(
            select(User).where(
                func.lower(User.username) == func.lower(user_update.username),
                User.id != current_user.id,
            )
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already in use",
            )
        current_user.username = user_update.username

    if user_update.email is not None:
        # Check if email is already taken by another user
        existing = await session.scalar(
            select(User).where(
                User.email == user_update.email, User.id != current_user.id
            )
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already in use",
            )
        current_user.email = user_update.email

    if user_update.password is not None:
        current_user.password = user_update.password

    if user_update.language is not None:
        current_user.language = user_update.language

    # Note: Regular users cannot change their is_active status

    await session.commit()
    await session.refresh(current_user)

    return current_user
