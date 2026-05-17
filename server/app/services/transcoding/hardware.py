"""Hardware encoder detection for ffmpeg."""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

CodecName = str

SOFTWARE_DEVICE_ID = "software"
AUTO_DEVICE_ID = "auto"

SOFTWARE_ENCODERS: dict[str, tuple[str, list[str]]] = {
    "h264": ("libx264", ["-preset", "veryfast", "-profile:v", "high", "-level", "4.1"]),
    "hevc": ("libx265", ["-preset", "veryfast"]),
}

HARDWARE_ENCODERS: dict[str, dict[str, str]] = {
    "nvidia": {
        "h264": "h264_nvenc",
        "hevc": "hevc_nvenc",
        "av1": "av1_nvenc",
    },
    "qsv": {
        "h264": "h264_qsv",
        "hevc": "hevc_qsv",
        "av1": "av1_qsv",
    },
    "vaapi": {
        "h264": "h264_vaapi",
        "hevc": "hevc_vaapi",
        "av1": "av1_vaapi",
    },
}

HARDWARE_DECODERS: dict[str, dict[str, str]] = {
    "nvidia": {
        "h264": "h264_cuvid",
        "hevc": "hevc_cuvid",
        "av1": "av1_cuvid",
    },
    "qsv": {
        "h264": "h264_qsv",
        "hevc": "hevc_qsv",
        "av1": "av1_qsv",
    },
}

NVIDIA_DECODE_SAMPLE_ENCODERS: dict[str, tuple[str, ...]] = {
    "h264": ("libx264",),
    "hevc": ("libx265",),
    "av1": ("libaom-av1", "libsvtav1", "librav1e"),
}

CODEC_ALIASES = {
    "h265": "hevc",
    "libx265": "hevc",
    "libx264": "h264",
}

VAAPI_DECODE_SAMPLE_ENCODERS: dict[str, tuple[str, str, str]] = {
    "h264": ("libx264", "h264", "h264"),
    "hevc": ("libx265", "hevc", "hevc"),
}


class HardwareCodecCapability(BaseModel):
    """Encode/decode support for one video codec."""

    codec: str
    can_decode: bool = False
    can_encode: bool = False
    source: str = "ffmpeg"


class HardwareDeviceInfo(BaseModel):
    """Detected hardware transcoding device exposed to the admin UI."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    type: str
    name: str
    path: str | None = None
    index: int | None = None
    available: bool = True
    capabilities: list[HardwareCodecCapability] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class HardwareAccelerationStatus(BaseModel):
    """Current hardware acceleration state."""

    ffmpeg_path: str
    selected_device: str
    active_device_id: str | None = None
    devices: list[HardwareDeviceInfo] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


@dataclass(slots=True)
class HardwareDevice:
    """Internal representation of a tested hardware transcoding target."""

    id: str
    type: str
    name: str
    path: str | None = None
    index: int | None = None
    encoders: dict[CodecName, str] = field(default_factory=dict)
    decoders: set[CodecName] = field(default_factory=set)
    warnings: list[str] = field(default_factory=list)

    @property
    def available(self) -> bool:
        return bool(self.encoders)

    def to_info(self) -> HardwareDeviceInfo:
        codecs = sorted(set(self.encoders) | self.decoders)
        return HardwareDeviceInfo(
            id=self.id,
            type=self.type,
            name=self.name,
            path=self.path,
            index=self.index,
            available=self.available,
            capabilities=[
                HardwareCodecCapability(
                    codec=codec,
                    can_decode=codec in self.decoders,
                    can_encode=codec in self.encoders,
                )
                for codec in codecs
            ],
            warnings=self.warnings,
        )


class HardwareAcceleration:
    """Detect and select available hardware encoders."""

    def __init__(self, ffmpeg_path: str = "ffmpeg", selected_device: str | None = None):
        self.ffmpeg_path = ffmpeg_path
        self.selected_device = selected_device or os.getenv("FERELIX_HW_ACCEL_DEVICE", AUTO_DEVICE_ID)
        self.devices: list[HardwareDevice] = []
        self.warnings: list[str] = []
        self._detected = False

    @property
    def nvenc_available(self) -> bool:
        """Compatibility shim for older command-builder checks."""
        return any(device.type == "nvidia" and device.available for device in self.devices)

    @property
    def qsv_available(self) -> bool:
        """Compatibility shim for older command-builder checks."""
        return any(device.type == "qsv" and device.available for device in self.devices)

    @property
    def vaapi_available(self) -> bool:
        """Compatibility shim for older command-builder checks."""
        return any(device.type == "vaapi" and device.available for device in self.devices)

    @property
    def vaapi_device(self) -> str | None:
        """Compatibility shim for older command-builder checks."""
        active_device = self.get_active_device()
        if active_device and active_device.type == "vaapi":
            return active_device.path
        return None

    def detect(self, *, force: bool = False) -> None:
        """Detect available hardware encoders in the current runtime context."""
        if self._detected and not force:
            return

        self._detected = True
        self.devices = []
        self.warnings = []

        try:
            encoders_output = self._run_ffmpeg("-encoders")
            decoders_output = self._run_ffmpeg("-decoders")
            hwaccels_output = self._run_ffmpeg("-hwaccels")
        except Exception as exc:
            message = f"Hardware acceleration detection failed: {exc}"
            self.warnings.append(message)
            logger.warning(message)
            return

        self.devices.extend(self._detect_nvidia_devices(encoders_output, decoders_output))
        self.devices.extend(self._detect_qsv_devices(encoders_output, decoders_output, hwaccels_output))
        self.devices.extend(self._detect_vaapi_devices(encoders_output, hwaccels_output))

        if not any(device.available for device in self.devices):
            logger.info("No hardware acceleration available, using software encoding")

    def refresh(self) -> HardwareAccelerationStatus:
        """Force a fresh hardware detection pass and return the resulting status."""
        self.detect(force=True)
        return self.status()

    def set_selected_device(self, selected_device: str | None) -> None:
        """Select the preferred hardware device for future transcodes."""
        self.selected_device = selected_device or AUTO_DEVICE_ID

    def status(self) -> HardwareAccelerationStatus:
        """Return the current detection and selection state."""
        self.detect()
        active_device = self.get_active_device()
        warnings = list(self.warnings)
        if self.selected_device not in {AUTO_DEVICE_ID, SOFTWARE_DEVICE_ID} and not self._device_by_id(
            self.selected_device
        ):
            warnings.append(f"Selected hardware device '{self.selected_device}' was not detected")

        return HardwareAccelerationStatus(
            ffmpeg_path=self.ffmpeg_path,
            selected_device=self.selected_device,
            active_device_id=active_device.id if active_device else None,
            devices=[device.to_info() for device in self.devices],
            warnings=warnings,
        )

    def get_active_device(self) -> HardwareDevice | None:
        """Return the selected available hardware device, if any."""
        self.detect()
        if self.selected_device == SOFTWARE_DEVICE_ID:
            return None

        if self.selected_device != AUTO_DEVICE_ID:
            selected = self._device_by_id(self.selected_device)
            if selected and selected.available:
                return selected

        return next((device for device in self.devices if device.available), None)

    def get_video_encoder(self, codec: str = "h264") -> tuple[str, list[str]]:
        """Return the best encoder and args for the requested video codec."""
        if codec == "copy":
            return "copy", []

        normalized_codec = normalize_video_codec(codec)
        active_device = self.get_active_device()
        if active_device and normalized_codec in active_device.encoders:
            return active_device.encoders[normalized_codec], self._encoder_args(active_device)

        if normalized_codec in SOFTWARE_ENCODERS:
            return SOFTWARE_ENCODERS[normalized_codec]

        return codec, []

    def _detect_nvidia_devices(self, encoders_output: str, decoders_output: str) -> list[HardwareDevice]:
        if not self._has_any_encoder("nvidia", encoders_output):
            return []

        gpu_rows = self._nvidia_gpu_rows()
        if not gpu_rows:
            device = HardwareDevice(
                id="nvidia:0",
                type="nvidia",
                name="NVIDIA GPU",
                index=0,
            )
            self._populate_nvidia_device(device, encoders_output, decoders_output)
            return [device] if device.available else []

        devices: list[HardwareDevice] = []
        for index, name, uuid in gpu_rows:
            device = HardwareDevice(
                id=f"nvidia:{uuid or index}",
                type="nvidia",
                name=name,
                index=index,
            )
            self._populate_nvidia_device(device, encoders_output, decoders_output, index)

            if not device.available:
                device.warnings.append("FFmpeg exposes NVENC, but test encoding failed for this GPU")
            devices.append(device)

        return devices

    def _detect_qsv_devices(
        self,
        encoders_output: str,
        decoders_output: str,
        hwaccels_output: str,
    ) -> list[HardwareDevice]:
        if "qsv" not in hwaccels_output and not self._has_any_encoder("qsv", encoders_output):
            return []

        device = HardwareDevice(
            id="qsv:auto",
            type="qsv",
            name="Intel Quick Sync",
        )
        for codec, encoder in HARDWARE_ENCODERS["qsv"].items():
            if self._has_ffmpeg_component(encoders_output, encoder) and self._test_encoder(encoder):
                device.encoders[codec] = encoder

        for codec, decoder in HARDWARE_DECODERS["qsv"].items():
            if self._has_ffmpeg_component(decoders_output, decoder):
                device.decoders.add(codec)

        if not device.available:
            return []

        return [device]

    def _populate_nvidia_device(
        self,
        device: HardwareDevice,
        encoders_output: str,
        decoders_output: str,
        index: int | None = None,
    ) -> None:
        output_args = ["-gpu", str(index)] if index is not None else None
        for codec, encoder in HARDWARE_ENCODERS["nvidia"].items():
            if self._has_ffmpeg_component(encoders_output, encoder) and self._test_encoder(
                encoder,
                output_args=output_args,
            ):
                device.encoders[codec] = encoder

        for codec, decoder in HARDWARE_DECODERS["nvidia"].items():
            if self._has_ffmpeg_component(decoders_output, decoder) and self._test_nvidia_decoder(
                codec,
                decoder,
                encoders_output,
                index=index,
            ):
                device.decoders.add(codec)

    def _detect_vaapi_devices(self, encoders_output: str, hwaccels_output: str) -> list[HardwareDevice]:
        if not self._has_any_encoder("vaapi", encoders_output):
            return []

        devices: list[HardwareDevice] = []
        for render_device in sorted(Path("/dev/dri").glob("renderD*")):
            device = HardwareDevice(
                id=f"vaapi:{render_device}",
                type="vaapi",
                name=self._vaapi_device_name(render_device),
                path=str(render_device),
            )
            for codec, encoder in HARDWARE_ENCODERS["vaapi"].items():
                if self._has_ffmpeg_component(encoders_output, encoder) and self._test_vaapi_encoder(
                    str(render_device),
                    encoder,
                ):
                    device.encoders[codec] = encoder

            device.decoders.update(self._vainfo_decoders(render_device))
            device.decoders.update(self._ffmpeg_vaapi_decoders(render_device, encoders_output, hwaccels_output))
            if not device.available:
                device.warnings.append("VAAPI render device exists, but test encoding failed")
            devices.append(device)

        return devices

    def _device_by_id(self, device_id: str) -> HardwareDevice | None:
        return next((device for device in self.devices if device.id == device_id), None)

    def _encoder_args(self, device: HardwareDevice) -> list[str]:
        if device.type == "nvidia":
            args = ["-preset", "p4", "-tune", "ll"]
            if device.index is not None:
                args.extend(["-gpu", str(device.index)])
            return args
        if device.type == "qsv":
            return ["-preset", "faster"]
        return []

    def _run_ffmpeg(self, option: str) -> str:
        result = subprocess.run(
            [self.ffmpeg_path, "-hide_banner", option],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return f"{result.stdout}\n{result.stderr}"

    def _nvidia_gpu_rows(self) -> list[tuple[int, str, str | None]]:
        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=index,name,uuid",
                    "--format=csv,noheader",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except Exception:
            return []

        if result.returncode != 0:
            return []

        rows: list[tuple[int, str, str | None]] = []
        for line in result.stdout.splitlines():
            parts = [part.strip() for part in line.split(",")]
            if len(parts) < 2:
                continue
            try:
                index = int(parts[0])
            except ValueError:
                continue
            rows.append((index, parts[1], parts[2] if len(parts) > 2 else None))
        return rows

    def _vaapi_device_name(self, render_device: Path) -> str:
        for by_path in sorted(Path("/dev/dri/by-path").glob("*-render")):
            try:
                if by_path.resolve() == render_device:
                    return f"VAAPI {render_device.name} ({by_path.name.replace('-render', '')})"
            except OSError:
                continue
        return f"VAAPI {render_device.name}"

    def _vainfo_decoders(self, render_device: Path) -> set[str]:
        try:
            result = subprocess.run(
                ["vainfo", "--display", "drm", "--device", str(render_device)],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except Exception:
            return set()

        if result.returncode != 0:
            return set()

        output = f"{result.stdout}\n{result.stderr}"
        decoders: set[str] = set()
        for codec, profiles in {
            "h264": ("VAProfileH264",),
            "hevc": ("VAProfileHEVC",),
            "av1": ("VAProfileAV1",),
        }.items():
            if any(
                any(profile in line and "VAEntrypointVLD" in line for line in output.splitlines())
                for profile in profiles
            ):
                decoders.add(codec)
        return decoders

    def _ffmpeg_vaapi_decoders(
        self,
        render_device: Path,
        encoders_output: str,
        hwaccels_output: str,
    ) -> set[str]:
        if "vaapi" not in hwaccels_output:
            return set()

        decoders: set[str] = set()
        for codec, (sample_encoder, bitstream_format, extension) in VAAPI_DECODE_SAMPLE_ENCODERS.items():
            if not self._has_ffmpeg_component(encoders_output, sample_encoder):
                continue
            if self._test_vaapi_decoder(render_device, sample_encoder, bitstream_format, extension):
                decoders.add(codec)
        return decoders

    def _test_vaapi_decoder(
        self,
        render_device: Path,
        sample_encoder: str,
        bitstream_format: str,
        extension: str,
    ) -> bool:
        try:
            with tempfile.TemporaryDirectory(prefix="ferelix-hw-probe-") as temp_dir:
                sample_path = Path(temp_dir) / f"sample.{extension}"
                create_sample = subprocess.run(
                    [
                        self.ffmpeg_path,
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-y",
                        "-f",
                        "lavfi",
                        "-i",
                        "testsrc2=s=256x256:d=0.2",
                        "-frames:v",
                        "3",
                        "-c:v",
                        sample_encoder,
                        "-f",
                        bitstream_format,
                        str(sample_path),
                    ],
                    capture_output=True,
                    timeout=15,
                )
                if create_sample.returncode != 0:
                    return False

                decode_sample = subprocess.run(
                    [
                        self.ffmpeg_path,
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-hwaccel",
                        "vaapi",
                        "-hwaccel_device",
                        str(render_device),
                        "-hwaccel_output_format",
                        "vaapi",
                        "-f",
                        bitstream_format,
                        "-i",
                        str(sample_path),
                        "-f",
                        "null",
                        "-",
                    ],
                    capture_output=True,
                    timeout=15,
                )
                return decode_sample.returncode == 0
        except Exception:
            return False

    def _has_any_encoder(self, device_type: str, output: str) -> bool:
        return any(self._has_ffmpeg_component(output, encoder) for encoder in HARDWARE_ENCODERS[device_type].values())

    def _has_ffmpeg_component(self, output: str, name: str) -> bool:
        return name in output

    def _test_encoder(self, encoder: str, output_args: list[str] | None = None) -> bool:
        try:
            cmd = [
                self.ffmpeg_path,
                "-hide_banner",
                "-f",
                "lavfi",
                "-i",
                "color=black:s=256x256:d=0.1",
                "-c:v",
                encoder,
            ]
            if output_args:
                cmd.extend(output_args)
            cmd.extend(["-f", "null", "-"])
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=10,
            )
            return result.returncode == 0
        except Exception:
            return False

    def _test_nvidia_decoder(
        self,
        codec: str,
        decoder: str,
        encoders_output: str,
        index: int | None = None,
    ) -> bool:
        sample_encoders = NVIDIA_DECODE_SAMPLE_ENCODERS.get(codec, ())
        sample_encoder = next(
            (encoder for encoder in sample_encoders if self._has_ffmpeg_component(encoders_output, encoder)),
            None,
        )
        if not sample_encoder:
            return False

        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                sample_path = Path(tmp_dir) / f"sample-{codec}.mkv"
                encode_sample = subprocess.run(
                    [
                        self.ffmpeg_path,
                        "-hide_banner",
                        "-f",
                        "lavfi",
                        "-i",
                        "color=black:s=64x64:d=0.1",
                        "-frames:v",
                        "1",
                        "-c:v",
                        sample_encoder,
                        str(sample_path),
                    ],
                    capture_output=True,
                    timeout=20,
                )
                if encode_sample.returncode != 0 or not sample_path.exists():
                    return False

                decode_cmd = [
                    self.ffmpeg_path,
                    "-hide_banner",
                    "-hwaccel",
                    "cuda",
                    "-hwaccel_output_format",
                    "cuda",
                ]
                if index is not None:
                    decode_cmd.extend(["-hwaccel_device", str(index)])
                decode_cmd.extend([
                    "-c:v",
                    decoder,
                    "-i",
                    str(sample_path),
                    "-f",
                    "null",
                    "-",
                ])
                decode_sample = subprocess.run(
                    decode_cmd,
                    capture_output=True,
                    timeout=15,
                )
                return decode_sample.returncode == 0
        except Exception:
            return False

    def _test_vaapi_encoder(self, device: str, encoder: str) -> bool:
        try:
            result = subprocess.run(
                [
                    self.ffmpeg_path,
                    "-hide_banner",
                    "-vaapi_device",
                    device,
                    "-f",
                    "lavfi",
                    "-i",
                    "color=black:s=256x256:d=0.1",
                    "-vf",
                    "format=nv12,hwupload",
                    "-c:v",
                    encoder,
                    "-f",
                    "null",
                    "-",
                ],
                capture_output=True,
                timeout=10,
            )
            return result.returncode == 0
        except Exception:
            return False


def normalize_video_codec(codec: str | None) -> str:
    """Normalize common FFmpeg and media metadata codec aliases."""
    if not codec:
        return ""
    normalized = codec.lower()
    return CODEC_ALIASES.get(normalized, normalized)
