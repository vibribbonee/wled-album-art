# Music Artwork Lighting — Home Assistant custom integration (v0.16.2)

Match your room lighting and an optional WLED matrix to the music you're playing. Use cover art from your media player or selected online services. The integration also exposes an image and RGB/hex palettes for dashboards and automations, with no lighting hardware required.

[Install](#install) · [Daily controls](#dashboard-controls) · [Cover services](#cover-services) · [Dashboard artwork and colors](#artwork-and-colors-in-dashboards) · [Troubleshooting](#troubleshooting)

## Requirements

- Home Assistant with custom integrations enabled.
- For matrix output, WLED 0.16.x with the Image effect / PixelForge GIF playback available on the matrix.
- For matrix output, choose a `light` entity created by Home Assistant's built-in WLED integration.
- For theme lighting, choose Home Assistant `light` entities capable of RGB, HS, XY, RGBW, or RGBWW color. Non-color lights are skipped.

## Install

The integration is now displayed as **Music Artwork Lighting**. Its internal domain and folder intentionally remain `wled_album_art` so existing entries and entity IDs keep working; do not rename the folder when upgrading.

1. Back up Home Assistant.
2. Copy the `custom_components/wled_album_art` folder from this repository into `/config/custom_components/`, so the integration manifest is at `/config/custom_components/wled_album_art/manifest.json`.
3. Restart Home Assistant.
4. Open **Settings → Devices & services → Add integration → Music Artwork Lighting**. Choose an initial media player, then select one WLED matrix light. Leave the matrix selection empty for room-light-only mode or artwork/color entities without physical outputs. Add a separate integration entry for each additional matrix.
5. Enter the WLED configuration PIN only if that device requires one.
6. Open the entry's **Configure** options. Choose media players in priority order and select the matrix and optional theme lights. The first eligible playing source wins; lower-priority players are fallbacks. Artwork, cover services, and session timing are always available on the next screen; matrix and room-light settings appear for selected outputs. Assign each physical light to only one entry, and keep the matrix out of the theme-light list. Configure rejects conflicting selections.
7. Set up the matrix display. Dimensions are auto-detected when supported, with manual width/height as a fallback. Verify the segment ID (usually `0`) and artwork fit: crop to fill, black bars, blurred fill, dominant-color fill, or mirrored edges. Choose a crop focal point and zoom if you want different framing. **Fade** is a good starting transition. **Fade to black before showing each new cover** adds a black interval but can show a brief WLED effect-switch glitch on some builds; use a direct fade if you see that.
8. Under **Automatic power**, choose whether the integration can turn on the selected matrix and/or theme lights. Under **Room lighting**, choose color-capable lights, an album-reactive color style, color safeguards, and how theme lights transition. Theme lights follow the entity-selector order. The default powers on all selected outputs and lifts near-black colors; room lights fade to black with matrix transitions only when fade-to-black is enabled.
9. Set the two independent ending controls: **Room lights when playback ends** defaults to restoring previous color, and **Matrix when playback ends** defaults to turning the matrix off. To restore room brightness too, choose **Restore previous color and brightness**. The default grace period is 30 seconds. **When playback is paused** defaults to ending after that grace period; choose **Keep scene until playback resumes** for indefinite pauses. Existing saved ending choices are preserved when upgrading.

## Dashboard controls

The Configure form first asks which players and outputs to manage, then shows only settings that apply to those outputs. Tuning is grouped into **Artwork**, **When cover art is missing**, **When playback ends**, **Automatic power**, **Matrix display**, and **Room lighting**. Cover-service settings are available even with no lights selected. Related choices live together in dropdowns, and no bundled mood preset silently changes several preferences at once.

Low-level switches, selects, and timing numbers are marked as configuration entities in Home Assistant. Only settings for selected outputs are created. During the grace period, Status says which player reports paused or that no configured player is playing, and includes `session_end_remaining_seconds`. After cleanup, `last_session_end_reason`, `last_session_end_source_name`, and `last_session_end_source_entity_id` explain why the session ended.

The **Automatic control** switch remains the master pause/resume control. Turning it off restores the saved session state before pausing automatic updates. **Matrix artwork** is the quick casual-listening control: turning it off sends a power-off request to WLED and keeps room-light matching active. If WLED is unavailable, the integration retries after it reconnects. Enabling Matrix artwork during playback reapplies the current cover. The configuration switch **Search online for cover art** is enabled by default. It finds missing covers and, when **Animated artwork** is enabled, looks for an animated alternative to a static player cover in the background. Disable online search to keep track metadata out of external lookup services. Add **Retry state restoration** to the same card if you want a manual recovery action; it is unavailable while there is nothing to restore. Structural settings (source list, target matrix, dimensions, segment, and PIN) remain in **Configure** because changing them can require rebuilding device clients or subscriptions.

For a compact dashboard, add an Entities card with the entry's **Automatic control**, **Matrix artwork**, **Status**, **Current source**, **Now playing**, **Refresh artwork**, **Test matrix**, and **Retry state restoration** entities. Select the entities from the integration device in the card editor; entity IDs are generated from your entry name and can differ between installations. The recovery button is disabled unless restoration is pending.

## Dashboard tuning controls

Each entry exposes Home Assistant entities that can be added to an Entities card or any dashboard:

- **Everyday controls:** Automatic control, Matrix artwork, Status, Now playing, refresh/test actions, and Retry state restoration remain available as device controls. The matrix test briefly shows a color and restores the saved state; it is disabled when Matrix artwork is off or while a session or recovery is active. Theme-light test snapshots are saved before the preview, so failed restoration can be retried. Turning Matrix artwork off powers down the WLED matrix while room-light matching continues, which is useful for casual listening.
- **Configuration entities:** The integration puts lower-level tuning switches, selects, numbers, and the fallback color picker in Home Assistant's configuration category. Matrix-only and theme-light-only controls appear only when their corresponding output is selected.
- **Color control:** Fallback color is a configuration-only light entity with an RGB picker and brightness slider; both store settings and do not directly operate a physical light. Select **Fallback brightness source → Use each room light’s brightness** to clear the override. Choose **Use fallback color light brightness** to use the slider value instead (100% when no fixed value was saved). Switching the fallback light off means black/off; switching it back on restores its remembered RGB, including after a Home Assistant restart. Its brightness override is preserved when switched off.
- **Switches:** Matrix artwork and fade-to-black. The main Automatic control switch remains a normal device control.
- **Selects:** Automatic power, Theme color mode, Theme-light transition, Album color adjustments, Matrix transition style, Artwork image fit, Artwork crop position, If playback has no cover art yet, If cover art disappears during a session, Room lights when playback ends, Matrix when playback ends, Fallback brightness source, and When playback is paused. Only controls relevant to selected outputs are created.
- **Numbers:** Matrix transition duration (0.1–5 seconds), Theme-light fade duration (0–10 seconds), Pause at black duration (0–2 seconds), Artwork zoom (100–200%), Artwork blur strength (0–40%), Background brightness (0–100%), Source stabilization (0.3–10 seconds), Playback-end grace (0–300 seconds), and Device warm-up delay (0–60 seconds).

The Status sensor identifies the player reporting paused during its countdown and keeps the last session-end reason after cleanup. Device health lists the specific outputs awaiting restoration. **Retry state restoration** is enabled only while saved state remains pending; automatic reconnect retries continue as before.

Changes are persisted and applied live when safe. Album color adjustments, theme-light transition, and theme color mode refresh room lights from the cached palette. Artwork fit, crop position, zoom, blur, background brightness, and automatic-power changes reapply the current cover when needed. Matrix transition style, fade-to-black, pause duration, and playback-end behavior affect the next relevant event. Source order, ignored player inputs, cover-service order and optional API keys, matrix target, dimensions, segment, and PIN remain in **Configure**. Leave ignored player inputs empty to allow all inputs. Source stabilization, playback-end grace, and device warm-up are live timing controls.

### Cover services

Under **Configure → Artwork**, available even without lighting outputs, set **First cover service** through **Fourth cover service**. A disabled position is skipped; selecting the same service twice does not send duplicate searches. Disable every position, or turn off **Search online for cover art**, to make no online cover requests. Changes apply to the current track when saved. This is the same online-search control as in earlier versions; its entity ID is unchanged.

The player cover appears first. If it is static and both **Animated artwork** and online search are enabled, a background lookup checks the selected services in order for an animated alternative. Static results are skipped while that lookup continues; an actual image with multiple frames is required, even if its filename ends in `.gif`. If no animation is found, a key is missing, or a service fails, the player cover stays in use. An already animated player cover needs no upgrade. This also works for the shared HA Artwork image without physical lighting outputs.

Online requests send the track title, artist, and album to selected services, including when the player already provides a static cover. Missing-key skips, request pacing, and service cooldowns apply to both lookup types. No artwork URL, image bytes, or local player credentials are sent as a search query. Turning off either animation or online search restores the original player cover if a background lookup had replaced it.

| Service | Key | Notes |
| --- | --- | --- |
| MusicBrainz / Cover Art Archive | None | Tries strongly matched releases and release groups, including alternate pressings. Without album metadata, it can resolve the song to its releases through recording search. |
| Deezer | None | Searches the public track catalog and checks title and artist before using an album cover. |
| Last.fm | Required | Uses the API key from your Last.fm API account; the shared secret is not needed. |
| TheAudioDB | Optional | Blank uses the shared free key `123`. A personal key uses your account's access and limits. Album lookup can fill in a track's missing thumbnail. |

New installations try MusicBrainz, Deezer, Last.fm, then TheAudioDB; Last.fm is skipped without a key. Existing installations keep their saved service selection, including Last.fm-only mode, until you choose additional services. TheAudioDB's shared free service has limited catalog access and shared quotas; a missing result can still fall through to another selected provider. See [TheAudioDB's API guide](https://www.theaudiodb.com/free_music_api) for current access levels and limits.

For music with video-style metadata, each service first receives the original metadata. Cleaned queries can normalize decorative letters (such as Fraktur artist names), remove an artist prefix matching the separate artist field, and remove explicit upload labels such as `(Official Video)`, `(Official Animated MV)` or `(Official MV Flipnote)`. For example, artist `𝔭𝔞𝔰𝔰𝔢𝔫𝔤𝔢𝔯𝔭𝔯𝔦𝔫𝔠𝔢𝔰𝔰` and title `passengerprincess - HEADLESS LOUNGE (Official Video)` can retry as artist `passengerprincess`, title `HEADLESS LOUNGE`. A labelled lyric/video upload can also try artist/title credits from the title, so uploader `FM Tender` with `Don't Stop Me Now - Queen (Lyrics)` can search Queen's song. Up to four metadata variants share the existing provider timeout, song cache, and request limits. Playback-position updates do not start another search; normal music-source eligibility checks still apply.

Live recording details are searched first. If that edition has no cover, a final query may use the base song and the same artist, without the live album constraint. Remix, acoustic, remaster, cover, sped-up and slowed labels are protected from that relaxation. Original HA metadata stays unchanged. `online_artwork_lookup.matched_query` shows the successful query and `used_metadata_fallback`; the image and color entities expose it as `artwork_match` for online covers. This makes a general song cover distinguishable from the exact version being played.

All native and online image candidates are decoded before they are accepted or cached. An empty response, HTML error page, corrupt image, or oversized download falls through to the next URL/service. Downloads are bounded while streaming, including when Content-Length is absent; GIF validation bounds frame count and total decoded pixels. Animated GIFs are preserved when a service actually returns one. More services improve cover availability, but cannot guarantee that a catalog supplies an animated cover. A static result is useful for a missing cover, but cannot replace a valid player cover during an animation lookup.

### Artwork and colors in dashboards

The integration device provides **Artwork**, **Artwork colors**, and **Animated artwork**. Their entity IDs depend on the device name and any renames; replace the example IDs below with those shown on your device. No WLED matrix or room lights are required to use them. **Automatic control** must be enabled for new covers to be processed.

**Artwork** serves the prepared cover through HA's native image proxy. Static covers are PNG thumbnails up to 512 pixels; animated-source covers are at most 256 pixels, keep their aspect ratio, and preserve up to 60 animation frames. Exported covers keep their original framing, independently of matrix crop/zoom settings. Opening a card makes no additional cover-service requests. The local picture URL changes when the image bytes change, so a generic card can refresh correctly. Use the entity picture directly rather than saving a proxy token permanently.

A [standard picture entity card](https://www.home-assistant.io/dashboards/picture-entity/) can show the cover:

```yaml
type: picture-entity
entity: image.your_room_artwork
show_name: false
show_state: false
```

**Artwork colors** has the primary color as its hex state, or `No artwork` before a palette is available. It and **Now playing** expose these reusable attributes:

| Attribute | Value |
| --- | --- |
| `rgb_color`, `hex_color` | Primary extracted color as `[R, G, B]` and `#RRGGBB`. |
| `palette_rgb`, `palette_hex` | Up to 16 extracted colors, before room-light adjustments. |
| `theme_colors_rgb`, `theme_colors_hex` | Up to 16 colors using the selected theme mode, dark-color protection, and brightness balancing. With room lights selected, these follow their assignment order. |
| `text_color` | Suggested black or white text for the primary color. |
| `image_entity_id` | The actual Artwork entity ID, including user renames. |
| `source_entity_id`, `artwork_provider` | Player supplying the cover and `player` or the matching online service. |
| `artwork_match`, `artwork_match_description` | Successful online query and a short explanation of inferred artist or general-song fallback. |
| `artwork_media_title`, `artwork_media_artist`, `artwork_media_album_name` | Metadata belonging to the retained cover. Now playing's regular media attributes describe the current track. |
| `is_active`, `playback_state` | Whether this snapshot's source is selected and playing/buffering accepted music, and its reported state. Paused playback has `is_active: false`. |
| `is_current` | Whether the retained cover matches the selected player's current title, artist, and album. |
| `has_artwork`, `is_fallback` | Whether a cover exists, or the exposed color represents the fallback scene. |
| `is_animated`, `source_is_animated`, `source_frame_count` | Exported animation status and original source details. |

For example, these expressions can be used in HA templates and automations, or in cards that support background/color templates:

```jinja
{{ state_attr('sensor.your_room_artwork_colors', 'hex_color') }}
{{ state_attr('sensor.your_room_artwork_colors', 'rgb_color') }}
{{ state_attr('sensor.your_room_artwork_colors', 'palette_hex') or [] }}
{{ state_attr('sensor.your_room_artwork_colors', 'text_color') }}
{{ state_attr('sensor.your_room_now_playing', 'entity_picture') }}
```

The last known image and palette remain available after playback ends, until another cover or an explicit no-art scene replaces them. Use `is_active` for a conditional dashboard background. If the missing-art policy keeps a previous cover during a new song, `is_current` becomes false and the `artwork_media_*` fields still identify that cover. A fallback-color scene exposes its color with `is_fallback: true` and no image; turning outputs off clears the palette. These snapshots are held in memory and start empty after an integration reload or Home Assistant restart.

**Animated artwork** is on by default and can be changed on the device or in Configure's Artwork section. With online search enabled, it also allows the background animation lookup described above. Off cancels that lookup and restores the original player cover after an online upgrade; otherwise it exports a PNG first frame and uploads a single-frame GIF to WLED from the cached cover. An active paused matrix is updated too, while an off matrix stays off. The preference also applies to future covers. WLED transitions between different covers retain their separate settings. A GIF with a nearly black opening frame can use a few representative frames to obtain a stable room palette; room lights do not animate frame by frame.

### Open the active music player from Now playing

Home Assistant does not template a card's tap action. To make **Now playing** open whichever configured player is active, add one conditional card per player. Each card is visible only when **Current source** matches that player's entity ID, and its tap action opens that player's media entity. Replace the example entity IDs with the values from your installation, then duplicate the card for each configured source:

```yaml
type: vertical-stack
cards:
  - type: conditional
    conditions:
      - condition: state
        entity: sensor.music_artwork_lighting_current_source
        state: "media_player.living_room_speaker"
    card:
      type: entity
      entity: sensor.music_artwork_lighting_now_playing
      name: Now playing
      tap_action:
        action: more-info
        entity: media_player.living_room_speaker
```

When another player becomes active, its matching card appears and routes the tap to that media player. The Current source sensor uses the media-player entity ID as its state so duplicate friendly names remain unambiguous; its `source_name` attribute contains the friendly name. The Now playing sensor also exposes the active media-player entity ID for automations.

## Status and diagnostics

Each entry exposes an event-driven **Status** sensor, a **Now playing** sensor, and a dedicated **Current source** diagnostic sensor. Status counts down to session cleanup and exposes `session_end_remaining_seconds`, `session_end_pending`, and `session_end_reason`. Now playing reports the active track and exposes `active_source_entity_id`. Current source uses the media-player entity ID as its state and reports the friendly name, title, artist, album, app, media type, priority position, selection reason, and a list of configured sources with playback and artwork availability. Matrix availability/dimensions, last artwork update, state-snapshot result, and restoration-pending status are available from Status. The integration also provides refresh, matrix-test, and theme-light-test buttons and an automatic-control switch for a temporary manual override. Downloadable diagnostics omit credentials and raw artwork URLs. The `online_artwork_lookup` attributes show the selected service order, whether optional keys are configured, the service that supplied the cover, whether the result was cached, and each attempted service's last result. Last.fm cooldown details remain directly in these attributes; `catalog_services` reports Deezer and TheAudioDB cooldowns. Invalid keys, service errors and missing results are also shown directly in Status while waiting for art. Status keeps its HA state within 255 characters; its `full_status` attribute contains the complete message.

The separate `animation_artwork_lookup` diagnostic section reports the background search for an animated alternative. A static result or no match means the original player cover is kept; it is not a missing-cover failure. The usual `online_artwork_lookup` diagnostics continue to describe searches for a missing or unusable player cover. Both searches reuse results for the current song. Position, volume, and output-state updates do not start another animation lookup, and obsolete results are discarded after source, track, or relevant settings changes. Background requests do not hold up native artwork or playback handling.

Online lookup results and genuine no-match results are reused for the current song until its title, artist, or album changes. Temporary failures such as timeouts, rate limits, and unavailable services can receive one automatic retry after the relevant cooldown, including during an animation lookup. That retry is cancelled when the song/source changes, playback stops, or online lookup is disabled. Position and volume updates reuse the existing result rather than starting another lookup. Returning to an earlier song reuses a successful result for up to 24 hours; a missing result can be retried after five minutes. **Refresh artwork** clears both kinds of lookup cache and retries the current song, but still respects an active service cooldown. A lookup can try album, track, and artist-credit variants; it is one lookup sequence per song, rather than necessarily one HTTP request. API requests are paced across integration entries: at least one second apart for MusicBrainz, Last.fm and Deezer, and 2.1 seconds for TheAudioDB. Rate-limit responses honor `Retry-After`; TheAudioDB waits at least a minute after a rate-limit response.

## How it behaves

### During playback

The integration chooses the highest-priority eligible playing music source first, then resolves artwork or the missing-cover behavior for that source. A lower-priority player does not win merely because it already has artwork. The current source can be held through buffering. Relevant metadata changes settle for 1.5 seconds by default, with a bounded wait during bursts; repeated position/volume updates cannot postpone processing or stop detection indefinitely. The source is checked again before artwork is applied. That reduces stale covers and oscillation when Home Assistant publishes playback state and artwork in separate updates. Artwork is taken from `entity_picture`, `media_image_url`, or Home Assistant's local `entity_picture_local` proxy.

When a new cover is ready, the integration uploads a content-addressed GIF, then tells WLED to activate its Image effect with the selected native transition. File-upload identity and the active physical display are tracked separately: unchanged artwork can reuse a known upload, while reconnecting or changing effects requires activation again. It does not upload temporary transition GIFs. WLED transition support and visual results depend on the firmware build and matrix/effect configuration.

Theme-light updates run independently of matrix output. The integration can therefore provide album-colored room lighting when no matrix is selected or the matrix is temporarily unavailable.

A player is treated as music when it provides cover art or recognizable audio metadata such as a music/audio content type, artist, or album. A player that labels media as generic video needs both track metadata and cover art before it starts a session; once accepted, brief cover-art gaps are handled using the **If cover art disappears during a session** choice. Title-only video is ignored. If an input reports only a generic playing state, outputs stay unchanged until music metadata or artwork appears. This avoids reacting to television inputs that do not identify themselves as audio. If a source has misleading metadata, add its exact `source` value to **Configure → Ignored player inputs**; values are comma-separated and matching ignores capitalization and punctuation (for example, `Product (TV), Product (HDMI1)`). Leave the list empty to use every source.

For audio that has no cover art, **If playback has no cover art yet** can leave outputs unchanged, apply a fallback color to room lights, or turn selected outputs off. The default is to leave outputs unchanged. The matrix stays off during fallback-color scenes. After artwork has appeared in a session, **If cover art disappears during a session** can keep the current scene, apply fallback color to room lights, or turn selected outputs off. Set the color and optional room-light brightness override with the configuration-only **Fallback color** light entity on the integration device; it stores settings and does not control a physical light directly. Use **Fallback brightness source** to choose each room light’s brightness or the fallback light’s slider. When artwork returns, a matrix temporarily switched off by the integration can resume even with automatic power-on disabled, provided it was originally on. A later manual power-on clears that temporary ownership, so a subsequent manual off is respected.

### When playback ends

Two independent controls cover the combinations:

| Control | Choices | New-entry default |
| --- | --- | --- |
| **Room lights when playback ends** | Restore previous color; restore previous color and brightness; keep music lighting; turn room lights off | Restore previous color |
| **Matrix when playback ends** | Restore previous matrix state; keep last artwork; turn matrix off | Turn matrix off |

For example, restore room color **and brightness** while turning the matrix off. Color-only restoration leaves current brightness unchanged. Under either restore choice, a room light that was off before playback is switched off again. Older combined choices migrate without changing their intent. Ending actions are saved before commands run, including per-light brightness restoration and off actions for offline devices. Disabling **Matrix artwork** continues to keep the matrix off through cleanup.

The former combined ending selector is replaced by these two controls. Update dashboard cards that used the old selector to show the relevant new controls.

Paused playback keeps the current cover and colors during the configured grace period. If no configured source resumes before it expires, the end behavior runs; resuming any source cancels pending restoration. This also handles Cast players that remain paused after casting ends while retaining the last album metadata.

State snapshots are captured and persisted before the integration first changes an output. If Home Assistant or the host restarts unexpectedly during a session, the integration attempts to restore the saved pre-session state. Each matrix/light is handled independently, so an unavailable or slow device does not hold up healthy outputs. Failed restores are kept in a durable queue and retried on availability/power-on events and periodically; snapshots are not discarded just because a device stays offline. By default, a device is given 12 seconds to settle after it becomes available or switches on before the integration sends commands; adjust **Device warm-up after power-on or reconnect** between 0 and 60 seconds. The delay applies to any configured light or matrix individually. Until an offline device returns, its original state cannot be restored; once it does, it receives the configured warm-up delay, restoration is retried before new artwork overwrites it, and the current cover/theme is reapplied if music is still playing. A matrix that missed its playback-end off action receives that action after reconnecting. Manual changes to the same devices during music playback can still be overwritten when the saved snapshot is restored. Configure rejects a matrix also selected as a theme light, lights controlled by another entry, and the generated fallback-color control selected as a physical output.

## Settings worth knowing

- **Automatic power** — choose whether the integration can power on all selected outputs, only the matrix, only theme lights, or none. With one output type selected, the dropdown offers just power on or never power on.
- **Theme-light transition** — choose to change colors instantly, fade directly between album colors, fade to black in sync with matrix fade-to-black, or use each light's default. The **Theme-light fade duration** number applies to timed fades; device-default mode leaves timing to the light.
- **Album color adjustments** — choose none, lift near-black colors, balance color brightness, or apply both adjustments. This replaces two separate switches while preserving their previous settings.
- **Room lights / Matrix when playback ends** — choose restoration, keeping the scene, or off separately. Set room color-and-brightness restoration independently of matrix power.
- **Artwork image fit** — crop to fill, show the whole cover on black, use a blurred background, fill margins with a dominant cover color, or mirror the cover edges. The adjustable blur style has separate blur and background-brightness sliders; crop focal point and zoom help frame off-center artwork.
- **Transition style = Shuffle** — picks a different native WLED transition per cover change, avoiding an immediate repeat when possible.
- **If playback has no cover art yet** — leave outputs unchanged, use a fallback color for sources with audio metadata, or turn selected outputs off. The safe default is to leave outputs unchanged; black means off and brightness `0` leaves the device brightness alone.
- **If cover art disappears during a session** — keep the current scene, apply fallback color to room lights with the matrix off, or turn outputs off. This only applies after artwork has appeared in the current session. Use **Ignored player inputs** for source values that should never start or continue a session, or leave that optional field empty to allow all inputs.
- **Source stabilization** — use 1.5 seconds initially; try 2–3 seconds for players that publish cover metadata slowly. Higher values reduce stale transitions but make track changes appear later. Position and volume changes do not restart this delay.

Theme color modes include Artwork palette, Dominant + contrast, Dominant color, Vibrant accents, Complementary accent, Analogous flow, Cinematic, and Monochrome tones. Each derives from the artwork; no unrelated mood preset changes your other preferences.

## Troubleshooting

- **No artwork appears:** in Developer Tools → States, inspect the selected media player and confirm its state is `playing`. Check for `entity_picture`, `media_image_url`, or `entity_picture_local`. For players that label music as generic video, confirm both track metadata and a cover-art URL are available; the Current source sensor explains when it is waiting to confirm music. The Fallback color picker and brightness slider are on the integration device; the default leaves outputs unchanged.
- **The Image effect cannot be found:** confirm that the WLED firmware exposes an `Image` effect and that GIF/PixelForge matrix support is enabled.
- **A brief glitch appears before a matrix fade or image change:** this is not an intended transition effect. The integration fades through black by changing the WLED segment from the Image effect to Solid, then back to Image; some firmware/effect combinations can briefly glitch while the Image effect is restarted. For a cleaner change, turn off **Fade to black before showing each new cover** and use a direct native **Fade / crossfade** transition. WLED exposes transition time in its [JSON API](https://kno.wled.ge/interfaces/json-api/) and treats effect changes as their own transition kind in the [firmware](https://github.com/wled/WLED/blob/main/wled00/FX.h), so seamless results can still depend on the active effect and build. Reduce duration or try another transition if needed.
- **The matrix dimensions are wrong:** disable auto-detection and set the correct manual width and height; check the 2D matrix configuration in WLED.
- **Theme lights do not change:** ensure theme lights are selected and support an RGB-type color mode. Set **Automatic power** to never power on if you only want already-on lights recolored.
- **The matrix is not restored:** choose **Matrix when playback ends → Restore previous matrix state**, and confirm the selected WLED matrix is available and the integration is allowed to control it.
- **A lower-priority player has art but nothing changes:** the preferred eligible player owns the scene. Check its metadata and cover-service results in Current source and Status, or change player order in Configure.
- **Cover service failed temporarily:** one automatic retry follows its cooldown. Genuine misses remain cached for the song; use **Refresh artwork** to try again manually. Active service cooldowns still apply.
- **The player keeps an old image at the same URL:** **Refresh artwork** clears native image and online lookup caches before requesting the cover again.
- **A player cover stays static:** enable both **Animated artwork** and **Search online for cover art**, select cover services, and check `animation_artwork_lookup` in diagnostics. A service must return an actual animation; a static cover or a single-frame GIF leaves the original image in use. Last.fm needs an API key, but not its shared secret.

## What changed in 0.16.2

- Display the player's cover immediately, then look for an animated alternative in the background when online search and Animated artwork are enabled.
- Continue past static service results and replace the player cover only with validated multiframe artwork. No match or service errors leave the original cover in use.
- Cache animation lookups for the current song, share service limits, and cancel obsolete work. Expose their results separately in `animation_artwork_lookup` diagnostics.
- Restore the original player cover when animation or online search is turned off after an upgrade.
- Rename the existing online-search control to **Search online for cover art** to explain its expanded purpose; saved settings and entity IDs remain unchanged.

Older release notes are in [CHANGELOG.md](CHANGELOG.md).

## Development and validation

`manager.py` coordinates playback, update scheduling, and outputs. Small modules now own source event filtering and player priority (`source_flow.py`), matrix upload/display state (`matrix_control.py`), native and online download/validation bounds (`image_download.py`), and durable session-ending plans (`session_journal.py`). Other components cover provider queries, metadata normalization, artwork export, WLED requests, image fitting, and theme palettes.

The existing automated suite is retained. This release received Python syntax, JSON, and documentation consistency checks; automated tests were not run or added for this work. No live Home Assistant or physical WLED testing was performed.

`README.md` and `CHANGELOG.md` at project root are the documentation sources. Run `python3 tools/sync_component_docs.py` after editing them to refresh the copies shipped inside the component folder.

Entries from v0.13.x that selected multiple matrices are migrated to the first selected matrix; add separate entries for additional displays. Existing color-adjustment and ending preferences are preserved. The internal integration domain/folder remains `wled_album_art`.
