"""Number platform for Chameleon: brightness and animation speed sliders.

Both sliders use **semantic zero-values**:

- ``brightness == 0`` → behaves like the "Off" scene (lights off). Going back
  above zero restores the previously-applied scene at the new brightness.
- ``animation_speed == 0`` → static mode. Any running animation is stopped and
  the current scene is re-applied as a static color/palette.

Live updates: while an animation is running, slider drags push the new value
into the running controller without restarting it.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

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
from .helpers import get_chameleon_device_name, get_entity_base_name

if TYPE_CHECKING:
    from .animations import AnimationManager
    from .select import ChameleonSceneSelect

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Chameleon number entities from a config entry."""
    _LOGGER.debug("Setting up Chameleon number entities for entry: %s", entry.entry_id)

    if CONF_LIGHT_ENTITIES in entry.data:
        light_entities = entry.data[CONF_LIGHT_ENTITIES]
    else:
        light_entities = [entry.data[CONF_LIGHT_ENTITY]]

    initial_animation_speed = entry.data.get(CONF_ANIMATION_SPEED, DEFAULT_ANIMATION_SPEED)

    async_add_entities(
        [
            ChameleonBrightnessNumber(hass, entry, light_entities),
            ChameleonAnimationSpeedNumber(hass, entry, light_entities, initial_animation_speed),
        ],
        True,
    )


def _entry_data(hass: HomeAssistant, entry_id: str) -> dict:
    """Return (creating if needed) the per-entry runtime dict in hass.data."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    return domain_data.setdefault(entry_id, {})


def _get_scene_select(hass: HomeAssistant, entry_id: str) -> ChameleonSceneSelect | None:
    """Look up the registered scene select entity for this config entry."""
    return _entry_data(hass, entry_id).get("scene_select")


def _get_animation_manager(hass: HomeAssistant) -> AnimationManager | None:
    """Look up the shared animation manager."""
    return hass.data.get(DOMAIN, {}).get("animation_manager")


class ChameleonBrightnessNumber(NumberEntity):
    """Brightness slider. Value of 0 = lights off; remembers last non-zero."""

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
        self._last_nonzero = DEFAULT_BRIGHTNESS  # restored when slider goes 0 → >0

        base_name = get_entity_base_name(hass, light_entities)
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_brightness"
        self.entity_id = f"number.chameleon_{base_name}_brightness"

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
    def native_value(self) -> float:
        """Return the current brightness percentage (0-100)."""
        return self._brightness

    async def async_set_native_value(self, value: float) -> None:
        """Handle a slider change.

        - 0 → turn lights off; remember scene state.
        - 0 → >0 → ask the select to re-apply the current scene.
        - >0 → >0 → push to running animation (or apply directly to lights).
        """
        new_value = int(value)
        previous = self._brightness
        self._brightness = new_value

        _entry_data(self.hass, self._entry.entry_id)["brightness"] = new_value

        if new_value > 0:
            self._last_nonzero = new_value

        _LOGGER.info(
            "Brightness %d%% → %d%% for %s",
            previous,
            new_value,
            self._light_entities,
        )

        if new_value == 0:
            await self._turn_off_lights()
        elif previous == 0:
            # Coming back from off — replay the active scene at new brightness.
            await self._reapply_current_scene()
        else:
            # Live update: push to running animation if any, else just bump
            # brightness on the lights without disturbing color.
            manager = _get_animation_manager(self.hass)
            if manager and manager.is_running(self._entry.entry_id):
                manager.update_brightness(self._entry.entry_id, new_value)
            await self._apply_brightness_to_lights()

        self.async_write_ha_state()

    async def _turn_off_lights(self) -> None:
        """Turn off all configured lights and stop any running animation."""
        manager = _get_animation_manager(self.hass)
        if manager:
            await manager.stop(self._entry.entry_id)

        for light_entity in self._light_entities:
            try:
                await self.hass.services.async_call(
                    "light",
                    "turn_off",
                    {"entity_id": light_entity},
                    blocking=True,
                )
            except Exception:
                _LOGGER.exception("Failed to turn off %s", light_entity)

    async def _apply_brightness_to_lights(self) -> None:
        """Bump brightness on lights without changing color."""
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
            except Exception:
                _LOGGER.exception("Failed to apply brightness to %s", light_entity)

    async def _reapply_current_scene(self) -> None:
        """Ask the scene select to re-apply its current scene with new state."""
        select = _get_scene_select(self.hass, self._entry.entry_id)
        if select is not None:
            await select.async_reapply_current_scene()

    @property
    def extra_state_attributes(self):
        """Return extra state attributes."""
        return {
            "light_entities": self._light_entities,
            "brightness_255": int((self._brightness / 100) * 255),
            "last_nonzero": self._last_nonzero,
        }


class ChameleonAnimationSpeedNumber(NumberEntity):
    """Animation speed slider. Value of 0 = static (no animation loop)."""

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
        # Clamp to the current allowed range — older config entries may have stored
        # values from a wider range (the slider used to go up to 60s).
        self._speed = max(MIN_ANIMATION_SPEED, min(MAX_ANIMATION_SPEED, float(initial_speed)))
        self._last_nonzero = self._speed if self._speed > 0 else float(DEFAULT_ANIMATION_SPEED)

        # Seed runtime data so the select's initial read sees a valid speed.
        _entry_data(hass, entry.entry_id)["animation_speed"] = self._speed

        base_name = get_entity_base_name(hass, light_entities)
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_animation_speed"
        self.entity_id = f"number.chameleon_{base_name}_animation_speed"

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
    def native_value(self) -> float:
        """Return the current animation speed (seconds per tick)."""
        return self._speed

    async def async_set_native_value(self, value: float) -> None:
        """Handle a slider change.

        - 0 → stop animation; re-apply current scene as static.
        - 0 → >0 → re-apply current scene with animation enabled.
        - >0 → >0 → push live speed update to the running controller.
        """
        new_value = round(float(value), 1)
        previous = self._speed
        self._speed = new_value

        _entry_data(self.hass, self._entry.entry_id)["animation_speed"] = new_value

        if new_value > 0:
            self._last_nonzero = new_value

        _LOGGER.info(
            "Animation speed %.1fs → %.1fs for %s",
            previous,
            new_value,
            self._light_entities,
        )

        crossed_zero_boundary = (previous == 0) != (new_value == 0)
        if crossed_zero_boundary:
            # Switch between static and animated: full re-apply.
            await self._reapply_current_scene()
        else:
            # Same mode: live-update the running controller (no-op if not running).
            manager = _get_animation_manager(self.hass)
            if manager:
                manager.update_speed(self._entry.entry_id, new_value)

        self.async_write_ha_state()

    async def _reapply_current_scene(self) -> None:
        """Ask the scene select to re-apply its current scene."""
        select = _get_scene_select(self.hass, self._entry.entry_id)
        if select is not None:
            await select.async_reapply_current_scene()

    @property
    def extra_state_attributes(self):
        """Return extra state attributes."""
        return {
            "light_entities": self._light_entities,
            "last_nonzero": self._last_nonzero,
        }
