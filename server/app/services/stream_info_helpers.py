"""Helpers for shaping playback-info response data."""

from app.models.media_file import MediaFile


def build_media_streams(media_file: MediaFile) -> list[dict]:
    """Build Jellyfin-style media stream entries from scanned tracks."""
    streams = []

    for video_track in media_file.video_tracks:
        stream = {
            "Index": video_track.stream_index,
            "Type": "Video",
            "Codec": video_track.codec,
            "Width": video_track.width,
            "Height": video_track.height,
            "BitRate": video_track.bitrate,
            "RealFrameRate": video_track.fps,
            "Profile": video_track.profile,
            "Level": video_track.level,
            "PixelFormat": video_track.pixel_format,
            "BitDepth": video_track.bit_depth,
            "IsDefault": video_track.is_default,
            "Language": video_track.language,
            "Title": video_track.title,
        }
        streams.append({key: value for key, value in stream.items() if value is not None})

    for audio_track in media_file.audio_tracks:
        stream = {
            "Index": audio_track.stream_index,
            "Type": "Audio",
            "Codec": audio_track.codec,
            "Channels": audio_track.channels,
            "SampleRate": audio_track.sample_rate,
            "BitRate": audio_track.bitrate,
            "IsDefault": audio_track.is_default,
            "Language": audio_track.language,
            "Title": audio_track.title,
        }
        streams.append({key: value for key, value in stream.items() if value is not None})

    for subtitle_track in media_file.subtitle_tracks:
        stream = {
            "Index": subtitle_track.stream_index,
            "Type": "Subtitle",
            "Codec": subtitle_track.codec,
            "IsDefault": subtitle_track.is_default,
            "IsForced": subtitle_track.is_forced,
            "Language": subtitle_track.language,
            "Title": subtitle_track.title,
        }
        streams.append({key: value for key, value in stream.items() if value is not None})

    return streams


def calculate_available_resolutions(media_file: MediaFile) -> list[dict]:
    """Calculate standard downscale targets for manual quality selection."""
    if not media_file.video_tracks:
        return []

    video_track = media_file.video_tracks[0]
    original_width = video_track.width or 1920
    original_height = video_track.height or 1080
    available_resolutions = [
        {
            "width": original_width,
            "height": original_height,
            "label": f"{original_width}x{original_height} (Original)",
            "is_original": True,
        }
    ]

    standard_resolutions = [
        {"width": 3840, "height": 2160, "label": "4K (3840x2160)"},
        {"width": 2560, "height": 1440, "label": "1440p (2560x1440)"},
        {"width": 1920, "height": 1080, "label": "1080p (1920x1080)"},
        {"width": 1280, "height": 720, "label": "720p (1280x720)"},
        {"width": 854, "height": 480, "label": "480p (854x480)"},
        {"width": 640, "height": 360, "label": "360p (640x360)"},
    ]

    for resolution in standard_resolutions:
        is_smaller = resolution["width"] < original_width or (
            resolution["width"] == original_width and resolution["height"] < original_height
        )
        if is_smaller:
            available_resolutions.append({**resolution, "is_original": False})

    return available_resolutions
