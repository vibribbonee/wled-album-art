"""Manual refresh button for Music Artwork Lighting."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    manager = hass.data[DOMAIN][entry.entry_id]
    entities = [
        WLEDAlbumArtRefreshButton(entry, manager),
        WLEDAlbumArtRetryRestoreButton(entry, manager),
    ]
    if manager.matrix_enabled:
        entities.append(WLEDAlbumArtTestMatrixButton(entry, manager))
    if manager.theme_light_entities:
        entities.append(WLEDAlbumArtTestThemeLightsButton(entry, manager))
    async_add_entities(entities)


class WLEDAlbumArtRefreshButton(ButtonEntity):
    """Button that manually re-sends the current artwork."""

    _attr_has_entity_name = True
    _attr_name = "Refresh artwork"
    _attr_translation_key = "refresh"
    _attr_icon = "mdi:image-refresh"

    def __init__(self, entry: ConfigEntry, manager) -> None:
        self._entry = entry
        self._manager = manager
        self._attr_unique_id = f"{entry.entry_id}_refresh"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Music Artwork Lighting",
            model="Home Assistant custom integration",
        )

    async def async_press(self) -> None:
        await self._manager.async_refresh_artwork()


class WLEDAlbumArtRetryRestoreButton(ButtonEntity):
    """Retry saved-state restoration when one or more devices need attention."""

    _attr_has_entity_name = True
    _attr_name = "Retry state restoration"
    _attr_translation_key = "retry_restore"
    _attr_icon = "mdi:backup-restore"

    def __init__(self, entry: ConfigEntry, manager) -> None:
        self._manager = manager
        self._attr_unique_id = f"{entry.entry_id}_retry_restore"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Music Artwork Lighting",
            model="Home Assistant custom integration",
        )

    @property
    def available(self) -> bool:
        """Only enable the action while a saved state is pending restoration."""
        return self._manager.restoration_retry_available

    async def async_added_to_hass(self) -> None:
        """Refresh button availability when recovery state changes."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._manager.async_add_entity_state_listener(self._handle_manager_update)
        )

    @callback
    def _handle_manager_update(self) -> None:
        self.async_write_ha_state()

    async def async_press(self) -> None:
        await self._manager.async_retry_state_restoration()
        self.async_write_ha_state()


class WLEDAlbumArtTestThemeLightsButton(ButtonEntity):
    """Briefly test selected theme lights and restore their previous state."""

    _attr_has_entity_name = True
    _attr_name = "Test theme lights"
    _attr_translation_key = "test_theme_lights"
    _attr_icon = "mdi:lightbulb-on-outline"

    def __init__(self, entry: ConfigEntry, manager) -> None:
        self._manager = manager
        self._attr_unique_id = f"{entry.entry_id}_test_theme_lights"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Music Artwork Lighting",
            model="Home Assistant custom integration",
        )

    async def async_press(self) -> None:
        await self._manager.async_test_theme_lights()


class WLEDAlbumArtTestMatrixButton(ButtonEntity):
    """Briefly show a test color on the matrix and restore its previous state."""

    _attr_has_entity_name = True
    _attr_name = "Test matrix"
    _attr_translation_key = "test_matrix"
    _attr_icon = "mdi:led-strip-variant"

    def __init__(self, entry: ConfigEntry, manager) -> None:
        self._manager = manager
        self._attr_unique_id = f"{entry.entry_id}_test_matrix"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Music Artwork Lighting",
            model="Home Assistant custom integration",
        )

    async def async_press(self) -> None:
        await self._manager.async_test_matrix()
