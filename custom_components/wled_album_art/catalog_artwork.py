"""Bounded cover lookups from Deezer and TheAudioDB's public catalogs."""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
import unicodedata
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping
from email.utils import parsedate_to_datetime
from math import ceil, isfinite
from urllib.parse import quote, urlsplit

import aiohttp

_USER_AGENT = "MusicArtworkLighting/0.16.2 (Home Assistant custom integration)"
_MAX_CANDIDATES = 10
_MAX_IMAGE_ATTEMPTS = 6
_MAX_JSON_BYTES = 1_000_000
_MAX_BACKOFF_ENTRIES = 128
_REQUEST_INTERVALS = {"deezer": 1.0, "theaudiodb": 2.1}
_PROVIDER_LOCKS = {provider: asyncio.Lock() for provider in _REQUEST_INTERVALS}
_LAST_REQUEST = {provider: 0.0 for provider in _REQUEST_INTERVALS}
# Cooldowns are shared across integration entries. Raw API keys are never stored here.
_BACKOFF: OrderedDict[tuple[str, str], tuple[str, float]] = OrderedDict()
_ARTIST_SEPARATOR = re.compile(
    r"\s+(?:feat\.?|ft\.?|featuring)\s+|,\s*|;\s*|\s+&\s+", re.I,
)
_FEATURE_CREDIT = re.compile(
    r"\s*[\[(](?:feat\.?|ft\.?|featuring)\s+[^\])]+[\])]\s*$"
    r"|\s+(?:feat\.?|ft\.?|featuring)\s+.+$", re.I,
)
_ERROR_MESSAGES = {
    "invalid_api_key": "The artwork provider rejected its API key",
    "rate_limited": "The artwork provider reached its request limit; retry later",
    "service_unavailable": "The artwork provider is temporarily unavailable",
    "timeout": "The artwork provider request timed out",
    "connection_failed": "Could not connect to the artwork provider",
    "tls_error": "Could not verify the artwork provider's HTTPS certificate",
    "api_error": "The artwork provider returned an invalid response",
    "image_download_failed": "The artwork provider found a cover that could not be downloaded",
    "unsupported_image_host": "The artwork provider returned an unrecognized image host",
}

ImageFetcher = Callable[[str, Callable[[str], bool]], Awaitable[bytes | None]]


def _text(value: object) -> str:
    """Keep metadata and provider strings small and predictable."""
    return " ".join(str(value or "").split())[:200]


def _match_key(value: object) -> str:
    """Compare spelling and punctuation without discarding version names."""
    decomposed = unicodedata.normalize("NFKD", unicodedata.normalize("NFKC", _text(value)).casefold())
    return "".join(character for character in decomposed if character.isalnum())


def _artist_queries(artist: str) -> list[str]:
    """Try the full credit before one bounded primary-credit fallback."""
    primary = _ARTIST_SEPARATOR.split(artist, maxsplit=1)[0].strip()
    return list(dict.fromkeys(value for value in (artist, primary) if value))


def _title_queries(title: str) -> list[str]:
    """Only remove featured performers, keeping live, remix and remaster names."""
    plain = _FEATURE_CREDIT.sub("", title).strip()
    return list(dict.fromkeys(value for value in (title, plain) if value))


def _same_title(actual: object, expected: str) -> bool:
    """A versioned track must match that version, not just its base title."""
    actual_text = _text(actual)
    return bool(actual_text) and bool(
        {_match_key(value) for value in _title_queries(actual_text)}
        & {_match_key(value) for value in _title_queries(expected)}
    )


class CatalogLookupError(ValueError):
    """Expose a safe provider name and reason without URLs or credentials."""

    def __init__(self, provider: str, reason: str) -> None:
        self.provider = provider
        self.reason = reason
        super().__init__(_ERROR_MESSAGES.get(reason, "Artwork catalog lookup failed"))


class CatalogArtworkLookup:
    """Fetch validated covers; the caller owns song caching and result reporting."""

    def __init__(
        self, session: aiohttp.ClientSession, fetch_image: ImageFetcher,
        *, none_is_miss: bool = False,
    ) -> None:
        self._session = session
        self._fetch_image = fetch_image
        # Animation upgrades deliberately decline otherwise valid static
        # images. Keep searching without scheduling retries for those misses;
        # exceptions still record real download failures below.
        self._none_is_miss = bool(none_is_miss)
        self._theaudiodb_api_key = "123"
        self._theaudiodb_key_configured = False

    def configure(self, theaudiodb_api_key: str) -> None:
        """A blank key uses TheAudioDB's documented public free key."""
        api_key = str(theaudiodb_api_key or "").strip()
        self._theaudiodb_key_configured = bool(api_key)
        self._theaudiodb_api_key = api_key or "123"

    def _backoff_key(self, provider: str) -> tuple[str, str]:
        fingerprint = (
            hashlib.sha256(self._theaudiodb_api_key.encode()).hexdigest()
            if provider == "theaudiodb" else "public"
        )
        return provider, fingerprint

    def _backoff(self, provider: str) -> tuple[str, float] | None:
        key = self._backoff_key(provider)
        record = _BACKOFF.get(key)
        if record is None:
            return None
        if record[1] <= time.monotonic():
            _BACKOFF.pop(key, None)
            return None
        _BACKOFF.move_to_end(key)
        return record

    def blocked_reason(self, provider: str) -> str | None:
        """Allow the caller to skip progress messages while a service is blocked."""
        record = self._backoff(provider)
        return record[0] if record else None

    def retry_deadline(self, provider: str) -> float | None:
        """Expose a finite monotonic cooldown to the song retry scheduler."""
        record = self._backoff(provider)
        return record[1] if record and isfinite(record[1]) else None

    def _remember_failure(
        self, provider: str, reason: str, retry_after: float | None = None,
    ) -> None:
        if reason == "invalid_api_key":
            deadline = float("inf")
        elif reason in {"rate_limited", "service_unavailable", "timeout"}:
            seconds = max(1.0, retry_after or 60.0)
            if provider == "theaudiodb" and reason == "rate_limited":
                seconds = max(60.0, seconds)
            deadline = time.monotonic() + seconds
        else:
            return
        key = self._backoff_key(provider)
        # Never shorten a cooldown already announced by this service.
        current = self._backoff(provider)
        if current and current[1] > deadline:
            return
        _BACKOFF[key] = reason, deadline
        _BACKOFF.move_to_end(key)
        while len(_BACKOFF) > _MAX_BACKOFF_ENTRIES:
            _BACKOFF.popitem(last=False)

    def clear_authentication_backoff(self) -> None:
        """Explicit refresh can retry a key; request-limit cooldowns remain active."""
        if self.blocked_reason("theaudiodb") == "invalid_api_key":
            _BACKOFF.pop(self._backoff_key("theaudiodb"), None)

    def remember_timeout(self, provider: str) -> None:
        """Apply shared cooldown when the caller's total lookup budget expires."""
        if provider in _REQUEST_INTERVALS:
            self._remember_failure(provider, "timeout")

    def diagnostics(self) -> dict:
        """Return only safe service names, cooldown reasons and remaining time."""
        result = {"theaudiodb_api_key_configured": self._theaudiodb_key_configured}
        for provider in _REQUEST_INTERVALS:
            backoff = self._backoff(provider)
            result[f"{provider}_backoff_reason"] = backoff[0] if backoff else None
            result[f"{provider}_retry_after_seconds"] = (
                max(0, ceil(backoff[1] - time.monotonic()))
                if backoff and isfinite(backoff[1]) else None
            )
        return result

    async def async_cover(
        self, provider: str, title: str, artist: str, album: str,
    ) -> bytes | None:
        """Try a small set of exact catalog matches and provider-owned images."""
        title, artist, album = (_text(value) for value in (title, artist, album))
        if provider not in _REQUEST_INTERVALS or not title or not artist:
            return None
        if reason := self.blocked_reason(provider):
            raise CatalogLookupError(provider, reason)
        attempts: dict[str, object] = {"urls": set(), "failed": False, "untrusted": False}
        try:
            if provider == "deezer":
                image = await self._async_deezer_cover(title, artist, album, attempts)
            else:
                image = await self._async_theaudiodb_cover(title, artist, album, attempts)
        except CatalogLookupError:
            raise
        except asyncio.TimeoutError as err:
            self._remember_failure(provider, "timeout")
            raise CatalogLookupError(provider, "timeout") from err
        except aiohttp.ClientSSLError as err:
            raise CatalogLookupError(provider, "tls_error") from err
        except aiohttp.ClientError as err:
            raise CatalogLookupError(provider, "connection_failed") from err
        except (ValueError, TypeError, OSError) as err:
            raise CatalogLookupError(provider, "api_error") from err
        if image is not None:
            return image
        if attempts["failed"]:
            raise CatalogLookupError(provider, "image_download_failed")
        if attempts["untrusted"]:
            raise CatalogLookupError(provider, "unsupported_image_host")
        return None

    async def _async_deezer_cover(
        self, title: str, artist: str, album: str, attempts: dict,
    ) -> bytes | None:
        for credited_artist in _artist_queries(artist):
            for track_title in _title_queries(title):
                payload = await self._async_json(
                    "deezer", "https://api.deezer.com/search",
                    {"q": f"{credited_artist} {track_title}", "limit": _MAX_CANDIDATES},
                )
                rows = payload.get("data") or []
                if not isinstance(rows, list):
                    raise CatalogLookupError("deezer", "api_error")
                candidates = []
                for row in rows[:_MAX_CANDIDATES]:
                    if not isinstance(row, dict):
                        continue
                    artist_data = row.get("artist")
                    album_data = row.get("album")
                    if not isinstance(artist_data, dict) or not isinstance(album_data, dict):
                        continue
                    if (
                        _match_key(artist_data.get("name")) != _match_key(credited_artist)
                        or not _same_title(row.get("title"), title)
                    ):
                        continue
                    # Catalogs may associate a song with a single or compilation.
                    # Prefer the reported album without rejecting the right track.
                    score = int(bool(album) and _match_key(album_data.get("title")) == _match_key(album))
                    candidates.append((score, album_data))
                candidates.sort(key=lambda item: item[0], reverse=True)
                for _score, album_data in candidates:
                    for field in ("cover_big", "cover_medium", "cover_xl", "cover"):
                        image = await self._async_image("deezer", album_data.get(field), attempts)
                        if image is not None:
                            return image
        return None

    async def _async_theaudiodb_cover(
        self, title: str, artist: str, album: str, attempts: dict,
    ) -> bytes | None:
        # Keep personal keys in one URL path segment, including future key formats.
        api_key_segment = quote(self._theaudiodb_api_key, safe="")
        base = f"https://www.theaudiodb.com/api/v1/json/{api_key_segment}"
        attempted_album_ids: set[str] = set()
        for credited_artist in _artist_queries(artist):
            if album:
                payload = await self._async_json(
                    "theaudiodb", f"{base}/searchalbum.php", {"s": credited_artist, "a": album},
                )
                for row in self._rows(payload, "album"):
                    if (
                        _match_key(row.get("strArtist")) != _match_key(credited_artist)
                        or _match_key(row.get("strAlbum")) != _match_key(album)
                    ):
                        continue
                    image = await self._async_album_image(row, attempts)
                    if image is not None:
                        return image
            for track_title in _title_queries(title):
                payload = await self._async_json(
                    "theaudiodb", f"{base}/searchtrack.php", {"s": credited_artist, "t": track_title},
                )
                candidates = [
                    row for row in self._rows(payload, "track")
                    if _match_key(row.get("strArtist")) == _match_key(credited_artist)
                    and _same_title(row.get("strTrack"), title)
                ]
                candidates.sort(
                    key=lambda row: bool(album) and _match_key(row.get("strAlbum")) == _match_key(album),
                    reverse=True,
                )
                for row in candidates:
                    image = await self._async_image("theaudiodb", row.get("strTrackThumb"), attempts)
                    if image is not None:
                        return image
                    album_id = str(row.get("idAlbum") or "")
                    # Missing track thumbnails are common. Resolve up to two
                    # distinct album IDs instead of assuming the song has no art.
                    if (
                        not re.fullmatch(r"[0-9]{1,20}", album_id)
                        or album_id in attempted_album_ids
                        or len(attempted_album_ids) >= 2
                    ):
                        continue
                    attempted_album_ids.add(album_id)
                    album_payload = await self._async_json(
                        "theaudiodb", f"{base}/album.php", {"m": album_id},
                    )
                    for album_row in self._rows(album_payload, "album"):
                        if (
                            str(album_row.get("idAlbum") or "") != album_id
                            or _match_key(album_row.get("strArtist")) != _match_key(credited_artist)
                        ):
                            continue
                        image = await self._async_album_image(album_row, attempts)
                        if image is not None:
                            return image
        return None

    async def _async_album_image(self, row: dict, attempts: dict) -> bytes | None:
        for field in ("strAlbumThumb", "strAlbumThumbHQ"):
            image = await self._async_image("theaudiodb", row.get(field), attempts)
            if image is not None:
                return image
        return None

    @staticmethod
    def _rows(payload: dict, key: str) -> list[dict]:
        rows = payload.get(key) or []
        if not isinstance(rows, list):
            raise CatalogLookupError("theaudiodb", "api_error")
        return [row for row in rows[:_MAX_CANDIDATES] if isinstance(row, dict)]

    async def _async_image(self, provider: str, value: object, attempts: dict) -> bytes | None:
        if not isinstance(value, str) or not value.strip():
            return None
        url = value.strip()
        urls = attempts["urls"]
        if url in urls or len(urls) >= _MAX_IMAGE_ATTEMPTS:
            return None
        urls.add(url)
        predicate = self._is_trusted_deezer_host if provider == "deezer" else self._is_trusted_theaudiodb_host
        try:
            parsed = urlsplit(url)
            valid = (
                len(url) <= 4096 and parsed.scheme in {"http", "https"}
                and parsed.hostname and predicate(parsed.hostname)
                and parsed.username is None and parsed.password is None
                and parsed.port in {None, 80, 443}
            )
        except ValueError:
            valid = False
        if not valid:
            attempts["untrusted"] = True
            return None
        try:
            image = await self._fetch_image(url, predicate)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, OSError):
            attempts["failed"] = True
            return None
        if not image and not self._none_is_miss:
            attempts["failed"] = True
        return image

    async def _async_json(self, provider: str, url: str, params: dict) -> dict:
        async with _PROVIDER_LOCKS[provider]:
            if reason := self.blocked_reason(provider):
                raise CatalogLookupError(provider, reason)
            delay = _REQUEST_INTERVALS[provider] - (time.monotonic() - _LAST_REQUEST[provider])
            if delay > 0:
                await asyncio.sleep(delay)
            _LAST_REQUEST[provider] = time.monotonic()
            try:
                return await self._async_request_json(provider, url, params)
            except asyncio.TimeoutError as err:
                self._remember_failure(provider, "timeout")
                raise CatalogLookupError(provider, "timeout") from err

    async def _async_request_json(self, provider: str, url: str, params: dict) -> dict:
        # API requests never redirect: TheAudioDB embeds its API key in the path.
        async with self._session.get(
            url, params=params,
            headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
            timeout=aiohttp.ClientTimeout(total=12), allow_redirects=False,
        ) as response:
            status = response.status
            if status == 429 or status >= 500 or (provider == "deezer" and status == 403):
                reason = "rate_limited" if status == 429 else "service_unavailable"
                self._remember_failure(provider, reason, self._retry_after_seconds(response.headers))
                raise CatalogLookupError(provider, reason)
            if provider == "theaudiodb" and status in {401, 403, 404}:
                self._remember_failure(provider, "invalid_api_key")
                raise CatalogLookupError(provider, "invalid_api_key")
            if status >= 300:
                raise CatalogLookupError(provider, "api_error")
            try:
                if int(response.headers.get("Content-Length") or 0) > _MAX_JSON_BYTES:
                    raise ValueError("Catalog response exceeds size limit")
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.content.iter_chunked(64 * 1024):
                    size += len(chunk)
                    if size > _MAX_JSON_BYTES:
                        raise ValueError("Catalog response exceeds size limit")
                    chunks.append(chunk)
                payload = json.loads(b"".join(chunks))
            except (ValueError, TypeError) as err:
                raise CatalogLookupError(provider, "api_error") from err
        if not isinstance(payload, dict):
            raise CatalogLookupError(provider, "api_error")
        if provider == "deezer" and payload.get("error"):
            error = payload["error"]
            try:
                code = int(error.get("code", 0)) if isinstance(error, dict) else 0
            except (TypeError, ValueError):
                code = 0
            if code == 800:  # A normal catalog miss.
                return {"data": []}
            reason = "rate_limited" if code == 4 else "api_error"
            self._remember_failure(provider, reason, self._retry_after_seconds(response.headers))
            raise CatalogLookupError(provider, reason)
        if provider == "theaudiodb" and (payload.get("error") or payload.get("Message")):
            raise CatalogLookupError(provider, "api_error")
        return payload

    @staticmethod
    def _retry_after_seconds(headers: Mapping) -> float:
        value = str(headers.get("Retry-After") or "").strip()
        try:
            seconds = float(value)
            if isfinite(seconds):
                return max(1.0, seconds)
        except (TypeError, ValueError):
            pass
        try:
            seconds = parsedate_to_datetime(value).timestamp() - time.time()
            if isfinite(seconds):
                return max(1.0, seconds)
        except (TypeError, ValueError, OverflowError):
            pass
        return 60.0

    @staticmethod
    def _is_trusted_deezer_host(host: str) -> bool:
        host = host.casefold().rstrip(".")
        return any(host == domain or host.endswith(f".{domain}") for domain in ("dzcdn.net", "deezer.com"))

    @staticmethod
    def _is_trusted_theaudiodb_host(host: str) -> bool:
        host = host.casefold().rstrip(".")
        return host == "theaudiodb.com" or host.endswith(".theaudiodb.com")
