"""Media player tracking for the Chameleon "Now Playing" effect.

:class:`NowPlayingTracker` watches one media player and reports two events:

- ``on_cover(key)`` when the album art changes while the player is playing or
  paused;
- ``on_fallback()`` when the player has been idle/off/unavailable for the
  grace period.

It knows nothing about lights; the Chameleon light decides what those events
mean. Cover bytes come from the media player *entity*
(``async_get_media_image``), never from fetching ``entity_picture`` over HTTP,
which would drag in auth tokens, internal/external URLs, and provider-specific
proxy URL formats.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

from homeassistant.components.media_player import DOMAIN as MEDIA_PLAYER_DOMAIN
from homeassistant.const import STATE_PAUSED, STATE_PLAYING
from homeassistant.core import CALLBACK_TYPE, Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.helpers.event import async_call_later, async_track_state_change_event

_LOGGER = logging.getLogger(__name__)

DEFAULT_GRACE_SECONDS = 30.0
COVER_FETCH_TIMEOUT = 10.0

_ACTIVE_STATES = frozenset({STATE_PLAYING, STATE_PAUSED})


def _is_active(state: State | None) -> bool:
    """Return True while the player is playing or paused."""
    return state is not None and state.state in _ACTIVE_STATES


def cover_key(state: State | None) -> str | None:
    """Return a stable identity for the player's current cover, or None.

    ``entity_picture`` for proxied art looks like
    ``/api/media_player_proxy/<id>?token=<t>&cache=<hash>``. HA rotates the
    token every few minutes, so the full string is not a stable identity; the
    ``cache`` value is derived from the image itself. Remotely accessible art
    has no ``cache`` parameter, so the URL itself is the identity.
    """
    if state is None or state.state not in _ACTIVE_STATES:
        return None
    picture = state.attributes.get("entity_picture")
    if not picture:
        return None
    cache = parse_qs(urlparse(picture).query).get("cache")
    return cache[0] if cache else str(picture)


class NowPlayingTracker:
    """Watch one media player for cover changes and end of playback."""

    def __init__(self, hass: HomeAssistant, media_player: str, grace: float = DEFAULT_GRACE_SECONDS) -> None:
        """Initialize the tracker (does not subscribe until :meth:`start`)."""
        self.hass = hass
        self.media_player = media_player
        self._grace = grace
        self._unsub_state: CALLBACK_TYPE | None = None
        self._cancel_grace: CALLBACK_TYPE | None = None
        self._on_cover: Callable[[str], None] | None = None
        self._on_fallback: Callable[[], None] | None = None
        self._last_key: str | None = None

    @property
    def is_running(self) -> bool:
        """Return True while subscribed to the player."""
        return self._unsub_state is not None

    def current_cover_key(self) -> str | None:
        """Return the cover identity of the player's current state."""
        return cover_key(self.hass.states.get(self.media_player))

    def start(self, on_cover: Callable[[str], None], on_fallback: Callable[[], None]) -> None:
        """Subscribe to the player. Restarts cleanly if already running."""
        self.stop()
        self._on_cover = on_cover
        self._on_fallback = on_fallback
        self._last_key = self.current_cover_key()
        self._unsub_state = async_track_state_change_event(self.hass, [self.media_player], self._handle_state_change)

    def stop(self) -> None:
        """Unsubscribe and cancel any pending fallback. Safe to call twice."""
        if self._unsub_state is not None:
            self._unsub_state()
            self._unsub_state = None
        self._cancel_grace_timer()

    @callback
    def _handle_state_change(self, event: Event[EventStateChangedData]) -> None:
        new_state = event.data["new_state"]
        if not _is_active(new_state):
            self._start_grace_timer()
            return

        self._cancel_grace_timer()
        key = cover_key(new_state)
        # No artwork while playing/paused (radio, line-in): hold what's showing.
        if key is None or key == self._last_key:
            return
        self._last_key = key
        if self._on_cover is not None:
            self._on_cover(key)

    def _start_grace_timer(self) -> None:
        if self._cancel_grace is None:
            self._cancel_grace = async_call_later(self.hass, self._grace, self._grace_expired)

    def _cancel_grace_timer(self) -> None:
        if self._cancel_grace is not None:
            self._cancel_grace()
            self._cancel_grace = None

    @callback
    def _grace_expired(self, _now: datetime | None) -> None:
        self._cancel_grace = None
        self.stop()
        if self._on_fallback is not None:
            self._on_fallback()

    async def async_fetch_cover(self) -> bytes | None:
        """Return the current cover's bytes from the player entity, or None."""
        component: Any = self.hass.data.get(MEDIA_PLAYER_DOMAIN)
        entity = component.get_entity(self.media_player) if component is not None else None
        if entity is None:
            _LOGGER.warning("Media player %s not found; can't fetch cover art", self.media_player)
            return None
        try:
            async with asyncio.timeout(COVER_FETCH_TIMEOUT):
                image, _content_type = await entity.async_get_media_image()
        except Exception as err:
            _LOGGER.warning("Fetching cover art from %s failed: %s", self.media_player, err)
            return None
        return image or None
