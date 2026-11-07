"""Resolve initial preferences once; explicit per-playback selections win."""

from app.models.media_file import AudioTrack, MediaFile, SubtitleTrack
from app.models.user import SubtitleMode, User
from app.services.languages import normalize_language


def _preferred_track[Track: AudioTrack | SubtitleTrack](tracks: list[Track], language: str | None) -> Track | None:
    preferred = normalize_language(language)
    matching = [track for track in tracks if preferred and normalize_language(track.language) == preferred]
    candidates = matching or tracks
    return min(candidates, key=lambda track: (not bool(track.is_default), track.stream_index), default=None)


def resolve_playback_tracks(
    media: MediaFile,
    user: User,
    audio_stream_index: int | None = None,
    subtitle_stream_index: int | None = None,
) -> tuple[int | None, int | None]:
    """Return absolute indexes, with None for no track and -1 as explicit subtitle-off.

    Forced mode considers only forced tracks; always considers all tracks.
    Within either set, prefer matching language, then default disposition, then
    lowest stream index. An unavailable language falls back to default/first.
    This helper never modifies a session or persists an implicit preference.
    """
    if audio_stream_index is not None:
        if not any(track.stream_index == audio_stream_index for track in media.audio_tracks):
            raise ValueError(f"Audio stream index {audio_stream_index} does not exist")
    else:
        audio = _preferred_track(media.audio_tracks, user.preferred_audio_language)
        audio_stream_index = audio.stream_index if audio is not None else None

    if subtitle_stream_index == -1:
        return audio_stream_index, None
    if subtitle_stream_index is not None:
        if not any(track.stream_index == subtitle_stream_index for track in media.subtitle_tracks):
            raise ValueError(f"Subtitle stream index {subtitle_stream_index} does not exist")
        return audio_stream_index, subtitle_stream_index

    mode = user.subtitle_mode or SubtitleMode.OFF
    if mode == SubtitleMode.OFF:
        return audio_stream_index, None
    candidates = [track for track in media.subtitle_tracks if mode == SubtitleMode.ALWAYS or track.is_forced]
    subtitle = _preferred_track(candidates, user.preferred_subtitle_language)
    return audio_stream_index, subtitle.stream_index if subtitle is not None else None
