"""Tests for config_flow module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.chameleon.const import (
    CONF_ANIMATION_ENABLED,
    CONF_ANIMATION_SPEED,
    CONF_LIGHT_ENTITIES,
)

# Import mocked FlowResultType from conftest
from tests.conftest import FlowResultType

# Use mocked SOURCE_USER constant
SOURCE_USER = "user"


def _setup_config_flow(flow, hass):
    """Common setup for config flow tests."""
    flow.hass = hass
    flow.context = {"source": SOURCE_USER}
    # Make async methods return coroutines
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = MagicMock()


class TestChameleonConfigFlow:
    """Tests for ChameleonConfigFlow."""

    @pytest.mark.asyncio
    async def test_form_shows_on_init(self, hass: MagicMock):
        """Test that form is shown on initialization."""
        from custom_components.chameleon.config_flow import ChameleonConfigFlow

        flow = ChameleonConfigFlow()
        _setup_config_flow(flow, hass)

        # Patch async_show_form to capture what it's called with
        # since the actual voluptuous schema with selectors is HA-specific
        called_args = {}

        def mock_async_show_form(step_id, data_schema, errors=None):
            called_args["step_id"] = step_id
            called_args["errors"] = errors
            return {
                "type": FlowResultType.FORM,
                "step_id": step_id,
                "data_schema": data_schema,
                "errors": errors or {},
            }

        flow.async_show_form = mock_async_show_form

        result = await flow.async_step_user()

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "user"
        assert result["errors"] == {}

    @pytest.mark.asyncio
    async def test_create_entry_single_light(self, hass: MagicMock):
        """Test creating entry with single light."""
        from custom_components.chameleon.config_flow import ChameleonConfigFlow

        flow = ChameleonConfigFlow()
        _setup_config_flow(flow, hass)

        # Mock the state for friendly name lookup
        mock_state = MagicMock()
        mock_state.attributes = {"friendly_name": "Bedroom Lamp"}
        hass.states.get.return_value = mock_state

        result = await flow.async_step_user(
            user_input={
                CONF_LIGHT_ENTITIES: ["light.bedroom_lamp"],
                CONF_ANIMATION_ENABLED: False,
                CONF_ANIMATION_SPEED: 5,
            }
        )

        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["title"] == "Bedroom Lamp"
        assert result["data"][CONF_LIGHT_ENTITIES] == ["light.bedroom_lamp"]
        assert result["data"][CONF_ANIMATION_ENABLED] is False
        assert result["data"][CONF_ANIMATION_SPEED] == 5

    @pytest.mark.asyncio
    async def test_create_entry_multiple_lights(self, hass: MagicMock):
        """Test creating entry with multiple lights."""
        from custom_components.chameleon.config_flow import ChameleonConfigFlow

        flow = ChameleonConfigFlow()
        _setup_config_flow(flow, hass)

        # Mock friendly names
        def get_state(entity_id):
            names = {
                "light.one": "Light One",
                "light.two": "Light Two",
            }
            mock_state = MagicMock()
            mock_state.attributes = {"friendly_name": names.get(entity_id, entity_id)}
            return mock_state

        hass.states.get.side_effect = get_state

        result = await flow.async_step_user(
            user_input={
                CONF_LIGHT_ENTITIES: ["light.one", "light.two"],
                CONF_ANIMATION_ENABLED: True,
                CONF_ANIMATION_SPEED: 10,
            }
        )

        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["title"] == "Light One, Light Two"
        assert result["data"][CONF_ANIMATION_ENABLED] is True

    @pytest.mark.asyncio
    async def test_create_entry_many_lights(self, hass: MagicMock):
        """Test creating entry with many lights shows abbreviated title."""
        from custom_components.chameleon.config_flow import ChameleonConfigFlow

        flow = ChameleonConfigFlow()
        _setup_config_flow(flow, hass)

        # Mock friendly name for first light
        mock_state = MagicMock()
        mock_state.attributes = {"friendly_name": "First Light"}
        hass.states.get.return_value = mock_state

        result = await flow.async_step_user(
            user_input={
                CONF_LIGHT_ENTITIES: [
                    "light.one",
                    "light.two",
                    "light.three",
                    "light.four",
                ],
                CONF_ANIMATION_ENABLED: False,
                CONF_ANIMATION_SPEED: 5,
            }
        )

        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["title"] == "First Light + 3 more"

    def test_get_light_name_with_friendly_name(self, hass: MagicMock):
        """Test getting light name when friendly_name exists."""
        from custom_components.chameleon.config_flow import ChameleonConfigFlow

        flow = ChameleonConfigFlow()
        flow.hass = hass

        mock_state = MagicMock()
        mock_state.attributes = {"friendly_name": "My Lamp"}
        hass.states.get.return_value = mock_state

        name = flow._get_light_name("light.my_lamp")
        assert name == "My Lamp"

    def test_get_light_name_fallback(self, hass: MagicMock):
        """Test getting light name falls back to entity_id."""
        from custom_components.chameleon.config_flow import ChameleonConfigFlow

        flow = ChameleonConfigFlow()
        flow.hass = hass

        # No state exists
        hass.states.get.return_value = None

        name = flow._get_light_name("light.bedroom_lamp")
        assert name == "Bedroom Lamp"

    def test_get_light_name_no_friendly_name_attr(self, hass: MagicMock):
        """Test getting light name when state exists but no friendly_name."""
        from custom_components.chameleon.config_flow import ChameleonConfigFlow

        flow = ChameleonConfigFlow()
        flow.hass = hass

        mock_state = MagicMock()
        mock_state.attributes = {}  # No friendly_name
        hass.states.get.return_value = mock_state

        name = flow._get_light_name("light.kitchen_strip")
        assert name == "Kitchen Strip"
