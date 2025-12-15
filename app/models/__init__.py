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
    ClientCapabilities,
    CompatibilityCheckRequest,
    CompatibilityCheckResponse,
    StartTranscodingRequest,
    TranscodingFormat,
    TranscodingProfile,
    TranscodingProfileSchema,
    TranscodingProgressResponse,
    TranscodingSession,
    TranscodingSessionSchema,
    TranscodingStatus,
)
from .user import User, UserCreate, UserSchema, UserUpdate

__all__ = [
    "AudioTrack",
    "AudioTrackSchema",
    "Base",
    "ClientCapabilities",
    "CompatibilityCheckRequest",
    "CompatibilityCheckResponse",
    "Library",
    "LibraryCreate",
    "LibrarySchema",
    "LibraryUpdate",
    "MediaFile",
    "MediaFileSchema",
    "RecommendationRow",
    "RecommendationRowCreate",
    "RecommendationRowSchema",
    "RecommendationRowUpdate",
    "RefreshToken",
    "Settings",
    "SettingsSchema",
    "SettingsUpdate",
    "StartTranscodingRequest",
    "SubtitleTrack",
    "SubtitleTrackSchema",
    "TranscodingFormat",
    "TranscodingProfile",
    "TranscodingProfileSchema",
    "TranscodingProgressResponse",
    "TranscodingSession",
    "TranscodingSessionSchema",
    "TranscodingStatus",
    "User",
    "UserCreate",
    "UserSchema",
    "UserUpdate",
    "VideoTrack",
    "VideoTrackSchema",
]
