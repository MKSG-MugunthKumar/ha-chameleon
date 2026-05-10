"""Select platform for Chameleon — scene picker and animation mode picker."""

from __future__ import annotations

import colorsys
import logging
import random
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from homeassistant.components.select import SelectEntity
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
    ANIMATION_MODES,
    CONF_ANIMATION_SPEED,
    CONF_LIGHT_ENTITIES,
    CONF_LIGHT_ENTITY,
    DEFAULT_ANIMATION_MODE,
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


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Chameleon select entities from a config entry."""
    _LOGGER.debug("Setting up Chameleon select entities for entry: %s", entry.entry_id)

    if CONF_LIGHT_ENTITIES in entry.data:
        light_entities = entry.data[CONF_LIGHT_ENTITIES]
    else:
        light_entities = [entry.data[CONF_LIGHT_ENTITY]]

    animation_speed = entry.data.get(CONF_ANIMATION_SPEED, 5)

    _LOGGER.info(
        "Chameleon configured for %d light(s): %s (initial speed=%ss)",
        len(light_entities),
        light_entities,
        animation_speed,
    )

    async_add_entities(
        [
            ChameleonSceneSelect(hass, entry, light_entities, animation_speed),
            ChameleonAnimationModeSelect(hass, entry, light_entities),
        ],
        True,
    )


def _scene_name_from_filename(filename: str) -> str:
    """Convert filename to human-readable scene name."""
    return filename.replace("_", " ").replace("-", " ").title()


def _entry_data(hass: HomeAssistant, entry_id: str) -> dict:
    """Return (creating if needed) the per-entry runtime dict in hass.data."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    return domain_data.setdefault(entry_id, {})


class ChameleonSceneSelect(SelectEntity):
    """Select entity for choosing Chameleon scenes.

    Animation is enabled implicitly when ``animation_speed > 0`` (read live from
    the speed number entity); a value of 0 means apply the scene statically.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "scene"

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        light_entities: list[str],
        animation_speed: float,
    ) -> None:
        """Initialize the select entity."""
        self.hass = hass
        self._entry = entry
        self._light_entities = light_entities
        self._animation_speed = animation_speed
        self._current_option: str | None = None
        self._applied_colors: dict[str, RGBColor] = {}

        self._extracted_palette: list[RGBColor] = []
        self._last_scene_change: datetime | None = None

        self._last_error: str | None = None
        self._failed_lights: dict[str, str] = {}

        # Options cache. Refreshed on entity add (so config-entry reload picks up new
        # images) and on demand via the chameleon.refresh_scenes service. Also lazily
        # rescanned on cache-miss inside _find_image_for_scene as a defensive fallback.
        self._cached_options: list[str] = []
        self._scene_to_path: dict[str, Path] = {}

        self._light_controller = LightController(hass)

        base_name = get_entity_base_name(hass, light_entities)
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_scene"
        self.entity_id = f"select.chameleon_{base_name}_scene"

    def _get_animation_manager(self) -> AnimationManager | None:
        """Get the AnimationManager from hass.data."""
        return self.hass.data.get(DOMAIN, {}).get("animation_manager")

    def _get_runtime_brightness(self) -> int:
        """Get brightness from runtime data (number slider) or fall back to default."""
        return _entry_data(self.hass, self._entry.entry_id).get("brightness", DEFAULT_BRIGHTNESS)

    def _get_runtime_animation_speed(self) -> float:
        """Get animation speed from runtime data (number slider) or fall back to config."""
        return _entry_data(self.hass, self._entry.entry_id).get("animation_speed", self._animation_speed)

    def _get_runtime_animation_mode(self) -> str:
        """Get animation mode from runtime data (mode select) or fall back to default."""
        return _entry_data(self.hass, self._entry.entry_id).get("animation_mode", DEFAULT_ANIMATION_MODE)

    async def async_added_to_hass(self) -> None:
        """Run when entity is added to hass."""
        await super().async_added_to_hass()

        # Register self so number/select siblings can call back for re-apply, and
        # so the chameleon.refresh_scenes service can find us.
        _entry_data(self.hass, self._entry.entry_id)["scene_select"] = self

        await self.async_refresh_options()

    async def async_will_remove_from_hass(self) -> None:
        """Run when entity is being removed."""
        await super().async_will_remove_from_hass()

        await self._stop_animations()

        # Clear our registration.
        entry_data = _entry_data(self.hass, self._entry.entry_id)
        if entry_data.get("scene_select") is self:
            entry_data.pop("scene_select", None)

    async def _stop_animations(self) -> None:
        """Stop animation for this entry, if running.

        ``manager.stop`` is idempotent — safe to call when nothing is running.
        """
        manager = self._get_animation_manager()
        if manager:
            await manager.stop(self._entry.entry_id)

    async def async_refresh_options(self) -> None:
        """Refresh the cached options list by scanning the image directory.

        Public API: called from the chameleon.refresh_scenes service handler
        and on entity add. Also called internally from _find_image_for_scene
        on cache miss.
        """
        new_options, new_scene_to_path = await self.hass.async_add_executor_job(self._scan_image_directory)

        if new_options != self._cached_options:
            self._cached_options = new_options
            self._scene_to_path = new_scene_to_path
            self.async_write_ha_state()

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
    def extra_state_attributes(self):
        """Return extra state attributes."""
        # is_animating is derived from the animation manager — the single source
        # of truth — to avoid mirror-state drift bugs.
        manager = self._get_animation_manager()
        attrs = {
            "light_entities": self._light_entities,
            "light_count": len(self._light_entities),
            "applied_colors": self._applied_colors,
            "is_animating": manager.is_running(self._entry.entry_id) if manager else False,
        }

        if self._extracted_palette:
            attrs["extracted_palette"] = [list(c) for c in self._extracted_palette]
            # ColorThief returns the palette in dominance order, so the first
            # entry is the most-prominent color of the image — useful as a
            # single representative tint for cards and templates.
            r, g, b = self._extracted_palette[0]
            attrs["dominant_color"] = [r, g, b]
            attrs["dominant_color_hex"] = f"#{r:02x}{g:02x}{b:02x}"
            # HSV decomposition for template-based "warm vs cool" / "vivid vs
            # muted" / "bright vs dark" branching. Hue is in degrees (0-360);
            # saturation and value are 0-1.
            h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
            attrs["dominant_hue"] = round(h * 360, 1)
            attrs["dominant_saturation"] = round(s, 2)
            attrs["dominant_value"] = round(v, 2)

        if self._last_scene_change:
            attrs["last_scene_change"] = self._last_scene_change.isoformat()

        if self._last_error:
            attrs["last_error"] = self._last_error
        if self._failed_lights:
            attrs["failed_lights"] = self._failed_lights

        return attrs

    @property
    def options(self) -> list[str]:
        """Return the list of available scene options.

        Includes ``Off`` and ``Random`` at the top.
        """
        return [SCENE_OFF, SCENE_RANDOM, *self._cached_options]

    @property
    def current_option(self) -> str | None:
        """Return the currently selected option."""
        return self._current_option

    async def async_reapply_current_scene(self) -> None:
        """Re-run the current scene with current runtime state.

        Called by the brightness/speed sliders when they cross the zero
        boundary, or by the mode select when its value changes mid-animation.
        """
        if self._current_option is None:
            return
        await self.async_select_option(self._current_option)

    async def async_select_option(self, option: str) -> None:
        """Handle the user (or another entity) selecting an option."""
        _LOGGER.info(
            "Scene selected: '%s' for %d light(s): %s",
            option,
            len(self._light_entities),
            self._light_entities,
        )

        self._last_error = None
        self._failed_lights = {}

        await self._stop_animations()

        if option == SCENE_OFF:
            await self._turn_off_lights()
            return

        if option == SCENE_RANDOM:
            if not self._cached_options:
                self._last_error = "No scenes available for random selection"
                _LOGGER.warning(self._last_error)
                self.async_write_ha_state()
                return
            option = random.choice(self._cached_options)
            _LOGGER.info("Random scene selected: '%s'", option)

        brightness = self._get_runtime_brightness()
        speed = self._get_runtime_animation_speed()

        # Brightness 0 = lights off. Record the scene but don't drive lights;
        # they'll get applied when brightness goes back above zero.
        if brightness == 0:
            self._current_option = option
            self._last_scene_change = datetime.now()
            _LOGGER.info("Scene '%s' deferred: brightness is 0", option)
            self.async_write_ha_state()
            return

        image_path = await self._find_image_for_scene(option)

        if image_path is None:
            self._last_error = f"Image not found for scene: {option}"
            _LOGGER.error(self._last_error)
            self.async_write_ha_state()
            return

        # speed > 0 → animated, speed == 0 → static.
        if speed > 0:
            result = await self._apply_colors_animated(image_path, brightness)
        else:
            result = await self._apply_colors_static(image_path, brightness)

        if result.all_succeeded:
            self._current_option = option
            self._applied_colors = result.applied_colors
            self._last_scene_change = datetime.now()
            mode = "animation started" if speed > 0 else "applied"
            _LOGGER.info("Scene '%s' %s successfully to all lights", option, mode)
        elif result.all_failed:
            self._last_error = "Failed to apply colors to any lights"
            self._failed_lights = result.failed_lights
            _LOGGER.error(
                "Scene '%s' failed: all %d lights failed",
                option,
                result.failed_count,
            )
        else:
            self._current_option = option
            self._applied_colors = result.applied_colors
            self._failed_lights = result.failed_lights
            self._last_scene_change = datetime.now()
            self._last_error = f"Partial failure: {result.failed_count}/{len(result.results)} lights failed"
            _LOGGER.warning(
                "Scene '%s' partially applied: %d/%d lights succeeded",
                option,
                result.succeeded_count,
                len(result.results),
            )

        self.async_write_ha_state()

    async def _apply_colors_static(self, image_path: Path, brightness: int = 100) -> ApplyColorsResult:
        """Extract colors from image and apply statically to lights."""
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

    async def _apply_colors_animated(self, image_path: Path, brightness: int = 100) -> ApplyColorsResult:
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

        # Pre-flight availability check so we don't animate dead lights.
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

    async def _turn_off_lights(self) -> None:
        """Turn off all configured lights (Off scene)."""
        _LOGGER.info("Turning off %d lights: %s", len(self._light_entities), self._light_entities)

        failed_lights: dict[str, str] = {}

        for light_entity in self._light_entities:
            try:
                await self.hass.services.async_call(
                    "light",
                    "turn_off",
                    {"entity_id": light_entity},
                    blocking=True,
                )
            except Exception as e:
                failed_lights[light_entity] = str(e)
                _LOGGER.error("Failed to turn off %s: %s", light_entity, e)

        if failed_lights:
            self._failed_lights = failed_lights
            if len(failed_lights) == len(self._light_entities):
                self._last_error = "Failed to turn off any lights"
            else:
                self._last_error = f"Partial failure: {len(failed_lights)}/{len(self._light_entities)} lights failed"
        else:
            self._current_option = SCENE_OFF
            self._applied_colors = {}

        self.async_write_ha_state()


class ChameleonAnimationModeSelect(SelectEntity):
    """Animation mode picker — synchronized vs staggered."""

    _attr_has_entity_name = True
    _attr_translation_key = "animation_mode"
    _attr_icon = "mdi:animation"

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        light_entities: list[str],
    ) -> None:
        """Initialize the animation mode select."""
        self.hass = hass
        self._entry = entry
        self._light_entities = light_entities
        self._attr_options = list(ANIMATION_MODES)
        self._current_option: str = DEFAULT_ANIMATION_MODE

        # Seed runtime data so the scene select sees the right mode immediately.
        _entry_data(hass, entry.entry_id)["animation_mode"] = self._current_option

        base_name = get_entity_base_name(hass, light_entities)
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_animation_mode"
        self.entity_id = f"select.chameleon_{base_name}_animation_mode"

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
    def current_option(self) -> str:
        """Return the currently selected mode."""
        return self._current_option

    @property
    def extra_state_attributes(self):
        """Return extra state attributes."""
        return {"light_entities": self._light_entities}

    async def async_select_option(self, option: str) -> None:
        """Handle a mode change.

        If an animation is running, push the new mode in live. Otherwise the
        new mode just takes effect on the next scene change.
        """
        if option not in ANIMATION_MODES:
            _LOGGER.warning("Unknown animation mode: %s", option)
            return

        self._current_option = option
        _entry_data(self.hass, self._entry.entry_id)["animation_mode"] = option
        _LOGGER.info("Animation mode set to '%s' for %s", option, self._light_entities)

        manager = self.hass.data.get(DOMAIN, {}).get("animation_manager")
        if manager and manager.is_running(self._entry.entry_id):
            manager.update_mode(self._entry.entry_id, option)

        self.async_write_ha_state()
