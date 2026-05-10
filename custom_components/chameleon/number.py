"""Number platform for Chameleon: transition slider.

Brightness is owned by the light entity (since light entities have native
brightness support). This platform only exposes the transition slider.

Semantic zero-value: ``transition == 0`` → static mode. Any running animation
is stopped and the current scene is re-applied as a static color or palette.

Live updates: while an animation is running, slider drags push the new value
into the running controller without restarting it.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_LIGHT_ENTITIES,
    CONF_LIGHT_ENTITY,
    CONF_TRANSITION,
    DEFAULT_TRANSITION,
    DOMAIN,
    MAX_TRANSITION,
    MIN_TRANSITION,
)
from .helpers import get_chameleon_device_name, get_entity_base_name

if TYPE_CHECKING:
    from .animations import AnimationManager
    from .light import ChameleonLight

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Chameleon transition number entity from a config entry."""
    if CONF_LIGHT_ENTITIES in entry.data:
        light_entities = entry.data[CONF_LIGHT_ENTITIES]
    else:
        light_entities = [entry.data[CONF_LIGHT_ENTITY]]

    initial_transition = entry.data.get(CONF_TRANSITION, DEFAULT_TRANSITION)

    async_add_entities(
        [ChameleonTransitionNumber(hass, entry, light_entities, initial_transition)],
        True,
    )


def _entry_data(hass: HomeAssistant, entry_id: str) -> dict:
    """Return (creating if needed) the per-entry runtime dict in hass.data."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    return domain_data.setdefault(entry_id, {})


def _get_chameleon_light(hass: HomeAssistant, entry_id: str) -> ChameleonLight | None:
    """Look up the registered Chameleon light entity for this config entry."""
    return _entry_data(hass, entry_id).get("chameleon_light")


def _get_animation_manager(hass: HomeAssistant) -> AnimationManager | None:
    """Look up the shared animation manager."""
    return hass.data.get(DOMAIN, {}).get("animation_manager")


class ChameleonTransitionNumber(NumberEntity):
    """Transition slider. Value of 0 = static (no animation loop)."""

    _attr_has_entity_name = True
    _attr_translation_key = "transition"
    _attr_native_min_value = MIN_TRANSITION
    _attr_native_max_value = MAX_TRANSITION
    _attr_native_step = 0.1
    _attr_native_unit_of_measurement = "s"
    _attr_mode = NumberMode.SLIDER
    _attr_icon = "mdi:transition"

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        light_entities: list[str],
        initial_transition: float,
    ) -> None:
        """Initialize the transition number entity."""
        self.hass = hass
        self._entry = entry
        self._light_entities = light_entities
        # Clamp to the current allowed range — older config entries may have stored
        # values from a wider range (the slider used to go up to 60s).
        self._transition = max(MIN_TRANSITION, min(MAX_TRANSITION, float(initial_transition)))
        self._last_nonzero = self._transition if self._transition > 0 else float(DEFAULT_TRANSITION)

        # Seed runtime data so the light's initial read sees a valid transition.
        _entry_data(hass, entry.entry_id)["transition"] = self._transition

        base_name = get_entity_base_name(hass, light_entities)
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_transition"
        self.entity_id = f"number.chameleon_{base_name}_transition"

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
        """Return the current transition (seconds per fade)."""
        return self._transition

    async def async_set_native_value(self, value: float) -> None:
        """Handle a slider change.

        - 0 → stop animation; re-apply current scene as static.
        - 0 → >0 → re-apply current scene with animation enabled.
        - >0 → >0 → push live transition update to the running controller.
        """
        new_value = round(float(value), 1)
        previous = self._transition
        self._transition = new_value

        _entry_data(self.hass, self._entry.entry_id)["transition"] = new_value

        if new_value > 0:
            self._last_nonzero = new_value

        _LOGGER.info(
            "Transition %.1fs → %.1fs for %s",
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
                manager.update_transition(self._entry.entry_id, new_value)

        self.async_write_ha_state()

    async def _reapply_current_scene(self) -> None:
        """Ask the Chameleon light entity to re-apply its current scene."""
        light = _get_chameleon_light(self.hass, self._entry.entry_id)
        if light is not None:
            await light.async_reapply_current_scene()

    @property
    def extra_state_attributes(self):
        """Return extra state attributes."""
        return {
            "light_entities": self._light_entities,
            "last_nonzero": self._last_nonzero,
        }
