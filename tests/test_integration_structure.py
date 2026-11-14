"""Lightweight structural checks for the Home Assistant entry lifecycle."""
from __future__ import annotations

import ast
from pathlib import Path

COMPONENT_DIR = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "wled_album_art"
)


def test_async_setup_invokes_a_defined_manager_start_method() -> None:
    manager_tree = ast.parse((COMPONENT_DIR / "manager.py").read_text())
    manager_class = next(
        node for node in manager_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "AlbumArtManager"
    )
    method_names = {
        node.name for node in manager_class.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "async_start" in method_names
    assert "async_stop" in method_names

    setup_tree = ast.parse((COMPONENT_DIR / "__init__.py").read_text())
    setup_entry = next(
        node for node in setup_tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "async_setup_entry"
    )
    calls_start = any(
        isinstance(node, ast.Await)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Attribute)
        and node.value.func.attr == "async_start"
        for node in ast.walk(setup_entry)
    )
    assert calls_start


def test_release_uses_one_matrix_per_entry_and_supports_theme_only_mode() -> None:
    import json

    component = COMPONENT_DIR
    manifest = json.loads((component / "manifest.json").read_text())
    strings = json.loads((component / "strings.json").read_text())
    assert manifest["version"] == "0.16.2"
    assert "one wled matrix" in strings["config"]["step"]["user"]["description"].lower()
    assert "leave the matrix empty" in strings["config"]["step"]["user"]["description"].lower()
    assert "next screen" in strings["options"]["step"]["init"]["description"].lower()
    assert "matrix" in strings["options"]["step"]["tuning"]["description"].lower()
    config_flow_source = (COMPONENT_DIR / "config_flow.py").read_text()
    assert "CONF_TARGET_ENTITIES" in config_flow_source  # legacy migration compatibility
    assert 'domain="light", integration="wled"' in config_flow_source
    manager_source = (COMPONENT_DIR / "manager.py").read_text()
    assert "from .matrix_control import MatrixOutput" in manager_source
    assert "class MatrixOutput" in (component / "matrix_control.py").read_text()
    assert "_async_update_matrix_output" in manager_source
    assert "matrix_entities" in manager_source
    assert "_async_snapshot_matrix_output" in manager_source
    assert "preserve_filenames" in (COMPONENT_DIR / "wled_client.py").read_text()
    assert "asyncio.gather" in manager_source


def test_matrix_snapshots_run_concurrently_and_diagnostics_are_per_output() -> None:
    manager_source = (COMPONENT_DIR / "manager.py").read_text()
    assert "*(self._async_snapshot_matrix_output(output) for output in outputs_to_snapshot)" in manager_source
    assert '"last_result": output.last_result' in manager_source
    assert '"snapshot_saved": output.snapshot is not None' in manager_source
    assert "_safe_error_text" in manager_source
    assert 'payload["ps"] = snapshot["ps"]' in manager_source
    assert (COMPONENT_DIR / "error_utils.py").exists()


def test_session_state_is_persisted_for_crash_recovery() -> None:
    manager_source = (COMPONENT_DIR / "manager.py").read_text()
    assert 'Store(hass, 1, f"{DOMAIN}_{entry.entry_id}_session")' in manager_source
    assert "_async_persist_session_journal" in manager_source
    assert "_async_restore_saved_state" in manager_source
    assert "theme_restore_pending" in manager_source
    lifecycle_source = (COMPONENT_DIR / "__init__.py").read_text()
    assert "async_migrate_entry" in lifecycle_source


def test_status_sensor_is_event_driven_not_polled() -> None:
    sensor_source = (COMPONENT_DIR / "sensor.py").read_text()
    assert "_attr_should_poll = False" in sensor_source
    assert "async_add_status_listener" in sensor_source
    assert "SCAN_INTERVAL" not in sensor_source


def test_failed_manager_start_is_cleaned_up_before_setup_error_propagates() -> None:
    source = (COMPONENT_DIR / "__init__.py").read_text()
    assert "await manager.async_start()" in source
    assert "await manager.async_stop()" in source
    assert "async_unload_platforms(entry, PLATFORMS)" in source
    assert "preserve the original setup exception" in source


def test_options_keep_matrix_pin_but_remove_confusing_text_preset_guard() -> None:
    config_flow_source = (COMPONENT_DIR / "config_flow.py").read_text()
    manager_source = (COMPONENT_DIR / "manager.py").read_text()
    strings = (COMPONENT_DIR / "strings.json").read_text()
    const_source = (COMPONENT_DIR / "const.py").read_text()
    assert 'CONF_PIN: current.get(CONF_PIN, self.config_entry.data.get(CONF_PIN, ""))' in config_flow_source
    assert 'vol.Optional(CONF_PIN, default=current.get(CONF_PIN, ""))' in config_flow_source
    assert 'options.get(CONF_PIN, entry.data.get(CONF_PIN, ""))' in manager_source
    assert "preset_entity" not in config_flow_source
    assert "CONF_PRESET_ENTITY" not in manager_source
    assert "_preset_protects_matrix" not in manager_source
    assert "preset_entity" not in strings
    assert "CONF_PRESET_ENTITY" not in const_source


def test_saved_matrix_can_be_restored_after_target_is_reassigned() -> None:
    manager_source = (COMPONENT_DIR / "manager.py").read_text()
    assert "def _output_for_saved_target" in manager_source
    assert "self._output_for_saved_target(entity_id, snapshot)" in manager_source
    assert "self._recovery_entity_ids" in manager_source
    assert '"pin": self.pin' in manager_source


def test_store_read_failure_pauses_updates_until_recovery_retry() -> None:
    manager_source = (COMPONENT_DIR / "manager.py").read_text()
    assert "self._recovery_pending = True" in manager_source
    assert "Saved-state journal could not be read; updates paused while retrying" in manager_source


def test_spectrum_balancing_preference_is_preserved_during_migration() -> None:
    lifecycle_source = (COMPONENT_DIR / "__init__.py").read_text()
    assert "CONF_BALANCE_THEME_SPECTRUM" not in lifecycle_source
    assert "options[CONF_BALANCE_THEME_SPECTRUM] = False" not in lifecycle_source
    const_source = (COMPONENT_DIR / "const.py").read_text()
    assert "DEFAULT_BALANCE_THEME_SPECTRUM = False" in const_source


def test_deferred_restoration_is_retried_without_expiring_saved_snapshots() -> None:
    manager_source = (COMPONENT_DIR / "manager.py").read_text()
    assert "_schedule_recovery_retry" in manager_source
    assert 'journal.get("deferred_matrix_restores")' in manager_source
    assert 'journal.get("deferred_theme_restores")' in manager_source
    assert "_recovery_window_expired" not in manager_source
    assert "recovery_timeout_seconds" not in manager_source
    assert "retaining snapshots on all failures" in manager_source


def test_powered_on_devices_get_a_configurable_warmup_and_are_refreshed() -> None:
    manager_source = (COMPONENT_DIR / "manager.py").read_text()
    const_source = (COMPONENT_DIR / "const.py").read_text()
    config_source = (COMPONENT_DIR / "config_flow.py").read_text()
    assert "DEFAULT_DEVICE_WARMUP_DELAY = 12" in const_source
    assert "CONF_DEVICE_WARMUP_DELAY" in config_source
    assert 'old_state.state == "off"' in manager_source
    assert "self._theme_last_key.pop(entity_id, None)" in manager_source
    assert "self._device_recovery_delay_seconds" in manager_source


def test_theme_light_and_matrix_restoration_are_parallel_and_bounded() -> None:
    manager_source = (COMPONENT_DIR / "manager.py").read_text()
    assert "self._async_attempt_matrix_restore(entity_id, snapshot)" in manager_source
    assert "theme_results = await asyncio.gather" in manager_source
    assert "timeout=15" in manager_source
    assert '"theme_light_results": deepcopy(self._theme_light_results)' in manager_source


def test_visible_name_is_music_artwork_lighting_without_changing_domain() -> None:
    import json

    manifest = json.loads((COMPONENT_DIR / "manifest.json").read_text())
    assert manifest["name"] == "Music Artwork Lighting"
    assert manifest["domain"] == "wled_album_art"
    hacs = json.loads((COMPONENT_DIR.parents[1] / "hacs.json").read_text())
    assert hacs["name"] == "Music Artwork Lighting"


def test_offline_matrix_does_not_get_overwritten_before_its_saved_state_is_restored() -> None:
    manager_source = (COMPONENT_DIR / "manager.py").read_text()
    assert "if output.entity_id not in deferred_matrix" in manager_source
    assert 'pending_behavior = snapshot.get("_pending_end_behavior")' in manager_source
    journal_source = (COMPONENT_DIR / "session_journal.py").read_text()
    assert "plan_session_end(" in manager_source
    assert '"black" if matrix_behavior == "black" else "turn_off_matrix"' in journal_source
    assert 'snapshot["_pending_end_behavior"] = (' in journal_source
    assert "_deferred_restore_retry_after[entity_id] = time.monotonic() + 30" in manager_source
    assert '"deferred_restore_retrying_entities"' in manager_source


def test_wled_http_calls_have_bounded_timeouts_for_unresponsive_devices() -> None:
    source = (COMPONENT_DIR / "wled_client.py").read_text()
    assert 'timeout=aiohttp.ClientTimeout(total=6)' in source
    assert 'timeout=aiohttp.ClientTimeout(total=12)' in source  # image upload
    assert 'timeout=aiohttp.ClientTimeout(total=5)' in source  # best-effort filesystem cleanup


def test_device_warmup_timer_binds_entity_id_into_callback_correctly() -> None:
    import ast

    source = (COMPONENT_DIR / "manager.py").read_text()
    tree = ast.parse(source)
    assert "from functools import partial" in source
    manager_class = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "AlbumArtManager"
    )
    method = next(
        node for node in manager_class.body
        if isinstance(node, ast.FunctionDef) and node.name == "_delay_device_recovery"
    )
    timer_calls = [
        node for node in ast.walk(method)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "async_call_later"
    ]
    assert len(timer_calls) == 1
    assert len(timer_calls[0].args) == 3  # HA timer accepts (hass, delay, callback)
    callback_arg = timer_calls[0].args[2]
    assert isinstance(callback_arg, ast.Call)
    assert isinstance(callback_arg.func, ast.Name) and callback_arg.func.id == "partial"
    assert isinstance(callback_arg.args[0], ast.Attribute)
    assert callback_arg.args[0].attr == "_device_recovery_delay_elapsed"


def test_warmup_help_text_applies_to_all_configured_outputs() -> None:
    import json

    strings = json.loads((COMPONENT_DIR / "strings.json").read_text())
    help_text = strings["options"]["step"]["init"]["data_description"]["device_warmup_delay_seconds"]
    assert "any light or matrix" in help_text.lower()
    assert "led curtain" not in help_text.lower()
    assert "wi-fi" not in help_text.lower()



def test_current_source_sensor_and_diagnostics_expose_priority_without_artwork_urls() -> None:
    source = (COMPONENT_DIR / "sensor.py").read_text()
    manager_source = (COMPONENT_DIR / "manager.py").read_text()
    manifest = __import__("json").loads((COMPONENT_DIR / "manifest.json").read_text())
    assert manifest["version"] == "0.16.2"
    assert "MusicArtworkCurrentSourceSensor" in source
    assert 'f"{entry.entry_id}_current_source"' in source
    assert "source_diagnostics" in source
    assert "def source_diagnostics(self) -> dict" in manager_source
    for key in ("active_source_name", "active_source_priority", "source_selection_reason", "source_candidates", "has_artwork"):
        assert f'"{key}"' in manager_source
    # Diagnostics report only whether artwork exists; the URL itself is not serialized.
    method = manager_source.split("def source_diagnostics(self) -> dict:", 1)[1].split("async def async_set_manual_override", 1)[0]
    assert '"has_artwork": bool(image_url)' in method
    assert '"entity_picture": image_url' not in method
    assert '"media_image_url": image_url' not in method



def test_strings_and_english_translation_stay_in_sync() -> None:
    import json

    component = COMPONENT_DIR
    strings = json.loads((component / "strings.json").read_text())
    translation = json.loads((component / "translations" / "en.json").read_text())
    assert strings == translation
    help_text = translation["options"]["step"]["init"]["data_description"]["device_warmup_delay_seconds"]
    assert "any light or matrix" in help_text.lower()


def test_device_health_sensor_is_event_driven_and_reports_each_output() -> None:
    sensor_source = (COMPONENT_DIR / "sensor.py").read_text()
    assert "class MusicArtworkDeviceHealthSensor" in sensor_source
    assert '"Unavailable"' in sensor_source
    assert '"Restoration pending"' in sensor_source
    assert '"last_error": output.get("last_error")' in sensor_source
    assert "async_add_status_listener" in sensor_source
    assert "_attr_should_poll = False" in sensor_source


def test_source_priority_help_explains_order_and_diagnostic_preview() -> None:
    import json

    strings = json.loads((COMPONENT_DIR / "strings.json").read_text())
    description = strings["options"]["step"]["init"]["data_description"]["source_entities"]
    assert "first eligible" in description
    assert "Current source" in description
    assert "Artwork is resolved for that source" in description
    translation = json.loads((COMPONENT_DIR / "translations" / "en.json").read_text())
    assert strings == translation


def test_device_health_includes_configured_theme_lights_before_first_update() -> None:
    sensor_source = (COMPONENT_DIR / "sensor.py").read_text()
    assert "for entity_id in self._manager.theme_light_entities" in sensor_source
    assert 'light_results.get(entity_id, {})' in sensor_source


def test_options_panel_explains_post_setup_tuning() -> None:
    import json

    strings = json.loads((COMPONENT_DIR / "strings.json").read_text())
    options = strings["options"]["step"]["init"]
    description = options["description"].lower()
    assert "next screen" in description
    field_help = strings["options"]["step"]["tuning"]["data_description"]
    assert "transition_style" in field_help
    assert "theme_color_mode" in field_help
    assert "room_end_behavior" in field_help
    assert "matrix_end_behavior" in field_help
    assert "device_warmup_delay_seconds" in options["data_description"]


def test_dashboard_tuning_controls_are_exposed_and_live_applied() -> None:
    import json

    component = COMPONENT_DIR
    setup_source = (component / "__init__.py").read_text()
    platform_assignment = next(
        node for node in ast.parse(setup_source).body
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "PLATFORMS"
    )
    assert set(ast.literal_eval(platform_assignment.value)) == {
        "button", "image", "light", "sensor", "switch", "select", "number",
    }
    assert "async_update_listener" in setup_source
    assert "async_apply_live_options" in setup_source

    manager_source = (component / "manager.py").read_text()
    assert "LIVE_TUNABLE_OPTIONS" in manager_source
    assert "self._last_theme_palette" in manager_source
    assert "Force a recolor from the cached palette" in manager_source

    select_source = (component / "select.py").read_text()
    number_source = (component / "number.py").read_text()
    assert "MusicArtworkThemeColorModeSelect" in select_source
    assert "MusicArtworkTransitionStyleSelect" in select_source
    assert "MusicArtworkMatrixTransitionDurationNumber" in number_source
    assert "MusicArtworkThemeLightTransitionDurationNumber" in number_source
    assert "async_set_live_option" in select_source and "async_set_live_option" in number_source

    strings = json.loads((component / "strings.json").read_text())
    translations = json.loads((component / "translations" / "en.json").read_text())
    assert strings["entity"] == translations["entity"]
    assert strings["entity"]["select"]["theme_color_mode"]["state"]["palette"] == "Artwork palette"
    assert "matrix_transition_duration" in strings["entity"]["number"]

    flow_tree = ast.parse((component / "config_flow.py").read_text())
    flow_values = {
        node.targets[0].id: ast.literal_eval(node.value)
        for node in flow_tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id in {"_THEME_COLOR_MODE_OPTIONS", "_TRANSITION_OPTIONS"}
    }
    select_tree = ast.parse(select_source)
    select_values = {
        node.targets[0].id: ast.literal_eval(node.value)
        for node in select_tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id in {"_THEME_COLOR_MODES", "_TRANSITION_STYLES"}
    }
    assert select_values["_THEME_COLOR_MODES"] == [item["value"] for item in flow_values["_THEME_COLOR_MODE_OPTIONS"]]
    assert select_values["_TRANSITION_STYLES"] == [item["value"] for item in flow_values["_TRANSITION_OPTIONS"]]


def test_instant_transition_can_be_selected_in_configure() -> None:
    source = (COMPONENT_DIR / "config_flow.py").read_text()
    assert '{"value": "instant", "label": "Instant cut"}' in source


def test_dashboard_behavior_toggles_and_live_selects_are_available() -> None:
    import json

    component = COMPONENT_DIR
    platforms = (component / "__init__.py").read_text()
    assert '"switch"' in platforms and '"select"' in platforms and '"number"' in platforms

    switch_source = (component / "switch.py").read_text()
    assert "async_add_entity_state_listener" in switch_source
    for option in (
        "CONF_MATRIX_OUTPUT_ENABLED", "CONF_FADE_TO_BLACK", "CONF_ONLINE_ARTWORK_LOOKUP",
    ):
        assert option in switch_source
    select_source = (component / "select.py").read_text()
    assert "async_add_entity_state_listener" in select_source
    for option in ("CONF_AUTO_POWER_MODE", "CONF_THEME_FADE_MODE", "CONF_THEME_COLOR_ADJUSTMENTS"):
        assert option in select_source
    assert "MusicArtworkImageFitSelect" in select_source
    assert "MusicArtworkRoomEndBehaviorSelect" in select_source
    assert "MusicArtworkMatrixEndBehaviorSelect" in select_source
    number_source = (component / "number.py").read_text()
    assert "async_add_entity_state_listener" in number_source
    assert "MusicArtworkBlackPauseNumber" in number_source
    assert "MusicArtworkSourceStabilizationNumber" in number_source
    assert "MusicArtworkPlaybackEndGraceNumber" in number_source
    assert "MusicArtworkDeviceWarmupNumber" in number_source

    manager_source = (component / "manager.py").read_text()
    for option in (
        "CONF_MATRIX_TURN_ON", "CONF_FADE_TO_BLACK", "CONF_FADE_THEME_WITH_MATRIX", "CONF_THEME_TURN_ON",
        "CONF_PREVENT_DARK_COLORS", "CONF_BALANCE_THEME_SPECTRUM",
        "CONF_RESTORE_THEME_BRIGHTNESS", "CONF_IMAGE_FIT",
        "CONF_END_BEHAVIOR", "CONF_BLACK_PAUSE",
    ):
        assert option in manager_source
    assert "self.hass.async_create_task(self.async_update(force=True))" in manager_source
    assert "_async_fade_theme_lights_to_black" in manager_source
    assert "self.fade_theme_lights_with_matrix" in manager_source
    assert '"value": "black"' not in (component / "config_flow.py").read_text()
    assert '"black": "Restore room lights, black matrix"' not in (component / "translations/en.json").read_text()

    strings = json.loads((component / "strings.json").read_text())
    translations = json.loads((component / "translations" / "en.json").read_text())
    assert strings["entity"] == translations["entity"]
    assert set(strings["entity"]["switch"]) == {
        "matrix_output_enabled", "fade_to_black", "online_artwork_lookup", "animated_artwork",
    }
    assert set(strings["entity"]["select"]) >= {
        "theme_color_mode", "transition_style", "image_fit", "room_end_behavior", "matrix_end_behavior",
    }
    assert "black_pause_duration" in strings["entity"]["number"]


def test_timing_controls_apply_live_and_room_end_behavior_is_explicit() -> None:
    import json

    component = COMPONENT_DIR
    number_source = (component / "number.py").read_text()
    manager_source = (component / "manager.py").read_text()
    config_flow_source = (component / "config_flow.py").read_text()
    for key in (
        "CONF_SOURCE_STABILIZATION", "CONF_END_GRACE", "CONF_DEVICE_WARMUP_DELAY",
    ):
        assert key in number_source
        assert key in manager_source
    assert "self._cancel_session_end()" in manager_source
    assert 'self._schedule_session_end("paused")' in manager_source
    assert 'self._schedule_session_end("stopped")' in manager_source
    assert '"keep_lighting"' in manager_source
    assert '"turn_off_matrix"' in manager_source
    assert '"turn_off_all"' in manager_source
    strings = json.loads((component / "strings.json").read_text())
    room_end = strings["entity"]["select"]["room_end_behavior"]
    matrix_end = strings["entity"]["select"]["matrix_end_behavior"]
    assert room_end["name"] == "Room lights when playback ends"
    assert matrix_end["name"] == "Matrix when playback ends"
    assert {"restore_color", "restore_color_brightness", "keep", "turn_off"} == set(room_end["state"])
    assert {"restore_previous", "keep", "turn_off"} == set(matrix_end["state"])
    assert set(strings["entity"]["number"]) >= {
        "source_stabilization", "playback_end_grace", "device_warmup_delay",
    }
    assert "Turn room lights off" in config_flow_source
    assert "Turn matrix off" in config_flow_source


def test_no_blunt_multi_setting_lighting_mood_presets() -> None:
    import json

    component = COMPONENT_DIR
    select_source = (component / "select.py").read_text()
    assert "MusicArtworkLightingProfileSelect" not in select_source
    assert "_PROFILE_OPTIONS" not in select_source
    strings = json.loads((component / "strings.json").read_text())
    assert "lighting_profile" not in strings["entity"]["select"]
    # Keep the individual color and transition controls instead of presets that
    # silently overwrite multiple user-selected options.
    assert "theme_color_mode" in strings["entity"]["select"]
    assert "transition_style" in strings["entity"]["select"]


def test_matrix_black_playback_end_choice_is_retired_and_migrates_to_off() -> None:
    config_source = (COMPONENT_DIR / "config_flow.py").read_text()
    manager_source = (COMPONENT_DIR / "manager.py").read_text()
    assert '"value": "black"' not in config_source
    const_source = (COMPONENT_DIR / "const.py").read_text()
    assert "normalize_end_behavior" in config_source
    assert "normalize_end_behavior" in manager_source
    assert 'legacy in {"turn_off_matrix", "black"}' in const_source
    assert 'matrix = "turn_off"' in const_source


def test_decorative_lights_can_follow_matrix_fade_to_black() -> None:
    import json

    component = COMPONENT_DIR
    select_source = (component / "select.py").read_text()
    manager_source = (component / "manager.py").read_text()
    strings = json.loads((component / "strings.json").read_text())
    assert "CONF_THEME_FADE_MODE" in select_source
    assert "_async_fade_theme_lights_to_black" in manager_source
    assert "self.fade_to_black\n                            and self.fade_theme_lights_with_matrix" in manager_source
    assert set(strings["entity"]["select"]["theme_fade_mode"]["state"]) == {
        "matrix_black", "colors", "instant", "device_default",
    }
