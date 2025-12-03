"""Light controller for Chameleon integration.

This module provides shared light control logic used by both the select entity
and services. It handles:
- Light availability checking
- RGB color application with proper error handling
- Tracking of applied colors and failures
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import ClassVar

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_RGB_COLOR,
    ATTR_SUPPORTED_COLOR_MODES,
    ATTR_TRANSITION,
    ColorMode,
)
from homeassistant.components.light import (
    DOMAIN as LIGHT_DOMAIN,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant

from .color_extractor import RGBColor
from .const import DEFAULT_TRANSITION_TIME

_LOGGER = logging.getLogger(__name__)


class LightError(Enum):
    """Types of light errors."""

    NOT_FOUND = "not_found"
    UNAVAILABLE = "unavailable"
    NO_RGB_SUPPORT = "no_rgb_support"
    SERVICE_CALL_FAILED = "service_call_failed"


@dataclass
class LightResult:
    """Result of applying color to a light."""

    entity_id: str
    success: bool
    color: RGBColor | None = None
    error: LightError | None = None
    error_message: str | None = None


@dataclass
class ApplyColorsResult:
    """Result of applying colors to multiple lights."""

    results: list[LightResult] = field(default_factory=list)

    @property
    def all_succeeded(self) -> bool:
        """Return True if all lights succeeded."""
        return all(r.success for r in self.results)

    @property
    def all_failed(self) -> bool:
        """Return True if all lights failed."""
        return all(not r.success for r in self.results)

    @property
    def partial_failure(self) -> bool:
        """Return True if some lights failed but not all."""
        return not self.all_succeeded and not self.all_failed

    @property
    def succeeded_count(self) -> int:
        """Return count of successful applications."""
        return sum(1 for r in self.results if r.success)

    @property
    def failed_count(self) -> int:
        """Return count of failed applications."""
        return sum(1 for r in self.results if not r.success)

    @property
    def applied_colors(self) -> dict[str, RGBColor]:
        """Return dict of successfully applied colors."""
        return {r.entity_id: r.color for r in self.results if r.success and r.color}

    @property
    def failed_lights(self) -> dict[str, str]:
        """Return dict of failed lights with error messages."""
        return {r.entity_id: r.error_message or str(r.error) for r in self.results if not r.success}


class LightController:
    """Controller for applying colors to lights with proper error handling."""

    # Color modes that support RGB
    RGB_COLOR_MODES: ClassVar[set[ColorMode]] = {
        ColorMode.RGB,
        ColorMode.RGBW,
        ColorMode.RGBWW,
        ColorMode.HS,
        ColorMode.XY,
    }

    def __init__(self, hass: HomeAssistant, transition_time: int = DEFAULT_TRANSITION_TIME) -> None:
        """Initialize the light controller.

        Args:
            hass: Home Assistant instance
            transition_time: Default transition time in seconds for light changes
        """
        self.hass = hass
        self.transition_time = transition_time

    def check_light_availability(self, entity_id: str) -> tuple[bool, LightError | None, str | None]:
        """Check if a light entity is available and supports RGB.

        Args:
            entity_id: The light entity ID to check

        Returns:
            Tuple of (is_available, error_type, error_message)
        """
        state = self.hass.states.get(entity_id)

        if state is None:
            return (
                False,
                LightError.NOT_FOUND,
                f"Light entity '{entity_id}' does not exist",
            )

        if state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return (
                False,
                LightError.UNAVAILABLE,
                f"Light '{entity_id}' is {state.state}",
            )

        # Check for RGB support
        supported_modes = state.attributes.get(ATTR_SUPPORTED_COLOR_MODES, [])
        if supported_modes:
            # Convert to set for comparison
            supported_set = set(supported_modes)
            if not supported_set & self.RGB_COLOR_MODES:
                return (
                    False,
                    LightError.NO_RGB_SUPPORT,
                    f"Light '{entity_id}' does not support RGB colors (modes: {supported_modes})",
                )

        return (True, None, None)

    async def apply_color_to_light(
        self,
        entity_id: str,
        color: RGBColor,
        transition: int | None = None,
        brightness: int | None = None,
        skip_availability_check: bool = False,
    ) -> LightResult:
        """Apply an RGB color to a specific light entity.

        Args:
            entity_id: The light entity ID
            color: RGB color tuple (r, g, b)
            transition: Transition time in seconds (uses default if None)
            brightness: Brightness percentage (1-100), converted to 0-255 for HA
            skip_availability_check: Skip availability check (useful for batch operations)

        Returns:
            LightResult with success status and any errors
        """
        # Check availability first (unless skipped)
        if not skip_availability_check:
            is_available, error, error_msg = self.check_light_availability(entity_id)
            if not is_available:
                _LOGGER.warning("Light unavailable: %s", error_msg)
                return LightResult(
                    entity_id=entity_id,
                    success=False,
                    error=error,
                    error_message=error_msg,
                )

        transition_time = transition if transition is not None else self.transition_time

        # Build service call data
        service_data = {
            ATTR_ENTITY_ID: entity_id,
            ATTR_RGB_COLOR: list(color),
            ATTR_TRANSITION: transition_time,
        }

        # Add brightness if specified (convert from 1-100% to 0-255)
        if brightness is not None:
            ha_brightness = int((brightness / 100) * 255)
            service_data[ATTR_BRIGHTNESS] = ha_brightness
            _LOGGER.info(
                "Applying color RGB(%d, %d, %d) to %s (transition=%ds, brightness=%d%%)",
                color[0],
                color[1],
                color[2],
                entity_id,
                transition_time,
                brightness,
            )
        else:
            _LOGGER.info(
                "Applying color RGB(%d, %d, %d) to %s (transition=%ds)",
                color[0],
                color[1],
                color[2],
                entity_id,
                transition_time,
            )

        try:
            await self.hass.services.async_call(
                LIGHT_DOMAIN,
                SERVICE_TURN_ON,
                service_data,
                blocking=True,
            )
            _LOGGER.debug("Successfully applied color to %s", entity_id)
            return LightResult(
                entity_id=entity_id,
                success=True,
                color=color,
            )
        except Exception as e:
            error_msg = f"Failed to apply color to {entity_id}: {e}"
            _LOGGER.error(error_msg)
            return LightResult(
                entity_id=entity_id,
                success=False,
                color=color,
                error=LightError.SERVICE_CALL_FAILED,
                error_message=error_msg,
            )

    async def apply_colors_to_lights(
        self,
        light_colors: dict[str, RGBColor],
        transition: int | None = None,
        brightness: int | None = None,
    ) -> ApplyColorsResult:
        """Apply colors to multiple lights.

        Args:
            light_colors: Dict mapping entity_id to RGB color
            transition: Transition time in seconds (uses default if None)
            brightness: Brightness percentage (1-100), converted to 0-255 for HA

        Returns:
            ApplyColorsResult with all results
        """
        result = ApplyColorsResult()

        # First check all lights for availability
        available_lights: dict[str, RGBColor] = {}
        for entity_id, color in light_colors.items():
            is_available, error, error_msg = self.check_light_availability(entity_id)
            if is_available:
                available_lights[entity_id] = color
            else:
                result.results.append(
                    LightResult(
                        entity_id=entity_id,
                        success=False,
                        error=error,
                        error_message=error_msg,
                    )
                )
                _LOGGER.warning("Skipping unavailable light: %s", error_msg)

        # Apply colors to available lights
        for entity_id, color in available_lights.items():
            light_result = await self.apply_color_to_light(
                entity_id,
                color,
                transition=transition,
                brightness=brightness,
                skip_availability_check=True,  # Already checked
            )
            result.results.append(light_result)

        # Log summary
        if result.all_succeeded:
            _LOGGER.debug("All %d lights updated successfully", len(result.results))
        elif result.all_failed:
            _LOGGER.error("All %d lights failed to update", len(result.results))
        else:
            _LOGGER.warning(
                "Partial failure: %d/%d lights updated",
                result.succeeded_count,
                len(result.results),
            )

        return result


def get_light_controller(hass: HomeAssistant) -> LightController:
    """Get or create a LightController instance.

    This can be extended to cache the controller in hass.data if needed.

    Args:
        hass: Home Assistant instance

    Returns:
        LightController instance
    """
    return LightController(hass)
