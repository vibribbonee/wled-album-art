"""Tests for deterministic ordered source selection."""
from __future__ import annotations

from wled_album_art_under_test.selection import first_priority_candidate


def test_first_eligible_source_in_configured_order_wins() -> None:
    candidates = [
        ("media_player.kitchen", "kitchen cover"),
        ("media_player.living_room", "living room cover"),
    ]
    selected = first_priority_candidate(
        ["media_player.living_room", "media_player.kitchen"], candidates
    )
    assert selected == ("media_player.living_room", "living room cover")


def test_missing_higher_priority_source_falls_back_to_next_eligible() -> None:
    candidates = [("media_player.kitchen", "kitchen cover")]
    selected = first_priority_candidate(
        ["media_player.living_room", "media_player.kitchen"], candidates
    )
    assert selected == ("media_player.kitchen", "kitchen cover")


def test_returns_none_when_no_source_is_eligible() -> None:
    assert first_priority_candidate(["media_player.living_room"], []) is None


def test_target_list_normalization_preserves_order_and_deduplicates() -> None:
    from wled_album_art_under_test.selection import normalize_entity_list

    assert normalize_entity_list([
        "light.matrix_a", "light.matrix_b", "light.matrix_a", "", None,
    ]) == ["light.matrix_a", "light.matrix_b"]


def test_target_resolution_migrates_legacy_single_target() -> None:
    from wled_album_art_under_test.selection import configured_matrix_entities

    assert configured_matrix_entities({}, {"target_entity": "light.matrix_old"}) == [
        "light.matrix_old"
    ]


def test_explicit_empty_matrix_list_disables_legacy_target_fallback() -> None:
    from wled_album_art_under_test.selection import configured_matrix_entities

    assert configured_matrix_entities(
        {"target_entities": []}, {"target_entity": "light.matrix_old"}
    ) == []


def test_legacy_multi_matrix_entry_keeps_first_target_for_single_output_migration() -> None:
    from wled_album_art_under_test.selection import configured_matrix_entities

    assert configured_matrix_entities(
        {"target_entities": ["light.second", "light.first"]},
        {"target_entity": "light.legacy"},
    ) == ["light.second"]


def test_single_target_option_takes_precedence_over_legacy_data() -> None:
    from wled_album_art_under_test.selection import configured_matrix_entities

    assert configured_matrix_entities(
        {"target_entity": "light.new"},
        {"target_entity": "light.legacy", "target_entities": ["light.old", "light.older"]},
    ) == ["light.new"]


def test_empty_single_target_means_theme_only_not_legacy_fallback() -> None:
    from wled_album_art_under_test.selection import configured_matrix_entities

    assert configured_matrix_entities(
        {"target_entity": ""},
        {"target_entity": "light.legacy"},
    ) == []
