"""Constants for the Chameleon integration."""

from typing import Final

# Integration domain
DOMAIN: Final = "chameleon"

# Default values
DEFAULT_NAME: Final = "Chameleon"
DEFAULT_TRANSITION: Final = 5  # default fade duration per color, seconds

# Image directory (hardcoded per design decision)
IMAGE_DIRECTORY: Final = "/config/www/chameleon"

# Supported image extensions
SUPPORTED_EXTENSIONS: Final = (".jpg", ".jpeg", ".png")

# Configuration keys
CONF_LIGHT_ENTITY: Final = "light_entity"  # Deprecated, kept for migration
CONF_LIGHT_ENTITIES: Final = "light_entities"  # New: list of light entities
CONF_TRANSITION: Final = "transition"

# Platforms. Light is the primary entity; select hosts the transition style picker;
# number hosts the transition slider. No switch (animation on/off is transition=0)
# and no scene select (scenes are exposed as the light's effects).
PLATFORMS: Final = ["light", "select", "number"]

# Services
SERVICE_APPLY_SCENE: Final = "apply_scene"
SERVICE_REFRESH_SCENES: Final = "refresh_scenes"

# Attributes
ATTR_SCENE_NAME: Final = "scene_name"
ATTR_MODE: Final = "mode"

# Special scene options
SCENE_OFF: Final = "Off"  # Turn off all lights
SCENE_RANDOM: Final = "Random"  # Pick a random scene

# Color extraction
DEFAULT_COLOR_COUNT: Final = 8  # Number of colors to extract for palette
DEFAULT_QUALITY: Final = 10  # Color extraction quality (1 = highest, 10 = fastest)

# Animation transition
# A "transition" is the seconds-long fade duration between successive scene
# colors. Transition of 0 means "static" — apply the scene once with no
# animation loop. Range chosen for usable slider precision: 100 positions over
# 0-10s with 0.1s step. 10s is enough for most ambient-lighting use cases.
MIN_TRANSITION: Final = 0
MAX_TRANSITION: Final = 10

# Static apply transition: the per-call transition seconds we use for one-shot
# scene application (when transition = 0). Kept short for snappy feel.
STATIC_TRANSITION_TIME: Final = 0.1

# Transition styles (used by ChameleonTransitionStyleSelect)
TRANSITION_STYLE_SYNC: Final = "synchronized"
TRANSITION_STYLE_STAGGERED: Final = "staggered"
TRANSITION_STYLES: Final = [TRANSITION_STYLE_SYNC, TRANSITION_STYLE_STAGGERED]
DEFAULT_TRANSITION_STYLE: Final = TRANSITION_STYLE_STAGGERED  # More natural-looking by default

# Brightness
# Brightness of 0 means "off" — equivalent to selecting the Off scene.
DEFAULT_BRIGHTNESS: Final = 100
MIN_BRIGHTNESS: Final = 0
MAX_BRIGHTNESS: Final = 100
