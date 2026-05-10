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
    DOMAIN,
    IMAGE_DIRECTORY,
    MAX_ANIMATION_SPEED,
    MAX_BRIGHTNESS,
    MIN_ANIMATION_SPEED,
    MIN_BRIGHTNESS,
    PLATFORMS,
    SERVICE_APPLY_SCENE,
    SERVICE_REFRESH_SCENES,
)

_LOGGER = logging.getLogger(__name__)

type ChameleonConfigEntry = ConfigEntry[None]

SERVICE_APPLY_SCENE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_SCENE_NAME): cv.string,
        vol.Optional("brightness"): vol.All(vol.Coerce(int), vol.Range(min=MIN_BRIGHTNESS, max=MAX_BRIGHTNESS)),
        vol.Optional("speed"): vol.All(vol.Coerce(float), vol.Range(min=MIN_ANIMATION_SPEED, max=MAX_ANIMATION_SPEED)),
    }
)

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
        #   - the refresh-scenes button (replaced by the chameleon.refresh_scenes
        #     service action)
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


def _scene_entity_sibling(scene_entity_id: str, sibling_suffix: str, domain: str = "number") -> str:
    """Derive a sibling entity ID from a Chameleon scene select entity ID.

    ``select.chameleon_living_room_scene`` + ``"animation_speed"`` →
    ``number.chameleon_living_room_animation_speed``.
    """
    base = scene_entity_id.removeprefix("select.").removesuffix("_scene")
    return f"{domain}.{base}_{sibling_suffix}"


async def _async_register_services(hass: HomeAssistant) -> None:
    """Register Chameleon services.

    Two services:

    - ``apply_scene``: targets the scene select entity. Optionally accepts
      ``brightness`` and ``speed`` to set those sliders before the scene is
      applied — covers the old ``start_animation`` / ``stop_animation`` cases
      (pass ``speed > 0`` to start, ``speed = 0`` to stop) without separate
      services.
    - ``refresh_scenes``: rescans the image directory for every Chameleon
      config. No target needed.

    Direct slider control still goes through ``number.set_value`` per HA
    convention — we don't wrap it.
    """

    async def handle_apply_scene(call: ServiceCall) -> None:
        """Apply a scene, optionally setting brightness and/or speed first.

        ``brightness`` and ``speed`` are optional; if omitted, the existing slider
        values are kept. When supplied, the sliders are set *before* the scene is
        applied so the new scene is rendered at the requested values directly
        (rather than at the old values then bumped).
        """
        entity_ids: list[str] = call.data.get("entity_id", [])
        scene_name: str = call.data[ATTR_SCENE_NAME]
        brightness = call.data.get("brightness")
        speed = call.data.get("speed")

        for entity_id in entity_ids:
            if not entity_id.startswith("select.chameleon_"):
                _LOGGER.warning("Skipping %s: not a Chameleon select entity", entity_id)
                continue

            if brightness is not None:
                await hass.services.async_call(
                    "number",
                    "set_value",
                    {
                        "entity_id": _scene_entity_sibling(entity_id, "brightness"),
                        "value": brightness,
                    },
                    blocking=True,
                )

            if speed is not None:
                await hass.services.async_call(
                    "number",
                    "set_value",
                    {
                        "entity_id": _scene_entity_sibling(entity_id, "animation_speed"),
                        "value": speed,
                    },
                    blocking=True,
                )

            await hass.services.async_call(
                "select",
                "select_option",
                {"entity_id": entity_id, "option": scene_name},
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
        SERVICE_REFRESH_SCENES,
        handle_refresh_scenes,
        schema=SERVICE_REFRESH_SCENES_SCHEMA,
    )
