"""Dashboard-number controls for Music Artwork Lighting transition timing."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_BLACK_PAUSE,
    CONF_DEVICE_WARMUP_DELAY,
    CONF_NO_ART_BRIGHTNESS,
    CONF_IMAGE_ZOOM,
    CONF_IMAGE_BLUR_STRENGTH,
    CONF_IMAGE_BACKGROUND_BRIGHTNESS,
    CONF_END_GRACE,
    CONF_SOURCE_STABILIZATION,
    CONF_THEME_LIGHT_TRANSITION,
    CONF_TRANSITION_SECONDS,
    DOMAIN,
)
from .controls import async_set_live_option


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add dashboard-adjustable transition duration entities."""
    manager = hass.data[DOMAIN][entry.entry_id]
    registry = er.async_get(hass)
    old_fallback_brightness_id = registry.async_get_entity_id(
        "number", DOMAIN,
        f"{entry.entry_id}_{CONF_NO_ART_BRIGHTNESS}_control",
    )
    if old_fallback_brightness_id:
        registry.async_remove(old_fallback_brightness_id)
    entities = [
        MusicArtworkSourceStabilizationNumber(entry, manager),
        MusicArtworkPlaybackEndGraceNumber(entry, manager),
        MusicArtworkDeviceWarmupNumber(entry, manager),
    ]
    if manager.matrix_enabled:
        entities.extend([
            MusicArtworkMatrixTransitionDurationNumber(entry, manager),
            MusicArtworkBlackPauseNumber(entry, manager),
            MusicArtworkImageZoomNumber(entry, manager),
            MusicArtworkImageBlurStrengthNumber(entry, manager),
            MusicArtworkImageBackgroundBrightnessNumber(entry, manager),
        ])
    if manager.theme_light_entities:
        entities.append(MusicArtworkThemeLightTransitionDurationNumber(entry, manager))
    async_add_entities(entities)


class _MusicArtworkLiveNumber(NumberEntity):
    """Base for bounded, persistent, live-applied duration controls."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_unit_of_measurement = "s"
    _attr_mode = NumberMode.BOX
    _attr_native_step = 0.1

    def __init__(self, entry: ConfigEntry, manager, option_key: str) -> None:
        self._entry = entry
        self._manager = manager
        self._option_key = option_key
        self._attr_unique_id = f"{entry.entry_id}_{option_key}_control"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Music Artwork Lighting",
            model="Home Assistant custom integration",
        )

    async def async_added_to_hass(self) -> None:
        """Refresh number values when options change outside the dashboard."""
        await super().async_added_to_hass()
        self.async_on_remove(self._manager.async_add_entity_state_listener(self._handle_manager_update))

    @callback
    def _handle_manager_update(self) -> None:
        self.async_write_ha_state()

    async def async_set_native_value(self, value: float) -> None:
        """Save and apply a duration value without a full reload."""
        try:
            new_value = round(float(value), 1)
        except (TypeError, ValueError) as err:
            raise HomeAssistantError("Value must be a number") from err
        if not self._attr_native_min_value <= new_value <= self._attr_native_max_value:
            raise HomeAssistantError("Value is outside the supported range")
        await async_set_live_option(
            self.hass, self._entry, self._manager, self._option_key, new_value
        )
        self.async_write_ha_state()


class MusicArtworkMatrixTransitionDurationNumber(_MusicArtworkLiveNumber):
    """Set the duration of matrix transitions between album covers."""

    _attr_translation_key = "matrix_transition_duration"
    _attr_icon = "mdi:timer-outline"
    _attr_native_min_value = 0.1
    _attr_native_max_value = 5.0

    def __init__(self, entry: ConfigEntry, manager) -> None:
        super().__init__(entry, manager, CONF_TRANSITION_SECONDS)

    @property
    def native_value(self) -> float:
        return self._manager.transition_seconds


class MusicArtworkThemeLightTransitionDurationNumber(_MusicArtworkLiveNumber):
    """Set the duration of color changes on theme lights."""

    _attr_translation_key = "theme_light_transition_duration"
    _attr_icon = "mdi:lightbulb-auto-outline"
    _attr_native_min_value = 0.0
    _attr_native_max_value = 10.0

    def __init__(self, entry: ConfigEntry, manager) -> None:
        super().__init__(entry, manager, CONF_THEME_LIGHT_TRANSITION)

    @property
    def native_value(self) -> float:
        return self._manager.theme_light_transition


class MusicArtworkBlackPauseNumber(_MusicArtworkLiveNumber):
    """Set the optional pause at black between matrix covers."""

    _attr_translation_key = "black_pause_duration"
    _attr_icon = "mdi:pause-circle-outline"
    _attr_native_min_value = 0.0
    _attr_native_max_value = 2.0
    _attr_native_step = 0.1

    def __init__(self, entry: ConfigEntry, manager) -> None:
        super().__init__(entry, manager, CONF_BLACK_PAUSE)

    @property
    def native_value(self) -> float:
        return self._manager.black_pause


class MusicArtworkSourceStabilizationNumber(_MusicArtworkLiveNumber):
    """Set how long source metadata must settle before switching artwork."""

    _attr_translation_key = "source_stabilization"
    _attr_icon = "mdi:timer-sand"
    _attr_native_min_value = 0.3
    _attr_native_max_value = 10.0
    _attr_native_step = 0.1

    def __init__(self, entry: ConfigEntry, manager) -> None:
        super().__init__(entry, manager, CONF_SOURCE_STABILIZATION)

    @property
    def native_value(self) -> float:
        return self._manager.source_stabilization


class MusicArtworkPlaybackEndGraceNumber(_MusicArtworkLiveNumber):
    """Set how long no configured source can play before end behavior runs."""

    _attr_translation_key = "playback_end_grace"
    _attr_icon = "mdi:timer-lock-outline"
    _attr_native_min_value = 0
    _attr_native_max_value = 300
    _attr_native_step = 1

    def __init__(self, entry: ConfigEntry, manager) -> None:
        super().__init__(entry, manager, CONF_END_GRACE)

    @property
    def native_value(self) -> float:
        return self._manager.end_grace_seconds


class MusicArtworkDeviceWarmupNumber(_MusicArtworkLiveNumber):
    """Set how long each device waits after power-on or reconnection."""

    _attr_translation_key = "device_warmup_delay"
    _attr_icon = "mdi:timer-cog-outline"
    _attr_native_min_value = 0
    _attr_native_max_value = 60
    _attr_native_step = 1

    def __init__(self, entry: ConfigEntry, manager) -> None:
        super().__init__(entry, manager, CONF_DEVICE_WARMUP_DELAY)

    @property
    def native_value(self) -> float:
        return self._manager._device_recovery_delay_seconds


class MusicArtworkImageZoomNumber(_MusicArtworkLiveNumber):
    """Set the artwork zoom level for matrix framing."""

    _attr_translation_key = "artwork_zoom"
    _attr_icon = "mdi:magnify-plus-outline"
    _attr_native_unit_of_measurement = "%"
    _attr_native_min_value = 100
    _attr_native_max_value = 200
    _attr_native_step = 5
    _attr_mode = NumberMode.SLIDER

    def __init__(self, entry: ConfigEntry, manager) -> None:
        super().__init__(entry, manager, CONF_IMAGE_ZOOM)

    @property
    def native_value(self) -> float:
        return self._manager.image_zoom


class MusicArtworkImageBlurStrengthNumber(_MusicArtworkLiveNumber):
    """Set the adjustable blurred-background strength."""

    _attr_translation_key = "artwork_blur_strength"
    _attr_icon = "mdi:blur"
    _attr_native_unit_of_measurement = "%"
    _attr_native_min_value = 0
    _attr_native_max_value = 40
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER

    def __init__(self, entry: ConfigEntry, manager) -> None:
        super().__init__(entry, manager, CONF_IMAGE_BLUR_STRENGTH)

    @property
    def native_value(self) -> float:
        return self._manager.image_blur_strength


class MusicArtworkImageBackgroundBrightnessNumber(_MusicArtworkLiveNumber):
    """Set the brightness of artwork-derived matrix backgrounds."""

    _attr_translation_key = "artwork_background_brightness"
    _attr_icon = "mdi:brightness-6"
    _attr_native_unit_of_measurement = "%"
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER

    def __init__(self, entry: ConfigEntry, manager) -> None:
        super().__init__(entry, manager, CONF_IMAGE_BACKGROUND_BRIGHTNESS)

    @property
    def native_value(self) -> float:
        return self._manager.image_background_brightness


