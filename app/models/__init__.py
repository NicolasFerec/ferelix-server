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
from .user import User, UserCreate, UserSchema, UserUpdate

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
    "User",
    "UserCreate",
    "UserSchema",
    "UserUpdate",
    "VideoTrack",
    "VideoTrackSchema",
]
