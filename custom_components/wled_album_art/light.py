"""Live fallback-color control for Music Artwork Lighting."""
from __future__ import annotations

from homeassistant.components.light import ColorMode, LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_NO_ART_BRIGHTNESS, CONF_NO_ART_COLOR, CONF_NO_ART_LAST_COLOR, DEFAULT_NO_ART_COLOR, DOMAIN
from .controls import async_set_live_options


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Expose the configured fallback color as a dashboard color picker."""
    manager = hass.data[DOMAIN][entry.entry_id]
    if manager.matrix_enabled or manager.theme_light_entities:
        async_add_entities([MusicArtworkFallbackColorLight(entry, manager)])


class MusicArtworkFallbackColorLight(LightEntity):
    """A configuration-only RGB picker; it never controls a physical light directly."""

    _attr_has_entity_name = True
    _attr_translation_key = "no_art_fallback_color"
    _attr_icon = "mdi:palette"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_supported_color_modes = {ColorMode.RGB}

    def __init__(self, entry: ConfigEntry, manager) -> None:
        self._entry = entry
        self._manager = manager
        saved_color = entry.options.get(CONF_NO_ART_LAST_COLOR, DEFAULT_NO_ART_COLOR)
        try:
            saved_color = tuple(max(0, min(255, int(channel))) for channel in saved_color)
            if len(saved_color) != 3 or not any(saved_color):
                saved_color = tuple(DEFAULT_NO_ART_COLOR)
        except (TypeError, ValueError):
            saved_color = tuple(DEFAULT_NO_ART_COLOR)
        self._last_color = tuple(manager.no_art_color) if any(manager.no_art_color) else saved_color
        self._attr_unique_id = f"{entry.entry_id}_no_art_fallback_color_control"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Music Artwork Lighting",
            model="Home Assistant custom integration",
        )

    async def async_added_to_hass(self) -> None:
        """Track fallback-color changes made from Configure or another entity."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._manager.async_add_entity_state_listener(self._handle_manager_update)
        )

    @callback
    def _handle_manager_update(self) -> None:
        if any(self._manager.no_art_color):
            self._last_color = tuple(self._manager.no_art_color)
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        """Show black as off, matching the fallback scene's black-means-off rule."""
        return any(self._manager.no_art_color)

    @property
    def color_mode(self) -> ColorMode:
        return ColorMode.RGB

    @property
    def rgb_color(self) -> tuple[int, int, int]:
        return tuple(self._manager.no_art_color)

    @property
    def brightness(self) -> int | None:
        """Expose the optional fallback-light brightness override in HA's 0–255 scale."""
        percent = self._manager.no_art_brightness
        return round(percent * 255 / 100) if percent else None

    async def async_turn_on(self, **kwargs) -> None:
        """Save color and brightness choices without commanding physical lights."""
        color = kwargs.get("rgb_color")
        if color is None:
            color = self._manager.no_art_color if any(self._manager.no_art_color) else self._last_color
        try:
            normalized = [max(0, min(255, int(channel))) for channel in color]
        except (TypeError, ValueError) as err:
            raise ValueError("Fallback color must contain three RGB channels") from err
        if len(normalized) != 3:
            raise ValueError("Fallback color must contain three RGB channels")
        if any(normalized):
            self._last_color = tuple(normalized)
        values = {CONF_NO_ART_COLOR: normalized}
        if any(normalized):
            values[CONF_NO_ART_LAST_COLOR] = normalized
        brightness = kwargs.get("brightness")
        if brightness is not None:
            try:
                brightness_percent = round(max(1, min(255, int(brightness))) * 100 / 255)
            except (TypeError, ValueError) as err:
                raise ValueError("Fallback brightness must be between 1 and 255") from err
            values[CONF_NO_ART_BRIGHTNESS] = max(1, min(100, brightness_percent))
        await async_set_live_options(self.hass, self._entry, self._manager, values)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Disable the fallback color while remembering color and brightness."""
        await async_set_live_options(
            self.hass, self._entry, self._manager,
            {CONF_NO_ART_COLOR: [0, 0, 0], CONF_NO_ART_LAST_COLOR: list(self._last_color)},
        )
        self.async_write_ha_state()
