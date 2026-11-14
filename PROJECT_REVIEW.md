# Project review implementation — updated 24 October 2026

Implemented for **0.16.0**, following the review of 0.15.31. This report records the changes made; it is not a live Home Assistant or WLED validation report.

### Follow-up improvement in 0.16.2

Static player artwork now appears before a separate background search checks selected cover services for an animated alternative. The upgrade requires validated multiframe artwork; static results, unavailable optional keys, and lookup failures keep the original image. Already animated player covers skip this search. The task runs outside the playback lock, caches results for the current track, shares provider request limits, and rejects obsolete results when playback, the source, or settings change. One cooldown retry is allowed for temporary failures. Disabling animation or online search restores the original player cover after an upgrade. The existing online-search control is now named **Search online for cover art**, and its help explains the metadata sent for either missing-cover searches or animation upgrades. Separate `animation_artwork_lookup` diagnostics distinguish a missing animation from a missing cover. The 0.16.1 matrix recovery correction remains included.

### Follow-up correction in 0.16.1

A missing-cover recovery exposed a false device warm-up: the fade-to-black command powered an off matrix on, its HA state event started the reconnect delay, and the next readiness check stopped before loading the image. Off matrices now skip the redundant black fade and activate artwork directly. Expected software power-on confirmations skip warm-up and preserve temporary fallback ownership, while actual reconnects retain their delay. Late confirmations do not invalidate an already activated image. Status preserves the specific skip reason and exposes real warm-up time. This correction received static checks and code-path review; no automated or physical-device tests were run.

## Playback and device fixes

| Reviewed problem | Implemented change |
| --- | --- |
| Continuous player position updates restart stabilization forever | Compare relevant playback/metadata fields, ignore position and volume churn, and bound how long a burst can postpone the scheduled update. Stop/paused transitions can start their grace timer promptly. |
| An unchanged image fingerprint hides a WLED reboot or effect change | Separate uploaded-file identity from physical display validity. Reconnection invalidates file certainty; display changes require activation even if source image bytes are unchanged. |
| HTTP 200 responses containing HTML, empty bytes, or damaged images block fallbacks | Stream-bound and decode-check native and online candidates before accepting or caching them. Try the next native URL or online service on failure. Image decoding runs outside the HA event loop. |
| An old online replacement survives a service-policy change | Record the replacement's real origin and provider settings revision; invalidate retained online replacements when service settings change or online lookup is disabled. |
| A missing-cover scene switches a matrix off permanently when automatic power-on is disabled | Track temporary integration-issued power changes. Permit artwork recovery only for a temporarily disabled matrix that was originally on; later power-on clears ownership so a subsequent manual off is respected. |
| Preferred player loses to a lower-priority player with native artwork | Select the highest-priority eligible playing music source before resolving its artwork or no-art policy. |
| A transient lookup failure remains pinned for the entire song | Keep genuine misses cached; schedule one automatic retry after transient cooldowns. Cancel the scheduled retry when playback/source/settings no longer justify it. |
| Resumed playback can lose a race with a queued ending action | Invalidate stale ending tasks, recheck playback after saving the ending plan, and restore the durable original journal before allowing further commands when a plan was superseded. |
| An upload can power a matrix back on after a manual off | Recheck power permission, availability, and reconnect delay after image preparation, upload, and fade waits. |
| Refresh reuses a cached image at the same player URL | Explicit refresh clears both native download and online lookup caches. Service cooldowns remain in effect. |

## Everyday controls and configuration

- **Room lights when playback ends** and **Matrix when playback ends** are independent Configure and device-select controls. Restoring room color/brightness while turning the matrix off is now expressible. Existing combined choices normalize into equivalent policies.
- Playback-end actions become a durable plan before output commands run. Per-light brightness decisions and offline-device off actions are stored with snapshots so later configuration changes do not alter a pending restore.
- **Artwork** always includes cover-service order, online lookup, optional API keys, and animation settings, including entries used solely for dashboard artwork and colors.
- The **Fallback color** light remembers its last nonblack RGB across restarts. Switching it off preserves its brightness override. **Fallback brightness source** explicitly selects each room light's own brightness or the color light's brightness slider.
- Configure rejects a matrix also selected as a room light, overlapping ownership with another entry, and a generated configuration light selected as a physical room-light output. Conflict messages identify the relevant entity.
- Source-priority help now states the same policy as the implementation. Artwork match descriptions explain inferred artist credits and general-song artwork. Status keeps its state within HA's limit and provides the full text in an attribute.

## Cover lookup and animation

- MusicBrainz can try multiple strongly matched releases instead of stopping at the first pressing, with release-group covers as alternatives. Missing album metadata can use a strongly matched recording to find its actual album/release. Attempts remain bounded.
- Native and online downloads share a streaming byte limit and image validation. Animated source validation bounds frame count and total decoded pixels, rather than trusting the first frame alone.
- A nearly black opening GIF frame can use a few representative frames for one stable theme palette. Room lights do not change color on every animation frame.
- Animated artwork remains enabled by default. It can find an animated alternative to a static player cover when online search is enabled. Disabling it restores the original player cover after such an upgrade; otherwise it uses a static first frame for the exported artwork and WLED, independently of the palette sampling improvement.

## Refactoring and documentation

Small responsibilities were extracted rather than rewriting the whole coordinator:

- `source_flow.py`: relevant source changes and player-priority decisions. The coordinator applies the bounded update schedule.
- `matrix_control.py`: typed matrix state, upload/display validity, and temporary power ownership.
- `image_download.py`: shared streaming bounds and safe image decoding.
- `session_journal.py`: construction of independent, durable playback-end plans.
- `artwork_models.py`: named artwork and fallback-scene identity fields at the artwork boundary.
- `const.py`: shared legacy-to-independent ending-policy normalization used by initialization, live changes, and Configure.

README now begins with setup and daily controls. Historical releases stay in CHANGELOG. Root README/CHANGELOG are authoritative; `tools/sync_component_docs.py` refreshes their packaged component copies.

## Validation and practical limits

Python syntax, JSON loading, relative import names, mirrored translations, documentation consistency, and traced code paths were checked. **No automated tests were added or run for this work. No live Home Assistant or physical WLED testing was performed.** Existing fixtures and structural assertions were updated for valid image decoding, the extracted modules, the replacement ending controls, and the new version.

The coordinator still owns substantial orchestration. Further extraction should follow behavior coverage rather than a single large rewrite. Firmware-dependent transition glitches, incomplete provider catalogs, and unavailable physical devices remain external constraints; the controls, diagnostics, and durable recovery paths provide the corresponding choices and visibility.
