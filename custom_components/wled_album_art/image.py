"""Locally served album artwork for dashboards and other integrations."""
from __future__ import annotations

from datetime import datetime

from homeassistant.components.image import ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Expose the artwork already fetched and prepared by the manager."""
    manager = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([MusicArtworkImage(hass, entry, manager)])


class MusicArtworkImage(ImageEntity):
    """Serve the current cover through Home Assistant's native image proxy."""

    _attr_has_entity_name = True
    _attr_translation_key = "artwork"
    _attr_icon = "mdi:album"
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, manager) -> None:
        super().__init__(hass)
        self._manager = manager
        self._attr_unique_id = f"{entry.entry_id}_artwork"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Music Artwork Lighting",
            model="Home Assistant custom integration",
        )

    @property
    def available(self) -> bool:
        """Remain available while the manager retains an artwork snapshot."""
        return self._manager.artwork_image is not None

    @property
    def content_type(self) -> str:
        return self._manager.artwork_content_type

    @property
    def image_last_updated(self) -> datetime | None:
        return self._manager.artwork_last_updated

    @property
    def entity_picture(self) -> str | None:
        """Publish only HA's local proxy, and only while artwork exists."""
        if not self.available:
            return None
        picture = super().entity_picture
        updated_at = self.image_last_updated
        if picture is not None and updated_at is not None:
            separator = "&" if "?" in picture else "?"
            # Generic cards reuse unchanged URLs even when the track changes.
            # The manager advances this timestamp only for changed image bytes.
            return f"{picture}{separator}v={updated_at.timestamp():.6f}"
        return picture

    @property
    def extra_state_attributes(self) -> dict:
        return self._manager.artwork_attributes()

    async def async_image(self) -> bytes | None:
        """Return bounded, cached bytes without additional image requests."""
        return self._manager.artwork_image

    async def async_added_to_hass(self) -> None:
        """Track artwork changes and register this entity's actual entity ID."""
        await super().async_added_to_hass()
        self._manager.set_artwork_image_entity_id(self.entity_id)
        self.async_on_remove(
            self._manager.async_add_entity_state_listener(self.async_write_ha_state)
        )

    async def async_will_remove_from_hass(self) -> None:
        """Remove the image reference when this entity is disabled or unloaded."""
        self._manager.set_artwork_image_entity_id(None)
        await super().async_will_remove_from_hass()
