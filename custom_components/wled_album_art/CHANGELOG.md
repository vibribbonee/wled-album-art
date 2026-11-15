# Changelog

## 0.16.3

- Correct Home Assistant integration metadata and use Home Assistant’s bundled Pillow dependency.
- Clarify cover lookup, playback controls, and display options in the README.

## 0.16.2 — Animated alternatives without delaying player artwork

- Display usable player artwork first. When Animated artwork and online cover search are enabled, look for an animated alternative in the background without blocking playback processing or native artwork updates.
- Search configured services in order and continue past static images, including single-frame GIFs. Replace player artwork only with validated multiframe artwork; keep the original for misses, missing optional keys, or service errors. Already animated player covers need no upgrade.
- Cache animation lookups separately from missing-cover searches, preserve shared request pacing and cooldowns, and allow one cooldown retry for temporary failures. Discard stale results after source, playback, and relevant setting changes.
- Retain the original player cover and restore it when animation or online search is turned off after an upgrade. Explicit Refresh artwork clears both lookup caches.
- Expose background lookup results in `animation_artwork_lookup` diagnostics without presenting a missing animation as an artwork failure.
- Preserve the current-song animation cache through pauses and native artwork URL refreshes. Report the actual artist/title credit when Last.fm's internal metadata fallback finds the image.
- Rename the existing control to Search online for cover art without changing its setting key or entity ID. Explain that metadata can be sent to selected services even when the player already supplies a static cover. No new toggle is required.

## 0.16.1 — Resume matrix artwork promptly after missing covers

- Skip fade-to-black when the matrix is already off or recovering from the integration's missing-cover off action. Load the image and power on in the same request.
- Match a short-lived software power-on intent to its Home Assistant state confirmation. Do not start reconnect warm-up or clear temporary fallback ownership for that confirmation; genuine reconnects and external power-on retain the configured delay.
- Preserve a successfully activated image when its expected power-on confirmation arrives late, avoiding a redundant same-cover fade.
- Clear pending power-on intent for explicit matrix opt-out, missing-cover off actions, failed activations, session cleanup, and loss of availability.
- Keep specific skip reasons, show the remaining device warm-up delay, and expose fallback power ownership in matrix diagnostics.

## 0.16.0 — Reliable playback, independent ending controls, and artwork recovery

- Position and volume updates no longer postpone artwork or playback-end handling; source priority now selects the player before resolving its artwork.
- Restore room brightness and turn the matrix off independently. Durable ending plans retain intended actions for offline devices.
- Invalidate stale playback-end tasks and recheck playback after saving an end plan. Restore original journal contents before allowing commands when playback supersedes a saved plan.
- Recheck matrix power permission, reconnect delay, and availability after preparation, upload, and fade waits; respect equivalent changes to room lights before sending prepared commands.
- Reconnects reactivate artwork, and matrices can recover from an integration-issued fallback off without overriding later manual power choices.
- Decode and stream-bound image candidates before caching; fall through from broken native covers; invalidate online replacements when provider settings change.
- Keep cover-service settings available for dashboard-only setups, preserve the fallback RGB across restarts, add a brightness-source selector, and reject conflicting lighting assignments.
- Try alternate MusicBrainz releases and recording-derived albums; automatically retry transient lookup failures once; improve palettes for GIFs that open on black.
- Extract scheduling, matrix state, shared image validation, and ending-plan helpers. Surface complete Status text and readable cover provenance.
- Make Refresh artwork clear both native-download and online-lookup caches, including unchanged player URLs.
- Replace the former combined ending select with independent room-light and matrix controls; existing saved policies are preserved. Dashboard cards using the former select should be updated.

## 0.15.31 — More video titles, uploader credits, and live-cover fallbacks

- Clean Official Animated MV and Official MV Flipnote labels, infer artist/title orders only for labelled uploads, and retain provider matching checks.
- After exact live-version lookup misses, allow a base-song cover by the same performer. Preserve remix/acoustic/remaster/cover/sped/slowed edition labels.
- Bound metadata variants to four within the existing provider timeout. Cache successful query details and expose them in lookup diagnostics and artwork attributes.

## 0.15.30 — Covers for styled artists and video-style titles

- Add one conservative cleaned-metadata fallback after an original metadata lookup has no cover, shared by MusicBrainz, Last.fm, Deezer, and TheAudioDB.
- Apply Unicode compatibility normalization to decorative artist/title lettering; remove a title's artist prefix only when it matches the reported artist, and strip a whitelist of upload-only video/audio/lyric labels.
- Preserve live, remix, acoustic, and remaster titles. Keep player-facing metadata unchanged and use the existing song cache, pacing, cooldowns, and total provider timeout.
- Normalize Unicode compatibility characters before case folding catalog match keys so uppercase decorative lettering compares consistently.

## 0.15.29 — Reusable artwork, palette data, and optional animation

- Add a native Artwork image entity backed by cached, bounded thumbnails and HA's image proxy, with content-based URL cache busting and no raw provider URLs.
- Add an Artwork colors sensor and expose colors/picture on Now playing. Publish RGB/hex palettes, adjusted theme colors, readable foreground color, cover metadata, original animation details, fallback state, and active/current flags.
- Add a default-on Animated artwork switch and Configure option. Prepare only the first frame for WLED and the exported image when disabled; reprocess cached bytes without new cover lookups, including paused-session matrices that remain on.
- Prepare palette data even without theme lights, and support entries with no lighting outputs. Retain the last snapshot after playback ends and mark activity separately; replace it on explicit fallback scenes.
- Preserve media-player metadata during theme-light readiness checks by avoiding a loop assignment that overwrote the selected player state.

## 0.15.28 — More cover sources and selectable fallback order

- Add Deezer public catalog search and TheAudioDB album/track search, including album-ID lookup when track artwork is absent. TheAudioDB can use the shared free key or an optional personal key.
- Replace fixed service-order presets with four priority dropdowns supporting disabled positions and deduplicated services. Preserve each legacy preset exactly and apply changes live.
- Validate track title and artist on catalog candidates, rank matching album results first, and retain mix/live edition names when matching. Keep failed providers from interrupting the remaining service chain.
- Pace requests and share cooldowns across entries, honor service retry guidance, redact the new key, and report safe per-service results and cooldowns. Reuse the existing current-song cache and animated-image pipeline.
- Check each online image redirect before following it, with bounded redirects and downloads.

## 0.15.27 — Last.fm image compatibility and quieter lookups

- Accept the `lastfm-img.freetls.fastly.net` CDN returned by Last.fm, including animated GIF images, while retaining a restricted image-host allowlist.
- Reuse successes and misses for the current song, serialize concurrent lookups, and show Searching only when attempting a provider request. Release the current-song cache pin when playback ends or the selected track changes, including songs with player-provided art.
- Pace Last.fm API requests to one per second across integration entries. Share rate-limit and service cooldowns by API-key fingerprint, honor numeric and HTTP-date `Retry-After` values, and stop retrying rejected keys until a key change or explicit refresh. Keep active service cooldowns in force during manual refresh.
- Report safe cooldown diagnostics and add regression coverage for repeated song updates, concurrent lookups, shared cooldowns, manual recovery, and Last.fm CDN GIF downloads.
- Preserve the summed source-frame delays when sampling long GIFs to 60 frames, including the correct final-frame hold.

## 0.15.26 — Last.fm lookup recovery and visible errors

- Expose Last.fm API errors, HTTP status, missing keys and connection failures in Status and safe lookup diagnostics, including API errors returned with HTTP 403. Clarify that cover lookup does not use a shared secret.
- Continue from failed album images to track artwork, and try bounded metadata variants for combined artist and featured-performer credits after exact lookups fail. Preserve live/remix edition names.
- Expire unsuccessful lookups after five minutes and make Refresh artwork clear the online lookup cache.
- Add provider response and recovery regression tests, and update older structural checks for the current dropdown controls.
- Fix contain/black-bar image fit: resize the foreground cover before centering it on the matrix canvas.

## 0.15.25 — More missing-cover sources and optional input filters

- Make **Ignored player inputs** optional; leave it empty to allow every player input.
- Add Last.fm as a second missing-cover source, with configurable provider order and an optional API key. MusicBrainz/Cover Art Archive remains key-free.
- Fall through on provider misses and failures, include provider settings in the bounded lookup cache, and redact the Last.fm key from diagnostics.
- Preserve animated GIFs returned by player artwork or lookup providers, up to 60 sampled frames. WLED playback requires the v0.16 Image effect.

## 0.15.24 — Find missing covers and finish matrix cleanup

- Turn off every selected matrix at playback end when requested, including matrices without a session snapshot. Replace older queued restores for a target when a newer explicit end action is chosen.
- Add an online missing-cover lookup using MusicBrainz and the Cover Art Archive, with a live opt-out switch, caching, a strong-match threshold, and the required MusicBrainz request throttle. The configuration explains that track title, artist, and album are sent to those services.
- Preserve up to 60 frames from animated player or Cover Art Archive GIF artwork when preparing the WLED file.

## 0.15.23 — Reliable artwork handoff and clearer source status

- Fix a malformed artwork race check that could abort valid cover updates.
- Try the player's regular artwork URL when its Home Assistant local proxy URL fails.
- Keep missing-art history bound to the same player input and video title; explain when a video-tagged track is waiting for a cover.
- Preserve the scheme for protocol-relative cover URLs and prevent stale track metadata from applying after a source change.
- Use the media-player entity ID as the Current source sensor state so dynamic cards remain unique when players share a friendly name.

## 0.15.22 — More reliable source handling and diagnostics

- Keep artwork history per media player so a separate source cannot inherit another player's music session.
- Normalize single or multiple selected entities consistently, including older saved entries.
- Include album, app, and media type in source diagnostics; distinguish video without music metadata from missing artwork.
- Preserve the manager if Home Assistant cannot unload all entity platforms.

## 0.15.21 — Jellyfin metadata and unified fallback control

- Accept artwork and clear artist/album metadata from sources that label music as generic `video`, while continuing to ignore title-only video playback.
- Check and fetch Home Assistant's local `entity_picture_local` artwork proxy alongside the standard artwork attributes.
- Move the optional fallback brightness override to the **Fallback color** light entity's brightness control.

## 0.15.20 — Safer artwork detection and live fallback controls

- Require artwork or recognizable audio metadata before treating a source as music; remember when artwork has appeared during a session.
- Default no-art playback to leaving outputs unchanged, preventing false starts from generic playing states.
- Add an optional comma-separated source/input ignore list with case- and punctuation-insensitive exact matching.
- Add a live fallback-color picker; fallback scenes keep the matrix off.

## 0.15.18 — More artwork framing choices

- Add dominant cover-color and mirrored-edge backgrounds, plus an adjustable blurred background.
- Add live crop focal-point and zoom controls, along with blur-strength and background-brightness sliders.
- Reapply the current cover when any artwork-fit tuning changes.

## 0.15.17 — Audio-only playback and reliable session cleanup

- Support active playback without cover art using a configurable solid fallback color, output-off behavior, or wait-for-artwork mode. Add a color picker and optional 0–100% brightness override; zero leaves device brightness unchanged.
- Send the configured matrix power-off command at session end even when Home Assistant reports a stale off state.
- Default new or unconfigured matrix entries to restore room color and power off the matrix at session end; preserve existing saved end-behavior choices.

## 0.15.16 — Reliable matrix-off override

- Send a device power-off command for explicit Matrix artwork opt-out even when Home Assistant's cached light state says off.
- Retry the off request after WLED reconnects while the override remains disabled, and surface power-off failures in Status and Device health.

## 0.15.15 — Playback clarity and restore recovery

- Identify the paused player during the playback-end countdown and retain the reason/source of the last completed session.
- Persist theme-light test snapshots before changing lights and use the normal durable restore queue after the preview.
- Add a recovery retry action and identify which configured outputs still need their saved state restored.
- Clarify Matrix artwork as a quick casual-listening control; room-light color matching remains active when matrix output is disabled.
- Centralize construction of the versioned recovery journal so test and playback restore paths share the same record shape.

## 0.15.14 — Clearer settings and WLED transition guidance

- Combine automatic power, theme-light transition, album-color adjustment, and playback-end restoration settings into focused dropdowns while preserving existing options for migration.
- Add soft, medium, and strong blurred-background artwork fits and keep the theme-light fade duration adjustable.
- Document that fade-through-black changes the WLED segment effect and can briefly glitch on some firmware/effect combinations; recommend a direct native fade for a cleaner transition.
- Document dynamic native Now playing cards that open the configured active player.

## 0.15.13 — Player navigation and matrix preview

- Add a **Now playing** sensor with active player and track details, and document native conditional cards that open the active media player.
- Add a safe **Test matrix** button that captures and restores the WLED state; failed restores are retained in the recovery journal.
- Move artwork download limits and caching out of the session manager, and separate countdown updates from other entity notifications.

## 0.15.12 — Everyday matrix output control

- Add a normal **Matrix artwork** switch that independently enables or disables album art on the selected WLED matrix. Turning it off powers down the matrix while room-light color matching continues.
- Preserve an explicit matrix-off choice during session restoration and startup recovery, and reapply the current cover when matrix artwork is enabled during playback.
- Promote the live Status sensor to the main device controls, add a compact dashboard recipe, and simplify duplicate setup steps.

## 0.15.11 — Grouped settings and visible session timing

- Split options into playback/output selection followed by output-specific Matrix display, Room lighting, and session-end settings. Unused output settings are hidden and their previously saved values are retained.
- Add an explicit pause policy. The default ends the session after the configured grace period; an optional hold mode preserves the room scene until playback resumes.
- Publish a live session-end countdown in the status sensor and expose pending state, reason, and remaining seconds as attributes.
- Categorize low-level tuning entities as configuration controls and only create matrix/theme controls when those outputs are selected.

## 0.15.10 — Restore after lingering paused playback

- Keep the current artwork and room colors during the configured playback-end grace period after a player pauses.
- Run the configured end behavior if no configured source resumes through the grace period; resuming playback cancels it.
- Clarify that Cast players may retain album metadata after casting ends, and that session activity follows playback state rather than artwork metadata.

## 0.15.9 — Better transition UX

- Remove the redundant playback-end choice that left the matrix powered on at black; the matrix-off option is clearer and less wasteful. Existing saved `black` selections migrate to matrix-off behavior.
- Add a dedicated “Fade theme lights with matrix” switch. When matrix fade-to-black is enabled, selected theme lights fade to black during cover changes, then fade into the new album palette. It has no effect when matrix fade-to-black is disabled.
- Update English translations, documentation, and regression coverage.

## 0.15.8 — Keep dashboard tuning explicit

- Remove the bundled Lighting mood selector because choosing a preset overwrote eight separate settings at once and Custom did not restore prior values.
- Keep all individual switches, color modes, transition styles, and timing controls available for direct tuning.
- Add regression coverage to ensure bundled presets do not return without an explicit, reversible design.

## 0.15.7 — Timing controls and room-wide playback-end behavior

- Add live dashboard timing controls for source stabilization, playback-end grace, and device warm-up delay.
- Reword the playback-end dropdown to describe the complete room-lighting outcome.
- Add keep-all-lighting and turn-matrix-off outcomes, while preserving the legacy values and deferred per-device recovery for matrix actions.
- Add three curated lighting moods (Calm / cinematic, Balanced, Energetic / vivid) plus automatic Custom detection; these tune artwork color modes and track-change transitions rather than claiming beat synchronization.
- Update translations and add tests for the new controls and behavior mapping.


## 0.15.6 — Dashboard behavior toggles and more live tuning

- Add six dashboard switches for matrix auto-power-on, fade-to-black, theme-light auto-power-on, near-black color protection, theme spectrum brightness balancing, and theme-light brightness restoration. The existing Automatic control switch remains the master pause/resume switch.
- Add live select entities for artwork image fit and playback-end behavior, plus a number entity for the optional pause at black between covers.
- Changes persist in config-entry options and apply live without a full integration reload. Image-fit and matrix-power changes reapply the current cover; theme color processing/auto-power-on changes refresh theme lights from the cached palette.
- Add translated entity names/state labels and structural regression coverage for all new controls.

## 0.15.5 — Live dashboard tuning controls

- Add four Home Assistant entities that can be placed directly on dashboards: **Theme color mode**, **Matrix transition style**, **Matrix transition duration**, and **Theme-light transition duration**.
- Persist control changes in config-entry options while applying these values live; no full integration reload is needed for these four settings.
- Switching theme color mode recolors the current album from its cached palette, without refetching the cover or re-uploading it to the WLED matrix.
- Expose instant matrix cuts as a selectable transition style and translate control names/options in the English UI.
- Add structural regression checks for the control platforms, live-option handling, and translation metadata.

## 0.15.4

- Made post-setup tuning easier to discover from the Configure panel and README.
- Added focused field guidance for transitions, image fit, color style, source stabilization, warm-up, and playback-end behavior.
- No runtime behavior or defaults changed in this release.

## 0.15.3

- Add an event-driven **Device health** diagnostic sensor with per-matrix and per-theme-light state, last result, error, and restoration information.
- Clarify source priority in Configure: the ordered list is evaluated top-to-bottom, and the Current source sensor explains the selection.
- Keep the diagnostic view URL-safe; report device state and errors without exposing artwork URLs.
- Add regression checks for the device-health entity, event-driven updates, and source-priority guidance.

## 0.15.2 — Visible source diagnostics

- Add a dedicated **Current source** diagnostic sensor showing the friendly name of the selected media player, with a useful transitional state while source selection/artwork is settling.
- Expand status attributes and downloadable diagnostics with source friendly name, playback state, priority position, track/artist, selection rationale, and a safe per-source candidate list (entity ID, state, artwork presence, and eligibility). Raw artwork URLs are never included.
- Keep the existing status sensor's `active_source` and priority fields for compatibility.
- Add structural regression tests for the sensor setup and detailed source diagnostics.


## 0.15.1 — Warm-up timer setup fix and clearer wording

- Fix the reconnect warm-up timer callback: Home Assistant's `async_call_later` supplies its own timestamp argument and does not accept an arbitrary positional `entity_id`; bind the entity ID with `functools.partial`. This prevents setup from failing when a previously available device needs a warm-up timer.
- Make the warm-up setting description general: its per-device delay applies to any selected light or matrix, not just Wi-Fi lights or LED curtains.
- Add a regression check for the timer callback signature and update release version metadata.


## 0.15.0 — Independent device recovery and more responsive updates

- Prevent a matrix with an unresolved original-state snapshot from being overwritten by newer artwork. It resumes after its own restore succeeds; healthy matrices and room lights continue independently.
- Add per-device 30-second retry backoff for reachable devices that reject restoration, while an availability/power-on event clears the backoff after the configurable warm-up delay.
- Queue a durable black-screen end action for a matrix that is offline when playback stops, then apply it when that matrix reconnects. Fade-to-black outputs run concurrently, and status distinguishes completed outputs from pending offline actions.
- Tighten local WLED request timeouts (6 seconds for JSON API calls, 12 seconds for image upload, and 5 seconds for best-effort filesystem cleanup) to reduce the impact of dead or slow devices.
- Report when an end-of-session action has completed on available devices but remains pending on offline targets.

- Preserve durable original-state snapshots until each disconnected device is successfully restored; retry when the entity returns and periodically, without an expiry that silently abandons restoration.
- Restore matrix state, theme-light state, and apply theme colors concurrently per device. Theme-light service calls are bounded to 15 seconds so a slow curtain/bulb cannot serialize every other light or hold the session lock forever.
- Add a configurable 0–60 second device warm-up delay (default 12 seconds). Apply it after `unavailable`/`unknown` → available transitions and `off` → `on` power-on events. When the delay expires, invalidate the cached cover/color key so the current artwork is resent even if the song has not changed.
- Retry failed matrix and theme-light updates after a cooldown, and expose per-theme-light status details in diagnostics.
- Improve **Fit image over blurred artwork background**: strengthen the blur and lift the background color so letterboxed areas are visibly artwork-derived rather than resembling black bars. Explain that this mode only differs when source and matrix aspect ratios differ.
- Remove stale timeout-based recovery diagnostics and documentation; offline snapshots are durable restoration work, not a reason to pause healthy outputs.
- Add regression coverage for visible blurred bands, device warm-up, parallel/bounded restoration, and persistent recovery queues.

## 0.14.3 — Bounded recovery and broader integration name

- Rename the visible integration to **Music Artwork Lighting** because it controls ordinary Home Assistant lights as well as WLED matrix outputs. Keep the internal `wled_album_art` domain/folder for upgrade compatibility.
- Bound state-recovery waits to 60 seconds. After the grace period, discard any still-unresolved saved snapshots so they cannot block playback on healthy lights; log which entity was skipped and expose the reason for matrix diagnostics. This is an explicit trade-off: a device that cannot be restored within the timeout may not return to its exact pre-session state.
- Schedule a coordinator retry when the recovery grace period ends, and cancel the recovery timer when the entry unloads.

## 0.14.1 — Preserve existing lighting preference

- Do not force-reset spectrum balancing for existing entries during migration. The previous release changed this setting based on an unconfirmed assumption about color appearance; existing user choice is now preserved.
- Keep spectrum balancing disabled by default for new entries, while leaving the option available in Configure.
- Add a regression check to ensure config-entry migration does not overwrite the user's spectrum-balancing setting.

## 0.14.0 — Single-output entries, crash recovery, and event-driven status

- Return to one matrix per integration entry, while keeping matrix output optional for album-themed room lighting only. Each matrix entry now has fully independent segment, size, fit, transition, preset-protection, and end behavior settings.
- Migrate legacy entries that had several matrices to the first configured matrix. Add separate entries for the remaining displays after upgrading; a theme-only entry can leave its matrix target blank.
- Restore the original album-color brightness character: spectrum balancing is disabled by default and existing entries are reset to that baseline during migration. It remains available as an explicit option.
- Persist original WLED and theme-light snapshots before changing devices. Attempt recovery after an unclean Home Assistant/host restart, retain snapshots when a device is unavailable, and retry restoration on relevant state changes rather than dropping failed restores.
- Replace the status sensor's 10-second polling with event-driven updates from the coordinator.
- Extend regression coverage for single-target migration, theme-only operation, journal persistence and non-polled status updates.

## 0.13.1 — Multi-matrix reliability and diagnostics

- Snapshot available WLED outputs concurrently and skip known-unavailable targets during startup, so an offline matrix does not cause serial timeout delays for healthy displays.
- Retry missing state snapshots concurrently when a target becomes eligible during an active music session.
- Add per-matrix result, last error, last update time, snapshot success, and dimension-source fields to status diagnostics.
- Make aggregate status counts use the selected matrix total, making skipped/offline outputs visible instead of counting only the currently-ready subset.
- Redact HTTP URLs from user-facing error diagnostics to avoid exposing signed artwork links or query tokens.
- Restore the saved WLED preset ID along with brightness, power and segment state when the session ends.
- Add regression checks for the startup/version contract, concurrent snapshotting, and per-matrix diagnostics.


## 0.13.0 — Multi-matrix single-entry support

- Replace the single-target selector with an ordered multi-select of WLED matrix lights during setup and in Configure options.
- Coordinate a single music-source priority/session pipeline across multiple displays; each matrix gets its own WLED client, upload/cleanup namespace, status details, dimension detection, artwork fingerprint, and pre-session state snapshot.
- Restore or clear each matrix independently when playback ends, a manual override is enabled, or the integration unloads. The optional Text-preset guard applies to the first selected matrix without blocking other outputs. Retry state snapshots for outputs that reconnect mid-session, and preserve any original managed artwork file needed for restoration.
- Preserve backwards compatibility with existing single-matrix entries and let an explicit empty target list disable matrix output without accidentally restoring a legacy target.
- Reject selecting a matrix already managed by a different integration entry.
- Matrix transition, segment, fit mode and manual fallback dimensions are shared across selected displays; auto-detected dimensions are independent per matrix. Detect dimensions concurrently so one offline device cannot serially delay every other display. Update the config-entry title when the matrix selection changes.
- Add regression coverage for target-list normalization, legacy target migration, explicit removal of targets, and the multi-output runtime structure.

## 0.12.2 — Multi-matrix setup clarity and regression coverage

- Clarify in both setup and options that each integration entry controls one matrix and that additional matrices are added as separate entries.
- Explain how to mirror source priorities safely and avoid duplicate theme-light control across entries.
- Confirm the startup lifecycle fix from 0.12.1 is included; 0.12.0 is known to fail setup because its manager lacked `async_start`.

## 0.12.1 — Startup and transition hotfix

- Restore the manager startup method that subscribes to selected player, matrix, and preset changes and schedules the initial update. This fixes a setup failure in 0.12.0.
- Fix Shuffle transitions by extracting the selection logic into a tested helper.
- Remove a stale area-discovery comment and unused retained frame buffer state.
- Add a structural regression test to ensure the integration startup method exists and is called.


## 0.12.0

- Preserve the three original album-color modes: Artwork palette, Dominant + contrast, and Dominant color.
- Replace generic Warm/Cool/Soft/etc. mood filters with five music-reactive color compositions: Vibrant accents, Complementary accent, Analogous flow, Cinematic, and Monochrome tones.
- Make all eight styles derive from the current cover palette or dominant cover hue; document their behavior in the options UI and README.
- Add unit coverage for legacy color modes and new music-reactive color composition.

## 0.11.0

- Remove unused idle WLED effect shuffling, its interval, allow-list, and related client logic; migrate old effect-shuffle end behavior to restore previous state.
- Remove area-based source discovery from the options UI and runtime; source selection is now explicit and ordered. Existing saved area selections are ignored.
- Expand theme/mood lighting profiles with Warm, Cool, Cinematic, and Energetic options alongside Balanced, Vivid, Soft, and Evening.
- Refresh configuration labels and documentation to focus on the supported features.

## 0.10.0

- Expose the WLED matrix target in Configure options so an existing entry can be reassigned safely. Validate WLED targets and reject a target already owned by another entry.
- Support one integration entry per matrix; additional displays can be added later from Home Assistant's Add integration flow and reuse the same ordered player priorities.
- Make configured player list order authoritative when choosing the first eligible source, while holding the previous cover briefly during metadata gaps when no higher-priority player is ready. Revalidate priority before completing an upload.
- Add a status sensor, diagnostics support, an artwork refresh button, a theme-light test button, and a manual automatic-control override switch.

## 0.9.1

- Removed idle-image URLs and idle-image rotation; end-of-session behavior now focuses on restoring the prior state, black screen, keeping the last cover, or optional WLED effect shuffle.
- Enabled color-spectrum balancing by default to soften near-white picks and lift very dark colors while preserving hue. This remains configurable.
- Implemented the separate "restore original brightness" toggle: original colors and on/off state are restored by default, while brightness restoration is opt-in for setups where other automations own brightness.
- Updated setup documentation and option labels to explain the color/brightness restoration distinction.

## 0.8.0 — Smarter theme palettes

- Add **Dominant + contrast** theme mode: retain the dominant cover color for the first selected light, then assign the most perceptually distinct colors present in the artwork to following lights.
- Compare palette colors in CIE Lab space rather than raw RGB, while never inventing colors absent from the cover.
- Clarify theme-mode labels and document the behavior and light-order priority.
- Add tests for contrast ordering, duplicate colors, and small palettes.

## 0.7.0 — Transition and project cleanup

- Split the integration into a small Home Assistant lifecycle module, a playback/session manager, a dedicated WLED API client, and image processing helpers.
- Switch from software-generated transition GIFs to WLED 0.16 native blend transitions; add shuffled transitions, additional wipes/pushes/circular styles, and optional idle effect shuffle.
- Keep old image files through the transition window before best-effort cleanup.
- Avoid reactivating unchanged image pixels and re-check the active source around artwork download/upload and fade-to-black.
- Make saved-state restoration the default for new configurations, restore the matrix's original on/off state, and refuse matrix output if the pre-session WLED state cannot be saved.
- Keep matrix output optional and retain room-light-only album palette support.
- Preserve a saved brightness level when turning an originally-off theme light on for music, and strengthen dark-image safety.
- Add focused tests for image processing, native transition payloads, and WLED effect shuffle filtering.

Validation covers syntax, JSON/translation files, nine focused unit tests, and ZIP integrity. It does not replace live testing with the user's Home Assistant instance and WLED hardware.

