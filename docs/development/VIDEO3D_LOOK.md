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
