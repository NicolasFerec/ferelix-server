"""Unit tests for the StreamBuilder service."""

from datetime import UTC, datetime

from app.models.media_file import AudioTrack, MediaFile, SubtitleTrack, VideoTrack
from app.models.playback import (
    CodecProfile,
    DeviceProfile,
    DirectPlayProfile,
    PlayMethod,
    TranscodeReason,
)
from app.services.stream_builder import PlaybackResult, StreamBuilder


def create_device_profile(
    direct_play_profiles: list[DirectPlayProfile] | None = None,
    codec_profiles: list[CodecProfile] | None = None,
) -> DeviceProfile:
    """Create a DeviceProfile for testing."""
    if direct_play_profiles is None:
        direct_play_profiles = [
            DirectPlayProfile(
                Type="Video",
                Container="mp4,mkv,webm",
                VideoCodec="h264,hevc,vp9",
                AudioCodec="aac,mp3,opus",
            ),
        ]
    if codec_profiles is None:
        codec_profiles = []

    return DeviceProfile(
        Name="Test Device",
        Id="test-device-001",
        DirectPlayProfiles=direct_play_profiles,
        CodecProfiles=codec_profiles,
    )


def create_media_file(
    video_codec: str = "h264",
    audio_codec: str = "aac",
    container: str = ".mp4",
    width: int = 1920,
    height: int = 1080,
    duration: float = 120.0,
    bitrate: int = 5000000,
) -> MediaFile:
    """Create a MediaFile for testing."""
    media_file = MediaFile(
        id=1,
        file_path="/test/movie.mp4",
        file_name="movie.mp4",
        file_size=1073741824,
        file_extension=container,
        duration=duration,
        width=width,
        height=height,
        codec=video_codec,
        bitrate=bitrate,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        scanned_at=datetime.now(UTC),
    )

    # Add video track
    video_track = VideoTrack(
        id=1,
        media_file_id=1,
        stream_index=0,
        codec=video_codec,
        width=width,
        height=height,
        bitrate=bitrate,
        fps=24.0,
        is_default=True,
        profile="High",
        level="4.1",
        pixel_format="yuv420p",
        bit_depth=8,
    )
    media_file.video_tracks = [video_track]

    # Add audio track
    audio_track = AudioTrack(
        id=1,
        media_file_id=1,
        stream_index=1,
        codec=audio_codec,
        channels=2,
        sample_rate=48000,
        bitrate=128000,
        is_default=True,
    )
    media_file.audio_tracks = [audio_track]

    # No subtitles by default
    media_file.subtitle_tracks = []

    return media_file


class TestStreamBuilderDirectPlay:
    """Tests for direct play scenarios."""

    def test_direct_play_h264_mp4(self) -> None:
        """Test direct play for H264 in MP4 container."""
        profile = create_device_profile()
        media_file = create_media_file(video_codec="h264", audio_codec="aac", container=".mp4")

        builder = StreamBuilder(profile)
        stream_info = builder.build_stream_info(media_file)

        assert stream_info.PlayMethod == PlayMethod.DIRECT_PLAY
        assert stream_info.DirectStreamUrl is not None

    def test_direct_play_hevc_mkv(self) -> None:
        """Test direct play for HEVC in MKV container."""
        profile = create_device_profile()
        media_file = create_media_file(video_codec="hevc", audio_codec="aac", container=".mkv")

        builder = StreamBuilder(profile)
        stream_info = builder.build_stream_info(media_file)

        assert stream_info.PlayMethod == PlayMethod.DIRECT_PLAY

    def test_direct_play_vp9_webm(self) -> None:
        """Test direct play for VP9 in WebM container."""
        profile = create_device_profile()
        media_file = create_media_file(video_codec="vp9", audio_codec="opus", container=".webm")

        builder = StreamBuilder(profile)
        stream_info = builder.build_stream_info(media_file)

        assert stream_info.PlayMethod == PlayMethod.DIRECT_PLAY


class TestStreamBuilderTranscode:
    """Tests for transcoding scenarios."""

    def test_transcode_unsupported_video_codec(self) -> None:
        """Test transcoding for unsupported video codec."""
        profile = create_device_profile()
        # AV1 is not in the supported codecs
        media_file = create_media_file(video_codec="av1", audio_codec="aac", container=".mp4")

        builder = StreamBuilder(profile)
        stream_info = builder.build_stream_info(media_file)

        assert stream_info.PlayMethod == PlayMethod.TRANSCODE
        assert TranscodeReason.VIDEO_CODEC_NOT_SUPPORTED in stream_info.TranscodeReasons

    def test_transcode_unsupported_container(self) -> None:
        """Test transcoding for unsupported container."""
        profile = create_device_profile()
        # AVI is not in the supported containers
        media_file = create_media_file(video_codec="h264", audio_codec="aac", container=".avi")

        builder = StreamBuilder(profile)
        stream_info = builder.build_stream_info(media_file)

        # Should either direct stream (remux) or transcode
        assert stream_info.PlayMethod in (PlayMethod.DIRECT_STREAM, PlayMethod.TRANSCODE)

    def test_transcode_unsupported_audio_codec(self) -> None:
        """Test transcoding for unsupported audio codec."""
        profile = create_device_profile()
        # AC3 is not in the supported codecs
        media_file = create_media_file(video_codec="h264", audio_codec="ac3", container=".mp4")

        builder = StreamBuilder(profile)
        stream_info = builder.build_stream_info(media_file)

        # Should transcode audio while copying video
        assert stream_info.PlayMethod in (PlayMethod.TRANSCODE,)


class TestStreamBuilderResolution:
    """Tests for resolution handling."""

    def test_available_resolutions_for_4k(self) -> None:
        """Test available resolutions for 4K content."""
        profile = create_device_profile()
        media_file = create_media_file(width=3840, height=2160)

        builder = StreamBuilder(profile)
        stream_info = builder.build_stream_info(media_file)

        assert stream_info.AvailableResolutions is not None
        assert len(stream_info.AvailableResolutions) > 1

        # First should be original
        original = stream_info.AvailableResolutions[0]
        assert original["is_original"] is True
        assert original["width"] == 3840
        assert original["height"] == 2160

    def test_available_resolutions_for_1080p(self) -> None:
        """Test available resolutions for 1080p content."""
        profile = create_device_profile()
        media_file = create_media_file(width=1920, height=1080)

        builder = StreamBuilder(profile)
        stream_info = builder.build_stream_info(media_file)

        # Should have original and lower resolutions
        assert stream_info.AvailableResolutions is not None
        widths = [r["width"] for r in stream_info.AvailableResolutions]

        # Should include original and some lower options
        assert 1920 in widths

    def test_resolution_override_forces_transcode(self) -> None:
        """Test that resolution override forces transcoding."""
        profile = create_device_profile()
        media_file = create_media_file(width=1920, height=1080)

        builder = StreamBuilder(profile)
        stream_info = builder.build_stream_info(
            media_file,
            requested_resolution={"width": 1280, "height": 720},
        )

        assert stream_info.PlayMethod == PlayMethod.TRANSCODE
        assert stream_info.TranscodeSettings is not None
        assert stream_info.TranscodeSettings.MaxWidth == 1280
        assert stream_info.TranscodeSettings.MaxHeight == 720


class TestStreamBuilderMediaStreams:
    """Tests for media stream information building."""

    def test_builds_video_stream_info(self) -> None:
        """Test that video stream info is built correctly."""
        profile = create_device_profile()
        media_file = create_media_file()

        builder = StreamBuilder(profile)
        stream_info = builder.build_stream_info(media_file)

        video_streams = [s for s in stream_info.MediaStreams if s.get("Type") == "Video"]
        assert len(video_streams) == 1
        assert video_streams[0]["Codec"] == "h264"
        assert video_streams[0]["Width"] == 1920
        assert video_streams[0]["Height"] == 1080

    def test_builds_audio_stream_info(self) -> None:
        """Test that audio stream info is built correctly."""
        profile = create_device_profile()
        media_file = create_media_file()

        builder = StreamBuilder(profile)
        stream_info = builder.build_stream_info(media_file)

        audio_streams = [s for s in stream_info.MediaStreams if s.get("Type") == "Audio"]
        assert len(audio_streams) == 1
        assert audio_streams[0]["Codec"] == "aac"
        assert audio_streams[0]["Channels"] == 2

    def test_builds_subtitle_stream_info(self) -> None:
        """Test that subtitle stream info is built correctly."""
        profile = create_device_profile()
        media_file = create_media_file()

        # Add subtitle track
        subtitle_track = SubtitleTrack(
            id=1,
            media_file_id=1,
            stream_index=2,
            codec="srt",
            language="en",
            is_default=True,
            is_forced=False,
        )
        media_file.subtitle_tracks = [subtitle_track]

        builder = StreamBuilder(profile)
        stream_info = builder.build_stream_info(media_file)

        subtitle_streams = [s for s in stream_info.MediaStreams if s.get("Type") == "Subtitle"]
        assert len(subtitle_streams) == 1
        assert subtitle_streams[0]["Codec"] == "srt"
        assert subtitle_streams[0]["Language"] == "en"


class TestStreamBuilderDisabledOptions:
    """Tests for disabled playback options."""

    def test_disable_direct_play(self) -> None:
        """Test that direct play can be disabled."""
        profile = create_device_profile()
        media_file = create_media_file()

        builder = StreamBuilder(profile)
        stream_info = builder.build_stream_info(
            media_file,
            enable_direct_play=False,
        )

        # Should not be direct play
        assert stream_info.PlayMethod != PlayMethod.DIRECT_PLAY

    def test_disable_all_options(self) -> None:
        """Test behavior when all options are disabled."""
        profile = create_device_profile()
        media_file = create_media_file()

        builder = StreamBuilder(profile)
        stream_info = builder.build_stream_info(
            media_file,
            enable_direct_play=False,
            enable_direct_stream=False,
            enable_transcoding=False,
        )

        # Should fall back to transcode with error reason
        assert stream_info.PlayMethod == PlayMethod.TRANSCODE


class TestPlaybackResult:
    """Tests for PlaybackResult class."""

    def test_can_play_true(self) -> None:
        """Test PlaybackResult with can_play=True."""
        result = PlaybackResult(can_play=True, reasons=[])

        assert result.can_play is True
        assert result.reasons == []

    def test_can_play_false_with_reasons(self) -> None:
        """Test PlaybackResult with can_play=False."""
        reasons = [TranscodeReason.VIDEO_CODEC_NOT_SUPPORTED]
        result = PlaybackResult(can_play=False, reasons=reasons)

        assert result.can_play is False
        assert TranscodeReason.VIDEO_CODEC_NOT_SUPPORTED in result.reasons
