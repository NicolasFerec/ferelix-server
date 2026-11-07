"""Stream builder service for making playback decisions."""

import logging
import math
from dataclasses import dataclass
from typing import Any

from app.models.media_file import AudioTrack, MediaFile, VideoTrack
from app.models.playback import (
    DeviceProfile,
    DeviceProfileCondition,
    PlayMethod,
    StreamInfo,
    TranscodeReason,
    TranscodeSettings,
)
from app.services.stream_info_helpers import build_media_streams, calculate_available_resolutions

logger = logging.getLogger(__name__)

HLS_TS_COPY_VIDEO_CODECS = {"h264"}
HLS_FMP4_COPY_VIDEO_CODECS = {"hevc", "h265", "av1", "vp9"}
HLS_TS_COPY_AUDIO_CODECS = {"aac", "mp3"}
HLS_FMP4_COPY_AUDIO_CODECS = {"aac", "mp3", "ac3", "eac3", "opus"}


def select_audio_track(media_file: MediaFile, stream_index: int | None = None) -> AudioTrack | None:
    """Resolve a requested/default track without mutating the ORM collection."""
    tracks = media_file.audio_tracks
    if stream_index is not None:
        selected = next((track for track in tracks if track.stream_index == stream_index), None)
        if selected is None:
            raise ValueError(f"Audio stream index {stream_index} does not exist")
        return selected
    return next((track for track in tracks if track.is_default), tracks[0] if tracks else None)


def select_video_track(media_file: MediaFile, stream_index: int | None = None) -> VideoTrack | None:
    tracks = media_file.video_tracks
    if stream_index is not None:
        selected = next((track for track in tracks if track.stream_index == stream_index), None)
        if selected is None:
            raise ValueError(f"Video stream index {stream_index} does not exist")
        return selected
    return next((track for track in tracks if track.is_default), tracks[0] if tracks else None)


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
        audio_stream_index: int | None = None,
        video_stream_index: int | None = None,
        allow_video_stream_copy: bool = True,
        allow_audio_stream_copy: bool = True,
    ) -> StreamInfo:
        """Choose only methods allowed by the request and advertised by the device."""
        audio_track = select_audio_track(media_file, audio_stream_index)
        video_track = select_video_track(media_file, video_stream_index)
        stream_info = self._base_stream_info(media_file)
        stream_info.AudioStreamIndex = audio_track.stream_index if audio_track is not None else None
        stream_info.VideoStreamIndex = video_track.stream_index if video_track is not None else None
        stream_info.AvailableResolutions = calculate_available_resolutions(media_file, video_track)
        if requested_resolution:
            if enable_transcoding and self._supports_h264_aac_output():
                return self._apply_resolution_override(stream_info, media_file, requested_resolution)
            return self._unavailable(stream_info)

        native_tracks = video_track is select_video_track(media_file) and audio_track is select_audio_track(media_file)
        if enable_direct_play and allow_video_stream_copy and allow_audio_stream_copy and native_tracks:
            result = self._check_direct_play(media_file, audio_track, video_track)
            if result.can_play:
                self._apply_direct_play(stream_info, media_file, result.reasons)
                return stream_info
            stream_info.TranscodeReasons.extend(result.reasons)

        if enable_direct_stream and allow_video_stream_copy and allow_audio_stream_copy:
            result = self._check_direct_stream(media_file, audio_track, video_track)
            if result.can_play:
                self._apply_direct_stream(stream_info, media_file, video_track)
                return stream_info
            stream_info.TranscodeReasons.extend(result.reasons)

        if enable_transcoding and self._supports_h264_aac_output():
            if allow_video_stream_copy:
                video_ok, audio_ok = self._needs_audio_transcode(media_file, audio_track, video_track)
                if video_ok and (not audio_ok or not allow_audio_stream_copy):
                    self._apply_audio_transcode(stream_info, media_file, video_track)
                    return stream_info
            self._apply_full_transcode(stream_info, media_file)
            return stream_info
        return self._unavailable(stream_info)

    def _supports_h264_aac_output(self) -> bool:
        profiles = self.device_profile.TranscodingProfiles or self.direct_play_profiles
        return any(
            profile.Type in {"Video", "VideoAudio"}
            and self._codec_name("h264") in self._codec_list(profile.VideoCodec)
            and "aac" in self._codec_list(profile.AudioCodec)
            and bool({"mp4", "ts", "mpegts", "fmp4"} & set(self._codec_list(profile.Container)))
            and getattr(profile, "Protocol", "hls").lower() == "hls"
            for profile in profiles
        )

    def _unavailable(self, stream_info: StreamInfo) -> StreamInfo:
        stream_info.PlayMethod = PlayMethod.NONE
        stream_info.DirectStreamUrl = None
        stream_info.TranscodingUrl = None
        stream_info.TranscodingType = None
        stream_info.TranscodeReasons.append(TranscodeReason.DIRECT_PLAY_ERROR)
        return stream_info

    def _codec_list(self, codecs: str | None) -> list[str]:
        return [part.strip().lower() for part in (codecs or "").split(",") if part.strip()]

    def _base_stream_info(self, media_file: MediaFile) -> StreamInfo:
        stream_info = StreamInfo(
            Id=str(media_file.id),
            Path=media_file.file_path,
            Container=media_file.file_extension.lstrip(".") if media_file.file_extension else "unknown",
            PlayMethod=PlayMethod.DIRECT_PLAY,
            VideoType="VideoFile",
            RunTimeTicks=int(media_file.duration * 10_000_000) if media_file.duration else None,
            Bitrate=media_file.bitrate,
            MediaStreams=build_media_streams(media_file),
        )
        stream_info.AvailableResolutions = calculate_available_resolutions(media_file)
        return stream_info

    def _apply_direct_play(
        self,
        stream_info: StreamInfo,
        media_file: MediaFile,
        reasons: list[TranscodeReason],
    ) -> None:
        stream_info.PlayMethod = PlayMethod.DIRECT_PLAY
        stream_info.DirectStreamUrl = f"/api/v1/stream/{media_file.id}"
        stream_info.TranscodeReasons = reasons

    def _apply_resolution_override(
        self,
        stream_info: StreamInfo,
        media_file: MediaFile,
        requested_resolution: dict,
    ) -> StreamInfo:
        self._apply_full_transcode(stream_info, media_file)
        settings = stream_info.TranscodeSettings or TranscodeSettings(VideoCodec="h264", AudioCodec="aac")
        for key, attribute in (("width", "MaxWidth"), ("height", "MaxHeight")):
            requested = requested_resolution.get(key)
            if requested is not None:
                if not isinstance(requested, int) or isinstance(requested, bool) or not 2 <= requested <= 8192:
                    raise ValueError(f"Requested {key} must be an integer between 2 and 8192")
                previous = getattr(settings, attribute)
                setattr(settings, attribute, min(previous, requested) if previous else requested)
        stream_info.TranscodeSettings = settings
        logger.debug(f"Forced transcode for resolution {requested_resolution}")
        return stream_info

    def _apply_direct_stream(
        self, stream_info: StreamInfo, media_file: MediaFile, video_track: VideoTrack | None
    ) -> None:
        stream_info.PlayMethod = PlayMethod.DIRECT_STREAM
        stream_info.TranscodingUrl = f"/api/v1/hls/{media_file.id}/remux"
        stream_info.TranscodingContainer = self._hls_copy_container(video_track)
        stream_info.TranscodingType = "remux"
        stream_info.IsRemuxOnly = True
        stream_info.TranscodeSettings = TranscodeSettings(VideoCodec="copy", AudioCodec="copy", IsRemuxOnly=True)

    def _apply_audio_transcode(
        self, stream_info: StreamInfo, media_file: MediaFile, video_track: VideoTrack | None
    ) -> None:
        stream_info.PlayMethod = PlayMethod.TRANSCODE
        stream_info.TranscodingUrl = f"/api/v1/hls/{media_file.id}/audio-transcode"
        stream_info.TranscodingContainer = self._hls_copy_container(video_track)
        stream_info.TranscodingVideoCodec = "copy"
        stream_info.TranscodingAudioCodec = "aac"
        stream_info.TranscodingType = "audio-only"
        stream_info.TranscodeReasons.append(TranscodeReason.AUDIO_TRANSCODE_REQUIRED)
        stream_info.TranscodeSettings = TranscodeSettings(
            VideoCodec="copy",
            AudioCodec="aac",
            AudioBitrate=128000,
            IsRemuxOnly=False,
        )

    def _apply_full_transcode(self, stream_info: StreamInfo, media_file: MediaFile) -> None:
        stream_info.PlayMethod = PlayMethod.TRANSCODE
        stream_info.TranscodingUrl = f"/api/v1/hls/{media_file.id}/start"
        stream_info.TranscodingContainer = "mp4"
        stream_info.TranscodingVideoCodec = "h264"
        stream_info.TranscodingAudioCodec = "aac"
        stream_info.TranscodingType = "full"
        caps: dict[str, float] = {}
        names = {
            "Width": "MaxWidth",
            "Height": "MaxHeight",
            "VideoBitrate": "VideoBitrate",
            "VideoFramerate": "MaxFrameRate",
            "Framerate": "MaxFrameRate",
        }
        for profile in self.codec_profiles:
            if profile.Type not in {"Video", "VideoAudio"} or "h264" not in self._codec_list(profile.Codec):
                continue
            for condition in profile.Conditions:
                key = names.get(condition.Property)
                if key and condition.IsRequired and condition.Condition == "LessThanEqual":
                    try:
                        value = float(condition.Value)
                    except ValueError:
                        continue
                    if value > 0 and math.isfinite(value):
                        caps[key] = min(caps.get(key, value), value)
        stream_info.TranscodeSettings = TranscodeSettings(
            VideoCodec="h264",
            AudioCodec="aac",
            MaxWidth=int(caps["MaxWidth"]) if "MaxWidth" in caps else None,
            MaxHeight=int(caps["MaxHeight"]) if "MaxHeight" in caps else None,
            VideoBitrate=int(caps["VideoBitrate"]) if "VideoBitrate" in caps else None,
            MaxFrameRate=caps.get("MaxFrameRate"),
        )

    def _check_direct_play(
        self, media_file: MediaFile, audio_track: AudioTrack | None, video_track: VideoTrack | None
    ) -> PlaybackResult:
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
        if video_track is not None:
            logger.debug(
                f"Checking video codec: {video_track.codec}, resolution: {video_track.width}x{video_track.height}, bit_depth: {video_track.bit_depth}"
            )
            video_codec_result = self._check_video_codec_support(video_track, target_container=container)
            if not video_codec_result.can_play:
                reasons.extend(video_codec_result.reasons)
                logger.debug(f"Video codec check failed, reasons: {video_codec_result.reasons}")
                return PlaybackResult(False, reasons)

        # Check audio codec support
        if audio_track is not None:
            logger.debug(f"Checking audio codec: {audio_track.codec}")
            audio_codec_result = self._check_audio_codec_support(audio_track, target_container=container)
            if not audio_codec_result.can_play:
                reasons.extend(audio_codec_result.reasons)
                logger.debug(f"Audio codec check failed, reasons: {audio_codec_result.reasons}")
                return PlaybackResult(False, reasons)

        logger.debug("Direct play check passed!")
        return PlaybackResult(True, reasons)

    def _check_direct_stream(
        self, media_file: MediaFile, audio_track: AudioTrack | None, video_track: VideoTrack | None
    ) -> PlaybackResult:
        """Check if media can be remuxed to HLS with stream copy."""

        reasons = []

        if video_track is not None:
            video_codec_result = self._check_video_codec_support(video_track, target_container="mp4", remux=True)
            if not video_codec_result.can_play:
                reasons.extend(video_codec_result.reasons)
                return PlaybackResult(False, reasons)
            if not self._can_copy_video_to_hls(video_track):
                return PlaybackResult(False, [TranscodeReason.VIDEO_CODEC_NOT_SUPPORTED])

        if audio_track is not None:
            audio_codec_result = self._check_audio_codec_support(audio_track, target_container="mp4")
            if not audio_codec_result.can_play:
                reasons.extend(audio_codec_result.reasons)
                return PlaybackResult(False, reasons)
            if not self._can_copy_audio_to_hls(audio_track, video_track):
                return PlaybackResult(False, [TranscodeReason.AUDIO_CODEC_NOT_SUPPORTED])

        return PlaybackResult(True, reasons)

    def _needs_audio_transcode(
        self, media_file: MediaFile, audio_track: AudioTrack | None, video_track: VideoTrack | None
    ) -> tuple[bool, bool]:
        """Return (video_ok, audio_ok) for HLS with copied video."""
        video_ok = True
        audio_ok = True
        if video_track is not None:
            video_res = self._check_video_codec_support(video_track, target_container="mp4", remux=True)
            video_ok = video_res.can_play and self._can_copy_video_to_hls(video_track)
        if audio_track is not None:
            audio_res = self._check_audio_codec_support(audio_track, target_container="mp4")
            audio_ok = audio_res.can_play and self._can_copy_audio_to_hls(audio_track, video_track)
        return video_ok, audio_ok

    def _check_video_codec_support(
        self, video_track: Any, target_container: str | None = None, remux: bool = False
    ) -> PlaybackResult:
        """Check if a video codec is supported by the client."""

        reasons = []
        codec = self._codec_name(video_track.codec)

        if not codec:
            reasons.append(TranscodeReason.UNKNOWN_VIDEO_STREAM_INFO)
            return PlaybackResult(False, reasons)

        # Check if codec is in any DirectPlayProfile
        container = target_container or "mp4"  # Default to mp4 for compatibility check
        codec_supported = False

        for profile in self.direct_play_profiles:
            if (
                profile.Type in {"Video", "VideoAudio"}
                and profile.VideoCodec
                and container.lower() in self._codec_list(profile.Container)
                and codec in self._codec_list(profile.VideoCodec)
            ):
                codec_supported = True
                break

        if not codec_supported:
            reasons.append(TranscodeReason.VIDEO_CODEC_NOT_SUPPORTED)
            return PlaybackResult(False, reasons)

        # Check codec profile constraints
        overrides = {"VideoCodecTag": "hvc1"} if remux and codec in {"hevc", "h265"} else {}
        constraint_result = self._check_codec_constraints(video_track, codec, "Video", overrides)
        if not constraint_result.can_play:
            reasons.extend(constraint_result.reasons)
            return PlaybackResult(False, reasons)

        return PlaybackResult(True, reasons)

    def _check_audio_codec_support(self, audio_track: Any, target_container: str | None = None) -> PlaybackResult:
        """Check if an audio codec is supported by the client."""

        reasons = []
        codec = self._codec_name(audio_track.codec)

        if not codec:
            reasons.append(TranscodeReason.UNKNOWN_AUDIO_STREAM_INFO)
            return PlaybackResult(False, reasons)

        # Check if codec is in any DirectPlayProfile
        container = target_container or "mp4"
        codec_supported = False

        for profile in self.direct_play_profiles:
            if (
                profile.AudioCodec
                and codec in self._codec_list(profile.AudioCodec)
                and profile.Type in {"Video", "VideoAudio"}
                and container.lower() in self._codec_list(profile.Container)
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

    def _check_codec_constraints(
        self, track: Any, codec: str, track_type: str, overrides: dict | None = None
    ) -> PlaybackResult:
        """Check codec profile constraints (level, bitrate, resolution, etc.)."""

        reasons = []

        # Find matching codec profiles
        matching_profiles = [
            p
            for p in self.codec_profiles
            if p.Type in {track_type, "VideoAudio"} and codec in self._codec_list(p.Codec)
        ]

        for profile in matching_profiles:
            for condition in profile.Conditions:
                constraint_failed = self._evaluate_condition(track, condition, overrides)
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

    def _evaluate_condition(self, track: Any, condition: DeviceProfileCondition, overrides: dict | None = None) -> bool:
        """Evaluate if a codec profile condition fails."""

        property_name = condition.Property
        condition_type = condition.Condition
        expected_value = condition.Value

        # Get actual value from track
        actual_value = (overrides or {}).get(property_name, self._get_track_property_value(track, property_name))
        if actual_value is None:
            return condition.IsRequired

        try:
            if condition_type == "LessThanEqual":
                return float(actual_value) > float(expected_value)
            if condition_type == "Equals":
                return str(actual_value).casefold() != expected_value.casefold()
            if condition_type == "EqualsAny":
                allowed_values = expected_value.split("|")
                return str(actual_value).casefold() not in [value.casefold() for value in allowed_values]
            if condition_type == "GreaterThanEqual":
                return float(actual_value) < float(expected_value)
        except ValueError, TypeError:
            return condition.IsRequired

        return condition.IsRequired

    def _get_track_property_value(self, track: Any, property_name: str) -> Any:
        """Get property value from a media track."""
        if property_name == "VideoRange":
            return self._get_video_range(track)
        if property_name == "VideoRangeType":
            transfer = (getattr(track, "color_transfer", None) or "").lower()
            if transfer in {"arib-std-b67", "hlg"}:
                return "HLG"
            if transfer == "smpte2084":
                return "HDR10"
            return "UnknownHDR" if self._get_video_range(track) == "HDR" else "SDR"

        attribute_by_property = {
            # Video properties
            "VideoLevel": "level",
            "VideoFramerate": "fps",
            "Framerate": "fps",
            "VideoCodecTag": "codec_tag",
            "Width": "width",
            "Height": "height",
            "VideoBitrate": "bitrate",
            "VideoBitDepth": "bit_depth",
            "VideoProfile": "profile",
            # Audio properties
            "AudioChannels": "channels",
            "AudioSampleRate": "sample_rate",
            "AudioBitrate": "bitrate",
        }

        attribute_name = attribute_by_property.get(property_name)
        if not attribute_name:
            return None

        return getattr(track, attribute_name, None)

    def _get_video_range(self, track: Any) -> str:
        """Determine if track is HDR or SDR based on color metadata."""
        color_space = (getattr(track, "color_space", None) or "").lower()
        color_primaries = (getattr(track, "color_primaries", None) or "").lower()
        transfer_characteristics = (getattr(track, "color_transfer", None) or "").lower()

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
            "VideoFramerate": TranscodeReason.VIDEO_FRAMERATE_NOT_SUPPORTED,
            "Framerate": TranscodeReason.VIDEO_FRAMERATE_NOT_SUPPORTED,
            "VideoCodecTag": TranscodeReason.VIDEO_CODEC_NOT_SUPPORTED,
            "Width": TranscodeReason.VIDEO_RESOLUTION_NOT_SUPPORTED,
            "Height": TranscodeReason.VIDEO_RESOLUTION_NOT_SUPPORTED,
            "VideoBitrate": TranscodeReason.VIDEO_BITRATE_NOT_SUPPORTED,
            "VideoBitDepth": TranscodeReason.VIDEO_BIT_DEPTH_NOT_SUPPORTED,
            "VideoProfile": TranscodeReason.VIDEO_PROFILE_NOT_SUPPORTED,
            "VideoRange": TranscodeReason.VIDEO_RANGE_NOT_SUPPORTED,
            "VideoRangeType": TranscodeReason.VIDEO_RANGE_NOT_SUPPORTED,
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
            if profile.Type in {media_type, "VideoAudio"}:
                # Split containers and normalize
                supported_containers = [c.strip().lower() for c in profile.Container.split(",")]
                logger.debug(f"Profile {profile.Type} supports containers: {supported_containers}")

                if container.lower() in supported_containers:
                    logger.debug(f"Container {container} is supported via profile: {profile.Container}")
                    return True

        logger.debug(f"Container {container} is NOT supported")
        return False

    def _codec_name(self, codec: str | None) -> str:
        return (codec or "").strip().lower()

    def _hls_copy_container(self, video_track: VideoTrack | None) -> str:
        video_codec = self._codec_name(video_track.codec) if video_track is not None else ""
        return "fmp4" if video_codec in HLS_FMP4_COPY_VIDEO_CODECS else "ts"

    def _can_copy_video_to_hls(self, video_track: Any) -> bool:
        codec = self._codec_name(video_track.codec)
        return codec in HLS_TS_COPY_VIDEO_CODECS or codec in HLS_FMP4_COPY_VIDEO_CODECS

    def _can_copy_audio_to_hls(self, audio_track: Any, video_track: VideoTrack | None) -> bool:
        codec = self._codec_name(audio_track.codec)
        if self._hls_copy_container(video_track) == "fmp4":
            return codec in HLS_FMP4_COPY_AUDIO_CODECS
        return codec in HLS_TS_COPY_AUDIO_CODECS


@dataclass(slots=True)
class PlaybackResult:
    """Result of playback capability check."""

    can_play: bool
    reasons: list[TranscodeReason]
