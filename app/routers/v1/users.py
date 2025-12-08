"""User management endpoints (admin-only)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.dependencies import get_current_active_user, require_admin
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

    # Note: Regular users cannot change their is_active status

    await session.commit()
    await session.refresh(current_user)

    return current_user


@router.get("/", response_model=list[UserSchema])
async def list_users(
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
    skip: int = 0,
    limit: int = 100,
) -> list[User]:
    """List all users (admin only).

    Args:
        _admin: Admin user (dependency)
        session: Database session
        skip: Number of records to skip
        limit: Maximum number of records to return

    Returns:
        List of users
    """
    result = await session.execute(select(User).offset(skip).limit(limit))
    users = result.scalars().all()
    return list(users)


@router.get("/{user_id}", response_model=UserSchema)
async def get_user(
    user_id: int,
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    """Get user by ID (admin only).

    Args:
        user_id: User ID
        _admin: Admin user (dependency)
        session: Database session

    Returns:
        User profile

    Raises:
        HTTPException: If user not found
    """
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    return user


@router.patch("/{user_id}", response_model=UserSchema)
async def update_user(
    user_id: int,
    user_update: UserUpdate,
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    """Update user by ID (admin only).

    Args:
        user_id: User ID
        user_update: User update data
        _admin: Admin user (dependency)
        session: Database session

    Returns:
        Updated user profile

    Raises:
        HTTPException: If user not found
    """
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    if user_update.email is not None:
        # Check if email is already taken by another user
        existing = await session.scalar(
            select(User).where(User.email == user_update.email, User.id != user_id)
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already in use",
            )
        user.email = user_update.email

    if user_update.password is not None:
        user.password = user_update.password

    if user_update.is_active is not None:
        user.is_active = user_update.is_active

    await session.commit()
    await session.refresh(user)

    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    """Delete user by ID (admin only).

    Args:
        user_id: User ID
        admin: Admin user (dependency)
        session: Database session

    Raises:
        HTTPException: If user not found or trying to delete self
    """
    if user_id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account",
        )

    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    await session.delete(user)
    await session.commit()
