# TODO - Chameleon Integration Roadmap

## Version 1.0 (Current)

### Pending

- [ ] **Brightness slider** - Adjust brightness directly from the Chameleon select entity UI
- [ ] **Animation toggle switch** - Enable/disable animation from the UI without reconfiguring
- [ ] **Synchronized animation option** - All lights change together
- [ ] Custom card for Lovelace
- [ ] Screenshots and demos for README
- [ ] Example images included in repo

---

## Future Features

### Media Player Integration

- [ ] **Album art color extraction** - Extract colors from media player's currently playing album cover
- [ ] **Media player selector** - Allow users to configure a media player entity as color source
- [ ] **Auto-update on track change** - Automatically update lights when song changes
- [ ] **Fallback to static scene** - Use configured scene when media player is idle/off

### Animation Features

- [ ] Animation patterns (fade, pulse, wave)
- [ ] Animation presets
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
