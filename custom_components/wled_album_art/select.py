"""Dashboard-select controls for Music Artwork Lighting."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    AUTO_POWER_MODES,
    CONF_AUTO_POWER_MODE,
    CONF_ROOM_END_BEHAVIOR,
    CONF_MATRIX_END_BEHAVIOR,
    CONF_NO_ART_BRIGHTNESS,
    CONF_IMAGE_FIT,
    CONF_IMAGE_CROP_POSITION,
    CONF_NO_ART_BEHAVIOR,
    CONF_NO_ART_DURING_SESSION,
    CONF_PAUSE_BEHAVIOR,
    CONF_THEME_COLOR_MODE,
    CONF_THEME_COLOR_ADJUSTMENTS,
    CONF_THEME_FADE_MODE,
    CONF_TRANSITION_STYLE,
    DOMAIN,
    ROOM_END_BEHAVIORS,
    MATRIX_END_BEHAVIORS,
    IMAGE_FIT_MODES,
    IMAGE_CROP_POSITIONS,
    NO_ART_BEHAVIORS,
    NO_ART_DURING_SESSION_BEHAVIORS,
    THEME_COLOR_ADJUSTMENT_MODES,
    THEME_FADE_MODES,
)
from .controls import async_set_live_option

_THEME_COLOR_MODES = [
    "palette", "contrast", "shared", "vibrant", "complementary",
    "analogous", "cinematic", "monochrome",
]
_PAUSE_BEHAVIORS = ["end_after_grace", "hold"]

_TRANSITION_STYLES = [
    "instant", "fade", "shuffle", "fairy_dust", "swipe_right", "swipe_left",
    "swipe_up", "swipe_down", "swipe_top_left", "swipe_top_right",
    "swipe_bottom_right", "swipe_bottom_left", "push_right", "push_left",
    "push_up", "push_down", "outside_in", "inside_out", "open_horizontal",
    "open_vertical", "circular_out", "circular_in",
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add dashboard-adjustable select entities."""
    manager = hass.data[DOMAIN][entry.entry_id]
    entities = [
        MusicArtworkPauseBehaviorSelect(entry, manager),
    ]
    if manager.matrix_enabled or manager.theme_light_entities:
        entities.extend([
            MusicArtworkAutoPowerModeSelect(entry, manager),
            MusicArtworkNoArtBehaviorSelect(entry, manager),
            MusicArtworkNoArtDuringSessionSelect(entry, manager),
        ])
    if manager.matrix_enabled:
        entities.extend([
            MusicArtworkTransitionStyleSelect(entry, manager),
            MusicArtworkImageFitSelect(entry, manager),
            MusicArtworkImageCropPositionSelect(entry, manager),
            MusicArtworkMatrixEndBehaviorSelect(entry, manager),
        ])
    if manager.theme_light_entities:
        entities.extend([
            MusicArtworkThemeColorModeSelect(entry, manager),
            MusicArtworkThemeFadeModeSelect(entry, manager),
            MusicArtworkThemeColorAdjustmentsSelect(entry, manager),
            MusicArtworkRoomEndBehaviorSelect(entry, manager),
            MusicArtworkFallbackBrightnessSelect(entry, manager),
        ])
    async_add_entities(entities)


class _MusicArtworkLiveSelect(SelectEntity):
    """Base for selects persisted in config-entry options and applied live."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

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
        """Refresh selected values when options change outside the dashboard."""
        await super().async_added_to_hass()
        self.async_on_remove(self._manager.async_add_entity_state_listener(self._handle_manager_update))

    @callback
    def _handle_manager_update(self) -> None:
        self.async_write_ha_state()

    async def async_select_option(self, option: str) -> None:
        """Save and apply the selected option without a full reload."""
        if option not in self.options:
            raise ValueError(f"Unsupported option: {option}")
        await async_set_live_option(
            self.hass, self._entry, self._manager, self._option_key, option
        )
        self.async_write_ha_state()


class MusicArtworkThemeColorModeSelect(_MusicArtworkLiveSelect):
    """Choose how colors from album artwork are distributed across theme lights."""

    _attr_translation_key = "theme_color_mode"
    _attr_icon = "mdi:palette"
    _attr_options = _THEME_COLOR_MODES

    def __init__(self, entry: ConfigEntry, manager) -> None:
        super().__init__(entry, manager, CONF_THEME_COLOR_MODE)

    @property
    def current_option(self) -> str:
        return self._manager.theme_color_mode


class MusicArtworkAutoPowerModeSelect(_MusicArtworkLiveSelect):
    """Choose which selected outputs may power on for a music session."""

    _attr_translation_key = "auto_power_mode"
    _attr_icon = "mdi:power-settings"
    _attr_options = list(AUTO_POWER_MODES)

    def __init__(self, entry: ConfigEntry, manager) -> None:
        super().__init__(entry, manager, CONF_AUTO_POWER_MODE)

    @property
    def current_option(self) -> str:
        return self._manager.auto_power_mode

    @property
    def options(self) -> list[str]:
        if self._manager.matrix_enabled and self._manager.theme_light_entities:
            return self._attr_options
        return ["all", "none"]


class MusicArtworkThemeFadeModeSelect(_MusicArtworkLiveSelect):
    """Choose how theme lights transition between album colors."""

    _attr_translation_key = "theme_fade_mode"
    _attr_icon = "mdi:lightbulb-auto-outline"
    _attr_options = list(THEME_FADE_MODES)

    def __init__(self, entry: ConfigEntry, manager) -> None:
        super().__init__(entry, manager, CONF_THEME_FADE_MODE)

    @property
    def current_option(self) -> str:
        if not self._manager.matrix_enabled and self._manager.theme_fade_mode == "matrix_black":
            return "colors"
        return self._manager.theme_fade_mode

    @property
    def options(self) -> list[str]:
        if self._manager.matrix_enabled:
            return self._attr_options
        return [option for option in self._attr_options if option != "matrix_black"]


class MusicArtworkThemeColorAdjustmentsSelect(_MusicArtworkLiveSelect):
    """Choose safeguards applied to extracted album colors."""

    _attr_translation_key = "theme_color_adjustments"
    _attr_icon = "mdi:palette-swatch"
    _attr_options = list(THEME_COLOR_ADJUSTMENT_MODES)

    def __init__(self, entry: ConfigEntry, manager) -> None:
        super().__init__(entry, manager, CONF_THEME_COLOR_ADJUSTMENTS)

    @property
    def current_option(self) -> str:
        return self._manager.theme_color_adjustments


class MusicArtworkTransitionStyleSelect(_MusicArtworkLiveSelect):
    """Choose how the matrix transitions between album covers."""

    _attr_translation_key = "transition_style"
    _attr_icon = "mdi:animation-outline"
    _attr_options = _TRANSITION_STYLES

    def __init__(self, entry: ConfigEntry, manager) -> None:
        super().__init__(entry, manager, CONF_TRANSITION_STYLE)

    @property
    def current_option(self) -> str:
        return self._manager.transition_style


class MusicArtworkImageFitSelect(_MusicArtworkLiveSelect):
    """Choose how a cover is fitted to the matrix."""

    _attr_translation_key = "image_fit"
    _attr_icon = "mdi:image-size-select-large"
    _attr_options = list(IMAGE_FIT_MODES)

    def __init__(self, entry: ConfigEntry, manager) -> None:
        super().__init__(entry, manager, CONF_IMAGE_FIT)

    @property
    def current_option(self) -> str:
        return self._manager.image_fit


class MusicArtworkImageCropPositionSelect(_MusicArtworkLiveSelect):
    """Choose the focal point used when artwork needs to be cropped."""

    _attr_translation_key = "image_crop_position"
    _attr_icon = "mdi:focus-field"
    _attr_options = list(IMAGE_CROP_POSITIONS)

    def __init__(self, entry: ConfigEntry, manager) -> None:
        super().__init__(entry, manager, CONF_IMAGE_CROP_POSITION)

    @property
    def current_option(self) -> str:
        return self._manager.image_crop_position


class MusicArtworkNoArtBehaviorSelect(_MusicArtworkLiveSelect):
    """Choose how a no-art music source is handled when a session starts."""

    _attr_translation_key = "no_art_behavior"
    _attr_icon = "mdi:image-off-outline"
    _attr_options = list(NO_ART_BEHAVIORS)

    def __init__(self, entry: ConfigEntry, manager) -> None:
        super().__init__(entry, manager, CONF_NO_ART_BEHAVIOR)

    @property
    def current_option(self) -> str:
        return self._manager.no_art_behavior


class MusicArtworkNoArtDuringSessionSelect(_MusicArtworkLiveSelect):
    """Choose what happens if artwork disappears after a track was shown."""

    _attr_translation_key = "no_art_during_session_behavior"
    _attr_icon = "mdi:image-refresh-outline"
    _attr_options = list(NO_ART_DURING_SESSION_BEHAVIORS)

    def __init__(self, entry: ConfigEntry, manager) -> None:
        super().__init__(entry, manager, CONF_NO_ART_DURING_SESSION)

    @property
    def current_option(self) -> str:
        return self._manager.no_art_during_session_behavior


class MusicArtworkRoomEndBehaviorSelect(_MusicArtworkLiveSelect):
    """Choose the room-light action independently from the matrix."""

    _attr_translation_key = "room_end_behavior"
    _attr_icon = "mdi:home-lightbulb-outline"
    _attr_options = list(ROOM_END_BEHAVIORS)

    def __init__(self, entry: ConfigEntry, manager) -> None:
        super().__init__(entry, manager, CONF_ROOM_END_BEHAVIOR)

    @property
    def current_option(self) -> str:
        return self._manager.room_end_behavior


class MusicArtworkMatrixEndBehaviorSelect(_MusicArtworkLiveSelect):
    """Choose the matrix action independently from the room lights."""

    _attr_translation_key = "matrix_end_behavior"
    _attr_icon = "mdi:led-outline"
    _attr_options = list(MATRIX_END_BEHAVIORS)

    def __init__(self, entry: ConfigEntry, manager) -> None:
        super().__init__(entry, manager, CONF_MATRIX_END_BEHAVIOR)

    @property
    def current_option(self) -> str:
        return self._manager.matrix_end_behavior


class MusicArtworkFallbackBrightnessSelect(_MusicArtworkLiveSelect):
    """Make returning to room brightness an explicit, discoverable action."""

    _attr_translation_key = "fallback_brightness_mode"
    _attr_icon = "mdi:brightness-6"
    _attr_options = ["follow_room", "fixed"]

    def __init__(self, entry: ConfigEntry, manager) -> None:
        super().__init__(entry, manager, "fallback_brightness_mode")

    @property
    def current_option(self) -> str:
        return "fixed" if self._manager.no_art_brightness else "follow_room"

    async def async_select_option(self, option: str) -> None:
        if option not in self.options:
            raise ValueError(f"Unsupported option: {option}")
        brightness = (self._manager.no_art_brightness or 100) if option == "fixed" else 0
        await async_set_live_option(
            self.hass, self._entry, self._manager, CONF_NO_ART_BRIGHTNESS, brightness
        )
        self.async_write_ha_state()


class MusicArtworkPauseBehaviorSelect(_MusicArtworkLiveSelect):
    """Choose whether a paused player should eventually end the session."""

    _attr_translation_key = "pause_behavior"
    _attr_icon = "mdi:pause-circle-outline"
    _attr_options = _PAUSE_BEHAVIORS

    def __init__(self, entry: ConfigEntry, manager) -> None:
        super().__init__(entry, manager, CONF_PAUSE_BEHAVIOR)

    @property
    def current_option(self) -> str:
        return self._manager.pause_behavior


