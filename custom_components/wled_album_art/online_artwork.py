"""Look up music covers and optional animated upgrades from metadata providers."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
import unicodedata
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from math import ceil, isfinite
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

import aiohttp

from .catalog_artwork import CatalogArtworkLookup, CatalogLookupError
from .const import (
    USER_AGENT,
    ARTWORK_PROVIDER_PRIORITIES,
    CONF_ARTWORK_PROVIDERS,
    CONF_ARTWORK_PROVIDER_PRIORITY,
    MAX_CACHED_IMAGE_BYTES,
    artwork_provider_order,
)
from .error_utils import safe_error_text
from .image_download import read_bounded_image, validate_image_animation
from .music_metadata import lookup_metadata_variants

_LOGGER = logging.getLogger(__name__)
_LOOKUP_CACHE_TTL = 24 * 60 * 60
_LOOKUP_FAILURE_TTL = 5 * 60
_MAX_CACHE_ENTRIES = 128
_PROVIDER_TIMEOUT_SECONDS = 20
_MB_REQUEST_INTERVAL = 1.0
_MB_LOCK = asyncio.Lock()
_LAST_MB_REQUEST = 0.0
_LASTFM_REQUEST_INTERVAL = 1.0
_LASTFM_LOCK = asyncio.Lock()
_LAST_LASTFM_REQUEST = 0.0
# Shared across entries using the same key; only fingerprints are retained.
_LASTFM_BACKOFF: OrderedDict[str, tuple[str, float]] = OrderedDict()
_PROVIDER_NAMES = {
    "musicbrainz": "MusicBrainz / Cover Art Archive",
    "lastfm": "Last.fm",
    "deezer": "Deezer",
    "theaudiodb": "TheAudioDB",
}
_CATALOG_FAILURE_MESSAGES = {
    "invalid_api_key": "rejected the API key; check its key in Configure",
    "rate_limited": "rate limit reached; waiting before retrying",
    "service_unavailable": "is temporarily unavailable",
    "api_error": "returned an API error",
    "timeout": "request timed out",
    "connection_failed": "could not be reached",
    "tls_error": "HTTPS certificate could not be verified",
    "request_failed": "request failed; see online artwork diagnostics",
    "image_download_failed": "found a cover but its image could not be downloaded",
    "unsupported_image_host": "returned an unrecognized image host",
}
_LUCENE_SPECIAL = re.compile(r'([+\-!(){}\[\]^"~*?:\\/])')
_MBID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.I,
)
_LASTFM_ENDPOINT = "https://ws.audioscrobbler.com/2.0/"
_LASTFM_PLACEHOLDER = "2a96cbd8b46e442fc41c2b86b821562f"
_LASTFM_ERROR_REASONS = {
    10: "invalid_api_key", 26: "suspended_api_key", 29: "rate_limited",
    11: "service_unavailable", 16: "service_unavailable",
}
_LASTFM_ERROR_MESSAGES = {
    "invalid_api_key": "Last.fm rejected the API key; use the API key, not the shared secret",
    "suspended_api_key": "Last.fm has suspended this API key",
    "rate_limited": "Last.fm rate limit reached; retry later",
    "service_unavailable": "Last.fm is temporarily unavailable",
    "api_error": "Last.fm returned an API error",
    "timeout": "Last.fm request timed out",
    "connection_failed": "Could not connect to Last.fm",
    "tls_error": "Could not verify Last.fm's HTTPS certificate",
    "request_failed": "Last.fm request failed; see online artwork diagnostics",
    "image_download_failed": "Last.fm found artwork but its image could not be downloaded",
    "unsupported_image_host": "Last.fm returned an image host the integration does not recognize",
}
_ARTIST_SEPARATOR = re.compile(r"\s+(?:feat\.?|ft\.?|featuring)\s+|,\s*|;\s*|\s+&\s+", re.I)
_FEATURE_CREDIT = re.compile(
    r"\s*[\[(](?:feat\.?|ft\.?|featuring)\s+[^\])]+[\])]\s*$"
    r"|\s+(?:feat\.?|ft\.?|featuring)\s+.+$", re.I,
)
_TRANSIENT_FAILURES = {
    "rate_limited", "service_unavailable", "timeout", "connection_failed",
    "tls_error", "request_failed", "image_download_failed",
}


def _normalize_metadata(value: str | None) -> str:
    """Use the same bounded metadata for requests and current-track identity."""
    return " ".join(str(value or "").split())[:200]


def _is_transient_failure(reason: str) -> bool:
    """Distinguish temporary service/image failures from a true catalog miss."""
    return (
        reason in _TRANSIENT_FAILURES or reason == "http_429"
        or (reason.startswith("http_") and reason[5:].isdigit() and int(reason[5:]) >= 500)
    )


class ArtworkLookupError(ValueError):
    """A provider error with a safe, actionable diagnostic reason."""

    def __init__(
        self, reason: str, retry_after: float | None = None,
        *, backoff_applied: bool = False,
    ) -> None:
        self.reason = reason
        self.retry_after = retry_after
        self.backoff_applied = backoff_applied
        super().__init__(_LASTFM_ERROR_MESSAGES.get(reason, "Artwork lookup failed"))


@dataclass
class _CachedLookup:
    expires_at: float
    image: bytes | None
    provider_results: dict[str, str]
    matched_provider: str | None
    matched_query: dict | None = None
    retry_at: float | None = None
    retry_attempted: bool = False


class OnlineArtworkLookup:
    """Find and cache a missing cover or an animated-only artwork upgrade."""

    def __init__(
        self, session: aiohttp.ClientSession, *, animated_only: bool = False,
    ) -> None:
        self._session = session
        # Use a separate instance for upgrades so a static success/miss in one
        # purpose never consumes another purpose's per-song result or retry.
        self._animated_only = bool(animated_only)
        self._providers = ("musicbrainz", "lastfm")
        self._lastfm_api_key = ""
        self._theaudiodb_api_key = ""
        self._cache: OrderedDict[
            tuple[str, str, str, str, str], _CachedLookup
        ] = OrderedDict()
        self._cache_bytes = 0
        self._provider_results: dict[str, str] = {}
        self._matched_provider: str | None = None
        self._matched_query: dict | None = None
        self._lastfm_matched_query: dict[str, str | None] | None = None
        self._from_cache = False
        self._active_key: tuple[str, str, str, str, str] | None = None
        self._lookup_lock = asyncio.Lock()
        self._catalog = CatalogArtworkLookup(
            session, self._async_fetch_image, none_is_miss=self._animated_only,
        )

    def configure(
        self, provider_priority: str, lastfm_api_key: str,
        *, providers: list[str] | tuple[str, ...] | None = None,
        theaudiodb_api_key: str = "",
    ) -> None:
        """Apply live provider settings without retaining obsolete secrets."""
        priority = (
            provider_priority
            if provider_priority in ARTWORK_PROVIDER_PRIORITIES
            else "musicbrainz_first"
        )
        api_key = str(lastfm_api_key or "").strip()
        audiodb_key = str(theaudiodb_api_key or "").strip()
        order = artwork_provider_order(
            {CONF_ARTWORK_PROVIDERS: providers}
            if providers is not None else {CONF_ARTWORK_PROVIDER_PRIORITY: priority}
        )
        if (order, api_key, audiodb_key) != (
            self._providers, self._lastfm_api_key, self._theaudiodb_api_key
        ):
            self.clear_cache()
        self._providers = order
        self._lastfm_api_key = api_key
        self._theaudiodb_api_key = audiodb_key
        self._catalog.configure(audiodb_key)

    def clear_cache(self, *, retry_authentication: bool = False) -> None:
        """Make a manual refresh or configuration change retry online lookups."""
        if retry_authentication:
            self._catalog.clear_authentication_backoff()
        if retry_authentication and (backoff := self._lastfm_backoff()) is not None:
            if backoff[0] in {"invalid_api_key", "suspended_api_key"}:
                fingerprint = hashlib.sha256(self._lastfm_api_key.encode()).hexdigest()
                _LASTFM_BACKOFF.pop(fingerprint, None)
        self._cache.clear()
        self._cache_bytes = 0
        self._provider_results = {}
        self._matched_provider = None
        self._matched_query = None
        self._lastfm_matched_query = None
        self._from_cache = False
        self._active_key = None

    def diagnostics(self) -> dict:
        """Describe the last lookup without URLs, credentials, or API payloads."""
        backoff = self._lastfm_backoff()
        return {
            "purpose": "animated_upgrade" if self._animated_only else "missing_cover",
            "animated_only": self._animated_only,
            "provider_order": list(self._ordered_providers()),
            "lastfm_api_key_configured": bool(self._lastfm_api_key),
            "theaudiodb_personal_key_configured": bool(self._theaudiodb_api_key),
            "matched_provider": self._matched_provider,
            "matched_query": dict(self._matched_query) if self._matched_query else None,
            "from_cache": self._from_cache,
            "provider_results": dict(self._provider_results),
            "lastfm_backoff_reason": backoff[0] if backoff else None,
            "lastfm_retry_after_seconds": (
                max(0, ceil(backoff[1] - time.monotonic()))
                if backoff and isfinite(backoff[1]) else None
            ),
            "catalog_services": self._catalog.diagnostics(),
            "retry_pending": self.next_retry_delay is not None,
            "retry_after_seconds": (
                ceil(self.next_retry_delay) if self.next_retry_delay is not None else None
            ),
        }

    @property
    def next_retry_delay(self) -> float | None:
        """Seconds until this song's single automatic retry, for HA scheduling."""
        cached = self._cache.get(self._active_key) if self._active_key else None
        if cached is None or cached.image is not None or cached.retry_at is None:
            return None
        return max(0.0, cached.retry_at - time.monotonic())

    def release_current_track(self) -> None:
        """Use normal cache expiry again after playback ends."""
        self._active_key = None

    def observe_track(
        self, title: str | None, artist: str | None, album: str | None = None,
    ) -> None:
        """Release an earlier lookup only when the selected track changes.

        Native artwork can be broken and require an online replacement, so its
        presence alone must not unpin this song's completed lookup.
        """
        metadata = tuple(_normalize_metadata(value).casefold() for value in (title, artist, album))
        if self._active_key is not None and self._active_key[:3] != metadata:
            self.release_current_track()

    @property
    def failure_summary(self) -> str | None:
        """Explain failures in service order without exposing request details."""
        if self._matched_provider:
            return None
        providers = self._ordered_providers()
        if not providers:
            return "No artwork services selected in Configure"
        for provider in providers:
            reason = self._provider_results.get(provider)
            if not reason or reason in {"no_match", "found"}:
                continue
            name = _PROVIDER_NAMES[provider]
            if reason == "missing_api_key":
                if len(providers) == 1:
                    return f"{name} needs an API key in Configure"
                continue
            if reason.startswith("http_"):
                return f"{name} request failed (HTTP {reason.removeprefix('http_')})"
            if reason.startswith("api_error_"):
                return f"{name} returned API error {reason.removeprefix('api_error_')}"
            if provider == "lastfm" and reason in _LASTFM_ERROR_MESSAGES:
                return _LASTFM_ERROR_MESSAGES[reason]
            if reason in _CATALOG_FAILURE_MESSAGES:
                return f"{name} {_CATALOG_FAILURE_MESSAGES[reason]}"
        if self._provider_results:
            if self._animated_only:
                return "No matching animated cover found; keeping player artwork"
            if len(providers) == 1:
                return f"{_PROVIDER_NAMES[providers[0]]} returned no cover for this track"
            return "No matching cover found by the selected services"
        return None

    def cached_lookup(
        self, title: str | None, artist: str | None, album: str | None = None,
    ) -> tuple[bool, bytes | None]:
        """Answer from memory only; ``(False, None)`` means a request is needed.

        This lets the coordinator decide without holding its playback lock
        while slow cover services respond. It never starts network requests.
        """
        request = self._lookup_request(title, artist, album)
        if request is None:
            self._record_missing_metadata()
            return True, None
        key = request[-1]
        cached = self._cache.get(key)
        if cached is not None and self._use_cached(key, cached, time.monotonic()):
            return True, cached.image
        return False, None

    async def async_lookup(
        self, title: str | None, artist: str | None, album: str | None = None,
        *, on_request: Callable[[], None] | None = None,
    ) -> bytes | None:
        """Reuse a completed song lookup and serialize simultaneous callers."""
        async with self._lookup_lock:
            return await self._async_lookup(title, artist, album, on_request=on_request)

    def _lookup_request(
        self, title: str | None, artist: str | None, album: str | None,
    ) -> tuple[str, str, str, tuple[str, ...], tuple] | None:
        """Normalize metadata and build the cache key, or None without title/artist."""
        title = _normalize_metadata(title)
        artist = _normalize_metadata(artist)
        album = _normalize_metadata(album)
        if not title or not artist:
            return None
        providers = self._ordered_providers()
        api_key_fingerprint = ":".join(
            hashlib.sha256(secret.encode()).hexdigest()[:16] if secret else ""
            for secret in (self._lastfm_api_key, self._theaudiodb_api_key)
        )
        key = (
            title.casefold(), artist.casefold(), album.casefold(),
            ",".join(providers), api_key_fingerprint,
        )
        return title, artist, album, providers, key

    def _record_missing_metadata(self) -> None:
        self._provider_results = {"lookup": "missing_metadata"}
        self._matched_provider = None
        self._matched_query = None
        self._from_cache = False
        self._active_key = None

    def _use_cached(self, key: tuple, cached: _CachedLookup, now: float) -> bool:
        """Adopt a cached result unless its single retry is due or it expired.

        Keep both success and failure for this playing song, even when a long
        track outlasts the ordinary cache TTL. Position/volume updates must not
        start another lookup. Refresh/settings explicitly reset it.
        """
        retry_due = cached.retry_at is not None and now >= cached.retry_at
        if retry_due or not (key == self._active_key or now < cached.expires_at):
            return False
        self._cache.move_to_end(key)
        self._provider_results = dict(cached.provider_results)
        self._matched_provider = cached.matched_provider
        self._matched_query = cached.matched_query
        self._from_cache = True
        self._active_key = key
        return True

    async def _async_lookup(
        self, title: str | None, artist: str | None, album: str | None = None,
        *, on_request: Callable[[], None] | None = None,
    ) -> bytes | None:
        """Return a bounded cover, trying configured providers in priority order."""
        request = self._lookup_request(title, artist, album)
        if request is None:
            self._record_missing_metadata()
            return None
        title, artist, album, providers, key = request
        now = time.monotonic()
        cached = self._cache.get(key)
        retry_attempted = bool(
            cached and cached.retry_attempted
            and (key == self._active_key or now < cached.expires_at)
        )
        retry_due = False
        if cached is not None:
            retry_due = cached.retry_at is not None and now >= cached.retry_at
            if self._use_cached(key, cached, now):
                return cached.image
            self._cache.pop(key, None)
            if cached.image is not None:
                self._cache_bytes -= len(cached.image)

        provider_results = {}
        matched_provider = None
        matched_query = None
        image = None
        request_announced = False
        request_attempted = False
        for provider in providers:
            if retry_due and cached is not None:
                prior_reason = cached.provider_results.get(provider, "no_match")
                if not _is_transient_failure(prior_reason):
                    provider_results[provider] = prior_reason
                    continue
            if provider == "lastfm" and not self._lastfm_api_key:
                provider_results[provider] = "missing_api_key"
                continue
            if provider == "lastfm" and (backoff := self._lastfm_backoff()) is not None:
                provider_results[provider] = backoff[0]
                continue
            if provider in {"deezer", "theaudiodb"}:
                if blocked := self._catalog.blocked_reason(provider):
                    provider_results[provider] = blocked
                    continue
            if on_request is not None and not request_announced:
                on_request()
                request_announced = True
            request_attempted = True
            try:
                async with asyncio.timeout(_PROVIDER_TIMEOUT_SECONDS):
                    attempted_release_queries: set[tuple[str, str, bool]] = set()
                    for query_title, query_artist, query_album in lookup_metadata_variants(title, artist, album):
                        if provider == "lastfm":
                            self._lastfm_matched_query = None
                            image = await self._async_lastfm_cover(query_title, query_artist, query_album)
                        elif provider in {"deezer", "theaudiodb"}:
                            image = await self._catalog.async_cover(provider, query_title, query_artist, query_album)
                        else:
                            release_query = (query_album or query_title, query_artist, bool(query_album))
                            if release_query in attempted_release_queries:
                                continue
                            attempted_release_queries.add(release_query)
                            image = await self._async_musicbrainz_cover(
                                query_album or query_title, query_artist,
                                **({"track_title": query_title} if not query_album else {}),
                            )
                        if image:
                            lastfm_query = (
                                self._lastfm_matched_query if provider == "lastfm" else None
                            )
                            matched_title = lastfm_query["title"] if lastfm_query else query_title
                            matched_artist = lastfm_query["artist"] if lastfm_query else query_artist
                            matched_album = lastfm_query["album"] if lastfm_query else query_album or None
                            matched_query = {
                                "title": matched_title, "artist": matched_artist,
                                "album": matched_album,
                                "used_metadata_fallback": (
                                    matched_title, matched_artist, matched_album or "",
                                ) != (title, artist, album),
                            }
                            break
            except CatalogLookupError as err:
                provider_results[provider] = err.reason
                _LOGGER.debug("%s artwork lookup failed: %s", provider, err)
                continue
            except ArtworkLookupError as err:
                provider_results[provider] = err.reason
                if provider == "lastfm":
                    self._remember_lastfm_failure(err)
                _LOGGER.debug("%s artwork lookup failed: %s", provider, err)
                continue
            except aiohttp.ClientResponseError as err:
                provider_results[provider] = f"http_{err.status}"
                _LOGGER.debug("%s artwork lookup failed with HTTP %s", provider, err.status)
                continue
            except asyncio.TimeoutError:
                provider_results[provider] = "timeout"
                if provider == "lastfm":
                    self._remember_lastfm_failure(ArtworkLookupError("timeout", 60))
                elif provider in {"deezer", "theaudiodb"}:
                    self._catalog.remember_timeout(provider)
                continue
            except aiohttp.ClientConnectorCertificateError:
                provider_results[provider] = "tls_error"
                continue
            except aiohttp.ClientConnectionError:
                provider_results[provider] = "connection_failed"
                continue
            except (aiohttp.ClientError, ValueError, OSError) as err:
                _LOGGER.debug("%s artwork lookup failed: %s", provider, safe_error_text(err))
                provider_results[provider] = "request_failed"
                continue
            provider_results[provider] = "found" if image else "no_match"
            if image:
                matched_provider = provider
                break

        self._provider_results = provider_results
        self._matched_provider = matched_provider
        self._matched_query = matched_query
        self._from_cache = False
        self._active_key = key
        # Revisited songs can retry an expired miss; the current song remains pinned.
        ttl = _LOOKUP_CACHE_TTL if image else _LOOKUP_FAILURE_TTL
        retry_attempted = retry_attempted or (retry_due and request_attempted)
        retry_at = None
        if image is None and not retry_attempted:
            deadlines = []
            for provider, reason in provider_results.items():
                if not _is_transient_failure(reason):
                    continue
                backoff = self._lastfm_backoff() if provider == "lastfm" else None
                deadline = (
                    backoff[1] if backoff else self._catalog.retry_deadline(provider)
                )
                deadlines.append(deadline or time.monotonic() + 60.0)
            if deadlines:
                retry_at = max(deadlines)
        previous = self._cache.pop(key, None)
        if previous is not None and previous.image is not None:
            self._cache_bytes -= len(previous.image)
        if image is None or len(image) <= MAX_CACHED_IMAGE_BYTES:
            self._cache[key] = _CachedLookup(
                time.monotonic() + ttl, image, dict(provider_results), matched_provider,
                matched_query,
                retry_at, retry_attempted,
            )
            if image is not None:
                self._cache_bytes += len(image)
            self._cache.move_to_end(key)
        while self._cache and (
            len(self._cache) > _MAX_CACHE_ENTRIES
            or self._cache_bytes > MAX_CACHED_IMAGE_BYTES
        ):
            _, oldest = self._cache.popitem(last=False)
            if oldest.image is not None:
                self._cache_bytes -= len(oldest.image)
        return image

    def _lastfm_backoff(self) -> tuple[str, float] | None:
        """Return an active key-wide cooldown, shared by all integration entries."""
        fingerprint = hashlib.sha256(self._lastfm_api_key.encode()).hexdigest()
        state = _LASTFM_BACKOFF.get(fingerprint)
        if state is not None and time.monotonic() < state[1]:
            _LASTFM_BACKOFF.move_to_end(fingerprint)
            return state
        _LASTFM_BACKOFF.pop(fingerprint, None)
        return None

    def _remember_lastfm_failure(self, error: ArtworkLookupError) -> None:
        """Stop invalid keys and rate/service failures from querying on every song."""
        if error.backoff_applied:
            return
        if error.reason in {"invalid_api_key", "suspended_api_key"}:
            retry_at = float("inf")
        elif error.reason in {"rate_limited", "service_unavailable", "timeout"}:
            seconds = error.retry_after or 60.0
            retry_at = time.monotonic() + (max(1.0, seconds) if isfinite(seconds) else 60.0)
        else:
            return
        current = self._lastfm_backoff()
        if current is not None and current[1] > retry_at:
            error.backoff_applied = True
            return
        fingerprint = hashlib.sha256(self._lastfm_api_key.encode()).hexdigest()
        _LASTFM_BACKOFF[fingerprint] = (error.reason, retry_at)
        error.backoff_applied = True
        _LASTFM_BACKOFF.move_to_end(fingerprint)
        while len(_LASTFM_BACKOFF) > _MAX_CACHE_ENTRIES:
            _LASTFM_BACKOFF.popitem(last=False)

    @staticmethod
    def _retry_after_seconds(headers) -> float:
        """Honor Retry-After as seconds or an HTTP date, with a safe default."""
        value = str(headers.get("Retry-After", ""))
        try:
            seconds = float(value)
            if isfinite(seconds):
                return max(1.0, seconds)
        except ValueError:
            pass
        try:
            seconds = parsedate_to_datetime(value).timestamp() - time.time()
            if isfinite(seconds):
                return max(1.0, seconds)
        except (TypeError, ValueError, OverflowError):
            pass
        return 60.0

    def _ordered_providers(self) -> tuple[str, ...]:
        """Return the selected services in priority order."""
        return self._providers

    async def _async_musicbrainz_cover(
        self, release_name: str, artist: str, *, track_title: str | None = None,
    ) -> bytes | None:
        """Try release covers, then resolve albumless songs through recordings."""
        matches = await self._async_find_releases(release_name, artist)
        attempted_releases: set[str] = set()
        attempted_groups: set[str] = set()
        last_error: Exception | None = None

        async def fetch_matches(releases: list[tuple[str, str | None]]) -> bytes | None:
            nonlocal last_error
            for release_id, release_group_id in releases:
                if release_id in attempted_releases:
                    continue
                if len(attempted_releases) >= 3:
                    break
                attempted_releases.add(release_id)
                candidates = [("release", release_id)]
                if release_group_id and release_group_id not in attempted_groups:
                    attempted_groups.add(release_group_id)
                    candidates.append(("release-group", release_group_id))
                for entity_type, mbid in candidates:
                    try:
                        image = await self._async_fetch_cover(entity_type, mbid)
                    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, OSError) as err:
                        last_error = err
                        continue
                    if image is not None:
                        return image
            return None

        # With no album, a title-named release is only the first lead. Reserve
        # room in the three-release budget for the recording's actual album.
        image = await fetch_matches(matches[:1] if track_title else matches)
        if image is not None:
            return image
        if track_title and len(attempted_releases) < 3:
            recording_releases = await self._async_find_recording_releases(track_title, artist)
            image = await fetch_matches(recording_releases)
            if image is not None:
                return image
            image = await fetch_matches(matches[1:])
            if image is not None:
                return image
        if last_error is not None:
            raise last_error
        return None

    async def _async_find_recording_releases(
        self, title: str, artist: str,
    ) -> list[tuple[str, str | None]]:
        """Resolve a song to releases only when both title and credit match."""
        escaped_title = _LUCENE_SPECIAL.sub(r"\\\1", title)
        escaped_artist = _LUCENE_SPECIAL.sub(r"\\\1", artist)
        result = await self._async_musicbrainz_search(
            "recording", f'recording:"{escaped_title}" AND artist:"{escaped_artist}"'
        )
        recordings = result.get("recordings", []) if isinstance(result, dict) else []

        def match_key(value: object) -> str:
            plain = unicodedata.normalize("NFKC", str(value or "")).casefold()
            return "".join(character for character in plain if character.isalnum())

        matches: list[tuple[str, str | None]] = []
        seen_releases: set[str] = set()
        strong_recordings = 0
        for recording in recordings if isinstance(recordings, list) else []:
            if not isinstance(recording, dict):
                continue
            try:
                score = int(recording.get("score", 0))
            except (TypeError, ValueError):
                continue
            credits = recording.get("artist-credit") or []
            if not isinstance(credits, list):
                continue
            names = []
            combined = []
            for credit in credits:
                if not isinstance(credit, dict):
                    continue
                artist_data = credit.get("artist") or {}
                name = credit.get("name") or (
                    artist_data.get("name") if isinstance(artist_data, dict) else ""
                )
                names.append(match_key(name))
                combined.append(str(name or "") + str(credit.get("joinphrase") or ""))
            if (
                score < 90 or match_key(recording.get("title")) != match_key(title)
                or match_key(artist) not in {*names, match_key("".join(combined))}
            ):
                continue
            strong_recordings += 1
            releases = recording.get("releases") or []
            for release in releases if isinstance(releases, list) else []:
                if not isinstance(release, dict):
                    continue
                release_id = str(release.get("id") or "")
                if not _MBID.fullmatch(release_id) or release_id in seen_releases:
                    continue
                group = release.get("release-group") or {}
                group_id = str(group.get("id") or "") if isinstance(group, dict) else ""
                seen_releases.add(release_id)
                matches.append((release_id, group_id if _MBID.fullmatch(group_id) else None))
                if len(matches) >= 3:
                    return matches
            if strong_recordings >= 3:
                break
        return matches

    async def _async_find_release(
        self, release_name: str, artist: str
    ) -> tuple[str, str | None] | None:
        """Return the strongest release for callers needing one result."""
        matches = await self._async_find_releases(release_name, artist)
        return matches[0] if matches else None

    async def _async_find_releases(
        self, release_name: str, artist: str,
    ) -> list[tuple[str, str | None]]:
        """Keep up to three strong pressings; the first may have no artwork."""
        escaped_release = _LUCENE_SPECIAL.sub(r"\\\1", release_name)
        escaped_artist = _LUCENE_SPECIAL.sub(r"\\\1", artist)
        query = f'release:"{escaped_release}" AND artist:"{escaped_artist}"'

        result = await self._async_musicbrainz_search("release", query)

        releases = result.get("releases", []) if isinstance(result, dict) else []
        matches = []
        seen_releases: set[str] = set()
        for release in releases:
            if not isinstance(release, dict):
                continue
            try:
                score = int(release.get("score", 0))
            except (TypeError, ValueError):
                score = 0
            release_id = str(release.get("id", ""))
            if score >= 90 and _MBID.fullmatch(release_id) and release_id not in seen_releases:
                release_group = release.get("release-group")
                group_id = (
                    str(release_group.get("id", ""))
                    if isinstance(release_group, dict) else ""
                )
                seen_releases.add(release_id)
                matches.append((release_id, group_id if _MBID.fullmatch(group_id) else None))
                if len(matches) >= 3:
                    break
        return matches

    async def _async_musicbrainz_search(self, entity_type: str, query: str) -> dict:
        """Share MusicBrainz's request gate between release and recording searches."""
        global _LAST_MB_REQUEST
        async with _MB_LOCK:
            delay = _MB_REQUEST_INTERVAL - (time.monotonic() - _LAST_MB_REQUEST)
            if delay > 0:
                await asyncio.sleep(delay)
            _LAST_MB_REQUEST = time.monotonic()
            async with self._session.get(
                f"https://musicbrainz.org/ws/2/{entity_type}/",
                params={"query": query, "fmt": "json", "limit": 5},
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                timeout=aiohttp.ClientTimeout(total=12),
            ) as response:
                response.raise_for_status()
                result = await response.json(content_type=None)
        return result if isinstance(result, dict) else {}

    async def _async_lastfm_cover(
        self, title: str, artist: str, album: str
    ) -> bytes | None:
        """Try exact credits first, with bounded retries for collaboration credits."""
        self._lastfm_matched_query = None
        primary_artist = _ARTIST_SEPARATOR.split(artist, maxsplit=1)[0].strip()
        artists = list(dict.fromkeys(item for item in (artist, primary_artist) if item))
        plain_title = _FEATURE_CREDIT.sub("", title).strip()
        titles = list(dict.fromkeys(item for item in (title, plain_title) if item))
        attempted_images: set[str] = set()
        image_failed = False
        # At most two artist credits and three queries per artist. Preserve mix,
        # live and remaster titles; only a trailing featured-artist credit is removed.
        for credited_artist in artists:
            queries = []
            if album:
                queries.append(("album.getInfo", {"artist": credited_artist, "album": album}))
            queries.extend(
                ("track.getInfo", {"artist": credited_artist, "track": track_title})
                for track_title in titles
            )
            for method, params in queries:
                image_urls = (
                    await self._async_lastfm_image_urls(method, params)
                    if self._animated_only else [await self._async_lastfm_image_url(method, params)]
                )
                for image_url in image_urls:
                    if not image_url or image_url in attempted_images:
                        continue
                    attempted_images.add(image_url)
                    try:
                        image = await self._async_fetch_image(image_url, self._is_trusted_lastfm_host)
                    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, OSError):
                        # A stale album image should not prevent a valid track image.
                        image_failed = True
                        continue
                    if image:
                        self._lastfm_matched_query = {
                            "title": params.get("track", title),
                            "artist": credited_artist,
                            "album": album or None,
                        }
                        return image
                    # Static covers are expected during an animation search.
                    # Continue other API images/track queries without turning a
                    # completed animation miss into a transient download error.
                    if not self._animated_only:
                        image_failed = True
        if image_failed:
            raise ArtworkLookupError("image_download_failed")
        return None

    async def _async_lastfm_image_url(self, method: str, params: dict) -> str | None:
        """Return the best image, preserving ordinary missing-cover behavior."""
        image_urls = await self._async_lastfm_image_urls(method, params)
        return image_urls[0] if image_urls else None

    async def _async_lastfm_image_urls(self, method: str, params: dict) -> list[str]:
        """Pace API requests across entries and recheck shared rate-limit backoff."""
        global _LAST_LASTFM_REQUEST
        async with _LASTFM_LOCK:
            if (backoff := self._lastfm_backoff()) is not None:
                raise ArtworkLookupError(backoff[0], backoff_applied=True)
            delay = _LASTFM_REQUEST_INTERVAL - (time.monotonic() - _LAST_LASTFM_REQUEST)
            if delay > 0:
                await asyncio.sleep(delay)
            _LAST_LASTFM_REQUEST = time.monotonic()
            try:
                return await self._async_request_lastfm_image_urls(method, params)
            except ArtworkLookupError as err:
                self._remember_lastfm_failure(err)
                raise

    async def _async_request_lastfm_image_url(self, method: str, params: dict) -> str | None:
        """Return the best non-placeholder image for existing direct callers."""
        image_urls = await self._async_request_lastfm_image_urls(method, params)
        return image_urls[0] if image_urls else None

    async def _async_request_lastfm_image_urls(self, method: str, params: dict) -> list[str]:
        """Keep bounded image alternatives; a smaller rendition may be animated."""
        payload = {
            "method": method,
            **params,
            "api_key": self._lastfm_api_key,
            "format": "json",
            "autocorrect": "1",
        }
        async with self._session.get(
            _LASTFM_ENDPOINT,
            params=payload,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=aiohttp.ClientTimeout(total=12),
        ) as response:
            if response.status == 429:
                raise ArtworkLookupError("rate_limited", self._retry_after_seconds(response.headers))
            if response.status >= 500:
                raise ArtworkLookupError("service_unavailable", self._retry_after_seconds(response.headers))
            try:
                result = await response.json(content_type=None)
            except ValueError as err:
                response.raise_for_status()
                raise ArtworkLookupError("api_error") from err
            if isinstance(result, dict) and result.get("error"):
                try:
                    error_code = int(result["error"])
                except (TypeError, ValueError):
                    error_code = 0
                if error_code != 6:  # Last.fm uses 6 for a normal "not found" result.
                    raise ArtworkLookupError(
                        _LASTFM_ERROR_REASONS.get(error_code, f"api_error_{error_code}"),
                        self._retry_after_seconds(response.headers),
                    )
                return []
            response.raise_for_status()
        if not isinstance(result, dict):
            raise ArtworkLookupError("api_error")
        root_key = "album" if method == "album.getInfo" else "track"
        root = result.get(root_key)
        if not isinstance(root, dict):
            raise ArtworkLookupError("api_error")
        album_data = root.get("album") if root_key == "track" else root
        if not isinstance(album_data, dict):
            return []
        images = album_data.get("image") or root.get("image") or []
        if isinstance(images, dict):
            images = [images]
        if not isinstance(images, list):
            return []
        unsupported_host = False
        image_urls: list[str] = []
        for entry in reversed(images):
            if not isinstance(entry, dict):
                continue
            image_url = str(entry.get("#text") or entry.get("url") or "").strip()
            parsed = urlsplit(image_url)
            if (
                image_url and _LASTFM_PLACEHOLDER not in image_url.casefold()
                and parsed.scheme in {"http", "https"} and parsed.hostname
            ):
                if self._is_trusted_lastfm_host(parsed.hostname):
                    if image_url not in image_urls:
                        image_urls.append(image_url)
                        if len(image_urls) >= 6:
                            break
                else:
                    unsupported_host = True
        if unsupported_host and not image_urls:
            raise ArtworkLookupError("unsupported_image_host")
        return image_urls

    @staticmethod
    def _is_trusted_lastfm_host(host: str) -> bool:
        """Limit Last.fm image downloads and redirects to its known image hosts."""
        host = host.casefold().rstrip(".")
        return (
            host in {"lastfm.freetls.fastly.net", "lastfm-img.freetls.fastly.net"}
            or host == "userserve-ak.last.fm"
            or host.endswith(".last.fm")
            or host in {"lastfm-img2.akamaized.net", "lastfm-img3.akamaized.net"}
        )

    async def _async_fetch_cover(self, entity_type: str, mbid: str) -> bytes | None:
        """Fetch a release or release-group front cover from the archive."""
        cover_url = f"https://coverartarchive.org/{entity_type}/{quote(mbid)}/front"
        return await self._async_fetch_image(cover_url, self._is_trusted_archive_host)

    async def _async_fetch_image(
        self, image_url: str, trusted_host: Callable[[str], bool]
    ) -> bytes | None:
        """Download a bounded image, validating each redirect before following it."""
        for redirect_count in range(6):
            parsed = urlsplit(image_url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError("Artwork lookup returned an invalid image URL")
            if (
                not trusted_host(parsed.hostname)
                or parsed.username is not None or parsed.password is not None
                or parsed.port not in {None, 80, 443}
            ):
                raise ValueError("Artwork lookup returned an untrusted image URL")
            # Legacy API results sometimes contain HTTP CDN URLs.
            if parsed.scheme == "http":
                image_url = urlunsplit(("https", parsed.netloc, parsed.path, parsed.query, ""))
            async with self._session.get(
                image_url,
                headers={"User-Agent": USER_AGENT, "Accept": "image/*"},
                timeout=aiohttp.ClientTimeout(total=15),
                allow_redirects=False,
            ) as response:
                if response.status in {301, 302, 303, 307, 308}:
                    location = response.headers.get("Location")
                    if not location or redirect_count == 5:
                        raise ValueError("Artwork lookup returned too many or invalid redirects")
                    image_url = urljoin(image_url, location)
                    continue
                if response.status == 404:
                    return None
                response.raise_for_status()
                final_host = (response.url.host or "").casefold()
                if not trusted_host(final_host):
                    raise ValueError("Artwork lookup redirected to an untrusted host")
                if not response.headers.get("Content-Type", "").casefold().startswith("image/"):
                    raise ValueError("Artwork lookup did not return an image")
                data = await read_bounded_image(response)
            animated = await asyncio.to_thread(validate_image_animation, data)
            if self._animated_only and not animated:
                return None
            return data
        return None

    @staticmethod
    def _is_trusted_archive_host(host: str) -> bool:
        """Accept the Cover Art Archive and its archive.org image CDN."""
        host = host.casefold().rstrip(".")
        return host == "coverartarchive.org" or host.endswith(".archive.org")
