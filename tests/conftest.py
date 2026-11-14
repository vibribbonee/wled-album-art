"""Load integration-independent modules without requiring Home Assistant in CI."""
from __future__ import annotations

import sys
import types
from pathlib import Path

COMPONENT_DIR = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "wled_album_art"
)
PACKAGE_NAME = "wled_album_art_under_test"

# Avoid executing the integration __init__.py, which imports Home Assistant.
# Image processing and the WLED HTTP client can be unit-tested on a plain Python
# runner without installing the full Home Assistant application.
if PACKAGE_NAME not in sys.modules:
    package = types.ModuleType(PACKAGE_NAME)
    package.__path__ = [str(COMPONENT_DIR)]  # type: ignore[attr-defined]
    sys.modules[PACKAGE_NAME] = package
