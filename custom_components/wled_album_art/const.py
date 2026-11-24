"""Constants for Music Artwork Lighting."""

from collections.abc import Mapping

DOMAIN = "wled_album_art"
# Keep in sync with manifest.json; tests enforce this.
INTEGRATION_VERSION = "0.16.4"
# MusicBrainz asks clients to identify themselves with a name, version, and contact URL.
USER_AGENT = (
    f"MusicArtworkLighting/{INTEGRATION_VERSION} "
    "( https://github.com/vibribbonee/wled-album-art )"
)

# Configuration keys. CONF_SOURCE_ENTITY remains for existing config entries.
CONF_SOURCE_ENTITY = "source_entity"
CONF_SOURCE_ENTITIES = "source_entities"
CONF_SOURCE_STABILIZATION = "source_stabilization"
CONF_DEVICE_WARMUP_DELAY = "device_warmup_delay_seconds"
CONF_TARGET_ENTITY = "target_entity"  # Legacy single-target setting
CONF_TARGET_ENTITIES = "target_entities"
CONF_MATRIX_OUTPUT_ENABLED = "matrix_output_enabled"
CONF_MATRIX_TURN_ON = "matrix_turn_on"
CONF_AUTO_POWER_MODE = "auto_power_mode"
CONF_PIN = "wled_pin"
CONF_WIDTH = "width"
CONF_HEIGHT = "height"
CONF_AUTO_DETECT_SIZE = "auto_detect_size"
CONF_IMAGE_FIT = "image_fit"
CONF_IMAGE_CROP_POSITION = "image_crop_position"
CONF_IMAGE_ZOOM = "image_zoom"
CONF_IMAGE_BLUR_STRENGTH = "image_blur_strength"
CONF_IMAGE_BACKGROUND_BRIGHTNESS = "image_background_brightness"
CONF_ANIMATED_ARTWORK = "animated_artwork"
CONF_FILENAME = "filename"
CONF_SEGMENT_ID = "segment_id"
CONF_TRANSITION_STYLE = "transition_style"
CONF_TRANSITION_SECONDS = "transition_seconds"
CONF_BLACK_PAUSE = "black_pause"
CONF_FADE_TO_BLACK = "fade_to_black"
CONF_FADE_THEME_WITH_MATRIX = "fade_theme_lights_with_matrix"
CONF_THEME_FADE_MODE = "theme_fade_mode"
CONF_THEME_LIGHT_ENTITIES = "theme_light_entities"
CONF_THEME_COLOR_MODE = "theme_color_mode"
CONF_THEME_LIGHT_TRANSITION = "theme_light_transition"
CONF_THEME_TURN_ON = "theme_lights_turn_on"
CONF_PREVENT_DARK_COLORS = "prevent_dark_theme_colors"
CONF_BALANCE_THEME_SPECTRUM = "balance_theme_spectrum"
CONF_THEME_COLOR_ADJUSTMENTS = "theme_color_adjustments"
CONF_RESTORE_THEME_BRIGHTNESS = "restore_theme_brightness"
CONF_NO_ART_BEHAVIOR = "no_art_behavior"
CONF_NO_ART_DURING_SESSION = "no_art_during_session_behavior"
CONF_NO_ART_COLOR = "no_art_color"
CONF_NO_ART_LAST_COLOR = "no_art_last_color"
CONF_NO_ART_BRIGHTNESS = "no_art_brightness"
CONF_ONLINE_ARTWORK_LOOKUP = "online_artwork_lookup"
CONF_ARTWORK_PROVIDER_PRIORITY = "artwork_provider_priority"
CONF_ARTWORK_PROVIDERS = "artwork_providers"
CONF_LASTFM_API_KEY = "lastfm_api_key"
CONF_THEAUDIODB_API_KEY = "theaudiodb_api_key"
CONF_IGNORED_INPUTS = "ignored_inputs"
CONF_END_BEHAVIOR = "end_behavior"
CONF_ROOM_END_BEHAVIOR = "room_end_behavior"
CONF_MATRIX_END_BEHAVIOR = "matrix_end_behavior"
CONF_END_GRACE = "end_grace_seconds"
CONF_PAUSE_BEHAVIOR = "pause_behavior"

DEFAULT_MATRIX_TURN_ON = True
DEFAULT_AUTO_POWER_MODE = "all"
DEFAULT_MATRIX_OUTPUT_ENABLED = True
DEFAULT_WIDTH = 32
DEFAULT_HEIGHT = 32
DEFAULT_FILENAME = "album.gif"
DEFAULT_SEGMENT_ID = 0
DEFAULT_AUTO_DETECT_SIZE = True
DEFAULT_SOURCE_STABILIZATION = 1.5
DEFAULT_DEVICE_WARMUP_DELAY = 12
DEFAULT_IMAGE_FIT = "crop"
DEFAULT_IMAGE_CROP_POSITION = "center"
DEFAULT_IMAGE_ZOOM = 100
DEFAULT_IMAGE_BLUR_STRENGTH = 16
DEFAULT_IMAGE_BACKGROUND_BRIGHTNESS = 62
DEFAULT_ANIMATED_ARTWORK = True
DEFAULT_TRANSITION_STYLE = "fade"
DEFAULT_TRANSITION_SECONDS = 0.7
DEFAULT_BLACK_PAUSE = 0.08
DEFAULT_FADE_TO_BLACK = False
DEFAULT_FADE_THEME_WITH_MATRIX = True
DEFAULT_THEME_FADE_MODE = "matrix_black"
DEFAULT_THEME_COLOR_MODE = "palette"
DEFAULT_THEME_LIGHT_TRANSITION = 0.8
DEFAULT_THEME_TURN_ON = True
DEFAULT_PREVENT_DARK_COLORS = True
DEFAULT_BALANCE_THEME_SPECTRUM = False
DEFAULT_THEME_COLOR_ADJUSTMENTS = "avoid_dark"
DEFAULT_RESTORE_THEME_BRIGHTNESS = False
DEFAULT_NO_ART_BEHAVIOR = "wait"
DEFAULT_NO_ART_DURING_SESSION = "keep_previous"
DEFAULT_NO_ART_COLOR = [64, 160, 255]
DEFAULT_NO_ART_BRIGHTNESS = 0
DEFAULT_ONLINE_ARTWORK_LOOKUP = True
DEFAULT_ARTWORK_PROVIDER_PRIORITY = "musicbrainz_first"
ARTWORK_PROVIDER_PRIORITIES = (
    "musicbrainz_first", "lastfm_first", "musicbrainz_only", "lastfm_only"
)
ARTWORK_PROVIDERS = ("musicbrainz", "lastfm", "deezer", "theaudiodb")
DEFAULT_ARTWORK_PROVIDERS = ("musicbrainz", "deezer", "lastfm", "theaudiodb")


def artwork_provider_order(options: Mapping[str, object]) -> tuple[str, ...]:
    """Read selected services in order, preserving existing provider choices."""
    if CONF_ARTWORK_PROVIDERS in options:
        configured = options[CONF_ARTWORK_PROVIDERS]
        if not isinstance(configured, (list, tuple)):
            return ()
        providers = (str(value).strip().casefold() for value in configured)
        return tuple(dict.fromkeys(value for value in providers if value in ARTWORK_PROVIDERS))
    legacy_orders = {
        "musicbrainz_first": ("musicbrainz", "lastfm"),
        "lastfm_first": ("lastfm", "musicbrainz"),
        "musicbrainz_only": ("musicbrainz",),
        "lastfm_only": ("lastfm",),
    }
    if CONF_ARTWORK_PROVIDER_PRIORITY in options:
        return legacy_orders.get(
            str(options[CONF_ARTWORK_PROVIDER_PRIORITY]),
            legacy_orders[DEFAULT_ARTWORK_PROVIDER_PRIORITY],
        )
    return DEFAULT_ARTWORK_PROVIDERS


DEFAULT_END_BEHAVIOR = "turn_off_matrix"
DEFAULT_END_GRACE = 30
DEFAULT_PAUSE_BEHAVIOR = "end_after_grace"

ROOM_END_BEHAVIORS = ("restore_color", "restore_color_brightness", "keep", "turn_off")
MATRIX_END_BEHAVIORS = ("restore_previous", "keep", "turn_off")


def normalize_end_behavior(
    options: Mapping[str, object], matrix_enabled: bool = True
) -> tuple[str, str]:
    """Read independent end policies, preserving saved combined choices."""
    legacy = options.get(
        CONF_END_BEHAVIOR,
        "restore_previous" if CONF_RESTORE_THEME_BRIGHTNESS in options
        else DEFAULT_END_BEHAVIOR,
    )
    room = (
        "restore_color_brightness"
        if options.get(CONF_RESTORE_THEME_BRIGHTNESS, DEFAULT_RESTORE_THEME_BRIGHTNESS)
        else "restore_color"
    )
    matrix = "restore_previous"
    if legacy == "restore_previous_brightness":
        room = "restore_color_brightness"
    elif legacy == "restore_previous_color":
        room = "restore_color"
    elif legacy == "keep_lighting":
        room, matrix = "keep", "keep"
    elif legacy == "keep_last":
        matrix = "keep"
    elif legacy in {"turn_off_matrix", "black"}:
        matrix = "turn_off"
    elif legacy == "turn_off_all":
        room, matrix = "turn_off", "turn_off"
    configured_room = options.get(CONF_ROOM_END_BEHAVIOR)
    configured_matrix = options.get(CONF_MATRIX_END_BEHAVIOR)
    if configured_room in ROOM_END_BEHAVIORS:
        room = str(configured_room)
    if configured_matrix in MATRIX_END_BEHAVIORS:
        matrix = str(configured_matrix)
    return room, matrix if matrix_enabled else "restore_previous"

IMAGE_EFFECT_NAME = "Image"
SOLID_EFFECT_NAME = "Solid"
MAX_SOURCE_IMAGE_BYTES = 15 * 1024 * 1024
MAX_CACHED_IMAGE_BYTES = 25 * 1024 * 1024
IMAGE_CACHE_TTL_SECONDS = 300
MAX_SOURCE_IMAGE_PIXELS = 40_000_000
MAX_ANIMATED_ARTWORK_FRAMES = 60

AUTO_POWER_MODES = ("all", "matrix", "theme", "none")
THEME_FADE_MODES = ("matrix_black", "colors", "instant", "device_default")
THEME_COLOR_ADJUSTMENT_MODES = ("none", "avoid_dark", "balance", "both")
NO_ART_BEHAVIORS = ("fallback_color", "turn_off", "wait")
NO_ART_DURING_SESSION_BEHAVIORS = ("keep_previous", "fallback_color", "turn_off")
END_BEHAVIORS = (
    "restore_previous_color", "restore_previous_brightness", "keep_lighting",
    "keep_last", "turn_off_matrix", "turn_off_all",
)
IMAGE_FIT_MODES = (
    "crop", "contain", "blurred_background_soft",
    "blurred_background", "blurred_background_strong",
    "blurred_background_custom", "solid_background", "mirrored_background",
)
IMAGE_CROP_POSITIONS = (
    "top_left", "top", "top_right", "left", "center", "right",
    "bottom_left", "bottom", "bottom_right",
)

# WLED 16 JSON API transition blend styles (the "bs" state field).
# The "shuffle" choice is resolved by the manager to one of these before use.
TRANSITION_BLEND_STYLES = {
    "fade": 0,
    "fairy_dust": 1,
    "swipe_right": 2,
    "swipe_left": 3,
    "outside_in": 4,
    "inside_out": 5,
    "swipe_up": 6,
    "swipe_down": 7,
    "open_horizontal": 8,
    "open_vertical": 9,
    "swipe_top_left": 10,
    "swipe_top_right": 11,
    "swipe_bottom_right": 12,
    "swipe_bottom_left": 13,
    "circular_out": 14,
    "circular_in": 15,
    "push_right": 16,
    "push_left": 17,
    "push_up": 18,
    "push_down": 19,
}
