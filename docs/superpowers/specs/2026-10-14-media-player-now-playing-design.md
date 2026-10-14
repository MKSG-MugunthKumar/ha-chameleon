# Now Playing: album-art colours from a linked media player

- **Date:** 2026-10-14
- **Status:** Approved design, pending implementation plan
- **Roadmap:** README → Future Features → Media Player Integration

## Goal

A Chameleon light can follow the album art of **one specific media player**, typically the
player in the same room in a multi-room audio setup. The user opts in by picking an effect from
any stock light card; no YAML, no automation, no custom card.

Colour extraction is already solved (ColorThief, used for scene images). This feature is the
Home Assistant wiring: linking a player, getting its cover, deciding when to follow it and when
to stop.

## Decisions

| Question                           | Decision                                                                                                            |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| How a light links to a player      | Optional media player field on the config entry (user + reconfigure steps). Not a service, not an `input_*` helper. |
| How following starts               | Opt-in effect `Now Playing - <player name>`. Never automatic; music never turns lights on.                          |
| Paused                             | Hold the current colours.                                                                                           |
| Idle / off / standby / unavailable | 30 s grace period, then fall back.                                                                                  |
| Fall back to                       | The effect active before Now Playing was picked; `Random` if there was none.                                        |
| After fall back                    | Out of Now Playing. Music resuming later does nothing until the effect is picked again.                             |
| Automation-facing service          | Not built. Can be added later on top of the same internals if someone asks.                                         |

## Behaviour

### Setup

- Config flow and the reconfigure step gain an optional **Media player** field
  (`EntitySelector(domain="media_player")`), stored as `CONF_MEDIA_PLAYER = "media_player"` in
  `entry.data`.
- Entries without it behave exactly as today and have no Now Playing effect. No migration, no
  `VERSION` bump.
- Adding, changing, or clearing the player via reconfigure reloads the entry.

### Effect name

- Displayed as `Now Playing - <friendly name>`, using the player's current `friendly_name`.
  Fallback when the player has no state: the object ID title-cased (same rule as
  `helpers._get_light_friendly_name`), e.g. `media_player.lounge_speaker` → `Lounge Speaker`.
- Effect list order: `Random`, `Now Playing - <name>`, then scenes.
- Internally the mode is tracked with a fixed marker (`NOW_PLAYING_EFFECT` sentinel), never the
  display string. `_last_effect` stores the marker, so renaming the player does not break bare
  `turn_on` restore or fallback. The display string is built on read in `effect` and
  `effect_list`.
- `turn_on(effect=...)` matches the **current** display string. A hand-written automation that
  names the effect must be updated after a player rename (same as renaming a scene image).

### Entering Now Playing

1. Stop any running animation (as for any effect).
2. Start the tracker for the linked player.
3. If the player has a cover now (state `playing` or `paused` with an `entity_picture`): fetch,
   extract, apply through the normal pipeline (transition, transition style, static or animated,
   brightness).
4. If not: fall back immediately and set `last_error: "Nothing playing on <entity_id>"`.

### While in Now Playing

- Cover change (see _Cover identity_) while `playing` or `paused` → re-extract and re-apply.
- Same cover, different track (same album) → nothing.
- `paused` → hold.
- `idle`, `off`, `standby`, `unavailable` → start the 30 s grace timer. Returning to `playing`
  or `paused` within it cancels the timer. Timer expiry → fall back.

### Leaving Now Playing

- Picking any other effect, a manual colour, or `turn_off` stops the tracker and cancels the
  grace timer.
- Fall back = apply the pre-Now-Playing effect (or `Random`) through the normal `_apply_effect`
  path, with the tracker stopped first.
- The fallback target lives in `_fallback_effect`. On entering Now Playing the candidate is the
  current `_effect`, or `_last_effect` when the light is off. It is stored only if it is a scene
  or `Random` (not the Now Playing marker); otherwise the previous value is kept. `None` means
  `Random`. This prevents re-entry (bare `turn_on`, transition slider crossing zero) from making
  Now Playing its own fallback.
- Bare `turn_on` after `turn_off` restores `_last_effect`; if that is the Now Playing marker,
  enter Now Playing again (step 3/4 above).

### Attributes

- `media_player`: the linked entity ID (present only when configured).
- `now_playing`: `"<artist> - <title>"` while in Now Playing and a track is known; absent
  otherwise.
- Existing `effect`, `last_error`, `extracted_palette`, `dominant_*` attributes reflect the album
  palette while in Now Playing.

## Architecture

### `now_playing.py` - `NowPlayingTracker` (new)

Watches one media player and reports events. Knows nothing about lights.

```python
class NowPlayingTracker:
    def __init__(self, hass: HomeAssistant, media_player: str, grace: float = 30.0) -> None: ...
    def start(self, on_cover: Callable[[str], None], on_fallback: Callable[[], None]) -> None: ...
    def stop(self) -> None: ...
    def current_cover_key(self) -> str | None: ...
    async def async_fetch_cover(self) -> bytes | None: ...
```

- `start` subscribes with `async_track_state_change_event` on the player; `stop` unsubscribes
  and cancels the grace timer (`async_call_later` handle). Both are idempotent.
- `on_cover(cover_key)` fires when the cover key changes while `playing`/`paused`.
- `on_fallback()` fires when the grace timer expires.
- `async_fetch_cover` gets image bytes from the player **entity**, via the media_player entity
  component and `async_get_media_image()`, wrapped in a 10 s timeout. Returns `None` on any
  failure. It never fetches `entity_picture` over HTTP (avoids auth, internal/external URL,
  and Music Assistant imageproxy URL-format issues).

#### Cover identity

`entity_picture` for proxied images is `/api/media_player_proxy/<id>?token=<t>&cache=<hash>`.
HA rotates `token` every 5 minutes, so the full string is **not** a stable identity. The cover
key is the `cache` query parameter; if absent (remotely accessible image URL), the full
`entity_picture` string. `None` when there is no `entity_picture`.

### `color_extractor.py`

`extract_color_palette` and `extract_dominant_color` accept `Path | bytes`. Bytes are wrapped in
`io.BytesIO` for ColorThief inside the executor job. Nothing is written to disk.

### `light.py`

- **Refactor:** `_apply_colors_static` / `_apply_colors_animated` take a palette
  (`list[RGBColor]`) instead of an image path. Extraction moves to the callers (scene path and
  Now Playing path). Behaviour for scenes is unchanged.
- `_apply_effect` recognises the Now Playing display string / marker and runs _Entering Now
  Playing_. Every other effect path, `_apply_manual_color`, and `_do_turn_off` stop the tracker.
- Tracker callbacks are `@callback`s that only record state and schedule work with
  `entry.async_create_task`. The scheduled coroutine:
  1. takes `self._lock`;
  2. returns if no longer in Now Playing;
  3. for covers: returns if `cover_key` is no longer the latest seen (superseded by a newer
     skip), otherwise fetches, extracts, applies;
  4. for fallback: stops the tracker and applies the pre-Now-Playing effect.
- `effect` returns the display string while in Now Playing; `effect_list` inserts it after
  `Random` when a player is configured.
- `async_will_remove_from_hass` stops the tracker.

### `config_flow.py`, `strings.json`, `translations/en.json`, `const.py`

- `CONF_MEDIA_PLAYER` constant; optional selector in both steps; reconfigure pre-fills it and
  writes it via `data_updates`. Clearing the field stores `None`, which is treated the same as
  the key being absent.
- Strings for the new field and its description.

## Error handling

| Situation                                           | Behaviour                                                                                       |
| --------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| Player configured, not yet in HA (startup ordering) | Effect shown with the object-ID name; name updates once the player has state.                   |
| Player deleted from HA                              | Picking Now Playing falls back; `last_error: "<entity_id> not found"`.                          |
| Player has no image                                 | Treated as nothing playing: fall back with `last_error`.                                        |
| Cover fetch fails / times out                       | Keep current colours, **stay** in Now Playing, set `last_error`. Next cover change retries.     |
| Extraction fails                                    | Same as fetch failure.                                                                          |
| Rapid track skipping                                | Latest-key check under the lock: superseded covers do nothing; one repaint for the final cover. |
| Callback after user switched effect                 | Mode re-checked under the lock; work dropped.                                                   |
| Entry unload / reload                               | Tracker stopped; listener and grace timer cancelled.                                            |
| Member lights offline                               | Existing availability handling; unchanged.                                                      |

Principle: **player state decides whether to leave Now Playing; fetch or extraction errors never
do.**

## Testing

Automated (mocked HA, as the existing suite):

- `NowPlayingTracker`: token rotation with same `cache=` → no event; new `cache=` → `on_cover`;
  remote URL without `cache=` uses the full string; `paused` holds; `idle` → grace → `on_fallback`;
  resume within grace cancels; `stop()` cancels listener and timer; fetch timeout → `None`.
- `color_extractor`: palette from bytes of a small Pillow-generated PNG.
- `light.py`: display name from friendly name and fallback; `_last_effect` survives a rename;
  entering with no cover falls back with `last_error`; fetch failure keeps the mode; superseded
  and post-switch callbacks are dropped; fallback restores the previous effect or `Random`;
  `turn_off` stops the tracker; effect list unchanged without a player.
- Config flow: optional player in the user and reconfigure steps; pre-fill; entries without it
  unchanged.

Manual, on the owner's instance (Music Assistant, lounge player):

- Skip tracks within one album → no repaint; change album → repaint.
- Pause for a while → colours hold.
- Stop, wait 30 s → previous scene returns.
- Rename the player → effect name follows; bare `turn_on` still restores Now Playing.

## Out of scope

- A `chameleon.apply_media_image` service for automation-driven use.
- Following more than one player per Chameleon entry, or switching players at runtime.
- Automatic takeover when music starts.
- Restoring Now Playing across HA restarts (Chameleon does not restore state today).
