"""Switch platform for Chameleon integration - Animation toggle."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_ANIMATION_ENABLED,
    CONF_LIGHT_ENTITIES,
    CONF_LIGHT_ENTITY,
    DEFAULT_ANIMATION_ENABLED,
    DEFAULT_SYNC_ANIMATION,
    DOMAIN,
)
from .helpers import get_chameleon_device_name, get_entity_base_name

if TYPE_CHECKING:
    from .animations import AnimationManager

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Chameleon switch entities from a config entry."""
    _LOGGER.debug("Setting up Chameleon switch entities for entry: %s", entry.entry_id)

    # Support both old single-light and new multi-light config
    if CONF_LIGHT_ENTITIES in entry.data:
        light_entities = entry.data[CONF_LIGHT_ENTITIES]
    else:
        light_entities = [entry.data[CONF_LIGHT_ENTITY]]

    # Get initial animation state from config
    animation_enabled = entry.data.get(CONF_ANIMATION_ENABLED, DEFAULT_ANIMATION_ENABLED)

    async_add_entities(
        [
            ChameleonAnimationSwitch(hass, entry, light_entities, animation_enabled),
            ChameleonSyncAnimationSwitch(hass, entry, light_entities),
        ],
        True,
    )


class ChameleonAnimationSwitch(SwitchEntity):
    """Switch entity for toggling Chameleon animation mode."""

    _attr_has_entity_name = True
    _attr_translation_key = "animation"

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        light_entities: list[str],
        initial_state: bool,
    ) -> None:
        """Initialize the animation switch entity."""
        self.hass = hass
        self._entry = entry
        self._light_entities = light_entities
        self._is_on = initial_state

        # Generate unique ID and entity ID with chameleon_ prefix
        base_name = get_entity_base_name(hass, light_entities)
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_animation"
        self.entity_id = f"switch.chameleon_{base_name}_animation"

        _LOGGER.debug(
            "ChameleonAnimationSwitch initialized: entity_id=%s, unique_id=%s, is_on=%s",
            self.entity_id,
            self._attr_unique_id,
            self._is_on,
        )

    def _get_animation_manager(self) -> AnimationManager | None:
        """Get the AnimationManager from hass.data."""
        return self.hass.data.get(DOMAIN, {}).get("animation_manager")

    @property
    def device_info(self):
        """Return device info for this entity."""
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": get_chameleon_device_name(self.hass, self._light_entities),
            "manufacturer": "Chameleon",
            "model": "Scene Selector",
        }

    @property
    def is_on(self) -> bool:
        """Return true if animation is enabled."""
        return self._is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on animation mode."""
        self._is_on = True
        _LOGGER.info("Animation enabled for %s", self._light_entities)

        # Store animation state in hass.data for select entity to use
        self._store_animation_state()

        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off animation mode and stop any running animations."""
        self._is_on = False
        _LOGGER.info("Animation disabled for %s", self._light_entities)

        # Stop any running animations
        await self._stop_animations()

        # Store animation state in hass.data for select entity to use
        self._store_animation_state()

        self.async_write_ha_state()

    def _store_animation_state(self) -> None:
        """Store the animation state in hass.data for other entities to access."""
        if DOMAIN not in self.hass.data:
            self.hass.data[DOMAIN] = {}
        if self._entry.entry_id not in self.hass.data[DOMAIN]:
            self.hass.data[DOMAIN][self._entry.entry_id] = {}

        self.hass.data[DOMAIN][self._entry.entry_id]["animation_enabled"] = self._is_on

    async def _stop_animations(self) -> None:
        """Stop animations for all lights managed by this entity."""
        animation_manager = self._get_animation_manager()
        if animation_manager:
            for light_entity in self._light_entities:
                await animation_manager.stop_animation(light_entity)
            _LOGGER.debug("Stopped animations for %s", self._light_entities)

    @property
    def extra_state_attributes(self):
        """Return extra state attributes."""
        return {
            "light_entities": self._light_entities,
        }

    @property
    def icon(self) -> str:
        """Return the icon based on state."""
        return "mdi:animation-play" if self._is_on else "mdi:animation"


class ChameleonSyncAnimationSwitch(SwitchEntity):
    """Switch entity for toggling synchronized vs staggered animation mode.

    When ON: All lights change color simultaneously (synchronized)
    When OFF: Each light changes color with random delays (staggered)
    """

    _attr_has_entity_name = True
    _attr_translation_key = "sync_animation"

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        light_entities: list[str],
    ) -> None:
        """Initialize the sync animation switch entity."""
        self.hass = hass
        self._entry = entry
        self._light_entities = light_entities
        self._is_on = DEFAULT_SYNC_ANIMATION  # Default to staggered mode

        # Generate unique ID and entity ID with chameleon_ prefix
        base_name = get_entity_base_name(hass, light_entities)
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_sync_animation"
        self.entity_id = f"switch.chameleon_{base_name}_sync_animation"

        _LOGGER.debug(
            "ChameleonSyncAnimationSwitch initialized: entity_id=%s, unique_id=%s, is_on=%s",
            self.entity_id,
            self._attr_unique_id,
            self._is_on,
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

    @property
    def is_on(self) -> bool:
        """Return true if sync mode is enabled (all lights animate together)."""
        return self._is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable synchronized animation mode."""
        self._is_on = True
        _LOGGER.info("Sync animation enabled for %s", self._light_entities)

        # Store sync state in hass.data for animation manager to use
        self._store_sync_state()

        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Enable staggered animation mode."""
        self._is_on = False
        _LOGGER.info("Staggered animation enabled for %s", self._light_entities)

        # Store sync state in hass.data for animation manager to use
        self._store_sync_state()

        self.async_write_ha_state()

    def _store_sync_state(self) -> None:
        """Store the sync state in hass.data for other entities to access."""
        if DOMAIN not in self.hass.data:
            self.hass.data[DOMAIN] = {}
        if self._entry.entry_id not in self.hass.data[DOMAIN]:
            self.hass.data[DOMAIN][self._entry.entry_id] = {}

        self.hass.data[DOMAIN][self._entry.entry_id]["sync_animation"] = self._is_on

    @property
    def extra_state_attributes(self):
        """Return extra state attributes."""
        return {
            "light_entities": self._light_entities,
            "mode": "synchronized" if self._is_on else "staggered",
        }

    @property
    def icon(self) -> str:
        """Return the icon based on state."""
        return "mdi:sync" if self._is_on else "mdi:shuffle-variant"
