"""The Chameleon integration - Extract colors from images and apply to RGB lights."""

from __future__ import annotations

import logging
from pathlib import Path

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er

from .animations import AnimationManager
from .const import (
    ATTR_SCENE_NAME,
    DEFAULT_ANIMATION_SPEED,
    DOMAIN,
    IMAGE_DIRECTORY,
    PLATFORMS,
    SERVICE_APPLY_SCENE,
    SERVICE_REFRESH_SCENES,
    SERVICE_START_ANIMATION,
    SERVICE_STOP_ANIMATION,
)

_LOGGER = logging.getLogger(__name__)

type ChameleonConfigEntry = ConfigEntry[None]

SERVICE_APPLY_SCENE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_SCENE_NAME): cv.string,
    }
)

SERVICE_START_ANIMATION_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_SCENE_NAME): cv.string,
    }
)

SERVICE_STOP_ANIMATION_SCHEMA = vol.Schema({})

SERVICE_REFRESH_SCENES_SCHEMA = vol.Schema({})


async def async_setup_entry(hass: HomeAssistant, entry: ChameleonConfigEntry) -> bool:
    """Set up Chameleon from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    image_dir = Path(IMAGE_DIRECTORY)
    if not image_dir.exists():
        _LOGGER.info("Creating Chameleon image directory: %s", IMAGE_DIRECTORY)
        await hass.async_add_executor_job(image_dir.mkdir, True, True)

    if "animation_manager" not in hass.data[DOMAIN]:
        hass.data[DOMAIN]["animation_manager"] = AnimationManager(hass)

    hass.data[DOMAIN].setdefault(entry.entry_id, {})["config"] = entry.data

    if not hass.services.has_service(DOMAIN, SERVICE_APPLY_SCENE):
        await _async_register_services(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old config entries to the current schema.

    v1 → v2: multi-light support (light_entity → light_entities). Already in place
             via the runtime fallback in each platform's setup; nothing to do here.
    v2 → v3: removes the ``ChameleonAnimationSwitch`` / ``ChameleonSyncAnimationSwitch``
             entities (animation on/off is now ``animation_speed > 0``; sync vs
             staggered is now an animation_mode select). Strips the unused
             ``animation_enabled`` key from entry.data.
    """
    _LOGGER.info(
        "Migrating Chameleon config entry %s from v%d to v%d",
        entry.entry_id,
        entry.version,
        3,
    )

    if entry.version < 3:
        # Remove orphan v2 entities so users don't see "no longer provided"
        # entries in the integrations page:
        #   - the two animation/sync_animation switches (collapsed into speed=0
        #     and the new animation_mode select)
        #   - the refresh-scenes button (the directory auto-rescans every 30s,
        #     so the manual button was redundant)
        orphan_unique_ids = {
            f"{DOMAIN}_{entry.entry_id}_animation",
            f"{DOMAIN}_{entry.entry_id}_sync_animation",
            f"{DOMAIN}_{entry.entry_id}_refresh",
        }
        entity_registry = er.async_get(hass)
        for ent in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
            if ent.unique_id in orphan_unique_ids:
                _LOGGER.info("Removing orphan v2 entity: %s", ent.entity_id)
                entity_registry.async_remove(ent.entity_id)

        new_data = {k: v for k, v in entry.data.items() if k != "animation_enabled"}
        hass.config_entries.async_update_entry(entry, data=new_data, version=3)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ChameleonConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)

        remaining_entries = [key for key in hass.data[DOMAIN] if key != "animation_manager"]
        if not remaining_entries:
            animation_manager: AnimationManager = hass.data[DOMAIN].get("animation_manager")
            if animation_manager:
                await animation_manager.stop_all()

    return unload_ok


def _scene_entity_to_speed_entity(scene_entity_id: str) -> str:
    """Map ``select.chameleon_<base>_scene`` → ``number.chameleon_<base>_animation_speed``."""
    base = scene_entity_id.removeprefix("select.").removesuffix("_scene")
    return f"number.{base}_animation_speed"


async def _async_register_services(hass: HomeAssistant) -> None:
    """Register Chameleon services.

    All three services target the Chameleon scene select entity for consistency.
    Animation on/off is now derived from the animation_speed value (>0 = on,
    0 = off), so start/stop are implemented by setting the speed slider.
    """

    async def handle_apply_scene(call: ServiceCall) -> None:
        """Apply a scene by name to the targeted scene select entities."""
        entity_ids: list[str] = call.data.get("entity_id", [])
        scene_name: str = call.data[ATTR_SCENE_NAME]

        for entity_id in entity_ids:
            if not entity_id.startswith("select.chameleon_"):
                _LOGGER.warning("Skipping %s: not a Chameleon select entity", entity_id)
                continue

            await hass.services.async_call(
                "select",
                "select_option",
                {"entity_id": entity_id, "option": scene_name},
                blocking=True,
            )

    async def handle_start_animation(call: ServiceCall) -> None:
        """Ensure animation is enabled (speed > 0) and apply a scene."""
        entity_ids: list[str] = call.data.get("entity_id", [])
        scene_name: str = call.data[ATTR_SCENE_NAME]

        for entity_id in entity_ids:
            if not entity_id.startswith("select.chameleon_"):
                _LOGGER.warning("Skipping %s: not a Chameleon select entity", entity_id)
                continue

            speed_entity_id = _scene_entity_to_speed_entity(entity_id)
            speed_state = hass.states.get(speed_entity_id)
            current_speed = float(speed_state.state) if speed_state and speed_state.state not in ("unknown", "unavailable") else 0.0

            if current_speed <= 0:
                # Restore last non-zero speed if known, else fall back to default.
                target_speed = (
                    float(speed_state.attributes.get("last_nonzero", DEFAULT_ANIMATION_SPEED)) if speed_state else float(DEFAULT_ANIMATION_SPEED)
                )
                await hass.services.async_call(
                    "number",
                    "set_value",
                    {"entity_id": speed_entity_id, "value": target_speed},
                    blocking=True,
                )

            await hass.services.async_call(
                "select",
                "select_option",
                {"entity_id": entity_id, "option": scene_name},
                blocking=True,
            )

    async def handle_stop_animation(call: ServiceCall) -> None:
        """Stop animation by setting the speed slider to 0."""
        entity_ids: list[str] = call.data.get("entity_id", [])

        for entity_id in entity_ids:
            if not entity_id.startswith("select.chameleon_"):
                _LOGGER.warning("Skipping %s: not a Chameleon select entity", entity_id)
                continue

            speed_entity_id = _scene_entity_to_speed_entity(entity_id)
            await hass.services.async_call(
                "number",
                "set_value",
                {"entity_id": speed_entity_id, "value": 0},
                blocking=True,
            )

    async def handle_refresh_scenes(_call: ServiceCall) -> None:
        """Rescan the image directory and update every Chameleon scene select.

        All Chameleon configs share /config/www/chameleon/, so this refreshes
        every entity in one go — no per-entity targeting needed.
        """
        domain_data = hass.data.get(DOMAIN, {})
        refreshed = 0
        for key, entry_data in domain_data.items():
            if key == "animation_manager" or not isinstance(entry_data, dict):
                continue
            scene_select = entry_data.get("scene_select")
            if scene_select is not None:
                await scene_select.async_refresh_options()
                refreshed += 1
        _LOGGER.info("Refreshed scene list for %d Chameleon config(s)", refreshed)

    hass.services.async_register(
        DOMAIN,
        SERVICE_APPLY_SCENE,
        handle_apply_scene,
        schema=SERVICE_APPLY_SCENE_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_START_ANIMATION,
        handle_start_animation,
        schema=SERVICE_START_ANIMATION_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_STOP_ANIMATION,
        handle_stop_animation,
        schema=SERVICE_STOP_ANIMATION_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_REFRESH_SCENES,
        handle_refresh_scenes,
        schema=SERVICE_REFRESH_SCENES_SCHEMA,
    )
