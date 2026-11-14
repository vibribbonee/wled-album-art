"""Downloadable diagnostics for Music Artwork Lighting."""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers.redact import async_redact_data

from .const import CONF_LASTFM_API_KEY, CONF_THEAUDIODB_API_KEY, CONF_PIN, DOMAIN

TO_REDACT = {CONF_LASTFM_API_KEY, CONF_THEAUDIODB_API_KEY, CONF_PIN, CONF_HOST}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return sanitized configuration and runtime information without artwork URLs."""
    manager = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    return {
        "entry_data": async_redact_data(dict(entry.data), TO_REDACT),
        "entry_options": async_redact_data(dict(entry.options), TO_REDACT),
        "runtime": manager.status_attributes() if manager else {"status": "not_loaded"},
        "status": manager.status if manager else "not_loaded",
    }
