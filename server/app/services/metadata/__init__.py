"""Editorial metadata API. Every automatic write goes through the same lock-aware merge."""

from .editor import (
    apply_metadata_patch,
    identify_metadata,
    refresh_metadata,
    restore_metadata_fields,
    save_manual_artwork,
)
from .engine import export_metadata_nfo, process_metadata_jobs, search_metadata
from .files import artwork_path, export_nfo, metadata_directory, read_nfo, store_artwork
from .queue import enqueue_metadata, queue_nfo_export
from .types import IdentificationRequired, MetadataConflict, ProviderUnavailable

__all__ = [
    "IdentificationRequired",
    "MetadataConflict",
    "ProviderUnavailable",
    "apply_metadata_patch",
    "artwork_path",
    "enqueue_metadata",
    "export_metadata_nfo",
    "export_nfo",
    "identify_metadata",
    "metadata_directory",
    "process_metadata_jobs",
    "queue_nfo_export",
    "read_nfo",
    "refresh_metadata",
    "restore_metadata_fields",
    "save_manual_artwork",
    "search_metadata",
    "store_artwork",
]
