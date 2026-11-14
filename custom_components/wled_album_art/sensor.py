"""Status and diagnostic sensor entities for Music Artwork Lighting."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the status sensor for this integration entry."""
    manager = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        WLEDAlbumArtStatusSensor(entry, manager),
        MusicArtworkNowPlayingSensor(entry, manager),
        MusicArtworkColorsSensor(entry, manager),
        MusicArtworkCurrentSourceSensor(entry, manager),
        MusicArtworkDeviceHealthSensor(entry, manager),
    ])


class WLEDAlbumArtStatusSensor(SensorEntity):
    """Expose current playback and output status, with compact diagnostics."""

    _attr_has_entity_name = True
    _attr_name = "Status"
    _attr_icon = "mdi:information-outline"
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, manager) -> None:
        self._manager = manager
        self._attr_unique_id = f"{entry.entry_id}_status"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Music Artwork Lighting",
            model="Home Assistant custom integration",
        )

    @property
    def native_value(self) -> str:
        return self._manager.status[:255]

    @property
    def extra_state_attributes(self) -> dict:
        return {"full_status": self._manager.status, **self._manager.status_attributes()}

    async def async_added_to_hass(self) -> None:
        """Subscribe to coordinator changes instead of polling every ten seconds."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._manager.async_add_status_listener(self.async_write_ha_state)
        )


class MusicArtworkCurrentSourceSensor(SensorEntity):
    """Expose the selected music source and explain the priority decision."""

    _attr_has_entity_name = True
    _attr_name = "Current source"
    _attr_icon = "mdi:music-note"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, manager) -> None:
        self._manager = manager
        self._attr_unique_id = f"{entry.entry_id}_current_source"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Music Artwork Lighting",
            model="Home Assistant custom integration",
        )

    @property
    def native_value(self) -> str:
        details = self._manager.source_diagnostics()
        if details["active_source_is_playing_session"]:
            return str(details["active_source"] or "Unknown source")

        # Artwork availability must not change the configured player priority.
        candidate = next((item for item in details["source_candidates"]
                          if item["state"] == "playing"
                          and item["eligible_music"]), None)
        if candidate:
            return str(candidate["entity_id"])
        if any(
            item["state"] == "playing"
            and (
                "audio metadata found" in item["status"]
                or "waiting for cover art to confirm music" in item["status"].lower()
            )
            for item in details["source_candidates"]
        ):
            return "Waiting for artwork"
        if any(item["state"] in ("playing", "buffering") for item in details["source_candidates"]):
            return "No music source identified"
        return "No active source"

    @property
    def extra_state_attributes(self) -> dict:
        details = self._manager.source_diagnostics()
        selected_id = details["active_source"]
        return {
            "source_entity_id": selected_id,
            "source_name": details["active_source_name"],
            "source_state": details["active_source_state"],
            "media_title": details["active_source_media_title"],
            "media_artist": details["active_source_media_artist"],
            "media_album_name": details["active_source_media_album"],
            "media_content_type": details["active_source_media_type"],
            "app_name": details["active_source_app_name"],
            "priority_position": details["active_source_priority"],
            "selection_reason": details["source_selection_reason"],
            "session_had_artwork": details["session_had_artwork"],
            "source_priority_order": details["source_priority_order"],
            "source_candidates": details["source_candidates"],
        }

    async def async_added_to_hass(self) -> None:
        """Update immediately when source selection or playback status changes."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._manager.async_add_entity_state_listener(self.async_write_ha_state)
        )


class MusicArtworkNowPlayingSensor(SensorEntity):
    """Show the active track and expose its player for dashboard tap routing."""

    _attr_has_entity_name = True
    _attr_name = "Now playing"
    _attr_icon = "mdi:music-circle"
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, manager) -> None:
        self._manager = manager
        self._attr_unique_id = f"{entry.entry_id}_now_playing"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Music Artwork Lighting",
            model="Home Assistant custom integration",
        )

    @property
    def native_value(self) -> str:
        details = self._manager.source_diagnostics()
        if not details["active_source_is_playing_session"]:
            if any(
                item["state"] == "playing"
                and "waiting for cover art to confirm music" in item["status"].lower()
                for item in details["source_candidates"]
            ):
                return "Waiting for cover art"
            return "Nothing playing"
        title = details["active_source_media_title"]
        artist = details["active_source_media_artist"]
        if not title:
            return "Waiting for track details"
        value = f"{artist} — {title}" if artist else str(title)
        return value[:255]

    @property
    def extra_state_attributes(self) -> dict:
        details = self._manager.source_diagnostics()
        return {
            **self._manager.artwork_attributes(),
            "active_source_entity_id": details["active_source"],
            "active_source_name": details["active_source_name"],
            "active_source_state": details["active_source_state"],
            "media_title": details["active_source_media_title"],
            "media_artist": details["active_source_media_artist"],
            "source_selection_reason": details["source_selection_reason"],
        }

    @property
    def entity_picture(self) -> str | None:
        """Use the locally served cover, including covers found online."""
        return self._manager.artwork_entity_picture()

    @callback
    def _handle_image_state_change(self, event) -> None:
        """Follow proxy-token changes and image writes after manager updates."""
        if event.data.get("entity_id") == self._manager.artwork_image_entity_id:
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Update when the active player or its track changes."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._manager.async_add_entity_state_listener(self.async_write_ha_state)
        )
        self.async_on_remove(
            self.hass.bus.async_listen(EVENT_STATE_CHANGED, self._handle_image_state_change)
        )


class MusicArtworkColorsSensor(SensorEntity):
    """Expose primary and palette colors for dashboard templates and automations."""

    _attr_has_entity_name = True
    _attr_translation_key = "artwork_colors"
    _attr_icon = "mdi:palette"
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, manager) -> None:
        self._manager = manager
        self._attr_unique_id = f"{entry.entry_id}_artwork_colors"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Music Artwork Lighting",
            model="Home Assistant custom integration",
        )

    @property
    def native_value(self) -> str:
        return self._manager.artwork_attributes().get("hex_color") or "No artwork"

    @property
    def extra_state_attributes(self) -> dict:
        return self._manager.artwork_attributes()

    async def async_added_to_hass(self) -> None:
        """Publish colors when the manager accepts artwork or changes context."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._manager.async_add_entity_state_listener(self.async_write_ha_state)
        )


class MusicArtworkDeviceHealthSensor(SensorEntity):
    """Summarize health and recovery state for every configured output."""

    _attr_has_entity_name = True
    _attr_name = "Device health"
    _attr_icon = "mdi:heart-pulse"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, manager) -> None:
        self._manager = manager
        self._attr_unique_id = f"{entry.entry_id}_device_health"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Music Artwork Lighting",
            model="Home Assistant custom integration",
        )

    def _health(self) -> tuple[str, dict]:
        """Build a compact health summary from the manager's safe diagnostics."""
        details = self._manager.status_attributes()
        devices: dict[str, dict] = {}
        recovering = bool(details.get("state_restoration_pending"))
        attention = recovering
        pending_matrices = set(details.get("pending_matrix_restore_entities", []))
        pending_theme_lights = set(details.get("pending_theme_restore_entities", []))
        for entity_id, output in details.get("matrix_outputs", {}).items():
            state = "Online" if output.get("available") else "Unavailable"
            result = output.get("last_result", "not_started")
            if entity_id in pending_matrices:
                state = "Restoration pending"
                attention = recovering = True
            elif not output.get("available") or result in {
                "unavailable", "error", "snapshot_failed", "restore_deferred",
                "restore_pending_reconnect", "restore_pending", "reconnecting_wait",
                "override_off_failed", "override_off_waiting_reconnect",
            }:
                attention = True
                if result.startswith("restore") or result in {
                    "reconnecting_wait", "override_off_waiting_reconnect",
                }:
                    recovering = True
                if not output.get("available"):
                    state = "Unavailable"
                elif result == "override_off_failed":
                    state = "Power-off failed"
                elif result == "override_off_waiting_reconnect":
                    state = "Waiting for WLED"
                elif result in {"restore_deferred", "restore_pending_reconnect", "restore_pending", "reconnecting_wait"}:
                    state = "Restoration pending" if result.startswith("restore") else "Warming up"
                elif result == "snapshot_failed":
                    state = "Snapshot failed"
                elif result == "error":
                    state = "Update failed"
            devices[entity_id] = {
                "type": "matrix", "state": state, "last_result": result,
                "last_updated_at": output.get("last_updated_at"),
                "last_error": output.get("last_error"),
                "snapshot_saved": output.get("snapshot_saved", False),
            }
        light_results = details.get("theme_light_results", {})
        for entity_id in self._manager.theme_light_entities:
            output = light_results.get(entity_id, {})
            hass_state = self._manager.hass.states.get(entity_id)
            available = bool(hass_state and hass_state.state not in ("unknown", "unavailable"))
            result = output.get("last_result", "not_started")
            state = "Online" if available else "Unavailable"
            if entity_id in pending_theme_lights:
                state = "Restoration pending"
                attention = recovering = True
            elif not available or result in {"error", "unavailable", "restore_pending", "reconnecting_wait"}:
                attention = True
                if result in {"restore_pending", "reconnecting_wait"}:
                    recovering = True
                    state = "Restoration pending" if result == "restore_pending" else "Warming up"
                elif available and result == "error":
                    state = "Update failed"
            devices[entity_id] = {
                "type": "theme_light", "state": state, "last_result": result,
                "last_error": output.get("last_error"),
            }
        for entity_id in pending_matrices.difference(devices):
            devices[entity_id] = {
                "type": "matrix", "state": "Restoration pending",
                "last_result": "restore_pending",
            }
        for entity_id in pending_theme_lights.difference(devices):
            devices[entity_id] = {
                "type": "theme_light", "state": "Restoration pending",
                "last_result": "restore_pending",
            }
        if not devices:
            value = "No outputs configured"
        elif recovering:
            value = "Recovering"
        elif attention:
            value = "Attention needed"
        else:
            value = "Healthy"
        return value, {
            "device_count": len(devices),
            "devices": devices,
            "current_source": details.get("active_source_name"),
            "source_selection_reason": details.get("source_selection_reason"),
            "state_restoration_pending": details.get("state_restoration_pending", False),
            "restoration_retry_available": details.get("restoration_retry_available", False),
        }

    @property
    def native_value(self) -> str:
        return self._health()[0]

    @property
    def extra_state_attributes(self) -> dict:
        return self._health()[1]

    async def async_added_to_hass(self) -> None:
        """Update with the same event-driven manager notifications as other sensors."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._manager.async_add_entity_state_listener(self.async_write_ha_state)
        )
