"""Persisted playback preferences cross the API, negotiation and encoder-start boundary."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models import AudioTrack, MediaFile, PlaybackSession, SubtitleTrack, TranscodingJob, VideoTrack
from app.models.transcoding import TranscodingJobStatus, TranscodingJobType
from app.services.transcoder import FFmpegTranscoder
from tests.unit.test_stream_builder import create_device_profile


@pytest.fixture
async def preference_media(db_session, tmp_path):
    source = tmp_path / "film.mp4"
    source.touch()
    media = MediaFile(file_path=str(source), file_name=source.name, file_size=0, file_extension=".mp4")
    media.video_tracks = [VideoTrack(stream_index=0, codec="h264", is_default=True)]
    media.audio_tracks = [
        AudioTrack(stream_index=1, codec="aac", language="fra", is_default=True),
        AudioTrack(stream_index=2, codec="aac", language="eng", is_default=False),
    ]
    media.subtitle_tracks = [
        SubtitleTrack(stream_index=3, codec="hdmv_pgs_subtitle", language="fre", is_forced=True, is_default=False),
        SubtitleTrack(stream_index=4, codec="subrip", language="eng", is_forced=False, is_default=True),
    ]
    db_session.add(media)
    await db_session.commit()
    return media


def profile_request(**overrides):
    return {"DeviceProfile": create_device_profile().model_dump(), **overrides}


async def test_preferences_persist_without_changing_active_playback(
    client, db_session, test_user, auth_headers, preference_media, monkeypatch
):
    playback = PlaybackSession(user_id=test_user.id, media_file_id=preference_media.id, playback_generation=3)
    db_session.add(playback)
    await db_session.flush()
    job = TranscodingJob(
        media_file_id=preference_media.id,
        session_id=playback.id,
        playback_generation=3,
        type=TranscodingJobType.HLS,
        status=TranscodingJobStatus.RUNNING,
    )
    db_session.add(job)
    await db_session.commit()
    transcoder = MagicMock()
    monkeypatch.setattr("app.services.playback_session.get_transcoder", lambda: transcoder)
    response = await client.patch(
        "/api/v1/users/me",
        headers=auth_headers,
        json={
            "preferred_audio_language": " EN ",
            "preferred_subtitle_language": "FR_ca",
            "subtitle_mode": "forced",
        },
    )
    assert response.status_code == 200
    assert response.json()["preferred_audio_language"] == "en"
    assert response.json()["preferred_subtitle_language"] == "fr-ca"
    current = (await client.get("/api/v1/users/me", headers=auth_headers)).json()
    assert current["subtitle_mode"] == "forced"
    await db_session.refresh(playback)
    await db_session.refresh(job)
    assert playback.playback_generation == 3
    assert job.status == TranscodingJobStatus.RUNNING
    assert transcoder.mock_calls == []
    response = await client.patch("/api/v1/users/me", headers=auth_headers, json={"preferred_audio_language": None})
    assert response.json()["preferred_audio_language"] is None
    assert response.json()["preferred_subtitle_language"] == "fr-ca"


@pytest.mark.parametrize(
    "payload",
    [
        {"preferred_audio_language": "French"},
        {"preferred_subtitle_language": "a"},
        {"subtitle_mode": "sometimes"},
    ],
)
async def test_invalid_preference_is_rejected(client, auth_headers, payload):
    response = await client.patch("/api/v1/users/me", headers=auth_headers, json=payload)
    assert response.status_code == 422


async def test_automatic_nondefault_audio_is_remuxed_and_explicit_index_wins(
    client, db_session, test_user, auth_headers, preference_media
):
    test_user.preferred_audio_language = "en"
    await db_session.commit()
    endpoint = f"/api/v1/playback-info/{preference_media.id}"
    response = await client.post(endpoint, headers=auth_headers, json=profile_request())
    assert response.status_code == 200
    info = response.json()["MediaSources"][0]
    assert info["AudioStreamIndex"] == 2
    assert info["PlayMethod"] == "DirectStream"
    assert info["SubtitleStreamIndex"] is None
    response = await client.post(endpoint, headers=auth_headers, json=profile_request(AudioStreamIndex=1))
    assert response.json()["MediaSources"][0]["AudioStreamIndex"] == 1
    assert response.json()["MediaSources"][0]["PlayMethod"] == "DirectPlay"


async def test_preferred_image_subtitle_is_sent_to_the_real_startup_service_for_burning(
    client, db_session, test_user, auth_headers, preference_media, monkeypatch, tmp_path
):
    test_user.preferred_audio_language = "en"
    test_user.preferred_subtitle_language = "fr"
    test_user.subtitle_mode = "forced"
    playback = PlaybackSession(user_id=test_user.id, media_file_id=preference_media.id)
    db_session.add(playback)
    await db_session.commit()
    transcoder = FFmpegTranscoder(temp_dir=str(tmp_path / "transcodes"))
    transcoder.hw_accel.selected_device = "software"
    transcoder.hw_accel._detected = True
    transcoder.set_hardware_device = MagicMock()
    transcoder._mark_job_running = AsyncMock()
    transcoder._launch_ffmpeg = AsyncMock(return_value="playlist.m3u8")
    monkeypatch.setattr("app.services.playback_session.get_transcoder", lambda: transcoder)
    response = await client.post(
        f"/api/v1/start-stream/{preference_media.id}",
        headers=auth_headers,
        json=profile_request(PlaybackSessionId=playback.id, PlaybackGeneration=1),
    )
    assert response.status_code == 200
    assert response.json()["method"] == "hls_transcode"
    assert response.json()["subtitle_stream_index"] == "3"
    assert response.json()["subtitle_delivery_method"] == "Encode"
    command = transcoder._launch_ffmpeg.call_args.args[2]
    assert "[0:0][0:3]overlay" in command[command.index("-filter_complex") + 1]
    assert "0:2" in command
    assert command[command.index("-c:v") + 1] == "libx264"


async def test_explicit_subtitle_off_and_text_override_persisted_forced_mode(
    client, db_session, test_user, auth_headers, preference_media
):
    test_user.subtitle_mode = "forced"
    test_user.preferred_subtitle_language = "fr"
    await db_session.commit()
    endpoint = f"/api/v1/playback-info/{preference_media.id}"
    response = await client.post(endpoint, headers=auth_headers, json=profile_request(SubtitleStreamIndex=-1))
    info = response.json()["MediaSources"][0]
    assert info["SubtitleStreamIndex"] is None
    assert info["PlayMethod"] == "DirectPlay"
    response = await client.post(endpoint, headers=auth_headers, json=profile_request(SubtitleStreamIndex=4))
    info = response.json()["MediaSources"][0]
    assert info["SubtitleStreamIndex"] == 4
    assert info["SubtitleDeliveryMethod"] == "External"
    assert info["SubtitleUrl"] == f"/api/v1/subtitle/{preference_media.id}/4"
    assert info["PlayMethod"] == "DirectPlay"


async def test_file_details_expose_resolved_track_preferences(
    client, db_session, test_user, auth_headers, preference_media
):
    test_user.preferred_audio_language = "en"
    test_user.preferred_subtitle_language = "fr"
    test_user.subtitle_mode = "forced"
    await db_session.commit()
    endpoint = f"/api/v1/media/{preference_media.id}"
    response = await client.get(endpoint, headers=auth_headers)
    assert response.status_code == 200
    details = response.json()
    assert details["default_video_stream_index"] == 0
    assert details["default_audio_stream_index"] == 2
    assert details["default_subtitle_stream_index"] == 3
    test_user.subtitle_mode = "off"
    await db_session.commit()
    assert (await client.get(endpoint, headers=auth_headers)).json()["default_subtitle_stream_index"] is None
