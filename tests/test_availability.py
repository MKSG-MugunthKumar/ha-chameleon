"""Tests for member light availability: the facade, recovery, and the animation loop."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import State

from custom_components.chameleon.light_controller import LightResult, is_light_reachable

LIGHTS = ["light.one", "light.two"]
PALETTE = [(255, 0, 0), (0, 255, 0), (0, 0, 255)]


def _states(mapping: dict[str, str]):
    """Build a hass.states.get side effect from {entity_id: state}."""

    def get(entity_id):
        if entity_id not in mapping:
            return None
        return State(entity_id, mapping[entity_id])

    return get


def _make_light(hass: MagicMock, lights=LIGHTS):
    """Construct a ChameleonLight against the mocked hass."""
    from custom_components.chameleon import light as light_module

    entry = MagicMock()
    entry.entry_id = "entry"
    hass.data = {}
    with patch.object(light_module, "get_entity_base_name", return_value="test"):
        entity = light_module.ChameleonLight(hass, entry, list(lights), 0)
    entity.async_write_ha_state = MagicMock()
    entity._light_controller = MagicMock()
    entity._light_controller.apply_color_to_light = AsyncMock(side_effect=lambda eid, color, **_: LightResult(eid, True, color))
    return entity


def _change_event(entity_id: str, old: str | None, new: str | None) -> MagicMock:
    event = MagicMock()
    event.data = {
        "entity_id": entity_id,
        "old_state": State(entity_id, old) if old is not None else None,
        "new_state": State(entity_id, new) if new is not None else None,
    }
    return event


class TestIsLightReachable:
    """The shared reachability rule."""

    @pytest.mark.parametrize(
        ("state", "expected"),
        [("on", True), ("off", True), ("unavailable", False), ("unknown", False)],
    )
    def test_states(self, state: str, expected: bool):
        assert is_light_reachable(State("light.x", state)) is expected

    def test_missing_entity(self):
        assert is_light_reachable(None) is False


class TestFacadeAvailability:
    """light.chameleon_* follows the light-group rule."""

    def test_available_while_any_member_reachable(self, hass: MagicMock):
        hass.states.get.side_effect = _states({"light.one": "unavailable", "light.two": "on"})
        entity = _make_light(hass)

        assert entity.available is True
        assert entity.extra_state_attributes["unavailable_lights"] == ["light.one"]

    def test_unavailable_when_all_members_gone(self, hass: MagicMock):
        """The mains-off case: every member drops out together."""
        hass.states.get.side_effect = _states({"light.one": "unavailable", "light.two": "unavailable"})
        entity = _make_light(hass)

        assert entity.available is False
        assert entity.extra_state_attributes["unavailable_lights"] == LIGHTS

    def test_attribute_empty_when_all_reachable(self, hass: MagicMock):
        hass.states.get.side_effect = _states({"light.one": "on", "light.two": "off"})
        entity = _make_light(hass)

        assert entity.available is True
        assert entity.extra_state_attributes["unavailable_lights"] == []


class TestMemberStateListener:
    """Only reachability flips matter; color ticks are ignored."""

    def test_color_tick_is_ignored(self, hass: MagicMock):
        entity = _make_light(hass)
        entity._async_member_state_changed(_change_event("light.one", "on", "on"))

        entity.async_write_ha_state.assert_not_called()
        entity._entry.async_create_task.assert_not_called()

    def test_going_unreachable_writes_state_without_restore(self, hass: MagicMock):
        entity = _make_light(hass)
        entity._async_member_state_changed(_change_event("light.one", "on", "unavailable"))

        entity.async_write_ha_state.assert_called_once()
        entity._entry.async_create_task.assert_not_called()

    def test_recovery_writes_state_and_schedules_restore(self, hass: MagicMock):
        entity = _make_light(hass)
        entity._async_member_state_changed(_change_event("light.one", "unavailable", "on"))

        entity.async_write_ha_state.assert_called_once()
        entity._entry.async_create_task.assert_called_once()
        # Close the scheduled coroutine; we don't run it here
        entity._entry.async_create_task.call_args.args[1].close()


class TestRestoreMember:
    """Static scenes and manual colors are re-pushed on recovery."""

    @pytest.mark.asyncio
    async def test_static_scene_reapplies_palette_color_by_index(self, hass: MagicMock):
        entity = _make_light(hass)
        entity._is_on = True
        entity._effect = "Sunset"
        entity._extracted_palette = PALETTE

        await entity._async_restore_member("light.two")

        entity._light_controller.apply_color_to_light.assert_awaited_once_with("light.two", PALETTE[1], brightness=entity._brightness_pct)
        assert entity._applied_colors["light.two"] == PALETTE[1]

    @pytest.mark.asyncio
    async def test_manual_color_reapplied(self, hass: MagicMock):
        entity = _make_light(hass)
        entity._is_on = True
        entity._manual_color = (10, 20, 30)

        await entity._async_restore_member("light.one")

        entity._light_controller.apply_color_to_light.assert_awaited_once_with("light.one", (10, 20, 30), brightness=entity._brightness_pct)

    @pytest.mark.asyncio
    async def test_recovered_light_clears_its_failure(self, hass: MagicMock):
        entity = _make_light(hass)
        entity._is_on = True
        entity._manual_color = (10, 20, 30)
        entity._failed_lights = {"light.one": "unavailable", "light.two": "unavailable"}

        await entity._async_restore_member("light.one")

        assert entity._failed_lights == {"light.two": "unavailable"}

    @pytest.mark.asyncio
    async def test_noop_when_chameleon_is_off(self, hass: MagicMock):
        """Don't relight a bulb the user switched off."""
        entity = _make_light(hass)
        entity._is_on = False
        entity._manual_color = (10, 20, 30)

        await entity._async_restore_member("light.one")

        entity._light_controller.apply_color_to_light.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_noop_while_animating(self, hass: MagicMock):
        """The animation loop owns recovery for animated scenes."""
        entity = _make_light(hass)
        entity._is_on = True
        entity._effect = "Sunset"
        entity._extracted_palette = PALETTE
        manager = MagicMock()
        manager.is_running.return_value = True
        hass.data = {"chameleon": {"animation_manager": manager}}

        await entity._async_restore_member("light.one")

        entity._light_controller.apply_color_to_light.assert_not_awaited()


class TestAnimationLoopSkipsUnreachable:
    """The loop sits out ticks for unreachable lights but keeps their phase."""

    @staticmethod
    def _controller(hass: MagicMock, transition: float):
        from custom_components.chameleon.animations import AnimationController
        from custom_components.chameleon.const import TRANSITION_STYLE_SYNC

        return AnimationController(hass, ["light.one"], PALETTE, transition, style=TRANSITION_STYLE_SYNC)

    @pytest.mark.asyncio
    async def test_reachable_light_gets_full_ticks(self, hass: MagicMock):
        hass.states.get.side_effect = _states({"light.one": "on"})
        controller = self._controller(hass, transition=0.05)

        await controller.start()
        await asyncio.sleep(0.12)
        await controller.stop()

        calls = hass.services.async_call.await_args_list
        assert calls[0].args[2]["rgb_color"] == list(PALETTE[0])
        assert calls[0].args[2]["transition"] == 0.05

    @pytest.mark.asyncio
    async def test_no_calls_while_unreachable(self, hass: MagicMock):
        hass.states.get.side_effect = _states({"light.one": "unavailable"})
        controller = self._controller(hass, transition=0.05)

        with patch("custom_components.chameleon.animations._UNREACHABLE_POLL_SECONDS", 0.01):
            await controller.start()
            await asyncio.sleep(0.15)
            await controller.stop()

        hass.services.async_call.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_recovers_mid_tick_on_the_same_beat(self, hass: MagicMock):
        """Back mid-tick: this tick's color, faded over only the time left."""
        loop = asyncio.get_running_loop()
        back_at = loop.time() + 0.03
        hass.states.get.side_effect = lambda eid: State(eid, "on" if loop.time() >= back_at else "unavailable")
        controller = self._controller(hass, transition=0.1)

        with patch("custom_components.chameleon.animations._UNREACHABLE_POLL_SECONDS", 0.01):
            await controller.start()
            await asyncio.sleep(0.15)
            await controller.stop()

        calls = hass.services.async_call.await_args_list
        first, second = calls[0].args[2], calls[1].args[2]
        assert first["rgb_color"] == list(PALETTE[0])
        assert 0 < first["transition"] < 0.1
        # Phase kept: the next tick moves on to the next color at full length
        assert second["rgb_color"] == list(PALETTE[1])
        assert second["transition"] == 0.1

    @pytest.mark.asyncio
    async def test_whole_tick_missed_advances_color(self, hass: MagicMock):
        """Gone for a full tick: it rejoins on the color its peers are on."""
        loop = asyncio.get_running_loop()
        back_at = loop.time() + 0.07
        hass.states.get.side_effect = lambda eid: State(eid, "on" if loop.time() >= back_at else "unavailable")
        controller = self._controller(hass, transition=0.05)

        with patch("custom_components.chameleon.animations._UNREACHABLE_POLL_SECONDS", 0.005):
            await controller.start()
            await asyncio.sleep(0.09)
            await controller.stop()

        first = hass.services.async_call.await_args_list[0].args[2]
        assert first["rgb_color"] == list(PALETTE[1])
