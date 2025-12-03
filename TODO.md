# TODO - Chameleon Integration Roadmap

## Version 1.0 (Current)

### Pending

- [ ] **Brightness slider** - Adjust brightness directly from the Chameleon select entity UI
- [ ] **Animation toggle switch** - Enable/disable animation from the UI without reconfiguring
- [ ] Screenshots and demos for README
- [ ] Example images included in repo
- [ ] Translations for multiple languages
- [ ] Custom card for Lovelace

### Completed

- [x] Project structure
- [x] Manifest and basic setup
- [x] Config flow for multi-light selection
- [x] Select entity creation
- [x] Image directory scanning (with caching)
- [x] Color extraction (dominant + palette)
- [x] Apply color to lights (n colors for n lights)
- [x] LightController for shared logic
- [x] Error tracking in entity attributes
- [x] Light availability checks
- [x] HACS metadata (hacs.json)
- [x] README with setup instructions
- [x] Developer documentation
- [x] Basic unit tests
- [x] Animation infrastructure (AnimationController, AnimationManager)
- [x] Gradient path generation for smooth animation
- [x] Animation services registered
- [x] Animation toggle wired to select entity

---

## Future Features

### Media Player Integration

- [ ] **Album art color extraction** - Extract colors from media player's currently playing album cover
- [ ] **Media player selector** - Allow users to configure a media player entity as color source
- [ ] **Auto-update on track change** - Automatically update lights when song changes
- [ ] **Fallback to static scene** - Use configured scene when media player is idle/off

### Animation Features

- [ ] Synchronized animation option (all lights change together)
- [ ] Animation patterns (fade, pulse, wave)
- [ ] Animation presets

### Advanced Features

- [ ] Color temperature support (for white/CT lights)
- [ ] Scene presets with multiple images
- [ ] Time-based scene selection
- [ ] Integration with HA scenes

### Alternative Color Extraction Libraries

- [ ] **Haishoku** - Python library, alternative to ColorThief
- [ ] **K-means clustering** - Custom implementation using scikit-learn or numpy
- [ ] **Configurable extractor** - Allow users to choose extraction method

### Spatial Sampling (Experimental)

- [ ] **Grid-based region sampling** - Sample colors from different image regions
- [ ] **Left/center/right distribution** - Assign region colors to lights by position
- [ ] **Custom region mapping** - User-defined light-to-region assignments

---
