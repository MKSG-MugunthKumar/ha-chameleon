# LEARN.md - Building a Home Assistant Custom Integration

This document contains essential knowledge for building the Chameleon integration. Read this before writing code.

## Table of Contents

1. [Home Assistant Integration Basics](#home-assistant-integration-basics)
2. [Select Entity Platform](#select-entity-platform)
3. [Config Flow (UI Configuration)](#config-flow-ui-configuration)
4. [Color Extraction Techniques](#color-extraction-techniques)
5. [Animation Implementation](#animation-implementation)
6. [Database Write Considerations](#database-write-considerations)
7. [Development Environment Setup](#development-environment-setup)
8. [Key Learning Resources](#key-learning-resources)

---

## Home Assistant Integration Basics

### What is a Custom Integration?

A custom integration is a Python package that extends Home Assistant's functionality. It can:
- Create new entities (lights, sensors, switches, selects, etc.)
- Provide services that can be called from automations
- Listen to events and react to state changes
- Integrate with external APIs or devices

### Integration Structure

```
custom_components/your_integration/
├── __init__.py           # Entry point, setup functions
├── manifest.json         # Metadata (name, version, dependencies)
├── config_flow.py        # UI configuration (optional but recommended)
├── const.py              # Constants used throughout
├── {platform}.py         # Entity platform (e.g., select.py, light.py)
├── services.yaml         # Service definitions
└── strings.json          # UI text for config flow
```

### manifest.json

Defines integration metadata:

```json
{
  "domain": "chameleon",
  "name": "Chameleon",
  "version": "0.1.0",
  "documentation": "https://github.com/user/image-scene-colorizer",
  "requirements": ["Pillow==10.0.0", "colorthief==0.2.1"],
  "codeowners": ["@yourusername"],
  "iot_class": "local_polling"
}
```

**Key fields:**
- `domain`: Unique identifier (use snake_case)
- `requirements`: Python packages from PyPI
- `iot_class`: How integration interacts (local_polling, cloud_polling, local_push, etc.)

### __init__.py

Entry point for the integration:

```python
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

DOMAIN = "chameleon"
PLATFORMS = ["select"]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up from a config entry (created via UI)."""
    # Store data that platforms will need
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "light_entity": entry.data["light_entity"],
        "animation_enabled": entry.data.get("animation_enabled", False),
    }

    # Forward entry setup to platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
```

---

## Select Entity Platform

### What is a Select Entity?

A select entity represents a choice from a list of options. Like a dropdown menu.

**Examples in HA:**
- Thermostat fan mode (Auto, Low, Medium, High)
- Scene profiles (Energize, Relax, Sleep)
- Input selects (user-defined dropdowns)

### How It Works

**Three key components:**
1. **Current option**: The selected value
2. **Options list**: Available choices
3. **Select callback**: What happens when user picks a new option

### Creating a Select Entity

```python
# select.py
from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities,
):
    """Set up select entity from config entry."""
    light_entity = entry.data["light_entity"]

    # Create the select entity
    select_entity = ImageSceneSelect(hass, entry, light_entity)

    async_add_entities([select_entity])


class ImageSceneSelect(SelectEntity):
    """Select entity for choosing image scenes."""

    def __init__(self, hass, entry, light_entity):
        self._hass = hass
        self._entry = entry
        self._light_entity = light_entity
        self._current_option = None
        self._attr_name = f"{light_entity.split('.')[1]} Scene"
        self._attr_unique_id = f"{entry.entry_id}_scene_select"

    @property
    def options(self) -> list[str]:
        """Return list of available scenes."""
        # Scan image directory
        return self._scan_image_directory()

    @property
    def current_option(self) -> str | None:
        """Return currently selected scene."""
        return self._current_option

    async def async_select_option(self, option: str) -> None:
        """Handle user selecting a new scene."""
        self._current_option = option

        # Extract colors from image and apply to light
        await self._apply_scene(option)

        # Update entity state
        self.async_write_ha_state()

    def _scan_image_directory(self) -> list[str]:
        """Scan for available images."""
        from pathlib import Path

        image_dir = Path("/config/www/chameleon")
        if not image_dir.exists():
            return []

        images = list(image_dir.glob("*.jpg")) + list(image_dir.glob("*.png"))
        return [img.stem.replace("_", " ").title() for img in images]

    async def _apply_scene(self, scene_name: str):
        """Extract colors and apply to light."""
        # This is where color extraction happens
        # We'll implement this in detail later
        pass
```

### UI Integration

**The beauty of select entities**: HA automatically shows them in UI!

- More-info dialog shows dropdown
- Options populated from `options` property
- Selection triggers `async_select_option` callback
- No custom UI code needed

---

## Config Flow (UI Configuration)

### What is Config Flow?

Config flow is the UI-based setup process:
1. User clicks "Add Integration"
2. Fills out a form
3. Integration is configured (no YAML editing!)

### Why Use Config Flow?

- **User-friendly**: No YAML knowledge required
- **Validation**: Catch errors during setup
- **Reconfiguration**: Change settings via UI
- **Multiple instances**: Easy to set up multiple times

### Basic Config Flow

```python
# config_flow.py
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback

from .const import DOMAIN

class ImageColorizerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            # Validate input
            light_entity = user_input["light_entity"]

            if not self._is_valid_light(light_entity):
                errors["light_entity"] = "invalid_light"
            else:
                # Create the config entry
                return self.async_create_entry(
                    title=f"Scene for {light_entity}",
                    data=user_input,
                )

        # Show the form
        data_schema = vol.Schema({
            vol.Required("light_entity"): str,
            vol.Optional("animation_enabled", default=False): bool,
            vol.Optional("animation_speed", default=5): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=60)
            ),
        })

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )

    def _is_valid_light(self, entity_id: str) -> bool:
        """Validate that entity is a light."""
        return entity_id.startswith("light.")
```

### Advanced: Entity Selector

Use entity selectors for better UX:

```python
from homeassistant.helpers import selector

data_schema = vol.Schema({
    vol.Required("light_entity"): selector.EntitySelector(
        selector.EntitySelectorConfig(domain="light")
    ),
    vol.Optional("animation_enabled", default=False): bool,
})
```

This shows a nice dropdown of all light entities (with search!).

---

## Color Extraction Techniques

### Problem: Dominant Colors Aren't Enough

Using just the dominant color from an image:
- ❌ Boring for static application
- ❌ Terrible for animation (jumps between few colors)
- ❌ Doesn't capture image's full palette

### Solution 1: Color Palette Extraction

Extract multiple distinct colors from the image:

```python
from colorthief import ColorThief

def extract_color_palette(image_path: str, count: int = 10) -> list[tuple]:
    """Extract a palette of colors from image."""
    ct = ColorThief(image_path)
    palette = ct.get_palette(color_count=count, quality=1)
    return palette  # List of (R, G, B) tuples

# Example result:
# [(234, 145, 67), (89, 156, 203), (156, 89, 178), ...]
```

**Better, but still jumpy for animation.**

### Solution 2: Color Gradient Paths (Recommended)

Create smooth transitions between palette colors:

```python
def create_gradient(color1: tuple, color2: tuple, steps: int = 20) -> list[tuple]:
    """Create smooth gradient between two colors."""
    gradient = []
    for i in range(steps):
        ratio = i / steps
        r = int(color1[0] + (color2[0] - color1[0]) * ratio)
        g = int(color1[1] + (color2[1] - color1[1]) * ratio)
        b = int(color1[2] + (color2[2] - color1[2]) * ratio)
        gradient.append((r, g, b))
    return gradient


def generate_animation_path(image_path: str) -> list[tuple]:
    """Generate smooth color path for animation."""
    # Extract base palette
    palette = extract_color_palette(image_path, count=6)

    # Create gradients between each color
    full_path = []
    for i in range(len(palette)):
        next_i = (i + 1) % len(palette)  # Loop back to start
        gradient = create_gradient(palette[i], palette[next_i], steps=20)
        full_path.extend(gradient)

    return full_path  # ~120 smooth color transitions

# Animation then cycles through this path - buttery smooth!
```

### Solution 3: Spatial Sampling

Sample colors from different regions of the image:

```python
from PIL import Image

def sample_spatial_colors(image_path: str, grid_size: int = 4) -> list[tuple]:
    """Sample colors from different parts of image."""
    img = Image.open(image_path)
    width, height = img.size
    colors = []

    for x in range(grid_size):
        for y in range(grid_size):
            # Sample center of each grid cell
            px = int(width * (x + 0.5) / grid_size)
            py = int(height * (y + 0.5) / grid_size)
            rgb = img.getpixel((px, py))
            colors.append(rgb[:3])  # Ignore alpha if present

    return colors

# Good for multi-light setups:
# - Left lights get left-side colors
# - Center lights get center colors
# - Right lights get right-side colors
```

### Which to Use?

- **Static mode**: Dominant color or palette average
- **Animation mode**: Gradient paths (smooth!)
- **Multi-light**: Spatial sampling (distribute across room)

---

## Animation Implementation

### The Challenge

Create continuous, smooth color animation without:
- Blocking the event loop
- Killing the SD card with DB writes
- Hogging CPU resources

### Async Animation Loop

```python
import asyncio
from homeassistant.core import HomeAssistant

class AnimationController:
    """Manages color animation for a light."""

    def __init__(self, hass: HomeAssistant, light_entity: str):
        self._hass = hass
        self._light_entity = light_entity
        self._task = None
        self._running = False
        self._color_path = []
        self._speed = 5  # seconds per color

    def set_color_path(self, colors: list[tuple]):
        """Set the animation color sequence."""
        self._color_path = colors

    async def start(self):
        """Start the animation loop."""
        if self._running:
            return  # Already running

        self._running = True
        self._task = asyncio.create_task(self._animation_loop())

    async def stop(self):
        """Stop the animation loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _animation_loop(self):
        """The actual animation loop."""
        index = 0

        while self._running:
            # Get next color
            color = self._color_path[index]

            # Apply to light with transition
            await self._hass.services.async_call(
                "light",
                "turn_on",
                {
                    "entity_id": self._light_entity,
                    "rgb_color": list(color),
                    "transition": self._speed,  # Smooth transition
                },
                blocking=False,  # Don't wait for completion
            )

            # Wait before next color
            await asyncio.sleep(self._speed)

            # Move to next color (loop back to start)
            index = (index + 1) % len(self._color_path)
```

### Key Points

1. **Use asyncio.create_task()**: Don't block the event loop
2. **Use transitions**: Smooth changes, fewer state updates
3. **Cancellable**: Must be able to stop animation cleanly
4. **Non-blocking service calls**: Don't wait for light to respond

### Multiple Animations

```python
# In __init__.py or a dedicated module
class AnimationManager:
    """Manage multiple simultaneous animations."""

    def __init__(self, hass: HomeAssistant):
        self._hass = hass
        self._animations = {}  # entity_id -> AnimationController

    def get_controller(self, light_entity: str) -> AnimationController:
        """Get or create animation controller for a light."""
        if light_entity not in self._animations:
            self._animations[light_entity] = AnimationController(
                self._hass, light_entity
            )
        return self._animations[light_entity]

    async def stop_all(self):
        """Stop all animations (cleanup on shutdown)."""
        for controller in self._animations.values():
            await controller.stop()
```

---

## Database Write Considerations

### The Problem

Every time you change a light's state, Home Assistant:
1. Writes the new state to the database
2. Records history
3. Triggers state change events

**Animation at 1 color/second = 86,400 DB writes/day per light!**

On Raspberry Pi with SD card: **THIS KILLS YOUR SD CARD** 💀

### Solution 1: Recorder Exclusion (Best)

Tell users to exclude animation lights from recorder:

```yaml
# configuration.yaml
recorder:
  exclude:
    entities:
      - light.theatre_accents
      - light.office_accents
```

**Result**: No DB writes, no history, but light still works perfectly.

Document this clearly in README!

### Solution 2: Use Transitions

```python
# BAD: Discrete jumps, one DB write per color
await hass.services.async_call("light", "turn_on", {
    "entity_id": "light.theatre",
    "rgb_color": [255, 0, 0],
})
await asyncio.sleep(1)
await hass.services.async_call("light", "turn_on", {
    "entity_id": "light.theatre",
    "rgb_color": [0, 255, 0],
})
# Many calls, many DB writes

# GOOD: Smooth transition, fewer DB writes
await hass.services.async_call("light", "turn_on", {
    "entity_id": "light.theatre",
    "rgb_color": [255, 0, 0],
    "transition": 10,  # 10 second smooth fade
})
await asyncio.sleep(10)  # Wait for transition
await hass.services.async_call("light", "turn_on", {
    "entity_id": "light.theatre",
    "rgb_color": [0, 255, 0],
    "transition": 10,
})
# One state change per transition - much better!
```

### Solution 3: Lower Frequency

Don't update every second:
- 1s interval = 86,400 writes/day ❌
- 5s interval = 17,280 writes/day ⚠️
- 10s interval = 8,640 writes/day ✅

Make it configurable, default to 5-10 seconds.

### What NOT to Do

```python
# DON'T: Update every frame (60 FPS)
for i in range(1000000):
    color = calculate_color(i)
    await set_light(color)
    await asyncio.sleep(0.016)  # 60 FPS
# RIP SD card
```

---

## Development Environment Setup

### Local HA Instance

```bash
# Create project directory
mkdir ~/image-scene-colorizer
cd ~/image-scene-colorizer

# Create integration directory
mkdir -p custom_components/chameleon

# Create dev HA config
mkdir ~/ha-dev-config

# Run HA in Docker with volume mounts
docker run -d \
  --name ha-dev \
  --restart unless-stopped \
  -p 8123:8123 \
  -v ~/ha-dev-config:/config \
  -v ~/image-scene-colorizer/custom_components:/config/custom_components \
  ghcr.io/home-assistant/home-assistant:stable

# Access at http://localhost:8123
# Default user: create during first setup
```

### Development Loop

```bash
# 1. Edit code
code ~/image-scene-colorizer

# 2. Reload integration
# In HA: Developer Tools → YAML → Reload Integrations
# Or restart container: docker restart ha-dev

# 3. Test
# Open http://localhost:8123

# 4. Check logs
docker logs -f ha-dev
```

### Dummy Light for Testing

```yaml
# ~/ha-dev-config/configuration.yaml
light:
  - platform: template
    lights:
      test_light:
        friendly_name: "Test RGB Light"
        turn_on:
        turn_off:
        set_rgb:
          service: light.turn_on
          data:
            rgb_color: "{{ rgb_color }}"
```

### Deploy to Production

```bash
# Sync to production server
rsync -avz --delete \
  ~/image-scene-colorizer/custom_components/chameleon/ \
  your-server:/config/custom_components/chameleon/

# Restart production HA
ssh your-server "docker restart homeassistant"

# Monitor logs
ssh your-server "docker logs -f homeassistant"
```

---

## Key Learning Resources

### Official Documentation
- **HA Developer Docs**: https://developers.home-assistant.io/
  - Start here, comprehensive guides
- **Architecture**: https://developers.home-assistant.io/docs/architecture_index
  - Understand how HA works internally
- **Config Entries**: https://developers.home-assistant.io/docs/config_entries_index
  - UI-based configuration system
- **Entity Platform**: https://developers.home-assistant.io/docs/core/entity
  - Base class for all entities

### Specific Guides
- **Select Entity**: https://developers.home-assistant.io/docs/core/entity/select
- **Config Flow**: https://developers.home-assistant.io/docs/config_entries_config_flow_handler
- **Services**: https://developers.home-assistant.io/docs/dev_101_services
- **Async Programming**: https://developers.home-assistant.io/docs/asyncio_working_with_async

### Example Integrations to Study

**1. Adaptive Lighting** (Your style inspiration)
- GitHub: https://github.com/basnijholt/adaptive-lighting
- Study: Config flow, multiple instances, entity creation

**2. Scenery** (Select entity pattern)
- GitHub: https://github.com/j9brown/scenery
- Study: Select entities, profile management

**3. Template** (Built-in, simple)
- HA Core: `homeassistant/components/template/`
- Study: Basic entity creation

### Python Libraries

**Color Extraction**:
- **Pillow**: https://pillow.readthedocs.io/
  - Image processing, pixel access
- **colorthief**: https://github.com/fengsp/color-thief-py
  - Palette extraction (uses k-means)

**Async Programming**:
- **asyncio docs**: https://docs.python.org/3/library/asyncio.html
  - Essential for HA development

### Community

- **HA Dev Community**: https://community.home-assistant.io/c/development/
- **Discord**: https://discord.gg/home-assistant (dev channel)
- **GitHub Discussions**: Issues on HA core repo

---

## Development Checklist

Before you start coding, make sure you understand:

- [ ] Home Assistant integration structure (files, folders)
- [ ] How select entities work (properties, callbacks)
- [ ] Config flow basics (user input, validation)
- [ ] Color extraction approaches (palette vs gradients)
- [ ] Async programming (async/await, tasks)
- [ ] Database write concerns (SD card wear)
- [ ] Development workflow (local testing, rsync deploy)

**When ready**: Create the basic file structure, then implement step by step.

---

## Next Steps

1. **Read this entire document** (you are here!)
2. **Set up local development environment** (Docker HA)
3. **Study example integrations** (Adaptive Lighting, Scenery)
4. **Create basic project structure** (files and folders)
5. **Implement Phase 1: Static Mode** (MVP)
6. **Test locally** with dummy lights
7. **Deploy to production** via rsync
8. **Iterate**: Add animation, polish, release

Good luck! 🚀
