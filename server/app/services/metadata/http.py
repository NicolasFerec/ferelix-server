"""Bounded provider requests and a durable cache, without SQL transactions over network I/O."""

import asyncio
import gzip
import hashlib
import io
import json
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from app.database import async_session_maker
from app.models.metadata import MetadataCache

from .files import parse_xml
from .types import ProviderUnavailable

_HOSTS = frozenset({
    "api.themoviedb.org",
    "image.tmdb.org",
    "api.anidb.net",
    "anidb.net",
    "cdn.anidb.net",
    "github.com",
    "release-assets.githubusercontent.com",
    "raw.githubusercontent.com",
})
_anidb_gate = asyncio.Lock()
_next_anidb_request = 0.0


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.hostname not in _HOSTS or parsed.username or parsed.password:
        raise ValueError("Unsupported metadata source")
    if parsed.scheme != "https" and not (
        parsed.scheme == "http" and parsed.hostname == "api.anidb.net" and parsed.port == 9001
    ):
        raise ValueError("Unsupported metadata protocol")
    if parsed.scheme == "https" and parsed.port not in (None, 443):
        raise ValueError("Unsupported metadata port")


class _Redirects(HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        validate_url(newurl)
        if req.has_header("Authorization") and urlparse(req.full_url).hostname != urlparse(newurl).hostname:
            raise ValueError("Authenticated provider requests cannot redirect to another host")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(url: str, headers: dict[str, str] | None = None, maximum: int = 20_000_000) -> bytes:
    """Only fixed provider hosts are accepted, including every redirect destination."""
    validate_url(url)
    request = Request(url, headers={"User-Agent": "Ferelix/1 Metadata", **(headers or {})})
    try:
        with build_opener(_Redirects()).open(request, timeout=15) as response:
            content = response.read(maximum + 1)
            if len(content) > maximum:
                raise ProviderUnavailable("Provider response exceeds the supported size")
            return content
    except HTTPError as error:
        raise ProviderUnavailable(f"Provider HTTP {error.code}") from error
    except (URLError, TimeoutError, OSError) as error:
        raise ProviderUnavailable("Provider request failed") from error


class CachedHTTP:
    def __init__(self, session_factory: Any = async_session_maker):
        self.sessions = session_factory

    async def cached(self, key: str, *, stale: bool = False) -> Any | None:
        async with self.sessions() as session:
            row = await session.get(MetadataCache, key)
            if row and (stale or row.expires_at > utcnow()):
                return row.payload
        return None

    async def put(self, key: str, provider: str, payload: Any, seconds: int) -> None:
        async with self.sessions() as session:
            await session.merge(
                MetadataCache(
                    key=key,
                    provider=provider,
                    payload=payload,
                    fetched_at=utcnow(),
                    expires_at=utcnow() + timedelta(seconds=seconds),
                )
            )
            await session.commit()

    async def json(
        self,
        url: str,
        provider: str,
        *,
        headers: dict[str, str] | None = None,
        days: int = 7,
        maximum: int = 20_000_000,
    ) -> Any:
        key = f"{provider}:{hashlib.sha256(url.encode()).hexdigest()}"
        cached = await self.cached(key)
        if cached is not None:
            return cached
        raw = await asyncio.to_thread(download, url, headers, maximum)
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeError) as error:
            raise ProviderUnavailable("Provider returned invalid JSON") from error
        await self.put(key, provider, result, days * 86400)
        return result

    async def anidb(self, url: str, aid: str) -> str:
        """One document per anime, paced globally; bans survive process restarts."""
        global _next_anidb_request
        key = f"anidb:anime:{aid}"
        async with _anidb_gate:
            cached = await self.cached(key)
            if cached is not None:
                return cached["xml"]
            if await self.cached(f"anidb:refused:{aid}"):
                raise IdentificationError("AniDB recently rejected this identifier")
            cooldown = await self.cached("anidb:cooldown")
            if cooldown:
                old = await self.cached(key, stale=True)
                if old:
                    return old["xml"]
                raise ProviderUnavailable("AniDB requests are paused after a provider refusal")
            await asyncio.sleep(max(0, _next_anidb_request - time.monotonic()))
            _next_anidb_request = time.monotonic() + 3.0
            raw = await asyncio.to_thread(download, url, None, 8_000_000)
            if raw.startswith(b"\x1f\x8b"):
                with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
                    raw = stream.read(8_000_001)
            if len(raw) > 8_000_000:
                raise ProviderUnavailable("AniDB document is too large")
            text = raw.decode("utf-8")
            if not text.strip() or "banned" in text.lower()[:500] or '<error code="500"' in text:
                state = await self.cached("anidb:backoff", stale=True) or {"seconds": 1800}
                seconds = min(86400, state["seconds"])
                await self.put("anidb:cooldown", "anidb", {"paused": True}, seconds)
                await self.put("anidb:backoff", "anidb", {"seconds": min(86400, seconds * 2)}, 86400 * 30)
                raise ProviderUnavailable("AniDB refused requests; automatic retry is postponed")
            if "<error" in text:
                await self.put(f"anidb:refused:{aid}", "anidb", {"refused": True}, 86400)
                raise IdentificationError("AniDB could not find this anime")
            # Parsing/validation is performed before persisting so error documents never replace good data.
            root = parse_xml(text)
            if root.tag != "anime" or root.get("id") != aid:
                raise ProviderUnavailable("AniDB returned a mismatched document")
            await self.put(key, "anidb", {"xml": text}, 7 * 86400)
            await self.put("anidb:backoff", "anidb", {"seconds": 1800}, 30 * 86400)
            return text


class IdentificationError(ProviderUnavailable):
    """A provider rejected an explicit identifier."""
