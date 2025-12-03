# Chameleon Integration - Developer Guide

**Extract colors from images and apply them to your RGB lights.**

Chameleon is a custom component for [Home Assistant](https://www.home-assistant.io/) that automatically extracts colors from images and applies them to your lights. Perfect for creating ambient lighting that matches your favorite photos, artwork, or movie posters.

## Architecture Overview

### Module Responsibilities

| Module                | Responsibility                                               |
| --------------------- | ------------------------------------------------------------ |
| `__init__.py`         | Integration entry point, setup/unload                        |
| `config_flow.py`      | UI configuration flow                                        |
| `const.py`            | All constants and configuration keys                         |
| `select.py`           | Select entity (scene selection UI)                           |
| `light_controller.py` | Shared light control logic (availability, color application) |
| `color_extractor.py`  | Color extraction from images                                 |
| `animations.py`       | Animation loop management                                    |

### Key Design Pattern: Separation of Concerns

The `light_controller.py` module contains all light control logic shared between:

- Select entity (`select.py`)
- Services (future: `apply_scene`, `start_animation`, `stop_animation`)

This separation ensures consistent behavior and error handling across all light control operations.

## Color Extraction Strategy

### Libraries

- **Primary**: Pillow (PIL) - Core image processing
- **Color Extraction**: colorthief or custom k-means clustering
- **Alternatives considered**: colorz (Rust, not usable), haishoku (Python, viable)

### Animation Color Strategy

**Don't just use dominant colors** - they won't look good for smooth animation.

**Recommended Approach: Color Gradient Paths**

1. Extract 5-10 colors from image using palette extraction
2. Create smooth gradients between each color pair
3. Result: 50-100 color progression for smooth animation
4. Cycle through this gradient path

**Alternative: Spatial Sampling**

- Sample colors from different regions of image (grid-based)
- Left, center, right regions for spatial distribution
- Use for multi-light setups (different lights get different regions)

More details in TODO.md under "Color Extraction Techniques".

## Error Handling Strategy

### Light Availability Checks

Before applying colors, the integration checks:

1. **Entity exists**: Light entity is registered in HA
2. **Entity available**: Not in `unavailable` or `unknown` state
3. **RGB support**: Light supports RGB, RGBW, RGBWW, HS, or XY color modes

### Error Tracking

Errors are tracked in entity state attributes:

- `last_error`: Human-readable error message (cleared on success)
- `failed_lights`: Dict of entity_id → error message

This allows:

- UI display of errors
- Automation triggers based on failures
- Debugging without checking logs

### Failure Modes

| Scenario           | Behavior                                     |
| ------------------ | -------------------------------------------- |
| All lights succeed | Update `current_option`, clear errors        |
| All lights fail    | Keep previous `current_option`, set error    |
| Partial failure    | Update `current_option`, track failed lights |

### Production Testing

- Test with real Philips Hue or RGB lights
- Verify color accuracy
- Test animation smoothness
- Monitor DB writes (check recorder size growth)

## Common Issues

### Image Directory Not Found

- Ensure `/config/www/chameleon/` exists
- Integration should create it on first setup if missing

### Colors Look Wrong

- Check image format (RGB vs RGBA)
- Verify color space conversions
- Test with known-good images first

### Select Entity Not Showing Options

- Check image directory scan logic
- Verify file extensions (jpg, png)
- Check logs for errors (set `logger.logs.custom_components.chameleon: debug`)

### Light Not Responding

Check the `failed_lights` attribute for detailed error messages:

- `not_found`: Entity doesn't exist
- `unavailable`: Device offline
- `no_rgb_support`: Light doesn't support colors
- `service_call_failed`: HA service error

## Development Workflow

### Quick Start

```bash
make dev-setup    # First time: install tools + start server
make dev-start    # Start server (if already set up)
make dev-restart  # Reload code changes
make dev-logs     # View logs
```

### Deploy to Production (Your own HA instance)

```bash
# Sync to production server
rsync -avz --delete \
  ~/ha-chameleon/custom_components/chameleon/ \
  your-server:/config/custom_components/chameleon/

# Restart production HA
ssh your-server "docker restart homeassistant"

# Monitor logs
ssh your-server "docker logs -f homeassistant"
```

---

### Release Version (HACS)

1. Tag release: `git tag v0.1.0`
2. Push to GitHub: `git push origin v0.1.0`
3. Users install via HACS custom repository
4. Or submit to HACS default repository (after stability)
