"""Config and options flow for Music Artwork Lighting."""
from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector

from .selection import configured_matrix_entities, normalize_entity_list

from .const import (
    CONF_ANIMATED_ARTWORK,
    CONF_AUTO_DETECT_SIZE,
    CONF_AUTO_POWER_MODE,
    CONF_BLACK_PAUSE,
    CONF_FADE_TO_BLACK,
    CONF_FILENAME,
    CONF_ROOM_END_BEHAVIOR,
    CONF_MATRIX_END_BEHAVIOR,
    CONF_END_GRACE,
    CONF_FADE_THEME_WITH_MATRIX,
    CONF_THEME_FADE_MODE,
    CONF_PAUSE_BEHAVIOR,
    CONF_MATRIX_TURN_ON,
    CONF_HEIGHT,
    CONF_IMAGE_FIT,
    CONF_IMAGE_CROP_POSITION,
    CONF_IMAGE_ZOOM,
    CONF_IMAGE_BLUR_STRENGTH,
    CONF_IMAGE_BACKGROUND_BRIGHTNESS,
    CONF_PIN,
    CONF_SEGMENT_ID,
    CONF_SOURCE_ENTITIES,
    CONF_SOURCE_ENTITY,
    CONF_SOURCE_STABILIZATION,
    CONF_DEVICE_WARMUP_DELAY,
    CONF_TARGET_ENTITY,
    CONF_TARGET_ENTITIES,
    CONF_TRANSITION_SECONDS,
    CONF_TRANSITION_STYLE,
    CONF_THEME_COLOR_MODE,
    CONF_THEME_LIGHT_ENTITIES,
    CONF_THEME_LIGHT_TRANSITION,
    CONF_THEME_TURN_ON,
    CONF_PREVENT_DARK_COLORS,
    CONF_BALANCE_THEME_SPECTRUM,
    CONF_THEME_COLOR_ADJUSTMENTS,
    CONF_NO_ART_BEHAVIOR,
    CONF_NO_ART_DURING_SESSION,
    CONF_NO_ART_COLOR,
    CONF_NO_ART_BRIGHTNESS,
    CONF_ONLINE_ARTWORK_LOOKUP,
    CONF_ARTWORK_PROVIDER_PRIORITY,
    CONF_ARTWORK_PROVIDERS,
    CONF_LASTFM_API_KEY,
    CONF_THEAUDIODB_API_KEY,
    CONF_IGNORED_INPUTS,
    CONF_RESTORE_THEME_BRIGHTNESS,
    CONF_WIDTH,
    DEFAULT_AUTO_DETECT_SIZE,
    DEFAULT_ANIMATED_ARTWORK,
    DEFAULT_AUTO_POWER_MODE,
    DEFAULT_BLACK_PAUSE,
    DEFAULT_FADE_TO_BLACK,
    DEFAULT_FILENAME,
    DEFAULT_END_GRACE,
    DEFAULT_FADE_THEME_WITH_MATRIX,
    DEFAULT_THEME_FADE_MODE,
    DEFAULT_PAUSE_BEHAVIOR,
    DEFAULT_MATRIX_TURN_ON,
    DEFAULT_HEIGHT,
    DEFAULT_IMAGE_FIT,
    DEFAULT_IMAGE_CROP_POSITION,
    DEFAULT_IMAGE_ZOOM,
    DEFAULT_IMAGE_BLUR_STRENGTH,
    DEFAULT_IMAGE_BACKGROUND_BRIGHTNESS,
    DEFAULT_SEGMENT_ID,
    DEFAULT_SOURCE_STABILIZATION,
    DEFAULT_DEVICE_WARMUP_DELAY,
    DEFAULT_TRANSITION_SECONDS,
    DEFAULT_TRANSITION_STYLE,
    DEFAULT_THEME_COLOR_MODE,
    DEFAULT_THEME_LIGHT_TRANSITION,
    DEFAULT_THEME_TURN_ON,
    DEFAULT_PREVENT_DARK_COLORS,
    DEFAULT_BALANCE_THEME_SPECTRUM,
    DEFAULT_THEME_COLOR_ADJUSTMENTS,
    DEFAULT_NO_ART_BEHAVIOR,
    DEFAULT_NO_ART_DURING_SESSION,
    DEFAULT_NO_ART_COLOR,
    DEFAULT_NO_ART_BRIGHTNESS,
    DEFAULT_ONLINE_ARTWORK_LOOKUP,
    DEFAULT_WIDTH,
    DOMAIN,
    AUTO_POWER_MODES,
    THEME_FADE_MODES,
    THEME_COLOR_ADJUSTMENT_MODES,
    NO_ART_BEHAVIORS,
    NO_ART_DURING_SESSION_BEHAVIORS,
    artwork_provider_order,
    normalize_end_behavior,
)

def _entry_targets(entry) -> list[str]:
    """Return matrix targets for an entry, respecting an explicit empty list."""
    return configured_matrix_entities(dict(entry.options), dict(entry.data))


def _normalize_targets(value) -> list[str]:
    """Normalize a target selector value while supporting old singular values."""
    return normalize_entity_list(value)


_TRANSITION_OPTIONS = [
    {"value": "instant", "label": "Instant cut"},
    {"value": "fade", "label": "Fade / crossfade (recommended)"},
    {"value": "shuffle", "label": "Shuffle transition style on each album change"},
    {"value": "fairy_dust", "label": "Fairy Dust"},
    {"value": "swipe_right", "label": "Swipe right"},
    {"value": "swipe_left", "label": "Swipe left"},
    {"value": "swipe_up", "label": "Swipe up"},
    {"value": "swipe_down", "label": "Swipe down"},
    {"value": "swipe_top_left", "label": "Diagonal swipe: top-left"},
    {"value": "swipe_top_right", "label": "Diagonal swipe: top-right"},
    {"value": "swipe_bottom_right", "label": "Diagonal swipe: bottom-right"},
    {"value": "swipe_bottom_left", "label": "Diagonal swipe: bottom-left"},
    {"value": "push_right", "label": "Push right"},
    {"value": "push_left", "label": "Push left"},
    {"value": "push_up", "label": "Push up"},
    {"value": "push_down", "label": "Push down"},
    {"value": "outside_in", "label": "Outside in"},
    {"value": "inside_out", "label": "Inside out"},
    {"value": "open_horizontal", "label": "Open horizontally"},
    {"value": "open_vertical", "label": "Open vertically"},
    {"value": "circular_out", "label": "Circular out"},
    {"value": "circular_in", "label": "Circular in"},
]
_THEME_COLOR_MODE_OPTIONS = [
    {"value": "palette", "label": "Artwork palette — spread colors found on the cover across lights (recommended)"},
    {"value": "contrast", "label": "Dominant + contrast — lead with the main color, then use the most distinct cover colors"},
    {"value": "shared", "label": "Dominant color — use the cover's main color on every light"},
    {"value": "vibrant", "label": "Vibrant accents — main color first, then the cover's most saturated colors"},
    {"value": "complementary", "label": "Complementary accent — main cover color plus its opposite hue for contrast"},
    {"value": "analogous", "label": "Analogous flow — coordinated neighboring hues derived from the main cover color"},
    {"value": "cinematic", "label": "Cinematic — subdued main color with a vivid accent found in the cover"},
    {"value": "monochrome", "label": "Monochrome tones — one cover-derived hue in a tonal gradient"},
]
_ROOM_END_BEHAVIOR_OPTIONS = [
    {"value": "restore_color", "label": "Restore previous color (leave brightness unchanged)"},
    {"value": "restore_color_brightness", "label": "Restore previous color and brightness"},
    {"value": "keep", "label": "Keep the music lighting"},
    {"value": "turn_off", "label": "Turn room lights off"},
]
_MATRIX_END_BEHAVIOR_OPTIONS = [
    {"value": "restore_previous", "label": "Restore previous matrix state"},
    {"value": "keep", "label": "Keep the last artwork"},
    {"value": "turn_off", "label": "Turn matrix off"},
]
_PAUSE_BEHAVIOR_OPTIONS = [
    {"value": "end_after_grace", "label": "End the session after the grace period (recommended)"},
    {"value": "hold", "label": "Keep the room scene until playback resumes"},
]
_IMAGE_FIT_OPTIONS = [
    {"value": "crop", "label": "Fill matrix (crop to fill)"},
    {"value": "contain", "label": "Fit entire image (black bars)"},
    {"value": "blurred_background_soft", "label": "Fit image over soft blurred background"},
    {"value": "blurred_background", "label": "Fit image over medium blurred background"},
    {"value": "blurred_background_strong", "label": "Fit image over strongly blurred background"},
    {"value": "blurred_background_custom", "label": "Fit image over adjustable blurred background"},
    {"value": "solid_background", "label": "Fit image over dominant cover color"},
    {"value": "mirrored_background", "label": "Fit image over mirrored cover edges"},
]
_IMAGE_CROP_POSITION_OPTIONS = [
    {"value": "top_left", "label": "Top left"},
    {"value": "top", "label": "Top"},
    {"value": "top_right", "label": "Top right"},
    {"value": "left", "label": "Left"},
    {"value": "center", "label": "Center"},
    {"value": "right", "label": "Right"},
    {"value": "bottom_left", "label": "Bottom left"},
    {"value": "bottom", "label": "Bottom"},
    {"value": "bottom_right", "label": "Bottom right"},
]
_AUTO_POWER_OPTIONS = [
    {"value": "all", "label": "Power on all selected outputs (recommended)"},
    {"value": "matrix", "label": "Power on the matrix only"},
    {"value": "theme", "label": "Power on theme lights only"},
    {"value": "none", "label": "Do not power on outputs"},
]
_THEME_FADE_OPTIONS = [
    {"value": "matrix_black", "label": "Fade to black with the matrix (when enabled)"},
    {"value": "colors", "label": "Fade directly between album colors"},
    {"value": "instant", "label": "Don't fade (change colors instantly)"},
    {"value": "device_default", "label": "Use each light's default transition"},
]
_THEME_COLOR_ADJUSTMENT_OPTIONS = [
    {"value": "none", "label": "Use extracted colors as-is"},
    {"value": "avoid_dark", "label": "Lift near-black colors"},
    {"value": "balance", "label": "Balance color brightness"},
    {"value": "both", "label": "Lift near-black and balance brightness"},
]
_NO_ART_BEHAVIOR_OPTIONS = [
    {"value": "fallback_color", "label": "Use fallback color on room lights; keep matrix off"},
    {"value": "turn_off", "label": "Turn selected outputs off"},
    {"value": "wait", "label": "Leave lights unchanged until cover art appears (recommended)"},
]
_NO_ART_DURING_SESSION_OPTIONS = [
    {"value": "keep_previous", "label": "Keep the current scene (recommended)"},
    {"value": "fallback_color", "label": "Use fallback color on room lights; keep matrix off"},
    {"value": "turn_off", "label": "Turn selected outputs off"},
]
_ARTWORK_PROVIDER_FIELDS = tuple(f"artwork_provider_{index}" for index in range(1, 5))
_ARTWORK_PROVIDER_OPTIONS = [
    {"value": "disabled", "label": "Disabled"},
    {"value": "musicbrainz", "label": "MusicBrainz / Cover Art Archive (no key)"},
    {"value": "deezer", "label": "Deezer (no key)"},
    {"value": "lastfm", "label": "Last.fm (API key required)"},
    {"value": "theaudiodb", "label": "TheAudioDB (shared free key or personal key)"},
]


class WLEDAlbumArtConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure the WLED target and an initial media-player source."""

    VERSION = 2

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            source = user_input[CONF_SOURCE_ENTITY]
            targets = _normalize_targets(
                user_input.get(CONF_TARGET_ENTITY, user_input.get(CONF_TARGET_ENTITIES))
            )[:1]
            if self.hass.states.get(source) is None:
                return self.async_show_form(
                    step_id="user", data_schema=self._schema(user_input),
                    errors={"base": "source_missing"}
                )

            entity_registry = er.async_get(self.hass)
            for target in targets:
                target_entry = entity_registry.async_get(target)
                if target_entry is None or target_entry.platform != "wled":
                    return self.async_show_form(
                        step_id="user", data_schema=self._schema(user_input),
                        errors={"base": "target_not_wled"}
                    )
                wled_config = self.hass.config_entries.async_get_entry(target_entry.config_entry_id)
                if wled_config is None or wled_config.domain != "wled" or not wled_config.data.get(CONF_HOST):
                    return self.async_show_form(
                        step_id="user", data_schema=self._schema(user_input),
                        errors={"base": "wled_config_missing"}
                    )
            selected = set(targets)
            for other in self.hass.config_entries.async_entries(DOMAIN):
                other_outputs = set(_entry_targets(other)) | set(normalize_entity_list(
                    other.options.get(CONF_THEME_LIGHT_ENTITIES, [])
                ))
                if selected.intersection(other_outputs):
                    return self.async_show_form(
                        step_id="user", data_schema=self._schema(user_input),
                        errors={"base": "target_already_configured"}
                    )

            normalized = dict(user_input)
            normalized[CONF_TARGET_ENTITY] = targets[0] if targets else ""
            normalized.pop(CONF_TARGET_ENTITIES, None)
            if targets:
                first_target = targets[0]
                title = f"Music artwork → {first_target}"
            else:
                title = f"Music lighting → {source}"
            return self.async_create_entry(title=title, data=normalized)

        return self.async_show_form(step_id="user", data_schema=self._schema())

    @staticmethod
    def _schema(current=None):
        current = current or {}
        source_key = (
            vol.Required(CONF_SOURCE_ENTITY, default=current[CONF_SOURCE_ENTITY])
            if current.get(CONF_SOURCE_ENTITY)
            else vol.Required(CONF_SOURCE_ENTITY)
        )
        targets = _normalize_targets(current.get(CONF_TARGET_ENTITY, current.get(CONF_TARGET_ENTITIES)))[:1]
        target_key = vol.Optional(CONF_TARGET_ENTITY, default=targets[0] if targets else None)
        return vol.Schema({
            source_key: selector.EntitySelector(
                selector.EntitySelectorConfig(domain="media_player")
            ),
            target_key: selector.EntitySelector(
                selector.EntitySelectorConfig(domain="light", integration="wled")
            ),
            vol.Optional(CONF_PIN, default=current.get(CONF_PIN, "")): str,
        })

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return WLEDAlbumArtOptionsFlow()


class WLEDAlbumArtOptionsFlow(config_entries.OptionsFlow):
    """Manage playback, matrix display, room lighting, and session behavior."""

    async def async_step_init(self, user_input=None):
        """Choose sources and outputs before showing output-specific tuning."""
        if user_input is None:
            return self.async_show_form(
                step_id="init", data_schema=self._selection_schema()
            )

        selected = self._flatten_sections(user_input)
        targets = _normalize_targets(selected.get(CONF_TARGET_ENTITY))[:1]
        error = self._validate_target(
            targets, normalize_entity_list(selected.get(CONF_THEME_LIGHT_ENTITIES))
        )
        if error:
            return self.async_show_form(
                step_id="init", data_schema=self._selection_schema(selected),
                errors={"base": error},
                description_placeholders={"entities": getattr(self, "_conflicting_outputs", "")},
            )

        selected[CONF_TARGET_ENTITY] = targets[0] if targets else ""
        selected[CONF_SOURCE_ENTITIES] = normalize_entity_list(
            selected.get(CONF_SOURCE_ENTITIES)
        )
        selected[CONF_THEME_LIGHT_ENTITIES] = normalize_entity_list(
            selected.get(CONF_THEME_LIGHT_ENTITIES)
        )
        selected[CONF_PIN] = str(selected.get(CONF_PIN, "") or "")
        self._pending_selection = selected
        return await self.async_step_tuning()

    async def async_step_tuning(self, user_input=None):
        """Tune only the outputs selected on the previous step."""
        current = dict(self.config_entry.options)
        pending = getattr(self, "_pending_selection", {})
        defaults = {**current, **pending}
        matrix_selected = bool(_normalize_targets(defaults.get(CONF_TARGET_ENTITY)))
        theme_selected = bool(defaults.get(CONF_THEME_LIGHT_ENTITIES))
        schema = self._tuning_schema(defaults, matrix_selected, theme_selected)

        if user_input is None:
            return self.async_show_form(step_id="tuning", data_schema=schema)

        options = {**current, **pending, **self._flatten_sections(user_input)}
        targets = _normalize_targets(options.get(CONF_TARGET_ENTITY))[:1]
        options[CONF_TARGET_ENTITY] = targets[0] if targets else ""
        options.pop(CONF_TARGET_ENTITIES, None)
        options.pop("enable_matrix", None)
        options[CONF_PIN] = str(options.get(
            CONF_PIN, self.config_entry.data.get(CONF_PIN, "")
        ) or "")
        options[CONF_SOURCE_ENTITIES] = normalize_entity_list(
            options.get(CONF_SOURCE_ENTITIES)
        )
        options[CONF_THEME_LIGHT_ENTITIES] = normalize_entity_list(
            options.get(CONF_THEME_LIGHT_ENTITIES)
        )
        if options.get(CONF_TRANSITION_STYLE) in ("crossfade", "fade_black"):
            options[CONF_TRANSITION_STYLE] = "fade"
        if targets:
            power_mode = options.get(CONF_AUTO_POWER_MODE, DEFAULT_AUTO_POWER_MODE)
            options[CONF_MATRIX_TURN_ON] = power_mode in {"all", "matrix"}
        theme_selected = bool(options.get(CONF_THEME_LIGHT_ENTITIES))
        if theme_selected:
            power_mode = options.get(CONF_AUTO_POWER_MODE, DEFAULT_AUTO_POWER_MODE)
            options[CONF_THEME_TURN_ON] = power_mode in {"all", "theme"}
        fade_mode = options.get(CONF_THEME_FADE_MODE, DEFAULT_THEME_FADE_MODE)
        options[CONF_FADE_THEME_WITH_MATRIX] = fade_mode == "matrix_black"
        adjustments = options.get(
            CONF_THEME_COLOR_ADJUSTMENTS, DEFAULT_THEME_COLOR_ADJUSTMENTS
        )
        options[CONF_PREVENT_DARK_COLORS] = adjustments in {"avoid_dark", "both"}
        options[CONF_BALANCE_THEME_SPECTRUM] = adjustments in {"balance", "both"}
        room_end, matrix_end = normalize_end_behavior(options)
        options[CONF_ROOM_END_BEHAVIOR] = room_end
        options[CONF_MATRIX_END_BEHAVIOR] = matrix_end
        options[CONF_RESTORE_THEME_BRIGHTNESS] = room_end == "restore_color_brightness"
        no_art_behavior = options.get(CONF_NO_ART_BEHAVIOR, DEFAULT_NO_ART_BEHAVIOR)
        options[CONF_NO_ART_BEHAVIOR] = (
            no_art_behavior if no_art_behavior in NO_ART_BEHAVIORS
            else DEFAULT_NO_ART_BEHAVIOR
        )
        try:
            color = [max(0, min(255, int(channel))) for channel in options.get(
                CONF_NO_ART_COLOR, DEFAULT_NO_ART_COLOR
            )]
        except (TypeError, ValueError):
            color = list(DEFAULT_NO_ART_COLOR)
        options[CONF_NO_ART_COLOR] = color if len(color) == 3 else list(DEFAULT_NO_ART_COLOR)
        options[CONF_NO_ART_BRIGHTNESS] = max(0, min(100, int(options.get(
            CONF_NO_ART_BRIGHTNESS, DEFAULT_NO_ART_BRIGHTNESS
        ))))
        if any(field in options for field in _ARTWORK_PROVIDER_FIELDS):
            options[CONF_ARTWORK_PROVIDERS] = [
                options.get(field, "disabled") for field in _ARTWORK_PROVIDER_FIELDS
            ]
        options[CONF_ARTWORK_PROVIDERS] = list(artwork_provider_order(options))
        for field in _ARTWORK_PROVIDER_FIELDS:
            options.pop(field, None)
        options.pop(CONF_ARTWORK_PROVIDER_PRIORITY, None)
        options[CONF_LASTFM_API_KEY] = str(
            options.get(CONF_LASTFM_API_KEY, "") or ""
        ).strip()
        options[CONF_THEAUDIODB_API_KEY] = str(
            options.get(CONF_THEAUDIODB_API_KEY, "") or ""
        ).strip()
        ignored_inputs = options.get(CONF_IGNORED_INPUTS, "")
        if isinstance(ignored_inputs, str):
            ignored_inputs = ignored_inputs.replace("\n", ",").split(",")
        options[CONF_IGNORED_INPUTS] = ", ".join(dict.fromkeys(
            str(item).strip() for item in (ignored_inputs or []) if str(item).strip()
        ))

        legacy_source = self.config_entry.data.get(CONF_SOURCE_ENTITY)
        source_for_title = (
            options[CONF_SOURCE_ENTITIES][0]
            if options[CONF_SOURCE_ENTITIES] else legacy_source or "source"
        )
        new_title = (
            f"Music artwork → {targets[0]}" if targets
            else f"Music lighting → {source_for_title}"
        )
        self.hass.config_entries.async_update_entry(self.config_entry, title=new_title)
        return self.async_create_entry(title="", data=options)

    @staticmethod
    def _flatten_sections(user_input: dict) -> dict:
        """Keep nested UI sections stored as the integration's flat option keys."""
        flattened = {}
        for key, value in user_input.items():
            if isinstance(value, dict):
                flattened.update(value)
            else:
                flattened[key] = value
        return flattened

    def _selection_defaults(self, selected=None) -> dict:
        current = self.config_entry.options
        legacy_source = self.config_entry.data.get(CONF_SOURCE_ENTITY)
        defaults = {
            CONF_SOURCE_ENTITIES: normalize_entity_list(current.get(
                CONF_SOURCE_ENTITIES, [legacy_source] if legacy_source else []
            )),
            CONF_SOURCE_STABILIZATION: current.get(
                CONF_SOURCE_STABILIZATION, DEFAULT_SOURCE_STABILIZATION
            ),
            CONF_TARGET_ENTITY: (
                _entry_targets(self.config_entry)[0] if _entry_targets(self.config_entry) else None
            ),
            CONF_THEME_LIGHT_ENTITIES: normalize_entity_list(
                current.get(CONF_THEME_LIGHT_ENTITIES, [])
            ),
            CONF_PIN: current.get(CONF_PIN, self.config_entry.data.get(CONF_PIN, "")),
            CONF_DEVICE_WARMUP_DELAY: current.get(
                CONF_DEVICE_WARMUP_DELAY, DEFAULT_DEVICE_WARMUP_DELAY
            ),
        }
        if selected:
            defaults.update(selected)
        defaults[CONF_SOURCE_ENTITIES] = normalize_entity_list(
            defaults.get(CONF_SOURCE_ENTITIES)
        )
        defaults[CONF_THEME_LIGHT_ENTITIES] = normalize_entity_list(
            defaults.get(CONF_THEME_LIGHT_ENTITIES)
        )
        return defaults

    def _selection_schema(self, selected=None):
        defaults = self._selection_defaults(selected)
        playback = vol.Schema({
            vol.Optional(CONF_SOURCE_ENTITIES, default=defaults[CONF_SOURCE_ENTITIES]): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="media_player", multiple=True, reorder=True)
            ),
            vol.Required(CONF_SOURCE_STABILIZATION, default=defaults[CONF_SOURCE_STABILIZATION]): vol.All(
                float, vol.Range(min=0.3, max=10.0)
            ),
        })
        outputs = vol.Schema({
            vol.Optional(CONF_TARGET_ENTITY, default=defaults[CONF_TARGET_ENTITY]): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="light", integration="wled")
            ),
            vol.Optional(CONF_THEME_LIGHT_ENTITIES, default=defaults[CONF_THEME_LIGHT_ENTITIES]): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="light", multiple=True, reorder=True)
            ),
            vol.Optional(CONF_PIN, default=defaults[CONF_PIN]): str,
            vol.Required(CONF_DEVICE_WARMUP_DELAY, default=defaults[CONF_DEVICE_WARMUP_DELAY]): vol.All(
                int, vol.Range(min=0, max=60)
            ),
        })
        return vol.Schema({
            vol.Required("playback"): section(playback, {"collapsed": False}),
            vol.Required("outputs"): section(outputs, {"collapsed": False}),
        })

    def _validate_target(self, targets: list[str], theme_lights: list[str] | None = None) -> str | None:
        """Validate WLED ownership before using the selection to build step two."""
        entity_registry = er.async_get(self.hass)
        for selected_target in targets:
            target_entity = entity_registry.async_get(selected_target)
            if target_entity is None or target_entity.platform != "wled":
                return "target_not_wled"
            wled_entry = self.hass.config_entries.async_get_entry(target_entity.config_entry_id)
            if wled_entry is None or wled_entry.domain != "wled" or not wled_entry.data.get(CONF_HOST):
                return "wled_config_missing"
        theme_set = set(theme_lights or [])
        for entity_id in theme_set:
            registered = entity_registry.async_get(entity_id)
            if registered is not None and registered.platform == DOMAIN:
                self._conflicting_outputs = entity_id
                return "output_not_physical"
        overlap = set(targets).intersection(theme_set)
        if overlap:
            self._conflicting_outputs = ", ".join(sorted(overlap))
            return "output_roles_overlap"
        selected_set = set(targets) | theme_set
        for other in self.hass.config_entries.async_entries(DOMAIN):
            if other.entry_id == self.config_entry.entry_id:
                continue
            other_outputs = set(_entry_targets(other)) | set(normalize_entity_list(
                other.options.get(CONF_THEME_LIGHT_ENTITIES, [])
            ))
            overlap = selected_set.intersection(other_outputs)
            if overlap:
                self._conflicting_outputs = ", ".join(sorted(overlap))
                return "output_already_configured"
        return None

    @staticmethod
    def _default_auto_power_mode(current: dict, matrix_selected: bool, theme_selected: bool) -> str:
        """Preserve the old per-output power switches as one combined choice."""
        mode = current.get(CONF_AUTO_POWER_MODE)
        if mode in AUTO_POWER_MODES and matrix_selected and theme_selected:
            return mode
        if mode in AUTO_POWER_MODES and matrix_selected:
            return "all" if mode in {"all", "matrix"} else "none"
        if mode in AUTO_POWER_MODES and theme_selected:
            return "all" if mode in {"all", "theme"} else "none"
        matrix_on = bool(current.get(CONF_MATRIX_TURN_ON, DEFAULT_MATRIX_TURN_ON)) if matrix_selected else False
        theme_on = bool(current.get(CONF_THEME_TURN_ON, DEFAULT_THEME_TURN_ON)) if theme_selected else False
        if not matrix_selected or not theme_selected:
            return "all" if matrix_on or theme_on else "none"
        if matrix_on and theme_on:
            return "all"
        if matrix_on:
            return "matrix"
        if theme_on:
            return "theme"
        return "none"

    @staticmethod
    def _default_theme_fade_mode(current: dict, matrix_selected: bool = True) -> str:
        """Migrate the old fade-with-matrix toggle to a single mode."""
        mode = current.get(CONF_THEME_FADE_MODE)
        if mode in THEME_FADE_MODES:
            return "colors" if not matrix_selected and mode == "matrix_black" else mode
        mode = "matrix_black" if current.get(
            CONF_FADE_THEME_WITH_MATRIX, DEFAULT_FADE_THEME_WITH_MATRIX
        ) else "colors"
        return "colors" if not matrix_selected and mode == "matrix_black" else mode

    @staticmethod
    def _default_color_adjustments(current: dict) -> str:
        """Combine the legacy dark-color and spectrum switches into one value."""
        mode = current.get(CONF_THEME_COLOR_ADJUSTMENTS)
        if mode in THEME_COLOR_ADJUSTMENT_MODES:
            return mode
        avoid_dark = current.get(CONF_PREVENT_DARK_COLORS, DEFAULT_PREVENT_DARK_COLORS)
        balance = current.get(CONF_BALANCE_THEME_SPECTRUM, DEFAULT_BALANCE_THEME_SPECTRUM)
        return "both" if avoid_dark and balance else (
            "avoid_dark" if avoid_dark else "balance" if balance else "none"
        )

    def _tuning_schema(self, current, matrix_selected: bool, theme_selected: bool):
        default_transition = current.get(CONF_TRANSITION_STYLE, DEFAULT_TRANSITION_STYLE)
        if default_transition in ("crossfade", "fade_black"):
            default_transition = "fade"

        provider_order = artwork_provider_order(current)
        artwork_fields = vol.Schema({
            vol.Required(
                CONF_ANIMATED_ARTWORK,
                default=current.get(CONF_ANIMATED_ARTWORK, DEFAULT_ANIMATED_ARTWORK),
            ): selector.BooleanSelector(),
            vol.Required(CONF_ONLINE_ARTWORK_LOOKUP, default=current.get(
                CONF_ONLINE_ARTWORK_LOOKUP, DEFAULT_ONLINE_ARTWORK_LOOKUP
            )): selector.BooleanSelector(),
            **{
                vol.Required(field, default=(
                    provider_order[index] if index < len(provider_order) else "disabled"
                )): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=_ARTWORK_PROVIDER_OPTIONS,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )
                for index, field in enumerate(_ARTWORK_PROVIDER_FIELDS)
            },
            vol.Optional(CONF_LASTFM_API_KEY, default=current.get(
                CONF_LASTFM_API_KEY, ""
            )): selector.TextSelector(
                selector.TextSelectorConfig(type="password")
            ),
            vol.Optional(CONF_THEAUDIODB_API_KEY, default=current.get(
                CONF_THEAUDIODB_API_KEY, ""
            )): selector.TextSelector(
                selector.TextSelectorConfig(type="password")
            ),
        })
        matrix_fields = vol.Schema({
            vol.Required(CONF_AUTO_DETECT_SIZE, default=current.get(CONF_AUTO_DETECT_SIZE, DEFAULT_AUTO_DETECT_SIZE)): selector.BooleanSelector(),
            vol.Required(CONF_WIDTH, default=current.get(CONF_WIDTH, DEFAULT_WIDTH)): vol.All(int, vol.Range(min=1, max=128)),
            vol.Required(CONF_HEIGHT, default=current.get(CONF_HEIGHT, DEFAULT_HEIGHT)): vol.All(int, vol.Range(min=1, max=128)),
            vol.Required(CONF_IMAGE_FIT, default=current.get(CONF_IMAGE_FIT, DEFAULT_IMAGE_FIT)): selector.SelectSelector(
                selector.SelectSelectorConfig(options=_IMAGE_FIT_OPTIONS, mode=selector.SelectSelectorMode.DROPDOWN)
            ),
            vol.Required(
                CONF_IMAGE_CROP_POSITION,
                default=current.get(CONF_IMAGE_CROP_POSITION, DEFAULT_IMAGE_CROP_POSITION),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_IMAGE_CROP_POSITION_OPTIONS,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                CONF_IMAGE_ZOOM, default=current.get(CONF_IMAGE_ZOOM, DEFAULT_IMAGE_ZOOM)
            ): vol.All(int, vol.Range(min=100, max=200)),
            vol.Required(
                CONF_IMAGE_BLUR_STRENGTH,
                default=current.get(CONF_IMAGE_BLUR_STRENGTH, DEFAULT_IMAGE_BLUR_STRENGTH),
            ): vol.All(int, vol.Range(min=0, max=40)),
            vol.Required(
                CONF_IMAGE_BACKGROUND_BRIGHTNESS,
                default=current.get(
                    CONF_IMAGE_BACKGROUND_BRIGHTNESS,
                    DEFAULT_IMAGE_BACKGROUND_BRIGHTNESS,
                ),
            ): vol.All(int, vol.Range(min=0, max=100)),
            vol.Required(CONF_TRANSITION_STYLE, default=default_transition): selector.SelectSelector(
                selector.SelectSelectorConfig(options=_TRANSITION_OPTIONS, mode=selector.SelectSelectorMode.DROPDOWN)
            ),
            vol.Required(CONF_TRANSITION_SECONDS, default=current.get(CONF_TRANSITION_SECONDS, DEFAULT_TRANSITION_SECONDS)): vol.All(float, vol.Range(min=0.1, max=5.0)),
            vol.Required(CONF_FADE_TO_BLACK, default=current.get(CONF_FADE_TO_BLACK, DEFAULT_FADE_TO_BLACK)): selector.BooleanSelector(),
            vol.Required(CONF_BLACK_PAUSE, default=current.get(CONF_BLACK_PAUSE, DEFAULT_BLACK_PAUSE)): vol.All(float, vol.Range(min=0.0, max=2.0)),
            vol.Required(CONF_FILENAME, default=current.get(CONF_FILENAME, DEFAULT_FILENAME)): str,
            vol.Required(CONF_SEGMENT_ID, default=current.get(CONF_SEGMENT_ID, DEFAULT_SEGMENT_ID)): vol.All(int, vol.Range(min=0, max=31)),
        })
        theme_fade_options = _THEME_FADE_OPTIONS if matrix_selected else [
            item for item in _THEME_FADE_OPTIONS if item["value"] != "matrix_black"
        ]
        theme_fields = vol.Schema({
            vol.Required(CONF_THEME_COLOR_MODE, default=current.get(CONF_THEME_COLOR_MODE, DEFAULT_THEME_COLOR_MODE)): selector.SelectSelector(
                selector.SelectSelectorConfig(options=_THEME_COLOR_MODE_OPTIONS, mode=selector.SelectSelectorMode.DROPDOWN)
            ),
            vol.Required(CONF_THEME_LIGHT_TRANSITION, default=current.get(CONF_THEME_LIGHT_TRANSITION, DEFAULT_THEME_LIGHT_TRANSITION)): vol.All(float, vol.Range(min=0.0, max=10.0)),
            vol.Required(CONF_THEME_FADE_MODE, default=self._default_theme_fade_mode(
                current, matrix_selected
            )): selector.SelectSelector(
                selector.SelectSelectorConfig(options=theme_fade_options, mode=selector.SelectSelectorMode.DROPDOWN)
            ),
            vol.Required(CONF_THEME_COLOR_ADJUSTMENTS, default=self._default_color_adjustments(current)): selector.SelectSelector(
                selector.SelectSelectorConfig(options=_THEME_COLOR_ADJUSTMENT_OPTIONS, mode=selector.SelectSelectorMode.DROPDOWN)
            ),
        })

        no_art_fields = vol.Schema({
            vol.Required(CONF_NO_ART_BEHAVIOR, default=current.get(
                CONF_NO_ART_BEHAVIOR, DEFAULT_NO_ART_BEHAVIOR
            )): selector.SelectSelector(
                selector.SelectSelectorConfig(options=_NO_ART_BEHAVIOR_OPTIONS, mode=selector.SelectSelectorMode.DROPDOWN)
            ),
            vol.Required(CONF_NO_ART_DURING_SESSION, default=current.get(
                CONF_NO_ART_DURING_SESSION, DEFAULT_NO_ART_DURING_SESSION
            )): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_NO_ART_DURING_SESSION_OPTIONS,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
        })
        source_filter_fields = vol.Schema({
            vol.Optional(CONF_IGNORED_INPUTS, default=current.get(
                CONF_IGNORED_INPUTS, ""
            )): selector.TextSelector(
                selector.TextSelectorConfig(multiline=True)
            ),
        })

        auto_power_options = _AUTO_POWER_OPTIONS
        if not matrix_selected or not theme_selected:
            label = "Power on the selected output if it is off" if matrix_selected or theme_selected else "Power on selected outputs"
            auto_power_options = [
                {"value": "all", "label": f"{label} (recommended)"},
                {"value": "none", "label": "Do not power on outputs"},
            ]
        power_fields = vol.Schema({
            vol.Required(CONF_AUTO_POWER_MODE, default=self._default_auto_power_mode(
                current, matrix_selected, theme_selected
            )): selector.SelectSelector(
                selector.SelectSelectorConfig(options=auto_power_options, mode=selector.SelectSelectorMode.DROPDOWN)
            ),
        })

        room_end, matrix_end = normalize_end_behavior(current, matrix_selected)
        end_fields = {}
        if theme_selected:
            end_fields[vol.Required(CONF_ROOM_END_BEHAVIOR, default=room_end)] = selector.SelectSelector(
                selector.SelectSelectorConfig(options=_ROOM_END_BEHAVIOR_OPTIONS, mode=selector.SelectSelectorMode.DROPDOWN)
            )
        if matrix_selected:
            end_fields[vol.Required(CONF_MATRIX_END_BEHAVIOR, default=matrix_end)] = selector.SelectSelector(
                selector.SelectSelectorConfig(options=_MATRIX_END_BEHAVIOR_OPTIONS, mode=selector.SelectSelectorMode.DROPDOWN)
            )
        session_fields = vol.Schema({
            **end_fields,
            vol.Required(CONF_PAUSE_BEHAVIOR, default=current.get(
                CONF_PAUSE_BEHAVIOR, DEFAULT_PAUSE_BEHAVIOR
            )): selector.SelectSelector(
                selector.SelectSelectorConfig(options=_PAUSE_BEHAVIOR_OPTIONS, mode=selector.SelectSelectorMode.DROPDOWN)
            ),
            vol.Required(CONF_END_GRACE, default=current.get(CONF_END_GRACE, DEFAULT_END_GRACE)): vol.All(int, vol.Range(min=0, max=300)),
        })
        fields = {vol.Required("session_end"): section(session_fields, {"collapsed": False})}
        fields[vol.Required("artwork")] = section(artwork_fields, {"collapsed": False})
        fields[vol.Required("source_filter")] = section(
            source_filter_fields, {"collapsed": True}
        )
        if matrix_selected or theme_selected:
            fields[vol.Required("no_art")] = section(no_art_fields, {"collapsed": False})
        if matrix_selected or theme_selected:
            fields[vol.Required("power")] = section(power_fields, {"collapsed": False})
        if matrix_selected:
            fields[vol.Required("matrix")] = section(matrix_fields, {"collapsed": False})
        if theme_selected:
            fields[vol.Required("room_lighting")] = section(theme_fields, {"collapsed": False})
        return vol.Schema(fields)
