"""Database models for the media server."""

from .base import Base
from .library import (
    Library,
    LibraryCreate,
    LibrarySchema,
    LibraryUpdate,
)
from .media_file import (
    AudioTrack,
    AudioTrackSchema,
    MediaFile,
    MediaFileSchema,
    SubtitleTrack,
    SubtitleTrackSchema,
    VideoTrack,
    VideoTrackSchema,
)
from .media_view import MediaView, MediaViewSchema, MediaViewUpdate
from .playback_session import (
    PlaybackSession,
    PlaybackSessionCreate,
    PlaybackSessionHeartbeat,
    PlaybackSessionHeartbeatResponse,
    PlaybackSessionSchema,
    PlaybackSessionStatus,
)
from .recommendation_row import (
    RecommendationRow,
    RecommendationRowCreate,
    RecommendationRowSchema,
    RecommendationRowUpdate,
)
from .refresh_token import RefreshToken
from .settings import (
    Settings,
    SettingsSchema,
    SettingsUpdate,
)
from .transcoding import (
    TranscodingJob,
    TranscodingJobSchema,
    TranscodingProgressUpdate,
)
from .user import User, UserCreate, UserRole, UserSchema, UserUpdate

__all__ = [
    "AudioTrack",
    "AudioTrackSchema",
    "Base",
    "Library",
    "LibraryCreate",
    "LibrarySchema",
    "LibraryUpdate",
    "MediaFile",
    "MediaFileSchema",
    "MediaView",
    "MediaViewSchema",
    "MediaViewUpdate",
    "PlaybackSession",
    "PlaybackSessionCreate",
    "PlaybackSessionHeartbeat",
    "PlaybackSessionHeartbeatResponse",
    "PlaybackSessionSchema",
    "PlaybackSessionStatus",
    "RecommendationRow",
    "RecommendationRowCreate",
    "RecommendationRowSchema",
    "RecommendationRowUpdate",
    "RefreshToken",
    "Settings",
    "SettingsSchema",
    "SettingsUpdate",
    "SubtitleTrack",
    "SubtitleTrackSchema",
    "TranscodingJob",
    "TranscodingJobSchema",
    "TranscodingProgressUpdate",
    "User",
    "UserCreate",
    "UserRole",
    "UserSchema",
    "UserUpdate",
    "VideoTrack",
    "VideoTrackSchema",
]
