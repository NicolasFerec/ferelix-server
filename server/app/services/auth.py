"""Authentication service for JWT token management and token hashing."""

import contextlib
import hashlib
import os
import secrets
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from jose import JWTError, jwt


def load_secret_key() -> str:
    """Keep a private signing key across reloads without a shared public default."""
    configured = os.getenv("SECRET_KEY")
    if configured:
        return configured
    default_path = Path("/config/.secret_key") if Path("/config").is_dir() else Path(".secret_key")
    path = Path(os.getenv("FERELIX_SECRET_KEY_FILE", str(default_path)))
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        # Publish a complete file atomically; simultaneous workers reuse the winner.
        descriptor, temporary = tempfile.mkstemp(dir=path.parent)
        try:
            with os.fdopen(descriptor, "w") as file:
                file.write(secrets.token_hex(32))
            with contextlib.suppress(FileExistsError):
                os.link(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
    key = path.read_text().strip()
    if not key:
        raise RuntimeError(f"Empty JWT signing key file: {path}")
    return key


# JWT configuration
SECRET_KEY = load_secret_key()
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """Create a JWT access token.

    Args:
        data: The data to encode in the token (typically {"sub": user_id})
        expires_delta: Optional custom expiration time

    Returns:
        The encoded JWT token
    """
    to_encode = data.copy()
    to_encode.setdefault("cv", 0)
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": expire, "type": "access"})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def create_refresh_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """Create a JWT refresh token.

    Args:
        data: The data to encode in the token (typically {"sub": user_id})
        expires_delta: Optional custom expiration time

    Returns:
        The encoded JWT refresh token
    """
    to_encode = data.copy()
    to_encode.setdefault("cv", 0)
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

    # Add unique jti (JWT ID) to ensure token uniqueness
    to_encode.update({"exp": expire, "type": "refresh", "jti": str(uuid.uuid4())})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def verify_token(token: str, token_type: str = "access") -> dict | None:
    """Verify and decode a JWT token.

    Args:
        token: The JWT token to verify
        token_type: Expected token type ("access" or "refresh")

    Returns:
        The decoded token payload if valid, None otherwise
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM], options={"require_exp": True})
        if payload.get("type") != token_type:
            return None
        version = payload.get("cv", 0)
        if type(version) is not int or version < 0:
            return None
        subject = payload.get("sub")
        if not isinstance(subject, str) or not subject.isascii() or not subject.isdecimal() or int(subject) <= 0:
            return None
        return payload
    except JWTError:
        return None


def hash_token(token: str) -> str:
    """Hash a token for secure storage in database using SHA256.

    Args:
        token: The token to hash

    Returns:
        The hashed token (hex digest)
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
