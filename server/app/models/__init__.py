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
    MediaCardSchema,
    MediaFile,
    MediaFileSchema,
    SubtitleTrack,
    SubtitleTrackSchema,
    VideoTrack,
    VideoTrackSchema,
)
from .media_view import MediaView, MediaViewSchema, MediaViewUpdate
from .metadata import Artwork, MediaItem, MediaItemFile, MetadataCache, MetadataJob, UserItemState
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
from .watchlist import WatchlistEntry, WatchlistState

__all__ = [
    "Artwork",
    "AudioTrack",
    "AudioTrackSchema",
    "Base",
    "Library",
    "LibraryCreate",
    "LibrarySchema",
    "LibraryUpdate",
    "MediaCardSchema",
    "MediaFile",
    "MediaFileSchema",
    "MediaItem",
    "MediaItemFile",
    "MediaView",
    "MediaViewSchema",
    "MediaViewUpdate",
    "MetadataCache",
    "MetadataJob",
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
    "UserItemState",
    "UserRole",
    "UserSchema",
    "UserUpdate",
    "VideoTrack",
    "VideoTrackSchema",
    "WatchlistEntry",
    "WatchlistState",
]
