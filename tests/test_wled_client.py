from __future__ import annotations

import pytest

from wled_album_art_under_test.wled_client import WLEDClient


class FakeResponse:
    def __init__(self, payload=None, status: int = 200, body: str = "") -> None:
        self.payload = payload
        self.status = status
        self.body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args) -> None:
        return None

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise RuntimeError(f"unexpected HTTP status {self.status}")

    async def json(self, content_type=None):
        return self.payload

    async def text(self) -> str:
        return self.body


class FakeSession:
    def __init__(self) -> None:
        self.posted_states: list[dict] = []
        self.effects = [
            "Solid", "Image", "Rainbow", "Colorwaves", "Text", "Scrolling Text",
            "GIF", "Pacifica",
        ]
        self.state = {"seg": [{"id": 0, "fx": 2}]}

    def get(self, url, **_kwargs):
        if url.endswith("json/eff"):
            return FakeResponse(self.effects)
        if url.endswith("json/state"):
            return FakeResponse(self.state)
        if url.endswith("edit"):
            return FakeResponse([])
        raise AssertionError(f"Unexpected GET URL: {url}")

    def post(self, url, json=None, **_kwargs):
        if url.endswith("json/state"):
            self.posted_states.append(json or {})
            return FakeResponse({"success": True})
        raise AssertionError(f"Unexpected POST URL: {url}")


@pytest.mark.asyncio
async def test_native_transition_activates_uploaded_filename_in_one_state_update() -> None:
    session = FakeSession()
    client = WLEDClient(session, "http://wled.local/", "", 0, "album")

    await client.async_activate_image("album_123456.gif", "fade", 0.7)

    assert len(session.posted_states) == 1
    payload = session.posted_states[0]
    assert payload["on"] is True
    assert payload["bs"] == 0
    assert payload["tt"] == 7
    assert payload["seg"][0]["fx"] == 1  # Image effect index discovered from WLED
    assert payload["seg"][0]["n"] == "album_123456.gif"




class CleanupSession:
    def __init__(self) -> None:
        self.deleted_paths: list[str] = []
        self.files = [
            {"name": "album_active.gif"},
            {"name": "album_saved-before-session.gif"},
            {"name": "album_old-cover.gif"},
            {"name": "unrelated.gif"},
        ]

    def get(self, url, params=None, **_kwargs):
        params = params or {}
        if url.endswith("edit") and params.get("func") == "list":
            return FakeResponse(self.files)
        if url.endswith("edit") and params.get("func") == "delete":
            self.deleted_paths.append(str(params.get("path")))
            return FakeResponse({"success": True})
        raise AssertionError(f"Unexpected GET URL: {url}, params={params}")


@pytest.mark.asyncio
async def test_cleanup_preserves_artwork_needed_for_state_restoration() -> None:
    session = CleanupSession()
    client = WLEDClient(session, "http://wled.local/", "", 0, "album")

    await client.async_cleanup_old_images(
        "album_active.gif", preserve_filenames=["album_saved-before-session.gif"]
    )

    assert session.deleted_paths == ["/album_old-cover.gif"]


def test_client_follows_a_new_address_from_the_resolver():
    """A WLED that moves to a new IP keeps working without a reload."""
    address = {"url": "http://192.168.0.108"}
    client = WLEDClient(
        None, "http://192.168.0.108", "", 0, "album",
        url_resolver=lambda: address["url"],
    )
    assert client._url("json/state") == "http://192.168.0.108/json/state"
    address["url"] = "http://192.168.0.140/"
    assert client._url("json/state") == "http://192.168.0.140/json/state"

    def missing():
        raise ValueError("WLED entry removed")

    client._url_resolver = missing
    assert client._url("json/info") == "http://192.168.0.140/json/info"
