"""The Chameleon integration - Extract colors from images and apply to RGB lights."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, IMAGE_DIRECTORY, PLATFORMS

_LOGGER = logging.getLogger(__name__)

type ChameleonConfigEntry = ConfigEntry[None]


async def async_setup_entry(hass: HomeAssistant, entry: ChameleonConfigEntry) -> bool:
    """Set up Chameleon from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # Create the image directory if it doesn't exist
    image_dir = Path(IMAGE_DIRECTORY)
    if not image_dir.exists():
        _LOGGER.info("Creating Chameleon image directory: %s", IMAGE_DIRECTORY)
        await hass.async_add_executor_job(image_dir.mkdir, True, True)

    # Store entry data
    hass.data[DOMAIN][entry.entry_id] = {
        "config": entry.data,
    }

    # Forward entry setup to platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ChameleonConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
