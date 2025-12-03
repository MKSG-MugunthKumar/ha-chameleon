# Contributing to Chameleon

Thank you for your interest in contributing to Chameleon! This document provides guidelines and instructions for contributing.

## Development Setup

### Prerequisites

- Python 3.13+
- [uv](https://github.com/astral-sh/uv) (recommended) or pip

### Getting Started

1. Fork and clone the repository:

   ```bash
   git clone https://github.com/YOUR_USERNAME/ha-chameleon.git
   cd ha-chameleon
   ```

2. Create a virtual environment and install dependencies:

   ```bash
   uv venv
   source .venv/bin/activate
   uv pip install -e ".[dev,test]"
   ```

3. Install pre-commit hooks (optional but recommended):

   ```bash
   pre-commit install
   ```

## Code Quality

Before submitting a pull request, ensure your code passes all checks:

```bash
make check
```

This runs:

- **Ruff** - Linting and formatting
- **ty** - Type checking
- **pytest** - Unit tests

### Individual Commands

```bash
make lint      # Run ruff linter
make format    # Format code with ruff
make typecheck # Run ty type checker
make test      # Run tests with coverage
```

## Pull Request Process

1. **Create a feature branch** from `main`:

   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes** following the code style guidelines below

3. **Add tests** for new functionality

4. **Run checks** before committing:

   ```bash
   make check
   ```

5. **Commit with a descriptive message**:

   ```bash
   git commit -m "Add feature: brief description"
   ```

6. **Push and create a pull request**

## Code Style

- Follow [Home Assistant development guidelines](https://developers.home-assistant.io/docs/development_guidelines)
- Use type hints for all function signatures
- Use async/await for all I/O operations
- Keep functions focused and small
- Add docstrings for public functions and classes

### Example

```python
async def extract_colors(
    hass: HomeAssistant,
    image_path: Path,
    count: int = 5,
) -> list[tuple[int, int, int]]:
    """Extract dominant colors from an image.

    Args:
        hass: Home Assistant instance.
        image_path: Path to the image file.
        count: Number of colors to extract.

    Returns:
        List of RGB tuples.
    """
    ...
```

## Translations

We welcome translations to make Chameleon accessible to more users!

### Adding a New Language

1. Copy the English translation file:

   ```bash
   cp custom_components/chameleon/translations/en.json \
      custom_components/chameleon/translations/YOUR_LANG_CODE.json
   ```

   Use [ISO 639-1 language codes](https://en.wikipedia.org/wiki/List_of_ISO_639-1_codes) (e.g., `de`, `fr`, `es`, `zh`).

2. Translate the strings in the new file

3. Also update `custom_components/chameleon/strings.json` if adding a widely-used language

4. Submit a pull request with your translation

### Translation Files Structure

```
custom_components/chameleon/
├── strings.json              # Default strings (English)
└── translations/
    ├── en.json               # English
    ├── de.json               # German (example)
    └── ...
```

### What to Translate

- Config flow titles and descriptions
- Entity names and state descriptions
- Error messages

### What NOT to Translate

- Entity IDs
- Service names
- Technical identifiers

## Testing

### Running Tests

```bash
# Run all tests with coverage
make test

# Run tests without coverage (faster)
make test-quick

# Run specific test file
pytest tests/test_light_controller.py -v

# Run specific test
pytest tests/test_light_controller.py::TestLightController::test_init -v
```

### Writing Tests

- Place tests in the `tests/` directory
- Mirror the source structure (e.g., `test_light_controller.py` for `light_controller.py`)
- Use pytest fixtures from `conftest.py`
- Mock Home Assistant dependencies

## Development Server

For testing with a real Home Assistant instance:

```bash
# Start development server (Docker)
make dev-start

# View logs
make dev-logs

# Stop server
make dev-stop
```

## Reporting Issues

When reporting bugs, please include:

1. Home Assistant version
2. Chameleon version
3. Relevant log entries (enable debug logging)
4. Steps to reproduce
5. Expected vs actual behavior

Enable debug logging:

```yaml
logger:
  logs:
    custom_components.chameleon: debug
```

## Feature Requests

Feature requests are welcome! Please:

1. Check existing issues first
2. Describe the use case
3. Explain the expected behavior
4. Consider if it fits the project scope

## Questions?

- Open a [GitHub Discussion](https://github.com/MKSG-MugunthKumar/ha-chameleon/discussions)
- Check existing issues and discussions

Thank you for contributing!
