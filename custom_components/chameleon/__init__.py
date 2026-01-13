"""The Chameleon integration - Extract colors from images and apply to RGB lights."""

from __future__ import annotations

import logging
from pathlib import Path

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .animations import AnimationManager
from .const import (
    ATTR_SCENE_NAME,
    DOMAIN,
    IMAGE_DIRECTORY,
    PLATFORMS,
    SERVICE_APPLY_SCENE,
    SERVICE_START_ANIMATION,
    SERVICE_STOP_ANIMATION,
)

_LOGGER = logging.getLogger(__name__)

type ChameleonConfigEntry = ConfigEntry[None]

# Service schemas - now target Chameleon entities instead of lights
SERVICE_APPLY_SCENE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_SCENE_NAME): cv.string,
    }
)

SERVICE_START_ANIMATION_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_SCENE_NAME): cv.string,
    }
)

SERVICE_STOP_ANIMATION_SCHEMA = vol.Schema({})


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
    """Register Chameleon services.

    Services now target Chameleon entities instead of raw lights:
    - apply_scene: Targets select.chameleon_* entities
    - start_animation: Targets select.chameleon_* entities (enables animation first)
    - stop_animation: Targets switch.chameleon_*_animation entities
    """

    async def handle_apply_scene(call: ServiceCall) -> None:
        """Handle the apply_scene service call.

        Targets Chameleon select entities and sets their value to the scene name.
        """
        entity_ids: list[str] = call.data.get("entity_id", [])
        scene_name: str = call.data[ATTR_SCENE_NAME]

        _LOGGER.info(
            "Service apply_scene: entities=%s, scene=%s",
            entity_ids,
            scene_name,
        )

        for entity_id in entity_ids:
            # Validate this is a Chameleon select entity
            if not entity_id.startswith("select.chameleon_"):
                _LOGGER.warning(
                    "Skipping %s: not a Chameleon select entity",
                    entity_id,
                )
                continue

            # Call the select service to set the scene
            await hass.services.async_call(
                "select",
                "select_option",
                {
                    "entity_id": entity_id,
                    "option": scene_name,
                },
                blocking=True,
            )
            _LOGGER.debug("Applied scene '%s' to %s", scene_name, entity_id)

    async def handle_start_animation(call: ServiceCall) -> None:
        """Handle the start_animation service call.

        Targets Chameleon select entities. Enables the animation switch first,
        then applies the scene.
        """
        entity_ids: list[str] = call.data.get("entity_id", [])
        scene_name: str = call.data[ATTR_SCENE_NAME]

        _LOGGER.info(
            "Service start_animation: entities=%s, scene=%s",
            entity_ids,
            scene_name,
        )

        for entity_id in entity_ids:
            # Validate this is a Chameleon select entity
            if not entity_id.startswith("select.chameleon_"):
                _LOGGER.warning(
                    "Skipping %s: not a Chameleon select entity",
                    entity_id,
                )
                continue

            # Derive the animation switch entity ID from the select entity ID
            # select.chameleon_hallway_scene -> switch.chameleon_hallway_animation
            base = entity_id.replace("select.", "").replace("_scene", "")
            animation_switch_id = f"switch.{base}_animation"

            # Turn on the animation switch
            await hass.services.async_call(
                "switch",
                "turn_on",
                {"entity_id": animation_switch_id},
                blocking=True,
            )
            _LOGGER.debug("Enabled animation: %s", animation_switch_id)

            # Apply the scene
            await hass.services.async_call(
                "select",
                "select_option",
                {
                    "entity_id": entity_id,
                    "option": scene_name,
                },
                blocking=True,
            )
            _LOGGER.debug("Applied scene '%s' to %s", scene_name, entity_id)

    async def handle_stop_animation(call: ServiceCall) -> None:
        """Handle the stop_animation service call.

        Targets Chameleon animation switch entities and turns them off.
        """
        entity_ids: list[str] = call.data.get("entity_id", [])

        _LOGGER.info("Service stop_animation: entities=%s", entity_ids)

        for entity_id in entity_ids:
            # Validate this is a Chameleon switch entity
            if not entity_id.startswith("switch.chameleon_"):
                _LOGGER.warning(
                    "Skipping %s: not a Chameleon switch entity",
                    entity_id,
                )
                continue

            # Turn off the animation switch
            await hass.services.async_call(
                "switch",
                "turn_off",
                {"entity_id": entity_id},
                blocking=True,
            )
            _LOGGER.debug("Stopped animation: %s", entity_id)

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

    _LOGGER.info(
        "Registered Chameleon services: %s, %s, %s",
        SERVICE_APPLY_SCENE,
        SERVICE_START_ANIMATION,
        SERVICE_STOP_ANIMATION,
    )
