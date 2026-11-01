"""Regression tests for cleanup, signing keys, optional metadata and upload limits."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.models import MediaFile, TranscodingJob
from app.models.playback import DeviceProfile
from app.models.transcoding import TranscodingJobStatus, TranscodingJobType
from app.services.auth import create_access_token, load_secret_key, verify_token
from app.services.profile_images import MAX_PROFILE_IMAGE_BYTES, save_profile_image
from app.services.stream_builder import StreamBuilder
from app.services.transcoder import FFmpegTranscoder


@pytest.mark.parametrize("subject", ["", "abc", "-1", "0", "\uff11\uff12", "1.5"])
def test_invalid_token_subject_is_rejected(subject: str) -> None:
    assert verify_token(create_access_token({"sub": subject})) is None


def test_generated_secret_is_private_and_survives_reload(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("SECRET_KEY", raising=False)
    path = tmp_path / ".secret_key"
    monkeypatch.setenv("FERELIX_SECRET_KEY_FILE", str(path))
    first = load_secret_key()
    assert len(first) == 64
    assert load_secret_key() == first
    assert path.stat().st_mode & 0o077 == 0


def test_missing_color_metadata_is_sdr() -> None:
    builder = StreamBuilder(
        DeviceProfile(Id="test", Name="test", DirectPlayProfiles=[], TranscodingProfiles=[], CodecProfiles=[])
    )
    track = SimpleNamespace(color_space=None, color_primaries=None, color_transfer=None)
    assert builder._get_video_range(track) == "SDR"


async def test_profile_upload_reads_only_up_to_limit() -> None:
    upload = MagicMock()
    upload.read = AsyncMock(return_value=b"x" * (MAX_PROFILE_IMAGE_BYTES + 1))
    with pytest.raises(HTTPException) as error:
        await save_profile_image(1, upload)
    assert error.value.status_code == 413
    upload.read.assert_awaited_once_with(MAX_PROFILE_IMAGE_BYTES + 1)


async def test_cleanup_preserves_completed_job_still_in_use(db_session, monkeypatch) -> None:
    media = MediaFile(file_path="/movie.mp4", file_name="movie", file_size=1, file_extension=".mp4")
    db_session.add(media)
    await db_session.flush()
    fresh = TranscodingJob(
        id="fresh",
        media_file_id=media.id,
        type=TranscodingJobType.HLS,
        status=TranscodingJobStatus.COMPLETED,
        output_path="/fresh",
        last_accessed_at=datetime.now(UTC),
    )
    stale = TranscodingJob(
        id="stale",
        media_file_id=media.id,
        type=TranscodingJobType.HLS,
        status=TranscodingJobStatus.COMPLETED,
        output_path="/stale",
        last_accessed_at=datetime.now(UTC) - timedelta(hours=1),
    )
    db_session.add_all([fresh, stale])
    await db_session.commit()

    @asynccontextmanager
    async def session_scope():
        yield db_session

    monkeypatch.setattr("app.services.transcoder.async_session_maker", session_scope)
    remove = MagicMock()
    monkeypatch.setattr("app.services.transcoder.remove_output_path", remove)
    transcoder = object.__new__(FFmpegTranscoder)
    assert await transcoder.cleanup_transcode_files() == 1
    remove.assert_called_once_with("/stale")


async def test_ffmpeg_finishing_immediately_with_success_is_not_a_startup_failure() -> None:
    process = MagicMock()
    process.wait = AsyncMock(return_value=0)
    process.returncode = 0
    process.stderr.read = AsyncMock(return_value=b"Successful remux")
    transcoder = object.__new__(FFmpegTranscoder)
    await transcoder._ensure_process_running("short-remux", process)
    process.stderr.read.assert_not_awaited()
