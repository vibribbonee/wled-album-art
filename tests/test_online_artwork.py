"""Regression coverage for external API payloads and failed-cover recovery."""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from io import BytesIO
from types import SimpleNamespace

import aiohttp
import pytest
from PIL import Image
from yarl import URL

from wled_album_art_under_test import online_artwork
from wled_album_art_under_test.online_artwork import OnlineArtworkLookup
from wled_album_art_under_test.image_processing import prepare_image

IMAGE_URL = "https://lastfm.freetls.fastly.net/i/u/300x300/cover.png"
PLACEHOLDER = "https://lastfm.freetls.fastly.net/i/u/300x300/2a96cbd8b46e442fc41c2b86b821562f.png"
_IMAGE_BUFFER = BytesIO()
Image.new("RGB", (2, 2), (90, 140, 200)).save(_IMAGE_BUFFER, format="PNG")
IMAGE_BYTES = _IMAGE_BUFFER.getvalue()


@pytest.fixture(autouse=True)
def isolated_lastfm_request_gate(monkeypatch):
    """No real delays or shared credentials between independent API scenarios."""
    monkeypatch.setattr(online_artwork, "_LASTFM_REQUEST_INTERVAL", 0)
    monkeypatch.setattr(online_artwork, "_LAST_LASTFM_REQUEST", 0.0)
    monkeypatch.setattr(online_artwork, "_LASTFM_LOCK", asyncio.Lock())
    monkeypatch.setattr(online_artwork, "_LASTFM_BACKOFF", OrderedDict())


class Response:
    def __init__(self, payload=None, *, status=200, image=None, url=IMAGE_URL):
        self.payload = payload
        self.status = status
        self.url = URL(url)
        self.headers = {"Content-Type": "image/png" if image else "application/json"}
        self.content = self
        self.image = image

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def json(self, **_kwargs):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload

    async def iter_chunked(self, _size):
        yield self.image

    def raise_for_status(self):
        if self.status >= 400:
            raise aiohttp.ClientResponseError(
                request_info=SimpleNamespace(real_url=self.url),
                history=(), status=self.status,
            )


class Session:
    def __init__(self, handler):
        self.handler = handler
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.handler(url, kwargs.get("params", {}))


def track_payload(url=IMAGE_URL):
    return {"track": {"name": "Musician", "artist": {"name": "Porter Robinson"},
                      "album": {"title": "Nurture", "image": [{"#text": url, "size": "extralarge"}]}}}


def missing():
    return Response({"error": 6, "message": "Album not found"})


@pytest.mark.asyncio
async def test_album_placeholder_falls_back_to_track_art_with_api_key_only():
    def handler(url, params):
        if params.get("method") == "album.getInfo":
            return Response({"album": {"image": [{"#text": PLACEHOLDER}]}})
        if params.get("method") == "track.getInfo":
            return Response(track_payload())
        assert url == IMAGE_URL
        return Response(image=IMAGE_BYTES)

    session = Session(handler)
    lookup = OnlineArtworkLookup(session)
    lookup.configure("lastfm_only", "test-api-key")
    assert await lookup.async_lookup("Musician", "Porter Robinson", "Nurture") == IMAGE_BYTES
    assert lookup.diagnostics()["matched_provider"] == "lastfm"
    for _url, kwargs in session.calls[:2]:
        assert kwargs["params"]["api_key"] == "test-api-key"
        assert "api_sig" not in kwargs["params"]
        assert "secret" not in kwargs["params"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 403])
async def test_invalid_key_is_visible_even_when_error_uses_http_403(status):
    session = Session(lambda _url, _params: Response(
        {"error": 10, "message": "Invalid API key"}, status=status,
    ))
    lookup = OnlineArtworkLookup(session)
    lookup.configure("lastfm_only", "test-secret-value")
    assert await lookup.async_lookup("Musician", "Porter Robinson") is None
    assert lookup.diagnostics()["provider_results"] == {"lastfm": "invalid_api_key"}
    assert "rejected the API key" in lookup.failure_summary
    assert "test-secret-value" not in str(lookup.diagnostics())
    assert len(session.calls) == 1


@pytest.mark.asyncio
async def test_broken_album_image_does_not_skip_track_lookup():
    bad_url = "https://lastfm.freetls.fastly.net/i/u/300x300/old.png"

    def handler(url, params):
        if params.get("method") == "album.getInfo":
            return Response({"album": {"image": [{"#text": bad_url}]}})
        if params.get("method") == "track.getInfo":
            return Response(track_payload())
        return Response(status=403 if url == bad_url else 200, image=IMAGE_BYTES)

    lookup = OnlineArtworkLookup(Session(handler))
    lookup.configure("lastfm_only", "key")
    assert await lookup.async_lookup("Musician", "Porter Robinson", "Nurture") == IMAGE_BYTES


@pytest.mark.asyncio
async def test_combined_artists_and_featured_title_have_bounded_fallbacks():
    def handler(url, params):
        if (params.get("artist"), params.get("track")) == ("Seven Lions", "Foolish Of Me"):
            return Response(track_payload())
        return Response(image=IMAGE_BYTES) if url == IMAGE_URL else missing()

    session = Session(handler)
    lookup = OnlineArtworkLookup(session)
    lookup.configure("lastfm_only", "key")
    assert await lookup.async_lookup(
        "Foolish Of Me (feat. Jonathan Mendelsohn)",
        "Seven Lions, Jason Ross, Crystal Skies & Jonathan Mendelsohn", "Foolish Of Me",
    ) == IMAGE_BYTES
    api_calls = [kwargs["params"] for _url, kwargs in session.calls if "params" in kwargs]
    assert api_calls[0]["artist"] == "Seven Lions, Jason Ross, Crystal Skies & Jonathan Mendelsohn"
    assert len(api_calls) <= 6


@pytest.mark.asyncio
async def test_exact_band_credit_and_remix_name_are_preserved():
    session = Session(lambda url, params: (
        Response(track_payload()) if params else Response(image=IMAGE_BYTES)
    ))
    lookup = OnlineArtworkLookup(session)
    lookup.configure("lastfm_only", "key")
    assert await lookup.async_lookup("Song (Live Remix)", "Simon & Garfunkel") == IMAGE_BYTES
    params = session.calls[0][1]["params"]
    assert params["artist"] == "Simon & Garfunkel"
    assert params["track"] == "Song (Live Remix)"


@pytest.mark.asyncio
async def test_current_song_keeps_cached_miss_until_playback_ends_or_refresh(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(online_artwork, "time", SimpleNamespace(
        monotonic=lambda: clock[0], time=lambda: clock[0],
    ))
    available = [False]

    def handler(url, params):
        if url == IMAGE_URL:
            return Response(image=IMAGE_BYTES)
        return Response(track_payload()) if available[0] else missing()

    session = Session(handler)
    lookup = OnlineArtworkLookup(session)
    lookup.configure("lastfm_only", "key")
    assert await lookup.async_lookup("Musician", "Porter Robinson") is None
    available[0] = True
    assert await lookup.async_lookup("Musician", "Porter Robinson") is None
    assert lookup.diagnostics()["from_cache"] is True
    assert len(session.calls) == 1
    clock[0] += 301
    assert await lookup.async_lookup("Musician", "Porter Robinson") is None
    assert len(session.calls) == 1
    lookup.release_current_track()
    assert await lookup.async_lookup("Musician", "Porter Robinson") == IMAGE_BYTES
    lookup.clear_cache()
    available[0] = False
    assert await lookup.async_lookup("Musician", "Porter Robinson") is None
    lookup.clear_cache()
    available[0] = True
    assert await lookup.async_lookup("Musician", "Porter Robinson") == IMAGE_BYTES


@pytest.mark.asyncio
async def test_broken_native_art_updates_preserve_current_song_lookup(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(online_artwork, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    session = Session(lambda _url, _params: missing())
    lookup = OnlineArtworkLookup(session)
    lookup.configure("lastfm_only", "key")
    assert await lookup.async_lookup("Musician", "Porter Robinson", "Nurture") is None
    request_count = len(session.calls)
    clock[0] += 301
    lookup.observe_track("  MUSICIAN ", "Porter  Robinson", "nurture")
    assert await lookup.async_lookup("Musician", "Porter Robinson", "Nurture") is None
    assert len(session.calls) == request_count
    assert lookup.diagnostics()["from_cache"] is True


@pytest.mark.asyncio
async def test_intervening_native_art_track_releases_previous_lookup(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(online_artwork, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    session = Session(lambda _url, _params: missing())
    lookup = OnlineArtworkLookup(session)
    lookup.configure("lastfm_only", "key")
    assert await lookup.async_lookup("Musician", "Porter Robinson", "Nurture") is None
    request_count = len(session.calls)
    clock[0] += 301
    lookup.observe_track("Shelter", "Madeon & Porter Robinson", "Shelter")
    assert await lookup.async_lookup("Musician", "Porter Robinson", "Nurture") is None
    assert len(session.calls) > request_count
    assert lookup.diagnostics()["from_cache"] is False


@pytest.mark.asyncio
async def test_changing_api_key_discards_cached_failure():
    def handler(url, params):
        if url == IMAGE_URL:
            return Response(image=IMAGE_BYTES)
        if params.get("api_key") == "old-key":
            return Response({"error": 10})
        return Response(track_payload())

    lookup = OnlineArtworkLookup(Session(handler))
    lookup.configure("lastfm_only", "old-key")
    assert await lookup.async_lookup("Musician", "Porter Robinson") is None
    lookup.configure("lastfm_only", "new-key")
    assert await lookup.async_lookup("Musician", "Porter Robinson") == IMAGE_BYTES


@pytest.mark.asyncio
async def test_provider_failure_falls_through_to_musicbrainz(monkeypatch):
    lookup = OnlineArtworkLookup(Session(lambda _url, _params: Response({"error": 10})))
    lookup.configure("lastfm_first", "key")

    async def archive_cover(_release, _artist, **_kwargs):
        return IMAGE_BYTES

    monkeypatch.setattr(lookup, "_async_musicbrainz_cover", archive_cover)
    assert await lookup.async_lookup("Musician", "Porter Robinson") == IMAGE_BYTES
    assert lookup.diagnostics()["provider_results"] == {"lastfm": "invalid_api_key", "musicbrainz": "found"}
    assert lookup.failure_summary is None


@pytest.mark.asyncio
async def test_lastfm_only_without_key_is_explicit_and_makes_no_request():
    session = Session(lambda _url, _params: pytest.fail("A missing key must not make a request"))
    lookup = OnlineArtworkLookup(session)
    lookup.configure("lastfm_only", "")
    assert await lookup.async_lookup("Musician", "Porter Robinson") is None
    assert lookup.diagnostics()["lastfm_api_key_configured"] is False
    assert "needs an API key" in lookup.failure_summary


@pytest.mark.asyncio
@pytest.mark.parametrize("status, reason", [(429, "rate_limited"), (503, "service_unavailable")])
async def test_service_failures_are_not_reported_as_no_match(status, reason):
    lookup = OnlineArtworkLookup(Session(lambda _url, _params: Response(status=status)))
    lookup.configure("lastfm_only", "key")
    assert await lookup.async_lookup("Musician", "Porter Robinson") is None
    assert lookup.diagnostics()["provider_results"] == {"lastfm": reason}


@pytest.mark.asyncio
async def test_non_json_http_error_preserves_status_without_leaking_request_url():
    session = Session(lambda _url, _params: Response(ValueError("HTML error page"), status=403))
    lookup = OnlineArtworkLookup(session)
    lookup.configure("lastfm_only", "test-secret-value")
    assert await lookup.async_lookup("Musician", "Porter Robinson") is None
    assert lookup.diagnostics()["provider_results"] == {"lastfm": "http_403"}
    assert "HTTP 403" in lookup.failure_summary
    assert "test-secret-value" not in str(lookup.diagnostics())


@pytest.mark.asyncio
async def test_slow_provider_is_bounded_and_next_provider_can_succeed(monkeypatch):
    lookup = OnlineArtworkLookup(Session(lambda _url, _params: pytest.fail("Unexpected request")))
    lookup.configure("lastfm_first", "key")
    monkeypatch.setattr(online_artwork, "_PROVIDER_TIMEOUT_SECONDS", 0.01)

    async def slow_lastfm(*_args):
        await asyncio.Event().wait()

    async def archive_cover(*_args, **_kwargs):
        return IMAGE_BYTES

    monkeypatch.setattr(lookup, "_async_lastfm_cover", slow_lastfm)
    monkeypatch.setattr(lookup, "_async_musicbrainz_cover", archive_cover)
    assert await lookup.async_lookup("Musician", "Porter Robinson") == IMAGE_BYTES
    assert lookup.diagnostics()["provider_results"] == {"lastfm": "timeout", "musicbrainz": "found"}


@pytest.mark.asyncio
async def test_unrecognized_image_host_is_visible_and_never_downloaded():
    session = Session(lambda _url, _params: Response(track_payload("https://unknown.example/cover.png")))
    lookup = OnlineArtworkLookup(session)
    lookup.configure("lastfm_only", "key")
    assert await lookup.async_lookup("Musician", "Porter Robinson") is None
    assert lookup.diagnostics()["provider_results"] == {"lastfm": "unsupported_image_host"}
    assert len(session.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("final_host", ["lastfm-img.freetls.fastly.net", "lastfm.freetls.fastly.net"])
async def test_lastfm_image_cdn_gif_survives_lookup_and_matrix_preparation(final_host):
    gif_url = "https://lastfm-img.freetls.fastly.net/i/u/300x300/animated-cover.gif"
    frames = [Image.new("RGB", (64, 64), color) for color in ("red", "green", "blue")]
    original = BytesIO()
    frames[0].save(
        original, format="GIF", save_all=True, append_images=frames[1:],
        duration=[80, 120, 200], loop=0,
    )

    def handler(url, params):
        if params.get("method") == "track.getInfo":
            return Response(track_payload(gif_url))
        assert url == gif_url
        response = Response(image=original.getvalue(), url=f"https://{final_host}/cover.gif")
        response.headers["Content-Type"] = "image/gif"
        return response

    lookup = OnlineArtworkLookup(Session(handler))
    lookup.configure("lastfm_only", "key")
    cover = await lookup.async_lookup("Super Shy", "NewJeans")
    assert cover == original.getvalue()
    _preview, matrix_gif = prepare_image(cover, 32, 32, "crop")
    with Image.open(BytesIO(matrix_gif)) as image:
        assert image.n_frames == 3
        assert image.size == (32, 32)
        assert image.info["loop"] == 0
        durations = []
        pixels = []
        for index in range(image.n_frames):
            image.seek(index)
            durations.append(image.info["duration"])
            pixels.append(image.convert("RGB").getpixel((0, 0)))
        assert durations == [80, 120, 200]
        assert len(set(pixels)) == 3


@pytest.mark.parametrize("host", [
    "unrelated.freetls.fastly.net",
    "lastfm-img.freetls.fastly.net.evil.example",
    "evil-lastfm-img.freetls.fastly.net",
])
def test_lastfm_cdn_fix_does_not_trust_other_fastly_tenants(host):
    assert OnlineArtworkLookup._is_trusted_lastfm_host(host) is False


@pytest.mark.asyncio
async def test_position_style_updates_do_not_repeat_requests_or_searching_status():
    session = Session(lambda _url, _params: missing())
    lookup = OnlineArtworkLookup(session)
    lookup.configure("lastfm_only", "key")
    searching = []
    for _position_update in range(100):
        assert await lookup.async_lookup(
            "  Musician  ", "Porter Robinson", on_request=lambda: searching.append(True),
        ) is None
    assert len(session.calls) == 1
    assert searching == [True]
    assert lookup.diagnostics()["from_cache"] is True
    await lookup.async_lookup("Super Shy", "NewJeans", on_request=lambda: searching.append(True))
    assert len(session.calls) == 2
    assert searching == [True, True]
    lookup.clear_cache()
    await lookup.async_lookup("Super Shy", "NewJeans", on_request=lambda: searching.append(True))
    assert len(session.calls) == 3
    assert searching == [True, True, True]


@pytest.mark.asyncio
async def test_simultaneous_requests_for_same_song_share_one_lookup():
    class SlowResponse(Response):
        async def json(self, **kwargs):
            await asyncio.sleep(0.01)
            return await super().json(**kwargs)

    session = Session(lambda _url, _params: SlowResponse({"error": 6}))
    lookup = OnlineArtworkLookup(session)
    lookup.configure("lastfm_only", "key")
    results = await asyncio.gather(*(
        lookup.async_lookup("Musician", "Porter Robinson") for _caller in range(8)
    ))
    assert results == [None] * 8
    assert len(session.calls) == 1


@pytest.mark.asyncio
async def test_retry_after_is_shared_across_entries_and_track_changes(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(online_artwork, "time", SimpleNamespace(
        monotonic=lambda: clock[0], time=lambda: clock[0],
    ))
    def limited(_url, _params):
        response = Response(status=429)
        response.headers["Retry-After"] = "120"
        return response

    first_session = Session(limited)
    first = OnlineArtworkLookup(first_session)
    first.configure("lastfm_only", "shared-key")
    await first.async_lookup("Musician", "Porter Robinson")
    other_session = Session(lambda _url, _params: missing())
    other = OnlineArtworkLookup(other_session)
    other.configure("lastfm_only", "shared-key")
    searching = []
    await other.async_lookup("Super Shy", "NewJeans", on_request=lambda: searching.append(True))
    assert len(first_session.calls) == 1
    assert other_session.calls == []
    assert searching == []
    assert other.diagnostics()["provider_results"] == {"lastfm": "rate_limited"}
    assert other.diagnostics()["lastfm_retry_after_seconds"] == 120
    clock[0] += 119
    other.clear_cache(retry_authentication=True)
    await other.async_lookup("Super Shy", "NewJeans")
    assert other_session.calls == []
    clock[0] += 2
    other.clear_cache()
    await other.async_lookup("Super Shy", "NewJeans")
    assert len(other_session.calls) == 1


@pytest.mark.asyncio
async def test_invalid_key_is_not_queried_again_for_every_new_song():
    session = Session(lambda _url, _params: Response({"error": 10}))
    lookup = OnlineArtworkLookup(session)
    lookup.configure("lastfm_only", "bad-key")
    await lookup.async_lookup("Musician", "Porter Robinson")
    await lookup.async_lookup("Super Shy", "NewJeans")
    lookup.clear_cache()
    await lookup.async_lookup("EVERLASTING", "passengerprincess")
    assert len(session.calls) == 1
    assert lookup.diagnostics()["provider_results"] == {"lastfm": "invalid_api_key"}
    lookup.configure("lastfm_only", "another-key")
    await lookup.async_lookup("EVERLASTING", "passengerprincess")
    assert len(session.calls) == 2


@pytest.mark.asyncio
async def test_lastfm_api_calls_are_spaced_across_album_and_track_queries(monkeypatch):
    clock = [1000.0]
    sleeps = []
    monkeypatch.setattr(online_artwork, "time", SimpleNamespace(
        monotonic=lambda: clock[0], time=lambda: clock[0],
    ))
    monkeypatch.setattr(online_artwork, "_LASTFM_REQUEST_INTERVAL", 1.0)

    async def advance(seconds):
        sleeps.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr(online_artwork.asyncio, "sleep", advance)
    session = Session(lambda _url, _params: missing())
    lookup = OnlineArtworkLookup(session)
    lookup.configure("lastfm_only", "key")
    await lookup.async_lookup("Musician", "Porter Robinson", "Nurture")
    assert len(session.calls) == 2
    assert sleeps == [1.0]


def test_retry_after_http_date_is_honored(monkeypatch):
    monkeypatch.setattr(online_artwork, "time", SimpleNamespace(time=lambda: 0.0))
    assert OnlineArtworkLookup._retry_after_seconds({"Retry-After": "Thu, 01 Jan 1970 00:02:00 GMT"}) == 120


@pytest.mark.asyncio
async def test_queued_entry_does_not_shorten_or_extend_existing_retry_after(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(online_artwork, "time", SimpleNamespace(
        monotonic=lambda: clock[0], time=lambda: clock[0],
    ))
    entered = asyncio.Event()
    release = asyncio.Event()

    class PausedLimitResponse(Response):
        async def __aenter__(self):
            entered.set()
            await release.wait()
            return self

    def limited(_url, _params):
        response = PausedLimitResponse(status=429)
        response.headers["Retry-After"] = "600"
        return response

    session = Session(limited)
    first, second = OnlineArtworkLookup(session), OnlineArtworkLookup(session)
    first.configure("lastfm_only", "same-key")
    second.configure("lastfm_only", "same-key")
    first_request = asyncio.create_task(first.async_lookup("Musician", "Porter Robinson"))
    await entered.wait()
    second_request = asyncio.create_task(second.async_lookup("Super Shy", "NewJeans"))
    await asyncio.sleep(0)
    release.set()
    await asyncio.gather(first_request, second_request)
    assert len(session.calls) == 1
    assert first.diagnostics()["lastfm_retry_after_seconds"] == 600
    assert second.diagnostics()["lastfm_retry_after_seconds"] == 600
    clock[0] += 550
    await second.async_lookup("EVERLASTING", "passengerprincess")
    assert second.diagnostics()["lastfm_retry_after_seconds"] == 50


@pytest.mark.asyncio
async def test_explicit_refresh_can_retry_same_key_after_authentication_failure():
    working = [False]
    session = Session(lambda _url, _params: missing() if working[0] else Response({"error": 10}))
    lookup = OnlineArtworkLookup(session)
    lookup.configure("lastfm_only", "same-key")
    await lookup.async_lookup("Musician", "Porter Robinson")
    working[0] = True
    lookup.clear_cache(retry_authentication=True)
    await lookup.async_lookup("Musician", "Porter Robinson")
    assert len(session.calls) == 2
    assert lookup.diagnostics()["provider_results"] == {"lastfm": "no_match"}
    assert lookup.diagnostics()["lastfm_backoff_reason"] is None


@pytest.mark.asyncio
async def test_cached_lookup_never_requests_and_reports_completed_searches():
    """The coordinator polls this while holding its lock, so it must stay offline."""
    def handler(url, params):
        if params.get("method") == "album.getInfo":
            return Response({"album": {"image": [{"#text": PLACEHOLDER}]}})
        if params.get("method") == "track.getInfo":
            return Response(track_payload())
        return Response(image=IMAGE_BYTES)

    session = Session(handler)
    lookup = OnlineArtworkLookup(session)
    lookup.configure("lastfm_only", "test-api-key")

    assert lookup.cached_lookup("Musician", "Porter Robinson", "Nurture") == (False, None)
    assert session.calls == []

    assert await lookup.async_lookup("Musician", "Porter Robinson", "Nurture") == IMAGE_BYTES
    request_count = len(session.calls)
    assert lookup.cached_lookup("Musician", "Porter Robinson", "Nurture") == (True, IMAGE_BYTES)
    assert lookup.diagnostics()["from_cache"] is True
    assert len(session.calls) == request_count


def test_cached_lookup_answers_missing_metadata_without_a_search():
    session = Session(lambda _url, _params: pytest.fail("no request expected"))
    lookup = OnlineArtworkLookup(session)
    lookup.configure("lastfm_only", "test-api-key")
    assert lookup.cached_lookup("", "Porter Robinson") == (True, None)
    assert lookup.diagnostics()["provider_results"] == {"lookup": "missing_metadata"}


@pytest.mark.asyncio
async def test_cached_lookup_keeps_a_miss_for_the_current_song():
    session = Session(lambda _url, _params: missing())
    lookup = OnlineArtworkLookup(session)
    lookup.configure("lastfm_only", "test-api-key")
    assert await lookup.async_lookup("Unknown", "Nobody") is None
    assert lookup.cached_lookup("Unknown", "Nobody") == (True, None)
