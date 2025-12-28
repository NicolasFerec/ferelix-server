"""API tests for media endpoints."""

from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AudioTrack, Library, MediaFile, User, VideoTrack


@pytest.fixture
async def test_media_file(
    db_session: AsyncSession,
    test_library: Library,
) -> MediaFile:
    """Create a test media file with tracks."""
    media_file = MediaFile(
        file_path="/test/media/path/movie.mp4",
        file_name="movie.mp4",
        file_size=1073741824,
        file_extension=".mp4",
        duration=7200.0,
        width=1920,
        height=1080,
        codec="h264",
        bitrate=5000000,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        scanned_at=datetime.now(UTC),
    )
    db_session.add(media_file)
    await db_session.flush()

    # Add video track
    video_track = VideoTrack(
        media_file_id=media_file.id,
        stream_index=0,
        codec="h264",
        width=1920,
        height=1080,
        bitrate=4500000,
        fps=24.0,
        is_default=True,
        profile="High",
        level="4.1",
        pixel_format="yuv420p",
        bit_depth=8,
    )
    db_session.add(video_track)

    # Add audio track
    audio_track = AudioTrack(
        media_file_id=media_file.id,
        stream_index=1,
        codec="aac",
        channels=2,
        sample_rate=48000,
        bitrate=128000,
        language="en",
        is_default=True,
    )
    db_session.add(audio_track)

    await db_session.commit()
    await db_session.refresh(media_file)
    return media_file


class TestGetLibraries:
    """Tests for GET /api/v1/libraries."""

    @pytest.mark.asyncio
    async def test_get_libraries_authenticated(
        self,
        client: AsyncClient,
        test_user: User,
        auth_headers: dict[str, str],
        test_library: Library,
    ) -> None:
        """Test getting libraries as authenticated user."""
        response = await client.get(
            "/api/v1/libraries",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1

    @pytest.mark.asyncio
    async def test_get_libraries_unauthenticated(
        self,
        client: AsyncClient,
    ) -> None:
        """Test getting libraries without authentication fails."""
        response = await client.get("/api/v1/libraries")

        assert response.status_code == 401


class TestGetLibraryItems:
    """Tests for GET /api/v1/libraries/{id}/items."""

    @pytest.mark.asyncio
    async def test_get_library_items_empty(
        self,
        client: AsyncClient,
        test_user: User,
        auth_headers: dict[str, str],
        test_library: Library,
    ) -> None:
        """Test getting items from empty library."""
        response = await client.get(
            f"/api/v1/libraries/{test_library.id}/items",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        # Returns a list directly
        assert isinstance(data, list)
        assert len(data) == 0

    @pytest.mark.asyncio
    async def test_get_library_items_not_found(
        self,
        client: AsyncClient,
        test_user: User,
        auth_headers: dict[str, str],
    ) -> None:
        """Test getting items from non-existent library."""
        response = await client.get(
            "/api/v1/libraries/99999/items",
            headers=auth_headers,
        )

        assert response.status_code == 404


class TestGetMediaFiles:
    """Tests for GET /api/v1/media-files."""

    @pytest.mark.asyncio
    async def test_get_media_files_authenticated(
        self,
        client: AsyncClient,
        test_user: User,
        auth_headers: dict[str, str],
        test_media_file: MediaFile,
    ) -> None:
        """Test getting media files as authenticated user."""
        response = await client.get(
            "/api/v1/media-files",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        # Returns a list directly
        assert isinstance(data, list)
        assert len(data) >= 1

    @pytest.mark.asyncio
    async def test_get_media_files_pagination(
        self,
        client: AsyncClient,
        test_user: User,
        auth_headers: dict[str, str],
        test_media_file: MediaFile,
    ) -> None:
        """Test pagination parameters."""
        response = await client.get(
            "/api/v1/media-files?skip=0&limit=10",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        # Returns a list directly
        assert isinstance(data, list)


class TestGetMediaFile:
    """Tests for GET /api/v1/media/{id}."""

    @pytest.mark.asyncio
    async def test_get_media_file_success(
        self,
        client: AsyncClient,
        test_user: User,
        auth_headers: dict[str, str],
        test_media_file: MediaFile,
    ) -> None:
        """Test getting a specific media file."""
        response = await client.get(
            f"/api/v1/media/{test_media_file.id}",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["file_name"] == test_media_file.file_name
        assert "video_tracks" in data
        assert "audio_tracks" in data

    @pytest.mark.asyncio
    async def test_get_media_file_not_found(
        self,
        client: AsyncClient,
        test_user: User,
        auth_headers: dict[str, str],
    ) -> None:
        """Test getting non-existent media file."""
        response = await client.get(
            "/api/v1/media/99999",
            headers=auth_headers,
        )

        assert response.status_code == 404


class TestPlaybackInfo:
    """Tests for POST /api/v1/playback-info/{id}."""

    @pytest.fixture
    def device_profile(self) -> dict[str, Any]:
        """Sample device profile for playback tests."""
        return {
            "Name": "Test Device",
            "Id": "test-device-001",
            "DirectPlayProfiles": [
                {
                    "Type": "Video",
                    "Container": "mp4,mkv,webm",
                    "VideoCodec": "h264,hevc,vp9",
                    "AudioCodec": "aac,mp3,opus",
                },
            ],
            "CodecProfiles": [],
        }

    @pytest.mark.asyncio
    async def test_get_playback_info_success(
        self,
        client: AsyncClient,
        test_user: User,
        auth_headers: dict[str, str],
        test_media_file: MediaFile,
        device_profile: dict[str, Any],
    ) -> None:
        """Test getting playback info."""
        response = await client.post(
            f"/api/v1/playback-info/{test_media_file.id}",
            headers=auth_headers,
            json={
                "DeviceProfile": device_profile,
                "EnableDirectPlay": True,
                "EnableDirectStream": True,
                "EnableTranscoding": True,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "MediaSources" in data
        assert len(data["MediaSources"]) == 1

        source = data["MediaSources"][0]
        assert "PlayMethod" in source
        assert "MediaStreams" in source

    @pytest.mark.asyncio
    async def test_get_playback_info_direct_play(
        self,
        client: AsyncClient,
        test_user: User,
        auth_headers: dict[str, str],
        test_media_file: MediaFile,
        device_profile: dict[str, Any],
    ) -> None:
        """Test playback info returns direct play for compatible format."""
        response = await client.post(
            f"/api/v1/playback-info/{test_media_file.id}",
            headers=auth_headers,
            json={
                "DeviceProfile": device_profile,
                "EnableDirectPlay": True,
                "EnableDirectStream": True,
                "EnableTranscoding": True,
            },
        )

        assert response.status_code == 200
        data = response.json()
        source = data["MediaSources"][0]
        # H264/AAC in MP4 should direct play
        assert source["PlayMethod"] == "DirectPlay"

    @pytest.mark.asyncio
    async def test_get_playback_info_not_found(
        self,
        client: AsyncClient,
        test_user: User,
        auth_headers: dict[str, str],
        device_profile: dict[str, Any],
    ) -> None:
        """Test playback info for non-existent media."""
        response = await client.post(
            "/api/v1/playback-info/99999",
            headers=auth_headers,
            json={
                "DeviceProfile": device_profile,
                "EnableDirectPlay": True,
                "EnableDirectStream": True,
                "EnableTranscoding": True,
            },
        )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_playback_info_with_resolution_override(
        self,
        client: AsyncClient,
        test_user: User,
        auth_headers: dict[str, str],
        test_media_file: MediaFile,
        device_profile: dict[str, Any],
    ) -> None:
        """Test playback info with resolution override."""
        response = await client.post(
            f"/api/v1/playback-info/{test_media_file.id}",
            headers=auth_headers,
            json={
                "DeviceProfile": device_profile,
                "EnableDirectPlay": True,
                "EnableDirectStream": True,
                "EnableTranscoding": True,
                "RequestedResolution": {"width": 1280, "height": 720},
            },
        )

        assert response.status_code == 200
        data = response.json()
        source = data["MediaSources"][0]
        # Resolution override should force transcode
        assert source["PlayMethod"] == "Transcode"
