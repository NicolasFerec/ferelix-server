"""Tests for FFmpeg HLS command construction."""

from app.services.transcoding.commands import HlsCommandBuilder, HlsCommandOptions
from app.services.transcoding.hardware import HardwareAcceleration, HardwareDevice


def test_vaapi_transcode_uses_hardware_decode_when_source_codec_is_supported() -> None:
    hw_accel = HardwareAcceleration(selected_device="auto")
    hw_accel.devices = [
        HardwareDevice(
            id="vaapi:/dev/dri/renderD128",
            type="vaapi",
            name="VAAPI renderD128",
            path="/dev/dri/renderD128",
            encoders={"h264": "h264_vaapi"},
            decoders={"hevc"},
        )
    ]
    hw_accel._detected = True

    cmd = HlsCommandBuilder("ffmpeg", hw_accel).build_transcode(
        HlsCommandOptions(
            input_path="/media/movie.mkv",
            playlist_path="/tmp/playlist.m3u8",
            segment_pattern="/tmp/segment_%03d.ts",
            source_video_codec="h265",
            video_codec="h264",
        )
    )

    assert cmd[cmd.index("-vaapi_device") + 1] == "/dev/dri/renderD128"
    assert cmd[cmd.index("-hwaccel") + 1] == "vaapi"
    assert cmd[cmd.index("-hwaccel_output_format") + 1] == "vaapi"
    assert cmd[cmd.index("-c:v") + 1] == "h264_vaapi"
    assert "hwupload" not in cmd


def test_vaapi_transcode_keeps_software_decode_when_burning_subtitles() -> None:
    hw_accel = HardwareAcceleration(selected_device="auto")
    hw_accel.devices = [
        HardwareDevice(
            id="vaapi:/dev/dri/renderD128",
            type="vaapi",
            name="VAAPI renderD128",
            path="/dev/dri/renderD128",
            encoders={"h264": "h264_vaapi"},
            decoders={"hevc"},
        )
    ]
    hw_accel._detected = True

    cmd = HlsCommandBuilder("ffmpeg", hw_accel).build_transcode(
        HlsCommandOptions(
            input_path="/media/movie.mkv",
            playlist_path="/tmp/playlist.m3u8",
            segment_pattern="/tmp/segment_%03d.ts",
            source_video_codec="hevc",
            video_codec="h264",
            subtitle_stream_index=2,
        )
    )

    assert "-hwaccel" not in cmd
    assert "subtitles='/media/movie.mkv':stream_index=2,format=nv12,hwupload" in cmd


def test_nvidia_transcode_uses_cuda_decode_without_scaling() -> None:
    hw_accel = HardwareAcceleration(selected_device="auto")
    hw_accel.devices = [
        HardwareDevice(
            id="nvidia:0",
            type="nvidia",
            name="NVIDIA GPU",
            index=0,
            encoders={"h264": "h264_nvenc"},
            decoders={"hevc"},
        )
    ]
    hw_accel._detected = True

    cmd = HlsCommandBuilder("ffmpeg", hw_accel).build_transcode(
        HlsCommandOptions(
            input_path="/media/movie.mkv",
            playlist_path="/tmp/playlist.m3u8",
            segment_pattern="/tmp/segment_%03d.ts",
            source_video_codec="hevc",
            video_codec="h264",
        )
    )

    assert cmd[cmd.index("-hwaccel") + 1] == "cuda"
    assert cmd[cmd.index("-hwaccel_output_format") + 1] == "cuda"
    assert cmd[cmd.index("-hwaccel_device") + 1] == "0"
    assert cmd[cmd.index("-c:v") + 1] == "h264_nvenc"
    assert cmd[cmd.index("-forced-idr") + 1] == "1"


def test_nvidia_transcode_keeps_software_decode_when_scaling() -> None:
    hw_accel = HardwareAcceleration(selected_device="auto")
    hw_accel.devices = [
        HardwareDevice(
            id="nvidia:0",
            type="nvidia",
            name="NVIDIA GPU",
            index=0,
            encoders={"h264": "h264_nvenc"},
            decoders={"hevc"},
        )
    ]
    hw_accel._detected = True

    cmd = HlsCommandBuilder("ffmpeg", hw_accel).build_transcode(
        HlsCommandOptions(
            input_path="/media/movie.mkv",
            playlist_path="/tmp/playlist.m3u8",
            segment_pattern="/tmp/segment_%03d.ts",
            source_video_codec="hevc",
            video_codec="h264",
            max_width=1280,
            max_height=720,
        )
    )

    assert "-hwaccel" not in cmd
    assert cmd[cmd.index("-vf") + 1].startswith("scale=")
