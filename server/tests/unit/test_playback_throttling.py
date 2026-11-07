"""Encoder pause/resume hysteresis and stop safety."""

import signal
from unittest.mock import MagicMock

import pytest

from app.services.transcoding.throttling import PlaybackBuffer, resume_before_stop


@pytest.mark.parametrize("start", [0.0, 600.0])
def test_playback_buffer_pauses_then_resumes_without_flapping(start):
    process = MagicMock(returncode=None)
    buffer = PlaybackBuffer("session", start_time=start, position=start)
    buffer.encoded_duration = 119.0
    assert buffer.reconcile(process) is False
    buffer.encoded_duration = 120.0
    assert buffer.reconcile(process) is True
    process.send_signal.assert_called_once_with(signal.SIGSTOP)
    buffer.position += 59.0
    assert buffer.reconcile(process) is False
    buffer.position += 1.0
    assert buffer.reconcile(process) is True
    assert process.send_signal.call_args.args == (signal.SIGCONT,)
    assert buffer.paused is False


def test_stop_resumes_paused_encoder_before_quit():
    process = MagicMock(returncode=None)
    resume_before_stop(process)
    process.send_signal.assert_called_once_with(signal.SIGCONT)


def test_old_heartbeat_does_not_resume_new_encoder():
    from app.services.transcoder import FFmpegTranscoder

    transcoder = object.__new__(FFmpegTranscoder)
    process = MagicMock(returncode=None)
    buffer = PlaybackBuffer("session", generation=2, encoded_duration=120, paused=True)
    transcoder._playback_buffers = {"job": buffer}
    transcoder._active_jobs = {"job": process}
    transcoder.update_playback_position("session", 100, generation=1)
    assert buffer.position == 0
    assert buffer.paused
    process.send_signal.assert_not_called()


def test_encoder_does_not_pause_before_the_first_playlist_is_ready():
    process = MagicMock(returncode=None)
    buffer = PlaybackBuffer("session", encoded_duration=300, ready=False)
    assert buffer.reconcile(process) is False
    process.send_signal.assert_not_called()
    buffer.ready = True
    assert buffer.reconcile(process) is True
    process.send_signal.assert_called_once_with(signal.SIGSTOP)
