"""Constants for the Chameleon integration."""

from typing import Final

# Integration domain
DOMAIN: Final = "chameleon"

# Default values
DEFAULT_NAME: Final = "Chameleon"
DEFAULT_ANIMATION_SPEED: Final = 5  # seconds per color transition

# Image directory (hardcoded per design decision)
IMAGE_DIRECTORY: Final = "/config/www/chameleon"

# Supported image extensions
SUPPORTED_EXTENSIONS: Final = (".jpg", ".jpeg", ".png")

# Configuration keys
CONF_LIGHT_ENTITY: Final = "light_entity"  # Deprecated, kept for migration
CONF_LIGHT_ENTITIES: Final = "light_entities"  # New: list of light entities
CONF_ANIMATION_SPEED: Final = "animation_speed"

# Platforms (no `switch` — animation on/off is now speed=0; mode is a select)
PLATFORMS: Final = ["select", "number"]

# Services
SERVICE_APPLY_SCENE: Final = "apply_scene"
SERVICE_START_ANIMATION: Final = "start_animation"
SERVICE_STOP_ANIMATION: Final = "stop_animation"
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

# Animation
# Speed of 0 means "static" — apply the scene once with no animation loop.
# Range chosen for usable slider precision: 100 positions over 0-10s with 0.1s step.
# 10s is enough for most ambient-lighting use cases; longer cycles can be set via
# the number entity's box mode or a service call if a power user wants them.
MIN_ANIMATION_SPEED: Final = 0
MAX_ANIMATION_SPEED: Final = 10
DEFAULT_TRANSITION_TIME: Final = 0.1  # Instant snap transitions

# Animation modes (used by ChameleonAnimationModeSelect)
ANIMATION_MODE_SYNC: Final = "synchronized"
ANIMATION_MODE_STAGGERED: Final = "staggered"
ANIMATION_MODES: Final = [ANIMATION_MODE_SYNC, ANIMATION_MODE_STAGGERED]
DEFAULT_ANIMATION_MODE: Final = ANIMATION_MODE_STAGGERED  # More natural-looking by default

# Brightness
# Brightness of 0 means "off" — equivalent to selecting the Off scene.
DEFAULT_BRIGHTNESS: Final = 100
MIN_BRIGHTNESS: Final = 0
MAX_BRIGHTNESS: Final = 100
