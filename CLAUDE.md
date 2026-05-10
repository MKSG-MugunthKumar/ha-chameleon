# CLAUDE.md - Chameleon Integration

This file provides guidance to Claude Code when working with the Chameleon custom Home Assistant integration.
The project overview, the architecture is modular and follows best practices, and more information for how to develop is in README.md. Future planned features are listed in the "Future Features" section at the bottom of README.md.

## Code Style (Human and AI Alike)

When working on this project:

- Prioritize code quality and HA best practices
- Follow Home Assistant development guidelines
- Use async/await for all I/O operations
- Keep file structure clean and modular
- Document complex color extraction logic
- Use descriptive variable names
- Add type hints everywhere (Pylance Strict in Visual Studio Code)
- The precommit checks will fail if code style is not followed
- Use conventional commit messages (Again precommit checks will enforce this)
- Use `light_controller.py` for all light control operations
- Track errors in entity attributes for UI visibility
- Add comprehensive docstrings
- Use ASCII `-` in comments, not en-dash `–`; ruff `RUF003` will fail the build
- Prefer `light.turn_off` over `light.turn_on(brightness=0)` — the latter behaves inconsistently across HA versions

## Verification

- Lint, format, and type checks run via pre-commit hooks (configured in `.pre-commit-config.yaml`); they trigger on every commit and in CI. Run them manually with `pre-commit run --all-files`.
- Tests are not in pre-commit. Run with `make test`. Local install needs a C compiler (`pytest-homeassistant-custom-component` → `lru-dict` builds via gcc); CI handles this.

## Architectural Patterns

- **Inter-entity coordination**: subordinate entities (number, transition-style select) register themselves at `hass.data[DOMAIN][entry_id][<key>]` so siblings in other platforms can call back. The Chameleon light exposes `async_reapply_current_scene()` for sliders that cross zero-boundaries.
- **Removing entities in a release**: list their old `unique_id`s in the orphan set inside `async_migrate_entry` and bump `VERSION` in `config_flow.py`. Match by `unique_id` (stable across user renames), not `entity_id`.
- **Renaming entities in a release**: use `entity_registry.async_update_entity(entity_id, new_unique_id=..., new_entity_id=...)` for in-place rename — preserves user customisations (custom name, icon, area). Different pattern from orphan-removal, which retires entirely.
- **Concurrency on stateful entities**: HA dispatches service calls (turn_on/turn_off) concurrently onto the same entity. If the handler mutates shared state (animation manager, scene state), wrap with a per-entity `asyncio.Lock`. Without it, racing calls fail to "replace" each other.
- **Cancel-safe service calls in loops**: prefer `blocking=True` in `hass.services.async_call` inside long-running tasks. `blocking=False` leaks queued calls past cancellation — visible as flicker after a `turn_off`.
- **Instant `turn_off`**: pass `transition=0` to `light.turn_off`, otherwise the light inherits the previous `turn_on(transition=N)` fade duration and "fades to off" instead of going dark.
- **Derive state, don't mirror it**: if a source of truth exists (e.g., `manager.is_running(entry_id)`), expose it as a derived property. Don't keep a parallel `_is_X` flag — mirrors drift, derived properties don't.
- **No custom Lovelace card**: all UX must work through stock HA cards + standard service actions. Don't propose a custom-card path.
