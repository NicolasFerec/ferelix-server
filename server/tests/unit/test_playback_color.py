"""Repair HDR metadata produced by the legacy scanner before transcoding."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models import MediaFile, PlaybackSession, VideoTrack
from app.models.playback import PlayMethod, StreamInfo, TranscodeSettings
from app.models.transcoding import TranscodingJobType
from app.services.playback_session import HlsStartOptions, PlaybackSessionService


async def test_legacy_wide_gamut_metadata_is_repaired_once(db_session, test_user, tmp_path, monkeypatch):
    path = tmp_path / "movie.mkv"
    path.write_bytes(b"video")
    media = MediaFile(file_path=str(path), file_name="movie.mkv", file_size=5, file_extension=".mkv")
    media.video_tracks = [VideoTrack(stream_index=0, codec="hevc", color_space="bt2020nc", color_transfer=None)]
    db_session.add(media)
    await db_session.commit()
    playback = PlaybackSession(user_id=test_user.id, media_file_id=media.id)
    db_session.add(playback)
    await db_session.commit()
    transcoder = MagicMock()
    transcoder.stop_job = AsyncMock(return_value=True)
    transcoder.start_hls_transcode = AsyncMock()
    monkeypatch.setattr("app.services.playback_session.get_transcoder", lambda: transcoder)
    probe = MagicMock(return_value={"video_tracks": [{"stream_index": 0, "color_transfer": "smpte2084"}]})
    monkeypatch.setattr("app.services.playback_session.extract_video_metadata", probe)
    service = PlaybackSessionService(db_session)
    await service.start_hls_job(
        media.id,
        HlsStartOptions(
            job_type=TranscodingJobType.HLS,
            playback_session_id=playback.id,
            playback_generation=playback.playback_generation + 1,
        ),
    )
    assert transcoder.start_hls_transcode.call_args.kwargs["media_file"].video_tracks[0].color_transfer == "smpte2084"
    await service.start_hls_job(
        media.id,
        HlsStartOptions(
            job_type=TranscodingJobType.HLS,
            playback_session_id=playback.id,
            playback_generation=playback.playback_generation + 1,
        ),
    )
    assert probe.call_count == 1


@pytest.mark.parametrize("transcoding_type", ["remux", "audio-only", "full"])
async def test_automatic_start_preserves_negotiated_audio_track(db_session, monkeypatch, transcoding_type):
    monkeypatch.setattr("app.services.playback_session.get_transcoder", MagicMock())
    service = PlaybackSessionService(db_session)
    start = AsyncMock(return_value=MagicMock(id="job"))
    monkeypatch.setattr(service, "start_hls_job", start)
    source = StreamInfo(
        Id="1",
        PlayMethod=PlayMethod.DIRECT_STREAM if transcoding_type == "remux" else PlayMethod.TRANSCODE,
        IsRemuxOnly=transcoding_type == "remux",
        TranscodingType=transcoding_type,
        AudioStreamIndex=4,
        TranscodeSettings=TranscodeSettings(VideoCodec="copy", AudioCodec="aac"),
    )

    await service.start_from_stream_info(1, source, "session", 1)

    assert start.call_args.args[1].audio_stream_index == 4
