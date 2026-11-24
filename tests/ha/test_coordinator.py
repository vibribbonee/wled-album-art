"""Coordinator behavior that needs Home Assistant's event loop and state machine."""
from __future__ import annotations

import asyncio
from unittest.mock import patch

from datetime import timedelta

from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.wled_album_art.const import DOMAIN
from custom_components.wled_album_art.online_artwork import OnlineArtworkLookup

SOURCE = "media_player.living_room"
ROOM_LIGHT = "light.room"


def _entry(**options) -> MockConfigEntry:
    """A room-lights-only entry, so no WLED device is needed."""
    return MockConfigEntry(
        domain=DOMAIN,
        version=2,
        title=f"Music lighting → {SOURCE}",
        data={"source_entity": SOURCE, "target_entity": ""},
        options={
            "source_entities": [SOURCE],
            "target_entity": "",
            "theme_light_entities": [ROOM_LIGHT],
            "source_stabilization": 0.3,
            "online_artwork_lookup": True,
            "artwork_provider_priority": "musicbrainz_first",
            **options,
        },
    )


async def _setup(hass, entry):
    hass.states.async_set(ROOM_LIGHT, "on", {"rgb_color": [255, 255, 255], "brightness": 128})
    hass.states.async_set(SOURCE, "idle")
    async_mock_service(hass, "light", "turn_on")
    async_mock_service(hass, "light", "turn_off")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    return hass.data[DOMAIN][entry.entry_id]


async def _settle(hass, seconds: float = 3) -> None:
    """Fire the coordinator's debounce timers and wait for its tasks."""
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))
    await hass.async_block_till_done(wait_background_tasks=True)


def _play_without_artwork(hass):
    hass.states.async_set(SOURCE, "playing", {
        "media_title": "Musician",
        "media_artist": "Porter Robinson",
        "media_album_name": "Nurture",
        "media_content_type": "music",
    })


async def test_setup_and_unload_without_any_reachable_device(hass):
    entry = _entry()
    manager = await _setup(hass, entry)
    assert manager.status
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.entry_id not in hass.data.get(DOMAIN, {})


async def test_slow_cover_search_does_not_hold_the_playback_lock(hass):
    entry = _entry()
    manager = await _setup(hass, entry)
    release = asyncio.Event()
    started = asyncio.Event()

    async def slow_lookup(self, title, artist, album=None, *, on_request=None):
        started.set()
        await release.wait()
        return None

    with patch.object(OnlineArtworkLookup, "async_lookup", slow_lookup):
        _play_without_artwork(hass)
        await asyncio.wait_for(started.wait(), 5)
        # The search is still running, but the coordinator is free for
        # refresh, playback-end, and unload work.
        await asyncio.sleep(0)
        assert not manager._lock.locked()
        assert "Searching online" in manager.status
        task = manager._missing_cover_task
        assert task is not None and not task.done()

        release.set()
        await hass.async_block_till_done(wait_background_tasks=True)
        assert manager._missing_cover_task is None

    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_unload_cancels_a_running_cover_search(hass):
    entry = _entry()
    manager = await _setup(hass, entry)
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def never_finishes(self, title, artist, album=None, *, on_request=None):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    with patch.object(OnlineArtworkLookup, "async_lookup", never_finishes):
        _play_without_artwork(hass)
        await asyncio.wait_for(started.wait(), 5)
        assert await asyncio.wait_for(hass.config_entries.async_unload(entry.entry_id), 5)
        await asyncio.wait_for(cancelled.wait(), 5)
    assert manager._stopping


async def test_completed_search_is_used_without_another_request(hass):
    """Only the network step is faked; caching and scheduling are real."""
    entry = _entry()
    manager = await _setup(hass, entry)
    calls = 0

    async def no_cover(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        return None

    with patch.object(OnlineArtworkLookup, "_async_musicbrainz_cover", no_cover):
        _play_without_artwork(hass)
        await _settle(hass)
        searched = calls
        assert searched >= 1
        # Position/volume churn and repeated updates reuse the remembered miss.
        hass.states.async_set(SOURCE, "playing", {
            **hass.states.get(SOURCE).attributes, "media_position": 12,
        })
        await _settle(hass)
        await manager.async_update(force=True)
        await _settle(hass)
    assert calls == searched
    assert manager._missing_cover_task is None
    assert "Searching online" not in manager.status
    assert await hass.config_entries.async_unload(entry.entry_id)
