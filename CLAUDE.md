# CLAUDE.md - Chameleon Integration

This file provides guidance to Claude Code when working with the Chameleon custom Home Assistant integration.
The project overview, the architecture is modular and follows best practices, and more information for how to develop is in README.md. Future planned features are in TODO.md.

## Code Style (Human and AI Alike)

When working on this project:

- Prioritize code quality and HA best practices
- Follow Home Assistant development guidelines
- Use async/await for all I/O operations
- Keep file structure clean and modular
- Document complex color extraction logic
- Use descriptive variable names
- Add type hints everywhere (Pylance Strict in Visual Studio Code)
- The precommit checks will fail if code style is not followed
- Use conventional commit messages (Again precommit checks will enforce this)
- Use `light_controller.py` for all light control operations
- Track errors in entity attributes for UI visibility
- Add comprehensive docstrings
