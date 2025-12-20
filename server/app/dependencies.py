"""FastAPI dependencies for authentication and authorization."""

from typing import Annotated

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import User
from app.services.auth import verify_token

# HTTP Bearer scheme for JWT tokens
security = HTTPBearer(auto_error=False)


async def get_current_user(
    session: Annotated[AsyncSession, Depends(get_session)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)] = None,
    api_key: Annotated[str | None, Query(alias="api_key")] = None,
) -> User:
    """Get the current authenticated user from JWT token.

    Supports two authentication methods:
    1. Authorization header: Bearer <token>
    2. Query parameter: ?api_key=<token>

    Args:
        session: Database session
        credentials: HTTP Bearer credentials from header
        api_key: API key from query parameter

    Returns:
        The authenticated user

    Raises:
        HTTPException: If authentication fails
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # Extract token from header or query parameter
    token = None
    if credentials:
        token = credentials.credentials
    elif api_key:
        token = api_key

    if not token:
        raise credentials_exception

    # Verify token
    payload = verify_token(token, token_type="access")
    if payload is None:
        raise credentials_exception

    user_id_str = payload.get("sub")
    if user_id_str is None:
        raise credentials_exception
    user_id = int(user_id_str)

    # Get user from database
    user = await session.get(User, user_id)
    if user is None:
        raise credentials_exception

    return user


def get_current_active_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Get the current active user (must be active).

    Args:
        current_user: The current authenticated user

    Returns:
        The current user if active

    Raises:
        HTTPException: If user is inactive
    """
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user",
        )
    return current_user


async def get_optional_user(
    session: Annotated[AsyncSession, Depends(get_session)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)] = None,
    api_key: Annotated[str | None, Query(alias="api_key")] = None,
) -> User | None:
    """Get the current user if authenticated, None otherwise.

    This is useful for endpoints that work with or without authentication.

    Args:
        session: Database session
        credentials: HTTP Bearer credentials from header
        api_key: API key from query parameter

    Returns:
        The authenticated user or None
    """
    # Extract token from header or query parameter
    token = None
    if credentials:
        token = credentials.credentials
    elif api_key:
        token = api_key

    if not token:
        return None

    # Verify token
    payload = verify_token(token, token_type="access")
    if payload is None:
        return None

    user_id_str = payload.get("sub")
    if user_id_str is None:
        return None

    # Get user from database
    user = await session.get(User, int(user_id_str))
    return user


def require_admin(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> User:
    """Require the current user to be an admin.

    Args:
        current_user: The current active user

    Returns:
        The current user if admin

    Raises:
        HTTPException: If user is not an admin
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return current_user


# Global scheduler instance (set during app startup)
_scheduler_instance: AsyncIOScheduler | None = None


def set_scheduler(scheduler: AsyncIOScheduler) -> None:
    """Set the global scheduler instance.

    Called during app startup to make scheduler available to dependencies.

    Args:
        scheduler: The scheduler instance
    """
    global _scheduler_instance
    _scheduler_instance = scheduler


def get_scheduler() -> AsyncIOScheduler:
    """Get the scheduler instance.

    Returns:
        The scheduler instance

    Raises:
        HTTPException: If scheduler is not available
    """
    if _scheduler_instance is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Scheduler not available",
        )
    return _scheduler_instance
