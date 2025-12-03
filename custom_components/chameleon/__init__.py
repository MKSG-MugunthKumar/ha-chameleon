"""The Chameleon integration - Extract colors from images and apply to RGB lights."""

from __future__ import annotations

import logging
from pathlib import Path

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .animations import AnimationManager
from .color_extractor import extract_color_palette, generate_gradient_path
from .const import (
    ATTR_MODE,
    ATTR_SCENE_NAME,
    DEFAULT_ANIMATION_SPEED,
    DEFAULT_COLOR_COUNT,
    DOMAIN,
    IMAGE_DIRECTORY,
    MODE_ANIMATED,
    MODE_STATIC,
    PLATFORMS,
    SERVICE_APPLY_SCENE,
    SERVICE_START_ANIMATION,
    SERVICE_STOP_ANIMATION,
    SUPPORTED_EXTENSIONS,
)
from .light_controller import LightController

_LOGGER = logging.getLogger(__name__)

type ChameleonConfigEntry = ConfigEntry[None]

# Service schemas
SERVICE_APPLY_SCENE_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): cv.entity_ids,
        vol.Required(ATTR_SCENE_NAME): cv.string,
        vol.Optional(ATTR_MODE, default=MODE_STATIC): vol.In([MODE_STATIC, MODE_ANIMATED]),
    }
)

SERVICE_START_ANIMATION_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): cv.entity_ids,
        vol.Required(ATTR_SCENE_NAME): cv.string,
    }
)

SERVICE_STOP_ANIMATION_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): cv.entity_ids,
    }
)


def _find_image_for_scene(scene_name: str) -> Path | None:
    """Find image file for a scene name."""
    image_dir = Path(IMAGE_DIRECTORY)
    if not image_dir.exists():
        return None

    # Convert scene name to filename pattern
    filename_base = scene_name.lower().replace(" ", "_")

    for ext in SUPPORTED_EXTENSIONS:
        # Try exact match
        image_path = image_dir / f"{filename_base}{ext}"
        if image_path.exists():
            return image_path

        # Try case-insensitive
        for file in image_dir.glob(f"*{ext}"):
            if file.stem.lower() == filename_base:
                return file

    return None


async def async_setup_entry(hass: HomeAssistant, entry: ChameleonConfigEntry) -> bool:
    """Set up Chameleon from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # Create the image directory if it doesn't exist
    image_dir = Path(IMAGE_DIRECTORY)
    if not image_dir.exists():
        _LOGGER.info("Creating Chameleon image directory: %s", IMAGE_DIRECTORY)
        await hass.async_add_executor_job(image_dir.mkdir, True, True)

    # Create shared AnimationManager if not exists
    if "animation_manager" not in hass.data[DOMAIN]:
        hass.data[DOMAIN]["animation_manager"] = AnimationManager(hass)
        _LOGGER.debug("Created AnimationManager")

    # Store entry data
    hass.data[DOMAIN][entry.entry_id] = {
        "config": entry.data,
    }

    # Register services (only once)
    if not hass.services.has_service(DOMAIN, SERVICE_APPLY_SCENE):
        await _async_register_services(hass)

    # Forward entry setup to platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ChameleonConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

        # If no more entries, stop all animations and cleanup
        remaining_entries = [key for key in hass.data[DOMAIN] if key != "animation_manager"]
        if not remaining_entries:
            animation_manager: AnimationManager = hass.data[DOMAIN].get("animation_manager")
            if animation_manager:
                await animation_manager.stop_all()
                _LOGGER.debug("Stopped all animations on last entry unload")

    return unload_ok


async def _async_register_services(hass: HomeAssistant) -> None:
    """Register Chameleon services."""

    async def handle_apply_scene(call: ServiceCall) -> None:
        """Handle the apply_scene service call."""
        entity_ids: list[str] = call.data["entity_id"]
        scene_name: str = call.data[ATTR_SCENE_NAME]
        mode: str = call.data.get(ATTR_MODE, MODE_STATIC)

        _LOGGER.info(
            "Service apply_scene: entities=%s, scene=%s, mode=%s",
            entity_ids,
            scene_name,
            mode,
        )

        # Find image file
        image_path = await hass.async_add_executor_job(_find_image_for_scene, scene_name)
        if not image_path:
            _LOGGER.error("Scene '%s' not found in %s", scene_name, IMAGE_DIRECTORY)
            return

        # Extract colors
        colors = await extract_color_palette(
            hass,
            image_path,
            color_count=max(len(entity_ids), DEFAULT_COLOR_COUNT),
        )

        if not colors:
            _LOGGER.error("Failed to extract colors from %s", image_path)
            return

        if mode == MODE_ANIMATED:
            # Start animation for each light
            animation_manager: AnimationManager = hass.data[DOMAIN]["animation_manager"]
            gradient = generate_gradient_path(colors, steps_between=10)

            for entity_id in entity_ids:
                await animation_manager.start_animation(
                    entity_id,
                    gradient,
                    speed=DEFAULT_ANIMATION_SPEED,
                )
        else:
            # Static mode - apply colors directly
            light_controller = LightController(hass)
            light_colors = {entity_ids[i]: colors[i % len(colors)] for i in range(len(entity_ids))}
            await light_controller.apply_colors_to_lights(light_colors)

    async def handle_start_animation(call: ServiceCall) -> None:
        """Handle the start_animation service call."""
        entity_ids: list[str] = call.data["entity_id"]
        scene_name: str = call.data[ATTR_SCENE_NAME]

        _LOGGER.info(
            "Service start_animation: entities=%s, scene=%s",
            entity_ids,
            scene_name,
        )

        # Find image file
        image_path = await hass.async_add_executor_job(_find_image_for_scene, scene_name)
        if not image_path:
            _LOGGER.error("Scene '%s' not found in %s", scene_name, IMAGE_DIRECTORY)
            return

        # Extract colors and generate gradient
        colors = await extract_color_palette(
            hass,
            image_path,
            color_count=DEFAULT_COLOR_COUNT,
        )

        if not colors:
            _LOGGER.error("Failed to extract colors from %s", image_path)
            return

        gradient = generate_gradient_path(colors, steps_between=10)

        # Start animation for each light
        animation_manager: AnimationManager = hass.data[DOMAIN]["animation_manager"]
        for entity_id in entity_ids:
            await animation_manager.start_animation(
                entity_id,
                gradient,
                speed=DEFAULT_ANIMATION_SPEED,
            )

    async def handle_stop_animation(call: ServiceCall) -> None:
        """Handle the stop_animation service call."""
        entity_ids: list[str] = call.data["entity_id"]

        _LOGGER.info("Service stop_animation: entities=%s", entity_ids)

        animation_manager: AnimationManager = hass.data[DOMAIN]["animation_manager"]
        for entity_id in entity_ids:
            await animation_manager.stop_animation(entity_id)

    # Register all services
    hass.services.async_register(
        DOMAIN,
        SERVICE_APPLY_SCENE,
        handle_apply_scene,
        schema=SERVICE_APPLY_SCENE_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_START_ANIMATION,
        handle_start_animation,
        schema=SERVICE_START_ANIMATION_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_STOP_ANIMATION,
        handle_stop_animation,
        schema=SERVICE_STOP_ANIMATION_SCHEMA,
    )

    _LOGGER.info("Registered Chameleon services: %s, %s, %s", SERVICE_APPLY_SCENE, SERVICE_START_ANIMATION, SERVICE_STOP_ANIMATION)
