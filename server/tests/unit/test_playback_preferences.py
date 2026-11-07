"""User preferences choose available tracks deterministically without replacing explicit choices."""

import pytest

from app.models import AudioTrack, SubtitleTrack, User
from app.models.playback import PlayMethod
from app.services.playback_preferences import resolve_playback_tracks
from app.services.stream_builder import StreamBuilder
from tests.unit.test_stream_builder import create_device_profile, create_media_file


@pytest.fixture
def tracks():
    media = create_media_file()
    media.audio_tracks = [
        AudioTrack(stream_index=1, codec="aac", language="eng", is_default=True),
        AudioTrack(stream_index=2, codec="aac", language="fre", is_default=False),
    ]
    media.subtitle_tracks = [
        SubtitleTrack(stream_index=3, codec="subrip", language="eng", is_forced=False, is_default=True),
        SubtitleTrack(stream_index=4, codec="hdmv_pgs_subtitle", language="fra", is_forced=True, is_default=False),
        SubtitleTrack(stream_index=5, codec="subrip", language="fr", is_forced=False, is_default=False),
        SubtitleTrack(stream_index=6, codec="subrip", language="eng", is_forced=True, is_default=False),
    ]
    return media


def test_existing_defaults_remain_native_audio_and_subtitles_off(tracks):
    assert resolve_playback_tracks(tracks, User()) == (1, None)


@pytest.mark.parametrize("language", ["fr", "fra", "fre", "FR_ca"])
def test_language_aliases_choose_compatible_nondefault_audio_without_wrong_native_audio(tracks, language):
    audio, subtitle = resolve_playback_tracks(tracks, User(preferred_audio_language=language))
    assert audio == 2
    plan = StreamBuilder(create_device_profile()).build_stream_info(
        tracks, audio_stream_index=audio, subtitle_stream_index=subtitle
    )
    assert plan.PlayMethod == PlayMethod.DIRECT_STREAM
    assert plan.AudioStreamIndex == 2


@pytest.mark.parametrize(
    "mode,language,expected",
    [
        ("off", "fr", None),
        ("forced", "fr", 4),
        ("forced", "de", 4),
        ("forced", "en", 6),
        ("always", "fr", 4),
        ("always", "en", 3),
        ("always", "de", 3),
    ],
)
def test_subtitle_mode_and_language_fallback_matrix(tracks, mode, language, expected):
    assert resolve_playback_tracks(
        tracks, User(preferred_audio_language="de", preferred_subtitle_language=language, subtitle_mode=mode)
    ) == (1, expected)


def test_preference_ties_use_default_then_lowest_index_regardless_of_collection_order(tracks):
    tracks.audio_tracks.extend([
        AudioTrack(stream_index=7, codec="aac", language="fra", is_default=True),
        AudioTrack(stream_index=8, codec="aac", language="fr", is_default=True),
    ])
    tracks.audio_tracks.reverse()
    assert resolve_playback_tracks(tracks, User(preferred_audio_language="fr"))[0] == 7


@pytest.mark.parametrize("mode", ["off", "forced", "always"])
def test_explicit_track_and_off_override_preferences(tracks, mode):
    user = User(preferred_audio_language="fr", preferred_subtitle_language="en", subtitle_mode=mode)
    assert resolve_playback_tracks(tracks, user, audio_stream_index=1, subtitle_stream_index=5) == (1, 5)
    assert resolve_playback_tracks(tracks, user, subtitle_stream_index=-1) == (2, None)


@pytest.mark.parametrize("index", ["audio", "subtitle"])
def test_missing_explicit_index_is_rejected_instead_of_falling_back(tracks, index):
    kwargs = {f"{index}_stream_index": 99}
    with pytest.raises(ValueError, match="99 does not exist"):
        resolve_playback_tracks(tracks, User(subtitle_mode="always"), **kwargs)


def test_missing_forced_tracks_or_tracks_entirely_leaves_subtitles_off(tracks):
    tracks.subtitle_tracks = [track for track in tracks.subtitle_tracks if not track.is_forced]
    assert resolve_playback_tracks(tracks, User(subtitle_mode="forced")) == (1, None)
    tracks.subtitle_tracks = []
    tracks.audio_tracks = []
    assert resolve_playback_tracks(tracks, User(subtitle_mode="always")) == (None, None)


@pytest.mark.parametrize("enabled,method", [(True, PlayMethod.TRANSCODE), (False, PlayMethod.NONE)])
def test_image_subtitle_cannot_silently_remux_or_play_without_burning(tracks, enabled, method):
    plan = StreamBuilder(create_device_profile()).build_stream_info(
        tracks, subtitle_stream_index=4, enable_transcoding=enabled
    )
    assert plan.PlayMethod == method
    assert plan.SubtitleStreamIndex == 4
    assert plan.SubtitleDeliveryMethod == "Encode"
    assert plan.SubtitleUrl is None
    if enabled:
        assert plan.TranscodingType == "full"


def test_text_subtitles_keep_direct_play_and_have_a_scoped_media_endpoint(tracks):
    plan = StreamBuilder(create_device_profile()).build_stream_info(tracks, subtitle_stream_index=3)
    assert plan.PlayMethod == PlayMethod.DIRECT_PLAY
    assert plan.SubtitleDeliveryMethod == "External"
    assert plan.SubtitleUrl == f"/api/v1/subtitle/{tracks.id}/3"
