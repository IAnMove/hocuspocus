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

Depth of field is constructed and then left disabled. `sync` sets `dof.enabled` to false. The circle-of-confusion blur was smearing the ground, and reading the depth attachment of the buffer being written turned the frame black. Shafts are a radial luminance blur of the bright pixels. The shadow-map march runs only when export quality has enabled a 2048 shadow map. Preview grass is 12000 blades. Export grass is 60000.

Without WebGL2 the set degrades to a flat sky and ground color in `softwareRender.ts` and does not throw.

### Look (stylised game forest)

The clearing is built in one flat-shaded, low-poly style so the geometry reads as a game world rather than a scan.

- Ground: a tileable painterly floor (`floorTexture` in `textures.ts`: moss, worn dirt, dark pockets and a few fallen leaves) over a 96 × 96 mesh with gentle mounds and low-frequency vertex tint, so the tile does not repeat visibly.
- Trunks (`forest.ts`): nine-sided, tapered, with a flared root base, a slight lean, moss climbing from the ground and a streaked bark texture. Each trunk has its own tint.
- Canopies: flat-shaded leaf clusters near each trunk top, all in one instanced draw call.
- Understory: bushes, flower tufts, red mushrooms at trunk bases, mossy rocks and a fallen log. `scatter` in `layout.ts` places them and never uses the subject's lane or a trunk's footprint.
- Grass: tapered blades in tufts of 18, denser toward the camera, each with its own tint. Preview 12,000 blades, export 60,000.

Materials use a small emissive term as fake bounce light, because the sun is a single spot and the trunks otherwise fall to black.

This clearing is a base. Shafts, dappled cobble shadows, and out-of-focus leaves at the frame edge still need another pass.

## What was measured

RTX 4090, headless Chromium, ANGLE, NVIDIA. 2026-09-29.

- 1920×1080 `frame()`, including the PNG readback: about 90–180 ms for the six stills.
- 1280×720, 5 s, 24 fps: 120 frames, H.264 file 3.6 MB.

The per-pass timers around shafts, depth of field, and grade read 0 or 0.1 ms. That is the resolution of `performance.now` here, not a pass budget. After `composer.render`, `renderer.info` only describes the last pass (one call, one triangle). Scene draw calls and a separate GPU-memory figure were not measured.

## Adding a set

A shipped set is one module plus the typed catalog:

1. Add `ui/src/features/scene3d/atmos/sets/<name>.ts`. Export an `AtmosSetDefinition`: palettes, times of day, defaults, subject, templates, `build`, and `fallback`.
2. Add the set id to `ATMOS_SET_IDS` and each template id to `ATMOS_TEMPLATE_IDS` in `atmos/registryIds.ts`. Those two lists are the typed catalog. `types.ts` cannot import the builder, because the builder imports three.js.
3. Add the set object to `ATMOS_SETS` in `atmos/registry.ts`. That one line is the runtime registry.
4. Add the title, and any new `atmos.day.*` or `atmos.swatch.*` labels, to the English and Spanish `scene3dEditor` catalogs.

Dressing mount, template documents, software fallback, and the gallery setting then follow the registry. Reuse `atmos/passes.ts`. Do not create a second composer. Depth of field stays off inside the clearing `sync`.

A unit test can call `installAtmosSet` with a small probe. That probe is recognized by dressing parse and template lookup, and it does not edit `registryIds.ts` or `ATMOS_SETS`. Remove it when the test ends. A probe is not a shipped set.

Leave pixel, action, and citadel dressings on their current path.
