"""Local NFO interchange and validated, atomically written artwork."""

import hashlib
import io
import json
import os
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from PIL import Image

from .types import LOCKABLE_FIELDS, MetadataProposal, parse_date

_NFO_FIELDS = {
    "title": "title",
    "originaltitle": "original_title",
    "sorttitle": "sort_title",
    "plot": "overview",
    "tagline": "tagline",
    "premiered": "release_date",
    "aired": "release_date",
    "season": "season_number",
    "episode": "episode_number",
    "originallanguage": "original_language",
}
_NFO_LISTS = {"genre": "genres", "tag": "keywords", "studio": "studios", "country": "countries"}
_LOCK_NAMES = {
    "name": "title",
    "overview": "overview",
    "cast": "credits",
    "genres": "genres",
    "studios": "studios",
    "tags": "keywords",
    "productionlocations": "countries",
}
_LOCK_EXPORT = {
    "title": "Name",
    "overview": "Overview",
    "credits": "Cast",
    "genres": "Genres",
    "studios": "Studios",
    "keywords": "Tags",
    "countries": "ProductionLocations",
}


def _read_credits(root: ET.Element) -> list[dict[str, str]]:
    credits = [
        {"name": node.findtext("name") or "", "role": node.findtext("role") or "", "department": "Acting"}
        for node in root.findall("actor")
        if node.findtext("name")
    ]
    for tag, role in (("director", "Director"), ("writer", "Writer")):
        credits.extend(
            {"name": node.text or "", "role": role, "department": role} for node in root.findall(tag) if node.text
        )
    return credits


def parse_xml(text: str, maximum: int = 8_000_000) -> ET.Element:
    if len(text) > maximum or "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise ValueError("Unsupported or oversized metadata XML")
    return ET.fromstring(text)


def _nfo_signature(root: ET.Element) -> str:
    def node_value(node: ET.Element) -> tuple:
        return (
            node.tag,
            sorted(node.attrib.items()),
            (node.text or "").strip(),
            [node_value(child) for child in node if child.tag != "ferelix"],
        )

    return hashlib.sha256(json.dumps(node_value(root), ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def read_nfo(path: Path, kind: str, locale: str) -> MetadataProposal:  # ruff: ignore[complex-structure]
    """Read supported editorial fields without trusting external entities or NFO paths."""
    if path.stat().st_size > 8_000_000:
        raise ValueError("NFO is too large")
    root = parse_xml(path.read_text(encoding="utf-8-sig"))
    result = MetadataProposal(kind)
    marker = root.find("ferelix")
    result.internal_export = marker is not None and marker.get("content_hash") == _nfo_signature(root)
    ids: dict[str, str] = {}
    for node in root:
        text = (node.text or "").strip()
        target = _NFO_FIELDS.get(node.tag)
        if target:
            value: Any = text
            if target == "release_date":
                value = parse_date(text)
            elif target in {"season_number", "episode_number"}:
                if not text.isdecimal():
                    continue
                value = int(text)
            result.fields[target] = value
        elif node.tag in _NFO_LISTS:
            result.fields.setdefault(_NFO_LISTS[node.tag], []).append(text if node.tag == "country" else {"name": text})
        elif node.tag == "uniqueid" and node.get("type") in {"tmdb", "imdb", "tvdb", "anidb"}:
            ids[str(node.get("type"))] = text
        elif node.tag in {"tmdbid", "imdbid", "tvdbid", "anidbid"}:
            ids[node.tag[:-2]] = text
        elif node.tag == "lockdata":
            result.locked = text.lower() == "true"
        elif node.tag == "lockedfields":
            result.locked_fields = [
                field for raw in text.split("|") if (field := _LOCK_NAMES.get(raw.lower(), raw)) in LOCKABLE_FIELDS
            ]
    if ids:
        result.fields["provider_ids"] = ids
    if credits := _read_credits(root):
        result.fields["credits"] = credits
    for name in result.fields:
        result.provenance[name] = {"source": "nfo", "locale": locale, "path": str(path)}
    for role, tag in (("poster", "thumb"), ("backdrop", "fanart/thumb")):
        value = root.findtext(tag)
        if value:
            # Remote URLs and paths are validated by the artwork layer, never dereferenced here.
            result.artwork[role] = value.strip()
    return result


def find_nfo(media_path: Path, kind: str) -> Path | None:
    candidates = [media_path.with_suffix(".nfo")]
    if kind == "movie":
        candidates.append(media_path.parent / "movie.nfo")
    elif kind == "series":
        candidates = [media_path / "tvshow.nfo"]
    return next((path for path in candidates if path.is_file()), None)


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=".ferelix-", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def export_nfo(item: Any, path: Path, artwork: dict[str, str] | None = None) -> None:
    """Export the effective values and locks; database remains the system of record."""
    tag = {"movie": "movie", "series": "tvshow", "season": "season", "episode": "episodedetails"}.get(item.kind)
    if not tag:
        raise ValueError("This metadata kind has no NFO export")
    root = ET.Element(tag)
    written: set[str] = set()
    for nfo_name, name in _NFO_FIELDS.items():
        value = getattr(item, name, None)
        if value is not None and name not in written:
            ET.SubElement(root, nfo_name).text = str(value)
            written.add(name)
    for nfo_name, name in _NFO_LISTS.items():
        for value in getattr(item, name, []) or []:
            ET.SubElement(root, nfo_name).text = str(value.get("name", "") if isinstance(value, dict) else value)
    for provider, identifier in sorted((item.provider_ids or {}).items()):
        ET.SubElement(root, "uniqueid", type=provider).text = str(identifier)
    for credit in getattr(item, "credits", []) or []:
        role = credit.get("role")
        if role in {"Director", "Writer"}:
            ET.SubElement(root, role.lower()).text = credit.get("name", "")
        else:
            actor = ET.SubElement(root, "actor")
            ET.SubElement(actor, "name").text = credit.get("name", "")
            ET.SubElement(actor, "role").text = role or ""
    ET.SubElement(root, "lockdata").text = str(bool(item.locked)).lower()
    ET.SubElement(root, "lockedfields").text = "|".join(
        str(_LOCK_EXPORT.get(name, name)) for name in sorted(item.locked_fields or [])
    )
    for role, location in (artwork or {}).items():
        if role == "poster":
            ET.SubElement(root, "thumb").text = location
        elif role == "backdrop":
            ET.SubElement(ET.SubElement(root, "fanart"), "thumb").text = location
    ET.SubElement(root, "ferelix", version="1", content_hash=_nfo_signature(root), revision=str(item.revision))
    ET.indent(root)
    atomic_write(path, ET.tostring(root, encoding="utf-8", xml_declaration=True))


def metadata_directory() -> Path:
    return Path(os.environ.get("FERELIX_METADATA_DIR", "./metadata")).resolve()


def artwork_path(path: str) -> Path:
    root = metadata_directory()
    candidate = (root / path).resolve()
    if not candidate.is_relative_to(root / "artwork"):
        raise ValueError("Artwork is outside metadata storage")
    return candidate


def store_artwork(payload: bytes) -> tuple[str, str]:
    if len(payload) > 20_000_000:
        raise ValueError("Artwork is too large")
    with Image.open(io.BytesIO(payload)) as picture:
        if picture.width * picture.height > 40_000_000 or picture.format not in {"JPEG", "PNG", "WEBP"}:
            raise ValueError("Unsupported artwork")
        picture.load()
        output = io.BytesIO()
        picture.convert("RGB").save(output, format="WEBP", quality=88)
    content = output.getvalue()
    digest = hashlib.sha256(content).hexdigest()
    relative = f"artwork/{digest[:2]}/{digest}.webp"
    path = artwork_path(relative)
    if not path.exists():
        atomic_write(path, content)
    return relative, digest
