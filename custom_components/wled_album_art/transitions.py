"""Pure helpers for selecting WLED transition styles."""
from __future__ import annotations

import random

from .const import TRANSITION_BLEND_STYLES


def choose_transition_style(configured_style: str, previous_style: str | None = None) -> str:
    """Resolve the shuffle option while avoiding an immediate repeat if possible."""
    if configured_style != "shuffle":
        return configured_style

    choices = list(TRANSITION_BLEND_STYLES)
    if previous_style in choices and len(choices) > 1:
        choices.remove(previous_style)
    return random.choice(choices)
