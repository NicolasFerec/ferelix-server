"""Playback models and schemas for transcoding decisions."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict


class PlayMethod(StrEnum):
    """Playback methods supported by the client."""

    DIRECT_PLAY = "DirectPlay"  # Native playback, no server processing
    DIRECT_STREAM = "DirectStream"  # Remux only (container change, no re-encoding)
    TRANSCODE = "Transcode"  # Full transcoding


class TranscodeReason(StrEnum):
    """Reasons why transcoding may be required."""

    # Container and codec support
    CONTAINER_NOT_SUPPORTED = "ContainerNotSupported"
    VIDEO_CODEC_NOT_SUPPORTED = "VideoCodecNotSupported"
    AUDIO_CODEC_NOT_SUPPORTED = "AudioCodecNotSupported"
    SUBTITLE_CODEC_NOT_SUPPORTED = "SubtitleCodecNotSupported"

    # Video constraints
    VIDEO_PROFILE_NOT_SUPPORTED = "VideoProfileNotSupported"
    VIDEO_LEVEL_NOT_SUPPORTED = "VideoLevelNotSupported"
    VIDEO_RESOLUTION_NOT_SUPPORTED = "VideoResolutionNotSupported"
    VIDEO_BIT_DEPTH_NOT_SUPPORTED = "VideoBitDepthNotSupported"
    VIDEO_FRAMERATE_NOT_SUPPORTED = "VideoFramerateNotSupported"
    VIDEO_BITRATE_NOT_SUPPORTED = "VideoBitrateNotSupported"
    VIDEO_RANGE_NOT_SUPPORTED = "VideoRangeNotSupported"  # HDR/SDR

    # Audio constraints
    AUDIO_CHANNELS_NOT_SUPPORTED = "AudioChannelsNotSupported"
    AUDIO_SAMPLE_RATE_NOT_SUPPORTED = "AudioSampleRateNotSupported"
    AUDIO_BITRATE_NOT_SUPPORTED = "AudioBitrateNotSupported"

    # Audio-related reasons
    VIDEO_DISABLED = "VideoDisabled"
    AUDIO_TRANSCODE_REQUIRED = "AudioTranscodeRequired"

    # Other reasons
    DIRECT_PLAY_ERROR = "DirectPlayError"
    UNKNOWN_VIDEO_STREAM_INFO = "UnknownVideoStreamInfo"
    UNKNOWN_AUDIO_STREAM_INFO = "UnknownAudioStreamInfo"


class DeviceProfileCondition(BaseModel):
    """Condition used in codec profiles to define constraints."""

    Condition: str  # "LessThanEqual", "EqualsAny", "Equals", etc.
    Property: str  # "VideoLevel", "Width", "VideoBitrate", etc.
    Value: str
    IsRequired: bool = False


class DirectPlayProfile(BaseModel):
    """Profile defining formats the client can play natively."""

    Type: str  # "Video" or "Audio"
    Container: str  # "mp4", "webm", etc.
    VideoCodec: str | None = None  # "h264,hevc"
    AudioCodec: str | None = None  # "aac,mp3"


class CodecProfile(BaseModel):
    """Profile defining codec constraints and limitations."""

    Type: str  # "Video" or "Audio"
    Codec: str  # "h264", "hevc", etc.
    Conditions: list[DeviceProfileCondition] = []


class TranscodingProfile(BaseModel):
    """Profile defining fallback transcoding configurations."""

    Type: str  # "Video" or "Audio"
    Container: str
    VideoCodec: str | None = None
    AudioCodec: str | None = None
    Protocol: str = "hls"
    EstimateContentLength: bool = False
    EnableMpegtsM2TsMode: bool = False
    TranscodeSeekInfo: str = "Auto"
    CopyTimestamps: bool = False
    Context: str = "Streaming"
    EnableSubtitlesInManifest: bool = False
    MaxAudioChannels: str = "8"


class SubtitleProfile(BaseModel):
    """Profile defining subtitle format support."""

    Format: str  # "vtt", "srt", etc.
    Method: str  # "External", "Embed", "Encode"


class DeviceProfile(BaseModel):
    """Complete device profile describing client capabilities."""

    Name: str
    Id: str
    Identification: dict[str, Any] | None = None
    DirectPlayProfiles: list[DirectPlayProfile] = []
    CodecProfiles: list[CodecProfile] = []
    TranscodingProfiles: list[TranscodingProfile] = []
    SubtitleProfiles: list[SubtitleProfile] = []

    # Optional debug information
    _DebugInfo: dict[str, Any] | None = None


class PlaybackInfoRequest(BaseModel):
    """Request for playback information."""

    model_config = ConfigDict(from_attributes=True)

    DeviceProfile: DeviceProfile
    EnableDirectPlay: bool = True
    EnableDirectStream: bool = True
    EnableTranscoding: bool = True
    AllowVideoStreamCopy: bool = True
    AllowAudioStreamCopy: bool = True
    IsPlayback: bool = True


class TranscodeSettings(BaseModel):
    """Settings for transcoding operations."""

    VideoCodec: str | None = None  # "h264", "hevc", "copy"
    AudioCodec: str | None = None  # "aac", "mp3", "copy"
    VideoBitrate: int | None = None
    AudioBitrate: int | None = None
    MaxWidth: int | None = None
    MaxHeight: int | None = None
    IsRemuxOnly: bool = False  # True for container conversion only


class StreamInfo(BaseModel):
    """Information about how a media file should be streamed."""

    model_config = ConfigDict(from_attributes=True)

    # Media source info
    Id: str  # Media file ID
    Path: str | None = None
    Protocol: str = "File"

    # Playback method decision
    PlayMethod: PlayMethod
    TranscodeReasons: list[TranscodeReason] = []
    IsRemuxOnly: bool = (
        False  # True if only container conversion needed (fast DirectStream)
    )

    # Stream URLs
    DirectStreamUrl: str | None = None
    TranscodingUrl: str | None = None

    # Container and codec info
    Container: str | None = None
    VideoType: str | None = None  # "VideoFile"

    # Media stream info
    MediaStreams: list[dict] = []  # Video, audio, subtitle stream info

    # Transcoding settings (when applicable)
    TranscodingContainer: str | None = None
    TranscodingVideoCodec: str | None = None
    TranscodingAudioCodec: str | None = None
    TranscodeSettings: Any = None

    # Runtime info
    RunTimeTicks: int | None = None  # Duration in 100-nanosecond ticks
    Bitrate: int | None = None

    # Playback constraints
    RequiredHttpHeaders: dict[str, str] = {}


class PlaybackInfoResponse(BaseModel):
    """Response containing playback information and media sources."""

    model_config = ConfigDict(from_attributes=True)

    MediaSources: list[StreamInfo]
    PlaySessionId: str | None = None
    ErrorCode: str | None = None
