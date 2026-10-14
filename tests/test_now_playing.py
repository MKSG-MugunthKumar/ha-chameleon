"""Tests for the Now Playing media player tracker."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import State

from custom_components.chameleon import now_playing
from custom_components.chameleon.now_playing import NowPlayingTracker, cover_key

PLAYER = "media_player.lounge"


def _player(state: str, picture: str | None = None, **attrs) -> State:
    attributes = dict(attrs)
    if picture is not None:
        attributes["entity_picture"] = picture
    return State(PLAYER, state, attributes)


def _proxy(cache: str, token: str = "t1") -> str:
    return f"/api/media_player_proxy/{PLAYER}?token={token}&cache={cache}"


def _event(old: State | None, new: State | None) -> MagicMock:
    event = MagicMock()
    event.data = {"entity_id": PLAYER, "old_state": old, "new_state": new}
    return event


class TestCoverKey:
    def test_proxy_url_uses_cache_param(self):
        assert cover_key(_player("playing", _proxy("abc"))) == "abc"

    def test_token_rotation_keeps_key(self):
        assert cover_key(_player("playing", _proxy("abc", "t1"))) == cover_key(_player("playing", _proxy("abc", "t2")))

    def test_remote_url_without_cache_uses_whole_string(self):
        url = "https://art.example/cover.jpg"
        assert cover_key(_player("playing", url)) == url

    def test_paused_counts(self):
        assert cover_key(_player("paused", _proxy("abc"))) == "abc"

    @pytest.mark.parametrize("state", ["idle", "off", "standby", "unavailable"])
    def test_inactive_states_have_no_key(self, state: str):
        assert cover_key(_player(state, _proxy("abc"))) is None

    def test_no_picture(self):
        assert cover_key(_player("playing")) is None

    def test_missing_entity(self):
        assert cover_key(None) is None


@pytest.fixture
def tracking(hass: MagicMock):
    """Start a tracker with captured HA hooks; yields (tracker, hooks, on_cover, on_fallback)."""
    hooks: dict = {"unsub": MagicMock(), "cancel_timer": MagicMock()}

    def fake_track(_hass, entity_ids, handler):
        hooks["entity_ids"] = entity_ids
        hooks["handler"] = handler
        return hooks["unsub"]

    def fake_call_later(_hass, delay, action):
        hooks["delay"] = delay
        hooks["timer_action"] = action
        return hooks["cancel_timer"]

    hass.states.get.return_value = _player("playing", _proxy("first"))
    with (
        patch.object(now_playing, "async_track_state_change_event", side_effect=fake_track),
        patch.object(now_playing, "async_call_later", side_effect=fake_call_later) as call_later,
    ):
        hooks["call_later"] = call_later
        tracker = NowPlayingTracker(hass, PLAYER)
        on_cover, on_fallback = MagicMock(), MagicMock()
        tracker.start(on_cover, on_fallback)
        yield tracker, hooks, on_cover, on_fallback


class TestTracker:
    def test_start_subscribes_to_the_player(self, tracking):
        tracker, hooks, _, _ = tracking
        assert hooks["entity_ids"] == [PLAYER]
        assert tracker.is_running is True

    def test_new_cover_fires_on_cover(self, tracking):
        _, hooks, on_cover, _ = tracking
        hooks["handler"](_event(_player("playing", _proxy("first")), _player("playing", _proxy("second"))))
        on_cover.assert_called_once_with("second")

    def test_token_rotation_is_not_a_new_cover(self, tracking):
        _, hooks, on_cover, _ = tracking
        hooks["handler"](_event(None, _player("playing", _proxy("first", token="rotated"))))
        on_cover.assert_not_called()

    def test_pause_holds(self, tracking):
        _, hooks, on_cover, _ = tracking
        hooks["handler"](_event(None, _player("paused", _proxy("first"))))
        on_cover.assert_not_called()
        hooks["call_later"].assert_not_called()

    def test_playing_without_artwork_holds(self, tracking):
        """Review focus 4: radio/line-in mid-session keeps the current colours."""
        _, hooks, on_cover, on_fallback = tracking
        hooks["handler"](_event(None, _player("playing")))
        on_cover.assert_not_called()
        hooks["call_later"].assert_not_called()
        on_fallback.assert_not_called()

    @pytest.mark.parametrize("state", ["idle", "off", "standby", "unavailable"])
    def test_inactive_starts_grace_timer(self, tracking, state: str):
        _, hooks, _, on_fallback = tracking
        hooks["handler"](_event(None, _player(state)))
        assert hooks["delay"] == 30.0
        on_fallback.assert_not_called()

    def test_grace_timer_started_once(self, tracking):
        _, hooks, _, _ = tracking
        hooks["handler"](_event(None, _player("idle")))
        hooks["handler"](_event(None, _player("off")))
        assert hooks["call_later"].call_count == 1

    def test_resume_within_grace_cancels(self, tracking):
        _, hooks, _, on_fallback = tracking
        hooks["handler"](_event(None, _player("idle")))
        hooks["handler"](_event(None, _player("playing", _proxy("first"))))
        hooks["cancel_timer"].assert_called_once()
        on_fallback.assert_not_called()

    def test_grace_expiry_stops_and_falls_back(self, tracking):
        tracker, hooks, _, on_fallback = tracking
        hooks["handler"](_event(None, _player("idle")))
        hooks["timer_action"](None)
        on_fallback.assert_called_once()
        hooks["unsub"].assert_called_once()
        assert tracker.is_running is False

    def test_entity_removed_starts_grace(self, tracking):
        _, hooks, _, _ = tracking
        hooks["handler"](_event(_player("playing", _proxy("first")), None))
        assert hooks["delay"] == 30.0

    def test_stop_cancels_listener_and_timer(self, tracking):
        tracker, hooks, _, _ = tracking
        hooks["handler"](_event(None, _player("idle")))
        tracker.stop()
        hooks["unsub"].assert_called_once()
        hooks["cancel_timer"].assert_called_once()
        tracker.stop()  # idempotent
        hooks["unsub"].assert_called_once()

    def test_restart_does_not_double_subscribe(self, tracking):
        tracker, hooks, on_cover, on_fallback = tracking
        tracker.start(on_cover, on_fallback)
        hooks["unsub"].assert_called_once()  # old subscription released first


class TestFetchCover:
    @pytest.mark.asyncio
    async def test_returns_bytes_from_entity(self, hass: MagicMock):
        entity = MagicMock()
        entity.async_get_media_image = AsyncMock(return_value=(b"img", "image/jpeg"))
        component = MagicMock()
        component.get_entity.return_value = entity
        hass.data = {"media_player": component}

        assert await NowPlayingTracker(hass, PLAYER).async_fetch_cover() == b"img"
        component.get_entity.assert_called_once_with(PLAYER)

    @pytest.mark.asyncio
    async def test_missing_entity_returns_none(self, hass: MagicMock):
        component = MagicMock()
        component.get_entity.return_value = None
        hass.data = {"media_player": component}

        assert await NowPlayingTracker(hass, PLAYER).async_fetch_cover() is None

    @pytest.mark.asyncio
    async def test_no_component_returns_none(self, hass: MagicMock):
        hass.data = {}
        assert await NowPlayingTracker(hass, PLAYER).async_fetch_cover() is None

    @pytest.mark.asyncio
    async def test_empty_image_returns_none(self, hass: MagicMock):
        entity = MagicMock()
        entity.async_get_media_image = AsyncMock(return_value=(None, None))
        component = MagicMock()
        component.get_entity.return_value = entity
        hass.data = {"media_player": component}

        assert await NowPlayingTracker(hass, PLAYER).async_fetch_cover() is None

    @pytest.mark.asyncio
    async def test_error_returns_none(self, hass: MagicMock):
        entity = MagicMock()
        entity.async_get_media_image = AsyncMock(side_effect=RuntimeError("boom"))
        component = MagicMock()
        component.get_entity.return_value = entity
        hass.data = {"media_player": component}

        assert await NowPlayingTracker(hass, PLAYER).async_fetch_cover() is None

    @pytest.mark.asyncio
    async def test_timeout_returns_none(self, hass: MagicMock):
        async def slow():
            await asyncio.sleep(1)
            return (b"late", "image/jpeg")

        entity = MagicMock()
        entity.async_get_media_image = slow
        component = MagicMock()
        component.get_entity.return_value = entity
        hass.data = {"media_player": component}

        with patch.object(now_playing, "COVER_FETCH_TIMEOUT", 0.01):
            assert await NowPlayingTracker(hass, PLAYER).async_fetch_cover() is None
