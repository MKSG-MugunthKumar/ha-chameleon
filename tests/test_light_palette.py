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
