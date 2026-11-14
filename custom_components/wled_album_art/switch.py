"""Live switches for Music Artwork Lighting."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_ANIMATED_ARTWORK,
    CONF_FADE_TO_BLACK,
    CONF_MATRIX_OUTPUT_ENABLED,
    CONF_ONLINE_ARTWORK_LOOKUP,
    DOMAIN,
)
from .controls import async_set_live_option


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up automatic control and dashboard tuning switches."""
    manager = hass.data[DOMAIN][entry.entry_id]
    entities = [
        WLEDAlbumArtAutomaticControlSwitch(entry, manager),
        MusicArtworkOptionSwitch(
            entry,
            manager,
            CONF_ANIMATED_ARTWORK,
            "animated_artwork_enabled",
            "animated_artwork",
            "mdi:animation-play-outline",
        ),
        MusicArtworkOptionSwitch(
            entry,
            manager,
            CONF_ONLINE_ARTWORK_LOOKUP,
            "online_artwork_lookup_enabled",
            "online_artwork_lookup",
            "mdi:image-search-outline",
        ),
    ]
    if manager.matrix_enabled:
        entities.extend([
            MusicArtworkMatrixOutputSwitch(entry, manager),
            MusicArtworkOptionSwitch(
                entry, manager, CONF_FADE_TO_BLACK,
                "fade_to_black", "fade_to_black", "mdi:transition",
            ),
        ])
    async_add_entities(entities)


class _MusicArtworkSwitchBase(SwitchEntity):
    """Shared device registration for switches belonging to one entry."""

    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry, manager) -> None:
        self._manager = manager
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Music Artwork Lighting",
            model="Home Assistant custom integration",
        )

    async def async_added_to_hass(self) -> None:
        """Refresh switch states when options change outside the dashboard."""
        await super().async_added_to_hass()
        self.async_on_remove(self._manager.async_add_entity_state_listener(self._handle_manager_update))

    @callback
    def _handle_manager_update(self) -> None:
        self.async_write_ha_state()


class WLEDAlbumArtAutomaticControlSwitch(_MusicArtworkSwitchBase):
    """Pause/resume the whole automation, restoring state when paused."""

    _attr_name = "Automatic control"
    _attr_icon = "mdi:autorenew"

    def __init__(self, entry: ConfigEntry, manager) -> None:
        super().__init__(entry, manager)
        self._attr_unique_id = f"{entry.entry_id}_automatic_control"

    @property
    def is_on(self) -> bool:
        return not self._manager.manual_override

    async def async_turn_off(self) -> None:
        await self._manager.async_set_manual_override(True)
        self.async_write_ha_state()

    async def async_turn_on(self) -> None:
        await self._manager.async_set_manual_override(False)
        self.async_write_ha_state()


class MusicArtworkMatrixOutputSwitch(_MusicArtworkSwitchBase):
    """Enable album artwork on the selected matrix, independently of room lights."""

    _attr_name = "Matrix artwork"
    _attr_translation_key = "matrix_output_enabled"
    _attr_icon = "mdi:led-strip-variant"

    def __init__(self, entry: ConfigEntry, manager) -> None:
        super().__init__(entry, manager)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{CONF_MATRIX_OUTPUT_ENABLED}_control"

    @property
    def is_on(self) -> bool:
        return self._manager.matrix_output_enabled

    async def async_turn_on(self) -> None:
        await self._set_value(True)

    async def async_turn_off(self) -> None:
        await self._set_value(False)

    async def _set_value(self, value: bool) -> None:
        await async_set_live_option(
            self.hass, self._entry, self._manager,
            CONF_MATRIX_OUTPUT_ENABLED, value,
        )
        self.async_write_ha_state()


class MusicArtworkOptionSwitch(_MusicArtworkSwitchBase):
    """Persist a boolean option and apply it without a full integration reload."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        entry: ConfigEntry,
        manager,
        option_key: str,
        attribute_name: str,
        translation_key: str,
        icon: str,
    ) -> None:
        super().__init__(entry, manager)
        self._entry = entry
        self._option_key = option_key
        self._attribute_name = attribute_name
        self._attr_translation_key = translation_key
        self._attr_icon = icon
        self._attr_unique_id = f"{entry.entry_id}_{option_key}_control"

    @property
    def is_on(self) -> bool:
        return bool(getattr(self._manager, self._attribute_name))

    async def async_turn_on(self) -> None:
        await self._set_value(True)

    async def async_turn_off(self) -> None:
        await self._set_value(False)

    async def _set_value(self, value: bool) -> None:
        await async_set_live_option(
            self.hass, self._entry, self._manager, self._option_key, value
        )
        self.async_write_ha_state()
