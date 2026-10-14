"""Light platform for Chameleon — primary entity exposing scenes as effects.

The Chameleon light is a facade over the user's configured RGB lights. It owns
the on/off state, brightness, and the currently-displayed color (either the
dominant of an active scene or a user-supplied manual override). Scenes are
exposed via HA's standard ``LightEntityFeature.EFFECT`` mechanism so stock
light cards (Tile, Mushroom, Bubble) render the scene picker natively.

Setters:

- ``turn_on(effect=X)`` → apply the named scene; clear any manual override.
- ``turn_on(rgb_color=X)`` → bypass scenes; apply X directly to all
  underlying lights and remember it as a manual override until the next
  scene/turn_off.
- ``turn_on(brightness=N)`` → update brightness and re-apply current state.
  ``N == 0`` is treated as ``turn_off`` (HA cards convert slider-to-zero into
  a turn_off, but we handle the explicit case defensively too).
- ``turn_on()`` (bare) → restore the last applied scene; if none, apply
  ``Random``.
- ``turn_off()`` → stop any animation; turn off all underlying lights.
- ``turn_on(effect="Now Playing - <player>")`` → follow the linked media
  player's album art (only when a player is configured). Pause holds; idle/off
  for 30 s falls back to the scene active before.

Availability follows HA's light group: the Chameleon light is available while
at least one member light is reachable, so a room whose mains is off shows as
unavailable. ``unavailable_lights`` names the members that are offline.
"""

from __future__ import annotations

import asyncio
import colorsys
import logging
import random
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_EFFECT,
    ATTR_RGB_COLOR,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from .color_extractor import (
    RGBColor,
    extract_color_palette,
    extract_dominant_color,
    generate_gradient_path,
)
from .const import (
    CONF_LIGHT_ENTITIES,
    CONF_LIGHT_ENTITY,
    CONF_MEDIA_PLAYER,
    CONF_TRANSITION,
    DEFAULT_BRIGHTNESS,
    DEFAULT_COLOR_COUNT,
    DEFAULT_TRANSITION,
    DEFAULT_TRANSITION_STYLE,
    DOMAIN,
    IMAGE_DIRECTORY,
    NOW_PLAYING_EFFECT,
    NOW_PLAYING_PREFIX,
    SCENE_OFF,
    SCENE_RANDOM,
    SUPPORTED_EXTENSIONS,
)
from .helpers import get_chameleon_device_name, get_entity_base_name, get_friendly_name
from .light_controller import ApplyColorsResult, LightController, LightResult, is_light_reachable
from .now_playing import NowPlayingTracker

if TYPE_CHECKING:
    from .animations import AnimationManager

_LOGGER = logging.getLogger(__name__)

# Default RGB shown when no scene has been applied yet (white).
_DEFAULT_RGB: RGBColor = (255, 255, 255)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Chameleon light entity from a config entry."""
    if CONF_LIGHT_ENTITIES in entry.data:
        light_entities = entry.data[CONF_LIGHT_ENTITIES]
    else:
        light_entities = [entry.data[CONF_LIGHT_ENTITY]]

    initial_transition = entry.data.get(CONF_TRANSITION, DEFAULT_TRANSITION)

    async_add_entities(
        [ChameleonLight(hass, entry, light_entities, initial_transition, media_player=entry.data.get(CONF_MEDIA_PLAYER))],
        True,
    )


def _scene_name_from_filename(filename: str) -> str:
    """Convert an image filename stem to a human-readable scene name."""
    return filename.replace("_", " ").replace("-", " ").title()


def _entry_data(hass: HomeAssistant, entry_id: str) -> dict:
    """Return (creating if needed) the per-entry runtime dict in hass.data."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    return domain_data.setdefault(entry_id, {})


class ChameleonLight(LightEntity):
    """Primary Chameleon entity — wraps the configured RGB lights as one facade.

    Effects are scene names (image-based palettes); brightness is owned here;
    rgb_color reflects either the active scene's dominant color or a manual
    color override.
    """

    _attr_has_entity_name = True
    _attr_name = None  # entity inherits the device name
    _attr_supported_color_modes: ClassVar[set[ColorMode]] = {ColorMode.RGB}
    _attr_color_mode = ColorMode.RGB
    _attr_supported_features = LightEntityFeature.EFFECT

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        light_entities: list[str],
        initial_transition: float,
        media_player: str | None = None,
    ) -> None:
        """Initialize the Chameleon light entity."""
        self.hass = hass
        self._entry = entry
        self._light_entities = light_entities
        self._initial_transition = initial_transition

        # Visible state
        self._is_on = False
        self._brightness_pct = DEFAULT_BRIGHTNESS  # internal 0-100 scale
        self._last_nonzero_brightness = DEFAULT_BRIGHTNESS
        self._effect: str | None = None
        self._last_effect: str | None = None  # restored on bare turn_on
        self._manual_color: RGBColor | None = None  # set when user picks raw color

        # Now Playing (optional): follow a media player's album art.
        self._media_player = media_player
        self._now_playing = NowPlayingTracker(hass, media_player) if media_player else None
        self._fallback_effect: str | None = None  # scene to return to when playback ends
        self._latest_cover_key: str | None = None  # newest cover seen; older pending work is dropped
        self._removed = False  # set on removal so in-flight scheduled work bails out

        # Diagnostics / palette
        self._extracted_palette: list[RGBColor] = []
        self._applied_colors: dict[str, RGBColor] = {}
        self._last_scene_change: datetime | None = None
        self._last_error: str | None = None
        self._failed_lights: dict[str, str] = {}

        # Scene cache (effect_list source)
        self._cached_options: list[str] = []
        self._scene_to_path: dict[str, Path] = {}

        # Serializes concurrent state-changing calls. HA can dispatch multiple
        # service calls (turn_on, turn_off, sibling re-apply) onto this entity
        # simultaneously; without the lock those interleave and race each other
        # over the animation manager state.
        self._lock = asyncio.Lock()

        self._light_controller = LightController(hass)

        base_name = get_entity_base_name(hass, light_entities)
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_light"
        self.entity_id = f"light.chameleon_{base_name}"

    # ── Helpers ──────────────────────────────────────────────────────────

    def _get_animation_manager(self) -> AnimationManager | None:
        return self.hass.data.get(DOMAIN, {}).get("animation_manager")

    def _get_runtime_transition(self) -> float:
        return _entry_data(self.hass, self._entry.entry_id).get("transition", self._initial_transition)

    def _get_runtime_transition_style(self) -> str:
        return _entry_data(self.hass, self._entry.entry_id).get("transition_style", DEFAULT_TRANSITION_STYLE)

    def _unreachable_members(self) -> list[str]:
        """Return member lights that can't take commands right now."""
        return [entity_id for entity_id in self._light_entities if not is_light_reachable(self.hass.states.get(entity_id))]

    def _static_color_for(self, entity_id: str) -> RGBColor | None:
        """Return the color a member should show under the current static state.

        Mirrors the mapping in ``_apply_colors_static`` (palette color by member
        index) and ``_apply_manual_color``. None when nothing static is active.
        """
        if self._manual_color is not None:
            return self._manual_color
        if self._effect is None or not self._extracted_palette:
            return None
        index = self._light_entities.index(entity_id)
        return self._extracted_palette[index % len(self._extracted_palette)]

    def _now_playing_name(self) -> str | None:
        """Return the Now Playing effect's display name, or None without a player."""
        if self._media_player is None:
            return None
        return f"{NOW_PLAYING_PREFIX} - {get_friendly_name(self.hass, self._media_player)}"

    def _stop_now_playing(self) -> None:
        """Stop following the media player (no-op when not following)."""
        if self._now_playing is not None:
            self._now_playing.stop()
        self._latest_cover_key = None

    # ── Lifecycle ────────────────────────────────────────────────────────

    async def async_added_to_hass(self) -> None:
        """Register self for service handler discovery and run initial scan."""
        await super().async_added_to_hass()
        _entry_data(self.hass, self._entry.entry_id)["chameleon_light"] = self
        self.async_on_remove(async_track_state_change_event(self.hass, self._light_entities, self._async_member_state_changed))
        if self._media_player is not None:
            self.async_on_remove(async_track_state_change_event(self.hass, [self._media_player], self._async_media_player_changed))
        await self.async_refresh_options()

    async def async_will_remove_from_hass(self) -> None:
        """Stop any animation and clear our registration.

        Takes the lock so an in-flight cover/restore task finishes (or is
        refused afterwards via ``_removed``) before the animation is stopped;
        otherwise a late task could start an animation nobody can stop.
        """
        await super().async_will_remove_from_hass()
        async with self._lock:
            self._removed = True
            self._stop_now_playing()
            manager = self._get_animation_manager()
            if manager:
                await manager.stop(self._entry.entry_id)

        entry_data = _entry_data(self.hass, self._entry.entry_id)
        if entry_data.get("chameleon_light") is self:
            entry_data.pop("chameleon_light", None)

    # ── HA-facing properties ─────────────────────────────────────────────

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
    def available(self) -> bool:
        """Return True while at least one member light is reachable.

        Same rule as HA's light group: one dead bulb shouldn't take away
        control of the rest, but when every member is gone (mains off) the
        facade goes unavailable too. Derived on read, never stored.
        """
        return len(self._unreachable_members()) < len(self._light_entities)

    @property
    def is_on(self) -> bool:
        """Return whether the light is currently on."""
        return self._is_on

    @property
    def brightness(self) -> int:
        """Return brightness on HA's 0-255 scale."""
        return int(self._brightness_pct * 255 / 100)

    @property
    def rgb_color(self) -> RGBColor:
        """Return the displayed color: manual override if set, else palette dominant."""
        if self._manual_color is not None:
            return self._manual_color
        if self._extracted_palette:
            return self._extracted_palette[0]
        return _DEFAULT_RGB

    @property
    def effect(self) -> str | None:
        """Return the currently active effect, or None when in manual-color mode."""
        if self._effect == NOW_PLAYING_EFFECT:
            return self._now_playing_name()
        return self._effect

    @property
    def effect_list(self) -> list[str]:
        """Return scene names available as effects.

        ``Off`` is intentionally excluded — that's expressed via ``turn_off()``.
        ``Random`` stays at the front so the alphabetically-sorted scenes that
        follow keep their own ordering. Now Playing follows Random when a media
        player is configured.
        """
        now_playing = self._now_playing_name()
        return [SCENE_RANDOM, *([now_playing] if now_playing else []), *self._cached_options]

    @property
    def extra_state_attributes(self):
        """Return extra state attributes for templates and dashboards."""
        manager = self._get_animation_manager()
        attrs: dict[str, Any] = {
            "light_entities": self._light_entities,
            "light_count": len(self._light_entities),
            "applied_colors": self._applied_colors,
            "is_animating": manager.is_running(self._entry.entry_id) if manager else False,
            "unavailable_lights": self._unreachable_members(),
        }

        if self._extracted_palette:
            attrs["extracted_palette"] = [list(c) for c in self._extracted_palette]
            r, g, b = self._extracted_palette[0]
            attrs["dominant_color"] = [r, g, b]
            attrs["dominant_color_hex"] = f"#{r:02x}{g:02x}{b:02x}"
            h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
            attrs["dominant_hue"] = round(h * 360, 1)
            attrs["dominant_saturation"] = round(s, 2)
            attrs["dominant_value"] = round(v, 2)

        if self._manual_color is not None:
            attrs["manual_color"] = list(self._manual_color)

        if self._last_scene_change:
            attrs["last_scene_change"] = self._last_scene_change.isoformat()
        if self._last_error:
            attrs["last_error"] = self._last_error
        if self._failed_lights:
            attrs["failed_lights"] = self._failed_lights

        if self._media_player is not None:
            attrs["media_player"] = self._media_player
            if self._effect == NOW_PLAYING_EFFECT:
                player = self.hass.states.get(self._media_player)
                title = player.attributes.get("media_title") if player else None
                artist = player.attributes.get("media_artist") if player else None
                if title:
                    attrs["now_playing"] = f"{artist} - {title}" if artist else title

        return attrs

    # ── HA-facing setters ────────────────────────────────────────────────

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on with optional effect, rgb_color, and/or brightness."""
        async with self._lock:
            await self._do_turn_on(**kwargs)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stop animation and turn off all underlying lights."""
        async with self._lock:
            await self._do_turn_off()

    async def _do_turn_on(self, **kwargs: Any) -> None:
        """Inner turn-on, runs under ``self._lock``."""
        self._last_error = None
        self._failed_lights = {}

        brightness = kwargs.get(ATTR_BRIGHTNESS)
        rgb_color = kwargs.get(ATTR_RGB_COLOR)
        effect = kwargs.get(ATTR_EFFECT)

        # brightness=0 from a card almost never happens (cards convert to
        # turn_off) but handle defensively without re-acquiring the lock.
        if brightness is not None and brightness == 0:
            await self._do_turn_off()
            return

        # Update brightness if provided.
        brightness_changed = False
        if brightness is not None:
            new_pct = max(1, round(brightness * 100 / 255))
            if new_pct != self._brightness_pct:
                brightness_changed = True
                self._brightness_pct = new_pct
                self._last_nonzero_brightness = new_pct
                _entry_data(self.hass, self._entry.entry_id)["brightness"] = new_pct

        if effect is not None:
            # Scene change — full re-apply.
            self._manual_color = None
            await self._apply_effect(effect)
            if effect == SCENE_OFF:
                return  # _do_turn_off already set the off state
        elif rgb_color is not None:
            # Manual color override — full re-apply.
            await self._apply_manual_color(tuple(rgb_color))
        elif not self._is_on:
            # Bare turn_on from off → restore last effect (Random if never set).
            target = self._last_effect or SCENE_RANDOM
            self._manual_color = None
            await self._apply_effect(target)
        elif brightness_changed:
            # Already on; brightness-only update. Push live to running animation
            # if any, otherwise just bump brightness on the lights without
            # re-extracting the palette.
            await self._update_brightness_only()
        # else: bare turn_on while already on with no change → no-op

        self._is_on = True
        self.async_write_ha_state()

    async def _do_turn_off(self) -> None:
        """Inner turn-off, runs under ``self._lock``."""
        self._stop_now_playing()
        manager = self._get_animation_manager()
        if manager:
            await manager.stop(self._entry.entry_id)

        # transition=0 → instant off, ignoring any trailing fade duration
        # the lights might inherit from the just-cancelled animation's last
        # turn_on with transition=speed.
        for light_entity in self._light_entities:
            try:
                await self.hass.services.async_call(
                    "light",
                    "turn_off",
                    {"entity_id": light_entity, "transition": 0},
                    blocking=True,
                )
            except Exception as e:
                _LOGGER.error("Failed to turn off %s: %s", light_entity, e)

        self._is_on = False
        self._effect = None
        self._manual_color = None
        self._applied_colors = {}
        # _last_effect is preserved so a bare turn_on can restore it.
        self.async_write_ha_state()

    async def _update_brightness_only(self) -> None:
        """Apply a brightness change without disturbing color/scene state.

        - Running animation: push live to the controller.
        - Manual color: re-apply at the new brightness.
        - Static scene: just bump brightness on the underlying lights; they
          remember their color from the last static apply.
        """
        manager = self._get_animation_manager()
        if manager and manager.is_running(self._entry.entry_id):
            manager.update_brightness(self._entry.entry_id, self._brightness_pct)
            return

        if self._manual_color is not None:
            await self._apply_manual_color(self._manual_color)
            return

        ha_brightness = int(self._brightness_pct * 255 / 100)
        for light_entity in self._light_entities:
            try:
                await self.hass.services.async_call(
                    "light",
                    "turn_on",
                    {"entity_id": light_entity, "brightness": ha_brightness},
                    blocking=True,
                )
            except Exception as e:
                _LOGGER.error("Failed to update brightness on %s: %s", light_entity, e)

    # ── Member light availability ────────────────────────────────────────

    @callback
    def _async_member_state_changed(self, event: Event[EventStateChangedData]) -> None:
        """React when a member light becomes reachable or unreachable.

        Members change state on every animation tick, so anything that isn't a
        reachability flip is ignored - writing our state on each tick would
        flood the recorder.
        """
        entity_id = event.data["entity_id"]
        old_state = event.data["old_state"]
        new_state = event.data["new_state"]
        was_reachable = is_light_reachable(old_state)
        now_reachable = is_light_reachable(new_state)
        if was_reachable == now_reachable:
            return

        # old_state is None when the member first appears (startup ordering);
        # that isn't an outage or a recovery worth logging.
        if old_state is not None:
            if now_reachable:
                _LOGGER.info("Member light %s is reachable again", entity_id)
            else:
                _LOGGER.info("Member light %s is %s", entity_id, new_state.state if new_state else "gone")

        if now_reachable:
            self._entry.async_create_task(self.hass, self._async_restore_member(entity_id))
        self.async_write_ha_state()

    async def _async_restore_member(self, entity_id: str) -> None:
        """Push the current static color to a member light that just came back.

        Animated scenes need nothing here: the loop polls reachability and picks
        the light up on its next beat. Static scenes and manual colors have no
        loop, so without this the bulb keeps its power-on color (typically warm
        white after a mains cut). Runs under the lock so it can't race a
        turn_off and relight a lamp the user just switched off.
        """
        async with self._lock:
            if self._removed or not self._is_on:
                return
            manager = self._get_animation_manager()
            if manager and manager.is_running(self._entry.entry_id):
                return
            color = self._static_color_for(entity_id)
            if color is None:
                return

            result = await self._light_controller.apply_color_to_light(entity_id, color, brightness=self._brightness_pct)
            if result.success:
                self._applied_colors = {**self._applied_colors, entity_id: color}
                self._failed_lights = {k: v for k, v in self._failed_lights.items() if k != entity_id}
                self.async_write_ha_state()

    # ── Now Playing ──────────────────────────────────────────────────────

    async def _enter_now_playing(self, tracker: NowPlayingTracker) -> None:
        """Start following the media player's album art.

        Runs under ``self._lock``. Remembers the scene to fall back to, then
        applies the current cover; with nothing playing, falls back at once.
        """
        candidate = self._effect if self._effect is not None else self._last_effect
        if candidate is not None and candidate != NOW_PLAYING_EFFECT:
            self._fallback_effect = candidate

        key = tracker.current_cover_key()
        if key is None:
            tracker.stop()
            player = tracker.media_player
            self._last_error = f"{player} not found" if self.hass.states.get(player) is None else f"Nothing playing on {player}"
            _LOGGER.warning(self._last_error)
            await self._fall_back()
            return

        tracker.start(self._on_cover_changed, self._on_now_playing_ended)
        self._effect = NOW_PLAYING_EFFECT
        self._last_effect = NOW_PLAYING_EFFECT
        self._latest_cover_key = key
        await self._apply_cover(tracker)

    async def _apply_cover(self, tracker: NowPlayingTracker) -> None:
        """Fetch the current cover and apply its palette.

        Fetch or extraction failures keep the current colours and the mode;
        only the player's state decides when to leave Now Playing.
        """
        image = await tracker.async_fetch_cover()
        if image is None:
            self._last_error = f"Couldn't fetch cover art from {tracker.media_player}"
            _LOGGER.warning(self._last_error)
            return

        animated = self._uses_animation()
        colors = await self._extract_palette(image, animated)
        if not colors:
            self._last_error = f"Couldn't read cover art from {tracker.media_player}"
            _LOGGER.warning(self._last_error)
            return

        result = await self._apply_palette(colors, animated)
        self._record_effect_result(NOW_PLAYING_EFFECT, self._now_playing_name() or NOW_PLAYING_PREFIX, result, animated)

    async def _reapply_now_playing(self, tracker: NowPlayingTracker) -> None:
        """Re-apply Now Playing in the current static/animated mode without re-entering.

        Re-entering would restart the tracker (resetting a running grace
        timer) and fall back when the player momentarily has no art. Instead
        re-fetch the cover if there is one, and otherwise re-apply the colours
        already showing.
        """
        animated = self._uses_animation()
        colors: list[RGBColor] = []
        if tracker.current_cover_key() is not None:
            image = await tracker.async_fetch_cover()
            if image is not None:
                colors = await self._extract_palette(image, animated)
        if not colors:
            colors = self._extracted_palette
        if not colors:
            return
        result = await self._apply_palette(colors, animated)
        self._record_effect_result(NOW_PLAYING_EFFECT, self._now_playing_name() or NOW_PLAYING_PREFIX, result, animated)

    async def _fall_back(self) -> None:
        """Leave Now Playing for the scene active before it (Random if none)."""
        self._stop_now_playing()
        self._effect = None
        await self._apply_effect(self._fallback_effect or SCENE_RANDOM)

    @callback
    def _on_cover_changed(self, cover_key: str) -> None:
        """Tracker callback: a new cover is showing. Work runs under the lock."""
        self._latest_cover_key = cover_key
        self._entry.async_create_task(self.hass, self._async_handle_cover(cover_key))

    async def _async_handle_cover(self, cover_key: str) -> None:
        async with self._lock:
            tracker = self._now_playing
            if self._removed or tracker is None or not self._is_on or self._effect != NOW_PLAYING_EFFECT:
                return
            if cover_key != self._latest_cover_key:
                return  # superseded by a newer track skip
            self._last_error = None
            self._failed_lights = {}
            await self._apply_cover(tracker)
            self.async_write_ha_state()

    @callback
    def _on_now_playing_ended(self) -> None:
        """Tracker callback: grace period expired with nothing playing."""
        self._entry.async_create_task(self.hass, self._async_handle_now_playing_ended())

    async def _async_handle_now_playing_ended(self) -> None:
        async with self._lock:
            if self._removed or not self._is_on or self._effect != NOW_PLAYING_EFFECT:
                return
            _LOGGER.info("Playback ended on %s; returning to %s", self._media_player, self._fallback_effect or SCENE_RANDOM)
            await self._fall_back()
            self.async_write_ha_state()

    @callback
    def _async_media_player_changed(self, event: Event[EventStateChangedData]) -> None:
        """Refresh our state when the player is renamed or, in Now Playing, the track changes.

        The effect name embeds the player's friendly name and ``now_playing``
        shows the track; other player updates (volume, position) are ignored.
        """
        old_state = event.data["old_state"]
        new_state = event.data["new_state"]
        watched = ["friendly_name"]
        if self._effect == NOW_PLAYING_EFFECT:
            watched += ["media_title", "media_artist"]
        old_values = [old_state.attributes.get(a) if old_state else None for a in watched]
        new_values = [new_state.attributes.get(a) if new_state else None for a in watched]
        if old_values != new_values:
            self.async_write_ha_state()

    # ── Public API for sibling entities ──────────────────────────────────

    async def async_reapply_current_scene(self) -> None:
        """Re-run the current scene/color with current runtime state.

        Called by the speed slider when it crosses the zero boundary, or by
        the mode select when its value changes mid-animation. Held under the
        same lock as turn_on/turn_off so re-applies serialize with user
        actions.
        """
        async with self._lock:
            if not self._is_on:
                return
            tracker = self._now_playing
            if self._manual_color is not None:
                await self._apply_manual_color(self._manual_color)
            elif self._effect == NOW_PLAYING_EFFECT and tracker is not None and tracker.is_running:
                await self._reapply_now_playing(tracker)
            elif self._effect is not None:
                await self._apply_effect(self._effect)

    async def async_refresh_options(self) -> None:
        """Refresh the scene cache (effect_list source).

        Public API: called by the chameleon.refresh_scenes service handler
        and on entity add. Also called internally on cache miss.
        """
        new_options, new_scene_to_path = await self.hass.async_add_executor_job(self._scan_image_directory)
        if new_options != self._cached_options:
            self._cached_options = new_options
            self._scene_to_path = new_scene_to_path
            self.async_write_ha_state()

    # ── Internals ────────────────────────────────────────────────────────

    async def _apply_effect(self, effect: str) -> None:
        """Apply a scene effect by name (handles Random and Off specially)."""
        # "Off" via the service path is equivalent to turn_off.
        if effect == SCENE_OFF:
            # Already under self._lock: call the inner turn-off, not async_turn_off.
            await self._do_turn_off()
            return

        tracker = self._now_playing
        if tracker is not None and effect in (NOW_PLAYING_EFFECT, self._now_playing_name()):
            await self._enter_now_playing(tracker)
            return

        if effect == SCENE_RANDOM:
            if not self._cached_options:
                self._last_error = "No scenes available for random selection"
                _LOGGER.warning(self._last_error)
                return
            effect = random.choice(self._cached_options)
            _LOGGER.info("Random scene selected: '%s'", effect)

        image_path = await self._find_image_for_scene(effect)
        if image_path is None:
            self._last_error = f"Image not found for scene: {effect}"
            _LOGGER.error(self._last_error)
            return

        animated = self._uses_animation()
        colors = await self._extract_palette(image_path, animated)
        if not colors:
            self._last_error = f"Failed to extract colors from scene: {effect}"
            _LOGGER.error(self._last_error)
            return

        # Only now does the new scene take over; a typo'd or missing scene above
        # leaves Now Playing (if active) running untouched.
        self._stop_now_playing()
        result = await self._apply_palette(colors, animated)
        self._record_effect_result(effect, effect, result, animated)
        if self._effect == NOW_PLAYING_EFFECT:
            self._effect = None  # tracker stopped and the new scene failed everywhere

    def _uses_animation(self) -> bool:
        """Return True when the runtime transition calls for the animation loop."""
        return self._get_runtime_transition() > 0

    async def _extract_palette(self, source: Path | bytes, animated: bool) -> list[RGBColor]:
        """Extract the palette an apply path needs from an image file or bytes.

        Animated: a fixed ``DEFAULT_COLOR_COUNT`` palette feeds the gradient.
        Static: one color per light - the dominant color for a single light,
        otherwise at least one palette entry per light.
        """
        if animated:
            return await extract_color_palette(self.hass, source, color_count=DEFAULT_COLOR_COUNT)
        if len(self._light_entities) == 1:
            color = await extract_dominant_color(self.hass, source)
            return [color] if color else []
        return await extract_color_palette(
            self.hass,
            source,
            color_count=max(len(self._light_entities), DEFAULT_COLOR_COUNT),
        )

    async def _apply_palette(self, colors: list[RGBColor], animated: bool) -> ApplyColorsResult:
        """Stop any running animation, then push a palette statically or animated."""
        manager = self._get_animation_manager()
        if manager:
            await manager.stop(self._entry.entry_id)
        if animated:
            return await self._apply_colors_animated(colors, self._brightness_pct)
        return await self._apply_colors_static(colors, self._brightness_pct)

    def _record_effect_result(self, effect: str, label: str, result: ApplyColorsResult, animated: bool) -> None:
        """Record the outcome of applying an effect's palette.

        ``effect`` is what ``_effect``/``_last_effect`` store (a scene name or
        an internal marker); ``label`` is the human-readable name for logs.
        """
        if result.all_succeeded:
            self._effect = effect
            self._last_effect = effect
            self._applied_colors = result.applied_colors
            self._last_scene_change = datetime.now()
            verb = "animation started" if animated else "applied"
            _LOGGER.info("Scene '%s' %s successfully", label, verb)
        elif result.all_failed:
            self._last_error = "Failed to apply colors to any lights"
            self._failed_lights = result.failed_lights
            _LOGGER.error("Scene '%s' failed for all %d lights", label, result.failed_count)
        else:
            self._effect = effect
            self._last_effect = effect
            self._applied_colors = result.applied_colors
            self._failed_lights = result.failed_lights
            self._last_scene_change = datetime.now()
            self._last_error = f"Partial failure: {result.failed_count}/{len(result.results)} lights failed"
            _LOGGER.warning(
                "Scene '%s' partially applied: %d/%d lights succeeded",
                label,
                result.succeeded_count,
                len(result.results),
            )

    async def _apply_manual_color(self, rgb_color: RGBColor) -> None:
        """Apply a single RGB color directly to all underlying lights."""
        self._stop_now_playing()
        manager = self._get_animation_manager()
        if manager:
            await manager.stop(self._entry.entry_id)

        result = await self._light_controller.apply_colors_to_lights(
            {entity: rgb_color for entity in self._light_entities},
            brightness=self._brightness_pct,
        )

        if result.all_succeeded:
            self._manual_color = rgb_color
            self._effect = None
            self._applied_colors = result.applied_colors
            self._last_scene_change = datetime.now()
            _LOGGER.info("Manual color RGB%s applied successfully", rgb_color)
        elif result.all_failed:
            self._last_error = "Failed to apply color to any lights"
            self._failed_lights = result.failed_lights
            _LOGGER.error("Manual color failed for all %d lights", result.failed_count)
        else:
            self._manual_color = rgb_color
            self._effect = None
            self._applied_colors = result.applied_colors
            self._failed_lights = result.failed_lights
            self._last_scene_change = datetime.now()
            self._last_error = f"Partial failure: {result.failed_count}/{len(result.results)} lights failed"

        if self._effect == NOW_PLAYING_EFFECT:
            self._effect = None  # tracker stopped above and the color failed everywhere

    async def _apply_colors_static(self, colors: list[RGBColor], brightness: int) -> ApplyColorsResult:
        """Apply a palette statically: palette color by light index, no loop."""
        self._extracted_palette = colors
        light_colors = {entity: colors[i % len(colors)] for i, entity in enumerate(self._light_entities)}
        return await self._light_controller.apply_colors_to_lights(light_colors, brightness=brightness)

    async def _apply_colors_animated(self, colors: list[RGBColor], brightness: int) -> ApplyColorsResult:
        """Start an animation across the configured lights from a palette."""
        manager = self._get_animation_manager()
        if not manager:
            _LOGGER.error("AnimationManager not available")
            return ApplyColorsResult()

        transition = self._get_runtime_transition()
        style = self._get_runtime_transition_style()

        self._extracted_palette = colors
        gradient = generate_gradient_path(colors, steps_between=10)

        # Pre-flight availability for result reporting. The loop itself gets
        # every member: it skips unreachable ones per tick, so a light that was
        # off when the scene started joins in once it comes back.
        results: list[LightResult] = []
        available_lights: list[str] = []
        for light_entity in self._light_entities:
            is_available, error, error_msg = self._light_controller.check_light_availability(light_entity)
            if is_available:
                available_lights.append(light_entity)
                results.append(
                    LightResult(
                        entity_id=light_entity,
                        success=True,
                        color=gradient[0] if gradient else None,
                    )
                )
            else:
                results.append(
                    LightResult(
                        entity_id=light_entity,
                        success=False,
                        error=error,
                        error_message=error_msg,
                    )
                )

        if available_lights:
            await manager.start(
                self._entry.entry_id,
                self._light_entities,
                gradient,
                transition=transition,
                style=style,
                brightness=brightness,
            )
            _LOGGER.info(
                "Started %s animation for %d lights (transition=%.1fs)",
                style,
                len(available_lights),
                transition,
            )

        return ApplyColorsResult(results=results)

    async def _find_image_for_scene(self, scene_name: str) -> Path | None:
        """Find the image file path for a given scene name."""
        if scene_name in self._scene_to_path:
            image_path = self._scene_to_path[scene_name]
            if image_path.exists():
                return image_path

        # Cache miss or stale — refresh and try again.
        await self.async_refresh_options()

        if scene_name in self._scene_to_path:
            image_path = self._scene_to_path[scene_name]
            if image_path.exists():
                return image_path

        _LOGGER.warning("No image found for scene '%s' in %s", scene_name, IMAGE_DIRECTORY)
        return None

    def _scan_image_directory(self) -> tuple[list[str], dict[str, Path]]:
        """Scan image directory for available scenes (runs in executor)."""
        image_dir = Path(IMAGE_DIRECTORY)

        if not image_dir.exists():
            _LOGGER.warning("Image directory does not exist: %s", IMAGE_DIRECTORY)
            return [], {}

        scene_to_path: dict[str, Path] = {}
        for ext in SUPPORTED_EXTENSIONS:
            for image_path in image_dir.glob(f"*{ext}"):
                scene_name = _scene_name_from_filename(image_path.stem)
                if scene_name not in scene_to_path:
                    scene_to_path[scene_name] = image_path

        return sorted(scene_to_path.keys()), scene_to_path
