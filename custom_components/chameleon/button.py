"""Button platform for Chameleon integration - Scene refresh."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_LIGHT_ENTITIES,
    CONF_LIGHT_ENTITY,
    DOMAIN,
)
from .helpers import get_chameleon_device_name, get_entity_base_name

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Chameleon button entity from a config entry."""
    _LOGGER.debug("Setting up Chameleon button entity for entry: %s", entry.entry_id)

    # Support both old single-light and new multi-light config
    if CONF_LIGHT_ENTITIES in entry.data:
        light_entities = entry.data[CONF_LIGHT_ENTITIES]
    else:
        light_entities = [entry.data[CONF_LIGHT_ENTITY]]

    async_add_entities(
        [ChameleonRefreshButton(hass, entry, light_entities)],
        True,
    )


class ChameleonRefreshButton(ButtonEntity):
    """Button entity for refreshing the scene list.

    Press this button to immediately rescan the image directory
    without waiting for the 30-second automatic refresh.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "refresh_scenes"
    _attr_icon = "mdi:refresh"

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        light_entities: list[str],
    ) -> None:
        """Initialize the refresh button entity."""
        self.hass = hass
        self._entry = entry
        self._light_entities = light_entities

        # Generate unique ID and entity ID with chameleon_ prefix
        base_name = get_entity_base_name(hass, light_entities)
        self._base_name = base_name  # Store for use in async_press
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_refresh"
        self.entity_id = f"button.chameleon_{base_name}_refresh_scenes"

        _LOGGER.debug(
            "ChameleonRefreshButton initialized: entity_id=%s, unique_id=%s",
            self.entity_id,
            self._attr_unique_id,
        )

    @property
    def device_info(self):
        """Return device info for this entity."""
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": get_chameleon_device_name(self.hass, self._light_entities),
            "manufacturer": "Chameleon",
            "model": "Scene Selector",
        }

    async def async_press(self) -> None:
        """Handle button press - refresh the scene list."""
        _LOGGER.info("Refresh scenes button pressed for entry: %s", self._entry.entry_id)

        # Find the select entity for this entry and trigger a refresh
        select_entity_id = f"select.chameleon_{self._base_name}_scene"
        select_entity = self.hass.states.get(select_entity_id)

        if select_entity:
            # Fire an event that the select entity can listen for
            # Or directly access the entity through the entity registry
            from homeassistant.helpers import entity_registry as er

            registry = er.async_get(self.hass)
            entity_entry = registry.async_get(select_entity_id)

            if entity_entry:
                # Get the actual entity object from the platform
                entity_component = self.hass.data.get("entity_components", {}).get("select")
                if entity_component:
                    for entity in entity_component.entities:
                        if entity.entity_id == select_entity_id and hasattr(entity, "_async_refresh_options"):
                            # Call the refresh method directly
                            await entity._async_refresh_options()
                            _LOGGER.info("Scene list refreshed successfully")
                            return

        # Fallback: fire an event that can be caught
        self.hass.bus.async_fire(
            f"{DOMAIN}_refresh_scenes",
            {"entry_id": self._entry.entry_id},
        )
        _LOGGER.debug("Fired refresh scenes event for entry: %s", self._entry.entry_id)
