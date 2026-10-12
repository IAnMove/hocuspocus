# Video 3D lighting and look

Phase 2.F1 of the local-quality roadmap (`docs/development/calidad-local/02-iluminacion-hdri-lut.md`): the contract for
environment lighting and the colour look. HDRI files (2.F2), LUT files (2.F3) and the Look panel (2.F4) build on it.

## Document fields

Both fields are optional and are parsed by `ui/src/features/scene3d/look.ts`:

```ts
lighting?: { environment: { source: 'room' | 'hdri' | 'none', asset?: string, intensity: 0..4,
                            rotation: degrees, background: 'set' | 'hdri' | 'blurred', blur: 0..1 } }
look?: { toneMapping: 'aces' | 'agx' | 'neutral', exposure: -4..4 EV, lut?: { asset: string, strength: 0..1 } }
```

- **Clamping.** Out-of-range numbers are clamped and the rotation is normalized to 0–360.
- **Dropping.** An unknown source or tone mapping drops the whole block. Asset URLs that are `blob:`, `file:`,
  `javascript:` or `filesystem:` are dropped.
- **Old scenes.** A scene saved without these fields renders exactly as before. That was measured on four scenes: frames
  byte-identical to `origin/development`.
- **New scenes.** Scenes created from `createDefaultScene3DDocument()` (every template starts there) get `NEW_SCENE_LIGHTING`
  (room environment, intensity 0.3) and `NEW_SCENE_LOOK` (ACES, −0.5 EV). This is the user's decision of 2026-10-03:
  only new scenes use the new lighting.

## Renderer

- **Environment light.** `EnvironmentLighting` (`environmentLighting.ts`) bakes three's `RoomEnvironment` once per renderer
  with `PMREMGenerator` and sets `scene.environment`, `environmentIntensity` and `environmentRotation`. Nothing is
  downloaded.
  - Pixel worlds keep their flat look and get no environment light.
  - Only scenes with a real model (a `model3d` slot with a source) bake and use it. Placeholder boxes, sets and
    effects-only scenes skip the bake.
    - **Why.** Each stage mount bakes its own PMREM, and with SwiftShader in CI that made the editor and world-effect
      E2E specs 1.5–2.2× slower.
    - **Result.** With the gate they run as fast as before: 2.8 / 6.4 / 3.6 s against 2.7 / 7.1 / 3.7 s on
      `development`. All 103 E2E tests pass.
  - Template thumbnails, which are placeholders in a shared background loop, render without lighting or look.
  - A scene with its own `look` sets tone mapping only in `applyLook`, so programs do not flip every frame.
  - `source: 'none'` or intensity 0 clears the environment.
  - Until 2.F2 loads files, `hdri` lights with the room. 2.F2 replaces that branch with `HDRLoader` → PMREM, plus the
    background modes.
- **Tone mapping and exposure.** `applyLook` sets `renderer.toneMapping` and `toneMappingExposure` (2^EV). It runs after
  `CinematicRuntime.sync`, so the look wins over the cinematic default. Without a `look`, the renderer keeps its previous
  behaviour: ACES on cinematic scenes, none otherwise.
- **Colour space.** `renderer.outputColorSpace` is now set explicitly to sRGB, the same as three's default.
- **LUT slot.** The composer has a `LUTPass` right after `OutputPass` (display-referred, where `.cube` LUTs belong) and
  before the pixel pass. It stays disabled until `CinematicRuntime.setLut(texture, strength)` receives a texture, and a
  disabled pass leaves the frame unchanged. For 2.F3:
  - load the `.cube` with `LUTCubeLoader`;
  - call `setLut`;
  - route scenes that have `look.lut` through the composer path.

  The composer targets are not multisampled in draft (see `VIDEO3D_EXPORT_QUALITY.md` once 1.F1 lands), so a LUT scene
  loses canvas antialiasing in draft unless that is addressed.

## Render looks

`renderLook` is a whole-frame preset, separate from `look`. The editor chooses it under **Render look**
(`RenderLookControls` in `CinematicControls.tsx`); agents set it with `world3d.scene.patch`, a production shot's
`scene3d.renderLook` or the document itself. Allowed values are in `SCENE3D_RENDER_LOOKS` (`types.ts`) and
`RENDER_LOOKS` (`app/services/world3d_look.py`); a test keeps the two lists equal. Any other value makes the document
invalid.

- **`n64`** (`n64Look.ts`): 240-pixel pixel pass, flat shading, nearest texture sampling and close fog.
- **`toon`** (`toonLook.ts`): cel shading and ink outlines on 3D model slots, so rigged or static GLB models sit next
  to flat cel cutouts and painted backgrounds.

```ts
renderLook?: 'n64' | 'toon'
toon?: { steps?: 2..4, outline?: 0..8, ink?: '#rrggbb' }   // defaults: 3 bands, 3 px, #141018
```

### Toon / cel

- **What changes.** Only meshes of `media: 'model3d'` slots. Image slots (walls, floors, backdrops, `surface: 'cutout'`
  with or without `imageLook.unlit`), screens, sets, the floor and effects keep their authored look.
- **Shading.** Standard, physical, Lambert and Phong materials are drawn with a `MeshToonMaterial`. It keeps `map`,
  `color`, `emissive`, `emissiveMap`, `alphaMap`, opacity and transparency, `side`, vertex colours, skinning and morph
  targets. Normal, roughness and metalness maps are dropped on purpose: cels are flat. A shared `DataTexture` gradient
  with `NearestFilter` gives `steps` hard bands; the darkest is 30 % light and the others are spaced evenly up to full
  light, so shadows are not black. Unlit (`MeshBasicMaterial`) GLB materials stay unlit.
- **Environment light.** `MeshToonMaterial` takes no environment map, so a scene lit mostly by `lighting.environment`
  would leave toon models dark. The toon copy adds the environment back as flat indirect light: π × 1.2 ×
  `scene.environmentIntensity`. 1.2 is the diffuse light a white surface gets from the generated room at intensity 1,
  measured on a sphere and a box from three sides. A white toon surface then gets about the light a white PBR surface
  gets from the room, without its direction. Metalness is ignored, so metallic Hunyuan3D textures keep their colour.
- **Models without normals.** Hunyuan3D GLBs have no `NORMAL` attribute. three flat-shades PBR, Lambert and Phong
  materials in that case, but not `MeshToonMaterial`: its normal would be zero and the light NaN. Without a FINITE
  pass (draft export), the bloom then spreads the NaN over the whole frame and the frame is black; with it (final),
  the models are black silhouettes. For the draw, such a geometry borrows the welded outline normals as `normal`,
  so the cel shading is smooth; they are removed again right after.
- **Ink.** An inverted hull: a second `Mesh`, or a `SkinnedMesh` bound to the same skeleton and bind matrix, shares the
  geometry and morph weights and is drawn back faces only in the ink colour. Its vertex shader pushes each vertex
  across the screen along a normal averaged over every face at that position, so hard edges and UV seams do not
  tear the line.
  - `outline` is the line width in pixels of a 1080-pixel-high frame, so a 720p preview and a 1080p or 4K export look
    the same. It does not depend on the model's scale, units or bones.
  - Lines keep their width up to 6 m from the camera and thin with distance beyond that, down to 35 % of the width.
  - The hull sits 0.15 % of its distance behind the surface, so it never covers a front face.
  - Hull faces turned more than about 127° away from the camera (cosine below −0.6) draw no ink. The line comes
    from faces near the silhouette; faces turned away only show through holes and open seams of scanned meshes, as
    black specks.
  - No ink on transparent materials with opacity below 1, alpha-tested or alpha-hashed materials (glass, hair cards)
    or materials with an `alphaMap`; a mesh with several materials hides only those groups. A model that is
    materializing (`slot.appearance`) gets ink only once it has fully arrived.
  - The tone mapping and fog of the frame apply to the ink.
- **Only while drawing.** `ToonLook.draw` swaps the toon materials and hulls in around the render call and puts the
  authored materials back right after it. Speech faces, materialization, picking (`transformGizmo`), bounds,
  grounding and shadow settings never see a toon material or a hull; a hull also ignores raycasts. The toon copy runs
  the authored material's shader patches (`onBeforeCompile` and its cache key), so speech mouths and the
  materialization effect still show. Runtime changes to the authored material (opacity, maps, `needsUpdate`) reach
  the next draw.
- **Cleanup.** Toon materials of meshes that are no longer drawn are disposed after the draw. Switching the look off
  disposes every toon material, the ink material and the gradient. The only thing left is the averaged normal
  attribute (`toonOutlineNormal`), stored once on each geometry and freed with it.
- **Preview and export.** `paintWorld` → `renderFrame` and the redraw in `renderWorld` both draw through `drawWorld`,
  in the plain path and in the `EffectComposer` path (bloom, LUT, pixel pass). The owned browser export renders the
  same stage, so an exported MP4 matches the editor. The software preview (`softwareRender.ts`, coloured boxes for
  agent previews) does not draw materials and is unchanged.
- **Not used.** three's `OutlineEffect` wraps `renderer.render` and does not fit the composer chain.

## Measurements (2026-10-03)

Real headless renders on GPU, 640×360:

- **Old documents** (clearing atmosphere, drive chase, a rigged pet, the pet with an environment): all frames
  byte-identical to `origin/development`.
- **Metallic sphere** (metallic 1, roughness 0.25), mean and standard deviation of luminance:

  | | Mean | Standard deviation |
  |---|---|---|
  | Without environment | 0.057 | 0.053 |
  | With the room at intensity 0.6 | 0.433 | 0.261 |

  Without an environment the sphere renders black; with the room it shows reflections.
- **Default tuning.** Four variants were compared on four models:
  - none (today);
  - ACES at 0.3 / −0.5 EV;
  - Neutral at 0.3 / −0.5 EV;
  - AgX at 0.3 / 0 EV.

  The models were a light Hunyuan pet, a box robot, a dark Hunyuan alien and the sphere. ACES at 0.3 / −0.5 EV keeps
  albedo colours and shading, adds fill and reflections, and does not wash out the floor (AgX did). At intensity 0.6 a
  light-albedo pet washed out.
