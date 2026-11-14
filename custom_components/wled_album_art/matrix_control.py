"""State for matrix uploads, display activation, and temporary power changes."""
from __future__ import annotations

from dataclasses import dataclass

from .wled_client import WLEDClient


@dataclass
class MatrixOutput:
    """Keep uploaded-file identity separate from the current physical display."""

    entity_id: str
    wled: WLEDClient
    width: int
    height: int
    auto_detect_size: bool
    image_fit: str
    image_crop_position: str
    image_zoom: int
    image_blur_strength: int
    image_background_brightness: int
    filename_prefix: str
    segment_id: int
    transition_style: str
    transition_seconds: float
    fade_to_black: bool
    black_pause: float
    matrix_turn_on: bool
    resolution_detected: bool = False
    snapshot: dict | None = None
    last_matrix_key: object | None = None
    last_filename: str | None = None
    last_art_fingerprint: str | None = None
    last_transition_style: str | None = None
    last_result: str = "not_started"
    last_error: str | None = None
    last_updated_at: str | None = None
    snapshot_error: str | None = None
    resolution_source: str = "manual_fallback"
    display_valid: bool = False
    uploaded_fingerprint: str | None = None
    temporary_fallback_off: bool = False
    power_on_expected_until: float | None = None

    def expect_power_on(self, now: float) -> None:
        """Allow a delayed HA confirmation of an integration-issued on command."""
        self.power_on_expected_until = now + 30.0

    def consume_expected_power_on(self, now: float) -> bool:
        """Match one software power-on confirmation, never a reconnect."""
        deadline = self.power_on_expected_until
        self.power_on_expected_until = None
        return deadline is not None and now <= deadline

    def invalidate_display(self, *, forget_upload: bool = False) -> None:
        """Require activation again; a reboot also makes file presence uncertain."""
        self.display_valid = False
        self.last_matrix_key = None
        if forget_upload:
            self.uploaded_fingerprint = None

    @property
    def can_restore_fallback_power(self) -> bool:
        """Only undo an integration-issued off action for a previously on matrix."""
        return bool(self.temporary_fallback_off and self.snapshot and self.snapshot.get("on"))
