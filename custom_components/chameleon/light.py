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
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .color_extractor import (
    RGBColor,
    extract_color_palette,
    extract_dominant_color,
    generate_gradient_path,
)
from .const import (
    CONF_ANIMATION_SPEED,
    CONF_LIGHT_ENTITIES,
    CONF_LIGHT_ENTITY,
    DEFAULT_ANIMATION_MODE,
    DEFAULT_ANIMATION_SPEED,
    DEFAULT_BRIGHTNESS,
    DEFAULT_COLOR_COUNT,
    DOMAIN,
    IMAGE_DIRECTORY,
    SCENE_OFF,
    SCENE_RANDOM,
    SUPPORTED_EXTENSIONS,
)
from .helpers import get_chameleon_device_name, get_entity_base_name
from .light_controller import ApplyColorsResult, LightController, LightResult

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

    initial_speed = entry.data.get(CONF_ANIMATION_SPEED, DEFAULT_ANIMATION_SPEED)

    async_add_entities(
        [ChameleonLight(hass, entry, light_entities, initial_speed)],
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
        initial_speed: float,
    ) -> None:
        """Initialize the Chameleon light entity."""
        self.hass = hass
        self._entry = entry
        self._light_entities = light_entities
        self._initial_speed = initial_speed

        # Visible state
        self._is_on = False
        self._brightness_pct = DEFAULT_BRIGHTNESS  # internal 0-100 scale
        self._last_nonzero_brightness = DEFAULT_BRIGHTNESS
        self._effect: str | None = None
        self._last_effect: str | None = None  # restored on bare turn_on
        self._manual_color: RGBColor | None = None  # set when user picks raw color

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

    def _get_runtime_animation_speed(self) -> float:
        return _entry_data(self.hass, self._entry.entry_id).get("animation_speed", self._initial_speed)

    def _get_runtime_animation_mode(self) -> str:
        return _entry_data(self.hass, self._entry.entry_id).get("animation_mode", DEFAULT_ANIMATION_MODE)

    # ── Lifecycle ────────────────────────────────────────────────────────

    async def async_added_to_hass(self) -> None:
        """Register self for service handler discovery and run initial scan."""
        await super().async_added_to_hass()
        _entry_data(self.hass, self._entry.entry_id)["chameleon_light"] = self
        await self.async_refresh_options()

    async def async_will_remove_from_hass(self) -> None:
        """Stop any animation and clear our registration."""
        await super().async_will_remove_from_hass()

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
        return self._effect

    @property
    def effect_list(self) -> list[str]:
        """Return scene names available as effects.

        ``Off`` is intentionally excluded — that's expressed via ``turn_off()``.
        ``Random`` stays at the front so the alphabetically-sorted scenes that
        follow keep their own ordering.
        """
        return [SCENE_RANDOM, *self._cached_options]

    @property
    def extra_state_attributes(self):
        """Return extra state attributes for templates and dashboards."""
        manager = self._get_animation_manager()
        attrs: dict[str, Any] = {
            "light_entities": self._light_entities,
            "light_count": len(self._light_entities),
            "applied_colors": self._applied_colors,
            "is_animating": manager.is_running(self._entry.entry_id) if manager else False,
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
            if self._manual_color is not None:
                await self._apply_manual_color(self._manual_color)
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
            await self.async_turn_off()
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

        # Stop any running animation before re-applying. The animated path will
        # start a new one; the static path stays stopped.
        manager = self._get_animation_manager()
        if manager:
            await manager.stop(self._entry.entry_id)

        speed = self._get_runtime_animation_speed()
        brightness = self._brightness_pct

        if speed > 0:
            result = await self._apply_colors_animated(image_path, brightness)
        else:
            result = await self._apply_colors_static(image_path, brightness)

        if result.all_succeeded:
            self._effect = effect
            self._last_effect = effect
            self._applied_colors = result.applied_colors
            self._last_scene_change = datetime.now()
            mode = "animation started" if speed > 0 else "applied"
            _LOGGER.info("Scene '%s' %s successfully", effect, mode)
        elif result.all_failed:
            self._last_error = "Failed to apply colors to any lights"
            self._failed_lights = result.failed_lights
            _LOGGER.error("Scene '%s' failed for all %d lights", effect, result.failed_count)
        else:
            self._effect = effect
            self._last_effect = effect
            self._applied_colors = result.applied_colors
            self._failed_lights = result.failed_lights
            self._last_scene_change = datetime.now()
            self._last_error = f"Partial failure: {result.failed_count}/{len(result.results)} lights failed"
            _LOGGER.warning(
                "Scene '%s' partially applied: %d/%d lights succeeded",
                effect,
                result.succeeded_count,
                len(result.results),
            )

    async def _apply_manual_color(self, rgb_color: RGBColor) -> None:
        """Apply a single RGB color directly to all underlying lights."""
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

    async def _apply_colors_static(self, image_path: Path, brightness: int) -> ApplyColorsResult:
        """Extract and apply colors statically (no animation loop)."""
        num_lights = len(self._light_entities)

        if num_lights == 1:
            color = await extract_dominant_color(self.hass, image_path)
            if color:
                self._extracted_palette = [color]
                return await self._light_controller.apply_colors_to_lights(
                    {self._light_entities[0]: color},
                    brightness=brightness,
                )
            _LOGGER.error("Failed to extract dominant color from %s", image_path)
            return ApplyColorsResult()

        colors = await extract_color_palette(
            self.hass,
            image_path,
            color_count=max(num_lights, DEFAULT_COLOR_COUNT),
        )
        if not colors:
            _LOGGER.error("Failed to extract color palette from %s", image_path)
            return ApplyColorsResult()

        self._extracted_palette = colors
        light_colors = {entity: colors[i % len(colors)] for i, entity in enumerate(self._light_entities)}
        return await self._light_controller.apply_colors_to_lights(
            light_colors,
            brightness=brightness,
        )

    async def _apply_colors_animated(self, image_path: Path, brightness: int) -> ApplyColorsResult:
        """Extract colors and start an animation across the configured lights."""
        manager = self._get_animation_manager()
        if not manager:
            _LOGGER.error("AnimationManager not available")
            return ApplyColorsResult()

        speed = self._get_runtime_animation_speed()
        mode = self._get_runtime_animation_mode()

        colors = await extract_color_palette(
            self.hass,
            image_path,
            color_count=DEFAULT_COLOR_COUNT,
        )
        if not colors:
            _LOGGER.error("Failed to extract color palette from %s", image_path)
            return ApplyColorsResult()

        self._extracted_palette = colors
        gradient = generate_gradient_path(colors, steps_between=10)

        # Pre-flight availability so we don't animate dead lights.
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
                available_lights,
                gradient,
                speed=speed,
                mode=mode,
                brightness=brightness,
            )
            _LOGGER.info(
                "Started %s animation for %d lights (speed=%.1fs)",
                mode,
                len(available_lights),
                speed,
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
