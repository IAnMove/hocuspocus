# Atmosphere sets

Procedural light and atmosphere for Video 3D. Geometry, noise, and textures are generated in code. No new models or image files belong in the repo. Character code stays as it is; a figure in the clearing only receives the set's light and shadow.

The passes join the composer that already exists in `cinematicRuntime.ts` (bloom, ACES, output). They turn on only when the document dressing is an atmosphere set.

## Set 1 — `atmos-clearing`

Templates: `atmos-clearing-wide`, `atmos-clearing-backlight`. Both use the establishment dolly. `atmosEye` cancels that dolly's extra rise so the move stays at eye height.

User-facing settings, parsed by `parseAtmosSettings`:

| Param | Values | Default |
| --- | --- | --- |
| `timeOfDay` | `dawn`, `morning`, `golden` | `golden` |
| `fogDensity` | 0–1 | 0.58 |
| `wind` | 0–1 | 0.46 |
| `motes` | 0–1 | 0.72 |
| `palette` | `green`, `autumn`, `blue` | `green` |

`previewFigure` is omitted unless it is `true`. It is for captures. The template does not ship a character mesh.

Passes, inserted after the scene render: shafts, depth of field, grade, then the existing bloom and output.

Depth of field is constructed and then left disabled. `sync` sets `dof.enabled` to false. The circle-of-confusion blur was smearing the ground, and reading the depth attachment of the buffer being written turned the frame black. Shafts are a radial luminance blur of the bright pixels. The shadow-map march runs only when export quality has enabled a 2048 shadow map. Preview grass is 4000 blades. Export grass is 24000.

Without WebGL2 the set degrades to a flat sky and ground color in `softwareRender.ts` and does not throw.

This clearing is a base. Shafts, dappled cobble shadows, and out-of-focus leaves at the frame edge still need another pass.

## What was measured

RTX 4090, headless Chromium, ANGLE, NVIDIA. 2026-09-29.

- 1920×1080 `frame()`, including the PNG readback: about 90–180 ms for the six stills.
- 1280×720, 5 s, 24 fps: 120 frames, H.264 file 3.6 MB.

The per-pass timers around shafts, depth of field, and grade read 0 or 0.1 ms. That is the resolution of `performance.now` here, not a pass budget. After `composer.render`, `renderer.info` only describes the last pass (one call, one triangle). Scene draw calls and a separate GPU-memory figure were not measured.

## Adding a set

1. Add the dressing id to the union in `types.ts` and to `DRESSINGS` in `documentSlot.ts`.
2. Mount the geometry from `dressing.ts`. Reuse `atmos/passes.ts` and `bindAtmosPasses`. Do not create a second composer.
3. Register the template id in `atmos/templateIds.ts` and `atmos/templates.ts`.
4. Give `softwareRender.ts` a flat fallback that does not throw.
5. Add the same keys to the English and Spanish `scene3dEditor` catalogs.

Leave pixel, action, and citadel dressings on their current path.
