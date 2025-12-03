"""Tests for light_controller module."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

# Import will use mocked homeassistant modules from conftest
from custom_components.chameleon.light_controller import (
    ApplyColorsResult,
    LightController,
    LightError,
    LightResult,
)


class TestLightResult:
    """Tests for LightResult dataclass."""

    def test_successful_result(self):
        """Test creating a successful result."""
        result = LightResult(
            entity_id="light.test",
            success=True,
            color=(255, 0, 0),
        )
        assert result.success is True
        assert result.color == (255, 0, 0)
        assert result.error is None
        assert result.error_message is None

    def test_failed_result(self):
        """Test creating a failed result."""
        result = LightResult(
            entity_id="light.test",
            success=False,
            error=LightError.NOT_FOUND,
            error_message="Light not found",
        )
        assert result.success is False
        assert result.error == LightError.NOT_FOUND
        assert result.error_message == "Light not found"


class TestApplyColorsResult:
    """Tests for ApplyColorsResult dataclass."""

    def test_all_succeeded(self):
        """Test when all lights succeed."""
        result = ApplyColorsResult(
            results=[
                LightResult("light.one", True, (255, 0, 0)),
                LightResult("light.two", True, (0, 255, 0)),
            ]
        )
        assert result.all_succeeded is True
        assert result.all_failed is False
        assert result.partial_failure is False
        assert result.succeeded_count == 2
        assert result.failed_count == 0

    def test_all_failed(self):
        """Test when all lights fail."""
        result = ApplyColorsResult(
            results=[
                LightResult("light.one", False, error=LightError.NOT_FOUND),
                LightResult("light.two", False, error=LightError.UNAVAILABLE),
            ]
        )
        assert result.all_succeeded is False
        assert result.all_failed is True
        assert result.partial_failure is False
        assert result.succeeded_count == 0
        assert result.failed_count == 2

    def test_partial_failure(self):
        """Test when some lights fail."""
        result = ApplyColorsResult(
            results=[
                LightResult("light.one", True, (255, 0, 0)),
                LightResult("light.two", False, error=LightError.UNAVAILABLE),
            ]
        )
        assert result.all_succeeded is False
        assert result.all_failed is False
        assert result.partial_failure is True
        assert result.succeeded_count == 1
        assert result.failed_count == 1

    def test_applied_colors(self):
        """Test getting applied colors dict."""
        result = ApplyColorsResult(
            results=[
                LightResult("light.one", True, (255, 0, 0)),
                LightResult("light.two", True, (0, 255, 0)),
                LightResult("light.three", False, error=LightError.UNAVAILABLE),
            ]
        )
        colors = result.applied_colors
        assert colors == {
            "light.one": (255, 0, 0),
            "light.two": (0, 255, 0),
        }

    def test_failed_lights(self):
        """Test getting failed lights dict."""
        result = ApplyColorsResult(
            results=[
                LightResult("light.one", True, (255, 0, 0)),
                LightResult(
                    "light.two",
                    False,
                    error=LightError.UNAVAILABLE,
                    error_message="Device offline",
                ),
            ]
        )
        failed = result.failed_lights
        assert "light.two" in failed
        assert failed["light.two"] == "Device offline"


class TestLightController:
    """Tests for LightController class."""

    def test_init(self, hass):
        """Test controller initialization."""
        controller = LightController(hass)
        assert controller.hass is hass
        assert controller.transition_time == 2  # Default

    def test_init_custom_transition(self, hass):
        """Test controller with custom transition time."""
        controller = LightController(hass, transition_time=5)
        assert controller.transition_time == 5

    def test_check_light_availability_not_found(self, hass):
        """Test checking availability when light doesn't exist."""
        hass.states.get.return_value = None

        controller = LightController(hass)
        is_available, error, msg = controller.check_light_availability("light.missing")

        assert is_available is False
        assert error == LightError.NOT_FOUND
        assert "does not exist" in msg

    def test_check_light_availability_unavailable(self, hass, mock_light_state_unavailable):
        """Test checking availability when light is unavailable."""
        hass.states.get.return_value = mock_light_state_unavailable

        controller = LightController(hass)
        is_available, error, msg = controller.check_light_availability("light.test_light")

        assert is_available is False
        assert error == LightError.UNAVAILABLE
        assert "unavailable" in msg

    def test_check_light_availability_no_rgb(self, hass, mock_light_state_no_rgb):
        """Test checking availability when light doesn't support RGB."""
        hass.states.get.return_value = mock_light_state_no_rgb

        controller = LightController(hass)
        is_available, error, msg = controller.check_light_availability("light.test_light")

        assert is_available is False
        assert error == LightError.NO_RGB_SUPPORT
        assert "does not support RGB" in msg

    def test_check_light_availability_success(self, hass, mock_light_state):
        """Test checking availability for a valid RGB light."""
        hass.states.get.return_value = mock_light_state

        controller = LightController(hass)
        is_available, error, msg = controller.check_light_availability("light.test_light")

        assert is_available is True
        assert error is None
        assert msg is None

    @pytest.mark.asyncio
    async def test_apply_color_to_light_success(self, hass, mock_light_state):
        """Test successfully applying color to a light."""
        hass.states.get.return_value = mock_light_state
        hass.services.async_call = AsyncMock()

        controller = LightController(hass)
        result = await controller.apply_color_to_light("light.test_light", (255, 0, 0))

        assert result.success is True
        assert result.color == (255, 0, 0)
        hass.services.async_call.assert_called_once()

    @pytest.mark.asyncio
    async def test_apply_color_to_light_unavailable(self, hass):
        """Test applying color to unavailable light."""
        hass.states.get.return_value = None  # Light doesn't exist

        controller = LightController(hass)
        result = await controller.apply_color_to_light("light.missing", (255, 0, 0))

        assert result.success is False
        assert result.error == LightError.NOT_FOUND

    @pytest.mark.asyncio
    async def test_apply_color_to_light_service_fails(self, hass, mock_light_state):
        """Test when service call raises exception."""
        hass.states.get.return_value = mock_light_state
        hass.services.async_call = AsyncMock(side_effect=Exception("Service failed"))

        controller = LightController(hass)
        result = await controller.apply_color_to_light("light.test_light", (255, 0, 0))

        assert result.success is False
        assert result.error == LightError.SERVICE_CALL_FAILED
        assert "Service failed" in result.error_message

    @pytest.mark.asyncio
    async def test_apply_colors_to_lights_all_success(self, hass, mock_light_state):
        """Test applying colors to multiple lights successfully."""
        hass.states.get.return_value = mock_light_state
        hass.services.async_call = AsyncMock()

        controller = LightController(hass)
        result = await controller.apply_colors_to_lights(
            {
                "light.one": (255, 0, 0),
                "light.two": (0, 255, 0),
            }
        )

        assert result.all_succeeded is True
        assert result.succeeded_count == 2

    @pytest.mark.asyncio
    async def test_apply_colors_to_lights_partial_failure(self, hass, mock_light_state):
        """Test applying colors with some lights failing."""

        # First light exists, second doesn't
        def get_state(entity_id):
            if entity_id == "light.one":
                return mock_light_state
            return None

        hass.states.get.side_effect = get_state
        hass.services.async_call = AsyncMock()

        controller = LightController(hass)
        result = await controller.apply_colors_to_lights(
            {
                "light.one": (255, 0, 0),
                "light.missing": (0, 255, 0),
            }
        )

        assert result.partial_failure is True
        assert result.succeeded_count == 1
        assert result.failed_count == 1
