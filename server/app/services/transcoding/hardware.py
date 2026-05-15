"""Hardware encoder detection for ffmpeg."""

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class HardwareAcceleration:
    """Detect and select available hardware encoders."""

    def __init__(self, ffmpeg_path: str = "ffmpeg"):
        self.ffmpeg_path = ffmpeg_path
        self.nvenc_available = False
        self.qsv_available = False
        self.vaapi_available = False
        self.vaapi_device: str | None = None
        self._detected = False

    def detect(self) -> None:
        """Detect available hardware encoders."""
        if self._detected:
            return

        self._detected = True
        try:
            result = subprocess.run(
                [self.ffmpeg_path, "-hide_banner", "-encoders"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            encoders_output = result.stdout

            if "h264_nvenc" in encoders_output and self._test_encoder("h264_nvenc"):
                self.nvenc_available = True
                logger.info("NVENC hardware acceleration available")

            if "h264_qsv" in encoders_output and self._test_encoder("h264_qsv"):
                self.qsv_available = True
                logger.info("Intel Quick Sync hardware acceleration available")

            if "h264_vaapi" in encoders_output:
                for device in ["/dev/dri/renderD128", "/dev/dri/renderD129"]:
                    if Path(device).exists() and self._test_vaapi_encoder(device):
                        self.vaapi_device = device
                        self.vaapi_available = True
                        logger.info("VAAPI hardware acceleration available on %s", device)
                        break
        except Exception as exc:
            logger.warning("Hardware acceleration detection failed: %s", exc)

        if not any([self.nvenc_available, self.qsv_available, self.vaapi_available]):
            logger.info("No hardware acceleration available, using software encoding")

    def get_video_encoder(self, codec: str = "h264") -> tuple[str, list[str]]:
        """Return the best encoder and args for the requested video codec."""
        if codec == "copy":
            return "copy", []

        if codec in ("h264", "libx264"):
            if self.nvenc_available:
                return "h264_nvenc", ["-preset", "p4", "-tune", "ll"]
            if self.qsv_available:
                return "h264_qsv", ["-preset", "faster"]
            if self.vaapi_available and self.vaapi_device:
                return "h264_vaapi", []
            return "libx264", ["-preset", "veryfast", "-profile:v", "high", "-level", "4.1"]

        if codec in ("hevc", "h265", "libx265"):
            if self.nvenc_available:
                return "hevc_nvenc", ["-preset", "p4", "-tune", "ll"]
            if self.qsv_available:
                return "hevc_qsv", ["-preset", "faster"]
            if self.vaapi_available and self.vaapi_device:
                return "hevc_vaapi", []
            return "libx265", ["-preset", "veryfast"]

        return codec, []

    def _test_encoder(self, encoder: str) -> bool:
        try:
            result = subprocess.run(
                [
                    self.ffmpeg_path,
                    "-hide_banner",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=black:s=64x64:d=0.1",
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

    def _test_vaapi_encoder(self, device: str) -> bool:
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
                    "color=black:s=64x64:d=0.1",
                    "-vf",
                    "format=nv12,hwupload",
                    "-c:v",
                    "h264_vaapi",
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
