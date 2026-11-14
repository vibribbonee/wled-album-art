"""Playback/session coordinator for the Music Artwork Lighting integration."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from copy import deepcopy
from datetime import datetime, timezone
from functools import partial
from math import ceil
from pathlib import PurePosixPath

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
)
from homeassistant.helpers.storage import Store

from .artwork_data import PreparedArtwork, prepare_artwork_data
from .artwork_models import NoArtKey, PlayerArtwork, TrackKey
from .const import (
    CONF_ANIMATED_ARTWORK,
    CONF_AUTO_DETECT_SIZE,
    CONF_AUTO_POWER_MODE,
    CONF_BLACK_PAUSE,
    CONF_FADE_TO_BLACK,
    CONF_FADE_THEME_WITH_MATRIX,
    CONF_THEME_FADE_MODE,
    CONF_FILENAME,
    CONF_END_BEHAVIOR,
    CONF_ROOM_END_BEHAVIOR,
    CONF_MATRIX_END_BEHAVIOR,
    CONF_END_GRACE,
    CONF_PAUSE_BEHAVIOR,
    CONF_MATRIX_OUTPUT_ENABLED,
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
    CONF_SOURCE_STABILIZATION,
    CONF_DEVICE_WARMUP_DELAY,
    CONF_SOURCE_ENTITY,
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
    CONF_NO_ART_LAST_COLOR,
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
    DEFAULT_FADE_THEME_WITH_MATRIX,
    DEFAULT_THEME_FADE_MODE,
    DEFAULT_FILENAME,
    DEFAULT_END_GRACE,
    DEFAULT_PAUSE_BEHAVIOR,
    DEFAULT_MATRIX_OUTPUT_ENABLED,
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
    DEFAULT_ARTWORK_PROVIDER_PRIORITY,
    artwork_provider_order,
    normalize_end_behavior,
    DEFAULT_WIDTH,
    DOMAIN,
    AUTO_POWER_MODES,
    THEME_FADE_MODES,
    THEME_COLOR_ADJUSTMENT_MODES,
    NO_ART_BEHAVIORS,
    NO_ART_DURING_SESSION_BEHAVIORS,
    IMAGE_CROP_POSITIONS,
    TRANSITION_BLEND_STYLES,
)
from .artwork_fetcher import ArtworkFetcher
from .matrix_control import MatrixOutput
from .online_artwork import OnlineArtworkLookup
from .music_metadata import artwork_match_description
from .source_flow import SourceCandidate, first_playing_source, source_change_affects_artwork
from .error_utils import safe_error_text as _safe_error_text
from .image_processing import (
    balance_color_spectrum, ensure_visible_color,
    build_theme_colors, prepare_image,
)
from .selection import (
    configured_matrix_entities, first_priority_candidate, normalize_entity_list,
)
from .session_journal import new_session_journal, plan_session_end
from .transitions import choose_transition_style
from .wled_client import WLEDClient

_LOGGER = logging.getLogger(__name__)

# These options can be safely applied without a full integration reload.
# Hardware selection, dimensions, and source lists still use Home Assistant's
# normal reload flow. Timing controls are applied live to future scheduling and
# device recovery events.
LIVE_TUNABLE_OPTIONS = {
    CONF_ROOM_END_BEHAVIOR,
    CONF_MATRIX_END_BEHAVIOR,
    CONF_NO_ART_LAST_COLOR,
    CONF_ANIMATED_ARTWORK,
    CONF_THEME_COLOR_MODE,
    CONF_TRANSITION_STYLE,
    CONF_TRANSITION_SECONDS,
    CONF_THEME_LIGHT_TRANSITION,
    CONF_IMAGE_FIT,
    CONF_IMAGE_CROP_POSITION,
    CONF_IMAGE_ZOOM,
    CONF_IMAGE_BLUR_STRENGTH,
    CONF_IMAGE_BACKGROUND_BRIGHTNESS,
    CONF_END_BEHAVIOR,
    CONF_END_GRACE,
    CONF_PAUSE_BEHAVIOR,
    CONF_SOURCE_STABILIZATION,
    CONF_DEVICE_WARMUP_DELAY,
    CONF_BLACK_PAUSE,
    CONF_MATRIX_OUTPUT_ENABLED,
    CONF_MATRIX_TURN_ON,
    CONF_AUTO_POWER_MODE,
    CONF_FADE_TO_BLACK,
    CONF_FADE_THEME_WITH_MATRIX,
    CONF_THEME_FADE_MODE,
    CONF_THEME_TURN_ON,
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
    CONF_PREVENT_DARK_COLORS,
    CONF_BALANCE_THEME_SPECTRUM,
    CONF_RESTORE_THEME_BRIGHTNESS,
}


class AlbumArtManager:
    """Coordinate one music session across its players, matrices, and room lights."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._applied_entry_options = dict(entry.options)
        self._live_options_lock = asyncio.Lock()
        self.session = async_get_clientsession(hass)
        self._artwork_fetcher = ArtworkFetcher(hass, self.session)
        self._online_artwork_lookup = OnlineArtworkLookup(self.session)
        self._animated_artwork_lookup = OnlineArtworkLookup(self.session, animated_only=True)
        self._animation_upgrade_task: asyncio.Task | None = None
        self._animation_upgrade_key: TrackKey | None = None
        self._animation_upgrade_status = "not_requested"
        self._player_artwork: PlayerArtwork | None = None
        self._artwork_provider_revision = 0
        self.legacy_source_entity = entry.data.get(CONF_SOURCE_ENTITY)

        options = entry.options
        self.target_entities = configured_matrix_entities(dict(options), dict(entry.data))
        self.target_entity = self.target_entities[0] if self.target_entities else None
        self.matrix_enabled = bool(self.target_entities)
        self.matrix_output_enabled = bool(options.get(
            CONF_MATRIX_OUTPUT_ENABLED, DEFAULT_MATRIX_OUTPUT_ENABLED
        ))
        auto_power_mode = options.get(CONF_AUTO_POWER_MODE)
        if auto_power_mode in AUTO_POWER_MODES:
            self.matrix_turn_on = self.matrix_enabled and auto_power_mode in {"all", "matrix"}
        else:
            self.matrix_turn_on = bool(options.get(CONF_MATRIX_TURN_ON, DEFAULT_MATRIX_TURN_ON))
        self.pin = str(options.get(CONF_PIN, entry.data.get(CONF_PIN, "")) or "")

        raw_sources = options.get(CONF_SOURCE_ENTITIES)
        self._legacy_source_fallback = raw_sources is None
        if raw_sources is None:
            raw_sources = [self.legacy_source_entity] if self.legacy_source_entity else []
        self.selected_source_entities = normalize_entity_list(raw_sources)
        raw_ignored_inputs = options.get(CONF_IGNORED_INPUTS, "")
        if isinstance(raw_ignored_inputs, str):
            raw_ignored_inputs = raw_ignored_inputs.replace("\n", ",").split(",")
        self.ignored_inputs = {
            self._normalize_input_name(item)
            for item in (raw_ignored_inputs or []) if self._normalize_input_name(item)
        }
        self.source_stabilization = float(options.get(CONF_SOURCE_STABILIZATION, DEFAULT_SOURCE_STABILIZATION))

        self.width = int(options.get(CONF_WIDTH, DEFAULT_WIDTH))
        self.height = int(options.get(CONF_HEIGHT, DEFAULT_HEIGHT))
        self.auto_detect_size = bool(options.get(CONF_AUTO_DETECT_SIZE, DEFAULT_AUTO_DETECT_SIZE))
        self.image_fit = str(options.get(CONF_IMAGE_FIT, DEFAULT_IMAGE_FIT))
        crop_position = str(options.get(
            CONF_IMAGE_CROP_POSITION, DEFAULT_IMAGE_CROP_POSITION
        ))
        self.image_crop_position = (
            crop_position if crop_position in IMAGE_CROP_POSITIONS
            else DEFAULT_IMAGE_CROP_POSITION
        )
        self.image_zoom = max(100, min(200, int(options.get(
            CONF_IMAGE_ZOOM, DEFAULT_IMAGE_ZOOM
        ))))
        self.image_blur_strength = max(0, min(40, int(options.get(
            CONF_IMAGE_BLUR_STRENGTH, DEFAULT_IMAGE_BLUR_STRENGTH
        ))))
        self.image_background_brightness = max(0, min(100, int(options.get(
            CONF_IMAGE_BACKGROUND_BRIGHTNESS, DEFAULT_IMAGE_BACKGROUND_BRIGHTNESS
        ))))

        configured_filename = str(options.get(CONF_FILENAME, DEFAULT_FILENAME)).strip()
        if not configured_filename.lower().endswith(".gif"):
            configured_filename += ".gif"
        configured_filename = PurePosixPath(configured_filename).name
        self.filename_prefix = PurePosixPath(configured_filename).stem
        self.segment_id = int(options.get(CONF_SEGMENT_ID, DEFAULT_SEGMENT_ID))

        self.transition_style = str(options.get(CONF_TRANSITION_STYLE, DEFAULT_TRANSITION_STYLE))
        if self.transition_style in ("fade_black", "crossfade"):
            self.transition_style = "fade"
        self.transition_seconds = float(options.get(CONF_TRANSITION_SECONDS, DEFAULT_TRANSITION_SECONDS))
        self.fade_to_black = bool(options.get(CONF_FADE_TO_BLACK, DEFAULT_FADE_TO_BLACK))
        self.theme_fade_mode = str(options.get(CONF_THEME_FADE_MODE, ""))
        if self.theme_fade_mode not in THEME_FADE_MODES:
            self.theme_fade_mode = (
                "matrix_black" if options.get(
                    CONF_FADE_THEME_WITH_MATRIX, DEFAULT_FADE_THEME_WITH_MATRIX
                ) else "colors"
            )
        self.fade_theme_lights_with_matrix = self.theme_fade_mode == "matrix_black"
        self.black_pause = float(options.get(CONF_BLACK_PAUSE, DEFAULT_BLACK_PAUSE))

        self.matrix_outputs: list[MatrixOutput] = []
        self._startup_output_errors: dict[str, str] = {}
        if self.matrix_enabled:
            for target in self.target_entities:
                try:
                    target_url = self._resolve_wled_url(target)
                    prefix = f"{self.filename_prefix}_{target.split('.')[-1]}"
                    client = WLEDClient(
                        self.session, target_url, self.pin, self.segment_id, prefix
                    )
                    self.matrix_outputs.append(MatrixOutput(
                        entity_id=target,
                        wled=client,
                        width=self.width,
                        height=self.height,
                        auto_detect_size=self.auto_detect_size,
                        image_fit=self.image_fit,
                        image_crop_position=self.image_crop_position,
                        image_zoom=self.image_zoom,
                        image_blur_strength=self.image_blur_strength,
                        image_background_brightness=self.image_background_brightness,
                        filename_prefix=prefix,
                        segment_id=self.segment_id,
                        transition_style=self.transition_style,
                        transition_seconds=self.transition_seconds,
                        fade_to_black=self.fade_to_black,
                        black_pause=self.black_pause,
                        matrix_turn_on=self.matrix_turn_on,
                    ))
                except (ValueError, KeyError, TypeError) as err:
                    self._startup_output_errors[target] = str(err)
                    _LOGGER.warning("Could not configure WLED matrix %s: %s", target, err)

        self._unsubscribers = []
        self._pending_update_unsub = None
        self._update_burst_started: float | None = None
        self._pending_update_deadline: float | None = None
        self._artwork_retry_unsub = None
        self._artwork_retry_deadline: float | None = None
        self._pending_end_unsub = None
        self._end_countdown_unsub = None
        self._session_end_deadline: float | None = None
        self._session_end_generation = 0
        self._session_end_reason: str | None = None
        self._last_session_end_reason: str | None = None
        self._last_session_end_source: str | None = None
        self._last_session_end_source_name: str | None = None
        self._last_session_end_source_state: str | None = None
        self._failure_retry_unsub = None
        self._end_plan_retry_pending = False
        self._end_plan_rollback_pending = False
        self._session_active = False
        self._session_had_artwork = False
        self._session_artwork_sources: set[str] = set()
        self._session_artwork_context: dict[str, dict[str, str]] = {}
        self._theme_snapshots: dict[str, dict] = {}
        self._theme_lights_touched: set[str] = set()
        self._last_key = None
        self._last_filename: str | None = None
        self._last_source_entity: str | None = None
        self.manual_override = False
        self.status = "Starting"
        self._last_error: str | None = None
        self._last_success_at: str | None = None
        self._current_title: str | None = None
        self._current_artist: str | None = None
        self._stopping = False
        self._lock = asyncio.Lock()
        self._status_listeners = set()
        self._entity_state_listeners = set()
        self._session_store = Store(hass, 1, f"{DOMAIN}_{entry.entry_id}_session")
        self._session_journal: dict | None = None
        self._recovery_pending = False
        self._recovery_entity_ids: set[str] = set()
        self._recovery_retry_unsub = None
        self._tracked_state_entities: set[str] = set()
        # Devices often report available before their controller/network stack is
        # ready to accept commands. Delay commands after an unavailable -> available
        # transition, independently for every device.
        self._device_recovery_delay_seconds = max(0, min(60, int(options.get(
            CONF_DEVICE_WARMUP_DELAY, DEFAULT_DEVICE_WARMUP_DELAY
        ))))
        self._device_ready_after: dict[str, float] = {}
        self._device_recovery_unsubs: dict[str, object] = {}
        # Don't hammer a reachable-but-failing device on every metadata event.
        # Availability/power-on warm-up clears this backoff for that device.
        self._deferred_restore_retry_after: dict[str, float] = {}
        self._theme_last_key: dict[str, object] = {}
        self._theme_light_results: dict[str, dict] = {}
        self._last_theme_palette: list[tuple[int, int, int]] = []
        self.animated_artwork_enabled = bool(options.get(
            CONF_ANIMATED_ARTWORK, DEFAULT_ANIMATED_ARTWORK
        ))
        self._artwork_data: PreparedArtwork | None = None
        self._artwork_metadata: dict = {}
        self._artwork_updated_at: datetime | None = None
        self._artwork_image_entity_id: str | None = None
        self._artwork_source_bytes: bytes | None = None
        self._artwork_source_key: tuple | None = None
        self._artwork_prepared_animations = self.animated_artwork_enabled

        # Older configurations could assign the same light to both controllers.
        # Keep a single owner until the user next edits that configuration.
        self.theme_light_entities = [
            entity_id for entity_id in normalize_entity_list(
                options.get(CONF_THEME_LIGHT_ENTITIES, [])
            ) if entity_id not in self.target_entities
        ]
        self.theme_color_mode = str(options.get(CONF_THEME_COLOR_MODE, DEFAULT_THEME_COLOR_MODE))
        no_art_behavior = str(options.get(CONF_NO_ART_BEHAVIOR, DEFAULT_NO_ART_BEHAVIOR))
        self.no_art_behavior = (
            no_art_behavior if no_art_behavior in NO_ART_BEHAVIORS
            else DEFAULT_NO_ART_BEHAVIOR
        )
        continuation_behavior = str(options.get(
            CONF_NO_ART_DURING_SESSION, DEFAULT_NO_ART_DURING_SESSION
        ))
        self.no_art_during_session_behavior = (
            continuation_behavior
            if continuation_behavior in NO_ART_DURING_SESSION_BEHAVIORS
            else DEFAULT_NO_ART_DURING_SESSION
        )
        try:
            self.no_art_color = tuple(
                max(0, min(255, int(channel)))
                for channel in options.get(CONF_NO_ART_COLOR, DEFAULT_NO_ART_COLOR)
            )
        except (TypeError, ValueError):
            self.no_art_color = tuple(DEFAULT_NO_ART_COLOR)
        if len(self.no_art_color) != 3:
            self.no_art_color = tuple(DEFAULT_NO_ART_COLOR)
        self.no_art_brightness = max(0, min(100, int(options.get(
            CONF_NO_ART_BRIGHTNESS, DEFAULT_NO_ART_BRIGHTNESS
        ))))
        self.online_artwork_lookup_enabled = bool(options.get(
            CONF_ONLINE_ARTWORK_LOOKUP, DEFAULT_ONLINE_ARTWORK_LOOKUP
        ))
        self._configure_artwork_lookups(options)
        self.theme_light_transition = float(options.get(
            CONF_THEME_LIGHT_TRANSITION, DEFAULT_THEME_LIGHT_TRANSITION
        ))
        if auto_power_mode in AUTO_POWER_MODES:
            self.theme_lights_turn_on = bool(
                self.theme_light_entities and auto_power_mode in {"all", "theme"}
            )
        else:
            self.theme_lights_turn_on = bool(options.get(CONF_THEME_TURN_ON, DEFAULT_THEME_TURN_ON))
        if self.matrix_enabled and self.theme_light_entities and self.matrix_turn_on and self.theme_lights_turn_on:
            self.auto_power_mode = "all"
        elif self.matrix_enabled and self.theme_light_entities and self.matrix_turn_on:
            self.auto_power_mode = "matrix"
        elif self.matrix_enabled and self.theme_light_entities and self.theme_lights_turn_on:
            self.auto_power_mode = "theme"
        elif self.matrix_enabled or self.theme_light_entities:
            # The UI exposes all/none for a single selected output. Keep the
            # current option valid even though runtime still stores per-output flags.
            selected_output_turns_on = (
                self.matrix_turn_on if self.matrix_enabled else self.theme_lights_turn_on
            )
            self.auto_power_mode = "all" if selected_output_turns_on else "none"
        else:
            self.auto_power_mode = "none"

        color_adjustments = str(options.get(CONF_THEME_COLOR_ADJUSTMENTS, ""))
        if color_adjustments in THEME_COLOR_ADJUSTMENT_MODES:
            self.theme_color_adjustments = color_adjustments
            self.prevent_dark_theme_colors = color_adjustments in {"avoid_dark", "both"}
            self.balance_theme_spectrum = color_adjustments in {"balance", "both"}
        else:
            self.prevent_dark_theme_colors = bool(options.get(
                CONF_PREVENT_DARK_COLORS, DEFAULT_PREVENT_DARK_COLORS
            ))
            self.balance_theme_spectrum = bool(options.get(
                CONF_BALANCE_THEME_SPECTRUM, DEFAULT_BALANCE_THEME_SPECTRUM
            ))
            self.theme_color_adjustments = (
                "both" if self.prevent_dark_theme_colors and self.balance_theme_spectrum
                else "avoid_dark" if self.prevent_dark_theme_colors
                else "balance" if self.balance_theme_spectrum else "none"
            )
        self._apply_end_policy(options)
        self.end_grace_seconds = int(options.get(CONF_END_GRACE, DEFAULT_END_GRACE))
        pause_behavior = str(options.get(CONF_PAUSE_BEHAVIOR, DEFAULT_PAUSE_BEHAVIOR))
        self.pause_behavior = (
            pause_behavior
            if pause_behavior in {"end_after_grace", "hold"}
            else DEFAULT_PAUSE_BEHAVIOR
        )

    def _apply_end_policy(self, options: dict) -> None:
        """Normalize ending choices once for startup and live changes."""
        self.room_end_behavior, self.matrix_end_behavior = normalize_end_behavior(
            options, self.matrix_enabled
        )
        self.restore_theme_brightness = self.room_end_behavior == "restore_color_brightness"
        # Compatibility values for consumers of older manager diagnostics.
        self.end_behavior = (
            "keep_lighting" if (self.room_end_behavior, self.matrix_end_behavior) == ("keep", "keep")
            else "turn_off_all" if (self.room_end_behavior, self.matrix_end_behavior) == ("turn_off", "turn_off")
            else "turn_off_matrix" if self.matrix_end_behavior == "turn_off"
            else "keep_last" if self.matrix_end_behavior == "keep"
            else "restore_previous"
        )
        self.end_behavior_choice = (
            "restore_previous_brightness" if self.restore_theme_brightness else "restore_previous_color"
        ) if self.end_behavior == "restore_previous" else self.end_behavior

    def _configure_artwork_lookups(self, options: dict) -> None:
        """Give missing-cover and animation lookups the same service preferences."""
        for lookup in (self._online_artwork_lookup, self._animated_artwork_lookup):
            lookup.configure(
                str(options.get(CONF_ARTWORK_PROVIDER_PRIORITY, DEFAULT_ARTWORK_PROVIDER_PRIORITY)),
                str(options.get(CONF_LASTFM_API_KEY, "") or ""),
                providers=artwork_provider_order(options),
                theaudiodb_api_key=str(options.get(CONF_THEAUDIODB_API_KEY, "") or ""),
            )

    @staticmethod
    def _set_matrix_override_restore(snapshot: dict, enabled: bool) -> None:
        """Make a temporary matrix-off choice survive session restoration."""
        if enabled:
            if not snapshot.pop("_matrix_override_disabled", False):
                return
            previous_behavior = snapshot.pop("_matrix_override_previous_behavior", None)
            if previous_behavior is None:
                snapshot.pop("_pending_end_behavior", None)
            else:
                snapshot["_pending_end_behavior"] = previous_behavior
            return

        if not snapshot.get("_matrix_override_disabled"):
            snapshot["_matrix_override_previous_behavior"] = snapshot.get(
                "_pending_end_behavior"
            )
            snapshot["_matrix_override_disabled"] = True
        snapshot["_pending_end_behavior"] = "turn_off_matrix"

    async def _async_apply_matrix_output_override(self, enabled: bool) -> None:
        """Power down the matrix on opt-out and preserve that choice through recovery."""
        journal = self._session_journal
        if journal is not None:
            for snapshots_key in ("matrix_snapshots", "deferred_matrix_restores"):
                snapshots = journal.setdefault(snapshots_key, {})
                for snapshot in snapshots.values():
                    if isinstance(snapshot, dict):
                        self._set_matrix_override_restore(snapshot, enabled)
            for output in self.matrix_outputs:
                if output.snapshot is not None:
                    self._set_matrix_override_restore(output.snapshot, enabled)
            if not await self._async_persist_session_journal():
                _LOGGER.error(
                    "Matrix override changed, but its restoration choice could not be saved"
                )

        for output in self.matrix_outputs:
            output.invalidate_display()
            if not enabled:
                output.temporary_fallback_off = False
                output.power_on_expected_until = None

        if enabled:
            if self._session_active:
                self._set_status("Matrix artwork enabled")
            else:
                self._set_status(self.status)
            return

        failures, _waiting = await self._async_power_off_matrix_outputs(force=True)
        status = self._matrix_wait_status()
        if failures:
            status += "; matrix power-off failed — see diagnostics"
        self._set_status(status, "; ".join(failures) if failures else None)

    async def _async_power_off_matrix_outputs(
        self, *, force: bool
    ) -> tuple[list[str], list[str]]:
        """Power off enabled WLED entities and retain failures for diagnosis/retry."""
        failures: list[str] = []
        waiting: list[str] = []

        async def turn_off(
            output: MatrixOutput,
        ) -> tuple[MatrixOutput, str | None, bool]:
            output.invalidate_display()
            output.temporary_fallback_off = False
            output.power_on_expected_until = None
            state = self.hass.states.get(output.entity_id)
            if state is None or state.state in ("unknown", "unavailable"):
                return output, None, True
            # The entity state can lag the physical WLED state. An explicit user
            # request must still reach the device even when HA currently says off.
            if not force and state.state == "off":
                return output, None, False
            try:
                await output.wled.async_post_state({"on": False})
                return output, None, False
            except Exception as err:  # noqa: BLE001 - isolate each selected matrix
                return output, _safe_error_text(err), False

        results = await asyncio.gather(
            *(turn_off(output) for output in self.matrix_outputs),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, Exception):
                error = _safe_error_text(result)
                failures.append(error)
                _LOGGER.warning(
                    "Could not turn off a matrix for the output override: %s", error
                )
                continue
            output, error, is_waiting = result
            if is_waiting:
                output.last_result = "override_off_waiting_reconnect"
                output.last_error = None
                waiting.append(output.entity_id)
                continue
            if error:
                failures.append(f"{output.entity_id}: {error}")
                output.last_error = error
                output.last_result = "override_off_failed"
                _LOGGER.warning("Could not turn off matrix %s: %s", output.entity_id, error)
            else:
                output.last_error = None
                output.last_result = "disabled_by_user"
        return failures, waiting

    async def async_apply_live_options(self) -> bool:
        """Apply dashboard-safe options live, serializing with playback/device writes."""
        async with self._live_options_lock:
            async with self._lock:
                current_options = dict(self.entry.options)
                previous_options = self._applied_entry_options
                missing = object()
                changed_keys = {
                    key for key in set(previous_options) | set(current_options)
                    if previous_options.get(key, missing) != current_options.get(key, missing)
                }
                if not changed_keys:
                    return True
                if not changed_keys.issubset(LIVE_TUNABLE_OPTIONS):
                    return False

                theme_refresh_keys = {
                    CONF_THEME_COLOR_MODE,
                    CONF_THEME_TURN_ON,
                    CONF_PREVENT_DARK_COLORS,
                    CONF_BALANCE_THEME_SPECTRUM,
                    CONF_THEME_COLOR_ADJUSTMENTS,
                    CONF_THEME_FADE_MODE,
                    CONF_AUTO_POWER_MODE,
                }
                no_art_refresh = bool(changed_keys & {
                    CONF_NO_ART_BEHAVIOR, CONF_NO_ART_DURING_SESSION,
                    CONF_NO_ART_COLOR, CONF_NO_ART_BRIGHTNESS,
                })
                artwork_lookup_settings = {
                    CONF_ONLINE_ARTWORK_LOOKUP,
                    CONF_ARTWORK_PROVIDER_PRIORITY,
                    CONF_ARTWORK_PROVIDERS,
                    CONF_LASTFM_API_KEY,
                    CONF_THEAUDIODB_API_KEY,
                }
                refresh_online_artwork = bool(changed_keys & artwork_lookup_settings)
                refresh_animation = CONF_ANIMATED_ARTWORK in changed_keys
                refresh_theme = bool(changed_keys & theme_refresh_keys)
                refresh_no_art_scene = bool(
                    refresh_theme and self._session_active and self._last_key is not None
                    and self._last_key[0] == "no_art"
                )
                restore_no_art_session = False
                refresh_matrix = self.matrix_enabled and bool(
                    changed_keys & {
                        CONF_IMAGE_FIT, CONF_IMAGE_CROP_POSITION, CONF_IMAGE_ZOOM,
                        CONF_IMAGE_BLUR_STRENGTH, CONF_IMAGE_BACKGROUND_BRIGHTNESS,
                        CONF_MATRIX_TURN_ON, CONF_AUTO_POWER_MODE,
                    }
                )

                if CONF_SOURCE_STABILIZATION in changed_keys:
                    self.source_stabilization = max(0.3, min(10.0, float(current_options.get(
                        CONF_SOURCE_STABILIZATION, DEFAULT_SOURCE_STABILIZATION
                    ))))
                if CONF_END_GRACE in changed_keys:
                    self.end_grace_seconds = max(0, min(300, int(current_options.get(
                        CONF_END_GRACE, DEFAULT_END_GRACE
                    ))) )
                    # If a stop timer is already running, restart it with the new value.
                    if self._pending_end_unsub:
                        reason = self._session_end_reason or "stopped"
                        self._cancel_session_end()
                        self._schedule_session_end(reason)
                if CONF_PAUSE_BEHAVIOR in changed_keys:
                    pause_behavior = str(current_options.get(
                        CONF_PAUSE_BEHAVIOR, DEFAULT_PAUSE_BEHAVIOR
                    ))
                    self.pause_behavior = (
                        pause_behavior if pause_behavior in {"end_after_grace", "hold"}
                        else DEFAULT_PAUSE_BEHAVIOR
                    )
                    paused = any(
                        (state := self.hass.states.get(entity_id)) is not None
                        and state.state == "paused"
                        for entity_id in self._source_entity_ids()
                    )
                    if paused and self._session_active:
                        if self.pause_behavior == "hold":
                            self._cancel_session_end()
                            self._set_status("Playback paused — keeping current artwork")
                        else:
                            self._schedule_session_end("paused")
                if CONF_DEVICE_WARMUP_DELAY in changed_keys:
                    self._device_recovery_delay_seconds = max(0, min(60, int(current_options.get(
                        CONF_DEVICE_WARMUP_DELAY, DEFAULT_DEVICE_WARMUP_DELAY
                    ))))
                restored_player_artwork = False
                if refresh_online_artwork:
                    self._cancel_artwork_retry()
                    self._cancel_animation_upgrade()
                    restored_player_artwork = self._restore_player_artwork()
                    if self._artwork_metadata.get("artwork_provider") not in {None, "player"}:
                        self._artwork_source_key = None
                        self._artwork_source_bytes = None
                    self.online_artwork_lookup_enabled = bool(current_options.get(
                        CONF_ONLINE_ARTWORK_LOOKUP, DEFAULT_ONLINE_ARTWORK_LOOKUP
                    ))
                    self._artwork_provider_revision += 1
                    self._configure_artwork_lookups(current_options)
                    if restored_player_artwork:
                        native = self._player_artwork
                        previous_key = native.key
                        current_key = previous_key._replace(provider_revision=self._artwork_provider_revision)
                        self._player_artwork = PlayerArtwork(
                            current_key, native.source, native.prepared, native.metadata
                        )
                        self._artwork_source_key = current_key
                        if self._last_key == previous_key:
                            self._last_key = current_key
                        for output in self.matrix_outputs:
                            if output.last_matrix_key == previous_key:
                                output.last_matrix_key = current_key
                if refresh_animation:
                    self._cancel_animation_upgrade()
                    self.animated_artwork_enabled = bool(current_options.get(
                        CONF_ANIMATED_ARTWORK, DEFAULT_ANIMATED_ARTWORK
                    ))
                    if not self.animated_artwork_enabled:
                        restored_player_artwork = self._restore_player_artwork() or restored_player_artwork
                    if self._artwork_source_bytes is not None:
                        # Rebuild the HA image from the retained source even when
                        # playback is paused or has ended. Optional online
                        # enrichment runs separately after native display updates.
                        prepared = await self.hass.async_add_executor_job(
                            prepare_artwork_data, self._artwork_source_bytes,
                            self.animated_artwork_enabled,
                            max(8, min(16, len(self.theme_light_entities))),
                        )
                        self._store_prepared_artwork(prepared)
                if refresh_animation or restored_player_artwork:
                    source = self.hass.states.get(self._last_source_entity) if self._last_source_entity else None
                    if (
                        self._session_active and source is not None
                        and source.state == "paused" and self._last_key is not None
                        and self._last_key[0] == "track"
                        and self._artwork_source_key == self._last_key
                    ):
                        # A paused session still displays its cover. Apply the
                        # preference without powering on an already-off matrix.
                        outputs = [output for output in self._ready_matrix_outputs()
                                   if output.last_matrix_key == self._last_key
                                   and (target := self.hass.states.get(output.entity_id)) is not None
                                   and target.state == "on"]
                        results = await asyncio.gather(
                            *(self._async_update_matrix_output(
                                output, self._artwork_source_bytes, self._last_key,
                                True, allow_paused=True,
                            ) for output in outputs),
                            return_exceptions=True,
                        )
                        for output, result in zip(outputs, results):
                            if isinstance(result, Exception):
                                output.last_result = "error"
                                output.last_error = _safe_error_text(result)
                                _LOGGER.warning("Could not update paused artwork on %s: %s", output.entity_id, output.last_error)
                if CONF_THEME_COLOR_MODE in changed_keys:
                    self.theme_color_mode = str(current_options.get(
                        CONF_THEME_COLOR_MODE, DEFAULT_THEME_COLOR_MODE
                    ))
                if no_art_refresh:
                    behavior = str(current_options.get(
                        CONF_NO_ART_BEHAVIOR, DEFAULT_NO_ART_BEHAVIOR
                    ))
                    self.no_art_behavior = (
                        behavior if behavior in NO_ART_BEHAVIORS
                        else DEFAULT_NO_ART_BEHAVIOR
                    )
                    continuation_behavior = str(current_options.get(
                        CONF_NO_ART_DURING_SESSION, DEFAULT_NO_ART_DURING_SESSION
                    ))
                    self.no_art_during_session_behavior = (
                        continuation_behavior
                        if continuation_behavior in NO_ART_DURING_SESSION_BEHAVIORS
                        else DEFAULT_NO_ART_DURING_SESSION
                    )
                    try:
                        color = tuple(
                            max(0, min(255, int(channel)))
                            for channel in current_options.get(
                                CONF_NO_ART_COLOR, DEFAULT_NO_ART_COLOR
                            )
                        )
                    except (TypeError, ValueError):
                        color = tuple(DEFAULT_NO_ART_COLOR)
                    self.no_art_color = color if len(color) == 3 else tuple(DEFAULT_NO_ART_COLOR)
                    self.no_art_brightness = max(0, min(100, int(current_options.get(
                        CONF_NO_ART_BRIGHTNESS, DEFAULT_NO_ART_BRIGHTNESS
                    ))))
                    restore_no_art_session = bool(
                        self.no_art_behavior == "wait"
                        and self._session_active
                        and self._last_key is not None
                        and self._last_key[0] == "no_art"
                        and (
                            len(self._last_key) <= 7
                            or self._last_key[7] == "start"
                        )
                    )
                    if self.no_art_behavior == "fallback_color":
                        refresh_matrix = self.matrix_enabled and self.matrix_output_enabled
                if CONF_TRANSITION_STYLE in changed_keys:
                    self.transition_style = str(current_options.get(
                        CONF_TRANSITION_STYLE, DEFAULT_TRANSITION_STYLE
                    ))
                    if self.transition_style in ("fade_black", "crossfade"):
                        self.transition_style = "fade"
                    for output in self.matrix_outputs:
                        output.transition_style = self.transition_style
                if CONF_TRANSITION_SECONDS in changed_keys:
                    self.transition_seconds = max(0.1, min(5.0, float(current_options.get(
                        CONF_TRANSITION_SECONDS, DEFAULT_TRANSITION_SECONDS
                    ))))
                    for output in self.matrix_outputs:
                        output.transition_seconds = self.transition_seconds
                if CONF_THEME_LIGHT_TRANSITION in changed_keys:
                    self.theme_light_transition = max(0.0, min(10.0, float(current_options.get(
                        CONF_THEME_LIGHT_TRANSITION, DEFAULT_THEME_LIGHT_TRANSITION
                    ))))
                if CONF_IMAGE_FIT in changed_keys:
                    self.image_fit = str(current_options.get(CONF_IMAGE_FIT, DEFAULT_IMAGE_FIT))
                    for output in self.matrix_outputs:
                        output.image_fit = self.image_fit
                if CONF_IMAGE_CROP_POSITION in changed_keys:
                    crop_position = str(current_options.get(
                        CONF_IMAGE_CROP_POSITION, DEFAULT_IMAGE_CROP_POSITION
                    ))
                    self.image_crop_position = (
                        crop_position if crop_position in IMAGE_CROP_POSITIONS
                        else DEFAULT_IMAGE_CROP_POSITION
                    )
                    for output in self.matrix_outputs:
                        output.image_crop_position = self.image_crop_position
                if CONF_IMAGE_ZOOM in changed_keys:
                    self.image_zoom = max(100, min(200, int(current_options.get(
                        CONF_IMAGE_ZOOM, DEFAULT_IMAGE_ZOOM
                    ))))
                    for output in self.matrix_outputs:
                        output.image_zoom = self.image_zoom
                if CONF_IMAGE_BLUR_STRENGTH in changed_keys:
                    self.image_blur_strength = max(0, min(40, int(current_options.get(
                        CONF_IMAGE_BLUR_STRENGTH, DEFAULT_IMAGE_BLUR_STRENGTH
                    ))))
                    for output in self.matrix_outputs:
                        output.image_blur_strength = self.image_blur_strength
                if CONF_IMAGE_BACKGROUND_BRIGHTNESS in changed_keys:
                    self.image_background_brightness = max(0, min(100, int(
                        current_options.get(
                            CONF_IMAGE_BACKGROUND_BRIGHTNESS,
                            DEFAULT_IMAGE_BACKGROUND_BRIGHTNESS,
                        )
                    )))
                    for output in self.matrix_outputs:
                        output.image_background_brightness = self.image_background_brightness
                if changed_keys & {
                    CONF_END_BEHAVIOR, CONF_ROOM_END_BEHAVIOR,
                    CONF_MATRIX_END_BEHAVIOR, CONF_RESTORE_THEME_BRIGHTNESS,
                }:
                    self._apply_end_policy(current_options)
                if CONF_BLACK_PAUSE in changed_keys:
                    self.black_pause = max(0.0, min(2.0, float(current_options.get(
                        CONF_BLACK_PAUSE, DEFAULT_BLACK_PAUSE
                    ))))
                    for output in self.matrix_outputs:
                        output.black_pause = self.black_pause
                if CONF_MATRIX_TURN_ON in changed_keys:
                    self.matrix_turn_on = bool(current_options.get(
                        CONF_MATRIX_TURN_ON, DEFAULT_MATRIX_TURN_ON
                    ))
                if CONF_AUTO_POWER_MODE in changed_keys:
                    mode = str(current_options.get(CONF_AUTO_POWER_MODE, DEFAULT_AUTO_POWER_MODE))
                    if mode in AUTO_POWER_MODES:
                        self.matrix_turn_on = self.matrix_enabled and mode in {"all", "matrix"}
                        self.theme_lights_turn_on = bool(
                            self.theme_light_entities and mode in {"all", "theme"}
                        )
                        if self.matrix_enabled and self.theme_light_entities:
                            self.auto_power_mode = mode
                        elif self.matrix_enabled or self.theme_light_entities:
                            selected_output_turns_on = (
                                self.matrix_turn_on if self.matrix_enabled
                                else self.theme_lights_turn_on
                            )
                            self.auto_power_mode = "all" if selected_output_turns_on else "none"
                        else:
                            self.auto_power_mode = "none"
                for output in self.matrix_outputs:
                    output.matrix_turn_on = self.matrix_turn_on
                if CONF_MATRIX_OUTPUT_ENABLED in changed_keys:
                    self.matrix_output_enabled = bool(current_options.get(
                        CONF_MATRIX_OUTPUT_ENABLED, DEFAULT_MATRIX_OUTPUT_ENABLED
                    ))
                    await self._async_apply_matrix_output_override(
                        self.matrix_output_enabled
                    )
                    if self.matrix_output_enabled:
                        refresh_matrix = self.matrix_enabled
                if CONF_FADE_TO_BLACK in changed_keys:
                    self.fade_to_black = bool(current_options.get(
                        CONF_FADE_TO_BLACK, DEFAULT_FADE_TO_BLACK
                    ))
                    for output in self.matrix_outputs:
                        output.fade_to_black = self.fade_to_black
                if CONF_FADE_THEME_WITH_MATRIX in changed_keys:
                    self.fade_theme_lights_with_matrix = bool(current_options.get(
                        CONF_FADE_THEME_WITH_MATRIX, DEFAULT_FADE_THEME_WITH_MATRIX
                    ))
                    self.theme_fade_mode = "matrix_black" if self.fade_theme_lights_with_matrix else "colors"
                if CONF_THEME_FADE_MODE in changed_keys:
                    mode = str(current_options.get(CONF_THEME_FADE_MODE, DEFAULT_THEME_FADE_MODE))
                    self.theme_fade_mode = mode if mode in THEME_FADE_MODES else DEFAULT_THEME_FADE_MODE
                    self.fade_theme_lights_with_matrix = self.theme_fade_mode == "matrix_black"
                if CONF_THEME_TURN_ON in changed_keys:
                    self.theme_lights_turn_on = bool(current_options.get(
                        CONF_THEME_TURN_ON, DEFAULT_THEME_TURN_ON
                    ))
                if CONF_PREVENT_DARK_COLORS in changed_keys:
                    self.prevent_dark_theme_colors = bool(current_options.get(
                        CONF_PREVENT_DARK_COLORS, DEFAULT_PREVENT_DARK_COLORS
                    ))
                if CONF_BALANCE_THEME_SPECTRUM in changed_keys:
                    self.balance_theme_spectrum = bool(current_options.get(
                        CONF_BALANCE_THEME_SPECTRUM, DEFAULT_BALANCE_THEME_SPECTRUM
                    ))
                if CONF_THEME_COLOR_ADJUSTMENTS in changed_keys:
                    mode = str(current_options.get(
                        CONF_THEME_COLOR_ADJUSTMENTS, DEFAULT_THEME_COLOR_ADJUSTMENTS
                    ))
                    if mode in THEME_COLOR_ADJUSTMENT_MODES:
                        self.theme_color_adjustments = mode
                        self.prevent_dark_theme_colors = mode in {"avoid_dark", "both"}
                        self.balance_theme_spectrum = mode in {"balance", "both"}
                # Advance only after all values have been validated/applied.
                self._applied_entry_options = current_options

                if restore_no_art_session:
                    self._recovery_pending = True
                    if await self._async_restore_saved_state():
                        self._last_key = None
                        self._reset_matrix_session_state()

                if (refresh_theme or restored_player_artwork) and not refresh_no_art_scene:
                    # Force a recolor from the cached palette without downloading artwork.
                    self._theme_last_key.clear()
                    if self._session_active and self._last_theme_palette and self._last_key is not None:
                        result = await self._async_update_theme_lights(
                            self._last_theme_palette, self._last_key
                        )
                        if result is False:
                            self._set_status(
                                "Theme-light update incomplete — see diagnostics",
                                "A live theme-light setting could not be applied to every selected light",
                            )

                # Image fit and matrix auto-power-on can affect the currently displayed
                # cover, so reapply that cover asynchronously after releasing the lock.
                self._set_status(self.status)
                if no_art_refresh or refresh_online_artwork or refresh_no_art_scene or refresh_animation or (
                    refresh_matrix and self._session_active and self._last_key is not None
                ):
                    self.hass.async_create_task(self.async_update(force=True))
                _LOGGER.debug("Applied live Music Artwork Lighting options: %s", sorted(changed_keys))
                return True

    @callback
    def async_add_status_listener(self, listener):
        """Subscribe to status state and its countdown updates."""
        self._status_listeners.add(listener)

        @callback
        def _unsubscribe() -> None:
            self._status_listeners.discard(listener)

        return _unsubscribe

    def async_add_entity_state_listener(self, listener):
        """Subscribe to manager changes that can affect non-status entities."""
        self._entity_state_listeners.add(listener)

        @callback
        def _unsubscribe() -> None:
            self._entity_state_listeners.discard(listener)

        return _unsubscribe

    @property
    def artwork_image(self) -> bytes | None:
        """Return the bounded artwork bytes served by HA's image entity."""
        return self._artwork_data.image if self._artwork_data is not None else None

    @property
    def artwork_content_type(self) -> str:
        return self._artwork_data.content_type if self._artwork_data is not None else "image/png"

    @property
    def artwork_last_updated(self) -> datetime | None:
        return self._artwork_updated_at

    @property
    def artwork_image_entity_id(self) -> str | None:
        return self._artwork_image_entity_id

    @callback
    def set_artwork_image_entity_id(self, entity_id: str | None) -> None:
        """Follow the registered image ID, including user renames and removal."""
        if entity_id == self._artwork_image_entity_id:
            return
        self._artwork_image_entity_id = entity_id
        for listener in tuple(self._entity_state_listeners):
            try:
                listener()
            except Exception:  # noqa: BLE001 - entity lifecycle must remain independent
                _LOGGER.debug("An artwork entity listener failed", exc_info=True)

    def artwork_entity_picture(self) -> str | None:
        """Use HA's local image proxy rather than exposing a source URL."""
        if self.artwork_image is None or not self._artwork_image_entity_id:
            return None
        state = self.hass.states.get(self._artwork_image_entity_id)
        return state.attributes.get("entity_picture") if state is not None else None

    def _store_prepared_artwork(self, prepared: PreparedArtwork) -> None:
        """Change the proxy cache timestamp only when its actual image changes."""
        if self._artwork_data is None or prepared.fingerprint != self._artwork_data.fingerprint:
            self._artwork_updated_at = datetime.now(timezone.utc)
        self._artwork_data = prepared
        self._artwork_prepared_animations = self.animated_artwork_enabled

    def _cancel_animation_upgrade(self, *, release_track: bool = False) -> None:
        """Stop optional enrichment without disturbing the displayed player cover."""
        task = self._animation_upgrade_task
        self._animation_upgrade_task = None
        if task is not None and not task.done() and task is not asyncio.current_task():
            task.cancel()
        self._animation_upgrade_key = None
        self._animation_upgrade_status = "not_requested"
        if release_track:
            self._animated_artwork_lookup.release_current_track()

    def _restore_player_artwork(self) -> bool:
        """Restore the native cover when animation enrichment is disabled."""
        native = self._player_artwork
        if (
            native is None or native.key != self._artwork_source_key
            or not self._artwork_metadata.get("is_animation_upgrade")
        ):
            return False
        self._artwork_source_bytes = native.source
        self._artwork_metadata = dict(native.metadata)
        self._last_theme_palette = list(native.prepared.palette)
        self._store_prepared_artwork(native.prepared)
        self._theme_last_key.clear()
        return True

    def _can_upgrade_player_artwork(self, key: TrackKey) -> bool:
        """Only enrich a static native cover for the still-selected playing song."""
        native = self._player_artwork
        return bool(
            self.animated_artwork_enabled and self.online_artwork_lookup_enabled
            and bool(self.entry.options.get(CONF_ANIMATED_ARTWORK, DEFAULT_ANIMATED_ARTWORK))
            and bool(self.entry.options.get(CONF_ONLINE_ARTWORK_LOOKUP, DEFAULT_ONLINE_ARTWORK_LOOKUP))
            and self._session_active and artwork_provider_order(self.entry.options)
            and native is not None and native.key == key
            and not native.prepared.source_is_animated
            and key.title and str(key.title).strip() and key.artist and str(key.artist).strip()
            and self._artwork_source_key == key and self._artwork_data is not None
            and self._artwork_metadata.get("artwork_provider") == "player"
            and self._candidate_is_current(key)
        )

    def _schedule_animation_upgrade(self, key: TrackKey) -> None:
        """Search once per current song after its native artwork has been shown."""
        if not self._can_upgrade_player_artwork(key) or self._animation_upgrade_key == key:
            return
        self._cancel_animation_upgrade()
        self._animation_upgrade_key = key
        self._animation_upgrade_status = "pending"
        # This optional task can wait through a service cooldown. Its explicit
        # lifecycle cancellation keeps it out of HA's foreground task drain.
        self._animation_upgrade_task = asyncio.create_task(
            self._async_upgrade_player_artwork(key),
            name=f"{DOMAIN} animated cover {self.entry.entry_id}",
        )

    async def _async_upgrade_player_artwork(self, key: TrackKey) -> None:
        """Find optional animation outside the playback lock; retain native on misses."""
        task = asyncio.current_task()
        try:
            # The primary update owns this lock until its native image, colors,
            # and output commands are complete. Online requests begin afterwards.
            async with self._lock:
                if not self._can_upgrade_player_artwork(key):
                    return
            while self._animation_upgrade_task is task:
                if not self._can_upgrade_player_artwork(key):
                    return
                self._animation_upgrade_status = "searching"
                self._set_status(self.status, self._last_error)
                image_bytes = await self._animated_artwork_lookup.async_lookup(
                    key.title, key.artist, key.album,
                )
                if image_bytes:
                    prepared = await self.hass.async_add_executor_job(
                        prepare_artwork_data, image_bytes, True,
                        max(8, min(16, len(self.theme_light_entities))),
                    )
                    async with self._lock:
                        if self._animation_upgrade_task is not task or not self._can_upgrade_player_artwork(key):
                            return
                        # File extensions and even GIF containers do not prove
                        # animation. The prepared export must have multiple frames.
                        if not prepared.is_animated:
                            self._animation_upgrade_status = "no_animation_found"
                            return
                        details = self._animated_artwork_lookup.diagnostics()
                        match = details.get("matched_query")
                        self._artwork_source_bytes = image_bytes
                        self._artwork_metadata = {
                            **self._artwork_metadata,
                            "artwork_provider": details.get("matched_provider") or "online",
                            "artwork_match": match,
                            "artwork_match_description": artwork_match_description(
                                str(key.title or ""), str(key.artist or ""), match,
                            ),
                            "is_animation_upgrade": True,
                        }
                        self._store_prepared_artwork(prepared)
                        self._last_theme_palette = list(prepared.palette)
                        self._theme_last_key.clear()
                        for output in self.matrix_outputs:
                            output.last_matrix_key = None
                        self._animation_upgrade_status = "applied"
                        # Reuse ordinary output readiness/power checks. This task
                        # never owns device writes, so cancellation stays harmless.
                        self._schedule_update(immediate=True, reset_delay=False)
                    return
                delay = self._animated_artwork_lookup.next_retry_delay
                if delay is None:
                    self._animation_upgrade_status = "no_animation_found"
                    return
                self._animation_upgrade_status = "waiting_retry"
                self._set_status(self.status, self._last_error)
                # Lookup caching allows one transient retry after service cooldowns.
                # Song/source changes cancel this task, including this wait.
                await asyncio.sleep(max(1.0, delay))
        except asyncio.CancelledError:
            raise
        except Exception as err:  # noqa: BLE001 - optional enrichment never interrupts playback
            if self._animation_upgrade_task is task:
                self._animation_upgrade_status = "failed"
            _LOGGER.debug("Animated cover upgrade skipped: %s", _safe_error_text(err))
        finally:
            if self._animation_upgrade_task is task:
                self._animation_upgrade_task = None
                self._set_status(self.status, self._last_error)

    def _clear_artwork_data(self) -> None:
        """Clear a cover when the selected no-art scene replaces it."""
        self._cancel_animation_upgrade(release_track=True)
        self._player_artwork = None
        if self._artwork_data is not None:
            self._artwork_updated_at = datetime.now(timezone.utc)
        self._artwork_data = None
        self._artwork_metadata = {}
        self._artwork_source_bytes = None
        self._artwork_source_key = None

    def artwork_attributes(self) -> dict:
        """Expose reusable colors and context, never raw artwork URLs or bytes."""
        data = self._artwork_data
        metadata = dict(self._artwork_metadata)
        source_entity = metadata.get("source_entity_id")
        source = self.hass.states.get(source_entity) if source_entity else None
        source_attributes = source.attributes if source is not None else {}
        playback_state = source.state if source is not None else "unknown"
        active = bool(
            source is not None and source_entity in self._source_entity_ids()
            and playback_state in {"playing", "buffering"}
            and self._is_music_activity(source)
            and source_entity == self._last_source_entity
        )
        current_artist = source_attributes.get("media_artist") or source_attributes.get("media_album_artist")
        current_title = source_attributes.get("media_title")
        is_current = bool(
            source is not None
            and source_entity == self._last_source_entity
            and current_title == metadata.get("media_title")
            and current_artist == metadata.get("media_artist")
            and source_attributes.get("media_album_name") == metadata.get("media_album_name")
        )
        fallback = bool(metadata.get("is_fallback"))
        palette = list(data.palette) if data is not None else (
            [tuple(metadata["fallback_rgb"])] if fallback else []
        )
        if palette:
            count = len(self.theme_light_entities) or len(palette)
            colors = (
                [palette[0]] * count if fallback
                else build_theme_colors(palette, self.theme_color_mode, count)
            )
            if not fallback:
                colors = [self._ensure_visible_color(
                    balance_color_spectrum(color, self.balance_theme_spectrum)
                ) for color in colors]
        else:
            colors = []

        def hex_color(color):
            return "#{:02X}{:02X}{:02X}".format(*color)

        primary = palette[0] if palette else None
        # Choose the readable black/white foreground using relative luminance.
        text_color = None
        if primary is not None:
            channels = [value / 255 for value in primary]
            linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in channels]
            luminance = sum(value * weight for value, weight in zip(linear, (0.2126, 0.7152, 0.0722)))
            text_color = "#000000" if luminance > 0.179 else "#FFFFFF"
        return {
            "source_entity_id": metadata.get("source_entity_id"),
            "media_title": metadata.get("media_title"),
            "media_artist": metadata.get("media_artist"),
            "media_album_name": metadata.get("media_album_name"),
            "artwork_provider": metadata.get("artwork_provider"),
            **{key: value for key, value in metadata.items() if key != "fallback_rgb"},
            "artwork_media_title": metadata.get("media_title"),
            "artwork_media_artist": metadata.get("media_artist"),
            "artwork_media_album_name": metadata.get("media_album_name"),
            "image_entity_id": self._artwork_image_entity_id,
            "has_artwork": data is not None,
            "is_active": active,
            "is_current": is_current,
            "is_fallback": fallback,
            "playback_state": playback_state,
            "current_media_title": current_title,
            "current_media_artist": current_artist,
            "rgb_color": list(primary) if primary is not None else None,
            "hex_color": hex_color(primary) if primary is not None else None,
            "text_color": text_color,
            "palette_rgb": [list(color) for color in palette],
            "palette_hex": [hex_color(color) for color in palette],
            "theme_colors_rgb": [list(color) for color in colors[:16]],
            "theme_colors_hex": [hex_color(color) for color in colors[:16]],
            "animated_artwork_enabled": self.animated_artwork_enabled,
            "is_animated": data.is_animated if data is not None else False,
            "source_is_animated": data.source_is_animated if data is not None else False,
            "source_frame_count": data.source_frame_count if data is not None else 0,
            "width": data.width if data is not None else None,
            "height": data.height if data is not None else None,
        }

    def _set_status(
        self, status: str, error: str | None = None, *, notify_entities: bool = True
    ) -> None:
        """Update status and notify entities whose state or attributes changed."""
        missing_cover_status = status.startswith((
            "Waiting for artwork", "Playing without cover art", "Playing without artwork",
            "Playing — fallback", "Playing — outputs turned off because artwork",
        ))
        if status.startswith("Playing —") and self._last_source_entity:
            source = self.hass.states.get(self._last_source_entity)
            source_name = (
                source.attributes.get("friendly_name") or self._last_source_entity
                if source is not None else self._last_source_entity
            )
            if self.matrix_enabled and not self.matrix_output_enabled:
                if any(output.last_result == "override_off_failed" for output in self.matrix_outputs):
                    matrix_state = "matrix power-off failed"
                elif any(
                    output.last_result == "override_off_waiting_reconnect"
                    for output in self.matrix_outputs
                ):
                    matrix_state = "matrix power-off waiting for WLED"
                else:
                    matrix_state = "matrix off"
                room_state = (
                    "; room-light matching continues"
                    if self.theme_light_entities else ""
                )
                status = f"Playing on {source_name} — {matrix_state}{room_state}"
            else:
                status = status.replace("Playing —", f"Playing on {source_name} —", 1)
        if status.startswith("Playback ended —") and self._last_session_end_reason:
            if self._last_session_end_reason == "paused":
                source_name = self._last_session_end_source_name or "the selected player"
                end_context = f"after {source_name} reported paused"
            else:
                end_context = "when no configured player was playing"
            status = status.replace("Playback ended —", f"Session ended {end_context} —", 1)
        if self.online_artwork_lookup_enabled and missing_cover_status:
            lookup_reason = self._online_artwork_lookup.failure_summary
            if lookup_reason:
                status = f"{status} — {lookup_reason}"
        self.status = status
        if error is not None:
            self._last_error = _safe_error_text(error)
        elif status.startswith((
            "Playing —", "Playing on ", "Playback ended —", "Updated ", "Artwork applied to ",
            "Playback ended after ", "Session ended ", "Restoration retry complete", "Theme-light test complete",
            "Matrix artwork off", "Matrix artwork enabled", "Matrix test complete",
        )):
            self._last_error = None
        listeners = set(self._status_listeners)
        if notify_entities:
            listeners.update(self._entity_state_listeners)
        for listener in tuple(listeners):
            try:
                listener()
            except Exception:  # noqa: BLE001 - diagnostics must never interrupt playback
                _LOGGER.debug("A status listener failed", exc_info=True)

    @property
    def restoration_retry_available(self) -> bool:
        """Return whether saved device state can be retried without ending playback."""
        journal = self._session_journal or {}
        has_deferred_devices = bool(
            journal.get("deferred_matrix_restores") or journal.get("deferred_theme_restores")
        )
        if has_deferred_devices:
            return True
        # A live session journal contains snapshots by design. Only expose the
        # retry action for an interrupted/ending session that still needs them.
        return bool(self._recovery_pending and not self._session_active)

    def status_attributes(self) -> dict:
        """Return useful diagnostics for the status sensor and downloadable report."""
        source_ids = self._source_entity_ids()
        current = self.hass.states.get(self._last_source_entity) if self._last_source_entity else None
        title = self._current_title or (current.attributes.get("media_title") if current else None)
        artist = self._current_artist or (current.attributes.get("media_artist") if current else None)
        source_states = {}
        for entity_id in source_ids:
            state = self.hass.states.get(entity_id)
            source_states[entity_id] = state.state if state is not None else "missing"
        source_details = self.source_diagnostics()
        return {
            "active_source": self._last_source_entity,
            "active_source_name": source_details["active_source_name"],
            "active_source_state": source_details["active_source_state"],
            "active_source_priority": source_details["active_source_priority"],
            "active_source_is_playing_session": source_details["active_source_is_playing_session"],
            "source_selection_reason": source_details["source_selection_reason"],
            "source_candidates": source_details["source_candidates"],
            "no_art_behavior": self.no_art_behavior,
            "no_art_during_session_behavior": self.no_art_during_session_behavior,
            "no_art_color": list(self.no_art_color),
            "no_art_brightness_percent": self.no_art_brightness,
            "online_artwork_lookup": {
                "enabled": self.online_artwork_lookup_enabled,
                **self._online_artwork_lookup.diagnostics(),
            },
            "animation_artwork_lookup": {
                "enabled": bool(self.animated_artwork_enabled and self.online_artwork_lookup_enabled),
                "state": self._animation_upgrade_status,
                "search_in_progress": bool(
                    self._animation_upgrade_task is not None and not self._animation_upgrade_task.done()
                ),
                **self._animated_artwork_lookup.diagnostics(),
            },
            "media_title": title,
            "media_artist": artist,
            "source_priority_order": source_ids,
            "source_states": source_states,
            "matrix_entity": self.target_entity,
            "matrix_entities": [output.entity_id for output in self.matrix_outputs],
            "matrix_outputs": {
                output.entity_id: {
                    "width": output.width,
                    "height": output.height,
                    "dimensions_source": "wled_auto_detected" if output.resolution_detected else output.resolution_source,
                    "segment_id": output.segment_id,
                    "last_artwork_file": output.last_filename,
                    "last_updated": output.last_matrix_key is not None,
                    "last_updated_at": output.last_updated_at,
                    "last_result": output.last_result,
                    "last_error": output.last_error,
                    "snapshot_saved": output.snapshot is not None,
                    "temporary_fallback_off": output.temporary_fallback_off,
                    "fallback_power_restore_allowed": output.can_restore_fallback_power,
                    "power_on_confirmation_pending": bool(
                        output.power_on_expected_until is not None
                        and output.power_on_expected_until > time.monotonic()
                    ),
                    "warmup_remaining_seconds": max(
                        0, ceil(self._device_ready_after.get(output.entity_id, 0) - time.monotonic())
                    ),
                    "snapshot_error": output.snapshot_error,
                    "available": bool(
                        (state := self.hass.states.get(output.entity_id))
                        and state.state not in ("unknown", "unavailable")
                    ),
                }
                for output in self.matrix_outputs
            },
            "matrix_startup_errors": dict(self._startup_output_errors),
            "matrix_enabled": self.matrix_enabled,
            "matrix_output_enabled": self.matrix_output_enabled,
            "theme_lights": list(self.theme_light_entities),
            "theme_light_results": deepcopy(self._theme_light_results),
            "theme_color_mode": self.theme_color_mode,
            "session_active": self._session_active,
            "session_end_pending": self._pending_end_unsub is not None,
            "session_end_reason": self._session_end_reason,
            "session_end_source_entity_id": (
                self._last_source_entity if self._pending_end_unsub else None
            ),
            "session_end_source_name": (
                source_details["active_source_name"] if self._pending_end_unsub else None
            ),
            "session_end_source_state": (
                source_details["active_source_state"] if self._pending_end_unsub else None
            ),
            "session_end_remaining_seconds": (
                max(0, ceil(self._session_end_deadline - time.monotonic()))
                if self._pending_end_unsub and self._session_end_deadline is not None
                else None
            ),
            "last_session_end_reason": self._last_session_end_reason,
            "last_session_end_source_entity_id": self._last_session_end_source,
            "last_session_end_source_name": self._last_session_end_source_name,
            "last_session_end_source_state": self._last_session_end_source_state,
            "pause_behavior": self.pause_behavior,
            "room_end_behavior": self.room_end_behavior,
            "matrix_end_behavior": self.matrix_end_behavior,
            "session_end_plan_retry_pending": self._end_plan_retry_pending,
            "session_end_rollback_pending": self._end_plan_rollback_pending,
            "manual_override": self.manual_override,
            "state_restoration_pending": bool(
                self._recovery_pending
                or (self._session_journal or {}).get("deferred_matrix_restores")
                or (self._session_journal or {}).get("deferred_theme_restores")
            ),
            "restoration_retry_available": self.restoration_retry_available,
            "deferred_matrix_restores": sorted(
                (self._session_journal or {}).get("deferred_matrix_restores", {}).keys()
            ),
            "deferred_theme_light_restores": sorted(
                (self._session_journal or {}).get("deferred_theme_restores", {}).keys()
            ),
            "pending_matrix_restore_entities": sorted(
                set((self._session_journal or {}).get("deferred_matrix_restores", {}))
                | (set((self._session_journal or {}).get("matrix_snapshots", {}))
                   if self._recovery_pending else set())
            ),
            "pending_theme_restore_entities": sorted(
                set((self._session_journal or {}).get("deferred_theme_restores", {}))
                | (set((self._session_journal or {}).get("theme_restore_pending", []))
                   if self._recovery_pending else set())
            ),
            "device_recovery_delay_seconds": self._device_recovery_delay_seconds,
            "deferred_restore_retrying_entities": sorted(
                entity_id for entity_id, ready_at in self._deferred_restore_retry_after.items()
                if ready_at > time.monotonic()
            ),
            "deferred_restorations_retrying": bool(
                (self._session_journal or {}).get("deferred_matrix_restores")
                or (self._session_journal or {}).get("deferred_theme_restores")
            ),
            "session_state_persisted": self._session_journal is not None,
            "last_success": self._last_success_at,
            "last_error": self._last_error,
            "last_artwork_file": self._last_filename,
            "last_artwork_files": {output.entity_id: output.last_filename for output in self.matrix_outputs},
        }

    @staticmethod
    def _normalize_input_name(value) -> str:
        """Normalize punctuation and case for exact source/input comparisons."""
        return "".join(character for character in str(value).casefold() if character.isalnum())

    def _is_ignored_input(self, state) -> bool:
        """Check user-configured source names without vendor-specific assumptions."""
        if state is None or not self.ignored_inputs:
            return False
        return any(
            self._normalize_input_name(state.attributes.get(attribute, "")) in self.ignored_inputs
            for attribute in ("source", "soundtouchplus_source")
        )

    @staticmethod
    def _artwork_urls(state) -> tuple[str, ...]:
        """Return distinct artwork URLs in preferred order."""
        if state is None:
            return ()
        attributes = state.attributes
        image_urls = []
        for key in ("entity_picture_local", "entity_picture", "media_image_url"):
            image_url = attributes.get(key)
            if isinstance(image_url, str) and image_url.strip():
                image_url = image_url.strip()
                if image_url not in image_urls:
                    image_urls.append(image_url)
        return tuple(image_urls)

    @staticmethod
    def _artwork_url(state) -> str | None:
        """Return the preferred artwork URL exposed by a media player."""
        image_urls = AlbumArtManager._artwork_urls(state)
        return image_urls[0] if image_urls else None

    @staticmethod
    def _has_artwork(state) -> bool:
        """Return whether a media player currently exposes a usable artwork URL."""
        return bool(AlbumArtManager._artwork_url(state))

    @staticmethod
    def _is_video_media(state) -> bool:
        """Recognize standard non-audio media types, independent of player brand."""
        if state is None:
            return False
        media_type = str(state.attributes.get("media_content_type", "")).strip().casefold()
        return media_type in {"video", "movie", "television", "tv"}

    @staticmethod
    def _has_music_metadata(state) -> bool:
        """Recognize audio types or track metadata, but never title-only video."""
        if state is None:
            return False
        attributes = state.attributes
        media_type = str(attributes.get("media_content_type", "")).strip().casefold()
        if media_type in {"music", "audio", "track", "song", "podcast", "radio"}:
            return True
        return any(
            attributes.get(key)
            for key in ("media_artist", "media_album_name", "media_album_artist", "media_track")
        )

    def _session_has_artwork_for(self, state) -> bool:
        """Keep trusting metadata gaps only for the same player/input in this session."""
        entity_id = getattr(state, "entity_id", None)
        if (
            not self._session_active or not entity_id
            or entity_id not in self._session_artwork_sources
        ):
            return False
        context = self._session_artwork_context.get(entity_id, {})
        attributes = state.attributes
        for key in ("source", "soundtouchplus_source", "app_name"):
            previous = self._normalize_input_name(context.get(key, ""))
            current = self._normalize_input_name(attributes.get(key, ""))
            if previous and current and previous != current:
                return False
        previous_type = str(context.get("media_content_type", "")).strip().casefold()
        current_type = str(attributes.get("media_content_type", "")).strip().casefold()
        if current_type in {"video", "movie", "television", "tv"}:
            previous_title = self._normalize_input_name(context.get("media_title", ""))
            current_title = self._normalize_input_name(attributes.get("media_title", ""))
            if previous_title and current_title and previous_title != current_title:
                return False
        return not (
            current_type in {"video", "movie", "television", "tv"}
            and previous_type in {"music", "audio", "track", "song", "podcast", "radio"}
        )

    def _is_music_activity(self, state) -> bool:
        """Treat art, audio metadata, or a previously established art session as music."""
        if (
            state is None or state.state not in ("playing", "buffering", "paused")
            or self._is_ignored_input(state)
            or (
                self._is_video_media(state)
                and not (
                    self._has_music_metadata(state)
                    and (self._has_artwork(state) or self._session_has_artwork_for(state))
                )
            )
            or (state.state == "paused" and not self._session_active)
        ):
            return False
        return (
            self._has_artwork(state)
            or self._has_music_metadata(state)
            or self._session_has_artwork_for(state)
        )

    def source_diagnostics(self) -> dict:
        """Describe source selection without exposing artwork URLs or credentials."""
        source_ids = self._source_entity_ids()
        selected_id = self._last_source_entity
        selected_state = self.hass.states.get(selected_id) if selected_id else None
        preferred_id = next((entity_id for entity_id in source_ids
                             if (state := self.hass.states.get(entity_id)) is not None
                             and state.state == "playing" and self._is_music_activity(state)), None)
        if preferred_id and not (
            selected_id in source_ids and selected_state is not None
            and selected_state.state == "buffering" and self._is_music_activity(selected_state)
            and source_ids.index(selected_id) < source_ids.index(preferred_id)
        ):
            # Publish the preferred player's metadata while its cover is loading.
            selected_id = preferred_id
            selected_state = self.hass.states.get(selected_id)
        selected_priority = source_ids.index(selected_id) + 1 if selected_id in source_ids else None
        selected_name = (
            selected_state.attributes.get("friendly_name", selected_id)
            if selected_state is not None and selected_id else selected_id
        )
        playback_state = selected_state.state if selected_state is not None else (
            "missing" if selected_id else "none"
        )
        selected_is_active = bool(
            selected_state
            and self._is_music_activity(selected_state)
        )

        def has_resolved_artwork(state) -> bool:
            metadata = self._artwork_metadata
            return bool(
                state is not None and self._artwork_data is not None
                and not metadata.get("is_fallback")
                and metadata.get("source_entity_id") == state.entity_id
                and metadata.get("media_title") == state.attributes.get("media_title")
                and metadata.get("media_artist") == (
                    state.attributes.get("media_artist") or state.attributes.get("media_album_artist")
                )
            )

        if not selected_id:
            reason = "No source selected yet"
        elif selected_state and selected_state.state == "buffering":
            reason = "Keeping this source while it buffers"
        elif selected_state and self._is_ignored_input(selected_state):
            reason = "Configured input ignored; waiting for another source"
        elif (
            selected_state and self._is_video_media(selected_state)
            and not self._is_music_activity(selected_state)
        ):
            reason = (
                "Video source has track metadata but no cover art yet; waiting to confirm music"
                if self._has_music_metadata(selected_state) and not self._has_artwork(selected_state)
                else "Non-audio media type ignored; waiting for music metadata"
            )
        elif (
            selected_state and selected_state.state == "playing"
            and has_resolved_artwork(selected_state)
        ):
            reason = "Highest-priority music player; artwork is available"
        elif (
            selected_state and selected_state.state == "playing"
            and not self._has_artwork(selected_state)
        ):
            if self._session_has_artwork_for(selected_state):
                reason = (
                    "Cover art disappeared during this session; keeping the current scene"
                    if self.no_art_during_session_behavior == "keep_previous"
                    else "Cover art disappeared during this session; applying the selected no-art behavior"
                )
            elif self.no_art_behavior == "wait":
                reason = "Playing without cover art; waiting as configured"
            else:
                reason = "Playing without cover art; using the configured fallback scene"
        elif selected_state and selected_state.state in ("playing", "paused"):
            reason = "Highest-priority eligible music player in the configured order"
        else:
            reason = "Last selected source; no configured source is currently eligible"

        candidates = []
        for index, entity_id in enumerate(source_ids, start=1):
            state = self.hass.states.get(entity_id)
            attributes = state.attributes if state is not None else {}
            state_value = state.state if state is not None else "missing"
            image_url = self._artwork_url(state)
            if state is None:
                candidate_status = "Entity not found"
            elif state_value in ("unknown", "unavailable"):
                candidate_status = "Unavailable"
            elif state_value == "buffering":
                candidate_status = "Buffering"
            elif state_value == "playing" and self._is_ignored_input(state):
                candidate_status = "Configured input ignored"
            elif (
                state_value == "playing" and self._is_video_media(state)
                and not self._is_music_activity(state)
            ):
                candidate_status = (
                    "Video has track metadata; waiting for cover art to confirm music"
                    if self._has_music_metadata(state) and not self._has_artwork(state)
                    else "Non-audio media type ignored"
                )
            elif state_value == "playing" and has_resolved_artwork(state):
                candidate_status = "Playing with resolved artwork"
            elif state_value == "playing" and image_url:
                candidate_status = "Playing with artwork"
            elif state_value == "playing":
                if self._session_has_artwork_for(state):
                    candidate_status = "Artwork seen earlier this session; applying no-art behavior"
                elif self._has_music_metadata(state):
                    candidate_status = "Playing without artwork; audio metadata found"
                else:
                    candidate_status = "Playing without artwork; waiting for music metadata"
            elif state_value == "paused":
                candidate_status = "Paused"
            else:
                candidate_status = f"Not playing ({state_value})"
            candidates.append({
                "priority": index,
                "entity_id": entity_id,
                "name": attributes.get("friendly_name", entity_id),
                "state": state_value,
                "media_title": attributes.get("media_title"),
                "media_artist": attributes.get("media_artist"),
                "media_album_name": attributes.get("media_album_name"),
                "media_content_type": attributes.get("media_content_type"),
                "app_name": attributes.get("app_name"),
                "source": attributes.get("source") or attributes.get("soundtouchplus_source"),
                "has_artwork": bool(image_url),
                "has_resolved_artwork": has_resolved_artwork(state),
                "eligible_music": bool(state is not None and self._is_music_activity(state)),
                "art_seen_this_session": self._session_has_artwork_for(state),
                "has_audio_metadata": self._has_music_metadata(state),
                "ignored_by_config": self._is_ignored_input(state),
                "selected": entity_id == selected_id,
                "status": candidate_status,
            })

        return {
            "active_source": selected_id,
            "active_source_name": selected_name,
            "active_source_state": playback_state,
            "active_source_media_title": (
                (selected_state.attributes.get("media_title") or self._current_title) if selected_state else self._current_title
            ),
            "active_source_media_artist": (
                (selected_state.attributes.get("media_artist") or self._current_artist) if selected_state else self._current_artist
            ),
            "active_source_media_album": (
                selected_state.attributes.get("media_album_name") if selected_state else None
            ),
            "active_source_media_type": (
                selected_state.attributes.get("media_content_type") if selected_state else None
            ),
            "active_source_app_name": (
                selected_state.attributes.get("app_name") if selected_state else None
            ),
            "active_source_priority": selected_priority,
            "active_source_is_playing_session": selected_is_active,
            "session_had_artwork": self._session_had_artwork,
            "source_selection_reason": reason,
            "source_priority_order": source_ids,
            "source_candidates": candidates,
        }

    async def async_set_manual_override(self, enabled: bool) -> None:
        """Pause/resume automation, restoring the saved state before releasing control."""
        enabled = bool(enabled)
        if enabled == self.manual_override:
            return
        self.manual_override = enabled
        if enabled:
            self._cancel_artwork_retry()
            self._cancel_animation_upgrade(release_track=True)
            self._end_plan_retry_pending = False
            if self._pending_update_unsub:
                self._pending_update_unsub()
                self._pending_update_unsub = None
            self._pending_update_deadline = None
            self._update_burst_started = None
            self._cancel_session_end()
            async with self._lock:
                self._recovery_pending = bool(self._session_active or self._session_journal)
                restored = await self._async_restore_saved_state() if self._recovery_pending else True
                self._session_active = False
                self._session_had_artwork = False
                self._session_artwork_sources.clear()
                self._session_artwork_context.clear()
                if restored:
                    pending_devices = bool(
                        (self._session_journal or {}).get("deferred_matrix_restores")
                        or (self._session_journal or {}).get("deferred_theme_restores")
                    )
                    self._set_status(
                        "Manual override — paused; offline devices still need restoration"
                        if pending_devices else "Manual override — automatic control paused"
                    )
                else:
                    self._set_status("Manual override active — state restoration pending")
                _LOGGER.info("Automatic album-art control paused for %s", self.entry.title)
        else:
            self._set_status(
                "Automatic control enabled — checking playback"
                if not self._recovery_pending
                else "Automatic control enabled — state restoration pending"
            )
            self._schedule_update()
            _LOGGER.info("Automatic album-art control resumed for %s", self.entry.title)

    async def async_test_theme_lights(self) -> None:
        """Test selected lights with a durable snapshot and the normal recovery path."""
        async with self._lock:
            if not self.theme_light_entities:
                self._set_status("Test unavailable — no theme lights selected")
                return
            if self._session_active or self._recovery_pending or self._session_journal is not None:
                self._set_status("Theme-light test unavailable during playback or state restoration")
                return

            snapshots = {}
            original_states = {}
            for entity_id in self.theme_light_entities:
                state = self.hass.states.get(entity_id)
                if state is None or state.state in ("unknown", "unavailable"):
                    continue
                snapshots[entity_id] = self._snapshot_theme_light(state)
                original_states[entity_id] = state
            if not snapshots:
                self._set_status("Theme-light test unavailable — no lights are ready")
                return

            # Persist before changing any light. If Home Assistant stops midway
            # through the preview, startup recovery still has every original state.
            self._theme_snapshots = deepcopy(snapshots)
            self._theme_lights_touched = set(snapshots)
            self._session_journal = new_session_journal(
                session_active=False,
                theme_snapshots=snapshots,
                theme_restore_pending=set(snapshots),
            )
            self._recovery_entity_ids.update(snapshots)
            self._recovery_pending = True
            if not await self._async_persist_session_journal():
                return

            tested = 0
            failures = []
            for entity_id, state in original_states.items():
                try:
                    data = {"entity_id": entity_id, "rgb_color": [64, 160, 255], "transition": 0.25}
                    if state.attributes.get("brightness") is not None:
                        data["brightness"] = int(state.attributes["brightness"])
                    await self.hass.services.async_call("light", "turn_on", data, blocking=True)
                    tested += 1
                    await asyncio.sleep(0.75)
                except (HomeAssistantError, ValueError, TypeError) as err:
                    failures.append(f"{entity_id}: {_safe_error_text(err)}")
                    _LOGGER.warning("Theme-light test failed for %s: %s", entity_id, err)
                except Exception as err:  # noqa: BLE001
                    failures.append(f"{entity_id}: {_safe_error_text(err)}")
                    _LOGGER.warning("Unexpected theme-light test error for %s", entity_id, exc_info=True)

            restored = await self._async_restore_saved_state()
            if self.restoration_retry_available:
                self._set_status(
                    "Theme-light test complete — saved-state restoration is pending",
                    "; ".join(failures) if failures else None,
                )
            elif not restored:
                self._set_status(
                    "Theme-light test complete — saved-state restoration needs attention",
                    "; ".join(failures) if failures else self._last_error,
                )
            elif failures:
                self._set_status(
                    f"Theme-light test incomplete — {tested} light(s) tested; previous states restored",
                    "; ".join(failures),
                )
            else:
                self._set_status(
                    f"Theme-light test complete — {tested} light(s) tested; previous states restored"
                )

    async def async_test_matrix(self) -> None:
        """Briefly show a color on the matrix, then restore its exact saved state."""
        async with self._live_options_lock:
            await self._async_test_matrix_with_options_locked()

    async def _async_test_matrix_with_options_locked(self) -> None:
        """Run the matrix preview while output settings remain stable."""
        if not self.matrix_outputs:
            self._set_status("Matrix test unavailable — no matrix is configured")
            return

        async with self._lock:
            if not self.matrix_output_enabled:
                self._set_status("Matrix test unavailable — matrix artwork is turned off")
                return
            if (
                self._session_active or self._recovery_pending
                or self._session_journal is not None
                or any(output.snapshot is not None for output in self.matrix_outputs)
            ):
                self._set_status("Matrix test unavailable during playback or state restoration")
                return

            tested = 0
            for output in self.matrix_outputs:
                state = self.hass.states.get(output.entity_id)
                if (
                    state is None or state.state in ("unknown", "unavailable")
                    or self._entity_in_recovery_cooldown(output.entity_id)
                ):
                    continue

                output.snapshot = None
                try:
                    output.snapshot = await self._async_read_matrix_snapshot(output)
                    output.snapshot_error = None
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, TypeError, RuntimeError, OSError) as err:
                    output.last_result = "snapshot_failed"
                    output.last_error = _safe_error_text(err)
                    output.snapshot_error = output.last_error
                    _LOGGER.warning(
                        "Could not snapshot WLED state before matrix test for %s: %s",
                        output.entity_id, output.last_error,
                    )
                    continue

                test_error = None
                restore_error = None
                recovery_saved = True
                try:
                    self._set_status(f"Testing matrix {output.entity_id}")
                    await output.wled.async_activate_solid_color([64, 160, 255], 0.25)
                    tested += 1
                    await asyncio.sleep(0.75)
                except Exception as err:  # noqa: BLE001 - always restore after a partial test
                    test_error = _safe_error_text(err)
                    _LOGGER.warning("Matrix color test failed for %s: %s", output.entity_id, test_error)
                finally:
                    try:
                        await self._async_restore_wled_state(output)
                    except Exception as err:  # noqa: BLE001 - preserve the exact state for retry
                        restore_error = _safe_error_text(err)
                        recovery_saved = await self._async_queue_matrix_test_restore(
                            output.entity_id, output.snapshot or {}
                        )
                        output.last_result = "restore_deferred"
                        output.last_error = restore_error
                        if not recovery_saved:
                            restore_error = "Could not save the matrix state needed for restoration"
                    output.snapshot = None

                if restore_error:
                    self._set_status(
                        f"Matrix test restore pending for {output.entity_id}"
                        if recovery_saved
                        else f"Matrix test restore failed for {output.entity_id}",
                        restore_error,
                    )
                    return
                if test_error:
                    self._set_status(
                        f"Matrix test failed for {output.entity_id}; previous state restored",
                        test_error,
                    )
                    return
                output.last_result = "matrix_test_restored"
                output.last_error = None

            if tested:
                self._set_status(f"Matrix test complete — {tested} matrix output(s) restored")
            else:
                self._set_status("Matrix test unavailable — no matrix is ready")

    async def _async_queue_matrix_test_restore(self, entity_id: str, snapshot: dict) -> bool:
        """Persist a failed test restore so normal recovery can retry it safely."""
        self._session_journal = new_session_journal(
            session_active=False,
            matrix_snapshots={entity_id: snapshot},
        )
        self._recovery_entity_ids.add(entity_id)
        self._recovery_pending = True
        persisted = await self._async_persist_session_journal()
        self._schedule_update()
        return persisted

    async def async_retry_state_restoration(self) -> None:
        """Retry saved-state restoration immediately for devices needing attention."""
        async with self._lock:
            if not self.restoration_retry_available:
                return

            journal = self._session_journal or {}
            retry_entities = set(journal.get("deferred_matrix_restores", {}))
            retry_entities.update(journal.get("deferred_theme_restores", {}))
            if self._recovery_pending:
                retry_entities.update(journal.get("matrix_snapshots", {}))
                retry_entities.update(journal.get("theme_restore_pending", []))
            for entity_id in retry_entities:
                self._deferred_restore_retry_after.pop(entity_id, None)

            restored = True
            if self._recovery_pending:
                restored = await self._async_restore_saved_state()

            journal = self._session_journal or {}
            deferred_entities = set(journal.get("deferred_matrix_restores", {}))
            deferred_entities.update(journal.get("deferred_theme_restores", {}))
            for entity_id in deferred_entities:
                self._deferred_restore_retry_after.pop(entity_id, None)
            if deferred_entities:
                await self._async_restore_deferred_state()

            if restored and not self.restoration_retry_available:
                self._set_status("Restoration retry complete — all saved states restored")
            else:
                self._set_status(
                    "Restoration retry attempted — one or more devices still need recovery",
                    self._last_error,
                )

    def _resolve_wled_url(self, target_entity: str | None = None) -> str:
        """Resolve a selected light to the host of its WLED config entry."""
        target_entity = target_entity or self.target_entity
        registry = er.async_get(self.hass)
        entity = registry.async_get(target_entity)
        if entity is None or entity.platform != "wled":
            raise ValueError(f"Target {target_entity} is not a WLED entity")
        target_entry = self.hass.config_entries.async_get_entry(entity.config_entry_id)
        if target_entry is None or target_entry.domain != "wled":
            raise ValueError(f"No WLED config entry found for {target_entity}")
        host = str(target_entry.data[CONF_HOST]).strip()
        if host.startswith(("http://", "https://")):
            return host.rstrip("/") + "/"
        return "http://" + host.strip("/") + "/"

    def _source_entity_ids(self) -> list[str]:
        """Return the explicitly selected media players in priority order."""
        ordered: list[str] = []
        seen: set[str] = set()
        for entity_id in self.selected_source_entities:
            if entity_id.startswith("media_player.") and entity_id not in seen:
                seen.add(entity_id)
                ordered.append(entity_id)
        if not ordered and self._legacy_source_fallback and self.legacy_source_entity:
            ordered.append(self.legacy_source_entity)
        return ordered

    @callback
    def _recovery_retry_elapsed(self, _now) -> None:
        """Retry deferred restoration without blocking normal playback updates."""
        self._recovery_retry_unsub = None
        self._schedule_update()

    def _schedule_recovery_retry(self) -> None:
        """Retry offline devices in the background every 30 seconds."""
        journal = self._session_journal or {}
        has_deferred = bool(
            journal.get("deferred_matrix_restores")
            or journal.get("deferred_theme_restores")
        )
        if has_deferred and self._recovery_retry_unsub is None and not self._stopping:
            self._recovery_retry_unsub = async_call_later(
                self.hass, 30, self._recovery_retry_elapsed
            )

    def _cancel_recovery_retry(self) -> None:
        """Cancel the background retry timer without deleting saved snapshots."""
        if self._recovery_retry_unsub:
            self._recovery_retry_unsub()
            self._recovery_retry_unsub = None

    def _entity_in_recovery_cooldown(self, entity_id: str) -> bool:
        """Return true while a just-reconnected device is being allowed to settle."""
        ready_after = self._device_ready_after.get(entity_id)
        return ready_after is not None and time.monotonic() < ready_after

    @callback
    def _device_recovery_delay_elapsed(self, entity_id: str, _now) -> None:
        """Schedule a fresh update after the per-device power-up grace period."""
        self._device_recovery_unsubs.pop(entity_id, None)
        self._device_ready_after.pop(entity_id, None)
        # Force this device to receive the current cover/theme again. A reconnect
        # can happen without any media metadata changing, and a bulb/curtain may
        # have acknowledged its power-on before its controller was actually ready.
        for output in self.matrix_outputs:
            if output.entity_id == entity_id:
                output.invalidate_display(forget_upload=True)
        self._theme_last_key.pop(entity_id, None)
        self._schedule_update()

    async def async_start(self) -> None:
        """Load recovery records, attempt safe restoration, and subscribe to changes."""
        try:
            stored = await self._session_store.async_load()
        except Exception as err:  # noqa: BLE001 - a damaged journal must not prevent loading
            stored = None
            self._recovery_pending = True
            _LOGGER.error("Could not load the saved album-art state journal: %s", _safe_error_text(err))
            self._set_status("Saved-state journal could not be read; updates paused while retrying", _safe_error_text(err))

        has_recovery_records = isinstance(stored, dict) and bool(
            stored.get("session_active")
            or stored.get("matrix_snapshots")
            or stored.get("theme_restore_pending")
            or stored.get("deferred_matrix_restores")
            or stored.get("deferred_theme_restores")
        )
        if has_recovery_records:
            self._session_journal = stored
            self._recovery_entity_ids = set(stored.get("matrix_snapshots", {}).keys())
            self._recovery_entity_ids.update(stored.get("theme_restore_pending", []))
            self._recovery_entity_ids.update(stored.get("deferred_matrix_restores", {}).keys())
            self._recovery_entity_ids.update(stored.get("deferred_theme_restores", {}).keys())
            self._theme_snapshots = deepcopy(stored.get("theme_snapshots", {}))
            self._theme_lights_touched = set(stored.get("theme_restore_pending", []))
            for entity_id in self._recovery_entity_ids:
                state = self.hass.states.get(entity_id)
                if state is not None and state.state not in ("unknown", "unavailable"):
                    # HA may start before a device is fully ready, even if its
                    # entity is already marked available.
                    self._delay_device_recovery(entity_id)
            for output in self.matrix_outputs:
                snapshot = stored.get("matrix_snapshots", {}).get(output.entity_id)
                if isinstance(snapshot, dict):
                    output.snapshot = deepcopy(snapshot)
            if stored.get("session_active") or stored.get("matrix_snapshots") or stored.get("theme_restore_pending"):
                self._recovery_pending = True
                self._set_status("Recovering saved pre-playback state")
                await self._async_restore_saved_state()
            else:
                self._recovery_pending = False
                self._schedule_recovery_retry()
                self._set_status("Waiting to restore previously unavailable devices")

        if self.matrix_enabled:
            await self._async_detect_resolution()

        if self.matrix_enabled and not self.matrix_output_enabled:
            await self._async_apply_matrix_output_override(False)

        entities = list(self._source_entity_ids())
        entities.extend(output.entity_id for output in self.matrix_outputs)
        entities.extend(self.theme_light_entities)
        entities.extend(self._recovery_entity_ids)
        self._track_state_entities(entities)

        # Run once after setup so the current player is picked up even when its
        # state does not change again for a while.
        self._schedule_update()

    def _delay_device_recovery(self, entity_id: str) -> None:
        """Hold commands for a short warm-up after a device becomes available."""
        old_unsub = self._device_recovery_unsubs.pop(entity_id, None)
        if old_unsub:
            old_unsub()
        if self._device_recovery_delay_seconds <= 0:
            self._device_ready_after.pop(entity_id, None)
            self._device_recovery_delay_elapsed(entity_id, None)
            return
        self._device_ready_after[entity_id] = time.monotonic() + self._device_recovery_delay_seconds
        # async_call_later invokes callbacks with a single ``now`` argument;
        # bind entity_id ahead of time instead of passing it as an unsupported
        # extra argument (which would make setup fail as soon as recovery starts).
        self._device_recovery_unsubs[entity_id] = async_call_later(
            self.hass,
            self._device_recovery_delay_seconds,
            partial(self._device_recovery_delay_elapsed, entity_id),
        )

    @callback
    def _handle_state_change(self, event: Event) -> None:
        """Debounce changes and let reconnecting devices settle before commands."""
        entity_id = event.data.get("entity_id")
        old_state = event.data.get("old_state")
        new_state = event.data.get("new_state")
        expected_matrix_power_on = self._note_matrix_state_change(entity_id, old_state, new_state)
        source_changed = entity_id in self._source_entity_ids()
        if source_changed:
            if not source_change_affects_artwork(old_state, new_state):
                return
            self._cancel_artwork_retry()
            if self._animation_upgrade_key is not None and not self._candidate_is_current(self._animation_upgrade_key):
                self._cancel_animation_upgrade()
            if new_state is not None and new_state.state in {"playing", "buffering"} and self._is_music_activity(new_state):
                self._end_plan_retry_pending = False
                self._cancel_session_end()
        device_entities = {output.entity_id for output in self.matrix_outputs}
        device_entities.update(self.theme_light_entities)
        device_entities.update(self._recovery_entity_ids)
        old_unavailable = old_state is None or old_state.state in ("unknown", "unavailable")
        new_available = new_state is not None and new_state.state not in ("unknown", "unavailable")
        powered_on = bool(
            old_state is not None and old_state.state == "off"
            and new_state is not None and new_state.state == "on"
        )
        if entity_id in device_entities and new_available and (
            old_unavailable or (powered_on and not expected_matrix_power_on)
        ):
            # Availability / power-on can precede a device being ready to accept
            # commands. Apply a per-device grace period; other devices continue
            # updating while this one settles.
            self._delay_device_recovery(entity_id)
            if self._device_recovery_delay_seconds > 0:
                self._set_status(
                    f"{entity_id} is powering up — waiting {self._device_recovery_delay_seconds}s before sending commands"
                )
            return
        stopped = source_changed and (new_state is None or new_state.state not in {"playing", "buffering"})
        self._schedule_update(immediate=stopped, reset_delay=source_changed)

    def _track_state_entities(self, entity_ids: list[str] | set[str]) -> None:
        """Subscribe to only new entities, including old targets needing recovery."""
        new_entities = set(entity_ids) - self._tracked_state_entities
        new_entities = {entity_id for entity_id in new_entities if entity_id}
        if not new_entities:
            return
        self._unsubscribers.append(
            async_track_state_change_event(
                self.hass, sorted(new_entities), self._handle_state_change
            )
        )
        self._tracked_state_entities.update(new_entities)

    @callback
    def _failure_retry_elapsed(self, _now) -> None:
        self._failure_retry_unsub = None
        if self._end_plan_retry_pending or getattr(self, "_end_plan_rollback_pending", False):
            self.hass.async_create_task(self._async_end_session())
            return
        self._schedule_update()

    def _schedule_failure_retry(self) -> None:
        """Retry transient device/API failures after a short cooldown."""
        if getattr(self, "_failure_retry_unsub", None) is None and not self._stopping:
            self._failure_retry_unsub = async_call_later(
                self.hass, 15, self._failure_retry_elapsed
            )

    def _schedule_update(self, *, immediate: bool = False, reset_delay: bool = True) -> None:
        """Settle metadata without allowing event bursts to starve processing."""
        if self._stopping:
            return
        now = time.monotonic()
        if self._update_burst_started is None:
            self._update_burst_started = now
        delay = 0.0 if immediate else max(0.3, self.source_stabilization)
        deadline = min(now + delay, self._update_burst_started + max(2.0, 2 * self.source_stabilization))
        if self._pending_update_unsub:
            if not reset_delay and self._pending_update_deadline is not None and self._pending_update_deadline <= deadline:
                return
            self._pending_update_unsub()
        self._pending_update_deadline = deadline
        self._pending_update_unsub = async_call_later(
            self.hass, max(0.0, deadline - now), self._run_scheduled_update
        )

    @callback
    def _run_scheduled_update(self, _now) -> None:
        self._pending_update_unsub = None
        self._pending_update_deadline = None
        self._update_burst_started = None
        self.hass.async_create_task(self.async_update())

    def _cancel_artwork_retry(self) -> None:
        if self._artwork_retry_unsub:
            self._artwork_retry_unsub()
            self._artwork_retry_unsub = None
        self._artwork_retry_deadline = None

    def _schedule_artwork_retry(self) -> None:
        """Schedule one retry for this song's temporary lookup failure."""
        delay = self._online_artwork_lookup.next_retry_delay
        if delay is None or self._stopping or self.manual_override:
            self._cancel_artwork_retry()
            return
        deadline = time.monotonic() + max(0.1, delay)
        if self._artwork_retry_deadline is not None and abs(deadline - self._artwork_retry_deadline) < 0.1:
            return
        self._cancel_artwork_retry()
        self._artwork_retry_deadline = deadline
        self._artwork_retry_unsub = async_call_later(
            self.hass, max(0.1, delay), self._artwork_retry_ready
        )

    @callback
    def _artwork_retry_ready(self, _now) -> None:
        self._artwork_retry_unsub = None
        self._artwork_retry_deadline = None
        if self._stopping or self.manual_override:
            return
        delay = self._online_artwork_lookup.next_retry_delay
        if delay is None:
            return
        if delay > 0.1:
            self._schedule_artwork_retry()
            return
        if any((state := self.hass.states.get(entity_id)) is not None
               and state.state == "playing" and self._is_music_activity(state)
               for entity_id in self._source_entity_ids()):
            self._schedule_update(immediate=True, reset_delay=False)

    async def async_stop(self) -> None:
        """Cancel listeners and restore pre-session state on unload when possible."""
        self._stopping = True
        self._cancel_artwork_retry()
        self._cancel_animation_upgrade(release_track=True)
        if self._pending_update_unsub:
            self._pending_update_unsub()
            self._pending_update_unsub = None
        if self._failure_retry_unsub:
            self._failure_retry_unsub()
            self._failure_retry_unsub = None
        self._cancel_session_end()
        self._cancel_recovery_retry()
        for unsubscribe in self._device_recovery_unsubs.values():
            unsubscribe()
        self._device_recovery_unsubs.clear()
        self._device_ready_after.clear()
        for unsubscribe in self._unsubscribers:
            unsubscribe()
        self._unsubscribers.clear()

        if self._session_active or self._recovery_pending:
            async with self._lock:
                self._recovery_pending = True
                await self._async_restore_saved_state()
                if not self._recovery_pending:
                    self._session_active = False
                    self._reset_matrix_session_state()
        self._cancel_recovery_retry()

    @callback
    def _cancel_session_end(self) -> None:
        """Cancel a pending playback-end grace timer."""
        self._session_end_generation += 1
        if self._pending_end_unsub:
            self._pending_end_unsub()
            self._pending_end_unsub = None
        if self._end_countdown_unsub:
            self._end_countdown_unsub()
            self._end_countdown_unsub = None
        self._session_end_deadline = None
        self._session_end_reason = None

    @callback
    def _schedule_session_end(self, reason: str | None = None) -> None:
        """Wait for a real end instead of reacting to a short handoff gap."""
        if not self._session_active:
            return
        if self._pending_end_unsub:
            if reason and reason != self._session_end_reason:
                self._session_end_reason = reason
                self._refresh_session_end_countdown()
            return
        self._session_end_reason = reason or "stopped"
        self._session_end_deadline = time.monotonic() + max(0, self.end_grace_seconds)
        self._pending_end_unsub = async_call_later(
            self.hass, max(0, self.end_grace_seconds),
            partial(self._session_end_ready, generation=self._session_end_generation),
        )
        self._refresh_session_end_countdown()
        _LOGGER.debug(
            "Playback %s; end-of-session grace period is %s seconds",
            self._session_end_reason, self.end_grace_seconds,
        )

    @callback
    def _refresh_session_end_countdown(self) -> None:
        """Publish a visible countdown and schedule the next status refresh."""
        if not self._pending_end_unsub or self._session_end_deadline is None:
            return
        remaining = max(0, ceil(self._session_end_deadline - time.monotonic()))
        if remaining <= 0:
            return
        if self._session_end_reason == "paused":
            source = self.hass.states.get(self._last_source_entity) if self._last_source_entity else None
            source_name = (
                source.attributes.get("friendly_name") or self._last_source_entity
                if source is not None else self._last_source_entity
            )
            summary = f"{source_name} reports paused" if source_name else "A configured player reports paused"
        else:
            summary = "No configured player is playing"
        self._set_status(f"{summary} — ending in {remaining}s", notify_entities=False)
        if self._end_countdown_unsub:
            self._end_countdown_unsub()
        delay = min(1.0, max(0.05, self._session_end_deadline - time.monotonic()))
        self._end_countdown_unsub = async_call_later(
            self.hass, delay, self._session_end_countdown_tick
        )

    @callback
    def _session_end_countdown_tick(self, _now) -> None:
        self._end_countdown_unsub = None
        self._refresh_session_end_countdown()

    @callback
    def _session_end_ready(self, _now, *, generation: int | None = None) -> None:
        if generation is not None and generation != self._session_end_generation:
            return
        self._last_session_end_reason = self._session_end_reason or "stopped"
        self._last_session_end_source = self._last_source_entity
        source = self.hass.states.get(self._last_source_entity) if self._last_source_entity else None
        self._last_session_end_source_name = (
            (source.attributes.get("friendly_name") or self._last_source_entity)
            if source is not None else self._last_source_entity
        )
        self._last_session_end_source_state = source.state if source is not None else "missing"
        self._pending_end_unsub = None
        if self._end_countdown_unsub:
            self._end_countdown_unsub()
            self._end_countdown_unsub = None
        self._session_end_deadline = None
        self._session_end_reason = None
        self.hass.async_create_task(self._async_end_session(generation=generation))

    def _note_matrix_state_change(self, entity_id: str, old_state, new_state) -> bool:
        """Invalidate display assumptions and identify our own power-on confirmation."""
        output = next((item for item in self.matrix_outputs if item.entity_id == entity_id), None)
        if output is None:
            return False
        old_value = old_state.state if old_state is not None else None
        new_value = new_state.state if new_state is not None else None
        expected_power_on = False
        if new_value in {None, "unknown", "unavailable"} or old_value in {None, "unknown", "unavailable"}:
            output.invalidate_display(forget_upload=True)
            # A real reconnect still needs the configured device warm-up.
            output.power_on_expected_until = None
        elif new_value != "on":
            output.invalidate_display()
        if old_value != "on" and new_value == "on":
            expected_power_on = output.consume_expected_power_on(time.monotonic())
            if not expected_power_on:
                # A later manual off must not inherit our earlier fallback.
                output.temporary_fallback_off = False
                output.invalidate_display()
        if old_state is not None and new_state is not None:
            old_effect = old_state.attributes.get("effect")
            new_effect = new_state.attributes.get("effect")
            if old_effect != new_effect and str(new_effect or "").casefold() != "image":
                output.invalidate_display()
        return expected_power_on

    def _ready_matrix_outputs(self) -> list[MatrixOutput]:
        """Return configured outputs that can receive a matrix update now."""
        ready: list[MatrixOutput] = []
        deferred = (self._session_journal or {}).get("deferred_matrix_restores", {})
        for output in self.matrix_outputs:
            state = self.hass.states.get(output.entity_id)
            if self._entity_in_recovery_cooldown(output.entity_id):
                output.last_result = "reconnecting_wait"
                continue
            if output.entity_id in deferred:
                output.last_result = "restore_pending"
                continue
            if state is None or state.state in ("unknown", "unavailable"):
                # Re-send the current cover when the WLED entity returns.
                output.invalidate_display(forget_upload=True)
                output.last_result = "unavailable"
                continue
            if (
                state.state != "on" and not output.matrix_turn_on
                and not output.can_restore_fallback_power
            ):
                output.last_result = "off_not_allowed_to_turn_on"
                continue
            ready.append(output)
        return ready

    def _matrix_wait_status(self) -> str:
        """Explain why none of the selected WLED outputs can be updated."""
        if self.manual_override:
            return "Manual override — automatic control paused"
        if self.matrix_enabled and self._startup_output_errors and not self.matrix_outputs:
            return "WLED target configuration error — see diagnostics"
        if self.matrix_enabled and not self.matrix_output_enabled:
            if any(output.last_result == "override_off_failed" for output in self.matrix_outputs):
                return "Matrix artwork off — matrix power-off failed; see diagnostics"
            if any(
                output.last_result == "override_off_waiting_reconnect"
                for output in self.matrix_outputs
            ):
                return "Matrix artwork off — waiting for WLED to reconnect"
            return (
                "Matrix artwork off — room lights continue"
                if self.theme_light_entities else "Matrix artwork off"
            )
        states = [self.hass.states.get(output.entity_id) for output in self.matrix_outputs]
        deferred = (self._session_journal or {}).get("deferred_matrix_restores", {})
        available_entities = {
            output.entity_id for output, state in zip(self.matrix_outputs, states)
            if state is not None and state.state not in ("unknown", "unavailable")
        }
        waiting_restore = sorted(available_entities.intersection(deferred))
        if waiting_restore and not available_entities.difference(deferred):
            return "Waiting for saved state restoration on " + ", ".join(waiting_restore)
        if not states or all(state is None or state.state in ("unknown", "unavailable") for state in states):
            return "WLED unavailable — waiting to update matrix"
        warmup_remaining = [
            max(1, ceil(self._device_ready_after[output.entity_id] - time.monotonic()))
            for output in self.matrix_outputs
            if output.entity_id in available_entities
            and output.entity_id not in deferred
            and self._entity_in_recovery_cooldown(output.entity_id)
        ]
        if warmup_remaining:
            return f"Matrix warming up — {min(warmup_remaining)}s remaining"
        if any(
            state is not None and state.state not in ("on", "unknown", "unavailable")
            and (
                output.last_result == "off_not_allowed_to_turn_on"
                or (not output.matrix_turn_on and not output.can_restore_fallback_power)
            )
            for output, state in zip(self.matrix_outputs, states)
        ):
            return "Matrix is off — theme lights continue" if self.theme_light_entities else "Matrix is off — album art output skipped"
        if any(output.last_result == "snapshot_failed" for output in self.matrix_outputs):
            return "Could not save matrix state — artwork output skipped; see diagnostics"
        return "Matrix update pending — check output diagnostics"

    def _reset_matrix_session_state(self, preserve_visible_art: bool = False) -> None:
        """Clear snapshots and optionally retain metadata for a kept cover."""
        self._theme_last_key.clear()
        for output in self.matrix_outputs:
            output.snapshot = None
            output.last_matrix_key = None
            output.temporary_fallback_off = False
            output.power_on_expected_until = None
            if not preserve_visible_art:
                output.invalidate_display()
                output.last_filename = None
                output.last_art_fingerprint = None
                output.uploaded_fingerprint = None
        self._last_filename = self.matrix_outputs[0].last_filename if self.matrix_outputs else None

    async def async_refresh_artwork(self) -> None:
        """Retry downloads and online searches even at an unchanged artwork URL."""
        async with self._lock:
            self._cancel_artwork_retry()
            self._cancel_animation_upgrade()
            self._artwork_fetcher.clear_cache()
            self._online_artwork_lookup.clear_cache(retry_authentication=True)
            self._animated_artwork_lookup.clear_cache(retry_authentication=True)
            self._artwork_source_key = None
        await self.async_update(force=True)

    async def async_update(self, force: bool = False) -> None:
        """Update one chosen music source to every configured matrix and theme light."""
        if self._stopping:
            return
        async with self._lock:
            if self._stopping:
                return
            if self._end_plan_rollback_pending:
                self._schedule_failure_retry()
                return
            if self._end_plan_retry_pending:
                if any((state := self.hass.states.get(entity_id)) is not None
                       and state.state in {"playing", "buffering"} and self._is_music_activity(state)
                       for entity_id in self._source_entity_ids()):
                    self._end_plan_retry_pending = False
                else:
                    self._schedule_failure_retry()
                    return
            if self._recovery_pending:
                # First resolve the previous session as far as possible. Failed
                # device snapshots move to a durable per-device queue. Recovery
                # failure caused by a device is non-blocking once the snapshot is
                # safely queued; journal read/write errors remain blocking because
                # proceeding without durable originals could corrupt user state.
                if not await self._async_restore_saved_state():
                    # Device failures are moved to durable deferred queues by
                    # _async_restore_saved_state. False therefore means we could
                    # not safely read/persist the journal, so stop before changing
                    # any new output.
                    return
            await self._async_restore_deferred_state()
            if self.matrix_enabled and not self.matrix_output_enabled:
                failures, _waiting = await self._async_power_off_matrix_outputs(force=False)
                if failures:
                    self._schedule_failure_retry()
            if self.manual_override:
                self._set_status("Manual override — automatic control paused")
                return
            source_ids = self._source_entity_ids()
            if not source_ids:
                self._online_artwork_lookup.release_current_track()
                self._set_status("No media-player sources configured")
                return

            source_states = [self.hass.states.get(entity_id) for entity_id in source_ids]
            active_or_buffering = any(
                state and state.state in ("playing", "buffering")
                and self._is_music_activity(state)
                for state in source_states
            )
            paused_present = any(
                state and state.state == "paused"
                and self._is_music_activity(state)
                for state in source_states
            )
            if active_or_buffering:
                self._cancel_session_end()
            elif paused_present:
                if self._session_active:
                    if self.pause_behavior == "hold":
                        self._cancel_session_end()
                        self._set_status("Playback paused — keeping current artwork")
                    else:
                        # Some Cast players retain the album and report "paused"
                        # after casting ends. The grace countdown lets a genuine
                        # pause resume while still ending abandoned sessions.
                        self._schedule_session_end("paused")
                    return
            elif self._session_active:
                self._schedule_session_end("stopped")
                return
            else:
                self._online_artwork_lookup.release_current_track()

            ready_outputs = (
                self._ready_matrix_outputs()
                if self.matrix_enabled and self.matrix_output_enabled else []
            )
            # A matrix with an outstanding snapshot from an earlier session must
            # finish restoring that state before we overwrite it with new art.
            # Keep it isolated; other matrices and theme lights continue normally.
            deferred_matrix = (self._session_journal or {}).get("deferred_matrix_restores", {})
            ready_outputs = [
                output for output in ready_outputs
                if output.entity_id not in deferred_matrix
            ]

            playing_with_art = []
            playing_without_art = []
            online_artwork_by_source: dict[str, bytes] = {}
            ignored_inputs = []
            unrecognized_no_art_sources = []
            paused_present = False
            for entity_id in source_ids:
                state = self.hass.states.get(entity_id)
                if state is None:
                    continue
                if self._is_ignored_input(state):
                    if state.state in ("playing", "buffering"):
                        ignored_inputs.append((entity_id, state))
                    continue
                if state.state == "paused" and self._is_music_activity(state):
                    paused_present = True
                if state.state != "playing":
                    continue
                image_urls = self._artwork_urls(state)
                if image_urls:
                    if self._is_music_activity(state):
                        playing_with_art.append((entity_id, state, image_urls))
                    else:
                        unrecognized_no_art_sources.append((entity_id, state))
                elif (
                    self._session_has_artwork_for(state)
                    or (
                        self._has_music_metadata(state)
                        and not self._is_video_media(state)
                    )
                ):
                    playing_without_art.append((entity_id, state, None))
                else:
                    unrecognized_no_art_sources.append((entity_id, state))

            # Select the room's preferred music source before resolving a cover.
            # Missing artwork on that player must not hand control to a lower
            # priority player that happens to have a native image already.
            preferred_source = first_playing_source(
                source_ids,
                [
                    SourceCandidate(entity_id, state, urls or ())
                    for entity_id, state, urls in playing_with_art + playing_without_art
                ],
            )
            if preferred_source is not None:
                playing_with_art = [
                    candidate for candidate in playing_with_art
                    if candidate[0] == preferred_source.entity_id
                ]
                playing_without_art = [
                    candidate for candidate in playing_without_art
                    if candidate[0] == preferred_source.entity_id
                ]

            # Resolve missing covers only for audio candidates the normal source
            # filter already accepts. In particular, this never searches generic
            # video/TV input metadata. The lookup is cached and rate-limited.
            if self.online_artwork_lookup_enabled and not playing_with_art and playing_without_art:
                lookup_candidate = first_priority_candidate(
                    source_ids, [(entity, state) for entity, state, _url in playing_without_art]
                )
                if lookup_candidate is not None:
                    source_entity, state = lookup_candidate
                    title = state.attributes.get("media_title")
                    artist = (
                        state.attributes.get("media_artist")
                        or state.attributes.get("media_album_artist")
                    )
                    if title and artist and not self._is_video_media(state):
                        image_bytes = await self._online_artwork_lookup.async_lookup(
                            title, artist, state.attributes.get("media_album_name"),
                            on_request=lambda: self._set_status("Searching online for a missing cover"),
                        )
                        self._schedule_artwork_retry()
                        if image_bytes:
                            online_artwork_by_source[source_entity] = image_bytes
                            playing_with_art.append((source_entity, state, ()))
                    else:
                        self._online_artwork_lookup.release_current_track()

            if not playing_with_art and playing_without_art:
                selected_candidate = first_priority_candidate(
                    source_ids, [(entity, state) for entity, state, _url in playing_without_art]
                )
                if selected_candidate is not None and self._session_has_artwork_for(selected_candidate[1]):
                    source_entity, state = selected_candidate
                    self._last_source_entity = source_entity
                    self._current_title = state.attributes.get("media_title")
                    self._current_artist = state.attributes.get("media_artist")
                    continuation = self.no_art_during_session_behavior
                    if continuation == "keep_previous":
                        self._set_status(
                            "Playing without cover art — keeping the current scene"
                            if self._last_key is not None and self._last_key[0] == "no_art"
                            else "Playing without cover art — keeping the previous artwork"
                        )
                        return
                    key = NoArtKey(
                        "no_art", source_entity, self._current_title, self._current_artist,
                        continuation, self.no_art_color, self.no_art_brightness,
                        "during_session",
                    )
                    await self._async_apply_no_art_scene(
                        source_entity, key, ready_outputs, behavior=continuation
                    )
                    return
                # A new unrelated no-art source cannot inherit another source's
                # dashboard cover. Same-session keep-previous returned above.
                self._clear_artwork_data()

            # Preserve the previous cover through brief gaps, but never let stickiness
            # defeat a higher-priority source becoming eligible.
            if self._last_source_entity and self._last_source_entity in source_ids:
                current_source_state = self.hass.states.get(self._last_source_entity)
                if (
                    current_source_state
                    and current_source_state.state in ("playing", "buffering")
                    and self._is_music_activity(current_source_state)
                ):
                    current_source_url = self._artwork_url(current_source_state)
                    current_index = source_ids.index(self._last_source_entity)
                    preferred_index = (
                        source_ids.index(preferred_source.entity_id)
                        if preferred_source is not None else None
                    )
                    if (
                        current_source_state.state == "buffering"
                        or (
                            not current_source_url
                            and self._last_source_entity not in online_artwork_by_source
                            and self.no_art_behavior == "wait"
                        )
                    ) and (
                        preferred_index is None or preferred_index >= current_index
                    ):
                        self._set_status(
                            f"Waiting for artwork from {self._last_source_entity}; keeping previous cover"
                        )
                        return

            if not playing_with_art and playing_without_art and self.no_art_behavior != "wait":
                selected_candidate = first_priority_candidate(
                    source_ids, [(entity, state) for entity, state, _url in playing_without_art]
                )
                if selected_candidate is None:
                    self._set_status("Waiting for playback")
                    return
                source_entity, state = selected_candidate
                self._last_source_entity = source_entity
                self._current_title = state.attributes.get("media_title")
                self._current_artist = state.attributes.get("media_artist")
                key = NoArtKey(
                    "no_art", source_entity, self._current_title, self._current_artist,
                    self.no_art_behavior, self.no_art_color, self.no_art_brightness,
                    "start",
                )
                matrix_needs_fallback = any(
                    output.last_matrix_key != key for output in ready_outputs
                )
                theme_needs_fallback = any(
                    self._theme_last_key.get(entity_id) != key
                    and (light_state := self.hass.states.get(entity_id)) is not None
                    and light_state.state not in ("unknown", "unavailable")
                    and (light_state.state == "on" or self.theme_lights_turn_on)
                    for entity_id in self.theme_light_entities
                )
                if not force and key == self._last_key and not matrix_needs_fallback and not theme_needs_fallback:
                    self._set_status("Playing — fallback scene unchanged")
                    return
                await self._async_apply_no_art_scene(
                    source_entity, key, ready_outputs
                )
                return
            if not playing_with_art and playing_without_art and self.no_art_behavior == "wait":
                selected_candidate = first_priority_candidate(
                    source_ids, [(entity, state) for entity, state, _url in playing_without_art]
                )
                if selected_candidate:
                    self._last_source_entity, state = selected_candidate
                    self._current_title = state.attributes.get("media_title")
                    self._current_artist = state.attributes.get("media_artist")

            if playing_with_art:
                selected_candidate = first_priority_candidate(
                    source_ids, [(entity, (state, urls)) for entity, state, urls in playing_with_art]
                )
                if selected_candidate is None:
                    self._set_status("Waiting for playback")
                    return
                source_entity, (state, selected_urls) = selected_candidate
                self._last_source_entity = source_entity
                self._current_title = state.attributes.get("media_title")
                self._current_artist = (
                    state.attributes.get("media_artist")
                    or state.attributes.get("media_album_artist")
                )
                self._online_artwork_lookup.observe_track(
                    self._current_title, self._current_artist,
                    state.attributes.get("media_album_name"),
                )
                self._animated_artwork_lookup.observe_track(
                    self._current_title, self._current_artist,
                    state.attributes.get("media_album_name"),
                )
                key = TrackKey(
                    "track", source_entity, state.attributes.get("media_title"),
                    self._current_artist, selected_urls,
                    str(state.attributes.get("media_content_type") or ""),
                    str(state.attributes.get("source") or ""),
                    str(state.attributes.get("soundtouchplus_source") or ""),
                    str(state.attributes.get("app_name") or ""),
                    str(state.attributes.get("media_album_name") or ""),
                    not selected_urls and source_entity in online_artwork_by_source,
                    self._artwork_provider_revision,
                )
                matrix_needs_this_cover = any(output.last_matrix_key != key for output in ready_outputs)
                deferred_theme = (self._session_journal or {}).get("deferred_theme_restores", {})
                theme_needs_this_cover = any(
                    entity_id not in deferred_theme
                    and not self._entity_in_recovery_cooldown(entity_id)
                    and self._theme_last_key.get(entity_id) != key
                    and (light_state := self.hass.states.get(entity_id)) is not None
                    and light_state.state not in ("unknown", "unavailable")
                    and (light_state.state == "on" or self.theme_lights_turn_on)
                    for entity_id in self.theme_light_entities
                )
                if not force and key == self._last_key and not matrix_needs_this_cover and not theme_needs_this_cover:
                    self._schedule_animation_upgrade(key)
                    if self.matrix_enabled and not ready_outputs:
                        self._set_status(self._matrix_wait_status())
                    else:
                        self._set_status("Playing — artwork unchanged")
                    return
            else:
                music_buffering = any(
                    state and state.state == "buffering"
                    and self._is_music_activity(state)
                    for state in source_states
                )
                if playing_without_art or music_buffering:
                    waiting_source = next((item for item in source_ids if (
                        (st := self.hass.states.get(item)) is not None
                        and st.state in ("playing", "buffering")
                        and self._is_music_activity(st)
                    )), None)
                    self._set_status(
                        f"Waiting for artwork from {waiting_source}" if waiting_source else "Waiting for artwork"
                    )
                    return
                if ignored_inputs:
                    source_name = ignored_inputs[0][1].attributes.get(
                        "friendly_name", ignored_inputs[0][0]
                    )
                    self._set_status(
                        f"Ignoring configured input from {source_name} — waiting for music"
                    )
                    return
                if unrecognized_no_art_sources:
                    unrecognized_state = unrecognized_no_art_sources[0][1]
                    source_name = unrecognized_state.attributes.get(
                        "friendly_name", unrecognized_no_art_sources[0][0]
                    )
                    if (
                        self._is_video_media(unrecognized_state)
                        and not self._has_music_metadata(unrecognized_state)
                        and self._has_artwork(unrecognized_state)
                    ):
                        status = f"Video media ignored from {source_name} — waiting for music metadata"
                    elif (
                        self._is_video_media(unrecognized_state)
                        and self._has_music_metadata(unrecognized_state)
                        and not self._has_artwork(unrecognized_state)
                    ):
                        status = (
                            f"Video source has track details but no cover art — "
                            f"waiting to confirm music from {source_name}"
                        )
                    else:
                        status = f"Waiting for music metadata or cover art from {source_name}"
                    self._set_status(status)
                    return
                if paused_present:
                    self._set_status("Playback paused — keeping current artwork")
                    return
                self._set_status("Waiting for playback")
                return

            try:
                self._set_status(
                    f"Loading online cover for {source_entity}"
                    if source_entity in online_artwork_by_source
                    else f"Loading artwork from {source_entity}"
                )
                if ready_outputs:
                    await self._async_detect_resolution()
                image_provider = "player"
                image_match = None
                image_is_animation_upgrade = False
                if key == self._artwork_source_key and self._artwork_source_bytes is not None:
                    image_bytes = self._artwork_source_bytes
                    image_provider = self._artwork_metadata.get("artwork_provider") or "player"
                    image_match = self._artwork_metadata.get("artwork_match")
                    image_is_animation_upgrade = bool(self._artwork_metadata.get("is_animation_upgrade"))
                elif source_entity in online_artwork_by_source:
                    image_bytes = online_artwork_by_source[source_entity]
                    image_provider = self._online_artwork_lookup.diagnostics()["matched_provider"] or "online"
                    image_match = self._online_artwork_lookup.diagnostics().get("matched_query")
                else:
                    try:
                        image_bytes = await self._artwork_fetcher.async_fetch_candidates(selected_urls)
                    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, OSError):
                        # A player may expose a stale proxy URL rather than a valid
                        # image. A metadata lookup is still useful for audio-only
                        # players, but a TV/video source remains opt-in through its
                        # normal source artwork and is never searched here.
                        title = state.attributes.get("media_title")
                        artist = (
                            state.attributes.get("media_artist")
                            or state.attributes.get("media_album_artist")
                        )
                        if not (
                            self.online_artwork_lookup_enabled
                            and not self._is_video_media(state)
                            and title and artist
                        ):
                            raise
                        fallback_image = await self._online_artwork_lookup.async_lookup(
                            title, artist, state.attributes.get("media_album_name"),
                            on_request=lambda: self._set_status("Searching online for a replacement cover"),
                        )
                        self._schedule_artwork_retry()
                        if not fallback_image:
                            raise
                        image_bytes = fallback_image
                        image_provider = self._online_artwork_lookup.diagnostics()["matched_provider"] or "online"
                        image_match = self._online_artwork_lookup.diagnostics().get("matched_query")
                prepared = self._artwork_data
                if (
                    key != self._artwork_source_key or prepared is None
                    or self._artwork_prepared_animations != self.animated_artwork_enabled
                ):
                    prepared = await self.hass.async_add_executor_job(
                        prepare_artwork_data, image_bytes, self.animated_artwork_enabled,
                        max(8, min(16, len(self.theme_light_entities))),
                    )
                theme_palette = list(prepared.palette)

                if not self._candidate_is_current(key):
                    _LOGGER.debug("Discarding album art because the source changed during fetch")
                    self._schedule_update()
                    return
                self._last_theme_palette = list(theme_palette)
                self._artwork_source_bytes = image_bytes
                self._artwork_source_key = key
                self._artwork_metadata = {
                    "source_entity_id": source_entity,
                    "media_title": state.attributes.get("media_title"),
                    "media_artist": state.attributes.get("media_artist") or state.attributes.get("media_album_artist"),
                    "media_album_name": state.attributes.get("media_album_name"),
                    "artwork_provider": image_provider,
                    "artwork_match": image_match,
                    "artwork_match_description": (
                        artwork_match_description(
                            str(state.attributes.get("media_title") or ""),
                            self._current_artist or "", image_match,
                        ) if image_provider != "player" else "Artwork supplied by the music player"
                    ),
                    "is_animation_upgrade": image_is_animation_upgrade,
                    "is_fallback": False,
                }
                self._store_prepared_artwork(prepared)
                if image_provider == "player":
                    self._player_artwork = PlayerArtwork(
                        TrackKey(*key), image_bytes, prepared, dict(self._artwork_metadata)
                    )
                elif self._player_artwork is not None and self._player_artwork.key != key:
                    self._player_artwork = None

                session_was_active = self._session_active
                if key[0] == "track" and not self._session_active:
                    if not await self._async_begin_session():
                        return
                elif key[0] == "track" and session_was_active:
                    # A WLED target can be unavailable during session start and
                    # return later. Retry its per-output snapshot before writing
                    # to it so restoration remains safe for every matrix.
                    missing_snapshots = [output for output in ready_outputs if output.snapshot is None]
                    if missing_snapshots:
                        await asyncio.gather(
                            *(self._async_snapshot_matrix_output(output) for output in missing_snapshots),
                            return_exceptions=True,
                        )
                        if not await self._async_refresh_session_journal():
                            self._set_status("Could not safely save matrix state — update skipped")
                            return
                if key[0] == "track":
                    self._session_had_artwork = True
                    self._session_artwork_sources.add(source_entity)
                    self._session_artwork_context[source_entity] = {
                        attribute: str(state.attributes.get(attribute) or "")
                        for attribute in (
                            "source", "soundtouchplus_source", "app_name",
                            "media_content_type", "media_title",
                        )
                    }
                    self._schedule_animation_upgrade(key)

                # A failed snapshot protects only that matrix; healthy outputs and
                # room lighting continue independently.
                ready_outputs = [output for output in ready_outputs if output.snapshot is not None]
                if not ready_outputs:
                    theme_ok = True
                    if key[0] == "track":
                        previous_key = self._last_key
                        restore_fallback_brightness = bool(
                            previous_key is not None
                            and previous_key[0] == "no_art"
                            and self.no_art_brightness > 0
                        )
                        restore_no_art_power = bool(
                            previous_key is not None
                            and previous_key[0] == "no_art"
                            and (previous_key[4] == "turn_off" or tuple(previous_key[5]) == (0, 0, 0))
                        )
                        theme_result = await self._async_update_theme_lights(
                            theme_palette, key,
                            restore_saved_brightness=restore_fallback_brightness,
                            restore_previously_on=restore_no_art_power,
                        )
                        theme_ok = theme_result is not False
                    self._last_key = key
                    self._last_success_at = datetime.now().astimezone().isoformat()
                    if self.matrix_enabled:
                        status = self._matrix_wait_status()
                        if not theme_ok:
                            status += "; theme-light update incomplete — see diagnostics"
                    elif self.theme_light_entities:
                        status = (
                            "Theme-light update incomplete — check diagnostics"
                            if not theme_ok else "Playing — theme lights updated"
                        )
                    else:
                        status = "Playing — artwork and colors available in Home Assistant"
                    self._set_status(status)
                    return

                async def update_theme() -> bool | None:
                    if key[0] == "track" and self.theme_light_entities:
                        # When the matrix explicitly fades through black between covers,
                        # optionally fade decorative lights down in parallel, then apply
                        # the new album palette after their black transition completes.
                        previous_key = self._last_key
                        if (
                            self.fade_to_black
                            and self.fade_theme_lights_with_matrix
                            and previous_key is not None
                            and previous_key != key
                        ):
                            await self._async_fade_theme_lights_to_black()
                        restore_fallback_brightness = bool(
                            previous_key is not None
                            and previous_key[0] == "no_art"
                            and self.no_art_brightness > 0
                        )
                        restore_no_art_power = bool(
                            previous_key is not None
                            and previous_key[0] == "no_art"
                            and (previous_key[4] == "turn_off" or tuple(previous_key[5]) == (0, 0, 0))
                        )
                        return await self._async_update_theme_lights(
                            theme_palette, key,
                            restore_saved_brightness=restore_fallback_brightness,
                            restore_previously_on=restore_no_art_power,
                        )
                    return None

                results = await asyncio.gather(
                    *(self._async_update_matrix_output(output, image_bytes, key, force)
                      for output in ready_outputs),
                    update_theme(),
                    return_exceptions=True,
                )
                matrix_results = results[:-1]
                theme_result = results[-1]
                theme_error = (
                    _safe_error_text(theme_result) if isinstance(theme_result, Exception)
                    else ("One or more theme lights failed; see per-light diagnostics"
                          if theme_result is False else None)
                )
                if theme_error:
                    _LOGGER.warning("Theme-light update failed: %s", theme_error)
                updated = sum(result == "updated" for result in matrix_results)
                unchanged = sum(result == "unchanged" for result in matrix_results)
                failures = []
                for output, result in zip(ready_outputs, matrix_results):
                    if isinstance(result, Exception):
                        message = _safe_error_text(result)
                        output.last_result = "error"
                        output.last_error = message
                        failures.append((output.entity_id, message))
                    elif isinstance(result, str) and result.startswith("error:"):
                        message = _safe_error_text(result.partition(":")[2].strip())
                        output.last_result = "error"
                        output.last_error = message
                        failures.append((output.entity_id, message))
                    elif result != "skipped":
                        output.last_result = result
                        if result in ("updated", "unchanged"):
                            output.last_error = None
                stale = any(result == "stale" for result in matrix_results)
                self._last_key = key
                self._last_success_at = datetime.now().astimezone().isoformat()
                self._last_filename = self.matrix_outputs[0].last_filename if self.matrix_outputs else None

                if stale:
                    self._schedule_update()
                elif failures or theme_error:
                    detail_parts = [f"{entity}: {message}" for entity, message in failures]
                    if theme_error:
                        detail_parts.append(f"theme lights: {theme_error}")
                    detail = "; ".join(detail_parts)[:450]
                    self._set_status(
                        "Artwork update incomplete — check diagnostics" if self.matrix_outputs
                        else "Theme-light update failed — check diagnostics",
                        detail,
                    )
                    self._schedule_failure_retry()
                elif updated:
                    self._set_status("Playing — album art updated")
                elif unchanged:
                    self._set_status("Playing — artwork unchanged")
                elif matrix_results and all(result == "skipped" for result in matrix_results):
                    self._set_status(self._matrix_wait_status())
                else:
                    self._set_status("Artwork update skipped — waiting for matrix/source readiness")
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, RuntimeError, OSError) as err:
                safe_error = _safe_error_text(err)
                _LOGGER.warning("Album-art update failed: %s", safe_error)
                self._set_status("Artwork update failed", safe_error)
                self._schedule_failure_retry()

    async def _async_apply_no_art_scene(
        self,
        source_entity: str,
        key: tuple,
        ready_outputs: list[MatrixOutput],
        behavior: str | None = None,
    ) -> None:
        """Use a configured solid-color or off scene for active audio without cover art."""
        behavior = behavior or key[4]
        if not self._session_active and not await self._async_begin_session():
            return

        missing_snapshots = [output for output in ready_outputs if output.snapshot is None]
        if missing_snapshots:
            await asyncio.gather(
                *(self._async_snapshot_matrix_output(output) for output in missing_snapshots),
                return_exceptions=True,
            )
            if not await self._async_refresh_session_journal():
                self._set_status("Could not safely save matrix state — fallback scene skipped")
                return
        ready_outputs = [output for output in ready_outputs if output.snapshot is not None]

        color = tuple(key[5])
        turn_off = behavior == "turn_off" or color == (0, 0, 0)
        matrix_off = turn_off or behavior == "fallback_color"

        async def update_matrix(output: MatrixOutput) -> tuple[MatrixOutput, str | None]:
            if output.snapshot is None:
                return output, "Could not save the original matrix state"
            state = self.hass.states.get(output.entity_id)
            if state is None or state.state in ("unknown", "unavailable"):
                output.last_result = "unavailable"
                return output, None
            if self._entity_in_recovery_cooldown(output.entity_id):
                output.last_result = "reconnecting_wait"
                return output, None
            if not self._candidate_is_current(key):
                return output, "stale"
            if matrix_off:
                # Send the command even when HA's cached state already says off.
                output.power_on_expected_until = None
                output.temporary_fallback_off = bool(
                    output.snapshot.get("on")
                    and (state.state == "on" or output.temporary_fallback_off)
                )
                output.invalidate_display()
                await output.wled.async_post_state({"on": False})
                if not self._candidate_is_current(key):
                    return output, "stale"
                output.last_result = "no_art_off" if turn_off else "no_art_matrix_off"
            else:
                if state.state != "on" and not output.matrix_turn_on:
                    output.last_result = "off_not_allowed_to_turn_on"
                    return output, None
                if not self._candidate_is_current(key):
                    return output, "stale"
                brightness = round(self.no_art_brightness * 255 / 100) if self.no_art_brightness else None
                await output.wled.async_activate_solid_color(
                    list(color), output.transition_seconds, brightness=brightness
                )
                if not self._candidate_is_current(key):
                    return output, "stale"
                output.last_result = "no_art_color"
                output.invalidate_display()
                output.last_updated_at = datetime.now().astimezone().isoformat()
            output.last_matrix_key = key
            output.last_art_fingerprint = None
            output.last_error = None
            return output, None

        matrix_results = await asyncio.gather(
            *(update_matrix(output) for output in ready_outputs),
            return_exceptions=True,
        )
        matrix_errors: list[str] = []
        stale = False
        for output, result in zip(ready_outputs, matrix_results):
            if isinstance(result, Exception):
                output.last_result = "error"
                output.last_error = _safe_error_text(result)
                matrix_errors.append(f"{output.entity_id}: {output.last_error}")
                continue
            _output, error = result
            if error == "stale":
                stale = True
            elif error:
                output.last_result = "error"
                output.last_error = error
                matrix_errors.append(f"{output.entity_id}: {error}")

        theme_result = await self._async_update_theme_lights(
            [color], key, turn_off=turn_off, preserve_color=True,
            brightness_percent=self.no_art_brightness,
        )
        if stale or not self._candidate_is_current(key):
            self._schedule_update()
            return

        self._last_theme_palette = [] if turn_off else [color]
        self._clear_artwork_data()
        source = self.hass.states.get(source_entity)
        attributes = source.attributes if source is not None else {}
        self._artwork_metadata = {
            "source_entity_id": source_entity,
            "media_title": attributes.get("media_title"),
            "media_artist": attributes.get("media_artist") or attributes.get("media_album_artist"),
            "media_album_name": attributes.get("media_album_name"),
            "artwork_provider": None,
            "is_fallback": not turn_off,
        }
        if not turn_off:
            self._artwork_metadata["fallback_rgb"] = color
        self._last_key = key
        self._last_success_at = datetime.now().astimezone().isoformat()
        if matrix_errors or theme_result is False:
            details = matrix_errors + (
                ["One or more theme lights failed"] if theme_result is False else []
            )
            self._set_status(
                "Fallback scene incomplete — check diagnostics", "; ".join(details)[:450]
            )
            self._schedule_failure_retry()
        elif turn_off:
            self._set_status("Playing — outputs turned off because artwork is unavailable")
        else:
            self._set_status(
                "Playing — fallback color applied to room lights; matrix kept off"
                if self.theme_light_entities
                else "Playing without artwork — matrix kept off"
            )

    async def _async_update_matrix_output(
        self, output: MatrixOutput, image_bytes: bytes, key: tuple, force: bool,
        *, allow_paused: bool = False,
    ) -> str:
        """Prepare, upload, activate, and clean up the artwork on one matrix."""
        if output.snapshot is None:
            output.last_result = "snapshot_failed"
            output.last_error = output.snapshot_error or "Could not save the original matrix state"
            return "skipped"

        def matrix_ready_to_activate() -> bool:
            """Recheck physical state after work that can outlast a user action."""
            if self._stopping or self.manual_override or not self.matrix_output_enabled:
                return False
            current_state = self.hass.states.get(output.entity_id)
            if current_state is None or current_state.state in {"unknown", "unavailable"}:
                output.invalidate_display(forget_upload=True)
                output.last_result = "unavailable"
                return False
            if self._entity_in_recovery_cooldown(output.entity_id):
                output.invalidate_display(forget_upload=True)
                output.last_result = "reconnecting_wait"
                return False
            if current_state.state != "on" and (
                allow_paused or (not output.matrix_turn_on and not output.can_restore_fallback_power)
            ):
                output.invalidate_display()
                output.last_result = "off_not_allowed_to_turn_on"
                return False
            return True

        if not matrix_ready_to_activate():
            return "skipped"
        target_state = self.hass.states.get(output.entity_id)
        if not self._candidate_is_current(key, allow_paused=allow_paused):
            return "stale"

        _frame_png, gif_bytes = await self.hass.async_add_executor_job(
            prepare_image,
            image_bytes,
            output.width,
            output.height,
            output.image_fit,
            output.image_zoom,
            output.image_crop_position,
            output.image_blur_strength,
            output.image_background_brightness,
            self.animated_artwork_enabled,
        )
        if not matrix_ready_to_activate():
            return "skipped"
        # A user may have switched the display off during image preparation.
        target_state = self.hass.states.get(output.entity_id)
        # Include all animation frames in identity; two animated covers can share
        # a first frame while differing later in the sequence.
        art_fingerprint = hashlib.sha256(gif_bytes).hexdigest()
        if (
            not force and output.display_valid and target_state.state == "on"
            and art_fingerprint == output.last_art_fingerprint
        ):
            output.last_matrix_key = key
            output.last_result = "unchanged"
            output.last_error = None
            return "unchanged"

        filename = self._filename_for(gif_bytes, output)
        if output.uploaded_fingerprint != art_fingerprint:
            await output.wled.async_unlock_if_needed()
            await output.wled.async_upload_gif(gif_bytes, filename)
            output.uploaded_fingerprint = art_fingerprint
        if not self._candidate_is_current(key, allow_paused=allow_paused):
            _LOGGER.debug("Discarding uploaded artwork for %s because the source changed", output.entity_id)
            output.last_result = "stale"
            return "stale"
        if not matrix_ready_to_activate():
            return "skipped"

        output.invalidate_display()
        chosen_transition = "fade" if output.fade_to_black else self._choose_transition_style(output)
        restore_fallback_brightness = bool(
            key[0] == "track"
            and self._last_key is not None
            and self._last_key[0] == "no_art"
            and self.no_art_brightness > 0
            and output.snapshot.get("on")
            and output.snapshot.get("bri") is not None
        )
        restored_brightness = output.snapshot.get("bri") if restore_fallback_brightness else None

        target_state = self.hass.states.get(output.entity_id)
        fade_through_black = bool(
            output.fade_to_black and target_state is not None and target_state.state == "on"
            and not output.temporary_fallback_off
        )
        try:
            if fade_through_black:
                await output.wled.async_activate_solid_black(output.transition_seconds)
                await asyncio.sleep(output.transition_seconds + output.black_pause)
                if not self._candidate_is_current(key, allow_paused=allow_paused):
                    output.last_result = "stale"
                    return "stale"
                if not matrix_ready_to_activate():
                    return "skipped"
                chosen_transition = "fade"
            # An off matrix is already black. Load its image and power it on in
            # one request, avoiding an empty Solid-effect interval on recovery.
            target_state = self.hass.states.get(output.entity_id)
            if output.temporary_fallback_off or (target_state is not None and target_state.state != "on"):
                output.expect_power_on(time.monotonic())
            await output.wled.async_activate_image(
                filename, chosen_transition, output.transition_seconds,
                brightness=restored_brightness,
            )
        except Exception:
            output.power_on_expected_until = None
            raise

        output.last_filename = filename
        output.last_art_fingerprint = art_fingerprint
        output.display_valid = True
        output.temporary_fallback_off = False
        output.last_matrix_key = key
        output.last_updated_at = datetime.now().astimezone().isoformat()
        output.last_result = "updated"
        output.last_error = None
        output.snapshot_error = None
        if (output.fade_to_black or chosen_transition != "instant") and output.transition_seconds > 0:
            await asyncio.sleep(output.transition_seconds + 0.15)
        snapshot_segment = (output.snapshot or {}).get("segment", {})
        preserved_image = snapshot_segment.get("n") if isinstance(snapshot_segment, dict) else None
        await output.wled.async_cleanup_old_images(
            filename,
            preserve_filenames=[preserved_image] if preserved_image else None,
        )
        return "updated"

    def _candidate_is_current(self, key: tuple, *, allow_paused: bool = False) -> bool:
        """Return whether the candidate is current and no higher-priority source won."""
        if self._stopping or self.manual_override:
            return False
        if key[0] == "no_art":
            candidate = NoArtKey(*key) if len(key) == 8 else NoArtKey(*key, "start")
            entity_id = candidate.source_entity
            state = self.hass.states.get(entity_id)
            if (
                state is None or state.state != "playing"
                or not self._is_music_activity(state)
            ):
                return False
            if self._has_artwork(state):
                return False
            policy = candidate.policy
            configured_behavior = (
                self.no_art_during_session_behavior
                if policy == "during_session" else self.no_art_behavior
            )
            if (
                state.attributes.get("media_title") != candidate.title
                or state.attributes.get("media_artist") != candidate.artist
                or configured_behavior != candidate.behavior
                or self.no_art_color != tuple(candidate.color)
                or self.no_art_brightness != candidate.brightness
            ):
                return False
            ordered_sources = self._source_entity_ids()
            if entity_id not in ordered_sources:
                return False
            for higher_priority_id in ordered_sources[:ordered_sources.index(entity_id)]:
                higher_state = self.hass.states.get(higher_priority_id)
                if (
                    higher_state and higher_state.state == "playing"
                    and self._is_music_activity(higher_state)
                ):
                    return False
            return True

        if key[0] == "track":
            if len(key) != len(TrackKey._fields):
                return False
            candidate = TrackKey(*key)
            entity_id = candidate.source_entity
            state = self.hass.states.get(entity_id)
            if (
                state is None
                or state.state not in ({"playing", "paused"} if allow_paused and self._session_active else {"playing"})
                or not self._is_music_activity(state)
            ):
                return False
            artist = (
                state.attributes.get("media_artist")
                or state.attributes.get("media_album_artist")
            )
            online_lookup = candidate.online_lookup
            if online_lookup and self._artwork_urls(state):
                return False
            if online_lookup and not bool(self.entry.options.get(
                CONF_ONLINE_ARTWORK_LOOKUP, DEFAULT_ONLINE_ARTWORK_LOOKUP
            )):
                return False
            current_key = TrackKey(
                "track", entity_id, state.attributes.get("media_title"),
                artist, self._artwork_urls(state),
                str(state.attributes.get("media_content_type") or ""),
                str(state.attributes.get("source") or ""),
                str(state.attributes.get("soundtouchplus_source") or ""),
                str(state.attributes.get("app_name") or ""),
                str(state.attributes.get("media_album_name") or ""),
                online_lookup,
                self._artwork_provider_revision,
            )
            if current_key != key:
                return False
            ordered_sources = self._source_entity_ids()
            if entity_id not in ordered_sources:
                return False
            # A more important player may have started while this cover was being
            # downloaded. Prevent a lower-priority upload from winning that race.
            for higher_priority_id in ordered_sources[:ordered_sources.index(entity_id)]:
                higher_state = self.hass.states.get(higher_priority_id)
                if not higher_state or higher_state.state != "playing":
                    continue
                if not self._is_music_activity(higher_state):
                    continue
                return False
            return True

        return False

    def _ensure_visible_color(self, rgb: tuple[int, int, int]) -> tuple[int, int, int]:
        """Apply the configured low-light safeguard to a palette color."""
        return ensure_visible_color(rgb, self.prevent_dark_theme_colors)

    def _theme_light_transition_value(self) -> float | None:
        """Resolve whether theme-light commands use instant, timed, or device timing."""
        if self.theme_fade_mode == "instant":
            return 0
        if self.theme_fade_mode == "device_default":
            return None
        return self.theme_light_transition

    async def _async_fade_theme_lights_to_black(self) -> None:
        """Fade selected decorative lights to black before the next cover palette."""
        entity_ids = []
        for entity_id in self.theme_light_entities:
            state = self.hass.states.get(entity_id)
            if state is None or state.state != "on":
                continue
            entity_ids.append(entity_id)
        if not entity_ids:
            return
        service_data = {"entity_id": entity_ids, "rgb_color": [0, 0, 0]}
        transition = self._theme_light_transition_value()
        if transition is not None:
            service_data["transition"] = transition
        try:
            await asyncio.wait_for(
                self.hass.services.async_call("light", "turn_on", service_data, blocking=True),
                timeout=15,
            )
            if transition:
                await asyncio.sleep(transition)
        except Exception as err:  # noqa: BLE001 - decorative fade must not block matrix updates
            _LOGGER.debug("Could not fade theme lights to black for cover transition: %s", _safe_error_text(err))

    async def _async_update_theme_lights(
        self,
        palette: list[tuple[int, int, int]],
        key: object | None = None,
        *,
        turn_off: bool = False,
        preserve_color: bool = False,
        brightness_percent: int = 0,
        restore_saved_brightness: bool = False,
        restore_previously_on: bool = False,
    ) -> bool | None:
        """Apply album colors concurrently so one slow light cannot serialize the rest."""
        if not self.theme_light_entities or (not palette and not turn_off):
            return None

        deferred = (self._session_journal or {}).get("deferred_theme_restores", {})
        assigned_colors = (
            ([palette[0]] * len(self.theme_light_entities))
            if preserve_color and palette
            else build_theme_colors(palette, self.theme_color_mode, len(self.theme_light_entities))
            if palette and not turn_off else []
        )
        prepared: list[tuple[str, str, dict]] = []

        # Snapshot and persist each light before issuing any commands. This part is
        # deliberately serialized so the durable journal never races with itself;
        # device commands below run concurrently.
        for index, entity_id in enumerate(self.theme_light_entities):
            state = self.hass.states.get(entity_id)
            if entity_id in deferred:
                self._theme_light_results[entity_id] = {
                    "last_result": "restore_pending", "last_error": None,
                }
                continue
            if self._entity_in_recovery_cooldown(entity_id):
                self._theme_light_results[entity_id] = {
                    "last_result": "reconnecting_wait", "last_error": None,
                }
                continue
            if state is None or state.state in ("unknown", "unavailable"):
                self._theme_light_results[entity_id] = {
                    "last_result": "unavailable", "last_error": None,
                }
                continue
            if key is not None and self._theme_last_key.get(entity_id) == key:
                continue
            saved_state = self._theme_snapshots.get(entity_id, {})
            restore_previously_on_now = bool(
                restore_previously_on and saved_state.get("was_on")
            )
            if (
                not turn_off and state.state != "on" and not self.theme_lights_turn_on
                and not restore_previously_on_now
            ):
                self._theme_light_results[entity_id] = {
                    "last_result": "off_not_enabled", "last_error": None,
                }
                continue

            supported_modes = state.attributes.get("supported_color_modes")
            if not turn_off and supported_modes:
                color_modes = {str(mode) for mode in supported_modes}
                if not color_modes.intersection({"rgb", "hs", "xy", "rgbw", "rgbww"}):
                    self._theme_light_results[entity_id] = {
                        "last_result": "unsupported_color", "last_error": None,
                    }
                    _LOGGER.debug("Skipping theme light %s because it does not support color", entity_id)
                    continue

            service_name = "turn_off" if turn_off else "turn_on"
            service_data = {"entity_id": entity_id}
            if not turn_off:
                rgb = assigned_colors[index % len(assigned_colors)]
                if not preserve_color:
                    rgb = balance_color_spectrum(rgb, self.balance_theme_spectrum)
                    rgb = self._ensure_visible_color(rgb)
                service_data["rgb_color"] = [int(rgb[0]), int(rgb[1]), int(rgb[2])]
                if brightness_percent:
                    service_data["brightness"] = max(1, min(255, round(brightness_percent * 255 / 100)))
                elif restore_saved_brightness:
                    if saved_state.get("brightness") is not None:
                        service_data["brightness"] = int(saved_state["brightness"])
                elif state.state != "on":
                    if saved_state.get("brightness") is not None:
                        service_data["brightness"] = int(saved_state["brightness"])
            transition = self._theme_light_transition_value()
            if transition is not None:
                service_data["transition"] = transition

            if self._session_active and entity_id not in self._theme_snapshots:
                self._theme_snapshots[entity_id] = self._snapshot_theme_light(state)
                if not await self._async_refresh_session_journal():
                    self._theme_snapshots.pop(entity_id, None)
                    continue
            if entity_id not in self._theme_lights_touched:
                self._theme_lights_touched.add(entity_id)
                if self._session_journal is None:
                    persisted = await self._async_refresh_session_journal()
                else:
                    self._session_journal["theme_restore_pending"] = sorted(self._theme_lights_touched)
                    persisted = await self._async_persist_session_journal()
                if not persisted:
                    self._theme_lights_touched.discard(entity_id)
                    if self._session_journal is not None:
                        self._session_journal["theme_restore_pending"] = sorted(self._theme_lights_touched)
                    continue
            prepared.append((entity_id, service_name, service_data))

        async def apply_one(
            entity_id: str, service_name: str, service_data: dict
        ) -> tuple[str, bool, str | None]:
            # Saving other lights' snapshots can take time. Respect a power-off
            # or reconnect observed since this command was prepared.
            state = self.hass.states.get(entity_id)
            if self._stopping or self.manual_override:
                return entity_id, False, None
            if state is None or state.state in {"unknown", "unavailable"}:
                self._theme_light_results[entity_id] = {
                    "last_result": "unavailable", "last_error": None,
                }
                return entity_id, False, None
            if self._entity_in_recovery_cooldown(entity_id):
                self._theme_light_results[entity_id] = {
                    "last_result": "reconnecting_wait", "last_error": None,
                }
                return entity_id, False, None
            if (
                service_name == "turn_on" and state.state != "on"
                and not self.theme_lights_turn_on
                and not (restore_previously_on and self._theme_snapshots.get(entity_id, {}).get("was_on"))
            ):
                self._theme_light_results[entity_id] = {
                    "last_result": "off_not_enabled", "last_error": None,
                }
                return entity_id, False, None
            try:
                # A broken cloud/local light integration must not hang the session
                # lock forever. Other selected lights are commanded concurrently.
                await asyncio.wait_for(
                    self.hass.services.async_call("light", service_name, service_data, blocking=True),
                    timeout=15,
                )
                return entity_id, True, None
            except Exception as err:  # noqa: BLE001 - isolate each light failure
                return entity_id, False, _safe_error_text(err)

        results = await asyncio.gather(
            *(apply_one(entity_id, service_name, data)
              for entity_id, service_name, data in prepared),
            return_exceptions=True,
        )
        updated = 0
        failed = False
        for result in results:
            if isinstance(result, Exception):
                # apply_one catches ordinary exceptions, but still guard this edge.
                _LOGGER.warning("Unexpected error applying album-art theme lighting", exc_info=True)
                failed = True
                continue
            entity_id, success, error = result
            if success:
                updated += 1
                if key is not None:
                    self._theme_last_key[entity_id] = key
                self._theme_light_results[entity_id] = {
                    "last_result": "turned_off" if turn_off else "updated",
                    "last_error": None,
                    "last_updated_at": datetime.now().astimezone().isoformat(),
                }
            elif error is not None:
                failed = True
                self._theme_light_results[entity_id] = {
                    "last_result": "error", "last_error": error,
                }
                _LOGGER.warning("Could not set album-art theme color on %s: %s", entity_id, error)

        if failed:
            self._schedule_failure_retry()
        if updated:
            _LOGGER.debug("Updated %d theme lights from the album-art palette", updated)
        return not failed

    async def _async_persist_session_journal(self) -> bool:
        """Persist pre-session state before any destructive display/light change."""
        if self._session_journal is None:
            return True
        try:
            await self._session_store.async_save(self._session_journal)
            return True
        except Exception as err:  # noqa: BLE001 - refusing to update is safer than losing original state
            _LOGGER.error("Could not persist album-art session state: %s", _safe_error_text(err))
            self._set_status("Could not safely save original state — updates skipped", _safe_error_text(err))
            return False

    async def _async_refresh_session_journal(self) -> bool:
        """Refresh snapshots in the journal after a newly available output is captured."""
        if self._session_journal is None:
            self._session_journal = new_session_journal(session_active=True)
        self._session_journal.setdefault("deferred_matrix_restores", {})
        self._session_journal.setdefault("deferred_theme_restores", {})
        self._session_journal["session_active"] = True
        self._session_journal["matrix_snapshots"] = {
            output.entity_id: deepcopy(output.snapshot)
            for output in self.matrix_outputs if output.snapshot is not None
        }
        self._session_journal["theme_snapshots"] = deepcopy(self._theme_snapshots)
        self._session_journal["theme_restore_pending"] = sorted(self._theme_lights_touched)
        return await self._async_persist_session_journal()

    async def _async_finish_session_journal_if_empty(self) -> bool:
        """Finish current-session restoration while retaining offline-device debt."""
        if self._session_journal is None:
            self._recovery_pending = False
            return True
        journal = self._session_journal
        matrix_snapshots = journal.get("matrix_snapshots", {})
        theme_pending = journal.get("theme_restore_pending", [])
        if matrix_snapshots or theme_pending:
            self._recovery_pending = True
            await self._async_persist_session_journal()
            return False

        deferred = bool(
            journal.get("deferred_matrix_restores")
            or journal.get("deferred_theme_restores")
        )
        if deferred:
            # The current session is fully handled. Keep a durable record for
            # offline devices but don't let that record gate new playback sessions.
            journal["session_active"] = False
            self._recovery_pending = False
            if not await self._async_persist_session_journal():
                self._recovery_pending = True
                return False
            self._schedule_recovery_retry()
            return True

        try:
            await self._session_store.async_remove()
        except Exception as err:  # noqa: BLE001 - retain journal so a later start can retry
            _LOGGER.error("Could not clear restored album-art session state: %s", _safe_error_text(err))
            self._recovery_pending = True
            self._set_status("Original state restored; cleanup pending", _safe_error_text(err))
            return False
        self._session_journal = None
        self._recovery_pending = False
        self._theme_snapshots.clear()
        self._theme_lights_touched.clear()
        self._cancel_recovery_retry()
        return True

    async def _async_restore_one_theme_light(self, entity_id: str, snapshot: dict) -> bool:
        """Restore one theme light; report failure so its snapshot can be retried."""
        state = self.hass.states.get(entity_id)
        if (
            self._entity_in_recovery_cooldown(entity_id)
            or state is None or state.state in ("unknown", "unavailable")
        ):
            return False
        if snapshot.get("_pending_end_behavior") == "turn_off_all":
            try:
                await asyncio.wait_for(
                    self.hass.services.async_call(
                        "light", "turn_off", {"entity_id": entity_id}, blocking=True
                    ),
                    timeout=15,
                )
                return True
            except Exception:  # noqa: BLE001 - keep the durable off action for retry
                _LOGGER.warning("Could not turn off theme light %s", entity_id, exc_info=True)
                return False
        service_data = {"entity_id": entity_id}
        transition = self._theme_light_transition_value()
        if transition is not None:
            service_data["transition"] = transition
        if snapshot.get("was_on"):
            restore_keys = [
                "effect", "rgb_color", "hs_color", "xy_color", "rgbw_color",
                "rgbww_color", "color_temp_kelvin", "color_temp", "white",
            ]
            if snapshot.get("_restore_brightness", self.restore_theme_brightness):
                restore_keys.append("brightness")
            for key in restore_keys:
                if key in snapshot:
                    service_data[key] = snapshot[key]
            domain_service = "turn_on"
        else:
            domain_service = "turn_off"
        try:
            await asyncio.wait_for(
                self.hass.services.async_call("light", domain_service, service_data, blocking=True),
                timeout=15,
            )
            return True
        except (HomeAssistantError, ValueError, TypeError, aiohttp.ClientError, asyncio.TimeoutError) as err:
            _LOGGER.warning("Could not restore theme light %s: %s", entity_id, _safe_error_text(err))
            return False
        except Exception:  # noqa: BLE001 - keep a failed light in the recovery journal
            _LOGGER.warning("Unexpected error restoring theme light %s", entity_id, exc_info=True)
            return False

    def _output_for_saved_target(self, entity_id: str, snapshot: dict) -> MatrixOutput:
        """Build a temporary client for restoring a previously selected matrix.

        This matters when a user changes the target in Configure after a session
        failed to restore. The previous target's saved state must not be orphaned.
        """
        segment = snapshot.get("segment", {})
        segment_id = int(segment.get("id", self.segment_id)) if isinstance(segment, dict) else self.segment_id
        target_url = self._resolve_wled_url(entity_id)
        client = WLEDClient(
            self.session, target_url, str(snapshot.get("pin", self.pin) or ""),
            segment_id, f"{self.filename_prefix}_{entity_id.split('.')[-1]}",
        )
        return MatrixOutput(
            entity_id=entity_id,
            wled=client,
            width=self.width,
            height=self.height,
            auto_detect_size=False,
            image_fit=self.image_fit,
            image_crop_position=self.image_crop_position,
            image_zoom=self.image_zoom,
            image_blur_strength=self.image_blur_strength,
            image_background_brightness=self.image_background_brightness,
            filename_prefix=client.filename_prefix,
            segment_id=segment_id,
            transition_style=self.transition_style,
            transition_seconds=self.transition_seconds,
            fade_to_black=False,
            black_pause=self.black_pause,
            matrix_turn_on=self.matrix_turn_on,
            snapshot=deepcopy(snapshot),
        )

    async def _async_attempt_matrix_restore(
        self, entity_id: str, snapshot: dict
    ) -> tuple[str, MatrixOutput | None, str | None]:
        """Attempt one restore independently, retaining snapshots on all failures."""
        if self._entity_in_recovery_cooldown(entity_id):
            return "pending", None, None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return "pending", None, None
        output: MatrixOutput | None = None
        try:
            output = next((item for item in self.matrix_outputs if item.entity_id == entity_id), None)
            saved_pin = str(snapshot.get("pin", self.pin) or "")
            if output is None or getattr(output.wled, "pin", saved_pin) != saved_pin:
                output = self._output_for_saved_target(entity_id, snapshot)
            output.snapshot = deepcopy(snapshot)
            pending_behavior = snapshot.get("_pending_end_behavior")
            if pending_behavior == "black":
                await output.wled.async_activate_solid_black(output.transition_seconds)
                await asyncio.sleep(max(0.1, output.transition_seconds) + 0.05)
            elif pending_behavior == "turn_off_matrix":
                await output.wled.async_post_state({"on": False})
            else:
                await self._async_restore_wled_state(output)
            return "restored", output, None
        except Exception as err:  # noqa: BLE001 - keep the saved state for another attempt
            return "failed", output, _safe_error_text(err)

    async def _async_restore_saved_state(self, *, preserve_visible_art: bool = False) -> bool:
        """Restore an ended/interrupted session, deferring failures per device."""
        if self._end_plan_rollback_pending:
            # A superseded ending plan must be replaced on disk before any
            # command can discard or restore the original session snapshots.
            if not await self._async_persist_session_journal():
                self._schedule_failure_retry()
                return False
            self._end_plan_rollback_pending = False
        if self._session_journal is None:
            try:
                stored = await self._session_store.async_load()
            except Exception as err:  # noqa: BLE001
                self._recovery_pending = True
                self._set_status("Could not load saved state — waiting to retry", _safe_error_text(err))
                return False
            if not isinstance(stored, dict):
                self._recovery_pending = False
                return True
            self._session_journal = stored

        journal = self._session_journal
        journal.setdefault("matrix_snapshots", {})
        journal.setdefault("theme_snapshots", {})
        journal.setdefault("theme_restore_pending", [])
        journal.setdefault("deferred_matrix_restores", {})
        journal.setdefault("deferred_theme_restores", {})
        if not self.matrix_output_enabled:
            for snapshots_key in ("matrix_snapshots", "deferred_matrix_restores"):
                for snapshot in journal[snapshots_key].values():
                    if isinstance(snapshot, dict):
                        self._set_matrix_override_restore(snapshot, False)
            for output in self.matrix_outputs:
                if output.snapshot is not None:
                    self._set_matrix_override_restore(output.snapshot, False)
        self._recovery_entity_ids.update(journal["matrix_snapshots"].keys())
        self._recovery_entity_ids.update(journal.get("theme_restore_pending", []))
        self._recovery_entity_ids.update(journal["deferred_matrix_restores"].keys())
        self._recovery_entity_ids.update(journal["deferred_theme_restores"].keys())
        
        # Restore matrices and theme lights concurrently, and restore matrices
        # concurrently with each other. One slow endpoint must not serialize the
        # recovery path for all healthy devices.
        self._theme_snapshots = deepcopy(journal.get("theme_snapshots", {}))
        self._theme_lights_touched = set(journal.get("theme_restore_pending", []))
        matrix_snapshots = journal["matrix_snapshots"]
        matrix_items = list(matrix_snapshots.items())
        theme_restore_task = asyncio.create_task(self._async_restore_theme_lights())
        matrix_results = await asyncio.gather(
            *(self._async_attempt_matrix_restore(entity_id, snapshot)
              for entity_id, snapshot in matrix_items),
            return_exceptions=True,
        )
        configured_targets = {item.entity_id for item in self.matrix_outputs}
        for (entity_id, snapshot), result in zip(matrix_items, matrix_results):
            if isinstance(result, Exception):
                status, output, safe_error = "failed", None, _safe_error_text(result)
            else:
                status, output, safe_error = result
            if status == "restored":
                matrix_snapshots.pop(entity_id, None)
                if output and entity_id in configured_targets:
                    output.snapshot = None
                if output:
                    output.last_result = (
                        "matrix_override_applied"
                        if snapshot.get("_matrix_override_disabled") else "restored"
                    )
                    output.last_error = None
                self._startup_output_errors.pop(entity_id, None)
            elif status == "failed":
                if output is not None:
                    output.last_error = safe_error
                    output.last_result = "restore_deferred"
                self._startup_output_errors[entity_id] = safe_error or "State restoration failed"
                self._deferred_restore_retry_after[entity_id] = time.monotonic() + 30
                _LOGGER.warning(
                    "Could not restore saved WLED state for %s; will retry independently: %s",
                    entity_id, safe_error,
                )
        await theme_restore_task

        deferred_matrix = journal["deferred_matrix_restores"]
        for entity_id, snapshot in list(matrix_snapshots.items()):
            deferred_matrix.setdefault(entity_id, deepcopy(snapshot))
            matrix_snapshots.pop(entity_id, None)
            output = next((item for item in self.matrix_outputs if item.entity_id == entity_id), None)
            if output:
                output.snapshot = None
                output.last_result = "restore_pending_reconnect"
                if not output.last_error:
                    output.last_error = "Original state saved; waiting for this matrix to become ready for restoration."

        deferred_theme = journal["deferred_theme_restores"]
        for entity_id in list(self._theme_lights_touched):
            snapshot = self._theme_snapshots.get(entity_id) or journal.get("theme_snapshots", {}).get(entity_id)
            if snapshot:
                deferred_theme.setdefault(entity_id, deepcopy(snapshot))
                state = self.hass.states.get(entity_id)
                if (
                    state is not None and state.state not in ("unknown", "unavailable")
                    and not self._entity_in_recovery_cooldown(entity_id)
                ):
                    # A reachable light that rejected a restore gets a backoff;
                    # a reconnect event clears it after the warm-up delay.
                    self._deferred_restore_retry_after[entity_id] = time.monotonic() + 30
            self._theme_lights_touched.discard(entity_id)
            self._theme_snapshots.pop(entity_id, None)

        # This recovery pass ends the old session. Deferred device state is stored
        # separately so a new playback session can start on all healthy devices.
        journal["session_active"] = False
        journal["matrix_snapshots"] = matrix_snapshots
        journal["theme_snapshots"] = deepcopy(self._theme_snapshots)
        journal["theme_restore_pending"] = sorted(self._theme_lights_touched)
        completed = await self._async_finish_session_journal_if_empty()
        self._session_active = False
        self._session_had_artwork = False
        self._session_artwork_sources.clear()
        self._session_artwork_context.clear()
        self._theme_snapshots = deepcopy(journal.get("theme_snapshots", {}))
        self._theme_lights_touched = set(journal.get("theme_restore_pending", []))
        if completed:
            if deferred_matrix or deferred_theme:
                self._set_status("Recovered available devices — waiting to restore offline devices")
                self._schedule_recovery_retry()
            else:
                self._set_status("Saved pre-playback state restored")
            self._reset_matrix_session_state(preserve_visible_art=preserve_visible_art)
            return True

        self._recovery_pending = True
        self._set_status("State recovery is pending — healthy devices continue independently")
        return False

    async def _async_restore_deferred_state(self) -> None:
        """Retry deferred device restoration in parallel without gating playback."""
        journal = self._session_journal
        if not journal:
            return
        deferred_matrix = journal.setdefault("deferred_matrix_restores", {})
        deferred_theme = journal.setdefault("deferred_theme_restores", {})

        now = time.monotonic()
        matrix_items = [
            (entity_id, snapshot) for entity_id, snapshot in deferred_matrix.items()
            if now >= self._deferred_restore_retry_after.get(entity_id, 0)
        ]
        theme_items = [
            (entity_id, snapshot) for entity_id, snapshot in deferred_theme.items()
            if now >= self._deferred_restore_retry_after.get(entity_id, 0)
        ]
        if not matrix_items and not theme_items:
            self._schedule_recovery_retry()
            return
        matrix_restore_future = asyncio.gather(
            *(self._async_attempt_matrix_restore(entity_id, snapshot)
              for entity_id, snapshot in matrix_items),
            return_exceptions=True,
        )
        theme_restore_future = asyncio.gather(
            *(self._async_restore_one_theme_light(entity_id, snapshot)
              for entity_id, snapshot in theme_items),
            return_exceptions=True,
        )
        matrix_results, theme_results = await asyncio.gather(
            matrix_restore_future, theme_restore_future
        )
        for (entity_id, _snapshot), result in zip(matrix_items, matrix_results):
            existing = next((item for item in self.matrix_outputs if item.entity_id == entity_id), None)
            if isinstance(result, Exception):
                status, _output, error = "failed", None, _safe_error_text(result)
            else:
                status, _output, error = result
            if status == "restored":
                deferred_matrix.pop(entity_id, None)
                self._deferred_restore_retry_after.pop(entity_id, None)
                if existing:
                    existing.last_result = (
                        "matrix_override_applied_after_reconnect"
                        if _snapshot.get("_matrix_override_disabled")
                        else "end_behavior_applied_after_reconnect"
                        if _snapshot.get("_pending_end_behavior") in {"black", "turn_off_matrix"}
                        else "restored_after_reconnect"
                    )
                    existing.last_error = None
                    existing.invalidate_display()
                    existing.temporary_fallback_off = False
                    existing.snapshot = None
                _LOGGER.info("Completed deferred action for reconnected matrix %s", entity_id)
            elif status == "failed":
                self._deferred_restore_retry_after[entity_id] = time.monotonic() + 30
                if existing:
                    existing.last_result = "restore_retrying"
                    existing.last_error = error
                _LOGGER.debug("Deferred matrix restoration failed for %s: %s", entity_id, error)

        for (entity_id, _snapshot), result in zip(theme_items, theme_results):
            if result is True:
                deferred_theme.pop(entity_id, None)
                self._deferred_restore_retry_after.pop(entity_id, None)
                self._theme_last_key.pop(entity_id, None)
                _LOGGER.info("Restored saved state for reconnected theme light %s", entity_id)
            else:
                self._deferred_restore_retry_after[entity_id] = time.monotonic() + 30

        if journal.get("deferred_matrix_restores") or journal.get("deferred_theme_restores"):
            journal["session_active"] = bool(self._session_active)
            if not await self._async_persist_session_journal():
                return
            self._schedule_recovery_retry()
        elif not journal.get("matrix_snapshots") and not journal.get("theme_restore_pending"):
            if self._session_active:
                journal["deferred_matrix_restores"] = {}
                journal["deferred_theme_restores"] = {}
                await self._async_persist_session_journal()
            else:
                try:
                    await self._session_store.async_remove()
                    self._session_journal = None
                    self._cancel_recovery_retry()
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning("Could not clear completed recovery journal: %s", _safe_error_text(err))
        if journal and not journal.get("deferred_matrix_restores") and not journal.get("deferred_theme_restores"):
            self._set_status("Deferred device restoration complete")

    async def _async_begin_session(self) -> bool:
        """Capture and persist every available original state before first changes."""
        if self._session_active:
            return True

        self._session_had_artwork = False
        self._session_artwork_sources.clear()
        self._session_artwork_context.clear()

        outputs_to_snapshot: list[MatrixOutput] = []
        deferred_matrix = (self._session_journal or {}).get("deferred_matrix_restores", {})
        deferred_theme = (self._session_journal or {}).get("deferred_theme_restores", {})
        for output in self.matrix_outputs:
            if output.entity_id in deferred_matrix:
                output.snapshot = None
                continue
            output.snapshot = None
            output.snapshot_error = None
            state = self.hass.states.get(output.entity_id)
            if state is not None and state.state not in ("unknown", "unavailable"):
                outputs_to_snapshot.append(output)
        if outputs_to_snapshot:
            await asyncio.gather(
                *(self._async_snapshot_matrix_output(output) for output in outputs_to_snapshot),
                return_exceptions=True,
            )

        self._theme_snapshots = {}
        self._theme_lights_touched.clear()
        for entity_id in self.theme_light_entities:
            if entity_id in deferred_theme:
                continue
            state = self.hass.states.get(entity_id)
            if state is not None and state.state not in ("unknown", "unavailable"):
                self._theme_snapshots[entity_id] = self._snapshot_theme_light(state)
        self._session_active = True
        previous_journal = self._session_journal or {}
        deferred_matrix = deepcopy(previous_journal.get("deferred_matrix_restores", {}))
        deferred_theme = deepcopy(previous_journal.get("deferred_theme_restores", {}))
        self._session_journal = new_session_journal(
            session_active=True,
            matrix_snapshots={
                output.entity_id: deepcopy(output.snapshot)
                for output in self.matrix_outputs
                if output.snapshot is not None and output.entity_id not in deferred_matrix
            },
            theme_snapshots=self._theme_snapshots,
            deferred_matrix_restores=deferred_matrix,
            deferred_theme_restores=deferred_theme,
        )
        if not await self._async_persist_session_journal():
            self._session_active = False
            self._session_artwork_sources.clear()
            self._session_artwork_context.clear()
            self._session_journal = None
            for output in self.matrix_outputs:
                output.snapshot = None
            self._theme_snapshots.clear()
            return False
        return True

    async def _async_read_matrix_snapshot(self, output: MatrixOutput) -> dict:
        """Read the restorable WLED state without changing manager session data."""
        state = await output.wled.async_get_state()
        segment = next(
            (item for item in state.get("seg", [])
             if isinstance(item, dict) and int(item.get("id", -1)) == output.segment_id),
            None,
        )
        if segment is None:
            raise RuntimeError(
                f"WLED segment {output.segment_id} was not found on {output.entity_id}; "
                "refusing to modify this matrix"
            )
        accepted_segment_keys = (
            "id", "start", "stop", "grp", "spc", "of", "on", "frz",
            "bri", "cct", "col", "fx", "sx", "ix", "pal", "sel",
            "rev", "mi", "o1", "o2", "o3", "si", "m12", "n",
        )
        segment_snapshot = {
            key: deepcopy(segment[key]) for key in accepted_segment_keys if key in segment
        }
        return {
            "on": state.get("on"),
            "bri": state.get("bri"),
            "pin": self.pin,
            "bs": state.get("bs"),
            "ps": state.get("ps"),
            "segment": segment_snapshot,
        }

    async def _async_snapshot_matrix_output(self, output: MatrixOutput) -> bool:
        """Capture one matrix's current state, protecting it if the read fails."""
        try:
            output.snapshot = await self._async_read_matrix_snapshot(output)
            output.snapshot_error = None
            output.last_error = None
            output.last_result = "ready"
            return True
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, TypeError, RuntimeError, OSError) as err:
            output.snapshot = None
            output.snapshot_error = _safe_error_text(err)
            output.last_error = output.snapshot_error
            output.last_result = "snapshot_failed"
            _LOGGER.warning("Could not snapshot WLED state for %s: %s", output.entity_id, _safe_error_text(err))
            return False

    @staticmethod
    def _snapshot_theme_light(state) -> dict:
        """Capture on/off state, brightness, effect, and the current color."""
        attributes = state.attributes
        snapshot = {"was_on": state.state == "on"}
        if attributes.get("brightness") is not None:
            snapshot["brightness"] = attributes["brightness"]

        effect = attributes.get("effect")
        if effect and str(effect).strip().lower() not in ("none", "off"):
            snapshot["effect"] = effect
            return snapshot

        mode_to_attribute = {
            "rgb": "rgb_color",
            "hs": "hs_color",
            "xy": "xy_color",
            "rgbw": "rgbw_color",
            "rgbww": "rgbww_color",
            "color_temp": "color_temp",
            "color_temp_kelvin": "color_temp_kelvin",
            "white": "white",
        }
        color_mode = attributes.get("color_mode")
        preferred = mode_to_attribute.get(str(color_mode))
        if preferred and attributes.get(preferred) is not None:
            snapshot[preferred] = attributes[preferred]
        else:
            # Some integrations omit color_mode; choose one reported color value.
            for attribute in (
                "rgb_color", "hs_color", "xy_color", "rgbw_color", "rgbww_color",
                "color_temp_kelvin", "color_temp", "white",
            ):
                if attributes.get(attribute) is not None:
                    snapshot[attribute] = attributes[attribute]
                    break
        return snapshot

    async def _async_restore_theme_lights(self) -> None:
        """Restore touched lights concurrently, retaining failed restores for retry."""
        if not self._theme_lights_touched:
            return
        entities = list(self._theme_lights_touched)

        async def restore_one(entity_id: str) -> tuple[str, bool]:
            snapshot = self._theme_snapshots.get(entity_id)
            if snapshot is None:
                # Without an original snapshot there is no safe value to restore.
                return entity_id, True
            return entity_id, await self._async_restore_one_theme_light(entity_id, snapshot)

        results = await asyncio.gather(*(restore_one(entity_id) for entity_id in entities))
        for entity_id, restored in results:
            if restored:
                self._theme_lights_touched.discard(entity_id)
                self._theme_snapshots.pop(entity_id, None)

        if self._session_journal is not None:
            self._session_journal["theme_snapshots"] = deepcopy(self._theme_snapshots)
            self._session_journal["theme_restore_pending"] = sorted(self._theme_lights_touched)
            await self._async_persist_session_journal()
        if not self._theme_lights_touched:
            self._theme_snapshots.clear()

    async def _async_restore_wled_state(self, output: MatrixOutput | None = None) -> None:
        """Restore a matrix's saved segment/device brightness and power state."""
        output = output or (self.matrix_outputs[0] if self.matrix_outputs else None)
        if output is None:
            return
        snapshot = output.snapshot
        if not snapshot:
            return
        payload = {"tt": max(1, int(round(max(0.1, output.transition_seconds) * 10)))}
        payload["bs"] = snapshot.get("bs", TRANSITION_BLEND_STYLES["fade"])
        if snapshot.get("on") is not None:
            payload["on"] = snapshot["on"]
        if snapshot.get("bri") is not None:
            payload["bri"] = snapshot["bri"]
        # The preset ID is part of the pre-session WLED state. Restore it too;
        # otherwise a previously active preset can be left deselected after the
        # Image effect has replaced it. WLED uses -1 for no active preset.
        if snapshot.get("ps") is not None:
            payload["ps"] = snapshot["ps"]
        if snapshot.get("segment"):
            payload["seg"] = [snapshot["segment"]]
        await output.wled.async_post_state(payload)

    async def _async_end_session(self, *, generation: int | None = None) -> None:
        """Persist independent room/matrix actions, then use shared recovery."""
        async with self._lock:
            if self._stopping:
                return
            if getattr(self, "_end_plan_rollback_pending", False):
                # The original journal is in memory, but the last successful
                # write still contains a superseded end action. Make originals
                # durable again before allowing either recovery or playback.
                if not await self._async_persist_session_journal():
                    self._recovery_pending = True
                    self._schedule_failure_retry()
                    return
                self._end_plan_rollback_pending = False
                self._end_plan_retry_pending = False
                self._recovery_pending = not self._session_active or self.manual_override
                if self._recovery_pending:
                    # Manual override may already have attempted (and failed)
                    # recovery while rollback persistence was unavailable.
                    await self._async_restore_saved_state()
                self._schedule_update(immediate=True, reset_delay=False)
                return
            if self._stopping or (generation is not None and generation != self._session_end_generation):
                return
            if self.manual_override:
                self._end_plan_retry_pending = False
                return
            source_states = [self.hass.states.get(entity_id) for entity_id in self._source_entity_ids()]
            if any(state and state.state in ("playing", "buffering")
                   and self._is_music_activity(state) for state in source_states):
                self._end_plan_retry_pending = False
                if self._recovery_pending:
                    self._schedule_update()
                return
            if self.pause_behavior == "hold" and any(
                state and state.state == "paused" and self._is_music_activity(state)
                for state in source_states
            ):
                self._end_plan_retry_pending = False
                return
            if not self._session_active:
                self._end_plan_retry_pending = False
                return

            matrix_defaults = {
                entity_id: {"pin": self.pin, "segment": {"id": self.segment_id}}
                for entity_id in self.target_entities
            }
            for output in self.matrix_outputs:
                defaults = deepcopy(output.snapshot or {})
                defaults.setdefault("pin", output.wled.pin)
                defaults.setdefault("segment", {"id": output.segment_id})
                matrix_defaults[output.entity_id] = defaults
            original_journal = self._session_journal
            plan_generation = self._session_end_generation

            def plan_superseded() -> bool:
                if (
                    self._stopping or self.manual_override
                    or plan_generation != self._session_end_generation
                ):
                    return True
                return any(
                    (state := self.hass.states.get(entity_id)) is not None
                    and self._is_music_activity(state)
                    and (
                        state.state in {"playing", "buffering"}
                        or (state.state == "paused" and self.pause_behavior == "hold")
                    )
                    for entity_id in self._source_entity_ids()
                )

            self._session_journal = plan_session_end(
                self._session_journal,
                room_behavior=self.room_end_behavior,
                matrix_behavior=self.matrix_end_behavior,
                theme_entities=self.theme_light_entities,
                matrix_defaults=matrix_defaults,
            )
            # A failed write must not be followed by irreversible loss of the
            # original scene. The ordinary recovery retry resumes this plan.
            if not await self._async_persist_session_journal():
                self._session_journal = original_journal
                self._end_plan_retry_pending = not plan_superseded()
                if self._end_plan_retry_pending:
                    self._schedule_failure_retry()
                else:
                    self._schedule_update(immediate=True, reset_delay=False)
                return
            if plan_superseded():
                # Playback/manual control can change while the store write is
                # pending. Roll back the durable plan before sending commands.
                self._session_journal = original_journal or new_session_journal(
                    session_active=True,
                    matrix_snapshots={
                        output.entity_id: output.snapshot
                        for output in self.matrix_outputs if output.snapshot is not None
                    },
                    theme_snapshots=self._theme_snapshots,
                    theme_restore_pending=self._theme_lights_touched,
                )
                self._end_plan_retry_pending = False
                self._end_plan_rollback_pending = True
                if not await self._async_persist_session_journal():
                    self._recovery_pending = True
                    self._schedule_failure_retry()
                    return
                self._end_plan_rollback_pending = False
                self._schedule_update(immediate=True, reset_delay=False)
                return
            self._end_plan_retry_pending = False
            self._cancel_artwork_retry()
            self._cancel_animation_upgrade(release_track=True)
            self._online_artwork_lookup.release_current_track()
            self._session_active = False
            self._session_had_artwork = False
            self._session_artwork_sources.clear()
            self._session_artwork_context.clear()
            self._cancel_session_end()
            self._recovery_pending = True
            restored = await self._async_restore_saved_state(
                preserve_visible_art=self.matrix_end_behavior == "keep"
            )
            if not restored:
                self._set_status("Playback ended — state restoration pending")
                return

            self._last_key = None
            self._reset_matrix_session_state(
                preserve_visible_art=self.matrix_end_behavior == "keep"
            )
            journal = self._session_journal or {}
            pending = bool(journal.get("deferred_matrix_restores") or journal.get("deferred_theme_restores"))
            parts = []
            if self.theme_light_entities:
                parts.append({
                    "restore_color": "room color restored",
                    "restore_color_brightness": "room color and brightness restored",
                    "keep": "room lighting kept",
                    "turn_off": "room lights off",
                }[self.room_end_behavior])
            if self.matrix_enabled:
                parts.append("matrix off" if not self.matrix_output_enabled else {
                    "restore_previous": "matrix state restored",
                    "keep": "matrix artwork kept",
                    "turn_off": "matrix off",
                }[self.matrix_end_behavior])
            if pending:
                # Avoid claiming an unavailable device has already completed its
                # action. Each saved action retains its original brightness policy.
                status = "Playback ended — available outputs handled; offline actions pending"
            else:
                status = "Playback ended — " + ("; ".join(parts) or "artwork retained in Home Assistant")
            self._set_status(status)
            _LOGGER.info("Ended music session (room: %s, matrix: %s)",
                         self.room_end_behavior, self.matrix_end_behavior)

    async def _async_detect_resolution(self, output: MatrixOutput | None = None) -> None:
        """Auto-detect dimensions independently without serial network timeouts."""
        if output is None:
            await asyncio.gather(
                *(self._async_detect_resolution(item) for item in self.matrix_outputs),
                return_exceptions=True,
            )
            return

        item = output
        if (
            not self.matrix_enabled or not item.auto_detect_size or item.resolution_detected
            or self._entity_in_recovery_cooldown(item.entity_id)
        ):
            return
        entity_state = self.hass.states.get(item.entity_id)
        if entity_state is None or entity_state.state in ("unknown", "unavailable"):
            return
        try:
            info = await item.wled.async_get_info()
            matrix = (info.get("leds") or {}).get("matrix") or {}
            width = int(matrix.get("w", 0))
            height = int(matrix.get("h", 0))
            if 1 <= width <= 128 and 1 <= height <= 128:
                if (width, height) != (item.width, item.height):
                    _LOGGER.info("Detected WLED matrix dimensions for %s: %sx%s", item.entity_id, width, height)
                item.width, item.height = width, height
                item.resolution_detected = True
                item.resolution_source = "wled_auto_detected"
                if self.matrix_outputs and item is self.matrix_outputs[0]:
                    self.width, self.height = width, height
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, TypeError, RuntimeError) as err:
            _LOGGER.debug("Could not auto-detect size for %s; using manual dimensions: %s", item.entity_id, err)

    def _filename_for(self, data: bytes, output: MatrixOutput | None = None) -> str:
        """Return a stable content-addressed filename for one matrix's prepared GIF."""
        digest = hashlib.sha256(data).hexdigest()[:12]
        prefix = output.filename_prefix if output else self.filename_prefix
        return f"{prefix}_{digest}.gif"

    def _choose_transition_style(self, output: MatrixOutput) -> str:
        """Resolve shuffle while avoiding an immediate repeat on each matrix."""
        chosen = choose_transition_style(output.transition_style, output.last_transition_style)
        if output.transition_style == "shuffle":
            output.last_transition_style = chosen
        return chosen

