"""Repair HDR metadata produced by the legacy scanner before transcoding."""

from unittest.mock import AsyncMock, MagicMock

from app.models import MediaFile, VideoTrack
from app.models.transcoding import TranscodingJobType
from app.services.playback_session import HlsStartOptions, PlaybackSessionService


async def test_legacy_wide_gamut_metadata_is_repaired_once(db_session, tmp_path, monkeypatch):
    path = tmp_path / "movie.mkv"
    path.write_bytes(b"video")
    media = MediaFile(file_path=str(path), file_name="movie.mkv", file_size=5, file_extension=".mkv")
    media.video_tracks = [VideoTrack(stream_index=0, codec="hevc", color_space="bt2020nc", color_transfer=None)]
    db_session.add(media)
    await db_session.commit()
    transcoder = MagicMock()
    transcoder.start_hls_transcode = AsyncMock()
    monkeypatch.setattr("app.services.playback_session.get_transcoder", lambda: transcoder)
    probe = MagicMock(return_value={"video_tracks": [{"stream_index": 0, "color_transfer": "smpte2084"}]})
    monkeypatch.setattr("app.services.playback_session.extract_video_metadata", probe)
    service = PlaybackSessionService(db_session)
    await service.start_hls_job(media.id, HlsStartOptions(job_type=TranscodingJobType.HLS))
    assert transcoder.start_hls_transcode.call_args.kwargs["media_file"].video_tracks[0].color_transfer == "smpte2084"
    await service.start_hls_job(media.id, HlsStartOptions(job_type=TranscodingJobType.HLS))
    assert probe.call_count == 1
