"""Exercise real subtitle filtering when FFmpeg is available."""

import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest

from app.services.thumbnails import generate_video_thumbnail
from app.services.transcoding.commands import HlsCommandBuilder, HlsCommandOptions, escape_filter_filename
from app.services.transcoding.files import read_process_messages, terminate_process
from app.services.transcoding.hardware import HardwareAcceleration


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg is not installed")
def test_subtitle_filename_with_filter_metacharacters(tmp_path: Path) -> None:
    subtitle = tmp_path / "Bob's: movie,[one].srt"
    subtitle.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n")
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=160x90:d=0.1",
            "-vf",
            f"subtitles=filename={escape_filter_filename(str(subtitle))}:stream_index=0",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg is not installed")
def test_subtitle_filter_uses_subtitle_ordinal_not_absolute_stream_index(tmp_path: Path) -> None:
    subtitle = tmp_path / "captions.srt"
    subtitle.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n")
    source = tmp_path / "movie.mkv"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=160x90:d=0.2",
            "-i",
            str(subtitle),
            "-map",
            "0:v",
            "-map",
            "1:s",
            "-map",
            "1:s",
            "-c:v",
            "libx264",
            "-c:s",
            "srt",
            str(source),
        ],
        capture_output=True,
        timeout=15,
        check=True,
    )
    hardware = HardwareAcceleration(selected_device="software")
    hardware._detected = True
    command = HlsCommandBuilder("ffmpeg", hardware).build_transcode(
        HlsCommandOptions(
            input_path=str(source),
            playlist_path=str(tmp_path / "playlist.m3u8"),
            segment_pattern=str(tmp_path / "segment_%03d.ts"),
            subtitle_stream_index=2,
            subtitle_filter_index=1,
        )
    )
    result = subprocess.run(command, capture_output=True, text=True, timeout=15, check=False)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "playlist.m3u8").is_file()


@pytest.mark.parametrize("arguments", [b"python\0server.py\0", b"ffmpeg\0-i\0movie.mkv\0/other/playlist.m3u8\0"])
def test_stale_pid_cannot_kill_an_unrelated_process(monkeypatch, arguments: bytes) -> None:
    killed = []
    monkeypatch.setattr(Path, "read_bytes", lambda _path: arguments)
    monkeypatch.setattr("app.services.transcoding.files.os.kill", lambda *args: killed.append(args))
    terminate_process(123, "/our-job")
    assert not killed


async def test_ffmpeg_progress_handles_carriage_returns_beyond_streamreader_limit() -> None:
    stream = asyncio.StreamReader()
    progress = b"frame=1 time=00:00:01.00 bitrate=100.0kbits/s\r"
    stream.feed_data(progress * 3000)
    stream.feed_eof()
    messages = [message async for message in read_process_messages(stream)]
    assert len(messages) == 3000
    assert messages[0] == progress.decode().strip()


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg is not installed")
def test_thumbnail_for_short_limited_range_video(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "movie.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=160x90:rate=10",
            "-t",
            "1",
            "-c:v",
            "libx264",
            str(source),
        ],
        capture_output=True,
        timeout=15,
        check=True,
    )
    monkeypatch.setenv("FERELIX_THUMBNAIL_DIR", str(tmp_path / "thumbnails"))
    output = generate_video_thumbnail(source, 1.0)
    assert output is not None
    assert Path(output).read_bytes().startswith(b"\xff\xd8")
