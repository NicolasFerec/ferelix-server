"""Authentication endpoints for user registration, login, and token refresh."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.dependencies import get_current_user
from app.models import RefreshToken, User, UserCreate, UserSchema
from app.services.auth import (
    create_access_token,
    create_refresh_token,
    get_password_hash,
    hash_token,
    verify_password,
    verify_token,
)

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])


class LoginRequest(BaseModel):
    """Request schema for user login."""

    username: str
    password: str
    device_info: str | None = None


class TokenResponse(BaseModel):
    """Response schema for token endpoints."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserSchema


class RefreshRequest(BaseModel):
    """Request schema for token refresh."""

    refresh_token: str


@router.post(
    "/register", response_model=UserSchema, status_code=status.HTTP_201_CREATED
)
async def register(
    user_data: UserCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    """Register a new user account.

    Args:
        user_data: User registration data
        session: Database session

    Returns:
        The created user (without password)

    Raises:
        HTTPException: If username or email already exists
    """
    # Check if username exists
    existing = await session.scalar(
        select(User).where(User.username == user_data.username)
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered",
        )

    # Check if email exists
    existing = await session.scalar(select(User).where(User.email == user_data.email))
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    # Create new user
    new_user = User(
        username=user_data.username,
        email=user_data.email,
        hashed_password=get_password_hash(user_data.password),
        is_admin=user_data.is_admin,
        is_active=True,
    )

    session.add(new_user)
    await session.commit()
    await session.refresh(new_user)

    return new_user


@router.post("/login", response_model=TokenResponse)
async def login(
    login_data: LoginRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TokenResponse:
    """Authenticate user and return access + refresh tokens.

    Args:
        login_data: Login credentials
        session: Database session

    Returns:
        Access token, refresh token, and user info

    Raises:
        HTTPException: If credentials are invalid
    """
    # Get user by username
    user = await session.scalar(
        select(User).where(User.username == login_data.username)
    )

    if not user or not verify_password(login_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user account",
        )

    # Create tokens
    access_token = create_access_token(data={"sub": str(user.id)})
    refresh_token_str = create_refresh_token(data={"sub": str(user.id)})

    # Store refresh token in database
    refresh_token = RefreshToken(
        user_id=user.id,
        token=hash_token(refresh_token_str),
        expires_at=datetime.now(UTC) + timedelta(days=7),
        device_info=login_data.device_info,
    )
    session.add(refresh_token)
    await session.commit()

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token_str,
        user=UserSchema.model_validate(user),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    refresh_data: RefreshRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TokenResponse:
    """Refresh access token using refresh token.

    Args:
        refresh_data: Refresh token
        session: Database session

    Returns:
        New access token, new refresh token, and user info

    Raises:
        HTTPException: If refresh token is invalid or expired
    """
    # Verify refresh token
    payload = verify_token(refresh_data.refresh_token, token_type="refresh")
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id_str = payload.get("sub")
    if user_id_str is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )
    user_id = int(user_id_str)

    # Get user
    user = await session.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    # Verify refresh token exists in database
    hashed = hash_token(refresh_data.refresh_token)
    stored_token = await session.scalar(
        select(RefreshToken).where(
            RefreshToken.user_id == user_id,
            RefreshToken.token == hashed,
            RefreshToken.expires_at > datetime.now(UTC),
        )
    )

    if not stored_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token not found or expired",
        )

    # Update last used timestamp
    stored_token.last_used_at = datetime.now(UTC)

    # Create new tokens
    access_token = create_access_token(data={"sub": str(user.id)})
    new_refresh_token_str = create_refresh_token(data={"sub": str(user.id)})

    # Store new refresh token and delete old one
    await session.delete(stored_token)
    new_refresh_token = RefreshToken(
        user_id=user.id,
        token=hash_token(new_refresh_token_str),
        expires_at=datetime.now(UTC) + timedelta(days=7),
        device_info=stored_token.device_info,
    )
    session.add(new_refresh_token)
    await session.commit()

    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh_token_str,
        user=UserSchema.model_validate(user),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    refresh_data: RefreshRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    """Logout user by revoking refresh token.

    Args:
        refresh_data: Refresh token to revoke
        current_user: Currently authenticated user
        session: Database session
    """
    # Delete refresh token from database
    hashed = hash_token(refresh_data.refresh_token)
    result = await session.execute(
        select(RefreshToken).where(
            RefreshToken.user_id == current_user.id,
            RefreshToken.token == hashed,
        )
    )
    token = result.scalar_one_or_none()
    if token:
        await session.delete(token)
        await session.commit()
