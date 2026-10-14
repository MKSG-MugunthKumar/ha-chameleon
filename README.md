[![HACS Validation](https://github.com/MKSG-MugunthKumar/ha-chameleon/actions/workflows/hacs.yaml/badge.svg)](https://github.com/MKSG-MugunthKumar/ha-chameleon/actions/workflows/hacs.yaml)
[![Validate with hassfest](https://github.com/MKSG-MugunthKumar/ha-chameleon/actions/workflows/hassfest.yaml/badge.svg)](https://github.com/MKSG-MugunthKumar/ha-chameleon/actions/workflows/hassfest.yaml)
[![Lint](https://github.com/MKSG-MugunthKumar/ha-chameleon/actions/workflows/lint.yaml/badge.svg)](https://github.com/MKSG-MugunthKumar/ha-chameleon/actions/workflows/lint.yaml)
[![Release](https://github.com/MKSG-MugunthKumar/ha-chameleon/actions/workflows/release.yaml/badge.svg)](https://github.com/MKSG-MugunthKumar/ha-chameleon/actions/workflows/release.yaml)

<p align="center">
  <img src="icon.png" alt="Chameleon" width="128" height="128">
</p>

# Chameleon

**Color your lights from images and album art.**

Chameleon is a custom integration for [Home Assistant](https://www.home-assistant.io/) that extracts a color palette from an image and spreads it across a group of RGB lights - statically, or as a slow, continuous fade through the palette. Drop photos, artwork, or posters into a folder and each one becomes a scene. Link a media player and the room follows the album cover of whatever is playing.

## Features

- **One light entity per room** - `light.chameleon_*` behaves like any HA light: on/off, brightness, color picker, and an effect list. Works with stock Tile, Mushroom, and Bubble cards; no custom card needed.
- **Image scenes as effects** - every image in `/config/www/chameleon/` shows up in the light's effect list, plus `Random`.
- **Palette across lights** - each member light gets its own color from the image's palette.
- **Animated or static** - a transition slider (0-10 s) sets the fade per color; `0` applies the palette once. Lights move in sync or staggered.
- **Now Playing** - follow a media player's album art; pause holds, stopping returns to your scene.
- **Mains-aware** - when a room's power is cut, the Chameleon light goes unavailable; when power returns, every bulb is put back on its scene color.
- **Reconfigure in place** - add or remove member lights, or link a media player, without losing entity IDs or customizations.

## Installation

### HACS (recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=MKSG-MugunthKumar&repo=ha-chameleon&category=integration)

1. Open HACS in Home Assistant
2. Three-dots menu → **Custom repositories**
3. Add this repository URL with category **Integration**
4. Search for "Chameleon" and install
5. Restart Home Assistant

Requires Home Assistant 2024.11 or newer.

### Manual

1. Copy `custom_components/chameleon` into your `config/custom_components/` directory
2. Restart Home Assistant

## Setup

1. **Settings → Devices & Services → Add Integration → Chameleon**
2. Pick the RGB light(s) for one room or zone
3. Optionally set the default transition and link the room's media player
4. Add images to `/config/www/chameleon/` (created on first setup)

Each Chameleon entry creates three entities, named after the room (or the first light):

| Entity                                     | What it does                                                                      |
| ------------------------------------------ | --------------------------------------------------------------------------------- |
| `light.chameleon_<name>`                   | The room's light: on/off, brightness, color, and the effect (scene) list          |
| `number.chameleon_<name>_transition`       | Fade duration per color, 0-10 s. `0` = static, anything above animates            |
| `select.chameleon_<name>_transition_style` | `synchronized` (all lights change together) or `staggered` (each on its own beat) |

To change the lights or the media player later: **Settings → Devices & Services → Chameleon → ⋮ → Reconfigure**. Entity IDs, names, areas, and automations stay intact.

## Usage

### Adding scenes

Drop images into `/config/www/chameleon/` (`.jpg`, `.jpeg`, `.png`). File names become scene names - underscores and hyphens turn into spaces, title case applied:

```text
/config/www/chameleon/
├── sunset_vibes.jpg      → "Sunset Vibes"
├── ocean-blue.png        → "Ocean Blue"
└── forest_morning.jpg    → "Forest Morning"
```

Then run the **`chameleon.refresh_scenes`** action (Developer Tools → Actions), or reload the integration, to pick them up.

Starter images are in [`examples/images/`](examples/images/):

| Image                    | Palette                     | Good for          |
| ------------------------ | --------------------------- | ----------------- |
| `beach sunset.jpg`       | Warm oranges, pinks, golds  | Relaxing evenings |
| `dusk.jpg`               | Soft purples, blues, pinks  | Calm twilight     |
| `blue waters.jpg`        | Cool blues, teals           | Serene, focused   |
| `greenery.jpg`           | Natural greens, earth tones | Fresh, organic    |
| `greenish blue lake.jpg` | Teal, aqua, green           | Tranquil          |
| `abstract green.jpg`     | Vibrant greens              | Modern, energetic |
| `artistic purple.jpg`    | Deep purples, violets       | Creative, moody   |

### Picking a scene

Open the Chameleon light from any card and choose an **effect**: a scene name, or `Random`.

- **Turn off** stops any animation and switches the member lights off.
- **Turn on** (no options) brings back the last scene, or `Random` if there wasn't one.
- **Picking a color** in the color picker overrides the scene and sends that color to every member light. Picking an effect clears the override.
- **Brightness** applies live, including mid-animation.

### Transition and style

The transition slider is the fade time for each color, in seconds:

- **0** - static: the palette is applied once, one color per light.
- **0.1-1 s** - snappy; parties and emphasis.
- **1-5 s** - visibly moving ambience (default 5 s).
- **5-10 s** - a slow drift you barely notice.

`synchronized` moves every light to the next color together; `staggered` gives each light a random head start so the room shimmers instead of pulsing.

### Now Playing (album art)

Link a media player during setup or via Reconfigure - pick the player in the **same room**; in a multi-room audio setup each Chameleon follows its own room.

The light then lists a `Now Playing - <player name>` effect. Pick it from any light card:

- The lights take their colors from the current album cover, with your transition and style, like any scene.
- A new album repaints the lights; tracks from the same album don't.
- Pausing keeps the colors. When the player is idle or off for 30 seconds, the light returns to the scene it showed before (`Random` if none).
- Picking another effect, a color, or turning the light off stops following the player.

```yaml
action: light.turn_on
target:
  entity_id: light.chameleon_lounge
data:
  effect: "Now Playing - Lounge"
```

The effect name follows the player's friendly name, so automations that name it need updating if you rename the player.

### When lights lose power

Chameleon follows the same rule as HA's light groups: the Chameleon light stays **available while any member light is reachable**, and goes **unavailable when all of them are** - typically because the room's mains is switched off. The `unavailable_lights` attribute lists which members are offline.

Offline lights are skipped quietly (no log spam). When a light comes back it picks up where the room is: animated scenes pull it back in step within about a second, and static scenes and manual colors are re-sent to it, so it doesn't stay on its power-on warm white.

### Dashboard cards

Any light card works. A stock Tile card:

```yaml
type: tile
entity: light.chameleon_bedroom
features:
  - type: light-brightness
```

With the transition controls alongside:

```yaml
type: vertical-stack
cards:
  - type: tile
    entity: light.chameleon_bedroom
    features:
      - type: light-brightness
  - type: entities
    entities:
      - entity: number.chameleon_bedroom_transition
        name: Transition (0 = static)
      - entity: select.chameleon_bedroom_transition_style
        name: Style
```

[Bubble Card](https://github.com/Clooos/Bubble-Card) can put the scene picker right on the button with `select_attribute: effect_list` (see [#7](https://github.com/MKSG-MugunthKumar/ha-chameleon/issues/7) for a full example).

### Actions

Stock light actions cover almost everything:

```yaml
# Apply a scene
action: light.turn_on
target:
  entity_id: light.chameleon_bedroom
data:
  effect: "Sunset Vibes"
  brightness_pct: 80
```

```yaml
# Manual color (bypasses scenes)
action: light.turn_on
target:
  entity_id: light.chameleon_bedroom
data:
  rgb_color: [255, 100, 50]
```

```yaml
# Change the transition
action: number.set_value
target:
  entity_id: number.chameleon_bedroom_transition
data:
  value: 2.5
```

Chameleon adds two actions of its own:

```yaml
# Apply a scene with brightness (0-100, 0 = off) and transition (0 = static)
# set in the same call, so it renders at those values directly
action: chameleon.apply_scene
target:
  entity_id: light.chameleon_bedroom
data:
  scene_name: "Movie Night"
  brightness: 30
  transition: 0
```

```yaml
# Re-scan /config/www/chameleon/ after adding or removing images
action: chameleon.refresh_scenes
```

### State attributes

| Attribute             | Description                                                                                                                         |
| --------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| `light_entities`      | Member light entity IDs                                                                                                             |
| `light_count`         | Number of member lights                                                                                                             |
| `applied_colors`      | Member → RGB color, for static scenes and manual colors (empty while animating)                                                     |
| `extracted_palette`   | The image's palette as `[R, G, B]` triples, most dominant first                                                                     |
| `dominant_color`      | Most dominant palette color, `[R, G, B]`                                                                                            |
| `dominant_color_hex`  | Same, as `#RRGGBB` - handy for card `background:` styles                                                                            |
| `dominant_hue`        | Hue of the dominant color, 0-360°. Warm ≈ 0-60 and 300-360, cool ≈ 180-270                                                          |
| `dominant_saturation` | Saturation, 0-1 (above 0.6 vivid, below 0.3 washed out)                                                                             |
| `dominant_value`      | Brightness of the dominant color, 0-1                                                                                               |
| `manual_color`        | `[R, G, B]` while a manual color is active                                                                                          |
| `last_scene_change`   | ISO timestamp of the last scene change, for automation triggers                                                                     |
| `is_animating`        | Whether the animation loop is running                                                                                               |
| `last_error`          | Message from the last failed operation (cleared on the next successful one)                                                         |
| `failed_lights`       | Member → error message from the last apply                                                                                          |
| `unavailable_lights`  | Members currently unreachable (`unavailable`/`unknown`). The Chameleon light goes unavailable only when every member is listed here |
| `media_player`        | Linked media player, when one is configured                                                                                         |
| `now_playing`         | `Artist - Title` while following the music                                                                                          |

## Recorder and database size

While a scene animates, every **member light** changes state once per color - at a 5 s transition that's about 17,000 state changes per light per day. The Chameleon light itself only changes when the scene, brightness, or availability changes.

If you animate for long periods, exclude the member lights from the recorder:

```yaml
# configuration.yaml
recorder:
  exclude:
    entities:
      - light.bedroom_lamp_left
      - light.bedroom_lamp_right
```

## Troubleshooting

### The effect list has no scenes

1. Check `/config/www/chameleon/` exists and holds `.jpg`, `.jpeg`, or `.png` files
2. Run `chameleon.refresh_scenes`, or reload the integration
3. Turn on debug logs:

   ```yaml
   logger:
     logs:
       custom_components.chameleon: debug
   ```

### A light isn't changing color

Look at `failed_lights` and `last_error` on the Chameleon light:

- **does not exist** - the member entity was renamed or removed; fix it with Reconfigure
- **is unavailable / unknown** - the device is offline (see `unavailable_lights`)
- **does not support RGB** - the light has no color mode Chameleon can drive (RGB, RGBW, RGBWW, HS, or XY)
- **Failed to apply color** - the light's integration rejected the call; check the HA log

### The Chameleon light is unavailable

Every member light is offline. Restore power or connectivity to at least one of them.

### Now Playing doesn't start, or switches back to a scene

- `last_error: Nothing playing on media_player.…` - the player had no cover when you picked the effect. Start the music first.
- `last_error: Couldn't fetch cover art …` - the player's integration didn't return the image. Chameleon keeps the current colors and retries on the next album.
- Radio and line-in usually have no artwork; Chameleon holds the last colors while they play.

### Colors look off

- Try a simple, high-contrast image first
- Prefer RGB images over CMYK
- Some bulbs render saturated colors poorly at low brightness

## What's new

- **3.1** - Now Playing (album art from a linked media player); member-light availability and power-loss recovery; Reconfigure for member lights and media player.
- **3.0** - Single light entity with scenes as effects; transition slider and transition style replace the old speed and mode controls.

## Roadmap

- **Pulsate brightness** ([#6](https://github.com/MKSG-MugunthKumar/ha-chameleon/issues/6)) - breathe brightness between the set level and a lower one, per light
- **Animation patterns and presets** - wave and other patterns beyond the color fade
- **Scene presets with multiple images**, **time-based scene selection**, **HA scene integration**
- **Alternative extractors** - Haishoku or k-means as options alongside ColorThief
- **Spatial sampling** - map image regions (left/center/right) to lights by position

## Development

### Architecture

| Module                | Responsibility                                                                                                     |
| --------------------- | ------------------------------------------------------------------------------------------------------------------ |
| `__init__.py`         | Entry setup/unload, services, config entry migrations                                                              |
| `config_flow.py`      | Setup and Reconfigure flows                                                                                        |
| `const.py`            | Constants and config keys                                                                                          |
| `light.py`            | The Chameleon light: effects, brightness, manual color, palette apply paths, member availability, Now Playing mode |
| `number.py`           | Transition slider (0 = static)                                                                                     |
| `select.py`           | Transition style (synchronized / staggered)                                                                        |
| `animations.py`       | `AnimationController` per entry: one task per light, skips unreachable lights while keeping phase                  |
| `now_playing.py`      | `NowPlayingTracker`: watches one media player, cover changes, 30 s grace timer, cover bytes                        |
| `light_controller.py` | Light service calls, reachability, per-light results                                                               |
| `color_extractor.py`  | Palette and dominant color from image files or bytes (ColorThief)                                                  |
| `helpers.py`          | Device, entity, and entry naming                                                                                   |

Design notes live in [CLAUDE.md](CLAUDE.md) (architectural patterns: per-entity lock, cancel-safe service calls, derived state) and in [`docs/superpowers/specs/`](docs/superpowers/specs/).

### Workflow

```bash
make setup        # dev tools + pre-commit hooks
make test         # pytest with coverage
make dev-start    # local HA dev server (also dev-restart, dev-logs, dev-stop)
make deploy       # rsync to your HA (set REMOTE_HOST and REMOTE_PATH in .env)
```

Lint, format, and type checks run as pre-commit hooks on every commit and in CI. Commits follow Conventional Commits.

### Translations

English only for now. See [CONTRIBUTING.md](CONTRIBUTING.md#translations) to add a language.

### Contributing

Contributions welcome - see [CONTRIBUTING.md](CONTRIBUTING.md). Fork, branch, commit (the hooks run the checks), and open a pull request.

## License

MIT - see [LICENSE](LICENSE).

## Acknowledgments

- [adaptive-lighting](https://github.com/basnijholt/adaptive-lighting) - multi-instance config flow patterns
- [ColorThief](https://github.com/fengsp/color-thief-py) - color extraction
- Example images from [Unsplash](https://unsplash.com)

## Author

Created by [@mk_sg](https://mastodon.social/@mk_sg) - follow for updates and other projects!
