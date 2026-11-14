"""Conservative fallback queries for player and video-platform metadata."""
from __future__ import annotations

import re
import unicodedata

# These describe uploads, not musical versions. Keep live/remix/acoustic/etc.
_UPLOAD_LABEL = (
    r"(?:official\s+(?:animated\s+)?(?:music\s+video|video|audio|mv(?:\s+flipnote)?)|"
    r"(?:official\s+)?(?:lyric\s+video|lyrics|visuali[sz]er))"
)
_UPLOAD_SUFFIX = re.compile(
    rf"\s*(?:\(\s*{_UPLOAD_LABEL}\s*\)|\[\s*{_UPLOAD_LABEL}\s*\]"
    rf"|\s+[-–—|]\s*{_UPLOAD_LABEL})\s*$", re.I,
)
_TITLE_SEPARATOR = re.compile(r"\s+[-–—|]\s+")
_LIVE_SUFFIX = re.compile(r"\s*[\[(]live(?:\s+[^\])]+)?[\])]\s*$", re.I)
_PROTECTED_EDITION = re.compile(r"\b(?:remix|mix|acoustic|remaster(?:ed)?|cover|sped|slowed)\b", re.I)


def _plain(value: str) -> str:
    """Fold decorative Unicode letters without changing the displayed metadata."""
    return " ".join(unicodedata.normalize("NFKC", value).split())


def lookup_metadata_variants(
    title: str, artist: str, album: str,
) -> tuple[tuple[str, str, str], ...]:
    """Build at most four queries, preserving the exact edition first.

    Remove an artist prefix only when it agrees with the separately reported
    artist. Infer credits only for labelled uploads, and relax live details
    only after the original edition. Protected musical versions remain intact.
    """
    original = (title, artist, album)
    plain_artist = _plain(artist)
    plain_title = _plain(title)
    upload_label_removed = False
    for _ in range(3):
        stripped = _UPLOAD_SUFFIX.sub("", plain_title).strip()
        if not stripped or stripped == plain_title:
            break
        plain_title = stripped
        upload_label_removed = True
    for separator in _TITLE_SEPARATOR.finditer(plain_title):
        prefix = plain_title[:separator.start()].strip()
        remainder = plain_title[separator.end():].strip()
        if prefix.casefold() == plain_artist.casefold() and remainder:
            plain_title = remainder
            break
    plain_album = _plain(album)
    if plain_album.casefold() == _plain(title).casefold():
        plain_album = plain_title
    cleaned = (plain_title, plain_artist, plain_album)
    variants = [original, cleaned]
    # A lyric/video uploader can differ from the credited performer. Try both
    # common title orders, relying on provider artist AND title matching rather
    # than choosing a cover by title alone. Only infer from labelled uploads.
    if upload_label_removed:
        separators = []
        for separator in _TITLE_SEPARATOR.finditer(plain_title):
            before = plain_title[:separator.start()]
            if before.count("(") == before.count(")") and before.count("[") == before.count("]"):
                separators.append(separator)
        if len(separators) == 1:
            separator = separators[0]
            left = plain_title[:separator.start()].strip()
            right = plain_title[separator.end():].strip()
            if left and right:
                variants.extend(((left, right, ""), (right, left, "")))
    # A catalog may lack a specific concert recording. Only after its exact
    # details fail, allow a cover for the base song by the same performer.
    if not _PROTECTED_EDITION.search(plain_title):
        base_title = _LIVE_SUFFIX.sub("", plain_title).strip()
        if base_title and base_title != plain_title:
            variants.append((base_title, plain_artist, ""))
    return tuple(dict.fromkeys(variants))[:4]


def artwork_match_description(title: str, artist: str, matched_query: dict | None) -> str:
    """Explain approximate catalog artwork without exposing raw diagnostics."""
    if not matched_query:
        return "Cover found by an artwork service"
    matched_artist = _plain(str(matched_query.get("artist") or ""))
    if matched_artist.casefold() != _plain(artist).casefold():
        return "Cover matched using an alternative artist credit"
    matched_title = _plain(str(matched_query.get("title") or ""))
    plain_title = _plain(title)
    if (
        _LIVE_SUFFIX.search(plain_title)
        and not _LIVE_SUFFIX.search(matched_title)
        and not _PROTECTED_EDITION.search(plain_title)
    ):
        return "General song cover for this live recording"
    if matched_query.get("used_metadata_fallback"):
        return "Cover matched after cleaning the upload title or artist name"
    return "Cover matched to the song metadata"
