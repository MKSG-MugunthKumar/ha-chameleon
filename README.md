# Chameleon

**Extract colors from images and apply them to your RGB lights.**

Chameleon is a custom component for [Home Assistant](https://www.home-assistant.io/) that automatically extracts colors from images and applies them to your lights. Perfect for creating ambient lighting that matches your favorite photos, artwork, or movie posters.

## Features

- **Image-based scenes**: Drop images in a folder, Chameleon auto-discovers them as scenes
- **Multi-light support**: Distribute extracted colors across multiple lights
- **Color palette extraction**: Uses advanced color extraction for vibrant, representative colors
- **Animation mode**: Cycle through colors from an image (coming soon)
- **Native HA integration**: Works with the built-in select entity UI

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click the three dots menu → Custom repositories
3. Add this repository URL with category "Integration"
4. Search for "Chameleon" and install
5. Restart Home Assistant

### Manual Installation

1. Copy the `custom_components/chameleon` folder to your `config/custom_components/` directory
2. Restart Home Assistant

## Configuration

1. Go to **Settings** → **Devices & Services** → **Add Integration**
2. Search for "Chameleon"
3. Select the RGB light(s) you want to control
4. Add images to `/config/www/chameleon/`

That's it! A select entity will be created that shows all available scenes.

## Usage

### Adding Scenes

Drop image files into `/config/www/chameleon/`:

```
/config/www/chameleon/
├── sunset_vibes.jpg      → "Sunset Vibes"
├── ocean-blue.png        → "Ocean Blue"
├── forest_morning.jpg    → "Forest Morning"
└── movie_poster.png      → "Movie Poster"
```

Filenames are automatically converted to scene names (underscores/hyphens become spaces, title case applied).

### Selecting Scenes

Use the select entity in:

- Home Assistant UI (entity card, more-info dialog)
- Automations
- Scripts
- Voice assistants

### State Attributes

The select entity exposes useful attributes:

| Attribute        | Description                               |
| ---------------- | ----------------------------------------- |
| `light_entities` | List of configured light entity IDs       |
| `light_count`    | Number of configured lights               |
| `applied_colors` | Dict of entity_id → RGB color             |
| `last_error`     | Error message if last operation failed    |
| `failed_lights`  | Dict of failed lights with error messages |

### Services

```yaml
# Apply a scene programmatically
service: select.select_option
target:
  entity_id: select.bedroom_lamp_scene
data:
  option: "Sunset Vibes"
```

## Multi-Light Setup

When configuring multiple lights:

1. Chameleon extracts a color palette from the image
2. Each light receives a different color from the palette
3. Colors are distributed in the order lights are configured

This creates a cohesive but varied lighting atmosphere.

## Error Handling

Chameleon provides detailed feedback when things go wrong:

- **Light not found**: Entity doesn't exist in HA
- **Light unavailable**: Device is offline
- **No RGB support**: Light doesn't support color mode
- **Service call failed**: HA service error

Check the `last_error` and `failed_lights` attributes for details.

## Database Considerations

Chameleon uses light transitions (default: 2 seconds) for smooth color changes. This means one state change per transition, not per color step. Animation mode creates frequent state changes. At 1 color/second, that's **86,400 database writes per day** per light.

### Recommended: Recorder Exclusion

Exclude animated lights from the recorder to prevent database bloat:

```yaml
# configuration.yaml
recorder:
  exclude:
    entities:
      - light.your_animated_light
    entity_globs:
      - light.chameleon_*
```

### Animation Speed

Default animation interval is 5 seconds. Adjust based on your needs:

- **Slow (10-60s)**: Subtle ambiance
- **Medium (5-10s)**: Good balance
- **Fast (1-5s)**: More dynamic

Regardless of speed, consider recorder exclusion for animated lights.

## Troubleshooting

### Select Entity Shows No Options

1. Verify `/config/www/chameleon/` directory exists
2. Check file extensions are `.jpg`, `.jpeg`, or `.png`
3. Check logs: `logger.logs.custom_components.chameleon: debug`
4. Options refresh every 30 seconds

### Colors Look Wrong

- Ensure images are RGB format (not CMYK)
- Test with a simple, high-contrast image first
- Check if the light supports full RGB range

### Light Not Responding

Check the `failed_lights` attribute:

- `not_found`: Verify the entity ID is correct
- `unavailable`: Check the device is online
- `no_rgb_support`: Use an RGB-capable light
- `service_call_failed`: Check HA logs for details

## License

MIT License - see [LICENSE](LICENSE) for details.

## Translations

Chameleon currently supports **English only**. We'd love help translating to other languages!

If you're fluent in another language and want to contribute translations, check out our [Contributing Guide](CONTRIBUTING.md#translations) for instructions.

## Contributing

Contributions welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

Quick start:

1. Fork the repository
2. Create a feature branch
3. Run `make check` before submitting
4. Submit a pull request

## Acknowledgments

Inspired by:

- [adaptive-lighting](https://github.com/basnijholt/adaptive-lighting) - For multi-instance config flow patterns
- [scenery](https://github.com/home-assistant/core) - For select entity patterns

Libraries used:

- [ColorThief](https://github.com/fengsp/color-thief-py) - Color extraction library
