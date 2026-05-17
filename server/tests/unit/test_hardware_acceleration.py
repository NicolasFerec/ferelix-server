"""Tests for hardware transcoding detection and selection."""

from app.services.transcoding.hardware import HardwareAcceleration, HardwareDevice


def test_software_selection_uses_software_encoder() -> None:
    hw_accel = HardwareAcceleration(selected_device="software")
    hw_accel.devices = [
        HardwareDevice(
            id="nvidia:0",
            type="nvidia",
            name="NVIDIA GPU",
            index=0,
            encoders={"h264": "h264_nvenc"},
        )
    ]
    hw_accel._detected = True

    encoder, args = hw_accel.get_video_encoder("h264")

    assert encoder == "libx264"
    assert "-preset" in args


def test_auto_selection_uses_first_available_hardware_device() -> None:
    hw_accel = HardwareAcceleration(selected_device="auto")
    hw_accel.devices = [
        HardwareDevice(
            id="vaapi:/dev/dri/renderD128",
            type="vaapi",
            name="VAAPI renderD128",
            path="/dev/dri/renderD128",
            encoders={"h264": "h264_vaapi"},
        )
    ]
    hw_accel._detected = True

    encoder, args = hw_accel.get_video_encoder("h264")

    assert encoder == "h264_vaapi"
    assert args == []


def test_selected_nvidia_device_adds_gpu_encoder_arg() -> None:
    hw_accel = HardwareAcceleration(selected_device="nvidia:1")
    hw_accel.devices = [
        HardwareDevice(
            id="nvidia:1",
            type="nvidia",
            name="NVIDIA GPU",
            index=1,
            encoders={"hevc": "hevc_nvenc"},
        )
    ]
    hw_accel._detected = True

    encoder, args = hw_accel.get_video_encoder("hevc")

    assert encoder == "hevc_nvenc"
    assert args[-2:] == ["-gpu", "1"]


def test_status_warns_when_selected_device_is_not_detected() -> None:
    hw_accel = HardwareAcceleration(selected_device="vaapi:/dev/dri/renderD129")
    hw_accel.devices = []
    hw_accel._detected = True

    status = hw_accel.status()

    assert status.active_device_id is None
    assert "was not detected" in status.warnings[0]


def test_ffmpeg_vaapi_decoders_probe_h264_and_hevc(monkeypatch, tmp_path) -> None:
    def fake_run(cmd, **kwargs):
        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        output = cmd[-1]
        if isinstance(output, str) and output.endswith((".h264", ".hevc")):
            (tmp_path / output.split("/")[-1]).write_bytes(b"sample")
        return Result()

    monkeypatch.setattr("app.services.transcoding.hardware.subprocess.run", fake_run)
    hw_accel = HardwareAcceleration()

    decoders = hw_accel._ffmpeg_vaapi_decoders(
        tmp_path / "renderD128",
        encoders_output="libx264 libx265",
        hwaccels_output="vaapi",
    )

    assert decoders == {"h264", "hevc"}
