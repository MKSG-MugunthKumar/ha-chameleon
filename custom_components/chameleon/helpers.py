"""Helper functions for the Chameleon integration."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


def slugify(text: str) -> str:
    """Convert text to a slug suitable for entity IDs.

    Args:
        text: The text to convert

    Returns:
        Lowercase string with spaces/special chars replaced by underscores
    """
    # Convert to lowercase
    text = text.lower()
    # Replace spaces and hyphens with underscores
    text = re.sub(r"[\s\-]+", "_", text)
    # Remove any characters that aren't alphanumeric or underscores
    text = re.sub(r"[^a-z0-9_]", "", text)
    # Remove consecutive underscores
    text = re.sub(r"_+", "_", text)
    # Strip leading/trailing underscores
    return text.strip("_")


def get_chameleon_device_name(hass: HomeAssistant, light_entities: list[str]) -> str:
    """Generate a friendly device name based on area or light names.

    Priority:
    1. If all lights share the same area -> "Chameleon <Area Name>"
    2. If single light -> "Chameleon <Light Friendly Name>"
    3. Otherwise -> "Chameleon <First Light Friendly Name>"

    Args:
        hass: Home Assistant instance
        light_entities: List of light entity IDs

    Returns:
        A friendly device name like "Chameleon Dining" or "Chameleon Living Room Light"
    """
    # Import here to avoid circular imports
    from homeassistant.helpers import area_registry as ar
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)
    area_registry = ar.async_get(hass)

    # Try to find a common area for all lights
    area_ids: set[str | None] = set()

    for entity_id in light_entities:
        area_id = _get_entity_area_id(
            entity_id, entity_registry, device_registry
        )
        area_ids.add(area_id)

    # Filter out None values
    valid_area_ids = {a for a in area_ids if a is not None}

    # If all lights share exactly one area, use that area name
    if len(valid_area_ids) == 1:
        area_id = valid_area_ids.pop()
        area = area_registry.async_get_area(area_id)
        if area:
            _LOGGER.debug(
                "All lights share area '%s', using for device name",
                area.name,
            )
            return f"Chameleon {area.name}"

    # Otherwise, use the first light's friendly name
    first_light_name = _get_light_friendly_name(hass, light_entities[0])
    _LOGGER.debug(
        "No common area found, using first light name: %s",
        first_light_name,
    )
    return f"Chameleon {first_light_name}"


def _get_entity_area_id(
    entity_id: str,
    entity_registry: "er.EntityRegistry",
    device_registry: "dr.DeviceRegistry",
) -> str | None:
    """Get the area ID for an entity, checking entity and device assignments.

    Args:
        entity_id: The entity ID to look up
        entity_registry: Entity registry instance
        device_registry: Device registry instance

    Returns:
        Area ID if found, None otherwise
    """
    # Import types for type hints
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    entity_entry = entity_registry.async_get(entity_id)
    if not entity_entry:
        return None

    # Check if entity has direct area assignment
    if entity_entry.area_id:
        return entity_entry.area_id

    # Check if entity's device has area assignment
    if entity_entry.device_id:
        device = device_registry.async_get(entity_entry.device_id)
        if device and device.area_id:
            return device.area_id

    return None


def _get_light_friendly_name(hass: HomeAssistant, entity_id: str) -> str:
    """Get a friendly name for a light entity.

    Args:
        hass: Home Assistant instance
        entity_id: The light entity ID

    Returns:
        Friendly name from state attributes, or formatted entity ID as fallback
    """
    state = hass.states.get(entity_id)
    if state and state.attributes.get("friendly_name"):
        return state.attributes["friendly_name"]

    # Fall back to entity_id without domain, formatted nicely
    return entity_id.split(".")[-1].replace("_", " ").title()


def get_entry_title(hass: HomeAssistant, light_entities: list[str]) -> str:
    """Generate a config entry title based on area or light names.

    This is similar to get_chameleon_device_name but without the "Chameleon " prefix.
    Used for the config entry title displayed in the integrations page.

    Args:
        hass: Home Assistant instance
        light_entities: List of light entity IDs

    Returns:
        A friendly title like "Dining Room" or "Living Room Light"
    """
    # Import here to avoid circular imports
    from homeassistant.helpers import area_registry as ar
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)
    area_registry = ar.async_get(hass)

    # Try to find a common area for all lights
    area_ids: set[str | None] = set()

    for entity_id in light_entities:
        area_id = _get_entity_area_id(
            entity_id, entity_registry, device_registry
        )
        area_ids.add(area_id)

    # Filter out None values
    valid_area_ids = {a for a in area_ids if a is not None}

    # If all lights share exactly one area, use that area name
    if len(valid_area_ids) == 1:
        area_id = valid_area_ids.pop()
        area = area_registry.async_get_area(area_id)
        if area:
            return area.name

    # Otherwise, use the first light's friendly name
    return _get_light_friendly_name(hass, light_entities[0])


def get_entity_base_name(hass: HomeAssistant, light_entities: list[str]) -> str:
    """Generate a slug-friendly base name for entity IDs.

    Used to create entity IDs like:
    - switch.chameleon_{base_name}_animation
    - number.chameleon_{base_name}_brightness

    Args:
        hass: Home Assistant instance
        light_entities: List of light entity IDs

    Returns:
        A slug like "hallway" or "dining_room"
    """
    # Get the friendly name (area or light name)
    friendly_name = get_entry_title(hass, light_entities)
    # Convert to slug
    return slugify(friendly_name)
