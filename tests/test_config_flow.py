"""Tests for config_flow module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.chameleon.const import (
    CONF_LIGHT_ENTITIES,
    CONF_TRANSITION,
)

# Import mocked FlowResultType from conftest
from tests.conftest import FlowResultType

# Use mocked SOURCE_USER constant
SOURCE_USER = "user"

# get_entry_title walks the area/device registries, which are bare MagicMocks
# here; patch it at the config_flow import site and test it separately.
TITLE_PATCH = "custom_components.chameleon.config_flow.get_entry_title"


def _setup_config_flow(flow, hass):
    """Common setup for config flow tests."""
    flow.hass = hass
    flow.context = {"source": SOURCE_USER}
    # Make async methods return coroutines
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = MagicMock()


class TestChameleonConfigFlow:
    """Tests for ChameleonConfigFlow user step."""

    @pytest.mark.asyncio
    async def test_form_shows_on_init(self, hass: MagicMock):
        """Test that form is shown on initialization."""
        from custom_components.chameleon.config_flow import ChameleonConfigFlow

        flow = ChameleonConfigFlow()
        _setup_config_flow(flow, hass)

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

        with patch(TITLE_PATCH, return_value="Bedroom Lamp"):
            result = await flow.async_step_user(
                user_input={
                    CONF_LIGHT_ENTITIES: ["light.bedroom_lamp"],
                    CONF_TRANSITION: 5,
                }
            )

        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["title"] == "Bedroom Lamp"
        assert result["data"][CONF_LIGHT_ENTITIES] == ["light.bedroom_lamp"]
        assert result["data"][CONF_TRANSITION] == 5
        flow.async_set_unique_id.assert_awaited_once_with("light.bedroom_lamp")

    @pytest.mark.asyncio
    async def test_unique_id_is_order_independent(self, hass: MagicMock):
        """The same set of lights in any order yields the same unique_id."""
        from custom_components.chameleon.config_flow import ChameleonConfigFlow

        flow = ChameleonConfigFlow()
        _setup_config_flow(flow, hass)

        with patch(TITLE_PATCH, return_value="Lights"):
            await flow.async_step_user(
                user_input={
                    CONF_LIGHT_ENTITIES: ["light.two", "light.one"],
                    CONF_TRANSITION: 10,
                }
            )

        flow.async_set_unique_id.assert_awaited_once_with("light.one_light.two")


class TestLightFriendlyName:
    """Tests for the helper that names a light for entry titles."""

    def test_with_friendly_name(self, hass: MagicMock):
        """Uses friendly_name when present."""
        from custom_components.chameleon.helpers import _get_light_friendly_name

        mock_state = MagicMock()
        mock_state.attributes = {"friendly_name": "My Lamp"}
        hass.states.get.return_value = mock_state

        assert _get_light_friendly_name(hass, "light.my_lamp") == "My Lamp"

    def test_fallback_without_state(self, hass: MagicMock):
        """Falls back to a title-cased object_id when no state exists."""
        from custom_components.chameleon.helpers import _get_light_friendly_name

        hass.states.get.return_value = None

        assert _get_light_friendly_name(hass, "light.bedroom_lamp") == "Bedroom Lamp"

    def test_fallback_without_friendly_name_attr(self, hass: MagicMock):
        """Falls back when state exists but has no friendly_name."""
        from custom_components.chameleon.helpers import _get_light_friendly_name

        mock_state = MagicMock()
        mock_state.attributes = {}
        hass.states.get.return_value = mock_state

        assert _get_light_friendly_name(hass, "light.kitchen_strip") == "Kitchen Strip"
