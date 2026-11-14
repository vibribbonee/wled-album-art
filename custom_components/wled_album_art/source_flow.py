"""Source-event and priority decisions independent of Home Assistant services."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol


class MediaSourceState(Protocol):
    """State fields used when deciding whether a source changed meaningfully."""

    state: str
    attributes: Mapping[str, object]


# Keep this aligned with music eligibility, input filtering, track identity and
# artwork URL selection. Position/volume updates are deliberately absent: they
# must not keep restarting the debounce or postpone playback-end detection.
SOURCE_CHANGE_ATTRIBUTES = (
    "entity_picture_local",
    "entity_picture",
    "media_image_url",
    "media_title",
    "media_artist",
    "media_album_artist",
    "media_album_name",
    "media_track",
    "media_content_id",
    "media_content_type",
    "source",
    "soundtouchplus_source",
    "app_name",
    "app_id",
)


def source_change_affects_artwork(
    old_state: MediaSourceState | None, new_state: MediaSourceState | None
) -> bool:
    """Ignore progress/volume churn while noticing playback and metadata changes.

    Removed and newly available entities count as changes. Two absent states do
    not. Values are compared directly, avoiding hashing arbitrary integration
    attributes or normalizing away meaningful track/URL changes.
    """
    if old_state is None or new_state is None:
        return old_state is not new_state
    if old_state.state != new_state.state:
        return True
    return any(
        old_state.attributes.get(attribute) != new_state.attributes.get(attribute)
        for attribute in SOURCE_CHANGE_ATTRIBUTES
    )


@dataclass(frozen=True)
class SourceCandidate:
    """One player evaluated by the manager's music eligibility policy."""

    entity_id: str
    state: MediaSourceState
    image_urls: tuple[str, ...]
    eligible_music: bool = True


def first_playing_source(
    source_order: Sequence[str], candidates: Sequence[SourceCandidate]
) -> SourceCandidate | None:
    """Choose a player before considering whether its artwork is available.

    The caller decides music eligibility, including ignored inputs and
    same-session continuity. A lower-priority source with artwork must not skip
    a preferred music source whose cover still needs fetching. Buffering and
    paused continuity remain explicit manager policies.
    """
    by_entity = {
        candidate.entity_id: candidate
        for candidate in candidates
        if candidate.eligible_music and candidate.state.state == "playing"
    }
    return next((by_entity[item] for item in source_order if item in by_entity), None)
