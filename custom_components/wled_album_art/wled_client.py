"""Small asynchronous client for the WLED JSON and filesystem APIs."""
from __future__ import annotations

import asyncio
import logging
import json
from collections.abc import Callable
from pathlib import PurePosixPath
from urllib.parse import urljoin

import aiohttp

from .const import (
    IMAGE_EFFECT_NAME,
    SOLID_EFFECT_NAME,
    TRANSITION_BLEND_STYLES,
)

_LOGGER = logging.getLogger(__name__)


class WLEDClient:
    """Encapsulate WLED HTTP requests, file upload, effects, and state restore."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        pin: str,
        segment_id: int,
        filename_prefix: str,
        *,
        url_resolver: Callable[[], str] | None = None,
    ) -> None:
        self._session = session
        self.base_url = base_url.rstrip("/") + "/"
        # Re-read the address before each request, so a WLED that moved to a
        # new IP (followed by Home Assistant's WLED integration) keeps working.
        self._url_resolver = url_resolver
        self.pin = str(pin or "")
        self.segment_id = int(segment_id)
        self.filename_prefix = filename_prefix
        self._effect_names: list[str] | None = None
        self._effect_ids: dict[str, int] = {}

    async def async_get_state(self) -> dict:
        """Fetch current device state."""
        async with self._session.get(
            self._url("json/state"), timeout=aiohttp.ClientTimeout(total=6)
        ) as response:
            response.raise_for_status()
            data = await response.json(content_type=None)
        return data if isinstance(data, dict) else {}

    async def async_get_info(self) -> dict:
        """Fetch WLED device/matrix information."""
        async with self._session.get(
            self._url("json/info"), timeout=aiohttp.ClientTimeout(total=6)
        ) as response:
            response.raise_for_status()
            data = await response.json(content_type=None)
        return data if isinstance(data, dict) else {}

    async def async_get_effect_names(self, refresh: bool = False) -> list[str]:
        """Return effect names in firmware order, which is also each effect's ID."""
        if self._effect_names is not None and not refresh:
            return list(self._effect_names)
        async with self._session.get(
            self._url("json/eff"), timeout=aiohttp.ClientTimeout(total=6)
        ) as response:
            response.raise_for_status()
            data = await response.json(content_type=None)
        if not isinstance(data, list):
            raise RuntimeError("WLED returned an invalid effect list")
        names: list[str] = []
        for item in data:
            name = item[0] if isinstance(item, (list, tuple)) and item else item
            names.append(str(name).strip())
        self._effect_names = names
        self._effect_ids = {name.casefold(): index for index, name in enumerate(names)}
        return list(names)

    async def async_get_effect_id(self, name: str) -> int:
        """Resolve a device-specific effect ID by name."""
        await self.async_get_effect_names()
        effect_id = self._effect_ids.get(name.casefold())
        if effect_id is None:
            # Effect IDs can differ between devices/builds, so refresh once before failing.
            await self.async_get_effect_names(refresh=True)
            effect_id = self._effect_ids.get(name.casefold())
        if effect_id is None:
            raise RuntimeError(f"The WLED effects list did not contain {name!r}.")
        return effect_id

    async def async_unlock_if_needed(self) -> None:
        """Submit WLED's configuration PIN before a filesystem upload if required."""
        if not self.pin:
            return
        await self.async_post_state({"pin": self.pin})

    async def async_upload_gif(self, data: bytes, filename: str) -> None:
        """Upload the prepared static or animated GIF to WLED's filesystem."""
        safe_name = PurePosixPath(filename).name
        form = aiohttp.FormData()
        form.add_field("data", data, filename=safe_name, content_type="image/gif")
        async with self._session.post(
            self._url("upload"), data=form, timeout=aiohttp.ClientTimeout(total=12)
        ) as response:
            body = await response.text()
            if response.status >= 400:
                if response.status == 401:
                    raise RuntimeError(
                        "WLED rejected the upload. Check the WLED PIN and network access."
                    )
                raise RuntimeError(f"WLED upload failed ({response.status}): {body[:500]}")
            # WLED builds vary slightly in their successful response body. Treat an
            # explicit API failure as an error but don't require a specific success
            # phrase, which has changed between firmware versions.
            try:
                result = json.loads(body) if body else None
            except ValueError:
                result = None
            if isinstance(result, dict) and (
                result.get("success") is False or result.get("error")
            ):
                raise RuntimeError(f"WLED rejected the image upload: {result}")
            if body and "error" in body.casefold() and not (
                isinstance(result, dict) and result.get("success") is True
            ):
                _LOGGER.debug("Unrecognized WLED upload response for %s: %s", safe_name, body[:500])

    async def async_post_state(self, payload: dict) -> None:
        """POST a partial state update without mutating the caller's dictionary."""
        state = dict(payload)
        if self.pin:
            state["pin"] = self.pin
        async with self._session.post(
            self._url("json/state"), json=state,
            timeout=aiohttp.ClientTimeout(total=6),
        ) as response:
            response.raise_for_status()
            try:
                result = await response.json(content_type=None)
            except (aiohttp.ContentTypeError, ValueError):
                result = None
        if isinstance(result, dict) and result.get("error"):
            raise RuntimeError(f"WLED JSON API returned an error: {result['error']}")

    async def async_activate_image(
        self, filename: str, transition_style: str, transition_seconds: float,
        *, brightness: int | None = None,
    ) -> None:
        """Activate a cover with one native WLED 16 state update.

        Unlike generated intermediate GIFs, WLED's native transition blending
        doesn't require uploading/activating a second animation for each change.
        That reduces filesystem churn and avoids quantization artifacts in the
        transition animation itself.
        """
        image_id = await self.async_get_effect_id(IMAGE_EFFECT_NAME)
        payload = {"on": True, "seg": [{
            "id": self.segment_id,
            "fx": image_id,
            "frz": False,
            "sx": 128,
            "ix": 0,
            "n": PurePosixPath(filename).name,
        }]}
        if transition_style == "instant":
            payload["tt"] = 0
        else:
            blend_style = TRANSITION_BLEND_STYLES.get(transition_style)
            if blend_style is None:
                raise ValueError(f"Unsupported native WLED transition: {transition_style}")
            payload["bs"] = blend_style
            payload["tt"] = max(0, int(round(transition_seconds * 10)))
        if brightness is not None:
            payload["bri"] = max(0, min(255, int(brightness)))
        await self.async_post_state(payload)

    async def async_activate_solid_black(self, duration_seconds: float) -> None:
        """Fade the selected segment to black using a native WLED transition."""
        await self.async_activate_solid_color([0, 0, 0], duration_seconds)

    async def async_activate_solid_color(
        self, color: list[int], duration_seconds: float, *, brightness: int | None = None
    ) -> None:
        """Fade the selected segment to a solid RGB color."""
        if len(color) != 3 or any(not 0 <= int(channel) <= 255 for channel in color):
            raise ValueError("A solid RGB color must contain three values from 0 to 255")
        solid_id = await self.async_get_effect_id(SOLID_EFFECT_NAME)
        payload = {
            "on": True,
            "bs": TRANSITION_BLEND_STYLES["fade"],
            "tt": max(0, int(round(duration_seconds * 10))),
            "seg": [{
                "id": self.segment_id,
                "fx": solid_id,
                "col": [list(color), [0, 0, 0], [0, 0, 0]],
                "frz": False,
                "sx": 128,
                "ix": 0,
                "n": "",
            }],
        }
        if brightness is not None:
            payload["bri"] = max(1, min(255, int(brightness)))
        await self.async_post_state(payload)

    async def async_cleanup_old_images(
        self, active_filename: str, preserve_filenames: list[str] | None = None
    ) -> None:
        """Delete old managed GIFs but retain files needed to restore saved state."""
        try:
            async with self._session.get(
                self._url("edit"), params={"func": "list", "path": "/"},
                timeout=aiohttp.ClientTimeout(total=5),
            ) as response:
                response.raise_for_status()
                entries = await response.json(content_type=None)
            if isinstance(entries, dict):
                entries = entries.get("files", entries.get("list", []))
            if not isinstance(entries, list):
                return
            managed_prefix = self.filename_prefix + "_"
            preserved = {PurePosixPath(str(name)).name for name in (preserve_filenames or []) if name}
            for item in entries:
                raw_name = item.get("name", "") if isinstance(item, dict) else ""
                name = PurePosixPath(str(raw_name)).name
                if (
                    name.lower().endswith(".gif")
                    and name.startswith(managed_prefix)
                    and name != active_filename
                    and name not in preserved
                ):
                    async with self._session.get(
                        self._url("edit"), params={"func": "delete", "path": "/" + name},
                        timeout=aiohttp.ClientTimeout(total=5),
                    ) as response:
                        if response.status >= 400:
                            _LOGGER.debug(
                                "Could not remove old WLED image %s (%s)", name, response.status
                            )
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
            _LOGGER.debug("Best-effort WLED GIF cleanup failed: %s", err)

    def _url(self, path: str) -> str:
        if self._url_resolver is not None:
            try:
                current = self._url_resolver().rstrip("/") + "/"
            except (ValueError, KeyError):
                current = self.base_url  # Keep the last known address.
            if current != self.base_url:
                _LOGGER.info("WLED address changed from %s to %s", self.base_url, current)
                self.base_url = current
        return urljoin(self.base_url, path)
