"""Select platform for Chameleon integration."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval

from .color_extractor import (
    RGBColor,
    extract_color_palette,
    extract_dominant_color,
    generate_gradient_path,
)
from .const import (
    CONF_ANIMATION_ENABLED,
    CONF_ANIMATION_SPEED,
    CONF_LIGHT_ENTITIES,
    CONF_LIGHT_ENTITY,
    DEFAULT_BRIGHTNESS,
    DEFAULT_COLOR_COUNT,
    DOMAIN,
    IMAGE_DIRECTORY,
    OPTIONS_CACHE_INTERVAL,
    SUPPORTED_EXTENSIONS,
)
from .light_controller import ApplyColorsResult, LightController

if TYPE_CHECKING:
    from .animations import AnimationManager

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Chameleon select entity from a config entry."""
    _LOGGER.debug("Setting up Chameleon select entity for entry: %s", entry.entry_id)

    # Support both old single-light and new multi-light config
    if CONF_LIGHT_ENTITIES in entry.data:
        light_entities = entry.data[CONF_LIGHT_ENTITIES]
    else:
        # Migration path: convert old single entity to list
        light_entities = [entry.data[CONF_LIGHT_ENTITY]]

    animation_enabled = entry.data.get(CONF_ANIMATION_ENABLED, False)
    animation_speed = entry.data.get(CONF_ANIMATION_SPEED, 5)

    _LOGGER.info(
        "Chameleon configured for %d light(s): %s (animation=%s, speed=%ds)",
        len(light_entities),
        light_entities,
        animation_enabled,
        animation_speed,
    )

    async_add_entities(
        [
            ChameleonSceneSelect(
                hass,
                entry,
                light_entities,
                animation_enabled,
                animation_speed,
            )
        ],
        True,
    )


def _scene_name_from_filename(filename: str) -> str:
    """Convert filename to human-readable scene name."""
    # Remove extension and convert underscores/hyphens to spaces, then title case
    return filename.replace("_", " ").replace("-", " ").title()


class ChameleonSceneSelect(SelectEntity):
    """Select entity for choosing Chameleon scenes."""

    _attr_has_entity_name = True
    _attr_translation_key = "scene"

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        light_entities: list[str],
        animation_enabled: bool,
        animation_speed: int,
    ) -> None:
        """Initialize the select entity."""
        self.hass = hass
        self._entry = entry
        self._light_entities = light_entities
        self._animation_enabled = animation_enabled
        self._animation_speed = animation_speed
        self._current_option: str | None = None
        self._applied_colors: dict[str, RGBColor] = {}  # Track colors applied to each light
        self._is_animating = False  # Track animation state

        # Error tracking for UI feedback
        self._last_error: str | None = None
        self._failed_lights: dict[str, str] = {}  # entity_id -> error message

        # Options caching - stores scene name -> file path mapping
        self._cached_options: list[str] = []
        self._scene_to_path: dict[str, Path] = {}  # Maps scene names to actual file paths
        self._options_cache_unsub: asyncio.TimerHandle | None = None

        # Light controller for shared logic
        self._light_controller = LightController(hass)

        # Generate unique ID and entity ID
        # Use first light's name as the base (per CLAUDE.md: select.{light_base_name}_scene)
        first_light_name = light_entities[0].split(".")[-1]
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_scene"
        self.entity_id = f"select.{first_light_name}_scene"

        _LOGGER.debug(
            "ChameleonSceneSelect initialized: entity_id=%s, unique_id=%s",
            self.entity_id,
            self._attr_unique_id,
        )

    def _get_animation_manager(self) -> AnimationManager | None:
        """Get the AnimationManager from hass.data."""
        return self.hass.data.get(DOMAIN, {}).get("animation_manager")

    def _get_runtime_animation_enabled(self) -> bool:
        """Get animation enabled state from runtime data (switch) or fall back to config."""
        entry_data = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
        return entry_data.get("animation_enabled", self._animation_enabled)

    def _get_runtime_brightness(self) -> int:
        """Get brightness from runtime data (number slider) or fall back to default."""
        entry_data = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
        return entry_data.get("brightness", DEFAULT_BRIGHTNESS)

    async def async_added_to_hass(self) -> None:
        """Run when entity is added to hass."""
        await super().async_added_to_hass()

        # Initial options scan
        await self._async_refresh_options()

        # Set up periodic options refresh
        self._options_cache_unsub = async_track_time_interval(
            self.hass,
            self._async_refresh_options_callback,
            OPTIONS_CACHE_INTERVAL,
        )

        _LOGGER.debug(
            "Options cache refresh scheduled every %s seconds",
            OPTIONS_CACHE_INTERVAL.total_seconds(),
        )

    async def async_will_remove_from_hass(self) -> None:
        """Run when entity is being removed."""
        await super().async_will_remove_from_hass()

        # Stop any running animations for our lights
        await self._stop_animations()

        # Cancel the options refresh timer
        if self._options_cache_unsub is not None:
            self._options_cache_unsub()
            self._options_cache_unsub = None

    async def _stop_animations(self) -> None:
        """Stop animations for all lights managed by this entity."""
        animation_manager = self._get_animation_manager()
        if animation_manager and self._is_animating:
            for light_entity in self._light_entities:
                await animation_manager.stop_animation(light_entity)
            self._is_animating = False
            _LOGGER.debug("Stopped animations for %s", self._light_entities)

    @callback
    def _async_refresh_options_callback(self, _now: object = None) -> None:
        """Callback wrapper for async_refresh_options."""
        self.hass.async_create_task(self._async_refresh_options())

    async def _async_refresh_options(self) -> None:
        """Refresh the cached options list by scanning the image directory."""
        new_options, new_scene_to_path = await self.hass.async_add_executor_job(self._scan_image_directory)

        if new_options != self._cached_options:
            old_count = len(self._cached_options)
            self._cached_options = new_options
            self._scene_to_path = new_scene_to_path
            _LOGGER.debug(
                "Options cache updated: %d -> %d scenes",
                old_count,
                len(new_options),
            )
            # Notify HA of state change if options changed
            self.async_write_ha_state()
        else:
            _LOGGER.debug("Options cache unchanged (%d scenes)", len(new_options))

    def _scan_image_directory(self) -> tuple[list[str], dict[str, Path]]:
        """Scan image directory for available scenes (runs in executor).

        Returns:
            Tuple of (sorted scene names list, scene name to file path mapping)
        """
        image_dir = Path(IMAGE_DIRECTORY)

        if not image_dir.exists():
            _LOGGER.warning("Image directory does not exist: %s", IMAGE_DIRECTORY)
            return [], {}

        scene_to_path: dict[str, Path] = {}
        for ext in SUPPORTED_EXTENSIONS:
            for image_path in image_dir.glob(f"*{ext}"):
                scene_name = _scene_name_from_filename(image_path.stem)
                # Only store first match if duplicate scene names exist
                if scene_name not in scene_to_path:
                    scene_to_path[scene_name] = image_path

        scenes = sorted(scene_to_path.keys())
        _LOGGER.debug("Found %d scenes in %s: %s", len(scenes), IMAGE_DIRECTORY, scenes)
        return scenes, scene_to_path

    @property
    def device_info(self):
        """Return device info for this entity."""
        if len(self._light_entities) == 1:
            name = f"Chameleon ({self._light_entities[0]})"
        else:
            name = f"Chameleon ({len(self._light_entities)} lights)"

        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": name,
            "manufacturer": "Chameleon",
            "model": "Scene Selector",
        }

    @property
    def extra_state_attributes(self):
        """Return extra state attributes."""
        attrs = {
            "light_entities": self._light_entities,
            "light_count": len(self._light_entities),
            "animation_enabled": self._animation_enabled,
            "animation_speed": self._animation_speed,
            "applied_colors": self._applied_colors,
            "is_animating": self._is_animating,
        }

        # Add error info if present
        if self._last_error:
            attrs["last_error"] = self._last_error
        if self._failed_lights:
            attrs["failed_lights"] = self._failed_lights

        return attrs

    @property
    def options(self) -> list[str]:
        """Return the list of available scene options (cached)."""
        return self._cached_options

    @property
    def current_option(self) -> str | None:
        """Return the currently selected option."""
        return self._current_option

    async def async_select_option(self, option: str) -> None:
        """Handle the user selecting an option."""
        # Get runtime values from switch/number entities (or fall back to config)
        animation_enabled = self._get_runtime_animation_enabled()
        brightness = self._get_runtime_brightness()

        _LOGGER.info(
            "Scene selected: '%s' for %d light(s): %s (animation=%s, brightness=%d%%)",
            option,
            len(self._light_entities),
            self._light_entities,
            animation_enabled,
            brightness,
        )

        # Clear previous error state
        self._last_error = None
        self._failed_lights = {}

        # Stop any existing animations before applying new scene
        await self._stop_animations()

        # Find the image file for this scene
        image_path = await self._find_image_for_scene(option)

        if image_path is None:
            self._last_error = f"Image not found for scene: {option}"
            _LOGGER.error(self._last_error)
            self.async_write_ha_state()
            return

        _LOGGER.debug("Found image for scene '%s': %s", option, image_path)

        # Extract colors and apply to lights (static or animated)
        if animation_enabled:
            result = await self._apply_colors_animated(image_path, brightness)
        else:
            result = await self._apply_colors_static(image_path, brightness)

        # Update state based on result
        if result.all_succeeded:
            # All lights updated successfully
            self._current_option = option
            self._applied_colors = result.applied_colors
            mode = "animation started" if animation_enabled else "applied"
            _LOGGER.info("Scene '%s' %s successfully to all lights", option, mode)
        elif result.all_failed:
            # All lights failed - don't update current_option
            self._last_error = "Failed to apply colors to any lights"
            self._failed_lights = result.failed_lights
            _LOGGER.error(
                "Scene '%s' failed: all %d lights failed",
                option,
                result.failed_count,
            )
        else:
            # Partial failure - update current_option but track failures
            self._current_option = option
            self._applied_colors = result.applied_colors
            self._failed_lights = result.failed_lights
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
            # Single light: use dominant color
            _LOGGER.debug("Extracting dominant color for single light")
            color = await extract_dominant_color(self.hass, image_path)
            if color:
                return await self._light_controller.apply_colors_to_lights(
                    {self._light_entities[0]: color},
                    brightness=brightness,
                )
            else:
                _LOGGER.error("Failed to extract dominant color from %s", image_path)
                return ApplyColorsResult()
        else:
            # Multiple lights: extract palette and distribute colors
            _LOGGER.debug("Extracting %d colors for %d lights", num_lights, num_lights)
            colors = await extract_color_palette(
                self.hass,
                image_path,
                color_count=max(num_lights, DEFAULT_COLOR_COUNT),
            )

            if not colors:
                _LOGGER.error("Failed to extract color palette from %s", image_path)
                return ApplyColorsResult()

            _LOGGER.debug("Extracted %d colors: %s", len(colors), colors[:num_lights])

            # Build light -> color mapping
            light_colors = {}
            for i, light_entity in enumerate(self._light_entities):
                color = colors[i % len(colors)]  # Cycle if fewer colors than lights
                light_colors[light_entity] = color

            return await self._light_controller.apply_colors_to_lights(
                light_colors,
                brightness=brightness,
            )

    async def _apply_colors_animated(self, image_path: Path, brightness: int = 100) -> ApplyColorsResult:
        """Extract colors from image and start synchronized animation for lights.

        All lights change color together, cycling through the gradient in sync.
        """
        animation_manager = self._get_animation_manager()
        if not animation_manager:
            _LOGGER.error("AnimationManager not available")
            return ApplyColorsResult()

        # Extract palette for animation
        colors = await extract_color_palette(
            self.hass,
            image_path,
            color_count=DEFAULT_COLOR_COUNT,
        )

        if not colors:
            _LOGGER.error("Failed to extract color palette from %s", image_path)
            return ApplyColorsResult()

        # Generate smooth gradient path for animation
        gradient = generate_gradient_path(colors, steps_between=10)
        _LOGGER.debug(
            "Generated gradient path with %d colors from %d palette colors",
            len(gradient),
            len(colors),
        )

        # Check availability of all lights first
        from .light_controller import LightResult

        results = []
        available_lights = []

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

        # Start synchronized animation for all available lights
        if available_lights:
            await animation_manager.start_synchronized_animation(
                available_lights,
                gradient,
                speed=self._animation_speed,
                brightness=brightness,
            )
            _LOGGER.info(
                "Started synchronized animation for %d lights",
                len(available_lights),
            )

        self._is_animating = True
        return ApplyColorsResult(results=results)

    async def _find_image_for_scene(self, scene_name: str) -> Path | None:
        """Find the image file path for a given scene name.

        Uses the cached scene-to-path mapping built during directory scan.
        This properly handles filenames with spaces, underscores, or any other characters.
        """
        # First, try the cached mapping (most reliable, handles spaces in filenames)
        if scene_name in self._scene_to_path:
            image_path = self._scene_to_path[scene_name]
            if image_path.exists():
                _LOGGER.debug("Found image from cache: scene='%s' -> %s", scene_name, image_path)
                return image_path
            # Path cached but file no longer exists - will fall through to rescan

        # Cache miss or stale cache - refresh and try again
        _LOGGER.debug("Cache miss for scene '%s', refreshing options", scene_name)
        await self._async_refresh_options()

        if scene_name in self._scene_to_path:
            image_path = self._scene_to_path[scene_name]
            if image_path.exists():
                return image_path

        _LOGGER.warning(
            "No image found for scene '%s' in %s",
            scene_name,
            IMAGE_DIRECTORY,
        )
        return None
