# Video 3D export quality levels

Phase 1.F1 of the local-quality roadmap (`docs/development/calidad-local/01-render-master.md`).
The server export (`scenes.world3d.export`) takes an optional `quality`:

| Level | Supersampling | Composer MSAA | Motion blur | Encode |
|---|---|---|---|---|
| `draft` (default) | 1× | none | none | x264 `fast`, crf 18, 1 thread (unchanged) |
| `final` | 1.5× | 4× | 4 subframes, 180° shutter | x264 `slow`, crf 14 |
| `master` | 2× | 4× | 8 subframes, 180° shutter | x264 `slow`, crf 12 |

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

## Motion blur (1.F2)

- **Sampling.** Each output frame averages `subframes` renders taken while a film-style shutter is open. The shutter
  opens at the frame time and stays open for `shutter / 360` of a frame, and no subframe goes past the scene's end.
- **Averaging.** Subframes are averaged in linear light (sRGB to linear, then back through a 4096-step table), at the
  output size. Effects, texts and lyrics are painted once, after the average, so they stay sharp.
- **The `shutter` input.** It is optional, in degrees from 0 to 360, and only for `final` and `master`. It overrides the
  180° default, and 0 turns the blur off. Asking for a shutter with `draft` is refused.
- **Pixel worlds.** They stay sharp, because their art is drawn on a pixel grid.
- **Determinism.** Painting is a pure function of scene time: no random state, no frame deltas, and the light is reset
  on every paint. So subframes at fractional times are reproducible.

Measured on real headless renders (GPU, 640×360, 24 fps):

| Check | Result |
|---|---|
| Truly still scene (fixed orbit camera), `master`, blur against sharp | 0 LSB difference |
| Triangle moving 15.5 px per frame, `final` (4 subframes) | streak of 6 px, expected 5.8 (`(n−1)/n × 180/360 × 15.5`), +3 % |
| Same, `master` (8 subframes) | streak of 6 px, expected 6.8, −11.5 %; the faintest of the 8 subframes falls under the detection threshold |
| The same blurred frames rendered twice | byte-identical |

Time per frame at 1080p, blur included:

| Scene | Device | `draft` | `final` | `master` |
|---|---|---|---|---|
| Atmosphere clearing | GPU | 0.163 s | 0.296 s | 0.443 s |
| Pet with environment | GPU | 0.063 s | 0.159 s | 0.242 s |
| Pet with environment | CPU (SwiftShader) | 0.09 s | 0.58 s | 1.60 s |

A one-minute `master` export at 24 fps takes about 38 minutes on CPU, so the planned estimate before rendering (1.F5) is
needed.

## Voice on the server render (1.F5)

Voiced scenes now export on the server too. A voiced scene has audible speech clips, a soundtrack, or `sfx`/`worldSfx`
cues with sound.

- **Same audio as the browser.** After the frames, the owned page's `audio()` runs `mixSceneSpeech` on the frozen
  snapshot. That is the mixer the browser export uses, with the same playback speed and the same 180 s bound. The mix is
  returned as a WAV data URL (`sceneAudioWavDataUrl`, shared with Video 2D).
- **Muxing.** `finish_media` muxes `fx.wav` under the encoded video: AAC 192k, video copied, trimmed or padded to the
  plan's duration. It then validates the result with `validate_scene_recording_output(..., expected_audio=True)`.
- **No silent publish.** A voiced scene whose page produced no mix is not published as a silent MP4, and the page's
  error message (`audio-error.txt`) is reported.
- **Audio refs.** Voice and soundtrack files are frozen as `audio` refs (`audioId`, `filename`, `workspace` or
  `root`), with the same blocked-URL and existence checks as model refs. Admission answers `missing_ref` when a file is
  absent.
- **Limits.** `capabilities.maxVoicedDuration` is 180; longer voiced scenes are refused with `voiced_duration`.

Real headless render (GPU, 320×180, 24 fps, 2 s): a soundtrack at gain 0.3 plus a speech clip at 0.2 s.

| Check | `playbackSpeed: 1` | `playbackSpeed: 2` (4 s scene) |
|---|---|---|
| Streams | H.264 + AAC | H.264 + AAC |
| Duration (video / audio) | 2.000 / 2.000 s | 2.000 / 2.000 s |
| Frames | 48 | 48 |
| 50 ms RMS envelope against the sources (correlation, mean error) | 1.000, 0.0006 | 1.000, 0.0001 |

## Not in this phase

Owned by other phases of the roadmap:

- 4K output and the H.264 levels (1.F3);
- the optional ProRes master, remuxing valid uploads, and lossless editor intermediates (1.F4);
- the level picker and the time estimate in the UI (1.F5, Grok).
