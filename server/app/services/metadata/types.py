"""Provider-neutral metadata. Providers propose changes; only the merge service writes them."""

from dataclasses import dataclass, field
from datetime import date
from typing import Any


class MetadataConflict(ValueError):
    """An administrator or another job changed this item in the meantime."""


class ProviderUnavailable(RuntimeError):
    """A provider is unconfigured, temporarily unavailable, or refusing requests."""


class IdentificationRequired(ValueError):
    """The available evidence does not identify one work unambiguously."""


@dataclass
class MatchCandidate:
    provider: str
    provider_id: str
    kind: str
    title: str
    original_title: str = ""
    year: int | None = None
    overview: str = ""
    poster_url: str | None = None


@dataclass
class MetadataProposal:
    kind: str
    fields: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    children: list[MetadataProposal] = field(default_factory=list)
    artwork: dict[str, str] = field(default_factory=dict)
    locked_fields: list[str] = field(default_factory=list)
    locked: bool = False
    hierarchy_complete: bool = False
    order_confirmed: bool = False
    collection: MetadataProposal | None = None
    prepared_artwork: dict[str, tuple[str, str, str]] = field(default_factory=dict)
    absolute_placements: dict[int, tuple[int, int]] = field(default_factory=dict)
    artwork_errors: list[str] = field(default_factory=list)
    internal_export: bool = False


EDITABLE_FIELDS = frozenset({
    "title",
    "original_title",
    "sort_title",
    "overview",
    "tagline",
    "original_language",
    "release_date",
    "season_number",
    "episode_number",
    "aliases",
    "genres",
    "keywords",
    "credits",
    "studios",
    "countries",
    "provider_ids",
    "metadata_locale",
})
LOCKABLE_FIELDS = EDITABLE_FIELDS | {"poster", "backdrop", "order"}


def parse_date(value: Any) -> date | None:
    """Invalid or unknown provider dates remain unknown."""
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def positive_id(value: str) -> str:
    if not value.isascii() or not value.isdecimal() or int(value) <= 0:
        raise ValueError("A positive provider identifier is required")
    return str(int(value))
