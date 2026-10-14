"""Tests for config_flow module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.chameleon.const import (
    CONF_LIGHT_ENTITIES,
    CONF_LIGHT_ENTITY,
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


def _mock_entry(entry_id: str, data: dict, unique_id: str | None = None) -> MagicMock:
    """Build a config entry stand-in."""
    entry = MagicMock()
    entry.entry_id = entry_id
    entry.data = data
    entry.unique_id = unique_id
    return entry


def _setup_reconfigure_flow(flow, hass, entry, other_entries=()):
    """Point the flow at an existing entry, with optional sibling entries."""
    flow.hass = hass
    flow.context = {"source": "reconfigure", "entry_id": entry.entry_id}
    flow._reconfigure_entry = entry
    flow._current_entries = [entry, *other_entries]


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


class TestChameleonReconfigureFlow:
    """Tests for the reconfigure step (add/remove member lights)."""

    @pytest.mark.asyncio
    async def test_form_prefilled_with_current_lights(self, hass: MagicMock):
        """The form opens pre-filled with the entry's current lights."""
        from custom_components.chameleon.config_flow import ChameleonConfigFlow

        entry = _mock_entry("abc", {CONF_LIGHT_ENTITIES: ["light.one", "light.two"], CONF_TRANSITION: 3})
        flow = ChameleonConfigFlow()
        _setup_reconfigure_flow(flow, hass, entry)

        result = await flow.async_step_reconfigure()

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "reconfigure"
        assert result["errors"] == {}
        assert flow.suggested_values == {CONF_LIGHT_ENTITIES: ["light.one", "light.two"]}

    @pytest.mark.asyncio
    async def test_form_prefilled_from_legacy_single_light(self, hass: MagicMock):
        """Pre-v2 entries stored one light under CONF_LIGHT_ENTITY."""
        from custom_components.chameleon.config_flow import ChameleonConfigFlow

        entry = _mock_entry("abc", {CONF_LIGHT_ENTITY: "light.old"})
        flow = ChameleonConfigFlow()
        _setup_reconfigure_flow(flow, hass, entry)

        await flow.async_step_reconfigure()

        assert flow.suggested_values == {CONF_LIGHT_ENTITIES: ["light.old"]}

    @pytest.mark.asyncio
    async def test_membership_change_updates_entry_in_place(self, hass: MagicMock):
        """Submitting a new set updates unique_id, title, and lights on the same entry."""
        from custom_components.chameleon.config_flow import ChameleonConfigFlow

        entry = _mock_entry("abc", {CONF_LIGHT_ENTITIES: ["light.one", "light.two"]}, "light.one_light.two")
        flow = ChameleonConfigFlow()
        _setup_reconfigure_flow(flow, hass, entry)

        with patch(TITLE_PATCH, return_value="Office") as title:
            result = await flow.async_step_reconfigure(user_input={CONF_LIGHT_ENTITIES: ["light.three", "light.one"]})

        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "reconfigure_successful"
        assert result["entry"] is entry
        assert result["updates"] == {
            "unique_id": "light.one_light.three",
            "title": "Office",
            "data_updates": {CONF_LIGHT_ENTITIES: ["light.three", "light.one"]},
        }
        title.assert_called_once_with(hass, ["light.three", "light.one"])

    @pytest.mark.asyncio
    async def test_resubmitting_same_lights_is_allowed(self, hass: MagicMock):
        """The entry's own unique_id is not a collision."""
        from custom_components.chameleon.config_flow import ChameleonConfigFlow

        entry = _mock_entry("abc", {CONF_LIGHT_ENTITIES: ["light.one"]}, "light.one")
        flow = ChameleonConfigFlow()
        _setup_reconfigure_flow(flow, hass, entry)

        with patch(TITLE_PATCH, return_value="One"):
            result = await flow.async_step_reconfigure(user_input={CONF_LIGHT_ENTITIES: ["light.one"]})

        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "reconfigure_successful"

    @pytest.mark.asyncio
    async def test_collision_with_other_entry_shows_error(self, hass: MagicMock):
        """Another entry already controlling the exact same lights blocks the change."""
        from custom_components.chameleon.config_flow import ChameleonConfigFlow

        entry = _mock_entry("abc", {CONF_LIGHT_ENTITIES: ["light.one"]}, "light.one")
        other = _mock_entry("xyz", {CONF_LIGHT_ENTITIES: ["light.two", "light.three"]}, "light.three_light.two")
        flow = ChameleonConfigFlow()
        _setup_reconfigure_flow(flow, hass, entry, [other])

        submitted = {CONF_LIGHT_ENTITIES: ["light.two", "light.three"]}
        result = await flow.async_step_reconfigure(user_input=submitted)

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "reconfigure"
        assert result["errors"] == {"base": "already_configured"}
        # The user's selection is kept on the re-shown form, not reset
        assert flow.suggested_values == submitted


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
