"""Only complete subtitle extraction results may enter the shared cache."""

import asyncio
import shutil
from pathlib import Path

import pytest

from app.services.transcoding import subtitles


@pytest.fixture
def extraction_process(monkeypatch):
    started = asyncio.Event()
    release = asyncio.Event()
    processes = []

    class Process:
        returncode = None
        killed = False
        communicate_calls = 0

        def __init__(self, output):
            self.output = output
            self.output.write_text("WEBVTT\n\npartial")

        async def communicate(self):
            self.communicate_calls += 1
            await release.wait()
            if not self.killed:
                self.output.write_text("WEBVTT\n\n00:00.000 --> 00:01.000\nComplete\n")
                self.returncode = 0
            return b"", b""

        def kill(self):
            self.killed = True
            self.returncode = -9
            release.set()

    async def spawn(*command, **_kwargs):
        await asyncio.sleep(0)
        process = Process(Path(command[-1]))
        processes.append(process)
        started.set()
        return process

    monkeypatch.setattr(subtitles.asyncio, "create_subprocess_exec", spawn)
    return started, release, processes


async def test_concurrent_requests_wait_for_one_atomic_publication_and_reuse_it(tmp_path, extraction_process):
    started, release, processes = extraction_process
    output = tmp_path / "captions.vtt"
    tasks = [asyncio.create_task(subtitles.extract_subtitle_to_webvtt("ffmpeg", "movie.mkv", 3, str(output)))]
    try:
        await started.wait()
        tasks.append(asyncio.create_task(subtitles.extract_subtitle_to_webvtt("ffmpeg", "movie.mkv", 3, str(output))))
        await asyncio.sleep(0)
        assert len(processes) == 1
        assert not output.exists(), "The cache name must not expose FFmpeg's partial output"
        assert not tasks[1].done()
    finally:
        release.set()
        results = await asyncio.gather(*tasks)
    assert results == [True, True]
    assert output.read_text().endswith("Complete\n")
    assert list(tmp_path.iterdir()) == [output]
    assert await subtitles.extract_subtitle_to_webvtt("ffmpeg", "movie.mkv", 3, str(output))
    assert len(processes) == 1


async def test_cancelled_extraction_kills_and_reaps_and_removes_partial_output(tmp_path, extraction_process):
    started, _release, processes = extraction_process
    output = tmp_path / "captions.vtt"
    task = asyncio.create_task(subtitles.extract_subtitle_to_webvtt("ffmpeg", "movie.mkv", 3, str(output)))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert processes[0].killed
    assert processes[0].communicate_calls >= 1
    assert list(tmp_path.iterdir()) == []


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg is not installed")
async def test_real_ffmpeg_extracts_valid_vtt_to_a_temporary_file(tmp_path):
    source = tmp_path / "captions.srt"
    source.write_text("1\n00:00:00,000 --> 00:00:01,000\nComplete subtitle\n")
    output = tmp_path / "captions.vtt"
    async with asyncio.timeout(5):
        assert await subtitles.extract_subtitle_to_webvtt("ffmpeg", str(source), 0, str(output))
    assert output.read_text().startswith("WEBVTT\n")
    assert "Complete subtitle" in output.read_text()
    assert sorted(path.name for path in tmp_path.iterdir()) == ["captions.srt", "captions.vtt"]


async def test_timeout_kills_and_reaps_without_a_cache_entry(tmp_path, extraction_process, monkeypatch):
    _started, _release, processes = extraction_process
    monkeypatch.setattr(subtitles, "EXTRACTION_TIMEOUT_SECONDS", 0.01, raising=False)
    async with asyncio.timeout(0.5):
        assert not await subtitles.extract_subtitle_to_webvtt("ffmpeg", "movie.mkv", 3, str(tmp_path / "captions.vtt"))
    assert processes[0].killed
    assert processes[0].communicate_calls == 2
    assert list(tmp_path.iterdir()) == []


async def test_cancellation_while_spawning_still_recovers_and_reaps_the_child(tmp_path, monkeypatch):
    started = asyncio.Event()
    release = asyncio.Event()

    class Process:
        returncode = None
        reaped = False

        def kill(self):
            self.returncode = -9

        async def communicate(self):
            self.reaped = True
            return b"", b""

    process = Process()

    async def spawn(*_args, **_kwargs):
        started.set()
        await release.wait()
        return process

    monkeypatch.setattr(subtitles.asyncio, "create_subprocess_exec", spawn)
    task = asyncio.create_task(
        subtitles.extract_subtitle_to_webvtt("ffmpeg", "movie.mkv", 3, str(tmp_path / "out.vtt"))
    )
    await started.wait()
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert process.returncode == -9
    assert process.reaped
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("returncode,content", [(1, "WEBVTT\npartial"), (0, ""), (0, "not WebVTT")])
async def test_failed_or_invalid_output_never_becomes_cache_ready(tmp_path, monkeypatch, returncode, content):
    class Process:
        def __init__(self, output):
            self.returncode = returncode
            output.write_text(content)

        async def communicate(self):
            return b"", b"invalid subtitle stream"

    async def spawn(*command, **_kwargs):
        await asyncio.sleep(0)
        return Process(Path(command[-1]))

    monkeypatch.setattr(subtitles.asyncio, "create_subprocess_exec", spawn)
    assert not await subtitles.extract_subtitle_to_webvtt("ffmpeg", "movie.mkv", 3, str(tmp_path / "captions.vtt"))
    assert list(tmp_path.iterdir()) == []
