"""Tests for native WLED transition selection."""
from __future__ import annotations

from wled_album_art_under_test.const import TRANSITION_BLEND_STYLES
from wled_album_art_under_test.transitions import choose_transition_style


def test_non_shuffle_transition_is_preserved() -> None:
    assert choose_transition_style("fade", "push_left") == "fade"


def test_shuffle_returns_supported_native_style() -> None:
    assert choose_transition_style("shuffle") in TRANSITION_BLEND_STYLES


def test_shuffle_avoids_immediate_repeat_when_possible() -> None:
    previous = "fade"
    assert choose_transition_style("shuffle", previous) in set(TRANSITION_BLEND_STYLES) - {previous}
