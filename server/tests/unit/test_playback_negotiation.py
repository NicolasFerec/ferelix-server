"""Decisions must respect selected tracks, disabled methods and real constraints."""

import pytest

from app.models import VideoTrack
from app.models.playback import CodecProfile, DeviceProfileCondition, PlayMethod
from app.services.stream_builder import StreamBuilder
from tests.unit.test_stream_builder import create_device_profile, create_media_file


@pytest.mark.parametrize("resolution", [None, {"width": 1280, "height": 720}])
def test_disabled_transcoding_never_returns_a_transcode(resolution):
    media = create_media_file(audio_codec="dts")
    plan = StreamBuilder(create_device_profile()).build_stream_info(
        media,
        enable_direct_play=False,
        enable_direct_stream=True,
        enable_transcoding=False,
        requested_resolution=resolution,
    )
    assert plan.PlayMethod == PlayMethod.NONE
    assert plan.TranscodingUrl is None


@pytest.mark.parametrize(
    "video_copy,audio_copy,expected", [(False, True, "full"), (True, False, "audio-only"), (False, False, "full")]
)
def test_stream_copy_permissions_are_honored(video_copy, audio_copy, expected):
    plan = StreamBuilder(create_device_profile()).build_stream_info(
        create_media_file(),
        allow_video_stream_copy=video_copy,
        allow_audio_stream_copy=audio_copy,
    )
    assert plan.PlayMethod == PlayMethod.TRANSCODE
    assert plan.TranscodingType == expected


def test_secondary_video_track_drives_codec_and_resolution_decision():
    media = create_media_file()
    media.video_tracks.append(VideoTrack(stream_index=2, codec="av1", width=3840, height=2160, is_default=False))
    plan = StreamBuilder(create_device_profile()).build_stream_info(media, video_stream_index=2)
    assert plan.VideoStreamIndex == 2
    assert plan.TranscodingType == "full"
    assert plan.AvailableResolutions[0]["width"] == 3840
    assert media.video_tracks[0].stream_index == 0


def test_secondary_compatible_video_still_requires_mapping_in_hls():
    media = create_media_file()
    media.video_tracks.append(VideoTrack(stream_index=2, codec="h264", width=640, height=360, is_default=False))
    plan = StreamBuilder(create_device_profile()).build_stream_info(media, video_stream_index=2)
    assert plan.PlayMethod == PlayMethod.DIRECT_STREAM
    assert plan.VideoStreamIndex == 2


@pytest.mark.parametrize("value,fps,expected", [("30", 60, "full"), ("60", 60, None), ("60", None, "full")])
def test_required_framerate_constraint_is_evaluated(value, fps, expected):
    profile = create_device_profile(
        codec_profiles=[
            CodecProfile(
                Type="Video",
                Codec="h264",
                Conditions=[
                    DeviceProfileCondition(
                        Condition="LessThanEqual", Property="VideoFramerate", Value=value, IsRequired=True
                    )
                ],
            )
        ]
    )
    media = create_media_file()
    media.video_tracks[0].fps = fps
    plan = StreamBuilder(profile).build_stream_info(media)
    assert plan.TranscodingType == expected


def test_hevc_safari_tag_is_repaired_by_remux():
    profile = create_device_profile(
        codec_profiles=[
            CodecProfile(
                Type="Video",
                Codec="hevc",
                Conditions=[
                    DeviceProfileCondition(
                        Condition="EqualsAny", Property="VideoCodecTag", Value="hvc1|dvh1", IsRequired=True
                    )
                ],
            )
        ]
    )
    media = create_media_file(video_codec="hevc")
    media.video_tracks[0].codec_tag = "hev1"
    plan = StreamBuilder(profile).build_stream_info(media)
    assert plan.PlayMethod == PlayMethod.DIRECT_STREAM
    assert plan.TranscodingType == "remux"


@pytest.mark.parametrize("transfer", ["smpte2084", "arib-std-b67"])
def test_hdr_is_tonemapped_when_device_only_supports_sdr(transfer):
    profile = create_device_profile(
        codec_profiles=[
            CodecProfile(
                Type="Video",
                Codec="hevc",
                Conditions=[
                    DeviceProfileCondition(
                        Condition="EqualsAny", Property="VideoRangeType", Value="SDR", IsRequired=True
                    )
                ],
            )
        ]
    )
    media = create_media_file(video_codec="hevc")
    media.video_tracks[0].color_transfer = transfer
    plan = StreamBuilder(profile).build_stream_info(media)
    assert plan.TranscodingType == "full"


def test_required_output_caps_are_sent_to_the_encoder():
    profile = create_device_profile(
        codec_profiles=[
            CodecProfile(
                Type="Video",
                Codec="h264",
                Conditions=[
                    DeviceProfileCondition(Condition="LessThanEqual", Property="Width", Value="1280", IsRequired=True),
                    DeviceProfileCondition(Condition="LessThanEqual", Property="Height", Value="720", IsRequired=True),
                    DeviceProfileCondition(
                        Condition="LessThanEqual", Property="VideoFramerate", Value="30", IsRequired=True
                    ),
                ],
            )
        ]
    )
    media = create_media_file()
    media.video_tracks[0].fps = 60
    plan = StreamBuilder(profile).build_stream_info(media)
    assert plan.TranscodeSettings is not None
    assert plan.TranscodeSettings.MaxWidth == 1280
    assert plan.TranscodeSettings.MaxHeight == 720
    assert plan.TranscodeSettings.MaxFrameRate == pytest.approx(30)


@pytest.mark.parametrize("resolution", [{"width": -1}, {"height": float("inf")}, {"width": "1920"}])
def test_invalid_manual_resolution_is_rejected(resolution):
    with pytest.raises(ValueError):
        StreamBuilder(create_device_profile()).build_stream_info(create_media_file(), requested_resolution=resolution)
