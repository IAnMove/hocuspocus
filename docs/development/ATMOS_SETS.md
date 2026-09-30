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

Export tuning (checked on a software export of `atmos-clearing-wide` with the TV-head humanoid in the open spot): the grass is trimmed around the character (`lawn`: 36 % height at the spot, full height from 2.8 m) so knees and feet stay in view, and the shadow-map scattering in the shaft pass is capped at 0.14 and fades in from 0.15 to 2.2 m above the surface. Uncapped, it lay a milky film over the ground and washed out the character.

Materials use a small emissive term as fake bounce light, because the sun is a single spot and the trunks otherwise fall to black.

This clearing is a base. Shafts, dappled cobble shadows, and out-of-focus leaves at the frame edge still need another pass.

## What was measured

RTX 4090, headless Chromium, ANGLE, NVIDIA. 2026-09-29.

- 1920×1080 `frame()`, including the PNG readback: about 90–180 ms for the six stills.
- 1280×720, 5 s, 24 fps: 120 frames, H.264 file 3.6 MB.

The per-pass timers around shafts, depth of field, and grade read 0 or 0.1 ms. That is the resolution of `performance.now` here, not a pass budget. After `composer.render`, `renderer.info` only describes the last pass (one call, one triangle). Scene draw calls and a separate GPU-memory figure were not measured.

## Capture

Review stills and clips stay outside the repository.

```
cd ui && npm run atmos:capture -- atmos-clearing-wide
cd ui && npm run atmos:capture -- atmos-clearing-wide --export --out /tmp/atmos-capture
```

The script builds the UI, serves it on `127.0.0.1` (port `HOCUSPOCUS_E2E_PORT`, default 4199), and opens Video 3D with the simulated API. It picks the template from the library, uses the shot, expands the video, and writes a 1920×1080 PNG. Chromium is launched with SwiftShader. If the WebGL renderer names NVIDIA, GeForce, Radeon, or AMD, the script stops.

`--export` records 6 seconds, or the template duration when that is shorter, at the document frame rate through the same `world3d-render.html` frame bridge the export service uses. Frames are muxed with ffmpeg into an MP4 in the output directory. The output directory defaults to `ATMOS_CAPTURE_DIR` or the system temporary directory, and it cannot sit inside the repo. This path does not call a running Lab, so it does not take the machine GPU.

A software export of `atmos-clearing-wide` produced 180 frames, 1280×720, 30 fps, 6.00 s, in 263915 ms. That is the editor document's size and frame rate. It is slower than the 60 s budget later sets are asked to meet at 1280×720 and 24 fps.

`--palette` and `--time` write those fields onto the open shot. `--subject FILE` places that GLB in the open character spot. The review stills for `atmos-waterfall` use this.

## Set 2 — `atmos-waterfall`

Templates: `atmos-waterfall-wide`, `atmos-waterfall-low`. Both last 6 seconds at 24 fps. The character spot is the same open circle as the clearing, on the near bank. The sheet, pool, mist and dew stay behind that circle.

| Param | Values | Default |
| --- | --- | --- |
| `timeOfDay` | `morning`, `golden` | `golden` |
| `palette` | `moss`, `amber` | `moss` |
| `variant` (`atmos.flow`) | 20–100 | 60 |

`golden` shows the rainbow. `morning` hides it. There is no grass field and no shaft, depth-of-field, or grade pass. Without WebGL2 the set is a flat bank. The library setting is `canyon`.

Look (same flat-shaded, low-poly style as the clearing; the pieces live in `sets/waterfallScenery.ts`, the placement in `sets/waterfallLayout.ts`):

- Rock: about 550 jittered boulders in one instanced draw call, stacked in columns along a wide ellipse. A cleft of 1.3 m either side of the falls is capped at the lip height; columns next to it sit further back so no rock crosses the water sheet. Colours come from strata bands, darker near the water, with moss on the tops.
- Water: the sheet is two layers of noise streaks with foam at the lip and at the base. The pool is an ellipse with ripples spreading from the fall point, churned foam, a foam rim and glints. Water stays blue-green in both palettes (`WATER` in the layout file).
- Ground: the painterly floor from the clearing over a 72 × 72 mesh, darker and bluer near the pool. The front edge of the pool stays 0.7 m short of the character spot; pool rocks skip the camera side.
- Plants: bushes and flower tufts on the banks (`addBushes` and `addFlowers` from `forest.ts`, given the bank areas), pines on the rim and the far banks. Ferns use the grass count as the number of bushes (18 preview, 36 export); dew uses the mote count (48 / 96).
- Rainbow: an additive arc in front of the falls at 20 % strength.

`waterfallLayout.ts` is pure, and `tests/atmosWaterfallLayout.test.mjs` checks it is deterministic, that no boulder crosses the sheet, and that the pool and pines stay clear of the character spot.

A software export of `atmos-waterfall-wide` (palette `amber`, time `morning`, 1280×720, 6 s) took 100 s on this machine, over the 60 s budget of the scenario plan. The earlier, simpler set took about 40 s. Most of the cost is fragment shading of the rock wall under SwiftShader.

## Set 3 — `atmos-moon`

Templates: `atmos-moon-wide`, `atmos-moon-low`. Both last 6 seconds at 24 fps. The character spot is the same open circle as the clearing. Craters, rocks, the lander and the footprints stay outside that circle and outside the lane to the camera.

| Param | Values | Default |
| --- | --- | --- |
| `timeOfDay` | `day`, `earthrise` | `day` |
| `palette` | `regolith`, `basalt` | `regolith` |
| `variant` (`atmos.prints`) | 8–40 | 18 |

`day` puts the Earth high and stretches the painted shadows. `earthrise` lowers the Earth toward the horizon and shortens the shadows. There is no grass field and no shaft, depth-of-field, or grade pass. Rocks use the grass count (10 preview, 18 export) and stars use the mote count (48 / 96). Fog stays near zero so the sky stays black. Without WebGL2 the set is a flat plain. The library setting is `moon`.

A software export of `atmos-moon-wide` produced 180 frames, 1280×720, 30 fps, 6.00 s, in 25340 ms. The mounted shot keeps the editor document's 1280×720 frame and 30 fps. That time is inside the 60 s budget.

## Set 4 — `atmos-mars`

Templates: `atmos-mars-wide`, `atmos-mars-low`. Both last 6 seconds at 24 fps. The character spot is the same open circle as the clearing. Rocks, dunes, the rover and the dust devils stay outside that circle and outside the lane to the camera.

| Param | Values | Default |
| --- | --- | --- |
| `timeOfDay` | `noon`, `dusk` | `noon` |
| `palette` | `rust`, `dusk` | `rust` |
| `variant` (`atmos.devils`) | 0–8 | 3 |

`noon` holds the two moons high. `dusk` lowers them and stretches the painted rover shadow. There is no grass field and no shaft, depth-of-field, or grade pass. Rocks use the grass count (8 preview, 14 export) and suspended dust uses the mote count (36 / 72). Without WebGL2 the set is a flat plain. The library setting is `desert`.

A software export of `atmos-mars-wide` produced 180 frames, 1280×720, 30 fps, 6.00 s, in 26733 ms. The mounted shot keeps the editor document's 1280×720 frame and 30 fps. That time is inside the 60 s budget.

## Set 5 — `atmos-snow`

Templates: `atmos-snow-wide`, `atmos-snow-low`. Both last 6 seconds at 24 fps. The character spot is the same open circle as the clearing. Pines, footprints and the cabin stay outside that circle and outside the lane to the camera.

| Param | Values | Default |
| --- | --- | --- |
| `timeOfDay` | `day`, `blue` | `blue` |
| `palette` | `frost`, `twilight` | `frost` |
| `variant` (`atmos.flakes`) | 0–80 | 36 |

`blue` shows the aurora and two falling flake layers. `day` hides the aurora. There is no grass field and no shaft, depth-of-field, or grade pass. Pines use the grass count (8 preview, 14 export) and the far flake layer is twice the near count. Without WebGL2 the set is a flat snowfield. The library setting is `snow`.

A software export of `atmos-snow-wide` produced 180 frames, 1280×720, 30 fps, 6.00 s, in 26927 ms. The mounted shot keeps the editor document's 1280×720 frame and 30 fps. That time is inside the 60 s budget.

## Set 6 — `atmos-desert`

Templates: `atmos-desert-wide`, `atmos-desert-low`. Both last 6 seconds at 24 fps. The character spot is the same open circle as the clearing. Dunes, palms, the pool and the ruins stay outside that circle and outside the lane to the camera.

| Param | Values | Default |
| --- | --- | --- |
| `timeOfDay` | `noon`, `dusk` | `noon` |
| `palette` | `sand`, `gold` | `sand` |
| `variant` (`atmos.ripples`) | 0–8 | 5 |

Wind ripples travel across the sand in one shader. The circle and the lane stay flat. `dusk` warms the sky. There is no grass field and no shaft, depth-of-field, or grade pass. Palms use the grass count (6 preview, 10 export). Without WebGL2 the set is a flat sand field. The library setting is `desert`, shared with the Martian set.

A software export of `atmos-desert-wide` produced 180 frames, 1280×720, 30 fps, 6.00 s, in 46529 ms. The mounted shot keeps the editor document's 1280×720 frame and 30 fps. That time is inside the 60 s budget.

## Set 7 — `atmos-beach`

Templates: `atmos-beach-wide`, `atmos-beach-low`. Both last 6 seconds at 24 fps. The character spot is the same open circle as the clearing. Palms, rocks, the boat and the gulls stay outside that circle and outside the lane to the camera. The water starts beyond the circle, on the far side of a wet-sand band.

| Param | Values | Default |
| --- | --- | --- |
| `timeOfDay` | `golden`, `dusk` | `golden` |
| `palette` | `amber`, `coral` | `amber` |
| `variant` (`atmos.tide`) | 0–8 | 5 |

Waves and foam travel in one shader. The sun sits low, and a bright streak runs from it across the water onto the wet sand. `dusk` drops the sun. There is no grass field and no shaft, depth-of-field, or grade pass. Palms use the grass count (4 preview, 6 export). Without WebGL2 the set is a flat sand field. The library setting is `sea`.

A software export of `atmos-beach-wide` produced 180 frames, 1280×720, 30 fps, 6.00 s, in 24922 ms. The mounted shot keeps the editor document's 1280×720 frame and 30 fps. That time is inside the 60 s budget.

## Set 8 — `atmos-crystal-cave`

Templates: `atmos-crystal-cave-wide`, `atmos-crystal-cave-low`. Both last 6 seconds at 24 fps. The character spot is the same open circle as the clearing. Crystals, rocks, drips and motes stay outside that circle and outside the lane to the camera. There is no sun.

| Param | Values | Default |
| --- | --- | --- |
| `timeOfDay` | `deep`, `glow` | `deep` |
| `palette` | `amethyst`, `aqua` | `amethyst` |
| `variant` (`atmos.glow`) | 0–8 | 5 |

Floor crystals point up and ceiling crystals point down from a stone roof. Their color brightens with the glow control, and drips fall on the same clock. `glow` lifts the sky behind that roof. There is no grass field and no shaft, depth-of-field, or grade pass. Crystal count uses the grass budget (8 preview, 12 export) and drips use the mote count. Without WebGL2 the set is a flat stone floor. The library setting is `cave`.

A software export of `atmos-crystal-cave-wide` produced 180 frames, 1280×720, 30 fps, 6.00 s, in 27732 ms. The mounted shot keeps the editor document's 1280×720 frame and 30 fps. That time is inside the 60 s budget.

## Set 9 — `atmos-meadow`

Templates: `atmos-meadow-wide`, `atmos-meadow-low`. Both last 6 seconds at 24 fps. The character spot is the same open circle as the clearing. Grass stays outside that circle and outside the lane to the camera. Low clouds drift above the figure. There is no sun.

| Param | Values | Default |
| --- | --- | --- |
| `timeOfDay` | `spring`, `overcast` | `spring` |
| `palette` | `clover`, `hay` | `clover` |
| `variant` (`atmos.breeze`) | 0–8 | 4 |

Wind leans the grass in the blade shader, and the same breeze slides the low clouds. Grass stays outside the open circle and the lane, and that circle is only a lighter patch so a figure is not buried. `overcast` greys the sky. There is no shaft, depth-of-field, or grade pass. Grass tufts use the grass count (100 preview, 140 export) and clouds use the mote count (8 / 12). Materials are unlit. Without WebGL2 the set is a flat green floor. The library setting is `forest`, shared with the clearing.

A software export of `atmos-meadow-wide` produced 180 frames, 1280×720, 30 fps, 6.00 s, in 27814 ms. The mounted shot keeps the editor document's 1280×720 frame and 30 fps. That time is inside the 60 s budget.

## Adding a set

A shipped set is one module plus the typed catalog:

1. Add `ui/src/features/scene3d/atmos/sets/<name>.ts`. Export an `AtmosSetDefinition`: palettes, times of day, defaults, subject, templates, `build`, and `fallback`.
2. Add the set id to `ATMOS_SET_IDS` and each template id to `ATMOS_TEMPLATE_IDS` in `atmos/registryIds.ts`. Those two lists are the typed catalog. `types.ts` cannot import the builder, because the builder imports three.js.
3. Add the set object to `ATMOS_SETS` in `atmos/registry.ts`. That one line is the runtime registry.
4. Add the title, and any new `atmos.day.*` or `atmos.swatch.*` labels, to the English and Spanish `scene3dEditor` catalogs.

Dressing mount, template documents, software fallback, and the gallery setting then follow the registry. Reuse `atmos/passes.ts`. Do not create a second composer. Depth of field stays off inside the clearing `sync`.

A unit test can call `installAtmosSet` with a small probe. That probe is recognized by dressing parse and template lookup, and it does not edit `registryIds.ts` or `ATMOS_SETS`. Remove it when the test ends. A probe is not a shipped set.

Leave pixel, action, and citadel dressings on their current path.
