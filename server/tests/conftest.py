"""Shared pytest fixtures for Ferelix server tests."""

import asyncio
import os
from collections.abc import AsyncGenerator, Generator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import Base, Library, User

# Set test environment before importing app modules
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["SECRET_KEY"] = "test-secret-key-for-testing-only"


# Create test engine (in-memory SQLite)
test_engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    echo=False,
)

test_session_maker = async_sessionmaker(
    test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop]:
    """Create event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession]:
    """Create a fresh database session for each test."""
    # Create all tables
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Create session
    async with test_session_maker() as session:
        yield session

    # Drop all tables after test
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient]:
    """Create test client with database session override."""
    from unittest.mock import MagicMock

    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    import app.database as database_module
    import app.services.setup as setup_module
    from app.database import get_session
    from app.dependencies import get_scheduler, set_scheduler
    from app.main import app

    # Create and configure mock scheduler
    mock_scheduler = MagicMock(spec=AsyncIOScheduler)
    mock_scheduler.get_jobs.return_value = []
    mock_scheduler.get_job.return_value = None
    set_scheduler(mock_scheduler)

    # Override the async_session_maker in database module to use test session
    original_session_maker = database_module.async_session_maker
    database_module.async_session_maker = test_session_maker

    # Also override in setup service (which imports it directly)
    original_setup_session_maker = setup_module.async_session_maker
    setup_module.async_session_maker = test_session_maker

    # Override database session dependency
    def override_get_session() -> Generator[AsyncSession]:
        yield db_session

    # Override scheduler dependency
    def override_get_scheduler() -> AsyncIOScheduler:
        return mock_scheduler

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_scheduler] = override_get_scheduler

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    # Clean up overrides
    app.dependency_overrides.clear()
    database_module.async_session_maker = original_session_maker
    setup_module.async_session_maker = original_setup_session_maker


@pytest.fixture
async def test_user(db_session: AsyncSession) -> User:
    """Create a test user."""
    user = User(
        username="testuser",
        email="test@example.com",
        password="testpassword123",
        is_admin=False,
        is_active=True,
        language="en",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def admin_user(db_session: AsyncSession) -> User:
    """Create a test admin user."""
    user = User(
        username="admin",
        email="admin@example.com",
        password="adminpassword123",
        is_admin=True,
        is_active=True,
        language="en",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def inactive_user(db_session: AsyncSession) -> User:
    """Create an inactive test user."""
    user = User(
        username="inactive",
        email="inactive@example.com",
        password="password123",
        is_admin=False,
        is_active=False,
        language="en",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def test_library(db_session: AsyncSession) -> Library:
    """Create a test library."""
    library = Library(
        name="Test Library",
        path="/test/media/path",
        library_type="movie",
        enabled=True,
        created_at=datetime.now(UTC),
    )
    db_session.add(library)
    await db_session.commit()
    await db_session.refresh(library)
    return library


@pytest.fixture
def auth_headers(test_user: User) -> dict[str, str]:
    """Get authentication headers for test user."""
    from app.services.auth import create_access_token

    token = create_access_token(data={"sub": str(test_user.id)})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_auth_headers(admin_user: User) -> dict[str, str]:
    """Get authentication headers for admin user."""
    from app.services.auth import create_access_token

    token = create_access_token(data={"sub": str(admin_user.id)})
    return {"Authorization": f"Bearer {token}"}


# FFmpeg mocking fixtures
@pytest.fixture
def mock_static_ffmpeg_paths() -> Generator[MagicMock]:
    """Mock static_ffmpeg.run.get_or_fetch_platform_executables_else_raise to return fake paths."""
    with patch("static_ffmpeg.run.get_or_fetch_platform_executables_else_raise") as mock:
        # Return fake paths for ffmpeg and ffprobe
        mock.return_value = ("/usr/bin/ffmpeg", "/usr/bin/ffprobe")
        yield mock


@pytest.fixture
def mock_ffprobe() -> Generator[MagicMock]:
    """Mock ffprobe subprocess call."""
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = """{
        "format": {
            "duration": "120.5",
            "size": "1073741824",
            "bit_rate": "7000000"
        },
        "streams": [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
                "bit_rate": "6000000",
                "r_frame_rate": "24/1",
                "profile": "High",
                "level": 41,
                "pix_fmt": "yuv420p"
            },
            {
                "index": 1,
                "codec_type": "audio",
                "codec_name": "aac",
                "channels": 2,
                "sample_rate": "48000",
                "bit_rate": "128000"
            }
        ]
    }"""
    mock_result.stderr = ""

    with patch("subprocess.run", return_value=mock_result) as mock:
        yield mock


@pytest.fixture
def mock_ffmpeg_transcode() -> Generator[AsyncMock]:
    """Mock FFmpeg transcoding process."""
    mock_process = AsyncMock()
    mock_process.returncode = 0
    mock_process.stdout = AsyncMock()
    mock_process.stdout.readline = AsyncMock(return_value=b"")
    mock_process.stderr = AsyncMock()
    mock_process.stderr.readline = AsyncMock(return_value=b"")
    mock_process.wait = AsyncMock(return_value=0)
    mock_process.terminate = MagicMock()

    with patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock:
        yield mock


@pytest.fixture
def sample_device_profile() -> dict[str, Any]:
    """Sample device profile for playback tests."""
    return {
        "DirectPlayProfiles": [
            {
                "Type": "Video",
                "Container": "mp4,mkv,webm",
                "VideoCodec": "h264,hevc,vp9",
                "AudioCodec": "aac,mp3,opus",
            },
            {
                "Type": "Audio",
                "Container": "mp3,flac,ogg",
                "AudioCodec": "mp3,flac,vorbis",
            },
        ],
        "CodecProfiles": [
            {
                "Type": "Video",
                "Codec": "h264",
                "Conditions": [
                    {
                        "Condition": "LessThanEqual",
                        "Property": "VideoLevel",
                        "Value": "51",
                        "IsRequired": True,
                    },
                    {
                        "Condition": "LessThanEqual",
                        "Property": "Width",
                        "Value": "3840",
                        "IsRequired": True,
                    },
                ],
            },
        ],
    }
