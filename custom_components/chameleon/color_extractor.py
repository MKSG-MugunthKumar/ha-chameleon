"""Color extraction logic for Chameleon integration."""

from __future__ import annotations

import logging
from pathlib import Path

from .const import DEFAULT_COLOR_COUNT, DEFAULT_QUALITY

_LOGGER = logging.getLogger(__name__)

# RGB color type
type RGBColor = tuple[int, int, int]


async def extract_dominant_color(
    image_path: Path,
    quality: int = DEFAULT_QUALITY,
) -> RGBColor | None:
    """
    Extract the single dominant color from an image.

    Args:
        image_path: Path to the image file
        quality: Color extraction quality (1=highest, 10=fastest)

    Returns:
        RGB tuple (r, g, b) or None if extraction fails
    """
    try:
        from colorthief import ColorThief

        color_thief = ColorThief(str(image_path))
        return color_thief.get_color(quality=quality)
    except Exception as e:
        _LOGGER.error("Failed to extract dominant color from %s: %s", image_path, e)
        return None


async def extract_color_palette(
    image_path: Path,
    color_count: int = DEFAULT_COLOR_COUNT,
    quality: int = DEFAULT_QUALITY,
) -> list[RGBColor]:
    """
    Extract a palette of colors from an image.

    Args:
        image_path: Path to the image file
        color_count: Number of colors to extract
        quality: Color extraction quality (1=highest, 10=fastest)

    Returns:
        List of RGB tuples, or empty list if extraction fails
    """
    try:
        from colorthief import ColorThief

        color_thief = ColorThief(str(image_path))
        return color_thief.get_palette(color_count=color_count, quality=quality)
    except Exception as e:
        _LOGGER.error("Failed to extract color palette from %s: %s", image_path, e)
        return []


def generate_gradient_path(
    colors: list[RGBColor],
    steps_between: int = 10,
) -> list[RGBColor]:
    """
    Generate a smooth gradient path between a list of colors.

    This creates intermediate colors between each pair of colors in the palette,
    resulting in a smooth color progression suitable for animation.

    Args:
        colors: List of RGB colors from palette extraction
        steps_between: Number of intermediate steps between each color pair

    Returns:
        List of RGB tuples representing the full gradient path
    """
    if len(colors) < 2:
        return colors

    gradient: list[RGBColor] = []

    for i in range(len(colors)):
        current_color = colors[i]
        next_color = colors[(i + 1) % len(colors)]  # Loop back to first color

        # Add intermediate steps
        for step in range(steps_between):
            t = step / steps_between
            r = int(current_color[0] + (next_color[0] - current_color[0]) * t)
            g = int(current_color[1] + (next_color[1] - current_color[1]) * t)
            b = int(current_color[2] + (next_color[2] - current_color[2]) * t)
            gradient.append((r, g, b))

    return gradient


def rgb_to_hs(rgb: RGBColor) -> tuple[float, float]:
    """
    Convert RGB to Hue/Saturation for Home Assistant light services.

    Home Assistant uses hs_color as (hue, saturation) where:
    - hue: 0-360 degrees
    - saturation: 0-100 percent

    Args:
        rgb: RGB tuple (0-255 for each channel)

    Returns:
        Tuple of (hue, saturation)
    """
    r, g, b = rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0
    max_c = max(r, g, b)
    min_c = min(r, g, b)
    diff = max_c - min_c

    # Calculate hue
    if diff == 0:
        hue = 0
    elif max_c == r:
        hue = (60 * ((g - b) / diff) + 360) % 360
    elif max_c == g:
        hue = (60 * ((b - r) / diff) + 120) % 360
    else:
        hue = (60 * ((r - g) / diff) + 240) % 360

    # Calculate saturation
    if max_c == 0:
        saturation = 0
    else:
        saturation = (diff / max_c) * 100

    return (hue, saturation)
