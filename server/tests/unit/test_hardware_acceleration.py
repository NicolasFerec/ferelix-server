"""Tests for hardware transcoding detection and selection."""

from pathlib import Path

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


def test_vaapi_device_name_uses_lspci_chip_name(monkeypatch) -> None:
    class Result:
        returncode = 0
        stdout = "c3:00.0 VGA compatible controller: Advanced Micro Devices, Inc. [AMD/ATI] Navi 23 [Radeon RX 6600]\n"
        stderr = ""

    monkeypatch.setattr("app.services.transcoding.hardware.subprocess.run", lambda *args, **kwargs: Result())

    hw_accel = HardwareAcceleration()
    monkeypatch.setattr(hw_accel, "_vaapi_pci_slot", lambda render_device: "0000:c3:00.0")

    assert hw_accel._vaapi_device_name(Path("/dev/dri/renderD128")) == "VAAPI Radeon RX 6600"


def test_pci_device_name_is_trimmed_for_readability() -> None:
    hw_accel = HardwareAcceleration()

    assert hw_accel._clean_pci_device_name("Advanced Micro Devices, Inc. [AMD/ATI] HawkPoint1 (rev d3)") == (
        "HawkPoint1"
    )
    assert hw_accel._clean_pci_device_name("Intel Corporation Alder Lake-P GT2 [Iris Xe Graphics]") == (
        "Iris Xe Graphics"
    )
    assert hw_accel._clean_pci_device_name("NVIDIA Corporation GA104 [GeForce RTX 3070] (rev a1)") == (
        "GeForce RTX 3070"
    )


def test_nvidia_decoders_are_probed_before_being_reported(monkeypatch, tmp_path) -> None:
    calls: list[list[str]] = []

    class FakeTemporaryDirectory:
        def __enter__(self):
            return tmp_path

        def __exit__(self, *args) -> None:
            return None

    def fake_run(cmd, **kwargs):
        calls.append(cmd)

        class Result:
            stdout = ""
            stderr = ""

            def __init__(self, returncode: int):
                self.returncode = returncode

        output = cmd[-1]
        if isinstance(output, str) and output.endswith(".mkv"):
            (tmp_path / output.split("/")[-1]).write_bytes(b"sample")
            return Result(0)

        if "av1_cuvid" in cmd:
            return Result(1)

        return Result(0)

    monkeypatch.setattr("app.services.transcoding.hardware.tempfile.TemporaryDirectory", FakeTemporaryDirectory)
    monkeypatch.setattr("app.services.transcoding.hardware.subprocess.run", fake_run)

    hw_accel = HardwareAcceleration()
    device = HardwareDevice(
        id="nvidia:0",
        type="nvidia",
        name="NVIDIA GPU",
        index=0,
    )

    hw_accel._populate_nvidia_device(
        device,
        encoders_output="h264_nvenc libx264 av1_nvenc libaom-av1",
        decoders_output="h264_cuvid av1_cuvid",
        index=0,
    )

    assert device.decoders == {"h264"}
    assert any("av1_cuvid" in call for call in calls)


def test_nvidia_hevc_decode_probe_uses_realistic_sample(monkeypatch, tmp_path) -> None:
    calls: list[list[str]] = []

    class FakeTemporaryDirectory:
        def __enter__(self):
            return tmp_path

        def __exit__(self, *args) -> None:
            return None

    def fake_run(cmd, **kwargs):
        calls.append(cmd)

        class Result:
            returncode = 0
            stdout = b""
            stderr = b""

        output = cmd[-1]
        if isinstance(output, str) and output.endswith(".mkv"):
            (tmp_path / output.split("/")[-1]).write_bytes(b"sample")
        return Result()

    monkeypatch.setattr("app.services.transcoding.hardware.tempfile.TemporaryDirectory", FakeTemporaryDirectory)
    monkeypatch.setattr("app.services.transcoding.hardware.subprocess.run", fake_run)

    hw_accel = HardwareAcceleration()

    assert hw_accel._test_nvidia_decoder(
        "hevc",
        "hevc_cuvid",
        "libx265 hevc_cuvid",
        index=0,
    )

    encode_cmd = calls[0]
    assert "color=black:s=256x256:d=0.2" in encode_cmd
    assert encode_cmd[encode_cmd.index("-frames:v") + 1] == "3"
    assert encode_cmd[encode_cmd.index("-pix_fmt") + 1] == "yuv420p"
