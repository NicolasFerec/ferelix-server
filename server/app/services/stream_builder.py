"""Stream builder service for making playback decisions."""

import logging
from typing import Any

from app.models.media_file import MediaFile
from app.models.playback import (
    DeviceProfile,
    DeviceProfileCondition,
    PlayMethod,
    StreamInfo,
    TranscodeReason,
)

logger = logging.getLogger(__name__)


class StreamBuilder:
    """Builds stream info by comparing device capabilities with media metadata."""

    def __init__(self, device_profile: DeviceProfile):
        """Initialize with device profile."""
        self.device_profile = device_profile
        self.direct_play_profiles = device_profile.DirectPlayProfiles
        self.codec_profiles = device_profile.CodecProfiles

    def build_stream_info(
        self,
        media_file: MediaFile,
        enable_direct_play: bool = True,
        enable_direct_stream: bool = True,
        enable_transcoding: bool = True,
        requested_resolution: dict | None = None,
    ) -> StreamInfo:
        """Build stream info for a media file based on device capabilities."""

        logger.debug(f"Building stream info for {media_file.file_name}")

        # Start with basic stream info
        stream_info = StreamInfo(
            Id=str(media_file.id),
            Path=media_file.file_path,
            Container=media_file.file_extension.lstrip(".") if media_file.file_extension else "unknown",
            PlayMethod=PlayMethod.DIRECT_PLAY,
            VideoType="VideoFile",
            RunTimeTicks=int(media_file.duration * 10_000_000) if media_file.duration else None,
            Bitrate=media_file.bitrate,
            MediaStreams=self._build_media_streams(media_file),
        )

        # Calculate available resolution options
        stream_info.AvailableResolutions = self._calculate_available_resolutions(media_file)

        # Check for manual resolution override
        if requested_resolution:
            logger.debug(f"Manual resolution override requested: {requested_resolution}")
            # Force transcoding with the requested resolution
            stream_info.PlayMethod = PlayMethod.TRANSCODE
            stream_info.TranscodingUrl = f"/api/v1/stream/{media_file.id}/master.m3u8"
            stream_info.TranscodingContainer = "mp4"
            stream_info.TranscodingVideoCodec = "h264"
            stream_info.TranscodingAudioCodec = "aac"
            stream_info.TranscodingType = "full"  # Resolution override requires full transcode

            from ..models.playback import TranscodeSettings

            stream_info.TranscodeSettings = TranscodeSettings(
                VideoCodec="h264",
                AudioCodec="aac",
                MaxWidth=requested_resolution.get("width"),
                MaxHeight=requested_resolution.get("height"),
                IsRemuxOnly=False,
            )
            logger.debug(f"Forced transcode for resolution {requested_resolution}")
            return stream_info

        # Try direct play first
        if enable_direct_play:
            direct_play_result = self._check_direct_play(media_file)
            if direct_play_result.can_play:
                stream_info.PlayMethod = PlayMethod.DIRECT_PLAY
                stream_info.DirectStreamUrl = f"/api/v1/stream/{media_file.id}"
                stream_info.TranscodeReasons = direct_play_result.reasons
                logger.debug(f"Direct play enabled for {media_file.file_name}")
                return stream_info

            # Collect reasons why direct play failed
            stream_info.TranscodeReasons.extend(direct_play_result.reasons)

        # Try direct stream (remux)
        if enable_direct_stream:
            direct_stream_result = self._check_direct_stream(media_file)
            if direct_stream_result.can_play:
                stream_info.PlayMethod = PlayMethod.DIRECT_STREAM
                stream_info.TranscodingUrl = f"/api/v1/hls/{media_file.id}/remux"
                stream_info.TranscodingContainer = "ts"  # HLS segments
                stream_info.TranscodingType = "remux"  # Flag for frontend

                # Mark as remux-only for fast container conversion
                stream_info.IsRemuxOnly = True

                # Set remux transcoding settings
                from ..models.playback import TranscodeSettings

                stream_info.TranscodeSettings = TranscodeSettings(
                    VideoCodec="copy", AudioCodec="copy", IsRemuxOnly=True
                )

                logger.debug(f"Direct stream (remux) enabled for {media_file.file_name}")
                return stream_info

            # Add additional reasons
            stream_info.TranscodeReasons.extend(direct_stream_result.reasons)

            # If video can be copied but audio requires transcoding, prefer audio-transcode (copy video, transcode audio)
            video_ok, audio_ok = self._needs_audio_transcode(media_file)
            if video_ok and not audio_ok:
                stream_info.PlayMethod = PlayMethod.TRANSCODE
                stream_info.TranscodingUrl = f"/api/v1/stream/{media_file.id}/master.m3u8"
                stream_info.TranscodingContainer = "ts"  # HLS uses TS segments
                stream_info.TranscodingVideoCodec = "copy"
                stream_info.TranscodingAudioCodec = "aac"
                stream_info.TranscodingType = "audio-only"  # Flag for frontend
                stream_info.TranscodeReasons.append(TranscodeReason.AUDIO_TRANSCODE_REQUIRED)

                from ..models.playback import TranscodeSettings

                stream_info.TranscodeSettings = TranscodeSettings(
                    VideoCodec="copy",
                    AudioCodec="aac",
                    AudioBitrate=128000,
                    IsRemuxOnly=False,
                )

                logger.debug(f"Audio-transcode (video copy) enabled for {media_file.file_name}")
                return stream_info

        # Fall back to transcoding (treat media as video files; music handling removed)
        if enable_transcoding:
            stream_info.PlayMethod = PlayMethod.TRANSCODE
            # Regular video transcoding
            stream_info.TranscodingUrl = f"/api/v1/stream/{media_file.id}/master.m3u8"
            stream_info.TranscodingContainer = "mp4"
            stream_info.TranscodingVideoCodec = "h264"
            stream_info.TranscodingAudioCodec = "aac"
            stream_info.TranscodingType = "full"  # Flag for frontend
            logger.debug(f"Transcoding required for {media_file.file_name}")
        else:
            # No playback method available
            logger.warning(f"No playback method available for {media_file.file_name}")
            stream_info.PlayMethod = PlayMethod.TRANSCODE
            stream_info.TranscodingType = "full"  # Fallback to full transcode
            stream_info.TranscodeReasons.append(TranscodeReason.DIRECT_PLAY_ERROR)

        return stream_info

    def _check_direct_play(self, media_file: MediaFile) -> PlaybackResult:
        """Check if media can be played directly without any server processing."""

        reasons = []

        # Check container support
        container = media_file.file_extension.lstrip(".") if media_file.file_extension else "unknown"
        logger.debug(f"Checking direct play for file: {media_file.file_name} (container: {container})")

        container_supported = self._is_container_supported(container, "Video")
        if not container_supported:
            reasons.append(TranscodeReason.CONTAINER_NOT_SUPPORTED)
            logger.debug(f"Container {container} not supported, direct play failed")
            return PlaybackResult(False, reasons)

        # Check video codec support
        if media_file.video_tracks:
            video_track = media_file.video_tracks[0]  # Use first video track
            logger.debug(
                f"Checking video codec: {video_track.codec}, resolution: {video_track.width}x{video_track.height}, bit_depth: {video_track.bit_depth}"
            )
            video_codec_result = self._check_video_codec_support(video_track)
            if not video_codec_result.can_play:
                reasons.extend(video_codec_result.reasons)
                logger.debug(f"Video codec check failed, reasons: {video_codec_result.reasons}")
                return PlaybackResult(False, reasons)

        # Check audio codec support
        if media_file.audio_tracks:
            audio_track = media_file.audio_tracks[0]  # Use first audio track
            logger.debug(f"Checking audio codec: {audio_track.codec}")
            audio_codec_result = self._check_audio_codec_support(audio_track)
            if not audio_codec_result.can_play:
                reasons.extend(audio_codec_result.reasons)
                logger.debug(f"Audio codec check failed, reasons: {audio_codec_result.reasons}")
                return PlaybackResult(False, reasons)

        logger.debug("Direct play check passed!")
        return PlaybackResult(True, reasons)

    def _check_direct_stream(self, media_file: MediaFile) -> PlaybackResult:
        """Check if media can be remuxed (container change only)."""

        reasons = []

        # Check video codec support (container will be changed to HLS/fMP4)
        if media_file.video_tracks:
            video_track = media_file.video_tracks[0]
            video_codec_result = self._check_video_codec_support(video_track, target_container="mp4")
            if not video_codec_result.can_play:
                reasons.extend(video_codec_result.reasons)
                return PlaybackResult(False, reasons)

        # Check audio codec support (container will be changed)
        if media_file.audio_tracks:
            audio_track = media_file.audio_tracks[0]
            audio_codec_result = self._check_audio_codec_support(audio_track, target_container="mp4")
            if not audio_codec_result.can_play:
                reasons.extend(audio_codec_result.reasons)
                return PlaybackResult(False, reasons)

        return PlaybackResult(True, reasons)

    def _needs_audio_transcode(self, media_file: MediaFile) -> tuple[bool, bool]:
        """Return (video_ok, audio_ok) for remux target (mp4)."""
        video_ok = True
        audio_ok = True
        # Check video support for remux target (mp4)
        if media_file.video_tracks:
            video_track = media_file.video_tracks[0]
            video_res = self._check_video_codec_support(video_track, target_container="mp4")
            video_ok = video_res.can_play
        # Check audio support for remux target (mp4)
        if media_file.audio_tracks:
            audio_track = media_file.audio_tracks[0]
            audio_res = self._check_audio_codec_support(audio_track, target_container="mp4")
            audio_ok = audio_res.can_play
        return video_ok, audio_ok

    def _check_video_codec_support(self, video_track: Any, target_container: str | None = None) -> PlaybackResult:
        """Check if a video codec is supported by the client."""

        reasons = []
        codec = video_track.codec

        if not codec:
            reasons.append(TranscodeReason.UNKNOWN_VIDEO_STREAM_INFO)
            return PlaybackResult(False, reasons)

        # Check if codec is in any DirectPlayProfile
        container = target_container or "mp4"  # Default to mp4 for compatibility check
        codec_supported = False

        for profile in self.direct_play_profiles:
            if (
                profile.Type == "Video"
                and profile.VideoCodec
                and container in profile.Container.split(",")
                and codec in profile.VideoCodec.split(",")
            ):
                codec_supported = True
                break

        if not codec_supported:
            reasons.append(TranscodeReason.VIDEO_CODEC_NOT_SUPPORTED)
            return PlaybackResult(False, reasons)

        # Check codec profile constraints
        constraint_result = self._check_codec_constraints(video_track, codec, "Video")
        if not constraint_result.can_play:
            reasons.extend(constraint_result.reasons)
            return PlaybackResult(False, reasons)

        return PlaybackResult(True, reasons)

    def _check_audio_codec_support(self, audio_track: Any, target_container: str | None = None) -> PlaybackResult:
        """Check if an audio codec is supported by the client."""

        reasons = []
        codec = audio_track.codec

        if not codec:
            reasons.append(TranscodeReason.UNKNOWN_AUDIO_STREAM_INFO)
            return PlaybackResult(False, reasons)

        # Check if codec is in any DirectPlayProfile
        container = target_container or "mp4"
        codec_supported = False

        for profile in self.direct_play_profiles:
            if (
                profile.AudioCodec
                and codec in profile.AudioCodec.split(",")
                and (profile.Type == "Audio" or (profile.Type == "Video" and container in profile.Container.split(",")))
            ):
                codec_supported = True
                break

        if not codec_supported:
            reasons.append(TranscodeReason.AUDIO_CODEC_NOT_SUPPORTED)
            return PlaybackResult(False, reasons)

        # Check codec profile constraints
        constraint_result = self._check_codec_constraints(audio_track, codec, "Audio")
        if not constraint_result.can_play:
            reasons.extend(constraint_result.reasons)
            return PlaybackResult(False, reasons)

        return PlaybackResult(True, reasons)

    def _check_codec_constraints(self, track: Any, codec: str, track_type: str) -> PlaybackResult:
        """Check codec profile constraints (level, bitrate, resolution, etc.)."""

        reasons = []

        # Find matching codec profiles
        matching_profiles = [p for p in self.codec_profiles if p.Type == track_type and p.Codec == codec]

        for profile in matching_profiles:
            for condition in profile.Conditions:
                constraint_failed = self._evaluate_condition(track, condition)
                if constraint_failed:
                    reason = self._condition_to_transcode_reason(condition.Property, track_type)
                    if reason:
                        actual_value = self._get_track_property_value(track, condition.Property)
                        logger.debug(
                            f"Constraint failed: {condition.Property} {condition.Condition} {condition.Value} (actual: {actual_value}, IsRequired: {condition.IsRequired})"
                        )
                        reasons.append(reason)

                    # Required constraints must pass
                    if condition.IsRequired:
                        logger.debug(f"Required constraint failed: {condition.Property}, blocking direct play")
                        return PlaybackResult(False, reasons)

        return PlaybackResult(True, reasons)

    def _evaluate_condition(self, track: Any, condition: DeviceProfileCondition) -> bool:
        """Evaluate if a codec profile condition fails."""

        property_name = condition.Property
        condition_type = condition.Condition
        expected_value = condition.Value

        # Get actual value from track
        actual_value = self._get_track_property_value(track, property_name)
        if actual_value is None:
            return False  # Can't evaluate, assume it passes

        try:
            if condition_type == "LessThanEqual":
                return float(actual_value) > float(expected_value)
            elif condition_type == "Equals":
                return str(actual_value) != expected_value
            elif condition_type == "EqualsAny":
                allowed_values = expected_value.split("|")
                return str(actual_value) not in allowed_values
            elif condition_type == "GreaterThanEqual":
                return float(actual_value) < float(expected_value)
        except ValueError, TypeError:
            # If we can't compare, assume it passes
            return False

        return False

    def _get_track_property_value(self, track: Any, property_name: str) -> Any:
        """Get property value from a media track."""

        property_map = {
            # Video properties
            "VideoLevel": "level",
            "Width": "width",
            "Height": "height",
            "VideoBitrate": "bitrate",
            "VideoBitDepth": "bit_depth",
            "VideoProfile": "profile",
            "VideoRange": self._get_video_range,
            # Audio properties
            "AudioChannels": "channels",
            "AudioSampleRate": "sample_rate",
            "AudioBitrate": "bitrate",
        }

        prop_getter = property_map.get(property_name)
        if not prop_getter:
            return None

        if callable(prop_getter):
            return prop_getter(track)
        else:
            return getattr(track, prop_getter, None)

    def _get_video_range(self, track: Any) -> str:
        """Determine if track is HDR or SDR based on color metadata."""
        color_space = getattr(track, "color_space", "").lower()
        color_primaries = getattr(track, "color_primaries", "").lower()
        transfer_characteristics = getattr(track, "transfer_characteristics", "").lower()

        hdr_indicators = ["bt2020", "rec2020", "smpte2084", "hlg", "arib-std-b67"]

        is_hdr = (
            any(indicator in color_space for indicator in hdr_indicators)
            or any(indicator in color_primaries for indicator in ["bt2020", "rec2020"])
            or any(indicator in transfer_characteristics for indicator in ["smpte2084", "arib-std-b67", "hlg"])
        )

        return "HDR" if is_hdr else "SDR"

    def _condition_to_transcode_reason(self, property_name: str, track_type: str) -> TranscodeReason | None:
        """Map condition property to transcode reason."""

        reason_map = {
            "VideoLevel": TranscodeReason.VIDEO_LEVEL_NOT_SUPPORTED,
            "Width": TranscodeReason.VIDEO_RESOLUTION_NOT_SUPPORTED,
            "Height": TranscodeReason.VIDEO_RESOLUTION_NOT_SUPPORTED,
            "VideoBitrate": TranscodeReason.VIDEO_BITRATE_NOT_SUPPORTED,
            "VideoBitDepth": TranscodeReason.VIDEO_BIT_DEPTH_NOT_SUPPORTED,
            "VideoProfile": TranscodeReason.VIDEO_PROFILE_NOT_SUPPORTED,
            "VideoRange": TranscodeReason.VIDEO_RANGE_NOT_SUPPORTED,
            "AudioChannels": TranscodeReason.AUDIO_CHANNELS_NOT_SUPPORTED,
            "AudioSampleRate": TranscodeReason.AUDIO_SAMPLE_RATE_NOT_SUPPORTED,
            "AudioBitrate": TranscodeReason.AUDIO_BITRATE_NOT_SUPPORTED,
        }

        return reason_map.get(property_name)

    def _is_container_supported(self, container: str, media_type: str) -> bool:
        """Check if container is supported for the given media type."""

        logger.debug(f"Checking container support for: {container} (type: {media_type})")
        logger.debug(f"Available direct play profiles: {[(p.Type, p.Container) for p in self.direct_play_profiles]}")

        for profile in self.direct_play_profiles:
            if profile.Type == media_type or media_type == "Video":
                # Split containers and normalize
                supported_containers = [c.strip().lower() for c in profile.Container.split(",")]
                logger.debug(f"Profile {profile.Type} supports containers: {supported_containers}")

                if container.lower() in supported_containers:
                    logger.debug(f"Container {container} is supported via profile: {profile.Container}")
                    return True

        logger.debug(f"Container {container} is NOT supported")
        return False

    def _build_media_streams(self, media_file: MediaFile) -> list[dict]:
        """Build media stream info for the response."""

        streams = []

        # Add video streams
        for i, video_track in enumerate(media_file.video_tracks):
            stream = {
                "Index": i,
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
            # Remove None values
            streams.append({k: v for k, v in stream.items() if v is not None})

        # Add audio streams
        for i, audio_track in enumerate(media_file.audio_tracks):
            stream = {
                "Index": len(media_file.video_tracks) + i,
                "Type": "Audio",
                "Codec": audio_track.codec,
                "Channels": audio_track.channels,
                "SampleRate": audio_track.sample_rate,
                "BitRate": audio_track.bitrate,
                "IsDefault": audio_track.is_default,
                "Language": audio_track.language,
                "Title": audio_track.title,
            }
            streams.append({k: v for k, v in stream.items() if v is not None})

        # Add subtitle streams
        for i, subtitle_track in enumerate(media_file.subtitle_tracks):
            stream = {
                "Index": len(media_file.video_tracks) + len(media_file.audio_tracks) + i,
                "Type": "Subtitle",
                "Codec": subtitle_track.codec,
                "IsDefault": subtitle_track.is_default,
                "IsForced": subtitle_track.is_forced,
                "Language": subtitle_track.language,
                "Title": subtitle_track.title,
            }
            streams.append({k: v for k, v in stream.items() if v is not None})

        return streams

    def _calculate_available_resolutions(self, media_file: MediaFile) -> list[dict]:
        """Calculate available resolution options for manual selection."""
        available_resolutions = []

        # Get original resolution from first video track
        if not media_file.video_tracks:
            return available_resolutions

        video_track = media_file.video_tracks[0]
        original_width = video_track.width or 1920
        original_height = video_track.height or 1080

        # Add original resolution
        available_resolutions.append({
            "width": original_width,
            "height": original_height,
            "label": f"{original_width}x{original_height} (Original)",
            "is_original": True,
        })

        # Common transcode targets (snap to standard resolutions)
        standard_resolutions = [
            {"width": 3840, "height": 2160, "label": "4K (3840x2160)"},
            {"width": 2560, "height": 1440, "label": "1440p (2560x1440)"},
            {"width": 1920, "height": 1080, "label": "1080p (1920x1080)"},
            {"width": 1280, "height": 720, "label": "720p (1280x720)"},
            {"width": 854, "height": 480, "label": "480p (854x480)"},
            {"width": 640, "height": 360, "label": "360p (640x360)"},
        ]

        # Only include resolutions smaller than original
        for resolution in standard_resolutions:
            if resolution["width"] < original_width or (
                resolution["width"] == original_width and resolution["height"] < original_height
            ):
                available_resolutions.append({
                    "width": resolution["width"],
                    "height": resolution["height"],
                    "label": resolution["label"],
                    "is_original": False,
                })

        return available_resolutions


class PlaybackResult:
    """Result of playback capability check."""

    def __init__(self, can_play: bool, reasons: list[TranscodeReason]):
        self.can_play = can_play
        self.reasons = reasons
