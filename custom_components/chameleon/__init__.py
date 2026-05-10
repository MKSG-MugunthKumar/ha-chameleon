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
    MAX_BRIGHTNESS,
    MAX_TRANSITION,
    MIN_BRIGHTNESS,
    MIN_TRANSITION,
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
        vol.Optional("transition"): vol.All(vol.Coerce(float), vol.Range(min=MIN_TRANSITION, max=MAX_TRANSITION)),
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
             entities (animation on/off is now ``transition > 0``; sync vs
             staggered is now a transition_style select). Strips the unused
             ``animation_enabled`` key from entry.data. Also removes the
             ``ChameleonRefreshButton`` (replaced by the chameleon.refresh_scenes
             service action).
    v3 → v4: collapses the scene select and brightness number into a single light
             entity that exposes scenes via ``LightEntityFeature.EFFECT`` and
             owns brightness natively. Renames the ``animation_speed`` slider
             entity to ``transition`` and the ``animation_mode`` select to
             ``transition_style``; renames the ``animation_speed`` key in
             entry.data to ``transition``.
    """
    target_version = 4
    _LOGGER.info(
        "Migrating Chameleon config entry %s from v%d to v%d",
        entry.entry_id,
        entry.version,
        target_version,
    )

    entity_registry = er.async_get(hass)

    if entry.version < 3:
        # Remove orphan v2 entities so users don't see "no longer provided"
        # entries in the integrations page:
        #   - the two animation/sync_animation switches
        #   - the refresh-scenes button (replaced by chameleon.refresh_scenes service)
        v2_orphans = {
            f"{DOMAIN}_{entry.entry_id}_animation",
            f"{DOMAIN}_{entry.entry_id}_sync_animation",
            f"{DOMAIN}_{entry.entry_id}_refresh",
        }
        for ent in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
            if ent.unique_id in v2_orphans:
                _LOGGER.info("Removing orphan v2 entity: %s", ent.entity_id)
                entity_registry.async_remove(ent.entity_id)

        new_data = {k: v for k, v in entry.data.items() if k != "animation_enabled"}
        hass.config_entries.async_update_entry(entry, data=new_data, version=3)

    if entry.version < 4:
        # Remove orphan v3 entities — scene select and brightness number are now
        # covered by the light entity's effect dropdown and native brightness.
        v3_orphans = {
            f"{DOMAIN}_{entry.entry_id}_scene",
            f"{DOMAIN}_{entry.entry_id}_brightness",
        }
        # Rename the animation_speed slider → transition, animation_mode → transition_style.
        # We rename in-place (preserving the user's customisations like custom name
        # / area / icon) by updating unique_id + entity_id on the existing entry.
        rename_map = {
            f"{DOMAIN}_{entry.entry_id}_animation_speed": (
                f"{DOMAIN}_{entry.entry_id}_transition",
                "_animation_speed",
                "_transition",
            ),
            f"{DOMAIN}_{entry.entry_id}_animation_mode": (
                f"{DOMAIN}_{entry.entry_id}_transition_style",
                "_animation_mode",
                "_transition_style",
            ),
        }

        for ent in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
            if ent.unique_id in v3_orphans:
                _LOGGER.info("Removing orphan v3 entity: %s", ent.entity_id)
                entity_registry.async_remove(ent.entity_id)
                continue

            rename = rename_map.get(ent.unique_id)
            if rename is not None:
                new_unique_id, old_suffix, new_suffix = rename
                new_entity_id = ent.entity_id.replace(old_suffix, new_suffix)
                _LOGGER.info("Renaming entity: %s → %s", ent.entity_id, new_entity_id)
                entity_registry.async_update_entity(
                    ent.entity_id,
                    new_unique_id=new_unique_id,
                    new_entity_id=new_entity_id,
                )

        # Rename entry.data["animation_speed"] → entry.data["transition"].
        new_data = dict(entry.data)
        if "animation_speed" in new_data:
            new_data["transition"] = new_data.pop("animation_speed")

        hass.config_entries.async_update_entry(entry, data=new_data, version=4)

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


def _light_entity_sibling(light_entity_id: str, sibling_suffix: str, domain: str = "number") -> str:
    """Derive a sibling entity ID from a Chameleon light entity ID.

    ``light.chameleon_living_room`` + ``"transition"`` →
    ``number.chameleon_living_room_transition``.
    """
    base = light_entity_id.removeprefix("light.")
    return f"{domain}.{base}_{sibling_suffix}"


async def _async_register_services(hass: HomeAssistant) -> None:
    """Register Chameleon services.

    Two services:

    - ``apply_scene``: targets the Chameleon light entity. Optionally accepts
      ``brightness`` and ``transition`` to set those values atomically with the
      scene change. To start animation pass ``transition > 0``; to stop it
      pass ``transition = 0`` (also expressible as a plain number.set_value
      call).
    - ``refresh_scenes``: rescans the image directory for every Chameleon
      config. No target needed.

    Direct slider control (transition, transition style) still goes through
    the standard ``number.set_value`` / ``select.select_option`` services per
    HA convention — we don't wrap those.
    """

    async def handle_apply_scene(call: ServiceCall) -> None:
        """Apply a scene, optionally setting brightness and/or transition first.

        ``brightness`` and ``transition`` are optional; if omitted, the existing
        values are preserved. Brightness flows directly into ``light.turn_on``;
        transition must be set on the sibling number entity first because the
        light entity doesn't own the animation tick rate.
        """
        entity_ids: list[str] = call.data.get("entity_id", [])
        scene_name: str = call.data[ATTR_SCENE_NAME]
        brightness = call.data.get("brightness")  # 0-100 in Chameleon scale
        transition = call.data.get("transition")

        for entity_id in entity_ids:
            if not entity_id.startswith("light.chameleon_"):
                _LOGGER.warning("Skipping %s: not a Chameleon light entity", entity_id)
                continue

            # Transition lives on a sibling number entity — set it before the
            # scene is applied so the light's _apply_effect reads the new value.
            if transition is not None:
                await hass.services.async_call(
                    "number",
                    "set_value",
                    {
                        "entity_id": _light_entity_sibling(entity_id, "transition"),
                        "value": transition,
                    },
                    blocking=True,
                )

            # Brightness flows directly into the light's turn_on call (HA's 0-255 scale).
            turn_on_data: dict = {"entity_id": entity_id, "effect": scene_name}
            if brightness is not None:
                turn_on_data["brightness"] = int(brightness * 255 / 100)

            await hass.services.async_call(
                "light",
                "turn_on",
                turn_on_data,
                blocking=True,
            )

    async def handle_refresh_scenes(_call: ServiceCall) -> None:
        """Rescan the image directory and update every Chameleon light entity.

        All Chameleon configs share /config/www/chameleon/, so this refreshes
        every entity in one go — no per-entity targeting needed.
        """
        domain_data = hass.data.get(DOMAIN, {})
        refreshed = 0
        for key, entry_data in domain_data.items():
            if key == "animation_manager" or not isinstance(entry_data, dict):
                continue
            chameleon_light = entry_data.get("chameleon_light")
            if chameleon_light is not None:
                await chameleon_light.async_refresh_options()
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
