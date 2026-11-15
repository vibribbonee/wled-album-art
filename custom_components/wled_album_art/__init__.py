"""Home Assistant setup for Music Artwork Lighting."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from .const import CONF_SOURCE_ENTITY, CONF_TARGET_ENTITIES, CONF_TARGET_ENTITY, DOMAIN
from .manager import AlbumArtManager
from .selection import normalize_entity_list

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
PLATFORMS = ["button", "image", "light", "sensor", "switch", "select", "number"]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up integration (configuration is managed through config entries)."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Create and start the playback coordinator."""
    # Rename entries created by older releases without changing their entity IDs
    # or the internal wled_album_art domain.
    old_title = entry.title
    target = entry.options.get(CONF_TARGET_ENTITY, entry.data.get(CONF_TARGET_ENTITY, "")) or ""
    if old_title.startswith("Album art → ") or old_title.startswith("Album colors → "):
        source_entities = normalize_entity_list(entry.options.get("source_entities"))
        if not source_entities:
            source_entities = [entry.data.get(CONF_SOURCE_ENTITY) or "source"]
        if target:
            new_title = f"Music artwork → {target}"
        else:
            new_title = f"Music lighting → {source_entities[0]}"
    else:
        new_title = old_title
    if new_title != old_title:
        hass.config_entries.async_update_entry(entry, title=new_title)

    manager = AlbumArtManager(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = manager
    try:
        await manager.async_start()
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        # Do not leave the manager, listeners, or partially forwarded platforms
        # behind when setup fails. Preserve the original exception for Home Assistant.
        try:
            await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Platform cleanup after setup failure also failed", exc_info=True)
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        try:
            await manager.async_stop()
        except Exception:  # noqa: BLE001 - preserve the original setup exception
            _LOGGER.debug("Manager cleanup after setup failure also failed", exc_info=True)
        raise
    entry.async_on_unload(entry.add_update_listener(async_update_listener))
    return True


async def async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Apply dashboard-tunable options live; reload for structural options."""
    manager = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if manager is not None and await manager.async_apply_live_options():
        return
    await async_reload_entry(hass, entry)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload platforms, listeners, and best-effort restore a running session."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False
    manager = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if manager:
        await manager.async_stop()
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload when integration options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate multi-matrix entries back to one matrix per entry.

    Older releases allowed multiple displays in one entry. From v0.14 each entry
    represents one display (or no display for theme-light-only operation), which
    allows fully independent settings and state recovery for each matrix.
    """
    if entry.version > 2:
        return False

    data = dict(entry.data)
    options = dict(entry.options)

    if CONF_TARGET_ENTITIES in data:
        data_targets = normalize_entity_list(data.pop(CONF_TARGET_ENTITIES))
        if data_targets:
            data[CONF_TARGET_ENTITY] = data_targets[0]
        else:
            data[CONF_TARGET_ENTITY] = ""

    if CONF_TARGET_ENTITIES in options:
        option_targets = normalize_entity_list(options.pop(CONF_TARGET_ENTITIES))
        options[CONF_TARGET_ENTITY] = option_targets[0] if option_targets else ""
    elif CONF_TARGET_ENTITY in options:
        normalized_target = normalize_entity_list(options.get(CONF_TARGET_ENTITY))
        options[CONF_TARGET_ENTITY] = normalized_target[0] if normalized_target else ""

    # The optional target selector replaces the old enable/disable checkbox.
    # A previously disabled matrix becomes theme-only until it is reselected.
    if options.get("enable_matrix") is False:
        options[CONF_TARGET_ENTITY] = ""
    options.pop("enable_matrix", None)

    if CONF_TARGET_ENTITY in options:
        target = options.get(CONF_TARGET_ENTITY) or ""
    else:
        target = data.get(CONF_TARGET_ENTITY) or ""
    if target:
        title = f"Music artwork → {target}"
    else:
        sources = options.get("source_entities") or [data.get(CONF_SOURCE_ENTITY) or "source"]
        title = f"Music lighting → {sources[0]}"

    hass.config_entries.async_update_entry(
        entry,
        data=data,
        options=options,
        title=title,
        version=2,
    )
    return True
