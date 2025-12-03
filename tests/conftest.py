"""Pytest fixtures for Chameleon tests."""

from __future__ import annotations

import sys
from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock

import pytest


# Mock homeassistant modules before any imports
def _setup_homeassistant_mocks():
    """Setup mock modules for homeassistant."""
    # Create mock modules
    mock_ha = MagicMock()
    mock_ha_core = MagicMock()
    mock_ha_const = MagicMock()
    mock_ha_components = MagicMock()
    mock_ha_components_light = MagicMock()
    mock_ha_config_entries = MagicMock()
    mock_ha_data_entry_flow = MagicMock()
    mock_ha_helpers = MagicMock()
    mock_ha_helpers_entity_platform = MagicMock()
    mock_ha_helpers_event = MagicMock()
    mock_ha_helpers_selector = MagicMock()
    mock_ha_helpers_cv = MagicMock()
    mock_ha_components_select = MagicMock()

    # Define ColorMode enum-like values
    class ColorMode:
        RGB = "rgb"
        RGBW = "rgbw"
        RGBWW = "rgbww"
        HS = "hs"
        XY = "xy"
        BRIGHTNESS = "brightness"
        ONOFF = "onoff"
        COLOR_TEMP = "color_temp"
        WHITE = "white"

    mock_ha_components_light.ColorMode = ColorMode
    mock_ha_components_light.ATTR_RGB_COLOR = "rgb_color"
    mock_ha_components_light.ATTR_TRANSITION = "transition"
    mock_ha_components_light.ATTR_SUPPORTED_COLOR_MODES = "supported_color_modes"

    # Define constants
    mock_ha_const.STATE_ON = "on"
    mock_ha_const.STATE_OFF = "off"
    mock_ha_const.STATE_UNAVAILABLE = "unavailable"
    mock_ha_const.STATE_UNKNOWN = "unknown"
    mock_ha_const.ATTR_ENTITY_ID = "entity_id"

    # Create State class
    class State:
        def __init__(self, entity_id, state, attributes=None):
            self.entity_id = entity_id
            self.state = state
            self.attributes = attributes or {}

    mock_ha_core.State = State
    mock_ha_core.HomeAssistant = MagicMock
    mock_ha_core.callback = lambda f: f  # Decorator that returns function unchanged

    # FlowResultType enum for config flows
    class FlowResultType:
        FORM = "form"
        CREATE_ENTRY = "create_entry"
        ABORT = "abort"
        EXTERNAL_STEP = "external_step"
        EXTERNAL_STEP_DONE = "external_step_done"
        SHOW_PROGRESS = "show_progress"
        SHOW_PROGRESS_DONE = "show_progress_done"

    mock_ha_data_entry_flow.FlowResultType = FlowResultType

    # ConfigFlow base class mock with metaclass support
    class ConfigFlowMeta(type):
        """Metaclass to support domain= keyword argument."""

        def __new__(mcs, name, bases, namespace, **kwargs):
            # Accept and ignore domain kwarg
            return super().__new__(mcs, name, bases, namespace)

    class ConfigFlow(metaclass=ConfigFlowMeta):
        """Mock ConfigFlow base class."""

        def __init__(self):
            self.hass = None
            self.context = {}

        async def async_set_unique_id(self, unique_id):
            pass

        def _abort_if_unique_id_configured(self):
            pass

        def async_create_entry(self, title, data):
            """Create a config entry."""
            return {
                "type": FlowResultType.CREATE_ENTRY,
                "title": title,
                "data": data,
            }

        def async_show_form(self, step_id, data_schema, errors=None):
            """Show a form."""
            return {
                "type": FlowResultType.FORM,
                "step_id": step_id,
                "data_schema": data_schema,
                "errors": errors or {},
            }

    # Also mock ConfigFlowResult as dict
    mock_ha_config_entries.ConfigFlowResult = dict
    mock_ha_config_entries.ConfigFlow = ConfigFlow
    mock_ha_config_entries.SOURCE_USER = "user"
    mock_ha_config_entries.ConfigEntry = MagicMock

    # SelectEntity mock
    class SelectEntity:
        """Mock SelectEntity base class."""

        _attr_has_entity_name = False
        _attr_translation_key = None
        _attr_unique_id = None
        entity_id = None
        hass = None

        async def async_added_to_hass(self):
            pass

        async def async_will_remove_from_hass(self):
            pass

        def async_write_ha_state(self):
            pass

    mock_ha_components_select.SelectEntity = SelectEntity

    # Selector classes (not mocks - need to be real classes with voluptuous support)
    class EntitySelectorConfig:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class EntitySelector:
        def __init__(self, config=None):
            self.config = config

        def __voluptuous_compile__(self, schema):
            """Support voluptuous schema compilation."""
            return lambda path, value: value

    class BooleanSelector:
        def __init__(self, config=None):
            self.config = config

        def __voluptuous_compile__(self, schema):
            """Support voluptuous schema compilation."""
            return lambda path, value: value

    class NumberSelectorConfig:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class NumberSelector:
        def __init__(self, config=None):
            self.config = config

        def __voluptuous_compile__(self, schema):
            """Support voluptuous schema compilation."""
            return lambda path, value: value

    class NumberSelectorMode:
        BOX = "box"
        SLIDER = "slider"

    mock_ha_helpers_selector.EntitySelector = EntitySelector
    mock_ha_helpers_selector.EntitySelectorConfig = EntitySelectorConfig
    mock_ha_helpers_selector.BooleanSelector = BooleanSelector
    mock_ha_helpers_selector.NumberSelector = NumberSelector
    mock_ha_helpers_selector.NumberSelectorConfig = NumberSelectorConfig
    mock_ha_helpers_selector.NumberSelectorMode = NumberSelectorMode

    # Config validation mocks
    mock_ha_helpers_cv.entity_ids = MagicMock
    mock_ha_helpers_cv.string = MagicMock

    # Setup module hierarchy
    sys.modules["homeassistant"] = mock_ha
    sys.modules["homeassistant.core"] = mock_ha_core
    sys.modules["homeassistant.const"] = mock_ha_const
    sys.modules["homeassistant.components"] = mock_ha_components
    sys.modules["homeassistant.components.light"] = mock_ha_components_light
    sys.modules["homeassistant.components.select"] = mock_ha_components_select
    sys.modules["homeassistant.config_entries"] = mock_ha_config_entries
    sys.modules["homeassistant.data_entry_flow"] = mock_ha_data_entry_flow
    sys.modules["homeassistant.helpers"] = mock_ha_helpers
    sys.modules["homeassistant.helpers.entity_platform"] = mock_ha_helpers_entity_platform
    sys.modules["homeassistant.helpers.event"] = mock_ha_helpers_event
    sys.modules["homeassistant.helpers.selector"] = mock_ha_helpers_selector
    sys.modules["homeassistant.helpers.config_validation"] = mock_ha_helpers_cv

    return ColorMode, State, FlowResultType


# Setup mocks at module load time
ColorMode, State, FlowResultType = _setup_homeassistant_mocks()


@pytest.fixture
def hass() -> Generator[MagicMock]:
    """Create a mock Home Assistant instance."""
    hass = MagicMock()
    hass.states = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()

    yield hass


@pytest.fixture
def mock_light_state() -> State:
    """Create a mock light state that supports RGB."""
    return State(
        entity_id="light.test_light",
        state="on",
        attributes={
            "supported_color_modes": [ColorMode.RGB, ColorMode.HS],
            "color_mode": ColorMode.RGB,
            "rgb_color": [255, 255, 255],
            "brightness": 255,
        },
    )


@pytest.fixture
def mock_light_state_unavailable() -> State:
    """Create a mock unavailable light state."""
    return State(
        entity_id="light.test_light",
        state="unavailable",
        attributes={},
    )


@pytest.fixture
def mock_light_state_no_rgb() -> State:
    """Create a mock light state without RGB support."""
    return State(
        entity_id="light.test_light",
        state="on",
        attributes={
            "supported_color_modes": [ColorMode.BRIGHTNESS],
            "color_mode": ColorMode.BRIGHTNESS,
            "brightness": 255,
        },
    )


@pytest.fixture
def mock_config_entry() -> MagicMock:
    """Create a mock config entry."""
    entry = MagicMock()
    entry.entry_id = "test_entry_id"
    entry.data = {
        "light_entities": ["light.test_light"],
        "animation_enabled": False,
        "animation_speed": 5,
    }
    return entry


@pytest.fixture
def sample_rgb_colors() -> list[tuple[int, int, int]]:
    """Sample RGB colors for testing."""
    return [
        (255, 0, 0),  # Red
        (0, 255, 0),  # Green
        (0, 0, 255),  # Blue
        (255, 255, 0),  # Yellow
        (255, 0, 255),  # Magenta
        (0, 255, 255),  # Cyan
    ]


@pytest.fixture
def mock_image_directory(tmp_path):
    """Create a temporary image directory with test images."""
    image_dir = tmp_path / "www" / "chameleon"
    image_dir.mkdir(parents=True)

    # Create dummy image files
    (image_dir / "sunset_vibes.jpg").write_bytes(b"fake image data")
    (image_dir / "ocean_blue.png").write_bytes(b"fake image data")
    (image_dir / "forest_morning.jpg").write_bytes(b"fake image data")

    return image_dir
