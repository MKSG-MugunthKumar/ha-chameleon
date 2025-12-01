"""Constants for the Chameleon integration."""

from typing import Final

# Integration domain
DOMAIN: Final = "chameleon"

# Default values
DEFAULT_NAME: Final = "Chameleon"
DEFAULT_ANIMATION_SPEED: Final = 5  # seconds per color transition
DEFAULT_ANIMATION_ENABLED: Final = False

# Image directory (hardcoded per design decision)
IMAGE_DIRECTORY: Final = "/config/www/chameleon"

# Supported image extensions
SUPPORTED_EXTENSIONS: Final = (".jpg", ".jpeg", ".png")

# Configuration keys
CONF_LIGHT_ENTITY: Final = "light_entity"
CONF_ANIMATION_ENABLED: Final = "animation_enabled"
CONF_ANIMATION_SPEED: Final = "animation_speed"

# Platforms
PLATFORMS: Final = ["select"]

# Services
SERVICE_APPLY_SCENE: Final = "apply_scene"
SERVICE_START_ANIMATION: Final = "start_animation"
SERVICE_STOP_ANIMATION: Final = "stop_animation"

# Attributes
ATTR_SCENE_NAME: Final = "scene_name"
ATTR_MODE: Final = "mode"

# Modes
MODE_STATIC: Final = "static"
MODE_ANIMATED: Final = "animated"

# Color extraction
DEFAULT_COLOR_COUNT: Final = 8  # Number of colors to extract for palette
DEFAULT_QUALITY: Final = 10  # Color extraction quality (1 = highest, 10 = fastest)

# Animation
MIN_ANIMATION_SPEED: Final = 1  # Minimum seconds per transition
MAX_ANIMATION_SPEED: Final = 60  # Maximum seconds per transition
DEFAULT_TRANSITION_TIME: Final = 2  # Seconds for light transition effect
