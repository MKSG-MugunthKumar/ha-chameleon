"""Animation loop and color cycling for Chameleon integration."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from homeassistant.components.light import ATTR_BRIGHTNESS, ATTR_RGB_COLOR, ATTR_TRANSITION
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
        brightness: int | None = None,
    ) -> None:
        """
        Initialize the animation controller.

        Args:
            hass: Home Assistant instance
            light_entity: Entity ID of the light to animate
            colors: List of RGB colors to cycle through
            speed: Seconds between color changes
            transition: Transition time for light changes
            brightness: Brightness percentage (1-100), converted to 0-255 for HA
        """
        self.hass = hass
        self.light_entity = light_entity
        self.colors = colors
        self.speed = speed
        self.transition = transition
        self.brightness = brightness

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

                # Build service call data
                service_data = {
                    ATTR_ENTITY_ID: self.light_entity,
                    ATTR_RGB_COLOR: list(color),
                    ATTR_TRANSITION: self.transition,
                }

                # Add brightness if specified
                if self.brightness is not None:
                    service_data[ATTR_BRIGHTNESS] = int((self.brightness / 100) * 255)

                # Apply color to light with transition
                await self.hass.services.async_call(
                    "light",
                    SERVICE_TURN_ON,
                    service_data,
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


class SynchronizedAnimationController:
    """Controls synchronized color animation for multiple lights.

    Each light displays a different color from the gradient (distributed evenly),
    and all lights cycle through colors together in sync.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        light_entities: list[str],
        colors: list[RGBColor],
        speed: int,
        transition: int = DEFAULT_TRANSITION_TIME,
        brightness: int | None = None,
    ) -> None:
        """
        Initialize the synchronized animation controller.

        Args:
            hass: Home Assistant instance
            light_entities: List of light entity IDs to animate together
            colors: List of RGB colors to cycle through
            speed: Seconds between color changes
            transition: Transition time for light changes
            brightness: Brightness percentage (1-100), converted to 0-255 for HA
        """
        self.hass = hass
        self.light_entities = light_entities
        self.colors = colors
        self.speed = speed
        self.transition = transition
        self.brightness = brightness

        self._running = False
        self._task: asyncio.Task | None = None
        self._current_index = 0

        # Calculate offset for each light to distribute colors evenly across the gradient
        num_lights = len(light_entities)
        num_colors = len(colors)
        # Spread lights evenly across the color gradient
        self._light_offsets = [(i * num_colors) // num_lights for i in range(num_lights)]

    @property
    def is_running(self) -> bool:
        """Return True if animation is currently running."""
        return self._running

    async def start(self) -> None:
        """Start the synchronized animation loop."""
        if self._running:
            _LOGGER.warning("Synchronized animation already running")
            return

        if not self.colors:
            _LOGGER.error("No colors provided for synchronized animation")
            return

        self._running = True
        self._task = asyncio.create_task(self._animation_loop())
        _LOGGER.info(
            "Started synchronized animation for %d lights with %d colors",
            len(self.light_entities),
            len(self.colors),
        )

    async def stop(self) -> None:
        """Stop the synchronized animation loop."""
        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        _LOGGER.info("Stopped synchronized animation for %d lights", len(self.light_entities))

    async def _animation_loop(self) -> None:
        """Main animation loop - each light shows a different color, all cycle in sync."""
        num_colors = len(self.colors)

        while self._running:
            try:
                # Apply a different color to each light based on its offset
                for i, light_entity in enumerate(self.light_entities):
                    # Each light gets a color at (current_index + its_offset) % num_colors
                    color_index = (self._current_index + self._light_offsets[i]) % num_colors
                    color = self.colors[color_index]

                    # Build service call data for this light
                    service_data = {
                        ATTR_ENTITY_ID: light_entity,
                        ATTR_RGB_COLOR: list(color),
                        ATTR_TRANSITION: self.transition,
                    }

                    # Add brightness if specified
                    if self.brightness is not None:
                        service_data[ATTR_BRIGHTNESS] = int((self.brightness / 100) * 255)

                    # Apply color to this light
                    await self.hass.services.async_call(
                        "light",
                        SERVICE_TURN_ON,
                        service_data,
                        blocking=False,
                    )

                # Move to next color (all lights advance together)
                self._current_index = (self._current_index + 1) % num_colors

                # Wait before next color change
                await asyncio.sleep(self.speed)

            except asyncio.CancelledError:
                break
            except Exception as e:
                _LOGGER.error("Error in synchronized animation loop: %s", e)
                await asyncio.sleep(1)  # Brief pause before retry


class AnimationManager:
    """Manages animation controllers (both individual and synchronized)."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the animation manager."""
        self.hass = hass
        self._controllers: dict[str, AnimationController] = {}
        self._sync_controller: SynchronizedAnimationController | None = None
        self._sync_lights: set[str] = set()  # Track which lights are in sync mode

    def get_controller(self, light_entity: str) -> AnimationController | None:
        """Get the animation controller for a light entity."""
        return self._controllers.get(light_entity)

    async def start_animation(
        self,
        light_entity: str,
        colors: list[RGBColor],
        speed: int,
        transition: int = DEFAULT_TRANSITION_TIME,
        brightness: int | None = None,
    ) -> None:
        """Start or update animation for a single light entity."""
        # Stop existing animation if running
        if light_entity in self._controllers:
            await self._controllers[light_entity].stop()

        # Remove from sync if it was in sync mode
        self._sync_lights.discard(light_entity)

        # Create new controller
        controller = AnimationController(
            self.hass,
            light_entity,
            colors,
            speed,
            transition,
            brightness,
        )
        self._controllers[light_entity] = controller
        await controller.start()

    async def start_synchronized_animation(
        self,
        light_entities: list[str],
        colors: list[RGBColor],
        speed: int,
        transition: int = DEFAULT_TRANSITION_TIME,
        brightness: int | None = None,
    ) -> None:
        """Start synchronized animation for multiple lights.

        All lights will change color at the same time, cycling through the gradient together.
        """
        # Stop any existing animations for these lights
        for light_entity in light_entities:
            if light_entity in self._controllers:
                await self._controllers[light_entity].stop()
                del self._controllers[light_entity]

        # Stop existing sync controller if running
        if self._sync_controller:
            await self._sync_controller.stop()

        # Create new synchronized controller
        self._sync_controller = SynchronizedAnimationController(
            self.hass,
            light_entities,
            colors,
            speed,
            transition,
            brightness,
        )
        self._sync_lights = set(light_entities)
        await self._sync_controller.start()

        _LOGGER.debug(
            "Started synchronized animation for lights: %s",
            light_entities,
        )

    async def stop_animation(self, light_entity: str) -> None:
        """Stop animation for a light entity."""
        # Check if it's in sync mode
        if light_entity in self._sync_lights:
            # Stop the entire sync controller when any sync light is stopped
            if self._sync_controller:
                await self._sync_controller.stop()
                self._sync_controller = None
            self._sync_lights.clear()
            return

        # Stop individual controller
        if light_entity in self._controllers:
            await self._controllers[light_entity].stop()
            del self._controllers[light_entity]

    async def stop_all(self) -> None:
        """Stop all running animations."""
        # Stop sync controller
        if self._sync_controller:
            await self._sync_controller.stop()
            self._sync_controller = None
        self._sync_lights.clear()

        # Stop individual controllers
        for controller in list(self._controllers.values()):
            await controller.stop()
        self._controllers.clear()

    def is_animating(self, light_entity: str) -> bool:
        """Check if a light entity is currently animating."""
        # Check sync mode first
        if light_entity in self._sync_lights:
            return self._sync_controller.is_running if self._sync_controller else False

        # Check individual controller
        controller = self._controllers.get(light_entity)
        return controller.is_running if controller else False
