# Now Playing (Media Player) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Chameleon light linked to one media player gains a `Now Playing - <player name>` effect that applies the current album art's colours, follows cover changes, holds on pause, and falls back to the previous scene 30 s after playback ends.

**Architecture:** A new `NowPlayingTracker` (`now_playing.py`) watches one media player and reports `on_cover(key)` / `on_fallback()`; it knows nothing about lights. `light.py` is refactored so the static/animated apply paths take a palette instead of an image path, then gains the Now Playing mode on top. The config flow stores an optional `media_player` in `entry.data`.

**Tech Stack:** Home Assistant custom integration (Python 3.14, HA >= 2024.11), ColorThief, pytest with the repo's mocked-HA `tests/conftest.py`.

**Spec:** `docs/superpowers/specs/2026-10-14-media-player-now-playing-design.md`

## Global Constraints

- Precondition: the member-light availability work (`is_light_reachable`, `_async_member_state_changed`, `tests/test_availability.py`) is committed before Task 1. This plan edits the same files.
- Minimum Home Assistant: `2024.11.0` (already in `hacs.json`). No other version bump.
- No config entry migration and no `VERSION` bump: `media_player` is an optional key; absent or `None` means "not configured".
- Effect display name: `Now Playing - <friendly name>` with an ASCII hyphen. Internally the mode is the marker `NOW_PLAYING_EFFECT = "__now_playing__"`, never the display string.
- Grace period: `30` seconds. Cover fetch timeout: `10` seconds.
- Never fetch `entity_picture` over HTTP; get bytes from the media player entity's `async_get_media_image()`.
- Cover identity: the `cache` query parameter of `entity_picture`; fall back to the full string when there is no `cache` parameter.
- All state-changing work runs under `ChameleonLight._lock`; tracker callbacks only record state and schedule tasks via `self._entry.async_create_task(self.hass, ...)`.
- Code style (CLAUDE.md): full type hints, docstrings, ASCII `-` in comments (ruff `RUF003`), conventional commits, `light_controller.py` for light service calls.
- Test command (no local venv; mocked HA needs no compiler). Referred to below as `$TEST`:
  `uv run --no-project --with pytest --with pytest-asyncio --with pytest-cov --with voluptuous --with Pillow --with colorthief==0.2.1 pytest -p no:cacheprovider --no-cov`
- Lint/type gate: `pre-commit run --all-files` must pass before each commit (the git hook runs it anyway).

## Review Focus

1. **Transition slider crosses zero while in Now Playing** (`async_reapply_current_scene` → `_apply_effect(marker)`): should re-apply the current cover in the new static/animated mode and must not overwrite `_fallback_effect` with Now Playing. Test in Task 5.
2. **Player renamed while the effect list is showing:** `effect` / `effect_list` should show the new name promptly, not only after the next unrelated state write. Test in Task 5 (`_async_media_player_changed`).
3. **The fallback scene's image was deleted:** fallback should stop the tracker, leave `effect` as `None` and set `last_error`, not leave a stale "Now Playing" with no tracker. Test in Task 5.
4. **Playing or paused with no artwork (radio, line-in) while already in Now Playing:** hold the current colours; no cover event, no grace timer, no fallback. Test in Task 2.
5. **`turn_on(effect="Now Playing - X")` on an entry with no player configured** (stale automation after Reconfigure removed the player): treated as an unknown scene (`Image not found` error), no crash. Test in Task 5.

---

## File Structure

| File                                                               | Change | Responsibility                                                                      |
| ------------------------------------------------------------------ | ------ | ----------------------------------------------------------------------------------- |
| `custom_components/chameleon/color_extractor.py`                   | Modify | Accept `Path \| bytes` image sources                                                |
| `custom_components/chameleon/now_playing.py`                       | Create | `cover_key()` + `NowPlayingTracker`: watch a player, grace timer, fetch cover bytes |
| `custom_components/chameleon/const.py`                             | Modify | `CONF_MEDIA_PLAYER`, `NOW_PLAYING_EFFECT`, `NOW_PLAYING_PREFIX`                     |
| `custom_components/chameleon/config_flow.py`                       | Modify | Optional media player in user + reconfigure steps                                   |
| `custom_components/chameleon/strings.json`, `translations/en.json` | Modify | Field labels/descriptions                                                           |
| `custom_components/chameleon/helpers.py`                           | Modify | Rename `_get_light_friendly_name` → `get_friendly_name` (now used for players too)  |
| `custom_components/chameleon/light.py`                             | Modify | Palette-based apply paths (Task 4), Now Playing mode (Task 5)                       |
| `tests/conftest.py`                                                | Modify | Mock `homeassistant.components.media_player`, `STATE_PLAYING`/`STATE_PAUSED`        |
| `tests/test_color_extractor.py`                                    | Modify | Bytes extraction test                                                               |
| `tests/test_now_playing.py`                                        | Create | Tracker tests                                                                       |
| `tests/test_config_flow.py`                                        | Modify | Media player field tests; updated expectations                                      |
| `tests/test_light_palette.py`                                      | Create | Refactor regression tests                                                           |
| `tests/test_light_now_playing.py`                                  | Create | Now Playing mode tests                                                              |
| `README.md`                                                        | Modify | Roadmap ticks + usage docs                                                          |

---

### Task 1: Colour extraction from bytes

**Files:**

- Modify: `custom_components/chameleon/color_extractor.py:1-95`
- Test: `tests/test_color_extractor.py`

**Interfaces:**

- Consumes: nothing.
- Produces:

  - `async def extract_dominant_color(hass: HomeAssistant, image: Path | bytes, quality: int = DEFAULT_QUALITY) -> RGBColor | None`
  - `async def extract_color_palette(hass: HomeAssistant, image: Path | bytes, color_count: int = DEFAULT_COLOR_COUNT, quality: int = DEFAULT_QUALITY) -> list[RGBColor]`
  - Existing callers pass the image positionally; renaming the parameter `image_path` → `image` breaks no caller (verify with `grep -rn "image_path=" custom_components`; expected: no matches for these two functions).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_color_extractor.py`:

```python
class TestExtractFromBytes:
    """Album art arrives as bytes, not a file path."""

    @pytest.mark.asyncio
    async def test_palette_from_png_bytes(self):
        import io
        from unittest.mock import AsyncMock, MagicMock

        from PIL import Image

        from custom_components.chameleon.color_extractor import extract_color_palette, extract_dominant_color

        # Left half pure red, right half pure blue
        image = Image.new("RGB", (40, 20), (255, 0, 0))
        image.paste((0, 0, 255), (20, 0, 40, 20))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        png = buffer.getvalue()

        hass = MagicMock()
        hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))

        palette = await extract_color_palette(hass, png, color_count=2)
        dominant = await extract_dominant_color(hass, png)

        assert len(palette) >= 2
        assert all(len(c) == 3 for c in palette)
        assert dominant is not None
        # ColorThief quantises, so check the channel that dominates rather than exact values
        assert max(dominant) in (dominant[0], dominant[2])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `$TEST tests/test_color_extractor.py::TestExtractFromBytes -v`
Expected: FAIL - ColorThief is handed `str(b"...")` and raises; the function logs and returns `[]`, so `assert len(palette) >= 2` fails.

- [ ] **Step 3: Implement**

In `custom_components/chameleon/color_extractor.py`, add `import io` next to `import logging`, and replace the two sync helpers and the two async extractors (keep everything from `def generate_gradient_path` onward unchanged):

```python
def _open_image(image: str | bytes) -> str | io.BytesIO:
    """Return something ColorThief can read: a path string or an in-memory file."""
    return io.BytesIO(image) if isinstance(image, bytes) else image


def _describe(image: Path | bytes) -> str:
    """Short log-friendly description of an image source."""
    return f"<{len(image)} bytes>" if isinstance(image, bytes) else str(image)


def _sync_extract_dominant_color(image: str | bytes, quality: int) -> RGBColor | None:
    """Synchronous color extraction - runs in executor."""
    from colorthief import ColorThief

    color_thief = ColorThief(_open_image(image))
    return color_thief.get_color(quality=quality)


def _sync_extract_palette(image: str | bytes, color_count: int, quality: int) -> list[RGBColor]:
    """Synchronous palette extraction - runs in executor."""
    from colorthief import ColorThief

    color_thief = ColorThief(_open_image(image))
    return color_thief.get_palette(color_count=color_count, quality=quality)


async def extract_dominant_color(
    hass: HomeAssistant,
    image: Path | bytes,
    quality: int = DEFAULT_QUALITY,
) -> RGBColor | None:
    """
    Extract the single dominant color from an image.

    Args:
        hass: Home Assistant instance (needed for executor)
        image: Path to an image file, or the image's raw bytes (e.g. album art)
        quality: Color extraction quality (1=highest, 10=fastest)

    Returns:
        RGB tuple (r, g, b) or None if extraction fails
    """
    try:
        _LOGGER.debug("Extracting dominant color from %s", _describe(image))
        color = await hass.async_add_executor_job(
            _sync_extract_dominant_color,
            image if isinstance(image, bytes) else str(image),
            quality,
        )
        _LOGGER.debug("Extracted dominant color: %s", color)
        return color
    except Exception as e:
        _LOGGER.error("Failed to extract dominant color from %s: %s", _describe(image), e)
        return None


async def extract_color_palette(
    hass: HomeAssistant,
    image: Path | bytes,
    color_count: int = DEFAULT_COLOR_COUNT,
    quality: int = DEFAULT_QUALITY,
) -> list[RGBColor]:
    """
    Extract a palette of colors from an image.

    Args:
        hass: Home Assistant instance (needed for executor)
        image: Path to an image file, or the image's raw bytes (e.g. album art)
        color_count: Number of colors to extract
        quality: Color extraction quality (1=highest, 10=fastest)

    Returns:
        List of RGB tuples, or empty list if extraction fails
    """
    try:
        _LOGGER.debug("Extracting %d colors from %s", color_count, _describe(image))
        colors = await hass.async_add_executor_job(
            _sync_extract_palette,
            image if isinstance(image, bytes) else str(image),
            color_count,
            quality,
        )
        _LOGGER.debug("Extracted %d colors: %s", len(colors), colors)
        return colors
    except Exception as e:
        _LOGGER.error("Failed to extract color palette from %s: %s", _describe(image), e)
        return []
```

- [ ] **Step 4: Run tests**

Run: `$TEST tests/ -q`
Expected: all pass, including `TestExtractFromBytes`.

- [ ] **Step 5: Commit**

```bash
git add custom_components/chameleon/color_extractor.py tests/test_color_extractor.py
git commit -m "feat: extract colors from in-memory image bytes"
```

---

### Task 2: `NowPlayingTracker`

**Files:**

- Create: `custom_components/chameleon/now_playing.py`
- Modify: `tests/conftest.py` (mock media_player module and two state constants)
- Test: `tests/test_now_playing.py`

**Interfaces:**

- Consumes: nothing from earlier tasks.
- Produces (used by Task 5):

  - `def cover_key(state: State | None) -> str | None`
  - `class NowPlayingTracker`
    - `__init__(self, hass: HomeAssistant, media_player: str, grace: float = DEFAULT_GRACE_SECONDS) -> None`
    - attribute `media_player: str`
    - `is_running -> bool` (property)
    - `start(self, on_cover: Callable[[str], None], on_fallback: Callable[[], None]) -> None` - idempotent: restarts cleanly if already running
    - `stop(self) -> None` - idempotent
    - `current_cover_key(self) -> str | None`
    - `async async_fetch_cover(self) -> bytes | None`
  - constants `DEFAULT_GRACE_SECONDS = 30.0`, `COVER_FETCH_TIMEOUT = 10.0`

- [ ] **Step 1: Extend the HA mocks**

In `tests/conftest.py`, inside `_setup_homeassistant_mocks()`:

After `mock_ha_const.ATTR_ENTITY_ID = "entity_id"` add:

```python
    mock_ha_const.STATE_PLAYING = "playing"
    mock_ha_const.STATE_PAUSED = "paused"
```

Next to the other `mock_ha_components_* = MagicMock()` lines add:

```python
    mock_ha_components_media_player = MagicMock()
    mock_ha_components_media_player.DOMAIN = "media_player"
```

Next to the other `sys.modules[...]` assignments add:

```python
    sys.modules["homeassistant.components.media_player"] = mock_ha_components_media_player
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_now_playing.py`:

```python
"""Tests for the Now Playing media player tracker."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import State

from custom_components.chameleon import now_playing
from custom_components.chameleon.now_playing import NowPlayingTracker, cover_key

PLAYER = "media_player.lounge"


def _player(state: str, picture: str | None = None, **attrs) -> State:
    attributes = dict(attrs)
    if picture is not None:
        attributes["entity_picture"] = picture
    return State(PLAYER, state, attributes)


def _proxy(cache: str, token: str = "t1") -> str:
    return f"/api/media_player_proxy/{PLAYER}?token={token}&cache={cache}"


def _event(old: State | None, new: State | None) -> MagicMock:
    event = MagicMock()
    event.data = {"entity_id": PLAYER, "old_state": old, "new_state": new}
    return event


class TestCoverKey:
    def test_proxy_url_uses_cache_param(self):
        assert cover_key(_player("playing", _proxy("abc"))) == "abc"

    def test_token_rotation_keeps_key(self):
        assert cover_key(_player("playing", _proxy("abc", "t1"))) == cover_key(_player("playing", _proxy("abc", "t2")))

    def test_remote_url_without_cache_uses_whole_string(self):
        url = "https://art.example/cover.jpg"
        assert cover_key(_player("playing", url)) == url

    def test_paused_counts(self):
        assert cover_key(_player("paused", _proxy("abc"))) == "abc"

    @pytest.mark.parametrize("state", ["idle", "off", "standby", "unavailable"])
    def test_inactive_states_have_no_key(self, state: str):
        assert cover_key(_player(state, _proxy("abc"))) is None

    def test_no_picture(self):
        assert cover_key(_player("playing")) is None

    def test_missing_entity(self):
        assert cover_key(None) is None


@pytest.fixture
def tracking(hass: MagicMock):
    """Start a tracker with captured HA hooks; yields (tracker, hooks, on_cover, on_fallback)."""
    hooks: dict = {"unsub": MagicMock(), "cancel_timer": MagicMock()}

    def fake_track(_hass, entity_ids, handler):
        hooks["entity_ids"] = entity_ids
        hooks["handler"] = handler
        return hooks["unsub"]

    def fake_call_later(_hass, delay, action):
        hooks["delay"] = delay
        hooks["timer_action"] = action
        return hooks["cancel_timer"]

    hass.states.get.return_value = _player("playing", _proxy("first"))
    with (
        patch.object(now_playing, "async_track_state_change_event", side_effect=fake_track),
        patch.object(now_playing, "async_call_later", side_effect=fake_call_later) as call_later,
    ):
        hooks["call_later"] = call_later
        tracker = NowPlayingTracker(hass, PLAYER)
        on_cover, on_fallback = MagicMock(), MagicMock()
        tracker.start(on_cover, on_fallback)
        yield tracker, hooks, on_cover, on_fallback


class TestTracker:
    def test_start_subscribes_to_the_player(self, tracking):
        tracker, hooks, _, _ = tracking
        assert hooks["entity_ids"] == [PLAYER]
        assert tracker.is_running is True

    def test_new_cover_fires_on_cover(self, tracking):
        _, hooks, on_cover, _ = tracking
        hooks["handler"](_event(_player("playing", _proxy("first")), _player("playing", _proxy("second"))))
        on_cover.assert_called_once_with("second")

    def test_token_rotation_is_not_a_new_cover(self, tracking):
        _, hooks, on_cover, _ = tracking
        hooks["handler"](_event(None, _player("playing", _proxy("first", token="rotated"))))
        on_cover.assert_not_called()

    def test_pause_holds(self, tracking):
        _, hooks, on_cover, on_fallback = tracking
        hooks["handler"](_event(None, _player("paused", _proxy("first"))))
        on_cover.assert_not_called()
        hooks["call_later"].assert_not_called()

    def test_playing_without_artwork_holds(self, tracking):
        """Review focus 4: radio/line-in mid-session keeps the current colours."""
        _, hooks, on_cover, on_fallback = tracking
        hooks["handler"](_event(None, _player("playing")))
        on_cover.assert_not_called()
        hooks["call_later"].assert_not_called()
        on_fallback.assert_not_called()

    @pytest.mark.parametrize("state", ["idle", "off", "standby", "unavailable"])
    def test_inactive_starts_grace_timer(self, tracking, state: str):
        _, hooks, _, on_fallback = tracking
        hooks["handler"](_event(None, _player(state)))
        assert hooks["delay"] == 30.0
        on_fallback.assert_not_called()

    def test_grace_timer_started_once(self, tracking):
        _, hooks, _, _ = tracking
        hooks["handler"](_event(None, _player("idle")))
        hooks["handler"](_event(None, _player("off")))
        assert hooks["call_later"].call_count == 1

    def test_resume_within_grace_cancels(self, tracking):
        _, hooks, _, on_fallback = tracking
        hooks["handler"](_event(None, _player("idle")))
        hooks["handler"](_event(None, _player("playing", _proxy("first"))))
        hooks["cancel_timer"].assert_called_once()
        on_fallback.assert_not_called()

    def test_grace_expiry_stops_and_falls_back(self, tracking):
        tracker, hooks, _, on_fallback = tracking
        hooks["handler"](_event(None, _player("idle")))
        hooks["timer_action"](None)
        on_fallback.assert_called_once()
        hooks["unsub"].assert_called_once()
        assert tracker.is_running is False

    def test_entity_removed_starts_grace(self, tracking):
        _, hooks, _, _ = tracking
        hooks["handler"](_event(_player("playing", _proxy("first")), None))
        assert hooks["delay"] == 30.0

    def test_stop_cancels_listener_and_timer(self, tracking):
        tracker, hooks, _, _ = tracking
        hooks["handler"](_event(None, _player("idle")))
        tracker.stop()
        hooks["unsub"].assert_called_once()
        hooks["cancel_timer"].assert_called_once()
        tracker.stop()  # idempotent
        hooks["unsub"].assert_called_once()

    def test_restart_does_not_double_subscribe(self, tracking):
        tracker, hooks, on_cover, on_fallback = tracking
        tracker.start(on_cover, on_fallback)
        hooks["unsub"].assert_called_once()  # old subscription released first


class TestFetchCover:
    @pytest.mark.asyncio
    async def test_returns_bytes_from_entity(self, hass: MagicMock):
        entity = MagicMock()
        entity.async_get_media_image = AsyncMock(return_value=(b"img", "image/jpeg"))
        component = MagicMock()
        component.get_entity.return_value = entity
        hass.data = {"media_player": component}

        assert await NowPlayingTracker(hass, PLAYER).async_fetch_cover() == b"img"
        component.get_entity.assert_called_once_with(PLAYER)

    @pytest.mark.asyncio
    async def test_missing_entity_returns_none(self, hass: MagicMock):
        component = MagicMock()
        component.get_entity.return_value = None
        hass.data = {"media_player": component}

        assert await NowPlayingTracker(hass, PLAYER).async_fetch_cover() is None

    @pytest.mark.asyncio
    async def test_no_component_returns_none(self, hass: MagicMock):
        hass.data = {}
        assert await NowPlayingTracker(hass, PLAYER).async_fetch_cover() is None

    @pytest.mark.asyncio
    async def test_empty_image_returns_none(self, hass: MagicMock):
        entity = MagicMock()
        entity.async_get_media_image = AsyncMock(return_value=(None, None))
        component = MagicMock()
        component.get_entity.return_value = entity
        hass.data = {"media_player": component}

        assert await NowPlayingTracker(hass, PLAYER).async_fetch_cover() is None

    @pytest.mark.asyncio
    async def test_error_returns_none(self, hass: MagicMock):
        entity = MagicMock()
        entity.async_get_media_image = AsyncMock(side_effect=RuntimeError("boom"))
        component = MagicMock()
        component.get_entity.return_value = entity
        hass.data = {"media_player": component}

        assert await NowPlayingTracker(hass, PLAYER).async_fetch_cover() is None

    @pytest.mark.asyncio
    async def test_timeout_returns_none(self, hass: MagicMock):
        async def slow():
            await asyncio.sleep(1)
            return (b"late", "image/jpeg")

        entity = MagicMock()
        entity.async_get_media_image = slow
        component = MagicMock()
        component.get_entity.return_value = entity
        hass.data = {"media_player": component}

        with patch.object(now_playing, "COVER_FETCH_TIMEOUT", 0.01):
            assert await NowPlayingTracker(hass, PLAYER).async_fetch_cover() is None
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `$TEST tests/test_now_playing.py -q`
Expected: collection error - `cannot import name 'now_playing'`.

- [ ] **Step 4: Implement**

Create `custom_components/chameleon/now_playing.py`:

```python
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
```

- [ ] **Step 5: Run tests**

Run: `$TEST tests/ -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add custom_components/chameleon/now_playing.py tests/conftest.py tests/test_now_playing.py
git commit -m "feat: add NowPlayingTracker for media player cover changes"
```

---

### Task 3: Media player field in the config flow

**Files:**

- Modify: `custom_components/chameleon/const.py`
- Modify: `custom_components/chameleon/config_flow.py`
- Modify: `custom_components/chameleon/strings.json`, `custom_components/chameleon/translations/en.json`
- Test: `tests/test_config_flow.py`

**Interfaces:**

- Consumes: nothing.
- Produces: `CONF_MEDIA_PLAYER: Final = "media_player"` in `const.py`. `entry.data[CONF_MEDIA_PLAYER]` is a `str` entity ID, `None`, or absent; Task 5 reads it with `entry.data.get(CONF_MEDIA_PLAYER)`.

- [ ] **Step 1: Write / update the tests**

In `tests/test_config_flow.py`:

Add `CONF_MEDIA_PLAYER` to the `from custom_components.chameleon.const import (...)` block.

In `TestChameleonConfigFlow`, add:

```python
    @pytest.mark.asyncio
    async def test_create_entry_with_media_player(self, hass: MagicMock):
        from custom_components.chameleon.config_flow import ChameleonConfigFlow

        flow = ChameleonConfigFlow()
        _setup_config_flow(flow, hass)

        with patch(TITLE_PATCH, return_value="Lounge"):
            result = await flow.async_step_user(
                user_input={
                    CONF_LIGHT_ENTITIES: ["light.one"],
                    CONF_TRANSITION: 5,
                    CONF_MEDIA_PLAYER: "media_player.lounge",
                }
            )

        assert result["data"][CONF_MEDIA_PLAYER] == "media_player.lounge"
```

In `TestChameleonReconfigureFlow`, replace the bodies' expectations as follows.

`test_form_prefilled_with_current_lights` - the entry has no player, so the pre-fill carries `None`:

```python
        assert flow.suggested_values == {CONF_LIGHT_ENTITIES: ["light.one", "light.two"], CONF_MEDIA_PLAYER: None}
```

`test_form_prefilled_from_legacy_single_light`:

```python
        assert flow.suggested_values == {CONF_LIGHT_ENTITIES: ["light.old"], CONF_MEDIA_PLAYER: None}
```

`test_membership_change_updates_entry_in_place` - `data_updates` now also carries the (absent → `None`) player:

```python
        assert result["updates"] == {
            "unique_id": "light.one_light.three",
            "title": "Office",
            "data_updates": {CONF_LIGHT_ENTITIES: ["light.three", "light.one"], CONF_MEDIA_PLAYER: None},
        }
```

Add:

```python
    @pytest.mark.asyncio
    async def test_prefills_existing_media_player(self, hass: MagicMock):
        from custom_components.chameleon.config_flow import ChameleonConfigFlow

        entry = _mock_entry("abc", {CONF_LIGHT_ENTITIES: ["light.one"], CONF_MEDIA_PLAYER: "media_player.lounge"})
        flow = ChameleonConfigFlow()
        _setup_reconfigure_flow(flow, hass, entry)

        await flow.async_step_reconfigure()

        assert flow.suggested_values[CONF_MEDIA_PLAYER] == "media_player.lounge"

    @pytest.mark.asyncio
    async def test_set_and_clear_media_player(self, hass: MagicMock):
        from custom_components.chameleon.config_flow import ChameleonConfigFlow

        entry = _mock_entry("abc", {CONF_LIGHT_ENTITIES: ["light.one"], CONF_MEDIA_PLAYER: "media_player.lounge"}, "light.one")
        flow = ChameleonConfigFlow()
        _setup_reconfigure_flow(flow, hass, entry)

        with patch(TITLE_PATCH, return_value="One"):
            set_result = await flow.async_step_reconfigure(
                user_input={CONF_LIGHT_ENTITIES: ["light.one"], CONF_MEDIA_PLAYER: "media_player.kitchen"}
            )
            # A cleared optional selector is simply absent from user_input
            clear_result = await flow.async_step_reconfigure(user_input={CONF_LIGHT_ENTITIES: ["light.one"]})

        assert set_result["updates"]["data_updates"][CONF_MEDIA_PLAYER] == "media_player.kitchen"
        assert clear_result["updates"]["data_updates"][CONF_MEDIA_PLAYER] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `$TEST tests/test_config_flow.py -q`
Expected: ImportError on `CONF_MEDIA_PLAYER`.

- [ ] **Step 3: Implement**

`custom_components/chameleon/const.py` - after `CONF_TRANSITION`:

```python
CONF_MEDIA_PLAYER: Final = "media_player"  # Optional: player whose album art drives "Now Playing"
```

`custom_components/chameleon/config_flow.py`:

Add `CONF_MEDIA_PLAYER` to the `.const` import. In `async_step_user`'s `data_schema`, after the `CONF_TRANSITION` entry, add:

```python
                vol.Optional(CONF_MEDIA_PLAYER): EntitySelector(EntitySelectorConfig(domain="media_player")),
```

In `async_step_reconfigure`, change the success call's `data_updates` to:

```python
                    data_updates={
                        CONF_LIGHT_ENTITIES: light_entities,
                        # A cleared optional selector is absent from user_input; store None
                        CONF_MEDIA_PLAYER: user_input.get(CONF_MEDIA_PLAYER),
                    },
```

change the pre-fill to:

```python
        suggested = (
            user_input
            if user_input is not None
            else {CONF_LIGHT_ENTITIES: current_lights, CONF_MEDIA_PLAYER: entry.data.get(CONF_MEDIA_PLAYER)}
        )
```

and add to the reconfigure `data_schema`, after the lights selector:

```python
                vol.Optional(CONF_MEDIA_PLAYER): EntitySelector(EntitySelectorConfig(domain="media_player")),
```

Strings - in **both** `strings.json` and `translations/en.json` (identical files), add to `config.step.user.data` and `config.step.reconfigure.data`:

```json
"media_player": "Media Player"
```

and to both steps' `data_description`:

```json
"media_player": "Optional. Adds a \"Now Playing\" effect that colors these lights from this player's album art. Pick the player in the same room."
```

- [ ] **Step 4: Run tests**

Run: `$TEST tests/ -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add custom_components/chameleon/const.py custom_components/chameleon/config_flow.py custom_components/chameleon/strings.json custom_components/chameleon/translations/en.json tests/test_config_flow.py
git commit -m "feat: optional media player in config and reconfigure flows"
```

---

### Task 4: Palette-based apply paths (refactor + extraction-failure fix)

Behaviour for scenes is unchanged except one bug fix: today a failed extraction returns an empty `ApplyColorsResult`, `all([])` is `True`, and the scene is recorded as **successful**. After this task it sets `last_error` and leaves `effect` unchanged.

**Files:**

- Modify: `custom_components/chameleon/light.py` (`_apply_effect`, `_apply_colors_static`, `_apply_colors_animated`; add `_uses_animation`, `_extract_palette`, `_apply_palette`, `_record_effect_result`)
- Test: `tests/test_light_palette.py`

**Interfaces:**

- Consumes: `extract_color_palette` / `extract_dominant_color` accepting `Path | bytes` (Task 1).
- Produces (used by Task 5):

  - `def _uses_animation(self) -> bool`
  - `async def _extract_palette(self, source: Path | bytes, animated: bool) -> list[RGBColor]`
  - `async def _apply_palette(self, colors: list[RGBColor], animated: bool) -> ApplyColorsResult` - stops any running animation first
  - `def _record_effect_result(self, effect: str, label: str, result: ApplyColorsResult, animated: bool) -> None` - `effect` is stored in `_effect`/`_last_effect`; `label` is for logs

- [ ] **Step 1: Write the failing tests**

Create `tests/test_light_palette.py`:

```python
"""Regression tests for the palette-based apply paths in light.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.chameleon import light as light_module
from custom_components.chameleon.light_controller import ApplyColorsResult, LightResult

PALETTE = [(255, 0, 0), (0, 255, 0), (0, 0, 255)]


def _make_light(hass: MagicMock, lights: list[str]):
    entry = MagicMock()
    entry.entry_id = "entry"
    hass.data = {}
    with patch.object(light_module, "get_entity_base_name", return_value="test"):
        entity = light_module.ChameleonLight(hass, entry, lights, 0)
    entity.async_write_ha_state = MagicMock()
    entity._light_controller = MagicMock()
    entity._light_controller.apply_colors_to_lights = AsyncMock(
        side_effect=lambda colors, **_: ApplyColorsResult([LightResult(e, True, c) for e, c in colors.items()])
    )
    entity._find_image_for_scene = AsyncMock(return_value=Path("/config/www/chameleon/sunset.jpg"))
    return entity


class TestExtractPalette:
    @pytest.mark.asyncio
    async def test_static_single_light_uses_dominant_color(self, hass: MagicMock):
        entity = _make_light(hass, ["light.one"])
        with patch.object(light_module, "extract_dominant_color", AsyncMock(return_value=(1, 2, 3))) as dominant:
            assert await entity._extract_palette(b"img", animated=False) == [(1, 2, 3)]
        dominant.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_static_multi_light_requests_at_least_one_color_per_light(self, hass: MagicMock):
        lights = [f"light.l{i}" for i in range(8)]
        entity = _make_light(hass, lights)
        with patch.object(light_module, "extract_color_palette", AsyncMock(return_value=PALETTE)) as palette:
            await entity._extract_palette(b"img", animated=False)
        assert palette.await_args.kwargs["color_count"] == 8

    @pytest.mark.asyncio
    async def test_animated_uses_default_count(self, hass: MagicMock):
        from custom_components.chameleon.const import DEFAULT_COLOR_COUNT

        entity = _make_light(hass, ["light.one", "light.two"])
        with patch.object(light_module, "extract_color_palette", AsyncMock(return_value=PALETTE)) as palette:
            await entity._extract_palette(b"img", animated=True)
        assert palette.await_args.kwargs["color_count"] == DEFAULT_COLOR_COUNT


class TestSceneApply:
    @pytest.mark.asyncio
    async def test_static_scene_maps_palette_by_light_index(self, hass: MagicMock):
        entity = _make_light(hass, ["light.one", "light.two"])
        with patch.object(light_module, "extract_color_palette", AsyncMock(return_value=PALETTE)):
            await entity._apply_effect("Sunset")

        sent = entity._light_controller.apply_colors_to_lights.await_args.args[0]
        assert sent == {"light.one": PALETTE[0], "light.two": PALETTE[1]}
        assert entity._effect == "Sunset"
        assert entity._last_effect == "Sunset"
        assert entity._extracted_palette == PALETTE

    @pytest.mark.asyncio
    async def test_extraction_failure_is_an_error_not_a_success(self, hass: MagicMock):
        entity = _make_light(hass, ["light.one", "light.two"])
        entity._effect = "Previous"
        with patch.object(light_module, "extract_color_palette", AsyncMock(return_value=[])):
            await entity._apply_effect("Sunset")

        assert entity._effect == "Previous"
        assert entity._last_error == "Failed to extract colors from scene: Sunset"
        entity._light_controller.apply_colors_to_lights.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_animated_scene_starts_manager_with_all_lights(self, hass: MagicMock):
        entity = _make_light(hass, ["light.one", "light.two"])
        manager = MagicMock()
        manager.start = AsyncMock()
        manager.stop = AsyncMock()
        hass.data = {"chameleon": {"animation_manager": manager, "entry": {"transition": 2.0}}}
        entity._light_controller.check_light_availability = MagicMock(return_value=(True, None, None))
        with patch.object(light_module, "extract_color_palette", AsyncMock(return_value=PALETTE)):
            await entity._apply_effect("Sunset")

        manager.stop.assert_awaited()
        assert manager.start.await_args.args[1] == ["light.one", "light.two"]
        assert entity._effect == "Sunset"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `$TEST tests/test_light_palette.py -q`
Expected: FAIL - `ChameleonLight` has no `_extract_palette`; `test_extraction_failure_is_an_error_not_a_success` fails because the effect is recorded as `"Sunset"`.

- [ ] **Step 3: Implement**

In `custom_components/chameleon/light.py`:

Replace the block in `_apply_effect` from `# Stop any running animation before re-applying.` to the end of the method with:

```python
        animated = self._uses_animation()
        colors = await self._extract_palette(image_path, animated)
        if not colors:
            self._last_error = f"Failed to extract colors from scene: {effect}"
            _LOGGER.error(self._last_error)
            return

        result = await self._apply_palette(colors, animated)
        self._record_effect_result(effect, effect, result, animated)
```

Add these methods directly after `_apply_effect`:

```python
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
```

Replace `_apply_colors_static` entirely with:

```python
    async def _apply_colors_static(self, colors: list[RGBColor], brightness: int) -> ApplyColorsResult:
        """Apply a palette statically: palette color by light index, no loop."""
        self._extracted_palette = colors
        light_colors = {entity: colors[i % len(colors)] for i, entity in enumerate(self._light_entities)}
        return await self._light_controller.apply_colors_to_lights(light_colors, brightness=brightness)
```

In `_apply_colors_animated`, change the signature to `async def _apply_colors_animated(self, colors: list[RGBColor], brightness: int) -> ApplyColorsResult:`, update its docstring to `"""Start an animation across the configured lights from a palette."""`, and delete the extraction block (from `colors = await extract_color_palette(` through `return ApplyColorsResult()` after the "Failed to extract color palette" log). The method then starts at `manager = self._get_animation_manager()` / transition / style, followed by `self._extracted_palette = colors` and the existing gradient + pre-flight + `manager.start` code unchanged.

- [ ] **Step 4: Run tests**

Run: `$TEST tests/ -q`
Expected: all pass (including `tests/test_availability.py`, untouched by this task).

- [ ] **Step 5: Commit**

```bash
git add custom_components/chameleon/light.py tests/test_light_palette.py
git commit -m "refactor: apply paths take a palette instead of an image path

Extraction moves up into the callers so album art can share the static
and animated apply paths. Also fixes a failed extraction being recorded
as a successful scene change (empty result made all_succeeded true)."
```

---

### Task 5: Now Playing mode on the Chameleon light

**Files:**

- Modify: `custom_components/chameleon/const.py`
- Modify: `custom_components/chameleon/helpers.py` (rename `_get_light_friendly_name` → `get_friendly_name`)
- Modify: `custom_components/chameleon/light.py`
- Modify: `tests/test_config_flow.py` (follow the rename)
- Test: `tests/test_light_now_playing.py`

**Interfaces:**

- Consumes: `CONF_MEDIA_PLAYER` (Task 3); `NowPlayingTracker` with `media_player`, `start(on_cover, on_fallback)`, `stop()`, `current_cover_key()`, `async_fetch_cover()` (Task 2); `_uses_animation`, `_extract_palette`, `_apply_palette`, `_record_effect_result` (Task 4).
- Produces:

  - `NOW_PLAYING_EFFECT: Final = "__now_playing__"`, `NOW_PLAYING_PREFIX: Final = "Now Playing"` in `const.py`
  - `get_friendly_name(hass, entity_id) -> str` in `helpers.py`
  - `ChameleonLight.__init__(self, hass, entry, light_entities, initial_transition, media_player: str | None = None)`
  - attributes `media_player` and `now_playing` in `extra_state_attributes`

- [ ] **Step 1: Rename the friendly-name helper**

In `custom_components/chameleon/helpers.py`, rename `def _get_light_friendly_name(` to `def get_friendly_name(` and change its docstring's first line to `"""Get a friendly name for an entity (lights, media players).`; update its two call sites in the same file. In `tests/test_config_flow.py`, replace every `_get_light_friendly_name` with `get_friendly_name`.

Run: `grep -rn "_get_light_friendly_name" custom_components tests`
Expected: no output.

- [ ] **Step 2: Write the failing tests**

Create `tests/test_light_now_playing.py`:

```python
"""Tests for the Now Playing effect on the Chameleon light."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import State

from custom_components.chameleon import light as light_module
from custom_components.chameleon.const import NOW_PLAYING_EFFECT
from custom_components.chameleon.light_controller import ApplyColorsResult, LightResult

PLAYER = "media_player.lounge"
PALETTE = [(255, 0, 0), (0, 255, 0), (0, 0, 255)]
NP_NAME = "Now Playing - Lounge"


def _ok(_colors, _animated):
    return ApplyColorsResult([LightResult("light.one", True, PALETTE[0])])


def _make_light(hass: MagicMock, media_player: str | None = PLAYER, player_state: State | None = None):
    """A ChameleonLight with a fake tracker and patched extraction/apply."""
    states = {PLAYER: player_state or State(PLAYER, "playing", {"friendly_name": "Lounge"})}
    hass.states.get.side_effect = lambda eid: states.get(eid)
    hass.data = {}
    hass.services.async_call = AsyncMock()
    entry = MagicMock()
    entry.entry_id = "entry"
    with patch.object(light_module, "get_entity_base_name", return_value="test"):
        entity = light_module.ChameleonLight(hass, entry, ["light.one"], 0, media_player=media_player)
    entity.async_write_ha_state = MagicMock()

    tracker = MagicMock()
    tracker.media_player = PLAYER
    tracker.current_cover_key.return_value = "cover-1"
    tracker.async_fetch_cover = AsyncMock(return_value=b"img")
    if media_player is not None:
        entity._now_playing = tracker

    entity._extract_palette = AsyncMock(return_value=PALETTE)
    entity._apply_palette = AsyncMock(side_effect=_ok)
    entity._find_image_for_scene = AsyncMock(return_value=Path("/config/www/chameleon/sunset.jpg"))
    entity._cached_options = ["Sunset"]
    return entity, tracker, states


class TestEffectNaming:
    def test_listed_after_random(self, hass: MagicMock):
        entity, _, _ = _make_light(hass)
        assert entity.effect_list == ["Random", NP_NAME, "Sunset"]

    def test_absent_without_player(self, hass: MagicMock):
        entity, _, _ = _make_light(hass, media_player=None)
        assert entity.effect_list == ["Random", "Sunset"]

    def test_name_falls_back_to_object_id(self, hass: MagicMock):
        entity, _, states = _make_light(hass, player_state=State(PLAYER, "playing", {"friendly_name": "Lounge Speaker"}))
        assert entity.effect_list[1] == "Now Playing - Lounge Speaker"
        states.clear()  # player not loaded yet (startup ordering)
        assert entity.effect_list[1] == "Now Playing - Lounge"

    def test_effect_shows_display_name(self, hass: MagicMock):
        entity, _, _ = _make_light(hass)
        entity._effect = NOW_PLAYING_EFFECT
        assert entity.effect == NP_NAME

    def test_rename_follows_and_marker_survives(self, hass: MagicMock):
        entity, _, states = _make_light(hass)
        entity._effect = NOW_PLAYING_EFFECT
        entity._last_effect = NOW_PLAYING_EFFECT
        states[PLAYER] = State(PLAYER, "playing", {"friendly_name": "Living Room"})
        assert entity.effect == "Now Playing - Living Room"
        assert entity._last_effect == NOW_PLAYING_EFFECT


class TestEnter:
    @pytest.mark.asyncio
    async def test_enter_by_display_name_applies_cover(self, hass: MagicMock):
        entity, tracker, _ = _make_light(hass)
        await entity._apply_effect(NP_NAME)

        tracker.start.assert_called_once()
        entity._extract_palette.assert_awaited_once_with(b"img", False)
        assert entity._effect == NOW_PLAYING_EFFECT
        assert entity._last_effect == NOW_PLAYING_EFFECT
        assert entity._latest_cover_key == "cover-1"

    @pytest.mark.asyncio
    async def test_enter_by_marker(self, hass: MagicMock):
        """Bare turn_on restores _last_effect, which stores the marker."""
        entity, tracker, _ = _make_light(hass)
        await entity._apply_effect(NOW_PLAYING_EFFECT)
        tracker.start.assert_called_once()

    @pytest.mark.asyncio
    async def test_nothing_playing_falls_back_with_error(self, hass: MagicMock):
        entity, tracker, _ = _make_light(hass)
        entity._effect = "Sunset"
        tracker.current_cover_key.return_value = None

        await entity._apply_effect(NP_NAME)

        tracker.start.assert_not_called()
        assert entity._last_error == f"Nothing playing on {PLAYER}"
        assert entity._effect == "Sunset"

    @pytest.mark.asyncio
    async def test_missing_player_error(self, hass: MagicMock):
        entity, tracker, states = _make_light(hass)
        entity._effect = "Sunset"
        tracker.current_cover_key.return_value = None
        states.clear()

        await entity._apply_effect(NP_NAME)

        assert entity._last_error == f"{PLAYER} not found"

    @pytest.mark.asyncio
    async def test_fetch_failure_keeps_mode(self, hass: MagicMock):
        entity, tracker, _ = _make_light(hass)
        tracker.async_fetch_cover.return_value = None

        await entity._apply_effect(NP_NAME)

        assert entity._effect == NOW_PLAYING_EFFECT
        assert entity._last_error == f"Couldn't fetch cover art from {PLAYER}"
        entity._apply_palette.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unreadable_cover_keeps_mode(self, hass: MagicMock):
        entity, _, _ = _make_light(hass)
        entity._extract_palette.return_value = []

        await entity._apply_effect(NP_NAME)

        assert entity._effect == NOW_PLAYING_EFFECT
        assert entity._last_error == f"Couldn't read cover art from {PLAYER}"

    @pytest.mark.asyncio
    async def test_display_name_without_player_is_just_an_unknown_scene(self, hass: MagicMock):
        """Review focus 5: stale automation after the player was removed."""
        entity, _, _ = _make_light(hass, media_player=None)
        entity._find_image_for_scene = AsyncMock(return_value=None)

        await entity._apply_effect(NP_NAME)

        assert entity._last_error == f"Image not found for scene: {NP_NAME}"


class TestFallbackTarget:
    @pytest.mark.asyncio
    async def test_returns_to_scene_active_before(self, hass: MagicMock):
        entity, _, _ = _make_light(hass)
        entity._is_on = True
        entity._effect = "Sunset"
        await entity._apply_effect(NP_NAME)

        await entity._async_handle_now_playing_ended()

        assert entity._effect == "Sunset"

    @pytest.mark.asyncio
    async def test_entering_from_off_uses_last_effect(self, hass: MagicMock):
        entity, _, _ = _make_light(hass)
        entity._effect = None
        entity._last_effect = "Sunset"
        await entity._apply_effect(NP_NAME)
        assert entity._fallback_effect == "Sunset"

    @pytest.mark.asyncio
    async def test_reentry_never_makes_now_playing_its_own_fallback(self, hass: MagicMock):
        """Review focus 1: transition slider crossing zero re-applies the marker."""
        entity, tracker, _ = _make_light(hass)
        entity._is_on = True
        entity._effect = "Sunset"
        await entity._apply_effect(NP_NAME)

        await entity.async_reapply_current_scene()

        assert entity._fallback_effect == "Sunset"
        assert tracker.start.call_count == 2
        assert entity._effect == NOW_PLAYING_EFFECT

    @pytest.mark.asyncio
    async def test_no_previous_scene_falls_back_to_random(self, hass: MagicMock):
        entity, _, _ = _make_light(hass)
        entity._is_on = True
        await entity._apply_effect(NP_NAME)

        await entity._async_handle_now_playing_ended()

        assert entity._effect == "Sunset"  # Random picked the only scene

    @pytest.mark.asyncio
    async def test_fallback_scene_deleted(self, hass: MagicMock):
        """Review focus 3."""
        entity, tracker, _ = _make_light(hass)
        entity._is_on = True
        entity._effect = "Sunset"
        await entity._apply_effect(NP_NAME)
        entity._find_image_for_scene = AsyncMock(return_value=None)

        await entity._async_handle_now_playing_ended()

        assert entity._effect is None
        assert entity._last_error == "Image not found for scene: Sunset"
        tracker.stop.assert_called()


class TestCallbacks:
    @pytest.mark.asyncio
    async def test_cover_change_reapplies(self, hass: MagicMock):
        entity, tracker, _ = _make_light(hass)
        entity._is_on = True
        await entity._apply_effect(NP_NAME)
        entity._latest_cover_key = "cover-2"

        await entity._async_handle_cover("cover-2")

        assert tracker.async_fetch_cover.await_count == 2
        entity.async_write_ha_state.assert_called()

    @pytest.mark.asyncio
    async def test_superseded_cover_dropped(self, hass: MagicMock):
        entity, tracker, _ = _make_light(hass)
        entity._is_on = True
        await entity._apply_effect(NP_NAME)
        entity._latest_cover_key = "cover-3"

        await entity._async_handle_cover("cover-2")

        assert tracker.async_fetch_cover.await_count == 1

    @pytest.mark.asyncio
    async def test_cover_after_switching_effect_dropped(self, hass: MagicMock):
        entity, tracker, _ = _make_light(hass)
        entity._is_on = True
        entity._effect = "Sunset"
        entity._latest_cover_key = "cover-2"

        await entity._async_handle_cover("cover-2")

        tracker.async_fetch_cover.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_ended_after_switching_effect_dropped(self, hass: MagicMock):
        entity, _, _ = _make_light(hass)
        entity._is_on = True
        entity._effect = "Sunset"
        entity._find_image_for_scene.reset_mock()

        await entity._async_handle_now_playing_ended()

        entity._find_image_for_scene.assert_not_awaited()

    def test_on_cover_changed_schedules_and_records_key(self, hass: MagicMock):
        entity, _, _ = _make_light(hass)
        entity._on_cover_changed("cover-9")
        assert entity._latest_cover_key == "cover-9"
        entity._entry.async_create_task.assert_called_once()
        entity._entry.async_create_task.call_args.args[1].close()


class TestLeaving:
    @pytest.mark.asyncio
    async def test_turn_off_stops_tracker(self, hass: MagicMock):
        entity, tracker, _ = _make_light(hass)
        await entity._apply_effect(NP_NAME)
        await entity._do_turn_off()
        tracker.stop.assert_called()

    @pytest.mark.asyncio
    async def test_other_scene_stops_tracker(self, hass: MagicMock):
        entity, tracker, _ = _make_light(hass)
        await entity._apply_effect(NP_NAME)
        tracker.stop.reset_mock()
        await entity._apply_effect("Sunset")
        tracker.stop.assert_called()
        assert entity._effect == "Sunset"

    @pytest.mark.asyncio
    async def test_manual_color_stops_tracker(self, hass: MagicMock):
        entity, tracker, _ = _make_light(hass)
        entity._light_controller = MagicMock()
        entity._light_controller.apply_colors_to_lights = AsyncMock(
            return_value=ApplyColorsResult([LightResult("light.one", True, (1, 2, 3))])
        )
        await entity._apply_effect(NP_NAME)
        tracker.stop.reset_mock()
        await entity._apply_manual_color((1, 2, 3))
        tracker.stop.assert_called()


class TestPlayerStateUpdates:
    def _event(self, old: State | None, new: State | None) -> MagicMock:
        event = MagicMock()
        event.data = {"entity_id": PLAYER, "old_state": old, "new_state": new}
        return event

    def test_rename_writes_state(self, hass: MagicMock):
        """Review focus 2."""
        entity, _, _ = _make_light(hass)
        entity._async_media_player_changed(
            self._event(State(PLAYER, "idle", {"friendly_name": "Lounge"}), State(PLAYER, "idle", {"friendly_name": "Den"}))
        )
        entity.async_write_ha_state.assert_called_once()

    def test_track_change_in_now_playing_writes_state(self, hass: MagicMock):
        entity, _, _ = _make_light(hass)
        entity._effect = NOW_PLAYING_EFFECT
        old = State(PLAYER, "playing", {"friendly_name": "Lounge", "media_title": "A"})
        new = State(PLAYER, "playing", {"friendly_name": "Lounge", "media_title": "B"})
        entity._async_media_player_changed(self._event(old, new))
        entity.async_write_ha_state.assert_called_once()

    def test_unrelated_change_ignored(self, hass: MagicMock):
        entity, _, _ = _make_light(hass)
        old = State(PLAYER, "playing", {"friendly_name": "Lounge", "media_title": "A", "volume_level": 0.2})
        new = State(PLAYER, "playing", {"friendly_name": "Lounge", "media_title": "A", "volume_level": 0.3})
        entity._async_media_player_changed(self._event(old, new))
        entity.async_write_ha_state.assert_not_called()


class TestAttributes:
    def test_media_player_and_now_playing(self, hass: MagicMock):
        player = State(PLAYER, "playing", {"friendly_name": "Lounge", "media_artist": "Bowie", "media_title": "Heroes"})
        entity, _, _ = _make_light(hass, player_state=player)
        entity._effect = NOW_PLAYING_EFFECT
        attrs = entity.extra_state_attributes
        assert attrs["media_player"] == PLAYER
        assert attrs["now_playing"] == "Bowie - Heroes"

    def test_no_now_playing_outside_mode(self, hass: MagicMock):
        entity, _, _ = _make_light(hass)
        entity._effect = "Sunset"
        assert "now_playing" not in entity.extra_state_attributes

    def test_no_media_player_attr_without_player(self, hass: MagicMock):
        entity, _, _ = _make_light(hass, media_player=None)
        assert "media_player" not in entity.extra_state_attributes
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `$TEST tests/test_light_now_playing.py -q`
Expected: ImportError on `NOW_PLAYING_EFFECT`.

- [ ] **Step 4: Implement - constants**

`custom_components/chameleon/const.py`, after `SCENE_RANDOM`:

```python
NOW_PLAYING_EFFECT: Final = "__now_playing__"  # Internal marker; display name is built from the player
NOW_PLAYING_PREFIX: Final = "Now Playing"  # Display: "Now Playing - <player friendly name>"
```

- [ ] **Step 5: Implement - light.py wiring**

In `custom_components/chameleon/light.py`:

Imports: add `CONF_MEDIA_PLAYER`, `NOW_PLAYING_EFFECT`, `NOW_PLAYING_PREFIX` to the `.const` import; change `from .helpers import get_chameleon_device_name, get_entity_base_name` to `from .helpers import get_chameleon_device_name, get_entity_base_name, get_friendly_name`; add `from .now_playing import NowPlayingTracker`.

Module docstring: after the `turn_off()` bullet, add:

```
- ``turn_on(effect="Now Playing - <player>")`` → follow the linked media
  player's album art (only when a player is configured). Pause holds; idle/off
  for 30 s falls back to the scene active before.
```

`async_setup_entry`: pass the player:

```python
    async_add_entities(
        [ChameleonLight(hass, entry, light_entities, initial_transition, media_player=entry.data.get(CONF_MEDIA_PLAYER))],
        True,
    )
```

`__init__`: add the parameter `media_player: str | None = None` after `initial_transition`, and after `self._manual_color = ...` add:

```python
        # Now Playing (optional): follow a media player's album art.
        self._media_player = media_player
        self._now_playing = NowPlayingTracker(hass, media_player) if media_player else None
        self._fallback_effect: str | None = None  # scene to return to when playback ends
        self._latest_cover_key: str | None = None  # newest cover seen; older pending work is dropped
```

Helpers section - add after `_static_color_for`:

```python
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
```

`async_added_to_hass`: after the member-light `self.async_on_remove(...)` line add:

```python
        if self._media_player is not None:
            self.async_on_remove(async_track_state_change_event(self.hass, [self._media_player], self._async_media_player_changed))
```

`async_will_remove_from_hass`: after `await super().async_will_remove_from_hass()` add `self._stop_now_playing()`.

`effect` property body:

```python
        if self._effect == NOW_PLAYING_EFFECT:
            return self._now_playing_name()
        return self._effect
```

`effect_list` body (keep the docstring, add one sentence: "Now Playing follows Random when a media player is configured."):

```python
        now_playing = self._now_playing_name()
        return [SCENE_RANDOM, *([now_playing] if now_playing else []), *self._cached_options]
```

`extra_state_attributes`: before `return attrs` add:

```python
        if self._media_player is not None:
            attrs["media_player"] = self._media_player
            if self._effect == NOW_PLAYING_EFFECT:
                player = self.hass.states.get(self._media_player)
                title = player.attributes.get("media_title") if player else None
                artist = player.attributes.get("media_artist") if player else None
                if title:
                    attrs["now_playing"] = f"{artist} - {title}" if artist else title
```

`_do_turn_off`: first line of the body becomes `self._stop_now_playing()`.

`_apply_manual_color`: first line of the body becomes `self._stop_now_playing()`.

`_apply_effect`: directly after the `if effect == SCENE_OFF:` block, insert:

```python
        tracker = self._now_playing
        if tracker is not None and effect in (NOW_PLAYING_EFFECT, self._now_playing_name()):
            await self._enter_now_playing(tracker)
            return

        self._stop_now_playing()
```

- [ ] **Step 6: Implement - Now Playing section**

Add a new section in `light.py` after the `# ── Member light availability` section's last method:

```python
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
            if tracker is None or not self._is_on or self._effect != NOW_PLAYING_EFFECT:
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
            if not self._is_on or self._effect != NOW_PLAYING_EFFECT:
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
```

Note `test_no_previous_scene_falls_back_to_random` / `test_returns_to_scene_active_before` call `_async_handle_now_playing_ended`, which takes the lock: the tests don't hold it, so no deadlock.

- [ ] **Step 7: Run tests**

Run: `$TEST tests/ -q`
Expected: all pass.

Run: `pre-commit run --all-files`
Expected: all hooks pass (ty may want `Event`/`EventStateChangedData` already imported - they are, from the availability work).

- [ ] **Step 8: Commit**

```bash
git add custom_components/chameleon/const.py custom_components/chameleon/helpers.py custom_components/chameleon/light.py tests/test_config_flow.py tests/test_light_now_playing.py
git commit -m "feat: Now Playing effect follows a linked media player's album art"
```

---

### Task 6: Documentation and on-instance verification

**Files:**

- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-10-14-media-player-now-playing-design.md` (fallback-target wording)

**Interfaces:** none.

- [ ] **Step 1: Align the spec's fallback rule with the implementation**

In the spec, replace the `_fallback_effect` bullet under _Leaving Now Playing_ with:

```markdown
- The fallback target lives in `_fallback_effect`. On entering Now Playing the candidate is the
  current `_effect`, or `_last_effect` when the light is off. It is stored only if it is a scene
  or `Random` (not the Now Playing marker); otherwise the previous value is kept. `None` means
  `Random`. This prevents re-entry (bare `turn_on`, transition slider crossing zero) from making
  Now Playing its own fallback.
```

- [ ] **Step 2: README roadmap**

Under `### Media Player Integration`, replace the four bullets with:

```markdown
- [x] **Album art color extraction** - `Now Playing - <player>` effect colors the lights from the linked player's current cover
- [x] **Media player selector** - Optional media player per Chameleon entry (setup or Reconfigure); one room, one player
- [x] **Auto-update on track change** - Repaints when the cover changes (once per album, not per track)
- [x] **Fallback to static scene** - Pause holds; idle/off for 30 s returns to the scene active before
```

- [ ] **Step 3: README usage section**

After the `### Selecting Scenes` section (before `### Example Dashboard Card`), add:

````markdown
### Now Playing (album art)

Link a media player to a Chameleon light during setup, or later via **Settings → Devices &
Services → Chameleon → ⋮ → Reconfigure**. Pick the player in the same room: in a multi-room
setup each Chameleon follows its own room.

The light then lists a **Now Playing - <player name>** effect. Pick it from any light card:

- The lights take their colours from the current album cover, using your transition and
  transition style like any scene.
- A new album repaints the lights; tracks from the same album don't.
- Pausing keeps the colours. When the player goes idle or off for 30 seconds, the light returns
  to the scene it showed before (Random if none).
- Picking another effect, a colour, or turning the light off stops following the player.

```yaml
action: light.turn_on
target:
  entity_id: light.chameleon_lounge
data:
  effect: "Now Playing - Lounge"
```

The effect name follows the player's friendly name; automations that name it need updating if
you rename the player.
````

Add two rows to the State Attributes table (after `unavailable_lights`):

```markdown
| `media_player` | Linked media player entity ID (only when one is configured) |
| `now_playing` | `Artist - Title` while following the music |
```

Run: `pre-commit run --files README.md docs/superpowers/specs/2026-10-14-media-player-now-playing-design.md` twice (prettier reformats tables on the first run).
Expected: second run passes.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/superpowers/specs/2026-10-14-media-player-now-playing-design.md
git commit -m "docs: document the Now Playing effect"
```

- [ ] **Step 5: Manual verification on the owner's instance**

Deploy with `make deploy` **only after the owner says to** (it rsyncs to production), restart HA, Reconfigure the lounge Chameleon to link the Music Assistant lounge player, then check:

1. Effect list shows `Now Playing - Lounge` after Random.
2. Pick it while music plays → lights take album colours; `now_playing` attribute shows artist - title.
3. Skip within one album → no repaint. Skip to another album → repaint.
4. Pause for a few minutes → colours hold (token rotation must not repaint).
5. Stop playback, wait 30 s → previous scene returns; effect shows that scene.
6. Pick Now Playing with nothing playing → previous scene stays, `last_error: Nothing playing on media_player.…`.
7. Rename the player → effect name updates; turn off, bare turn on → Now Playing resumes.
8. Move the transition slider across 0 while in Now Playing → re-applies cover static/animated; stopping playback still returns to the original scene.

```

```
