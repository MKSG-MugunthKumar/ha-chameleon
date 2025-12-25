"""Number platform for Chameleon integration - Brightness control."""

from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_ANIMATION_SPEED,
    CONF_LIGHT_ENTITIES,
    CONF_LIGHT_ENTITY,
    DEFAULT_ANIMATION_SPEED,
    DEFAULT_BRIGHTNESS,
    DOMAIN,
    MAX_ANIMATION_SPEED,
    MAX_BRIGHTNESS,
    MIN_ANIMATION_SPEED,
    MIN_BRIGHTNESS,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Chameleon number entities from a config entry."""
    _LOGGER.debug("Setting up Chameleon number entities for entry: %s", entry.entry_id)

    # Support both old single-light and new multi-light config
    if CONF_LIGHT_ENTITIES in entry.data:
        light_entities = entry.data[CONF_LIGHT_ENTITIES]
    else:
        light_entities = [entry.data[CONF_LIGHT_ENTITY]]

    # Get initial animation speed from config
    initial_animation_speed = entry.data.get(CONF_ANIMATION_SPEED, DEFAULT_ANIMATION_SPEED)

    async_add_entities(
        [
            ChameleonBrightnessNumber(hass, entry, light_entities),
            ChameleonAnimationSpeedNumber(hass, entry, light_entities, initial_animation_speed),
        ],
        True,
    )


class ChameleonBrightnessNumber(NumberEntity):
    """Number entity for controlling Chameleon brightness."""

    _attr_has_entity_name = True
    _attr_translation_key = "brightness"
    _attr_native_min_value = MIN_BRIGHTNESS
    _attr_native_max_value = MAX_BRIGHTNESS
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.SLIDER

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        light_entities: list[str],
    ) -> None:
        """Initialize the brightness number entity."""
        self.hass = hass
        self._entry = entry
        self._light_entities = light_entities
        self._brightness = DEFAULT_BRIGHTNESS

        # Generate unique ID and entity ID
        first_light_name = light_entities[0].split(".")[-1]
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_brightness"
        self.entity_id = f"number.{first_light_name}_brightness"

        _LOGGER.debug(
            "ChameleonBrightnessNumber initialized: entity_id=%s, unique_id=%s",
            self.entity_id,
            self._attr_unique_id,
        )

    @property
    def device_info(self):
        """Return device info for this entity."""
        if len(self._light_entities) == 1:
            name = f"Chameleon ({self._light_entities[0]})"
        else:
            name = f"Chameleon ({len(self._light_entities)} lights)"

        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": name,
            "manufacturer": "Chameleon",
            "model": "Scene Selector",
        }

    @property
    def native_value(self) -> float:
        """Return the current brightness value."""
        return self._brightness

    async def async_set_native_value(self, value: float) -> None:
        """Set the brightness value and apply to lights."""
        self._brightness = int(value)
        _LOGGER.info("Brightness set to %d%% for %s", self._brightness, self._light_entities)

        # Store brightness in hass.data for select entity to use
        if DOMAIN not in self.hass.data:
            self.hass.data[DOMAIN] = {}
        if self._entry.entry_id not in self.hass.data[DOMAIN]:
            self.hass.data[DOMAIN][self._entry.entry_id] = {}

        self.hass.data[DOMAIN][self._entry.entry_id]["brightness"] = self._brightness

        # Apply brightness to lights immediately
        await self._apply_brightness_to_lights()

        self.async_write_ha_state()

    async def _apply_brightness_to_lights(self) -> None:
        """Apply the current brightness to all configured lights."""
        # Convert percentage to HA brightness (0-255)
        ha_brightness = int((self._brightness / 100) * 255)

        for light_entity in self._light_entities:
            try:
                await self.hass.services.async_call(
                    "light",
                    "turn_on",
                    {
                        "entity_id": light_entity,
                        "brightness": ha_brightness,
                    },
                    blocking=True,
                )
                _LOGGER.debug(
                    "Applied brightness %d (%d%%) to %s",
                    ha_brightness,
                    self._brightness,
                    light_entity,
                )
            except Exception:
                _LOGGER.exception("Failed to apply brightness to %s", light_entity)

    @property
    def extra_state_attributes(self):
        """Return extra state attributes."""
        return {
            "light_entities": self._light_entities,
            "brightness_255": int((self._brightness / 100) * 255),
        }


class ChameleonAnimationSpeedNumber(NumberEntity):
    """Number entity for controlling Chameleon animation speed."""

    _attr_has_entity_name = True
    _attr_translation_key = "animation_speed"
    _attr_native_min_value = MIN_ANIMATION_SPEED
    _attr_native_max_value = MAX_ANIMATION_SPEED
    _attr_native_step = 0.1
    _attr_native_unit_of_measurement = "s"
    _attr_mode = NumberMode.SLIDER
    _attr_icon = "mdi:speedometer"

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        light_entities: list[str],
        initial_speed: float,
    ) -> None:
        """Initialize the animation speed number entity."""
        self.hass = hass
        self._entry = entry
        self._light_entities = light_entities
        self._speed = initial_speed

        # Generate unique ID and entity ID
        first_light_name = light_entities[0].split(".")[-1]
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_animation_speed"
        self.entity_id = f"number.{first_light_name}_animation_speed"

        _LOGGER.debug(
            "ChameleonAnimationSpeedNumber initialized: entity_id=%s, unique_id=%s, speed=%s",
            self.entity_id,
            self._attr_unique_id,
            self._speed,
        )

    @property
    def device_info(self):
        """Return device info for this entity."""
        if len(self._light_entities) == 1:
            name = f"Chameleon ({self._light_entities[0]})"
        else:
            name = f"Chameleon ({len(self._light_entities)} lights)"

        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": name,
            "manufacturer": "Chameleon",
            "model": "Scene Selector",
        }

    @property
    def native_value(self) -> float:
        """Return the current animation speed value."""
        return self._speed

    async def async_set_native_value(self, value: float) -> None:
        """Set the animation speed value."""
        self._speed = round(value, 1)
        _LOGGER.info("Animation speed set to %.1fs for %s", self._speed, self._light_entities)

        # Store animation speed in hass.data for other entities to use
        if DOMAIN not in self.hass.data:
            self.hass.data[DOMAIN] = {}
        if self._entry.entry_id not in self.hass.data[DOMAIN]:
            self.hass.data[DOMAIN][self._entry.entry_id] = {}

        self.hass.data[DOMAIN][self._entry.entry_id]["animation_speed"] = self._speed

        self.async_write_ha_state()

    @property
    def extra_state_attributes(self):
        """Return extra state attributes."""
        return {
            "light_entities": self._light_entities,
        }
