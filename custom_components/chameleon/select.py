"""Select platform for Chameleon integration."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_ANIMATION_ENABLED,
    CONF_ANIMATION_SPEED,
    CONF_LIGHT_ENTITY,
    DOMAIN,
    IMAGE_DIRECTORY,
    SUPPORTED_EXTENSIONS,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Chameleon select entity from a config entry."""
    light_entity = entry.data[CONF_LIGHT_ENTITY]
    animation_enabled = entry.data.get(CONF_ANIMATION_ENABLED, False)
    animation_speed = entry.data.get(CONF_ANIMATION_SPEED, 5)

    async_add_entities(
        [
            ChameleonSceneSelect(
                hass,
                entry,
                light_entity,
                animation_enabled,
                animation_speed,
            )
        ],
        True,
    )


def _scene_name_from_filename(filename: str) -> str:
    """Convert filename to human-readable scene name."""
    # Remove extension and convert underscores/hyphens to spaces, then title case
    return filename.replace("_", " ").replace("-", " ").title()


def _filename_from_scene_name(scene_name: str) -> str:
    """Convert scene name back to filename (without extension)."""
    return scene_name.lower().replace(" ", "_")


class ChameleonSceneSelect(SelectEntity):
    """Select entity for choosing Chameleon scenes."""

    _attr_has_entity_name = True
    _attr_translation_key = "scene"

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        light_entity: str,
        animation_enabled: bool,
        animation_speed: int,
    ) -> None:
        """Initialize the select entity."""
        self.hass = hass
        self._entry = entry
        self._light_entity = light_entity
        self._animation_enabled = animation_enabled
        self._animation_speed = animation_speed
        self._current_option: str | None = None

        # Generate unique ID from the light entity
        light_name = light_entity.split(".")[-1]
        self._attr_unique_id = f"{DOMAIN}_{light_name}_scene"

        # Entity ID will be select.{light_name}_scene
        self.entity_id = f"select.{light_name}_scene"

    @property
    def device_info(self):
        """Return device info for this entity."""
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": f"Chameleon ({self._light_entity})",
            "manufacturer": "Chameleon",
            "model": "Scene Selector",
        }

    @property
    def options(self) -> list[str]:
        """Return the list of available scene options."""
        image_dir = Path(IMAGE_DIRECTORY)

        if not image_dir.exists():
            _LOGGER.warning("Image directory does not exist: %s", IMAGE_DIRECTORY)
            return []

        scenes = []
        for ext in SUPPORTED_EXTENSIONS:
            for image_path in image_dir.glob(f"*{ext}"):
                scene_name = _scene_name_from_filename(image_path.stem)
                if scene_name not in scenes:
                    scenes.append(scene_name)

        return sorted(scenes)

    @property
    def current_option(self) -> str | None:
        """Return the currently selected option."""
        return self._current_option

    async def async_select_option(self, option: str) -> None:
        """Handle the user selecting an option."""
        _LOGGER.debug("Scene selected: %s for light %s", option, self._light_entity)

        # Find the image file for this scene
        image_path = await self._find_image_for_scene(option)

        if image_path is None:
            _LOGGER.error("Could not find image for scene: %s", option)
            return

        # TODO: Extract colors from image and apply to light
        # This will be implemented in color_extractor.py
        _LOGGER.info(
            "Would extract colors from %s and apply to %s",
            image_path,
            self._light_entity,
        )

        self._current_option = option
        self.async_write_ha_state()

    async def _find_image_for_scene(self, scene_name: str) -> Path | None:
        """Find the image file path for a given scene name."""
        image_dir = Path(IMAGE_DIRECTORY)
        filename_base = _filename_from_scene_name(scene_name)

        for ext in SUPPORTED_EXTENSIONS:
            # Try exact match first
            image_path = image_dir / f"{filename_base}{ext}"
            if image_path.exists():
                return image_path

            # Try case-insensitive search
            for file in image_dir.glob(f"*{ext}"):
                if file.stem.lower() == filename_base:
                    return file

        return None
