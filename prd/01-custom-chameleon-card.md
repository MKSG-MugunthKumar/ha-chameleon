# PRD: Custom Chameleon Lovelace Card

**Status**: Draft
**Author**: Claude + MK
**Created**: 2025-12-26
**Related**: [README.md Future Features](../README.md#custom-lovelace-card)

---

## Background

### Why a Custom Card?

Home Assistant's Tile Cards (evolved from Mushroom) work well for standard entities, but Chameleon has unique visualization needs:

1. **Image thumbnails** - Users want to see scene images, not just names
2. **Color palette visualization** - The `extracted_palette` attribute contains rich data
3. **Scene grid** - Visual selection beats dropdown for image-based scenes
4. **Integrated controls** - Brightness, speed, animation toggles in one cohesive UI

### Market Research

| Card                | Approach              | Limitation for Chameleon         |
| ------------------- | --------------------- | -------------------------------- |
| Tile Card           | Entity-focused, clean | No image support, no palette viz |
| Picture Entity Card | Shows images          | No multi-entity integration      |
| Custom Button Card  | Highly flexible       | Requires complex YAML per scene  |
| Bubble Card         | Mobile FAB style      | Pop-up based, not inline         |

**Conclusion**: A purpose-built card is the right approach.

---

## User Stories

### Primary

1. **As a user**, I want to see thumbnails of my scene images so I can visually pick the mood I want
2. **As a user**, I want to see the extracted color palette so I know what colors will be applied
3. **As a user**, I want quick access to brightness/animation controls without navigating away

### Secondary

1. **As a user**, I want to see which lights are controlled and their current colors
2. **As a user**, I want visual feedback when animation is running (subtle pulse/glow)
3. **As a user**, I want the card to match my HA theme (light/dark mode)

---

## Proposed Design

### Card Layout (Compact Mode)

```
┌─────────────────────────────────────────────┐
│  🎨 Chameleon                    [⟳] [⚙️]  │
├─────────────────────────────────────────────┤
│  ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐   │
│  │ img │ │ img │ │ img │ │ img │ │ ... │   │ ← Horizontal scroll
│  │     │ │     │ │     │ │     │ │     │   │
│  └─────┘ └─────┘ └─────┘ └─────┘ └─────┘   │
│   Beach   Dusk    Ocean   Forest   ...     │
├─────────────────────────────────────────────┤
│  Palette: [■][■][■][■][■][■][■][■]         │ ← extracted_palette
├─────────────────────────────────────────────┤
│  ☀️ ━━━━━━━━━●━━━━━━━ 75%                   │ ← Brightness slider
│  ⏱️ ━━━●━━━━━━━━━━━━━ 2.5s                  │ ← Speed slider
│  [▶️ Animation]  [🔄 Sync]                  │ ← Toggle chips
└─────────────────────────────────────────────┘
```

### Card Layout (Expanded/Grid Mode)

```
┌─────────────────────────────────────────────┐
│  🎨 Chameleon - Bedroom Lamp     [⟳] [⚙️]  │
├─────────────────────────────────────────────┤
│  ┌─────────┐ ┌─────────┐ ┌─────────┐       │
│  │         │ │         │ │  ████   │       │
│  │  Beach  │ │  Dusk   │ │ Forest  │ ← Selected
│  │ Sunset  │ │         │ │████████ │       │
│  └─────────┘ └─────────┘ └─────────┘       │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐       │
│  │         │ │         │ │         │       │
│  │  Ocean  │ │ Purple  │ │  Neon   │       │
│  │         │ │  Art    │ │         │       │
│  └─────────┘ └─────────┘ └─────────┘       │
├─────────────────────────────────────────────┤
│  Current Palette                            │
│  [██][██][██][██][██][██][██][██]           │
│   ↓    ↓    ↓                               │
│  💡1  💡2  💡3  (light assignments)         │
├─────────────────────────────────────────────┤
│  Brightness  ━━━━━━━━━●━━━━━━━  75%         │
│  Speed       ━━━●━━━━━━━━━━━━━  2.5s        │
│                                             │
│  [▶️ Animation ON]  [🔄 Sync ON]            │
└─────────────────────────────────────────────┘
```

---

## Technical Architecture

### Repository Structure

```
ha-chameleon-card/           # Separate repo
├── src/
│   ├── chameleon-card.ts    # Main card component
│   ├── editor.ts            # Card editor for UI config
│   ├── styles.ts            # CSS-in-JS styles
│   ├── types.ts             # TypeScript interfaces
│   └── utils.ts             # Helper functions
├── dist/
│   └── chameleon-card.js    # Built bundle
├── hacs.json                # HACS frontend config
├── package.json
├── rollup.config.js
└── README.md
```

### HACS Configuration

```json
{
  "name": "Chameleon Card",
  "render_readme": true,
  "homeassistant": "2024.1.0"
}
```

### Card Configuration Schema

```yaml
type: custom:chameleon-card
entity: select.bedroom_lamp_scene # Required: The Chameleon select entity
name: Bedroom Ambiance # Optional: Override title
layout: compact | grid # Optional: Default compact
show_controls: true # Optional: Show sliders/toggles
show_palette: true # Optional: Show extracted palette
columns: 3 # Optional: Grid columns (grid mode)
image_aspect_ratio: 1:1 | 16:9 | 4:3 # Optional: Thumbnail shape
```

### Entity Discovery

The card auto-discovers related entities from the select entity's `device_id`:

```typescript
// From select.bedroom_lamp_scene, find:
// - number.bedroom_lamp_brightness
// - number.bedroom_lamp_animation_speed
// - switch.bedroom_lamp_animation
// - switch.bedroom_lamp_sync_animation
// - button.bedroom_lamp_refresh_scenes
```

### Image URL Resolution

Images are accessible via HA's `/local/` path:

```typescript
// Scene name "Beach Sunset" → filename "beach_sunset.jpg" or "beach-sunset.jpg"
// URL: /local/chameleon/beach_sunset.jpg
const imageUrl = `/local/chameleon/${sceneName.toLowerCase().replace(/ /g, "_")}.jpg`;
```

**Challenge**: Need to handle various filename formats. Options:

1. Add `scene_images` attribute mapping scene names to filenames
2. Try multiple extensions (.jpg, .jpeg, .png)
3. Add image URL to each option's attributes (requires HA changes)

### State Attributes Used

```typescript
interface ChameleonSelectAttributes {
  light_entities: string[];
  light_count: number;
  applied_colors: Record<string, [number, number, number]>;
  extracted_palette: [number, number, number][];
  palette_count: number;
  last_scene_change: string; // ISO timestamp
  is_animating: boolean;
  animation_enabled: boolean;
  animation_speed: number;
  options: string[]; // Available scenes
}
```

---

## Implementation Phases

### Phase 1: MVP (v0.1.0)

- [ ] Basic card rendering with scene dropdown
- [ ] Palette visualization from `extracted_palette`
- [ ] Brightness slider integration
- [ ] Light/dark theme support
- [ ] HACS installation support

### Phase 2: Visual Selection (v0.2.0)

- [ ] Horizontal scroll scene thumbnails (compact mode)
- [ ] Grid layout option
- [ ] Image loading with fallback
- [ ] Scene name overlay on thumbnails

### Phase 3: Full Controls (v0.3.0)

- [ ] Animation speed slider
- [ ] Animation toggle chip
- [ ] Sync/staggered toggle chip
- [ ] Refresh button
- [ ] Animation running indicator

### Phase 4: Polish (v1.0.0)

- [ ] Card editor UI (no YAML needed)
- [ ] Responsive design
- [ ] Accessibility (keyboard nav, screen reader)
- [ ] Localization support
- [ ] Performance optimization (lazy image loading)

---

## Dependencies

| Dependency          | Purpose                               |
| ------------------- | ------------------------------------- |
| Lit 3.x             | Web component framework (HA standard) |
| TypeScript          | Type safety                           |
| Rollup              | Bundling                              |
| custom-card-helpers | HA integration utilities              |

---

## Open Questions

1. **Image mapping**: How to reliably map scene names to image filenames?

   - Option A: Exact match with underscore/hyphen normalization
   - Option B: Add `image_path` to select entity attributes
   - Option C: Store mapping in card config

2. **Multi-instance**: How should the card handle multiple Chameleon instances?

   - Show selector?
   - Require one card per instance?

3. **Offline images**: Should we cache/preload thumbnails?

4. **Animation preview**: Should tapping a scene show a color preview before applying?

---

## Success Metrics

- Card renders in < 100ms
- Image thumbnails load progressively
- Works on mobile (touch-friendly)
- Zero console errors
- HACS default install works first try

---

## References

- [HA Frontend Development Docs](https://developers.home-assistant.io/docs/frontend/)
- [Lit Web Components](https://lit.dev/)
- [Custom Card Tutorial](https://developers.home-assistant.io/docs/frontend/custom-ui/custom-card/)
- [Boilerplate Card](https://github.com/custom-cards/boilerplate-card)
- [HA Design System](https://design.home-assistant.io/)
