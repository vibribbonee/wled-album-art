"""Helpers for safe, user-facing integration diagnostics."""
from __future__ import annotations

import re

_URL_IN_ERROR = re.compile(r"https?://[^\s<>\"'`]+", re.IGNORECASE)


def safe_error_text(error: object, limit: int = 500) -> str:
    """Keep useful error diagnostics without exposing signed artwork URLs."""
    text = _URL_IN_ERROR.sub("[redacted URL]", str(error))
    return text[:limit]
