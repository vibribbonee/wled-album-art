<img src="https://raw.githubusercontent.com/vibribbonee/wled-album-art/main/custom_components/wled_album_art/brand/icon.png" alt="" width="64" height="64" align="right">

# Music Artwork Lighting

Show the current album cover on a WLED matrix and color the room to match the music.

[![Add to Home Assistant Marketplace](https://my.home-assistant.io/badges/marketplace_repository.svg)](https://my.home-assistant.io/redirect/marketplace_repository/?owner=vibribbonee&repository=wled-album-art&category=integration)

## Features

- Display album artwork and sync color-capable room lights to its palette.
- Use a matrix, room lights, or Home Assistant artwork entities on their own.
- Set player priority and choose what the lights do when playback ends.
- Use a separate integration entry for each matrix.

## Where the cover comes from

```mermaid
flowchart TD
    M[Home Assistant media player] -->|Track details and artwork URL| A[Music Artwork Lighting]
    A -->|Fetch player artwork| U[Player artwork URL]
    U -->|Cover image| A
    A -->|Search by title, artist, and album| S[Online cover services]
    S -->|Matching cover image| A
    A --> C[Selected cover]
    C --> W[WLED matrix]
    C --> P[Color palette] --> L[Room lights]
    C --> H[Home Assistant artwork entity]
```

With online search enabled, the integration can fetch a missing cover or look for an animated version of a static player cover. You can choose MusicBrainz and Cover Art Archive, Deezer, Last.fm, and TheAudioDB in the settings.

## Setup

1. Install from Home Assistant Marketplace and restart Home Assistant.
2. Go to **Settings → Devices & services → Add integration → Music Artwork Lighting** and choose a media player. Add more players in **Configure** to set their priority.
3. Pick color-capable room lights and, optionally, a matrix light from the built-in WLED integration. Matrix artwork needs WLED 0.16.x with the Image effect and PixelForge playback support. Add one entry per matrix and assign each physical light to one entry.
4. Choose what the matrix and room lights should do when playback ends. Keep your existing entry when upgrading.

Use **Automatic control** to pause the integration, or turn off **Matrix artwork** to keep room-light matching on its own. Disable **Search online for cover art** to use the artwork your players provide.

[Dashboard examples, tuning, and troubleshooting](https://github.com/vibribbonee/wled-album-art/blob/main/docs/guide.md) · [Changelog](CHANGELOG.md)

## Contributing

Pull requests are welcome. Describe the change and how you tested it.

[MIT license](https://github.com/vibribbonee/wled-album-art/blob/main/LICENSE). OpenAI Codex assisted with development, testing, and documentation.
