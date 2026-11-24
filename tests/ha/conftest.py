"""Run the real coordinator inside Home Assistant's test harness when available."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Load custom_components/wled_album_art from this checkout."""
    yield
