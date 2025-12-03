"""Tests for color_extractor module."""

from __future__ import annotations

import pytest

from custom_components.chameleon.color_extractor import (
    generate_gradient_path,
    rgb_to_hs,
)


class TestGenerateGradientPath:
    """Tests for generate_gradient_path function."""

    def test_empty_colors(self):
        """Test with empty color list."""
        result = generate_gradient_path([])
        assert result == []

    def test_single_color(self):
        """Test with single color."""
        colors = [(255, 0, 0)]
        result = generate_gradient_path(colors)
        assert result == colors

    def test_two_colors_default_steps(self):
        """Test gradient between two colors with default steps."""
        colors = [(255, 0, 0), (0, 255, 0)]  # Red to Green
        result = generate_gradient_path(colors, steps_between=10)

        # Should have 20 colors (10 steps between each pair, 2 pairs for loop back)
        assert len(result) == 20

        # First color should be red
        assert result[0] == (255, 0, 0)

        # Colors should transition smoothly
        # Check that red decreases and green increases in first half
        for i in range(1, 10):
            assert result[i][0] < result[i - 1][0] or result[i][0] == 0  # Red decreases
            assert result[i][1] > result[i - 1][1] or result[i][1] == 255  # Green increases

    def test_three_colors(self):
        """Test gradient with three colors."""
        colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255)]
        result = generate_gradient_path(colors, steps_between=5)

        # Should have 15 colors (5 steps * 3 pairs)
        assert len(result) == 15

    def test_steps_between_one(self):
        """Test with minimal steps (essentially no interpolation)."""
        colors = [(255, 0, 0), (0, 255, 0)]
        result = generate_gradient_path(colors, steps_between=1)

        # Should just have the starting colors (1 step per transition)
        assert len(result) == 2
        assert result[0] == (255, 0, 0)
        assert result[1] == (0, 255, 0)

    def test_gradient_values_in_range(self):
        """Test that all gradient values are valid RGB."""
        colors = [(255, 128, 0), (0, 64, 255)]
        result = generate_gradient_path(colors, steps_between=20)

        for r, g, b in result:
            assert 0 <= r <= 255
            assert 0 <= g <= 255
            assert 0 <= b <= 255


class TestRgbToHs:
    """Tests for rgb_to_hs function."""

    def test_red(self):
        """Test pure red."""
        hue, sat = rgb_to_hs((255, 0, 0))
        assert hue == pytest.approx(0, abs=1)
        assert sat == pytest.approx(100, abs=1)

    def test_green(self):
        """Test pure green."""
        hue, sat = rgb_to_hs((0, 255, 0))
        assert hue == pytest.approx(120, abs=1)
        assert sat == pytest.approx(100, abs=1)

    def test_blue(self):
        """Test pure blue."""
        hue, sat = rgb_to_hs((0, 0, 255))
        assert hue == pytest.approx(240, abs=1)
        assert sat == pytest.approx(100, abs=1)

    def test_yellow(self):
        """Test yellow (red + green)."""
        hue, sat = rgb_to_hs((255, 255, 0))
        assert hue == pytest.approx(60, abs=1)
        assert sat == pytest.approx(100, abs=1)

    def test_cyan(self):
        """Test cyan (green + blue)."""
        hue, sat = rgb_to_hs((0, 255, 255))
        assert hue == pytest.approx(180, abs=1)
        assert sat == pytest.approx(100, abs=1)

    def test_magenta(self):
        """Test magenta (red + blue)."""
        hue, sat = rgb_to_hs((255, 0, 255))
        assert hue == pytest.approx(300, abs=1)
        assert sat == pytest.approx(100, abs=1)

    def test_white(self):
        """Test white (no saturation)."""
        _hue, sat = rgb_to_hs((255, 255, 255))
        assert sat == pytest.approx(0, abs=1)
        # Hue is undefined for white, but should be 0

    def test_black(self):
        """Test black (no saturation)."""
        _hue, sat = rgb_to_hs((0, 0, 0))
        assert sat == pytest.approx(0, abs=1)

    def test_gray(self):
        """Test gray (50% brightness, no saturation)."""
        _hue, sat = rgb_to_hs((128, 128, 128))
        assert sat == pytest.approx(0, abs=1)

    def test_half_saturation(self):
        """Test color with 50% saturation."""
        # Light red (pink-ish)
        hue, sat = rgb_to_hs((255, 128, 128))
        assert hue == pytest.approx(0, abs=1)  # Still red hue
        assert 40 < sat < 60  # Approximately 50% saturation
