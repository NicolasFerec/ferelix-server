"""API tests for dashboard endpoints."""

from io import BytesIO
from pathlib import Path

import pytest
from httpx import AsyncClient
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AudioTrack, Library, MediaFile, MediaView, PlaybackSession, RefreshToken, TranscodingJob, User
from app.models.playback_session import PlaybackSessionStatus
from app.models.transcoding import TranscodingJobStatus, TranscodingJobType
from app.services import profile_images
from app.services.transcoding.hardware import HardwareAccelerationStatus, HardwareDeviceInfo


def make_png_bytes(width: int = 20, height: int = 12) -> bytes:
    """Create a small valid PNG image for upload tests."""
    buffer = BytesIO()
    Image.new("RGB", (width, height), (220, 40, 80)).save(buffer, format="PNG")
    return buffer.getvalue()


class TestDashboardAccess:
    """Tests for dashboard access control."""

    @pytest.mark.asyncio
    async def test_dashboard_requires_admin(
        self,
        client: AsyncClient,
        test_user: User,
        auth_headers: dict[str, str],
    ) -> None:
        """Test that non-admin users cannot access dashboard."""
        response = await client.get(
            "/api/v1/dashboard/libraries",
            headers=auth_headers,
        )

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_dashboard_admin_access(
        self,
        client: AsyncClient,
        admin_user: User,
        admin_auth_headers: dict[str, str],
    ) -> None:
        """Test that admin users can access dashboard."""
        response = await client.get(
            "/api/v1/dashboard/libraries",
            headers=admin_auth_headers,
        )

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_dashboard_unauthenticated(
        self,
        client: AsyncClient,
    ) -> None:
        """Test that unauthenticated requests are rejected."""
        response = await client.get("/api/v1/dashboard/libraries")

        assert response.status_code == 401


class TestLibraryManagement:
    """Tests for library management endpoints."""

    @pytest.mark.asyncio
    async def test_get_libraries_empty(
        self,
        client: AsyncClient,
        admin_user: User,
        admin_auth_headers: dict[str, str],
    ) -> None:
        """Test getting empty library list."""
        response = await client.get(
            "/api/v1/dashboard/libraries",
            headers=admin_auth_headers,
        )

        assert response.status_code == 200
        assert response.json() == []

    @pytest.mark.asyncio
    async def test_get_libraries_with_data(
        self,
        client: AsyncClient,
        admin_user: User,
        admin_auth_headers: dict[str, str],
        test_library: Library,
    ) -> None:
        """Test getting library list with data."""
        response = await client.get(
            "/api/v1/dashboard/libraries",
            headers=admin_auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == test_library.name
        assert data[0]["path"] == test_library.path

    @pytest.mark.asyncio
    async def test_create_library_success(
        self,
        client: AsyncClient,
        admin_user: User,
        admin_auth_headers: dict[str, str],
    ) -> None:
        """Test successful library creation."""
        response = await client.post(
            "/api/v1/dashboard/libraries",
            headers=admin_auth_headers,
            json={
                "name": "Movies",
                "path": "/media/movies",
                "library_type": "movie",
                "enabled": True,
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Movies"
        assert data["path"] == "/media/movies"
        assert data["library_type"] == "movie"
        assert data["enabled"] is True

    @pytest.mark.asyncio
    async def test_create_library_duplicate_path(
        self,
        client: AsyncClient,
        admin_user: User,
        admin_auth_headers: dict[str, str],
        test_library: Library,
    ) -> None:
        """Test library creation with duplicate path fails."""
        response = await client.post(
            "/api/v1/dashboard/libraries",
            headers=admin_auth_headers,
            json={
                "name": "Different Name",
                "path": test_library.path,
                "library_type": "movie",
            },
        )

        assert response.status_code == 409

    @pytest.mark.asyncio
    async def test_update_library(
        self,
        client: AsyncClient,
        admin_user: User,
        admin_auth_headers: dict[str, str],
        test_library: Library,
    ) -> None:
        """Test library update."""
        response = await client.patch(
            f"/api/v1/dashboard/libraries/{test_library.id}",
            headers=admin_auth_headers,
            json={
                "name": "Updated Library",
                "enabled": False,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Updated Library"
        assert data["enabled"] is False

    @pytest.mark.asyncio
    async def test_update_library_not_found(
        self,
        client: AsyncClient,
        admin_user: User,
        admin_auth_headers: dict[str, str],
    ) -> None:
        """Test library update with invalid ID."""
        response = await client.patch(
            "/api/v1/dashboard/libraries/99999",
            headers=admin_auth_headers,
            json={"name": "Updated"},
        )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_library(
        self,
        client: AsyncClient,
        admin_user: User,
        admin_auth_headers: dict[str, str],
        test_library: Library,
    ) -> None:
        """Test library deletion."""
        response = await client.delete(
            f"/api/v1/dashboard/libraries/{test_library.id}",
            headers=admin_auth_headers,
        )

        assert response.status_code == 204

        # Verify deletion
        get_response = await client.get(
            "/api/v1/dashboard/libraries",
            headers=admin_auth_headers,
        )
        assert len(get_response.json()) == 0


class TestUserManagement:
    """Tests for user management endpoints."""

    @pytest.mark.asyncio
    async def test_get_users(
        self,
        client: AsyncClient,
        admin_user: User,
        admin_auth_headers: dict[str, str],
        test_user: User,
    ) -> None:
        """Test getting user list."""
        response = await client.get(
            "/api/v1/dashboard/users",
            headers=admin_auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        # Should have both admin and test user
        assert len(data) >= 2

    @pytest.mark.asyncio
    async def test_create_admin_user(
        self,
        client: AsyncClient,
        admin_user: User,
        admin_auth_headers: dict[str, str],
    ) -> None:
        """Test creating a new admin user."""
        response = await client.post(
            "/api/v1/dashboard/users",
            headers=admin_auth_headers,
            json={
                "username": "created-admin",
                "email": "created-admin@example.com",
                "password": "password123",
                "role": "admin",
                "language": "en",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["username"] == "created-admin"
        assert data["role"] == "admin"
        assert data["is_admin"] is True

    @pytest.mark.asyncio
    async def test_get_user_by_id(
        self,
        client: AsyncClient,
        admin_user: User,
        admin_auth_headers: dict[str, str],
        test_user: User,
    ) -> None:
        """Test getting a specific user."""
        response = await client.get(
            f"/api/v1/dashboard/users/{test_user.id}",
            headers=admin_auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["username"] == test_user.username

    @pytest.mark.asyncio
    async def test_update_user(
        self,
        client: AsyncClient,
        admin_user: User,
        admin_auth_headers: dict[str, str],
        test_user: User,
    ) -> None:
        """Test updating a user."""
        response = await client.patch(
            f"/api/v1/dashboard/users/{test_user.id}",
            headers=admin_auth_headers,
            json={"is_active": False},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["is_active"] is False

    @pytest.mark.asyncio
    async def test_update_user_role(
        self,
        client: AsyncClient,
        admin_user: User,
        admin_auth_headers: dict[str, str],
        test_user: User,
    ) -> None:
        """Test promoting a reader to admin."""
        response = await client.patch(
            f"/api/v1/dashboard/users/{test_user.id}",
            headers=admin_auth_headers,
            json={"role": "admin"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["role"] == "admin"
        assert data["is_admin"] is True

    @pytest.mark.asyncio
    async def test_cannot_remove_current_admin_role(
        self,
        client: AsyncClient,
        admin_user: User,
        admin_auth_headers: dict[str, str],
    ) -> None:
        """Test admins cannot remove their own admin role."""
        response = await client.patch(
            f"/api/v1/dashboard/users/{admin_user.id}",
            headers=admin_auth_headers,
            json={"role": "reader"},
        )

        assert response.status_code == 400
        assert "admin role" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_cannot_delete_current_admin_account(
        self,
        client: AsyncClient,
        admin_user: User,
        admin_auth_headers: dict[str, str],
    ) -> None:
        """Test admins cannot delete their own account."""
        response = await client.delete(
            f"/api/v1/dashboard/users/{admin_user.id}",
            headers=admin_auth_headers,
        )

        assert response.status_code == 400
        assert "own account" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_upload_and_delete_user_profile_image(
        self,
        client: AsyncClient,
        admin_user: User,
        admin_auth_headers: dict[str, str],
        test_user: User,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test admins can manage user profile images."""
        monkeypatch.setattr(profile_images, "DEFAULT_PROFILE_IMAGE_DIR", str(tmp_path))

        upload_response = await client.put(
            f"/api/v1/dashboard/users/{test_user.id}/profile-image",
            headers=admin_auth_headers,
            files={"image": ("avatar.png", make_png_bytes(), "image/png")},
        )

        assert upload_response.status_code == 200
        data = upload_response.json()
        assert data["profile_image_url"] == f"/api/v1/users/{test_user.id}/profile-image"

        image_response = await client.get(
            data["profile_image_url"],
            headers=admin_auth_headers,
        )
        assert image_response.status_code == 200
        assert image_response.headers["content-type"] == "image/jpeg"
        assert image_response.content.startswith(b"\xff\xd8")

        delete_response = await client.delete(
            f"/api/v1/dashboard/users/{test_user.id}/profile-image",
            headers=admin_auth_headers,
        )

        assert delete_response.status_code == 200
        assert delete_response.json()["profile_image_url"] is None

    @pytest.mark.asyncio
    async def test_rejects_invalid_user_profile_image(
        self,
        client: AsyncClient,
        admin_user: User,
        admin_auth_headers: dict[str, str],
        test_user: User,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test profile images must be valid decodable images."""
        monkeypatch.setattr(profile_images, "DEFAULT_PROFILE_IMAGE_DIR", str(tmp_path))

        response = await client.put(
            f"/api/v1/dashboard/users/{test_user.id}/profile-image",
            headers=admin_auth_headers,
            files={"image": ("avatar.png", b"fake-png", "image/png")},
        )

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_delete_user_removes_profile_image_file(
        self,
        client: AsyncClient,
        admin_user: User,
        admin_auth_headers: dict[str, str],
        test_user: User,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test deleting a user also removes their stored profile image."""
        monkeypatch.setattr(profile_images, "DEFAULT_PROFILE_IMAGE_DIR", str(tmp_path))

        upload_response = await client.put(
            f"/api/v1/dashboard/users/{test_user.id}/profile-image",
            headers=admin_auth_headers,
            files={"image": ("avatar.png", make_png_bytes(), "image/png")},
        )
        assert upload_response.status_code == 200
        stored_files = list(tmp_path.glob("*.jpg"))
        assert len(stored_files) == 1

        delete_response = await client.delete(
            f"/api/v1/dashboard/users/{test_user.id}",
            headers=admin_auth_headers,
        )

        assert delete_response.status_code == 204
        assert not stored_files[0].exists()

    @pytest.mark.asyncio
    async def test_delete_user_removes_dependent_rows(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        admin_user: User,
        admin_auth_headers: dict[str, str],
        test_user: User,
    ) -> None:
        """Test hard-deleting a user removes dependent session data."""
        media_file = MediaFile(
            file_path="/tmp/delete-user-dependencies.mp4",
            file_name="delete-user-dependencies.mp4",
            file_size=1024,
            file_extension=".mp4",
        )
        db_session.add(media_file)
        await db_session.flush()

        refresh_token = RefreshToken(
            user_id=test_user.id,
            token="dependent-refresh-token",
            expires_at=test_user.created_at,
        )
        playback_session = PlaybackSession(
            user_id=test_user.id,
            media_file_id=media_file.id,
        )
        media_view = MediaView(
            user_id=test_user.id,
            media_file_id=media_file.id,
            position_seconds=120,
            duration_seconds=7200,
        )
        db_session.add_all([refresh_token, playback_session, media_view])
        await db_session.commit()
        refresh_token_id = refresh_token.id
        playback_session_id = playback_session.id
        media_view_id = media_view.id

        response = await client.delete(
            f"/api/v1/dashboard/users/{test_user.id}",
            headers=admin_auth_headers,
        )

        assert response.status_code == 204
        db_session.expire_all()
        assert await db_session.get(User, test_user.id) is None
        assert await db_session.get(RefreshToken, refresh_token_id) is None
        assert await db_session.get(PlaybackSession, playback_session_id) is None
        assert await db_session.get(MediaView, media_view_id) is None

    @pytest.mark.asyncio
    async def test_permanent_media_delete_keeps_user_view_history(
        self,
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        """Test hard-deleting media cascades file-bound data but preserves user activity."""
        media_file = MediaFile(
            file_path="/tmp/delete-media-cascade.mp4",
            file_name="delete-media-cascade.mp4",
            file_size=1024,
            file_extension=".mp4",
        )
        db_session.add(media_file)
        await db_session.flush()

        audio_track = AudioTrack(
            media_file_id=media_file.id,
            stream_index=1,
            codec="aac",
            is_default=True,
        )
        playback_session = PlaybackSession(
            user_id=test_user.id,
            media_file_id=media_file.id,
        )
        transcoding_job = TranscodingJob(
            media_file_id=media_file.id,
            type=TranscodingJobType.HLS,
            status=TranscodingJobStatus.COMPLETED,
        )
        media_view = MediaView(
            user_id=test_user.id,
            media_file_id=media_file.id,
            position_seconds=120,
            duration_seconds=7200,
        )
        db_session.add_all([audio_track, playback_session, transcoding_job, media_view])
        await db_session.commit()
        audio_track_id = audio_track.id
        playback_session_id = playback_session.id
        transcoding_job_id = transcoding_job.id
        media_view_id = media_view.id

        await db_session.delete(media_file)
        await db_session.commit()

        db_session.expire_all()
        assert await db_session.get(AudioTrack, audio_track_id) is None
        assert await db_session.get(PlaybackSession, playback_session_id) is None
        assert await db_session.get(TranscodingJob, transcoding_job_id) is None

        stored_view = await db_session.get(MediaView, media_view_id)
        assert stored_view is not None
        assert stored_view.media_file_id is None


class TestSettingsManagement:
    """Tests for admin settings endpoints."""

    @pytest.mark.asyncio
    async def test_get_settings_includes_hardware_transcoding_device(
        self,
        client: AsyncClient,
        admin_user: User,
        admin_auth_headers: dict[str, str],
    ) -> None:
        response = await client.get(
            "/api/v1/dashboard/settings",
            headers=admin_auth_headers,
        )

        assert response.status_code == 200
        assert response.json()["hardware_transcoding_device"] == "auto"

    @pytest.mark.asyncio
    async def test_update_hardware_transcoding_device(
        self,
        client: AsyncClient,
        admin_user: User,
        admin_auth_headers: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        class FakeTranscoder:
            selected_device: str | None = None

            def set_hardware_device(self, device_id: str | None) -> None:
                self.selected_device = device_id

        fake_transcoder = FakeTranscoder()
        monkeypatch.setattr("app.routers.v1.dashboard.get_transcoder", lambda: fake_transcoder)

        response = await client.patch(
            "/api/v1/dashboard/settings",
            headers=admin_auth_headers,
            json={"hardware_transcoding_device": "software"},
        )

        assert response.status_code == 200
        assert response.json()["hardware_transcoding_device"] == "software"
        assert fake_transcoder.selected_device == "software"

    @pytest.mark.asyncio
    async def test_get_hardware_transcoding_status(
        self,
        client: AsyncClient,
        admin_user: User,
        admin_auth_headers: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        status = HardwareAccelerationStatus(
            ffmpeg_path="ffmpeg",
            selected_device="auto",
            active_device_id="vaapi:/dev/dri/renderD128",
            devices=[
                HardwareDeviceInfo(
                    id="vaapi:/dev/dri/renderD128",
                    type="vaapi",
                    name="VAAPI renderD128",
                    path="/dev/dri/renderD128",
                )
            ],
        )

        class FakeTranscoder:
            def set_hardware_device(self, device_id: str | None) -> None:
                assert device_id == "auto"

            def hardware_status(self) -> HardwareAccelerationStatus:
                return status

        monkeypatch.setattr("app.routers.v1.dashboard.get_transcoder", lambda: FakeTranscoder())

        response = await client.get(
            "/api/v1/dashboard/hardware-transcoding",
            headers=admin_auth_headers,
        )

        assert response.status_code == 200
        assert response.json()["active_device_id"] == "vaapi:/dev/dri/renderD128"


class TestStreamsManagement:
    """Tests for admin active stream endpoints."""

    @pytest.mark.asyncio
    async def test_list_active_streams_includes_admin_acceleration_details(
        self,
        client: AsyncClient,
        admin_user: User,
        admin_auth_headers: dict[str, str],
        db_session: AsyncSession,
    ) -> None:
        media_file = MediaFile(
            file_path="/media/movie.mkv",
            file_name="movie.mkv",
            file_size=1024,
            file_extension=".mkv",
            duration=120.0,
            width=3840,
            height=2160,
            codec="hevc",
        )
        db_session.add(media_file)
        await db_session.commit()
        await db_session.refresh(media_file)

        job = TranscodingJob(
            id="job-1",
            media_file_id=media_file.id,
            type=TranscodingJobType.HLS,
            status=TranscodingJobStatus.RUNNING,
            video_codec="h264",
            audio_codec="aac",
            ffmpeg_command=(
                "ffmpeg -hide_banner -y -vaapi_device /dev/dri/renderD128 "
                "-hwaccel vaapi -hwaccel_output_format vaapi -i /media/movie.mkv "
                "-c:v h264_vaapi -c:a aac -vf scale_vaapi=w=1280:h=720 playlist.m3u8"
            ),
            client_ip="127.0.0.1",
            user_agent="Test Player",
        )
        db_session.add(job)
        playback_session = PlaybackSession(
            id="session-1",
            user_id=admin_user.id,
            media_file_id=media_file.id,
            transcoding_job_id=job.id,
            play_method="Transcode",
            transcoding_type="full",
            status=PlaybackSessionStatus.ACTIVE,
            position_seconds=42.0,
            duration_seconds=120.0,
            client_ip="127.0.0.1",
            user_agent="Test Player",
        )
        db_session.add(playback_session)
        await db_session.commit()

        response = await client.get(
            "/api/v1/dashboard/streams",
            headers=admin_auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == "session-1"
        assert data[0]["transcoding_job_id"] == "job-1"
        assert data[0]["media_file_name"] == "movie.mkv"
        assert data[0]["username"] == admin_user.username
        assert data[0]["video"]["source_label"] == "4K (HEVC)"
        assert data[0]["video"]["target_label"] == "H264"
        assert data[0]["video"]["decision"] == "Transcode"
        assert data[0]["video"]["is_hardware"] is True
        assert data[0]["acceleration"]["summary"] == "Full hardware video path"
        assert data[0]["acceleration"]["device"] == "/dev/dri/renderD128"
        assert "ffmpeg_command" in data[0]["acceleration"]

    @pytest.mark.asyncio
    async def test_admin_stop_stream_kicks_playback_session(
        self,
        client: AsyncClient,
        test_user: User,
        auth_headers: dict[str, str],
        admin_user: User,
        admin_auth_headers: dict[str, str],
        db_session: AsyncSession,
    ) -> None:
        media_file = MediaFile(
            file_path="/media/direct.mkv",
            file_name="direct.mkv",
            file_size=1024,
            file_extension=".mkv",
            duration=120.0,
        )
        db_session.add(media_file)
        await db_session.commit()
        await db_session.refresh(media_file)

        playback_session = PlaybackSession(
            id="direct-session",
            user_id=test_user.id,
            media_file_id=media_file.id,
            play_method="DirectPlay",
            status=PlaybackSessionStatus.ACTIVE,
            position_seconds=12.0,
            duration_seconds=120.0,
        )
        db_session.add(playback_session)
        await db_session.commit()

        stop_response = await client.delete(
            "/api/v1/dashboard/streams/direct-session",
            headers=admin_auth_headers,
        )
        assert stop_response.status_code == 204

        heartbeat_response = await client.post(
            "/api/v1/playback-sessions/direct-session/heartbeat",
            headers=auth_headers,
            json={
                "position_seconds": 15.0,
                "duration_seconds": 120.0,
                "is_paused": False,
                "play_method": "DirectPlay",
            },
        )

        assert heartbeat_response.status_code == 200
        data = heartbeat_response.json()
        assert data["kicked"] is True
        assert data["session"]["status"] == "stopped_by_admin"


class TestJobsManagement:
    """Tests for jobs management endpoints."""

    @pytest.mark.asyncio
    async def test_get_jobs(
        self,
        client: AsyncClient,
        admin_user: User,
        admin_auth_headers: dict[str, str],
    ) -> None:
        """Test getting jobs list."""
        response = await client.get(
            "/api/v1/dashboard/jobs",
            headers=admin_auth_headers,
        )

        assert response.status_code == 200
        # Should return a list (may be empty if scheduler not running)
        assert isinstance(response.json(), list)

    @pytest.mark.asyncio
    async def test_get_job_history(
        self,
        client: AsyncClient,
        admin_user: User,
        admin_auth_headers: dict[str, str],
    ) -> None:
        """Test getting job execution history."""
        response = await client.get(
            "/api/v1/dashboard/jobs/history",
            headers=admin_auth_headers,
        )

        assert response.status_code == 200
        assert isinstance(response.json(), list)
