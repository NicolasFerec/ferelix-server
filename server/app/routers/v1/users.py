"""User profile endpoints (authenticated users)."""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.dependencies import get_current_active_user
from app.models import User, UserSchema, UserUpdate
from app.services.profile_images import delete_profile_image, save_profile_image

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


@router.get("/{user_id}/profile-image")
async def get_profile_image(
    user_id: int,
    _current_user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FileResponse:
    """Serve a user profile image to authenticated users."""
    user = await session.get(User, user_id)
    if not user or not user.profile_image_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile image not found")
    if not Path(user.profile_image_path).exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile image not found")

    return FileResponse(
        user.profile_image_path,
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.put("/me/profile-image", response_model=UserSchema)
async def upload_current_user_profile_image(
    current_user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    image: Annotated[UploadFile, File()],
) -> User:
    """Upload or replace the current user's profile image."""
    previous_image_path = current_user.profile_image_path
    current_user.profile_image_path = await save_profile_image(current_user.id, image)
    await session.commit()
    await session.refresh(current_user)
    delete_profile_image(previous_image_path)
    return current_user


@router.delete("/me/profile-image", response_model=UserSchema)
async def delete_current_user_profile_image(
    current_user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    """Remove the current user's profile image."""
    previous_image_path = current_user.profile_image_path
    current_user.profile_image_path = None
    await session.commit()
    await session.refresh(current_user)
    delete_profile_image(previous_image_path)
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

    # Handle email update (can be None to clear email, or a string)
    if "email" in user_update.model_fields_set:
        # Normalize email: convert empty string to None, strip whitespace
        email_value = (
            user_update.email.strip() if isinstance(user_update.email, str) and user_update.email.strip() else None
        )

        # Update email (can be None to clear it)
        current_user.email = email_value

    if user_update.password is not None:
        current_user.password = user_update.password

    if user_update.language is not None:
        current_user.language = user_update.language

    await session.commit()
    await session.refresh(current_user)

    return current_user
