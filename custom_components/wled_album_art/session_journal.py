"""Construction helpers for durable saved-state recovery records."""
from __future__ import annotations

from copy import deepcopy


def new_session_journal(
    *,
    session_active: bool,
    matrix_snapshots: dict | None = None,
    theme_snapshots: dict | None = None,
    theme_restore_pending: list[str] | set[str] | None = None,
    deferred_matrix_restores: dict | None = None,
    deferred_theme_restores: dict | None = None,
) -> dict:
    """Build a complete v2 journal so restore paths share one stable schema."""
    return {
        "version": 2,
        "session_active": bool(session_active),
        "matrix_snapshots": deepcopy(matrix_snapshots or {}),
        "theme_snapshots": deepcopy(theme_snapshots or {}),
        "theme_restore_pending": sorted(set(theme_restore_pending or [])),
        "deferred_matrix_restores": deepcopy(deferred_matrix_restores or {}),
        "deferred_theme_restores": deepcopy(deferred_theme_restores or {}),
    }


def plan_session_end(
    journal: dict | None,
    *,
    room_behavior: str,
    matrix_behavior: str,
    theme_entities: list[str],
    matrix_defaults: dict[str, dict],
) -> dict:
    """Build a durable playback-end plan before issuing any output commands.

    Room and matrix policies are independent. Existing deferred restorations
    belong to earlier sessions and remain intact unless an explicit off/black
    action supersedes them for the same target. Returned snapshots never alias
    the supplied journal or defaults; the caller must persist this plan before
    applying it through the ordinary restoration path.

    ``matrix_defaults`` identifies all currently selected matrices and supplies
    connection details (PIN/segment) for targets without a session snapshot.
    Legacy ``black`` remains supported for entries retaining that end action.
    """
    if room_behavior not in {"restore_color", "restore_color_brightness", "keep", "turn_off"}:
        raise ValueError(f"Unsupported room playback-end behavior: {room_behavior}")
    if matrix_behavior not in {"restore_previous", "keep", "turn_off", "black"}:
        raise ValueError(f"Unsupported matrix playback-end behavior: {matrix_behavior}")

    plan = deepcopy(journal or {})
    defaults = new_session_journal(session_active=False)
    for key, value in defaults.items():
        plan.setdefault(key, value)
    plan["version"] = 2
    plan["session_active"] = False

    current_matrix = plan["matrix_snapshots"]
    deferred_matrix = plan["deferred_matrix_restores"]
    if matrix_behavior == "keep":
        plan["matrix_snapshots"] = {}
    elif matrix_behavior in {"turn_off", "black"}:
        target_ids = set(matrix_defaults) | set(current_matrix)
        for entity_id in sorted(target_ids):
            # Existing snapshots retain original connection information; default
            # details fill any holes for a selected target never snapshotted.
            snapshot = deepcopy(matrix_defaults.get(entity_id, {}))
            snapshot.update(deepcopy(deferred_matrix.get(entity_id, {})))
            snapshot.update(deepcopy(current_matrix.get(entity_id, {})))
            snapshot["_pending_end_behavior"] = (
                "black" if matrix_behavior == "black" else "turn_off_matrix"
            )
            current_matrix[entity_id] = snapshot
            deferred_matrix.pop(entity_id, None)

    current_theme = plan["theme_snapshots"]
    deferred_theme = plan["deferred_theme_restores"]
    pending_theme = set(plan["theme_restore_pending"])
    if room_behavior == "keep":
        plan["theme_snapshots"] = {}
        pending_theme.clear()
    elif room_behavior == "turn_off":
        pending_theme.update(theme_entities)
        for entity_id in sorted(pending_theme):
            snapshot = deepcopy(deferred_theme.get(entity_id, {}))
            snapshot.update(deepcopy(current_theme.get(entity_id, {})))
            snapshot["_pending_end_behavior"] = "turn_off_all"
            current_theme[entity_id] = snapshot
            deferred_theme.pop(entity_id, None)
    else:
        restore_brightness = room_behavior == "restore_color_brightness"
        for entity_id in pending_theme:
            if entity_id in current_theme:
                current_theme[entity_id]["_restore_brightness"] = restore_brightness
    plan["theme_restore_pending"] = sorted(pending_theme)
    return plan
