"""Tests for the Now Playing effect on the Chameleon light."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import State

from custom_components.chameleon import light as light_module
from custom_components.chameleon.const import NOW_PLAYING_EFFECT
from custom_components.chameleon.light_controller import ApplyColorsResult, LightResult

PLAYER = "media_player.lounge"
PALETTE = [(255, 0, 0), (0, 255, 0), (0, 0, 255)]
NP_NAME = "Now Playing - Lounge"


def _ok(_colors, _animated):
    return ApplyColorsResult([LightResult("light.one", True, PALETTE[0])])


def _make_light(hass: MagicMock, media_player: str | None = PLAYER, player_state: State | None = None):
    """A ChameleonLight with a fake tracker and patched extraction/apply."""
    states = {PLAYER: player_state or State(PLAYER, "playing", {"friendly_name": "Lounge"})}
    hass.states.get.side_effect = lambda eid: states.get(eid)
    hass.data = {}
    hass.services.async_call = AsyncMock()
    entry = MagicMock()
    entry.entry_id = "entry"
    with patch.object(light_module, "get_entity_base_name", return_value="test"):
        entity = light_module.ChameleonLight(hass, entry, ["light.one"], 0, media_player=media_player)
    entity.async_write_ha_state = MagicMock()

    tracker = MagicMock()
    tracker.media_player = PLAYER
    tracker.current_cover_key.return_value = "cover-1"
    tracker.async_fetch_cover = AsyncMock(return_value=b"img")
    if media_player is not None:
        entity._now_playing = tracker

    entity._extract_palette = AsyncMock(return_value=PALETTE)
    entity._apply_palette = AsyncMock(side_effect=_ok)
    entity._find_image_for_scene = AsyncMock(return_value=Path("/config/www/chameleon/sunset.jpg"))
    entity._cached_options = ["Sunset"]
    return entity, tracker, states


class TestEffectNaming:
    def test_listed_after_random(self, hass: MagicMock):
        entity, _, _ = _make_light(hass)
        assert entity.effect_list == ["Random", NP_NAME, "Sunset"]

    def test_absent_without_player(self, hass: MagicMock):
        entity, _, _ = _make_light(hass, media_player=None)
        assert entity.effect_list == ["Random", "Sunset"]

    def test_name_falls_back_to_object_id(self, hass: MagicMock):
        entity, _, states = _make_light(hass, player_state=State(PLAYER, "playing", {"friendly_name": "Lounge Speaker"}))
        assert entity.effect_list[1] == "Now Playing - Lounge Speaker"
        states.clear()  # player not loaded yet (startup ordering)
        assert entity.effect_list[1] == "Now Playing - Lounge"

    def test_effect_shows_display_name(self, hass: MagicMock):
        entity, _, _ = _make_light(hass)
        entity._effect = NOW_PLAYING_EFFECT
        assert entity.effect == NP_NAME

    def test_rename_follows_and_marker_survives(self, hass: MagicMock):
        entity, _, states = _make_light(hass)
        entity._effect = NOW_PLAYING_EFFECT
        entity._last_effect = NOW_PLAYING_EFFECT
        states[PLAYER] = State(PLAYER, "playing", {"friendly_name": "Living Room"})
        assert entity.effect == "Now Playing - Living Room"
        assert entity._last_effect == NOW_PLAYING_EFFECT


class TestEnter:
    @pytest.mark.asyncio
    async def test_enter_by_display_name_applies_cover(self, hass: MagicMock):
        entity, tracker, _ = _make_light(hass)
        await entity._apply_effect(NP_NAME)

        tracker.start.assert_called_once()
        entity._extract_palette.assert_awaited_once_with(b"img", False)
        assert entity._effect == NOW_PLAYING_EFFECT
        assert entity._last_effect == NOW_PLAYING_EFFECT
        assert entity._latest_cover_key == "cover-1"

    @pytest.mark.asyncio
    async def test_enter_by_marker(self, hass: MagicMock):
        """Bare turn_on restores _last_effect, which stores the marker."""
        entity, tracker, _ = _make_light(hass)
        await entity._apply_effect(NOW_PLAYING_EFFECT)
        tracker.start.assert_called_once()

    @pytest.mark.asyncio
    async def test_nothing_playing_falls_back_with_error(self, hass: MagicMock):
        entity, tracker, _ = _make_light(hass)
        entity._effect = "Sunset"
        tracker.current_cover_key.return_value = None

        await entity._apply_effect(NP_NAME)

        tracker.start.assert_not_called()
        assert entity._last_error == f"Nothing playing on {PLAYER}"
        assert entity._effect == "Sunset"

    @pytest.mark.asyncio
    async def test_missing_player_error(self, hass: MagicMock):
        entity, tracker, states = _make_light(hass)
        entity._effect = "Sunset"
        tracker.current_cover_key.return_value = None
        states.clear()

        await entity._apply_effect(NP_NAME)

        assert entity._last_error == f"{PLAYER} not found"

    @pytest.mark.asyncio
    async def test_fetch_failure_keeps_mode(self, hass: MagicMock):
        entity, tracker, _ = _make_light(hass)
        tracker.async_fetch_cover.return_value = None

        await entity._apply_effect(NP_NAME)

        assert entity._effect == NOW_PLAYING_EFFECT
        assert entity._last_error == f"Couldn't fetch cover art from {PLAYER}"
        entity._apply_palette.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unreadable_cover_keeps_mode(self, hass: MagicMock):
        entity, _, _ = _make_light(hass)
        entity._extract_palette.return_value = []

        await entity._apply_effect(NP_NAME)

        assert entity._effect == NOW_PLAYING_EFFECT
        assert entity._last_error == f"Couldn't read cover art from {PLAYER}"

    @pytest.mark.asyncio
    async def test_display_name_without_player_is_just_an_unknown_scene(self, hass: MagicMock):
        """Review focus 5: stale automation after the player was removed."""
        entity, _, _ = _make_light(hass, media_player=None)
        entity._find_image_for_scene = AsyncMock(return_value=None)

        await entity._apply_effect(NP_NAME)

        assert entity._last_error == f"Image not found for scene: {NP_NAME}"


class TestFallbackTarget:
    @pytest.mark.asyncio
    async def test_returns_to_scene_active_before(self, hass: MagicMock):
        entity, _, _ = _make_light(hass)
        entity._is_on = True
        entity._effect = "Sunset"
        await entity._apply_effect(NP_NAME)

        await entity._async_handle_now_playing_ended()

        assert entity._effect == "Sunset"

    @pytest.mark.asyncio
    async def test_entering_from_off_uses_last_effect(self, hass: MagicMock):
        entity, _, _ = _make_light(hass)
        entity._effect = None
        entity._last_effect = "Sunset"
        await entity._apply_effect(NP_NAME)
        assert entity._fallback_effect == "Sunset"

    @pytest.mark.asyncio
    async def test_reentry_never_makes_now_playing_its_own_fallback(self, hass: MagicMock):
        """Review focus 1: transition slider crossing zero re-applies the marker."""
        entity, tracker, _ = _make_light(hass)
        entity._is_on = True
        entity._effect = "Sunset"
        await entity._apply_effect(NP_NAME)

        await entity.async_reapply_current_scene()

        assert entity._fallback_effect == "Sunset"
        assert tracker.start.call_count == 1  # re-applied in place, not re-entered
        assert entity._effect == NOW_PLAYING_EFFECT

    @pytest.mark.asyncio
    async def test_no_previous_scene_falls_back_to_random(self, hass: MagicMock):
        entity, _, _ = _make_light(hass)
        entity._is_on = True
        await entity._apply_effect(NP_NAME)

        await entity._async_handle_now_playing_ended()

        assert entity._effect == "Sunset"  # Random picked the only scene

    @pytest.mark.asyncio
    async def test_fallback_scene_deleted(self, hass: MagicMock):
        """Review focus 3."""
        entity, tracker, _ = _make_light(hass)
        entity._is_on = True
        entity._effect = "Sunset"
        await entity._apply_effect(NP_NAME)
        entity._find_image_for_scene = AsyncMock(return_value=None)

        await entity._async_handle_now_playing_ended()

        assert entity._effect is None
        assert entity._last_error == "Image not found for scene: Sunset"
        tracker.stop.assert_called()


class TestCallbacks:
    @pytest.mark.asyncio
    async def test_cover_change_reapplies(self, hass: MagicMock):
        entity, tracker, _ = _make_light(hass)
        entity._is_on = True
        await entity._apply_effect(NP_NAME)
        entity._latest_cover_key = "cover-2"

        await entity._async_handle_cover("cover-2")

        assert tracker.async_fetch_cover.await_count == 2
        entity.async_write_ha_state.assert_called()

    @pytest.mark.asyncio
    async def test_superseded_cover_dropped(self, hass: MagicMock):
        entity, tracker, _ = _make_light(hass)
        entity._is_on = True
        await entity._apply_effect(NP_NAME)
        entity._latest_cover_key = "cover-3"

        await entity._async_handle_cover("cover-2")

        assert tracker.async_fetch_cover.await_count == 1

    @pytest.mark.asyncio
    async def test_cover_after_switching_effect_dropped(self, hass: MagicMock):
        entity, tracker, _ = _make_light(hass)
        entity._is_on = True
        entity._effect = "Sunset"
        entity._latest_cover_key = "cover-2"

        await entity._async_handle_cover("cover-2")

        tracker.async_fetch_cover.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_ended_after_switching_effect_dropped(self, hass: MagicMock):
        entity, _, _ = _make_light(hass)
        entity._is_on = True
        entity._effect = "Sunset"
        entity._find_image_for_scene.reset_mock()

        await entity._async_handle_now_playing_ended()

        entity._find_image_for_scene.assert_not_awaited()

    def test_on_cover_changed_schedules_and_records_key(self, hass: MagicMock):
        entity, _, _ = _make_light(hass)
        entity._on_cover_changed("cover-9")
        assert entity._latest_cover_key == "cover-9"
        entity._entry.async_create_task.assert_called_once()
        entity._entry.async_create_task.call_args.args[1].close()


class TestLeaving:
    @pytest.mark.asyncio
    async def test_turn_off_stops_tracker(self, hass: MagicMock):
        entity, tracker, _ = _make_light(hass)
        await entity._apply_effect(NP_NAME)
        await entity._do_turn_off()
        tracker.stop.assert_called()

    @pytest.mark.asyncio
    async def test_other_scene_stops_tracker(self, hass: MagicMock):
        entity, tracker, _ = _make_light(hass)
        await entity._apply_effect(NP_NAME)
        tracker.stop.reset_mock()
        await entity._apply_effect("Sunset")
        tracker.stop.assert_called()
        assert entity._effect == "Sunset"

    @pytest.mark.asyncio
    async def test_manual_color_stops_tracker(self, hass: MagicMock):
        entity, tracker, _ = _make_light(hass)
        entity._light_controller = MagicMock()
        entity._light_controller.apply_colors_to_lights = AsyncMock(return_value=ApplyColorsResult([LightResult("light.one", True, (1, 2, 3))]))
        await entity._apply_effect(NP_NAME)
        tracker.stop.reset_mock()
        await entity._apply_manual_color((1, 2, 3))
        tracker.stop.assert_called()


class TestPlayerStateUpdates:
    def _event(self, old: State | None, new: State | None) -> MagicMock:
        event = MagicMock()
        event.data = {"entity_id": PLAYER, "old_state": old, "new_state": new}
        return event

    def test_rename_writes_state(self, hass: MagicMock):
        """Review focus 2."""
        entity, _, _ = _make_light(hass)
        entity._async_media_player_changed(
            self._event(State(PLAYER, "idle", {"friendly_name": "Lounge"}), State(PLAYER, "idle", {"friendly_name": "Den"}))
        )
        entity.async_write_ha_state.assert_called_once()

    def test_track_change_in_now_playing_writes_state(self, hass: MagicMock):
        entity, _, _ = _make_light(hass)
        entity._effect = NOW_PLAYING_EFFECT
        old = State(PLAYER, "playing", {"friendly_name": "Lounge", "media_title": "A"})
        new = State(PLAYER, "playing", {"friendly_name": "Lounge", "media_title": "B"})
        entity._async_media_player_changed(self._event(old, new))
        entity.async_write_ha_state.assert_called_once()

    def test_unrelated_change_ignored(self, hass: MagicMock):
        entity, _, _ = _make_light(hass)
        old = State(PLAYER, "playing", {"friendly_name": "Lounge", "media_title": "A", "volume_level": 0.2})
        new = State(PLAYER, "playing", {"friendly_name": "Lounge", "media_title": "A", "volume_level": 0.3})
        entity._async_media_player_changed(self._event(old, new))
        entity.async_write_ha_state.assert_not_called()


class TestAttributes:
    def test_media_player_and_now_playing(self, hass: MagicMock):
        player = State(PLAYER, "playing", {"friendly_name": "Lounge", "media_artist": "Bowie", "media_title": "Heroes"})
        entity, _, _ = _make_light(hass, player_state=player)
        entity._effect = NOW_PLAYING_EFFECT
        attrs = entity.extra_state_attributes
        assert attrs["media_player"] == PLAYER
        assert attrs["now_playing"] == "Bowie - Heroes"

    def test_no_now_playing_outside_mode(self, hass: MagicMock):
        entity, _, _ = _make_light(hass)
        entity._effect = "Sunset"
        assert "now_playing" not in entity.extra_state_attributes

    def test_no_media_player_attr_without_player(self, hass: MagicMock):
        entity, _, _ = _make_light(hass, media_player=None)
        assert "media_player" not in entity.extra_state_attributes


class TestReviewFixes:
    """Findings from the final whole-branch review."""

    @pytest.mark.asyncio
    async def test_failed_switch_keeps_now_playing_consistent(self, hass: MagicMock):
        """Unknown effect while in Now Playing must not leave the mode with no tracker."""
        entity, tracker, _ = _make_light(hass)
        await entity._apply_effect(NP_NAME)
        tracker.stop.reset_mock()
        entity._find_image_for_scene = AsyncMock(return_value=None)

        await entity._apply_effect("Nope")

        tracker.stop.assert_not_called()
        assert entity._effect == NOW_PLAYING_EFFECT

    @pytest.mark.asyncio
    async def test_failed_manual_color_does_not_leave_stale_mode(self, hass: MagicMock):
        entity, tracker, _ = _make_light(hass)
        entity._light_controller = MagicMock()
        entity._light_controller.apply_colors_to_lights = AsyncMock(
            return_value=ApplyColorsResult([LightResult("light.one", False, error_message="unavailable")])
        )
        await entity._apply_effect(NP_NAME)

        await entity._apply_manual_color((1, 2, 3))

        tracker.stop.assert_called()
        assert entity._effect is None

    @pytest.mark.asyncio
    async def test_reapply_without_art_holds_mode(self, hass: MagicMock):
        """Slider crosses zero while radio (no art) plays: re-apply current colours, stay."""
        entity, tracker, _ = _make_light(hass)
        entity._is_on = True
        entity._effect = "Sunset"
        await entity._apply_effect(NP_NAME)
        entity._extracted_palette = PALETTE
        tracker.current_cover_key.return_value = None
        entity._apply_palette.reset_mock()

        await entity.async_reapply_current_scene()

        assert entity._effect == NOW_PLAYING_EFFECT
        assert entity._last_error is None
        assert tracker.start.call_count == 1  # not restarted: grace timer untouched
        entity._apply_palette.assert_awaited_once_with(PALETTE, False)

    @pytest.mark.asyncio
    async def test_reapply_with_art_refetches_without_restart(self, hass: MagicMock):
        entity, tracker, _ = _make_light(hass)
        entity._is_on = True
        await entity._apply_effect(NP_NAME)

        await entity.async_reapply_current_scene()

        assert tracker.async_fetch_cover.await_count == 2
        assert tracker.start.call_count == 1

    @pytest.mark.asyncio
    async def test_work_after_removal_is_dropped(self, hass: MagicMock):
        entity, tracker, _ = _make_light(hass)
        entity._is_on = True
        await entity._apply_effect(NP_NAME)
        entity._latest_cover_key = "cover-2"

        await entity.async_will_remove_from_hass()
        await entity._async_handle_cover("cover-2")
        await entity._async_handle_now_playing_ended()

        assert tracker.async_fetch_cover.await_count == 1
        entity._find_image_for_scene.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_off_effect_does_not_deadlock(self, hass: MagicMock):
        """Pre-existing: turn_on(effect="Off") re-took the entity lock and hung."""
        import asyncio

        entity, _, _ = _make_light(hass, media_player=None)
        entity._is_on = True

        await asyncio.wait_for(entity.async_turn_on(effect="Off"), timeout=1)

        assert entity._is_on is False
