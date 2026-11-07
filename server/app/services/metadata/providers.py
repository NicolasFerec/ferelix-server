"""TMDB and AniDB adapters. Provider identity and episode mapping are never guessed."""

import asyncio
import gzip
import io
import os
import re
import unicodedata
from typing import Any
from urllib.parse import urlencode

from .files import parse_xml
from .http import CachedHTTP, download
from .types import (
    IdentificationRequired,
    MatchCandidate,
    MetadataProposal,
    ProviderUnavailable,
    parse_date,
    positive_id,
)


def normalized_title(value: str) -> str:
    return re.sub(r"[^\w]+", " ", unicodedata.normalize("NFKC", value).casefold()).strip()


def select_match(candidates: list[MatchCandidate], title: str, year: int | None) -> MatchCandidate:
    """Auto-identification requires an exact title and a corroborating year."""
    matches = [
        candidate
        for candidate in candidates
        if year is not None
        and candidate.year == year
        and normalized_title(title) in {normalized_title(candidate.title), normalized_title(candidate.original_title)}
    ]
    if len(matches) != 1:
        raise IdentificationRequired("Choose the matching work; automatic identification is ambiguous")
    return matches[0]


class TMDB:
    def __init__(self, http: CachedHTTP, token: str | None = None):
        self.http = http
        self.token = token if token is not None else os.environ.get("FERELIX_TMDB_TOKEN", "")

    async def get(self, path: str, **params: Any) -> dict[str, Any]:
        if not self.token:
            raise ProviderUnavailable("Configure FERELIX_TMDB_TOKEN to retrieve TMDB metadata")
        url = f"https://api.themoviedb.org/3/{path}?{urlencode(params)}"
        result = await self.http.json(url, "tmdb", headers={"Authorization": f"Bearer {self.token}"}, days=1)
        if not isinstance(result, dict) or result.get("success") is False:
            raise ProviderUnavailable("TMDB returned an invalid response")
        return result

    async def search(self, query: str, kind: str, locale: str) -> list[MatchCandidate]:
        endpoint = "movie" if kind == "movie" else "tv"
        data = await self.get(f"search/{endpoint}", query=query, language=locale, include_adult="false")
        results = []
        for row in data.get("results", [])[:20]:
            released = parse_date(row.get("release_date") or row.get("first_air_date"))
            results.append(
                MatchCandidate(
                    "tmdb",
                    str(row["id"]),
                    kind,
                    row.get("title") or row.get("name", ""),
                    row.get("original_title") or row.get("original_name", ""),
                    released.year if released else None,
                    row.get("overview", ""),
                    image_url(row.get("poster_path")),
                )
            )
        return results

    async def find_imdb(self, identifier: str, kind: str, locale: str) -> str:
        """Resolve a supplied IMDb title ID without weakening it into a title search."""
        if kind not in {"movie", "series"} or not re.fullmatch(r"tt[0-9]+", identifier):
            raise IdentificationRequired("A valid IMDb title identifier is required")
        data = await self.get(f"find/{identifier}", external_source="imdb_id", language=locale)
        matches = data.get("movie_results" if kind == "movie" else "tv_results")
        if not isinstance(matches, list) or len(matches) != 1 or not isinstance(matches[0], dict):
            raise IdentificationRequired("The IMDb identifier does not resolve to exactly one work of this type")
        try:
            return positive_id(str(matches[0].get("id", "")))
        except ValueError as error:
            raise IdentificationRequired("TMDB returned an invalid identity for this IMDb identifier") from error

    async def fetch(self, identifier: str, kind: str, locale: str) -> MetadataProposal:
        identifier = positive_id(identifier)
        if kind == "collection":
            return await self.collection(identifier, locale)
        endpoint = "movie" if kind == "movie" else "tv"
        data = await self.get(
            f"{endpoint}/{identifier}",
            language=locale,
            append_to_response="translations,credits,keywords,alternative_titles,external_ids",
        )
        if str(data.get("id")) != identifier:
            raise ProviderUnavailable("TMDB returned a different identity")
        proposal = tmdb_proposal(data, kind, locale)
        if kind == "movie" and (data.get("belongs_to_collection") or {}).get("id"):
            proposal.collection = await self.collection(str(data["belongs_to_collection"]["id"]), locale)
        if kind == "series":
            seasons = data.get("seasons")
            if not isinstance(seasons, list) or len(seasons) > 200:
                raise ProviderUnavailable("TMDB did not return a supported season catalogue")
            for season in seasons:
                number = season["season_number"]
                details = await self.get(
                    f"tv/{identifier}/season/{number}", language=locale, append_to_response="translations"
                )
                child = tmdb_proposal(details, "season", locale)
                child.fields["season_number"] = number
                episodes = details.get("episodes")
                if not isinstance(episodes, list) or len(episodes) > 5000:
                    raise ProviderUnavailable("TMDB did not return a complete episode catalogue")
                numbers = [episode.get("episode_number") for episode in episodes]
                if any(type(number) is not int or number < 0 for number in numbers) or len(set(numbers)) != len(
                    numbers
                ):
                    raise ProviderUnavailable("TMDB returned ambiguous episode numbers")
                for episode in episodes:
                    ep = tmdb_proposal(episode, "episode", locale)
                    ep.fields["season_number"] = number
                    ep.fields["episode_number"] = episode["episode_number"]
                    ep.order_confirmed = True
                    ep.hierarchy_complete = True
                    child.children.append(ep)
                child.hierarchy_complete = True
                child.order_confirmed = True
                proposal.children.append(child)
            proposal.hierarchy_complete = True
            proposal.order_confirmed = True
        return proposal

    async def collection(self, identifier: str, locale: str) -> MetadataProposal:
        data = await self.get(f"collection/{positive_id(identifier)}", language=locale)
        if str(data.get("id")) != identifier:
            raise ProviderUnavailable("TMDB returned a different collection identity")
        parts = data.get("parts")
        if not isinstance(parts, list) or len(parts) > 1000:
            raise ProviderUnavailable("TMDB did not return a complete collection")
        result = tmdb_proposal(data, "collection", locale)
        result.children = [tmdb_proposal(row, "movie", locale) for row in parts]
        dates = [child.fields.get("release_date") for child in result.children]
        result.hierarchy_complete = True
        result.order_confirmed = all(dates) and len(set(dates)) == len(dates)
        for child in result.children:
            child.order_confirmed = result.order_confirmed
        return result


def image_url(path: Any) -> str | None:
    return f"https://image.tmdb.org/t/p/w780{path}" if isinstance(path, str) and path.startswith("/") else None


def tmdb_proposal(data: dict[str, Any], kind: str, locale: str) -> MetadataProposal:  # ruff: ignore[complex-structure]
    result = MetadataProposal(kind)
    fields: dict[str, Any] = {
        "title": data.get("title") or data.get("name", ""),
        "original_title": data.get("original_title") or data.get("original_name"),
        "overview": data.get("overview"),
        "tagline": data.get("tagline"),
        "original_language": data.get("original_language"),
        "release_date": parse_date(data.get("release_date") or data.get("first_air_date") or data.get("air_date")),
        "provider_ids": {"tmdb": str(data["id"])},
        "metadata_locale": locale,
    }
    for key in ("genres",):
        if key in data:
            fields[key] = data[key]
    if "keywords" in data:
        fields["keywords"] = data["keywords"].get("keywords", data["keywords"].get("results", []))
    if "credits" in data:
        fields["credits"] = [
            {
                "id": row.get("id"),
                "name": row.get("name"),
                "role": row.get("character") or row.get("job"),
                "department": row.get("department"),
                "source": "tmdb",
            }
            for row in [*data["credits"].get("cast", [])[:50], *data["credits"].get("crew", [])[:50]]
        ]
    if "production_companies" in data:
        fields["studios"] = [{"id": row["id"], "name": row["name"]} for row in data["production_companies"]]
    if "production_countries" in data:
        fields["countries"] = [row["iso_3166_1"] for row in data["production_countries"]]
    alternatives = data.get("alternative_titles", {})
    fields["aliases"] = sorted({row["title"] for row in alternatives.get("titles", alternatives.get("results", []))})
    external = data.get("external_ids", {})
    for name in ("imdb", "tvdb"):
        if external.get(f"{name}_id"):
            fields["provider_ids"][name] = str(external[f"{name}_id"])
    result.fields = {key: value for key, value in fields.items() if value is not None}
    result.provenance = {key: {"source": "tmdb", "locale": None, "requested_locale": locale} for key in result.fields}
    translations = data.get("translations", {}).get("translations", [])
    if translations:
        candidates = [
            row
            for requested in [locale, locale.split("-", maxsplit=1)[0], "en-US", "en"]
            for row in translations
            if requested in {f"{row.get('iso_639_1')}-{row.get('iso_3166_1')}", row.get("iso_639_1")}
        ]
        for name in ("title", "overview", "tagline"):
            source_name = "name" if name == "title" and kind != "movie" else name
            match = next((row for row in candidates if row.get("data", {}).get(source_name)), None)
            if match:
                result.fields[name] = match["data"][source_name]
                result.provenance.setdefault(name, {"source": "tmdb"})["locale"] = "-".join(
                    filter(None, [match.get("iso_639_1"), match.get("iso_3166_1")])
                )
            elif name == "title" and fields.get("original_title"):
                result.fields[name] = fields["original_title"]
                result.provenance[name]["locale"] = fields.get("original_language")
    for role, field in (("poster", "poster_path"), ("backdrop", "backdrop_path")):
        if url := image_url(data.get(field)):
            result.artwork[role] = url
    if kind == "episode" and (url := image_url(data.get("still_path"))):
        result.artwork["backdrop"] = url
    return result


class AniDB:
    def __init__(self, http: CachedHTTP):
        self.http = http

    async def search(self, query: str, kind: str, locale: str) -> list[MatchCandidate]:
        """Search the public title dump locally instead of spending one API call per candidate."""
        payload = await self.http.cached("anidb:title_index:v1")
        if payload is None:
            raw = await asyncio.to_thread(download, "https://anidb.net/api/anime-titles.xml.gz", None, 20_000_000)
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
                content = stream.read(80_000_001)
            root = parse_xml(content.decode("utf-8"), maximum=80_000_000)
            if root.tag != "animetitles":
                raise ProviderUnavailable("AniDB returned an invalid title index")
            titles = [
                {
                    "id": anime.get("aid"),
                    "titles": [
                        {
                            "title": node.text or "",
                            "language": node.get("{http://www.w3.org/XML/1998/namespace}lang"),
                            "type": node.get("type"),
                        }
                        for node in anime.findall("title")
                    ],
                }
                for anime in root.findall("anime")
                if (anime.get("aid") or "").isdecimal()
            ]
            payload = {"titles": titles}
            await self.http.put("anidb:title_index:v1", "anidb", payload, 7 * 86400)
        requested = normalized_title(query)
        results = []
        for anime in payload["titles"]:
            matches = [row for row in anime["titles"] if requested in normalized_title(row["title"])]
            if not matches:
                continue
            exact = next((row for row in matches if normalized_title(row["title"]) == requested), None)
            display = next(
                (
                    row["title"]
                    for language in [locale, locale.split("-", maxsplit=1)[0], "en", "ja", "x-jat"]
                    for row in anime["titles"]
                    if row["language"] == language
                ),
                matches[0]["title"],
            )
            candidate = MatchCandidate("anidb", anime["id"], kind, display, query if exact else matches[0]["title"])
            results.append((0 if exact else 1, display, candidate))
        return [row[2] for row in sorted(results, key=lambda row: (row[0], row[1], row[2].provider_id))[:20]]

    async def fetch(self, identifier: str, kind: str, locale: str) -> MetadataProposal:
        identifier = positive_id(identifier)
        client = os.environ.get("FERELIX_ANIDB_CLIENT", "")
        version = os.environ.get("FERELIX_ANIDB_CLIENT_VERSION", "1")
        if not re.fullmatch(r"[a-z][a-z0-9]{3,31}", client) or not version.isdecimal():
            raise ProviderUnavailable("Configure a registered FERELIX_ANIDB_CLIENT and client version")
        url = "http://api.anidb.net:9001/httpapi?" + urlencode({
            "request": "anime",
            "client": client,
            "clientver": version,
            "protover": 1,
            "aid": identifier,
        })
        root = parse_xml(await self.http.anidb(url, identifier))
        is_movie = root.findtext("type") == "Movie"
        if (kind == "movie") != is_movie:
            raise IdentificationRequired("The AniDB entry has a different media type")
        lang = "{http://www.w3.org/XML/1998/namespace}lang"
        titles = [(node.text or "", node.get(lang), node.get("type")) for node in root.findall("titles/title")]
        chosen = next(
            (
                row
                for language in [locale, locale.split("-", maxsplit=1)[0], "en", "ja", "x-jat"]
                for row in titles
                if row[1] == language and row[2] in {"main", "official"}
            ),
            None,
        )
        if not chosen:
            raise IdentificationRequired("AniDB did not provide a usable title")
        main = next((row for row in titles if row[2] == "main"), chosen)
        original_language = (
            "ja" if main[1] == "x-jat" else main[1] if main[1] and not main[1].startswith("x-") else None
        )
        result = MetadataProposal(kind)
        result.fields = {
            "title": chosen[0],
            "original_title": next((t[0] for t in titles if t[1] == "ja"), chosen[0]),
            "original_language": original_language,
            "aliases": sorted({row[0] for row in titles}),
            "provider_ids": {"anidb": identifier},
            "release_date": parse_date(root.findtext("startdate")),
            "metadata_locale": locale,
            "keywords": [
                {"id": node.get("id"), "name": node.findtext("name"), "source": "anidb"}
                for node in root.findall("tags/tag")
                if node.findtext("name")
            ],
        }
        description = root.findtext("description")
        if description:
            result.fields["overview"] = description
        credits = [
            {
                "id": actor.get("id"),
                "name": actor.text or "",
                "role": character.findtext("name"),
                "department": "Acting",
                "source": "anidb",
            }
            for character in root.findall("characters/character")
            for actor in character.findall("seiyuu")
        ]
        credits.extend(
            {"id": creator.get("id"), "name": creator.text or "", "role": creator.get("type"), "source": "anidb"}
            for creator in root.findall("creators/name")
        )
        if credits:
            result.fields["credits"] = credits
        result.provenance = {
            key: {"source": "anidb", "locale": chosen[1] if key == "title" else None} for key in result.fields
        }
        if (image := root.findtext("picture")) and re.fullmatch(r"[a-zA-Z0-9_.-]+", image):
            result.artwork["poster"] = f"https://cdn.anidb.net/images/main/{image}"
        if kind == "series":
            regular = MetadataProposal(
                "season", {"title": chosen[0], "season_number": 1, "provider_ids": {"anidb": identifier}}
            )
            specials = MetadataProposal("season", {"title": "Specials", "season_number": 0})
            for episode in root.findall("episodes/episode"):
                number = episode.find("epno")
                if number is None or number.get("type") not in {"1", "2"}:
                    continue
                raw_number = number.text or ""
                digits = raw_number if number.get("type") == "1" else raw_number.removeprefix("S")
                if not digits.isdecimal():
                    continue
                season = regular if number.get("type") == "1" else specials
                names = [(node.text or "", node.get(lang)) for node in episode.findall("title")]
                name = next(
                    (
                        value
                        for language in [locale.split("-", maxsplit=1)[0], "en", "ja", "x-jat"]
                        for value, tag in names
                        if tag == language
                    ),
                    raw_number,
                )
                season.children.append(
                    MetadataProposal(
                        "episode",
                        {
                            "title": name,
                            "season_number": season.fields["season_number"],
                            "episode_number": int(digits),
                            "provider_ids": {"anidb": identifier, "anidb_episode": str(episode.get("id"))},
                            "release_date": parse_date(episode.findtext("airdate")),
                            "metadata_locale": locale,
                        },
                        {"title": {"source": "anidb", "locale": None}},
                    )
                )
            result.children = [season for season in (specials, regular) if season.children]
            result.hierarchy_complete = True
            # Local SxxEyy numbering must be explicitly confirmed or mapped; an AniDB entry is not a TMDB series.
            result.order_confirmed = False
        return result


class AniBridge:
    """Versioned mapping data. Unsupported and non-bijective ranges stay explicit."""

    URL = "https://github.com/anibridge/anibridge-mappings/releases/download/v3/mappings.min.json"

    def __init__(self, http: CachedHTTP):
        self.http = http

    async def targets(self, descriptor: str) -> dict[str, Any]:
        data = await self.http.json(self.URL, "anibridge", maximum=80_000_000)
        if not isinstance(data, dict):
            raise ProviderUnavailable("Invalid AniBridge mapping dataset")
        return data.get(descriptor, {})

    async def anime_ids(self, tmdb_id: str, kind: str) -> list[str]:
        descriptor = f"tmdb_movie:{positive_id(tmdb_id)}" if kind == "movie" else f"tmdb_show:{positive_id(tmdb_id)}:s1"
        targets = await self.targets(descriptor)
        return sorted({key.split(":")[1] for key in targets if re.fullmatch(r"anidb:\d+:R", key)})

    async def map_absolute_episode(self, aid: str, number: int, tmdb_series_id: str) -> tuple[int, int] | None:
        """Resolve only an explicit, unambiguous one-to-one anime episode placement."""
        targets = await self.targets(f"anidb:{positive_id(aid)}:R")
        series_id = positive_id(tmdb_series_id)
        matches = []
        for target, ranges in targets.items():
            descriptor = re.fullmatch(rf"tmdb_show:{series_id}:s(\d+)", target)
            if descriptor and isinstance(ranges, dict):
                episode = self.map_episode(ranges, number)
                if episode is not None:
                    matches.append((int(descriptor[1]), episode))
        if len(matches) > 1:
            raise IdentificationRequired("Several placements match this absolute episode")
        return matches[0] if matches else None

    @staticmethod
    def map_episode(ranges: dict[str, str | None], number: int) -> int | None:
        matches = []
        for source, target in ranges.items():
            start, end = _mapping_range(source)
            if number < start or (end is not None and number > end):
                continue
            if target is None:
                matches.append(None)
                continue
            other, other_end = _mapping_range(target)
            if end is not None and other_end is not None and end - start != other_end - other:
                raise IdentificationRequired("Split or combined episodes need explicit file boundaries")
            mapped = other + number - start
            if other_end is None or mapped <= other_end:
                matches.append(mapped)
        if len(matches) > 1:
            raise IdentificationRequired("Conflicting episode mappings")
        return matches[0] if matches else None


def _mapping_range(value: str) -> tuple[int, int | None]:
    match = re.fullmatch(r"([1-9]\d*)(?:-([1-9]\d*)?)?", value)
    if match is None:
        raise IdentificationRequired("Ratios and non-contiguous ranges require explicit episode placement")
    start = int(match[1])
    end = None if value.endswith("-") else int(match[2] or match[1])
    if end is not None and end < start:
        raise IdentificationRequired("Invalid descending episode range")
    return start, end
