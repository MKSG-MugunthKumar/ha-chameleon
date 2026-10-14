"""Config flow for Chameleon integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .const import (
    CONF_LIGHT_ENTITIES,
    CONF_LIGHT_ENTITY,
    CONF_TRANSITION,
    DEFAULT_TRANSITION,
    DOMAIN,
    MAX_TRANSITION,
    MIN_TRANSITION,
)
from .helpers import get_entry_title


class ChameleonConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Chameleon."""

    VERSION = 4  # v4 collapses scene select + brightness number into a single light entity with EFFECT support

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            light_entities: list[str] = user_input[CONF_LIGHT_ENTITIES]

            unique_id = "_".join(sorted(light_entities))
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

            title = get_entry_title(self.hass, light_entities)
            return self.async_create_entry(
                title=title,
                data=user_input,
            )

        # Transition default; runtime control is via number.chameleon_{light}_transition
        # (set to 0 to disable animation entirely).
        data_schema = vol.Schema(
            {
                vol.Required(CONF_LIGHT_ENTITIES): EntitySelector(
                    EntitySelectorConfig(
                        domain="light",
                        multiple=True,
                    )
                ),
                vol.Required(CONF_TRANSITION, default=DEFAULT_TRANSITION): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_TRANSITION,
                        max=MAX_TRANSITION,
                        step=0.1,
                        unit_of_measurement="seconds",
                        mode=NumberSelectorMode.SLIDER,
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Let the user add or remove member lights on an existing entry.

        The entry's unique_id is derived from the sorted light list, so a
        membership change also changes the unique_id. The standard
        ``_abort_if_unique_id_mismatch()`` guard therefore doesn't apply; instead
        we reject only a collision with a *different* entry that already controls
        the exact same set of lights. Entities are keyed on ``entry_id``, which
        survives the reconfigure, so names, areas, and automations stay intact.
        """
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            light_entities: list[str] = user_input[CONF_LIGHT_ENTITIES]
            unique_id = "_".join(sorted(light_entities))

            collision = any(
                other.unique_id == unique_id and other.entry_id != entry.entry_id for other in self._async_current_entries(include_ignore=False)
            )
            if collision:
                errors["base"] = "already_configured"
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    unique_id=unique_id,
                    title=get_entry_title(self.hass, light_entities),
                    data_updates={CONF_LIGHT_ENTITIES: light_entities},
                )

        # Pre-v2 entries stored a single light under CONF_LIGHT_ENTITY
        current_lights: list[str] = entry.data.get(CONF_LIGHT_ENTITIES) or [entry.data[CONF_LIGHT_ENTITY]]
        suggested = user_input if user_input is not None else {CONF_LIGHT_ENTITIES: current_lights}

        data_schema = vol.Schema(
            {
                vol.Required(CONF_LIGHT_ENTITIES): EntitySelector(
                    EntitySelectorConfig(
                        domain="light",
                        multiple=True,
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(data_schema, suggested),
            errors=errors,
        )
