"""Animation loop and color cycling for Chameleon integration."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from homeassistant.components.light import ATTR_RGB_COLOR, ATTR_TRANSITION
from homeassistant.const import ATTR_ENTITY_ID, SERVICE_TURN_ON

from .const import DEFAULT_TRANSITION_TIME

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .color_extractor import RGBColor

_LOGGER = logging.getLogger(__name__)


class AnimationController:
    """Controls color animation for a light entity."""

    def __init__(
        self,
        hass: HomeAssistant,
        light_entity: str,
        colors: list[RGBColor],
        speed: int,
        transition: int = DEFAULT_TRANSITION_TIME,
    ) -> None:
        """
        Initialize the animation controller.

        Args:
            hass: Home Assistant instance
            light_entity: Entity ID of the light to animate
            colors: List of RGB colors to cycle through
            speed: Seconds between color changes
            transition: Transition time for light changes
        """
        self.hass = hass
        self.light_entity = light_entity
        self.colors = colors
        self.speed = speed
        self.transition = transition

        self._running = False
        self._task: asyncio.Task | None = None
        self._current_index = 0

    @property
    def is_running(self) -> bool:
        """Return True if animation is currently running."""
        return self._running

    async def start(self) -> None:
        """Start the animation loop."""
        if self._running:
            _LOGGER.warning("Animation already running for %s", self.light_entity)
            return

        if not self.colors:
            _LOGGER.error("No colors provided for animation on %s", self.light_entity)
            return

        self._running = True
        self._task = asyncio.create_task(self._animation_loop())
        _LOGGER.info(
            "Started animation for %s with %d colors",
            self.light_entity,
            len(self.colors),
        )

    async def stop(self) -> None:
        """Stop the animation loop."""
        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        _LOGGER.info("Stopped animation for %s", self.light_entity)

    async def _animation_loop(self) -> None:
        """Main animation loop - cycles through colors."""
        while self._running:
            try:
                color = self.colors[self._current_index]

                # Apply color to light with transition
                await self.hass.services.async_call(
                    "light",
                    SERVICE_TURN_ON,
                    {
                        ATTR_ENTITY_ID: self.light_entity,
                        ATTR_RGB_COLOR: list(color),
                        ATTR_TRANSITION: self.transition,
                    },
                    blocking=False,
                )

                # Move to next color
                self._current_index = (self._current_index + 1) % len(self.colors)

                # Wait before next color change
                await asyncio.sleep(self.speed)

            except asyncio.CancelledError:
                break
            except Exception as e:
                _LOGGER.error("Error in animation loop for %s: %s", self.light_entity, e)
                await asyncio.sleep(1)  # Brief pause before retry

    def update_colors(self, colors: list[RGBColor]) -> None:
        """Update the color palette without stopping animation."""
        self.colors = colors
        self._current_index = 0

    def update_speed(self, speed: int) -> None:
        """Update animation speed."""
        self.speed = speed


class AnimationManager:
    """Manages multiple animation controllers."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the animation manager."""
        self.hass = hass
        self._controllers: dict[str, AnimationController] = {}

    def get_controller(self, light_entity: str) -> AnimationController | None:
        """Get the animation controller for a light entity."""
        return self._controllers.get(light_entity)

    async def start_animation(
        self,
        light_entity: str,
        colors: list[RGBColor],
        speed: int,
        transition: int = DEFAULT_TRANSITION_TIME,
    ) -> None:
        """Start or update animation for a light entity."""
        # Stop existing animation if running
        if light_entity in self._controllers:
            await self._controllers[light_entity].stop()

        # Create new controller
        controller = AnimationController(
            self.hass,
            light_entity,
            colors,
            speed,
            transition,
        )
        self._controllers[light_entity] = controller
        await controller.start()

    async def stop_animation(self, light_entity: str) -> None:
        """Stop animation for a light entity."""
        if light_entity in self._controllers:
            await self._controllers[light_entity].stop()
            del self._controllers[light_entity]

    async def stop_all(self) -> None:
        """Stop all running animations."""
        for controller in list(self._controllers.values()):
            await controller.stop()
        self._controllers.clear()

    def is_animating(self, light_entity: str) -> bool:
        """Check if a light entity is currently animating."""
        controller = self._controllers.get(light_entity)
        return controller.is_running if controller else False
