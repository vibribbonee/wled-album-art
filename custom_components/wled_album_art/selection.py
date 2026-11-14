"""Pure source-priority helpers."""
from __future__ import annotations

from typing import TypeVar

T = TypeVar("T")


def first_priority_candidate(source_order: list[str], candidates: list[tuple[str, T]]) -> tuple[str, T] | None:
    """Return the first eligible candidate according to configured source order."""
    candidate_map = {entity_id: candidate for entity_id, candidate in candidates}
    for entity_id in source_order:
        if entity_id in candidate_map:
            return entity_id, candidate_map[entity_id]
    return None


def normalize_entity_list(value: object) -> list[str]:
    """Normalize a single entity or list of entities, preserving order and uniqueness."""
    if value is None or value is False:
        return []
    values = [value] if isinstance(value, str) else value
    if not isinstance(values, (list, tuple, set)):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        if not isinstance(item, str):
            continue
        entity_id = item.strip()
        if entity_id and entity_id not in seen:
            seen.add(entity_id)
            result.append(entity_id)
    return result


def configured_matrix_entities(options: dict, data: dict) -> list[str]:
    """Resolve a single matrix target, retaining migration support for old entries.

    The integration supports either one matrix per entry or zero matrix targets for
    theme-light-only mode. When reading a pre-0.14 multi-matrix entry, retain the
    first configured target; additional displays can be added as separate entries.
    An explicit empty setting means no matrix and must not fall back to legacy data.
    """
    if "target_entity" in options:
        return normalize_entity_list(options.get("target_entity"))[:1]
    if "target_entities" in options:
        return normalize_entity_list(options.get("target_entities"))[:1]
    if "target_entities" in data:
        return normalize_entity_list(data.get("target_entities"))[:1]
    return normalize_entity_list(data.get("target_entity"))[:1]
