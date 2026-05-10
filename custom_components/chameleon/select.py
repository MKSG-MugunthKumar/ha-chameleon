"""Select platform for Chameleon — animation mode picker.

The scene picker lives on the ``light`` platform (``effect``/``effect_list``);
this file just hosts the synchronized-vs-staggered mode select.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    ANIMATION_MODES,
    CONF_LIGHT_ENTITIES,
    CONF_LIGHT_ENTITY,
    DEFAULT_ANIMATION_MODE,
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
    """Set up the Chameleon animation mode select from a config entry."""
    if CONF_LIGHT_ENTITIES in entry.data:
        light_entities = entry.data[CONF_LIGHT_ENTITIES]
    else:
        light_entities = [entry.data[CONF_LIGHT_ENTITY]]

    async_add_entities(
        [ChameleonAnimationModeSelect(hass, entry, light_entities)],
        True,
    )


def _entry_data(hass: HomeAssistant, entry_id: str) -> dict:
    """Return (creating if needed) the per-entry runtime dict in hass.data."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    return domain_data.setdefault(entry_id, {})


class ChameleonAnimationModeSelect(SelectEntity):
    """Animation mode picker — synchronized vs staggered."""

    _attr_has_entity_name = True
    _attr_translation_key = "animation_mode"
    _attr_icon = "mdi:animation"

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        light_entities: list[str],
    ) -> None:
        """Initialize the animation mode select."""
        self.hass = hass
        self._entry = entry
        self._light_entities = light_entities
        self._attr_options = list(ANIMATION_MODES)
        self._current_option: str = DEFAULT_ANIMATION_MODE

        # Seed runtime data so the light entity sees the right mode immediately.
        _entry_data(hass, entry.entry_id)["animation_mode"] = self._current_option

        base_name = get_entity_base_name(hass, light_entities)
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_animation_mode"
        self.entity_id = f"select.chameleon_{base_name}_animation_mode"

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
    def current_option(self) -> str:
        """Return the currently selected mode."""
        return self._current_option

    @property
    def extra_state_attributes(self):
        """Return extra state attributes."""
        return {"light_entities": self._light_entities}

    async def async_select_option(self, option: str) -> None:
        """Handle a mode change.

        If an animation is running, push the new mode in live. Otherwise the
        new mode just takes effect on the next scene change.
        """
        if option not in ANIMATION_MODES:
            _LOGGER.warning("Unknown animation mode: %s", option)
            return

        self._current_option = option
        _entry_data(self.hass, self._entry.entry_id)["animation_mode"] = option
        _LOGGER.info("Animation mode set to '%s' for %s", option, self._light_entities)

        manager = self._get_animation_manager()
        if manager and manager.is_running(self._entry.entry_id):
            manager.update_mode(self._entry.entry_id, option)

        self.async_write_ha_state()
