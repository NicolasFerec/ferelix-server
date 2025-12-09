"""First-run setup service for admin account creation."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_maker, get_session
from app.models import User, UserSchema

router = APIRouter(prefix="/api/v1/setup", tags=["setup"])


class AdminSetupRequest(BaseModel):
    """Request schema for first-run admin setup."""

    username: str
    email: str
    password: str
    language: str = "en"


async def is_setup_complete() -> bool:
    """Check if initial setup has been completed.

    Returns:
        True if at least one user exists, False otherwise
    """
    async with async_session_maker() as session:
        result = await session.execute(select(User).limit(1))
        user = result.scalar_one_or_none()
        return user is not None


@router.get("/status")
async def get_setup_status() -> dict[str, bool]:
    """Check if initial setup is required.

    Returns:
        Dictionary with setup_complete status
    """
    return {"setup_complete": await is_setup_complete()}


@router.post("/admin", response_model=UserSchema, status_code=status.HTTP_201_CREATED)
async def create_first_admin(
    admin_data: AdminSetupRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    """Create the first admin account (only works if no users exist).

    Args:
        admin_data: Admin account credentials
        session: Database session

    Returns:
        Created admin user

    Raises:
        HTTPException: If setup already complete or validation fails
    """
    # Check if setup already complete
    if await is_setup_complete():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Setup already complete. Use the registration endpoint to create additional users.",
        )

    # Create first admin user
    admin_user = User(
        username=admin_data.username,
        email=admin_data.email,
        password=admin_data.password,
        is_admin=True,
        is_active=True,
        language=admin_data.language,
    )

    session.add(admin_user)
    await session.commit()
    await session.refresh(admin_user)

    return admin_user
