"""Config flow for Chameleon integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .const import (
    CONF_ANIMATION_ENABLED,
    CONF_ANIMATION_SPEED,
    CONF_LIGHT_ENTITIES,
    DEFAULT_ANIMATION_ENABLED,
    DEFAULT_ANIMATION_SPEED,
    DOMAIN,
    MAX_ANIMATION_SPEED,
    MIN_ANIMATION_SPEED,
)
from .helpers import get_entry_title


class ChameleonConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Chameleon."""

    VERSION = 2  # Bumped for multi-light support

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            light_entities: list[str] = user_input[CONF_LIGHT_ENTITIES]

            # Create a unique ID from sorted light entities
            unique_id = "_".join(sorted(light_entities))
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

            # Create the config entry with area-aware naming
            title = get_entry_title(self.hass, light_entities)
            return self.async_create_entry(
                title=title,
                data=user_input,
            )

        # Show the form
        data_schema = vol.Schema(
            {
                vol.Required(CONF_LIGHT_ENTITIES): EntitySelector(
                    EntitySelectorConfig(
                        domain="light",
                        multiple=True,
                    )
                ),
                vol.Required(CONF_ANIMATION_ENABLED, default=DEFAULT_ANIMATION_ENABLED): BooleanSelector(),
                vol.Required(CONF_ANIMATION_SPEED, default=DEFAULT_ANIMATION_SPEED): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_ANIMATION_SPEED,
                        max=MAX_ANIMATION_SPEED,
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
