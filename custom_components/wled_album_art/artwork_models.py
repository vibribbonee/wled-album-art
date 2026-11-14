"""Named, tuple-compatible identities for cached artwork and fallback scenes."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, NamedTuple

from .artwork_data import PreparedArtwork


class TrackKey(NamedTuple):
    """Artwork identity; tuple layout retained for existing saved/cache keys."""

    kind: Literal["track"]
    source_entity: str
    title: str | None
    artist: str | None
    image_urls: tuple[str, ...]
    media_content_type: str
    source: str
    alternate_source: str
    app_name: str
    album: str
    online_lookup: bool
    provider_revision: int | None


class NoArtKey(NamedTuple):
    """Fallback-scene identity with its session policy stated explicitly."""

    kind: Literal["no_art"]
    source_entity: str
    title: str | None
    artist: str | None
    behavior: str
    color: tuple[int, int, int]
    brightness: int
    policy: Literal["start", "during_session"]


@dataclass(frozen=True)
class PlayerArtwork:
    """Keep the player's original cover available after an animation upgrade."""

    key: TrackKey
    source: bytes
    prepared: PreparedArtwork
    metadata: dict
