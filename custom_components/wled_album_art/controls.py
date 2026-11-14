"""Shared helpers for persistent dashboard tuning controls."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant


async def async_set_live_option(
    hass: HomeAssistant, entry: ConfigEntry, manager, key: str, value: object
) -> None:
    """Persist a single live-tunable option and apply it without a full reload."""
    options = dict(entry.options)
    if options.get(key) == value:
        # Still ask the manager to reconcile if an older entry omitted the key.
        if key not in options:
            options[key] = value
            hass.config_entries.async_update_entry(entry, options=options)
        else:
            return
    else:
        options[key] = value
        hass.config_entries.async_update_entry(entry, options=options)

    # The entry listener may run before or after this call. The manager serializes
    # both paths and advances its applied-options snapshot only once.
    await manager.async_apply_live_options()


async def async_set_live_options(
    hass: HomeAssistant, entry: ConfigEntry, manager, values: dict[str, object]
) -> None:
    """Persist a group of related settings and apply them as one live update."""
    options = dict(entry.options)
    changed = False
    for key, value in values.items():
        if options.get(key) != value or key not in options:
            options[key] = value
            changed = True
    if not changed:
        return
    hass.config_entries.async_update_entry(entry, options=options)
    await manager.async_apply_live_options()
