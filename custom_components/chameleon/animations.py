"""Animation loop and color cycling for Chameleon integration.

A single :class:`AnimationController` handles both synchronized and staggered
transition styles. The animation runs as one continuous fade: each color tick
is sent with ``transition = transition`` so the light is always mid-fade
between colors, producing smooth gradient flow with no discontinuous jumps.

Staggered style applies a one-time random phase offset at the start of each
light's loop so members of a group desync from each other; subsequent ticks
run at the same ``transition`` cadence with that offset preserved.

Transition of 0 disables animation entirely; the caller (number entity) is
expected to stop the controller before setting transition=0, so the loop is
defensive but should not normally see transition<=0 while running.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import TYPE_CHECKING

from homeassistant.components.light import ATTR_BRIGHTNESS, ATTR_RGB_COLOR, ATTR_TRANSITION
from homeassistant.const import ATTR_ENTITY_ID, SERVICE_TURN_ON

from .const import DEFAULT_TRANSITION_STYLE, TRANSITION_STYLE_SYNC

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .color_extractor import RGBColor

_LOGGER = logging.getLogger(__name__)


class AnimationController:
    """Controls color animation for a group of lights in sync or staggered style."""

    def __init__(
        self,
        hass: HomeAssistant,
        light_entities: list[str],
        colors: list[RGBColor],
        transition: float,
        style: str = DEFAULT_TRANSITION_STYLE,
        brightness: int | None = None,
    ) -> None:
        """Initialize the animation controller.

        Args:
            hass: Home Assistant instance.
            light_entities: Light entity IDs to animate as a group.
            colors: Gradient colors to cycle through.
            transition: Seconds per color tick. Also used as the fade duration
                so the light is continuously transitioning between colors.
                Must be > 0 to start.
            style: ``TRANSITION_STYLE_SYNC`` or ``TRANSITION_STYLE_STAGGERED``.
            brightness: Brightness percentage (0-100), converted to 0-255 for HA.
        """
        self.hass = hass
        self.light_entities = list(light_entities)
        self.colors = list(colors)
        self.transition = max(0.0, float(transition))
        self.style = style
        self.brightness = brightness

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
        """Return True if running in synchronized style."""
        return self.style == TRANSITION_STYLE_SYNC

    async def start(self) -> None:
        """Start the animation loop (one async task per light)."""
        if self._running:
            _LOGGER.warning("Animation already running")
            return

        if not self.colors or not self.light_entities:
            _LOGGER.error("Cannot start animation: no colors or no lights")
            return

        if self.transition <= 0:
            _LOGGER.warning("Cannot start animation with transition=%s", self.transition)
            return

        self._running = True
        self._tasks = [asyncio.create_task(self._light_loop(i, entity)) for i, entity in enumerate(self.light_entities)]
        _LOGGER.info(
            "Started %s animation for %d lights with %d colors at %.1fs",
            self.style,
            len(self.light_entities),
            len(self.colors),
            self.transition,
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

    def update_transition(self, transition: float) -> None:
        """Update the tick interval. Picked up on the next loop iteration."""
        self.transition = max(0.0, float(transition))

    def update_brightness(self, brightness: int | None) -> None:
        """Update brightness applied on the next color tick."""
        self.brightness = brightness

    def update_style(self, style: str) -> None:
        """Switch between sync and staggered. Effective on next iteration."""
        self.style = style

    async def _light_loop(self, light_index: int, light_entity: str) -> None:
        """Animation loop for a single light.

        In staggered style each light waits a one-time random phase offset
        before its first tick; from then on it runs at ``transition`` cadence
        with that offset preserved relative to the other lights' tasks.

        Each tick sends ``turn_on(transition=transition)`` so the light fades
        continuously into the next color. The ``asyncio.sleep(transition)``
        after each apply waits for the fade to complete before issuing the
        next target color.
        """
        color_index = self._initial_offsets[light_index]

        # One-time phase offset for staggered style. After this each light's
        # cycle runs at exactly `transition` cadence but offset from its peers.
        if not self.synchronized and self.transition > 0:
            await asyncio.sleep(random.uniform(0, self.transition))

        while self._running:
            try:
                # Read live state each iteration so update_*() takes effect.
                transition = self.transition
                if transition <= 0:
                    # Defensive: caller should have stopped us first.
                    await asyncio.sleep(1)
                    continue

                color = self.colors[color_index % len(self.colors)]
                await self._apply_color(light_entity, color, transition=transition)
                color_index = (color_index + 1) % len(self.colors)

                # Wait for the fade to complete before targeting the next color.
                await asyncio.sleep(transition)

            except asyncio.CancelledError:
                break
            except Exception as e:
                _LOGGER.error("Animation error for %s: %s", light_entity, e)
                await asyncio.sleep(1)

    async def _apply_color(self, light_entity: str, color: RGBColor, transition: float) -> None:
        """Send a turn_on with the given color, brightness, and fade duration."""
        service_data: dict[str, object] = {
            ATTR_ENTITY_ID: light_entity,
            ATTR_RGB_COLOR: list(color),
            ATTR_TRANSITION: transition,
        }

        # brightness=0 means lights should be off; the controller shouldn't
        # really be running in that state, but defensively skip the brightness
        # attr so we don't fight the off-state.
        if self.brightness is not None and self.brightness > 0:
            service_data[ATTR_BRIGHTNESS] = int((self.brightness / 100) * 255)

        # blocking=True so cancellation is clean: when manager.stop() cancels
        # this task, no `turn_on` calls are left queued in HA to fire after a
        # subsequent `turn_off` (which would visibly relight the lamps).
        await self.hass.services.async_call(
            "light",
            SERVICE_TURN_ON,
            service_data,
            blocking=True,
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
        transition: float,
        style: str = DEFAULT_TRANSITION_STYLE,
        brightness: int | None = None,
    ) -> None:
        """Start (or replace) the animation for a config entry."""
        await self.stop(entry_id)

        controller = AnimationController(
            self.hass,
            light_entities,
            colors,
            transition,
            style=style,
            brightness=brightness,
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

    def update_transition(self, entry_id: str, transition: float) -> None:
        """Push a live transition update to the entry's controller, if running."""
        controller = self._controllers.get(entry_id)
        if controller:
            controller.update_transition(transition)

    def update_brightness(self, entry_id: str, brightness: int | None) -> None:
        """Push a live brightness update to the entry's controller, if running."""
        controller = self._controllers.get(entry_id)
        if controller:
            controller.update_brightness(brightness)

    def update_style(self, entry_id: str, style: str) -> None:
        """Push a live style change to the entry's controller, if running."""
        controller = self._controllers.get(entry_id)
        if controller:
            controller.update_style(style)
