# Video 3D export quality levels

Phase 1.F1 of the local-quality roadmap (`docs/development/calidad-local/01-render-master.md`).
The server export (`scenes.world3d.export`) takes an optional `quality`:

| Level | Supersampling | Composer MSAA | Encode |
|---|---|---|---|
| `draft` (default) | 1× | none | x264 `fast`, crf 18, 1 thread (unchanged) |
| `final` | 1.5× | 4× | x264 `slow`, crf 14 |
| `master` | 2× | 4× | x264 `slow`, crf 12 |

The output size never changes with the level.

- **Supersampling.** The stage paints at k× the output size. The owned renderer scales each frame down with
  `imageSmoothingQuality = 'high'`, then paints the overlays (effects, texts and lyrics) at the output size.
- **Antialiasing.** Composer render targets do not inherit the canvas `antialias`. Scenes with an environment, an atmosphere
  set or world effects used to lose antialiasing. Above draft, the composer targets are multisampled.
- **Finite-value guard.** A multisampled resolve can turn a very bright sample into NaN or Inf, and the bloom blur then
  spreads it over the frame (the atmosphere sets went black). Above draft, a guard pass sets non-finite values to 0 and caps
  others at 1024 before the bloom.
- **Bloom size.** The bloom keeps the output size, so its spread looks the same at every level.

## Compatibility

- **Draft is unchanged.** Its plan has no quality fields, so intents admitted earlier replay with the same fingerprint.
  Its frames are byte-identical to the renderer before levels existed (measured below).
- **Plan fields.** Final and master plans carry `quality`, `supersample` and `samples`. The page accepts up to 4×
  supersampling (for reference renders) and keeps the painted long side within 8192 px.
- **Reporting.** The task metadata, the projected receipt (`quality`), the sidecar and `capabilities.qualities` report the
  level.
- **Scope.** Video 2D and the browser export stay at draft.

## Measurements (2026-10-03)

**Method:**

- Real headless Chromium, through `run_owned_browser`.
- Output 640×360, 24 fps, frame 9 of 12.
- The reference is the same output size with 4× supersampling and MSAA.
- Edge error is the mean absolute RGB difference on pixels where the reference luminance gradient is above 0.25 (dilated
  by one pixel).

| Scene | Edge error `draft` → `final` → `master` | SSIM `draft` / `final` / `master` | Draft equals the old renderer |
|---|---|---|---|
| Atmosphere clearing (wide) | 0.0324 → 0.0138 (−57 %) → 0.0089 (−73 %) | 0.835 / 0.944 / 0.965 | yes |
| Drive chase | 0.0137 → 0.0088 (−36 %) → 0.0062 (−55 %) | 0.930 / 0.966 / 0.979 | yes |
| Rigged Hunyuan pet walking, no composer | 0.0112 → 0.0080 (−29 %) → 0.0040 (−65 %) | 0.999 / 0.999 / 1.000 | yes |
| Same pet with an environment (composer) | 0.0221 → 0.0097 (−56 %) → 0.0050 (−78 %) | 0.997 / 0.999 / 1.000 | yes |

Notes on the results:

- With the composer, draft's edge error is about twice the error without it. That confirms the lost antialiasing.
- The clearing set's per-pixel film grain differs at each internal resolution, which caps its SSIM.

Time per frame at 1080p:

| Scene | Device | `draft` | `final` | `master` |
|---|---|---|---|---|
| Atmosphere clearing | GPU | 0.163 s | 0.167 s | 0.171 s |
| Pet with environment | GPU | 0.059 s | 0.063 s | 0.067 s |
| Pet with environment | CPU (SwiftShader) | 0.10 s | 0.21 s | 0.27 s |

On the GPU, PNG transfer dominates.

## Not in this phase

Owned by other phases of the roadmap:

- motion blur (1.F2);
- 4K output and the H.264 levels (1.F3);
- the optional ProRes master, remuxing valid uploads, and lossless editor intermediates (1.F4);
- voiced scenes on the server render (1.F5);
- the level picker in the UI (1.F5).
