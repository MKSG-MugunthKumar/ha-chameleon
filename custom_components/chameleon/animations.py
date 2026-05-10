"""Animation loop and color cycling for Chameleon integration.

A single :class:`AnimationController` handles both synchronized and staggered
modes — staggered just inserts a per-light random pre-tick delay. Speed,
brightness, and mode can be updated live without restarting the controller.

Speed of 0 disables animation entirely; the caller (number entity) is expected
to stop the controller before setting speed=0, so the loop is defensive but
should not normally see speed<=0 while running.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import TYPE_CHECKING

from homeassistant.components.light import ATTR_BRIGHTNESS, ATTR_RGB_COLOR, ATTR_TRANSITION
from homeassistant.const import ATTR_ENTITY_ID, SERVICE_TURN_ON

from .const import (
    ANIMATION_MODE_SYNC,
    DEFAULT_ANIMATION_MODE,
    DEFAULT_TRANSITION_TIME,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .color_extractor import RGBColor

_LOGGER = logging.getLogger(__name__)


class AnimationController:
    """Controls color animation for a group of lights in sync or staggered mode."""

    def __init__(
        self,
        hass: HomeAssistant,
        light_entities: list[str],
        colors: list[RGBColor],
        speed: float,
        mode: str = DEFAULT_ANIMATION_MODE,
        brightness: int | None = None,
        transition: float = DEFAULT_TRANSITION_TIME,
    ) -> None:
        """Initialize the animation controller.

        Args:
            hass: Home Assistant instance.
            light_entities: Light entity IDs to animate as a group.
            colors: Gradient colors to cycle through.
            speed: Seconds per color tick. Must be > 0 to start.
            mode: ``ANIMATION_MODE_SYNC`` or ``ANIMATION_MODE_STAGGERED``.
            brightness: Brightness percentage (0-100), converted to 0-255 for HA.
            transition: Light service transition seconds.
        """
        self.hass = hass
        self.light_entities = list(light_entities)
        self.colors = list(colors)
        self.speed = max(0.0, float(speed))
        self.mode = mode
        self.brightness = brightness
        self.transition = transition

        self._running = False
        self._tasks: list[asyncio.Task] = []

        # Distribute starting positions across lights so they show different
        # colors at any given moment (gradient spread effect).
        num_lights = max(1, len(self.light_entities))
        num_colors = max(1, len(self.colors))
        self._initial_offsets = [(i * num_colors) // num_lights for i in range(num_lights)]

    @property
    def is_running(self) -> bool:
        """Return True if animation is currently running."""
        return self._running

    @property
    def synchronized(self) -> bool:
        """Return True if running in synchronized mode."""
        return self.mode == ANIMATION_MODE_SYNC

    async def start(self) -> None:
        """Start the animation loop (one async task per light)."""
        if self._running:
            _LOGGER.warning("Animation already running")
            return

        if not self.colors or not self.light_entities:
            _LOGGER.error("Cannot start animation: no colors or no lights")
            return

        if self.speed <= 0:
            _LOGGER.warning("Cannot start animation with speed=%s", self.speed)
            return

        self._running = True
        self._tasks = [asyncio.create_task(self._light_loop(i, entity)) for i, entity in enumerate(self.light_entities)]
        _LOGGER.info(
            "Started %s animation for %d lights with %d colors at %.1fs",
            self.mode,
            len(self.light_entities),
            len(self.colors),
            self.speed,
        )

    async def stop(self) -> None:
        """Stop all animation tasks."""
        self._running = False

        for task in self._tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks.clear()

        _LOGGER.info("Stopped animation for %d lights", len(self.light_entities))

    def update_speed(self, speed: float) -> None:
        """Update the tick interval. Picked up on the next loop iteration."""
        self.speed = max(0.0, float(speed))

    def update_brightness(self, brightness: int | None) -> None:
        """Update brightness applied on the next color tick."""
        self.brightness = brightness

    def update_mode(self, mode: str) -> None:
        """Switch between sync and staggered. Effective on next iteration."""
        self.mode = mode

    async def _light_loop(self, light_index: int, light_entity: str) -> None:
        """Animation loop for a single light.

        Sync mode: zero pre-tick delay, all lights advance roughly in lockstep.
        Staggered mode: each light waits a random fraction of `speed` before
        applying its color, producing an organic non-uniform effect.
        """
        color_index = self._initial_offsets[light_index]

        while self._running:
            try:
                # Read live state each iteration so update_*() takes effect.
                speed = self.speed
                if speed <= 0:
                    # Defensive: caller should have stopped us first.
                    await asyncio.sleep(1)
                    continue

                delay = 0.0 if self.synchronized else random.uniform(0, speed)
                if delay > 0:
                    await asyncio.sleep(delay)

                if not self._running:
                    break

                color = self.colors[color_index % len(self.colors)]
                await self._apply_color(light_entity, color)
                color_index = (color_index + 1) % len(self.colors)

                remaining = max(0.0, speed - delay)
                if remaining > 0:
                    await asyncio.sleep(remaining)

            except asyncio.CancelledError:
                break
            except Exception as e:
                _LOGGER.error("Animation error for %s: %s", light_entity, e)
                await asyncio.sleep(1)

    async def _apply_color(self, light_entity: str, color: RGBColor) -> None:
        """Send a turn_on with the given color (and current brightness)."""
        service_data: dict[str, object] = {
            ATTR_ENTITY_ID: light_entity,
            ATTR_RGB_COLOR: list(color),
            ATTR_TRANSITION: self.transition,
        }

        # brightness=0 means lights should be off; the controller shouldn't
        # really be running in that state, but defensively skip the brightness
        # attr so we don't fight the off-state.
        if self.brightness is not None and self.brightness > 0:
            service_data[ATTR_BRIGHTNESS] = int((self.brightness / 100) * 255)

        await self.hass.services.async_call(
            "light",
            SERVICE_TURN_ON,
            service_data,
            blocking=False,
        )


class AnimationManager:
    """Owns one AnimationController per config entry."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the animation manager."""
        self.hass = hass
        self._controllers: dict[str, AnimationController] = {}

    def get_controller(self, entry_id: str) -> AnimationController | None:
        """Return the active controller for an entry, or None."""
        return self._controllers.get(entry_id)

    def is_running(self, entry_id: str) -> bool:
        """Return True if the entry has a running animation."""
        controller = self._controllers.get(entry_id)
        return controller.is_running if controller else False

    async def start(
        self,
        entry_id: str,
        light_entities: list[str],
        colors: list[RGBColor],
        speed: float,
        mode: str = DEFAULT_ANIMATION_MODE,
        brightness: int | None = None,
        transition: float = DEFAULT_TRANSITION_TIME,
    ) -> None:
        """Start (or replace) the animation for a config entry."""
        await self.stop(entry_id)

        controller = AnimationController(
            self.hass,
            light_entities,
            colors,
            speed,
            mode=mode,
            brightness=brightness,
            transition=transition,
        )
        self._controllers[entry_id] = controller
        await controller.start()

    async def stop(self, entry_id: str) -> None:
        """Stop the animation for a config entry, if any."""
        controller = self._controllers.pop(entry_id, None)
        if controller:
            await controller.stop()

    async def stop_all(self) -> None:
        """Stop all running animations across all entries."""
        for entry_id in list(self._controllers.keys()):
            await self.stop(entry_id)

    def update_speed(self, entry_id: str, speed: float) -> None:
        """Push a live speed update to the entry's controller, if running."""
        controller = self._controllers.get(entry_id)
        if controller:
            controller.update_speed(speed)

    def update_brightness(self, entry_id: str, brightness: int | None) -> None:
        """Push a live brightness update to the entry's controller, if running."""
        controller = self._controllers.get(entry_id)
        if controller:
            controller.update_brightness(brightness)

    def update_mode(self, entry_id: str, mode: str) -> None:
        """Push a live mode change to the entry's controller, if running."""
        controller = self._controllers.get(entry_id)
        if controller:
            controller.update_mode(mode)
