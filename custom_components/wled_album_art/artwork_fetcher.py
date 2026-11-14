"""Download and briefly cache media-player artwork."""
from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from urllib.parse import urljoin

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.network import get_url

from .const import IMAGE_CACHE_TTL_SECONDS, MAX_CACHED_IMAGE_BYTES
from .error_utils import safe_error_text
from .image_download import read_bounded_image, validate_image

_LOGGER = logging.getLogger(__name__)


class ArtworkFetcher:
    """Fetch artwork while bounding request size and in-memory caching."""

    def __init__(self, hass: HomeAssistant, session: aiohttp.ClientSession) -> None:
        self._hass = hass
        self._session = session
        self._cache: OrderedDict[str, tuple[float, bytes]] = OrderedDict()
        self._cache_bytes = 0

    def clear_cache(self) -> None:
        """Let an explicit refresh re-download artwork at an unchanged URL."""
        self._cache.clear()
        self._cache_bytes = 0

    async def async_fetch(self, image_url: str) -> bytes:
        """Fetch artwork with a short TTL cache for repeated proxy URLs."""
        image_url = self._resolve_url(image_url)
        now = time.monotonic()
        cached = self._cache.get(image_url)
        if cached is not None:
            cached_at, cached_bytes = cached
            if now - cached_at <= IMAGE_CACHE_TTL_SECONDS:
                self._cache.move_to_end(image_url)
                return cached_bytes
            self._cache_bytes -= len(cached_bytes)
            self._cache.pop(image_url, None)

        async with self._session.get(
            image_url, timeout=aiohttp.ClientTimeout(total=20)
        ) as response:
            response.raise_for_status()
            data = await read_bounded_image(response)
        # A successful HTTP response can still be HTML, truncated, or corrupt.
        # Validate before caching so the next native URL or service can be tried.
        await self._hass.async_add_executor_job(validate_image, data)

        # Retain only recent, bounded responses for players that reuse proxy URLs.
        if len(data) <= MAX_CACHED_IMAGE_BYTES:
            previous = self._cache.pop(image_url, None)
            if previous is not None:
                self._cache_bytes -= len(previous[1])
            self._cache[image_url] = (time.monotonic(), data)
            self._cache_bytes += len(data)
            while self._cache and self._cache_bytes > MAX_CACHED_IMAGE_BYTES:
                _, (_, oldest_bytes) = self._cache.popitem(last=False)
                self._cache_bytes -= len(oldest_bytes)
        return data

    async def async_fetch_candidates(self, image_urls: tuple[str, ...]) -> bytes:
        """Try each artwork URL so a stale local proxy cannot hide a valid cover."""
        last_error: Exception | None = None
        for image_url in image_urls:
            try:
                return await self.async_fetch(image_url)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, OSError) as err:
                last_error = err
                _LOGGER.debug("Artwork URL candidate failed: %s", safe_error_text(err))
        if last_error is not None:
            raise last_error
        raise ValueError("Media player did not provide an artwork URL")

    def _resolve_url(self, image_url: str) -> str:
        """Resolve relative Home Assistant artwork URLs to an absolute URL."""
        if image_url.startswith("//"):
            return urljoin(self._base_url(), image_url)
        if not image_url.startswith("/"):
            return image_url

        base = self._base_url()
        return urljoin(base.rstrip("/") + "/", image_url.lstrip("/"))

    def _base_url(self) -> str:
        """Use HA's reachable internal URL, with a safe local fallback."""
        try:
            return (
                get_url(self._hass, prefer_external=False, allow_internal=True)
                or self._hass.config.internal_url
                or "http://homeassistant.local:8123"
            )
        except Exception:  # noqa: BLE001 - support installs without a configured URL
            return self._hass.config.internal_url or "http://homeassistant.local:8123"
