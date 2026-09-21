# Experimental MiniMax H3 30-second pass

Status: opt-in Studio flag, verified 2026-09-21 against
`ui/src/lib/h3ExtendedDuration.ts` and `app/models/minimax_h3/duration.py`.
This is not the published 15 s envelope and not a Series Lab planner change.

Related: [H3 implementation notes](H3_IMPLEMENTATION_NOTES.md),
[IMAGE / video commands](../minimax-h3-prompting.md),
[Series Lab](../series-lab/IMPLEMENTATION.md) (still 5 / 10 / 15 s shots).

---

## Intent

H3's VAE grid is `17*n+5` at 24 fps. The catalog `frames_maximum` stays
**345** (~15 s). Operators who explicitly check **Allow 30s clips** get one
legal pass of **719 frames (29.958 s)** without continuation windows.

The catalog JSON is never rewritten. The override is job-local.

---

## Contract

| Item | Value |
|---|---|
| Flag | `params.minimax_h3_extended_duration === true` |
| Default | `false` / omitted — 15 s catalog ceiling |
| Frames | `H3_EXPERIMENTAL_MAX_FRAMES = 719` |
| Seconds | `H3_EXPERIMENTAL_MAX_SECONDS = 30` (display); actual pass is 29.958 s |
| UI | Studio Video duration slider, only when `generationMode === 'video'` and the model is H3 |

`supportsH3ExtendedDuration` is true only when:

- architecture or `model_type` starts with `minimax_h3`
- not `audio_only`
- not `viggle_animate` / `minimax_h3_viggle`

Audio-only H3 and Viggle ignore the flag even if a client sends it.

Python `h3_duration_model_def` copies the model def and raises
`frames_maximum` plus `sliding_window_defaults.window_max` to 719.
`apply_h3_duration_override` also sets
`sliding_window_memory_override` and `minimax_h3_sequence_memory_override`
so Auto window sizing cannot silently shorten the experiment.

TypeScript `h3AlignmentOptions` must be the object passed to
`alignFrameCount`. Aligning 720 frames against the raw catalog options
still clamps to 345.

---

## Operator workflow

1. Direct generation → **Video**, MiniMax H3 selected.
2. Check **Allow 30s clips** (amber **Experimental**).
3. Drag duration to 30 s. The slider maximum becomes the 719-frame pass.
4. Generate. Admission still uses the existing video path; this flag only
   changes the job-local duration definition.

Unchecking the box restores the catalog 15 s ceiling. It does not rewrite
an already queued job.

---

## What this does not change

- Series Lab episode planning: shots remain 5, 10, or 15 seconds.
- Published model defaults in the catalog.
- Prompt policy, turbo modes, or reference-media duration limits.
- A quality or VRAM guarantee. The UI copy is explicit: more VRAM and
  time; motion or identity may drift.

---

## Pitfalls

- Inferring “H3 is 30 s now” from the checkbox existing. Off by default.
- Sending `minimax_h3_extended_duration: true` on Viggle / audio-only and
  expecting 719 frames. The helpers return the original def.
- Aligning frames with catalog `frames_maximum` after the user opted in.
  Submit must call `h3AlignmentOptions(options, true)`.
- Treating 719 frames as a sliding-window chain. It is one pass.

---

## Files to read next

| Path | Why |
|---|---|
| `app/models/minimax_h3/duration.py` | Job-local override |
| `ui/src/lib/h3ExtendedDuration.ts` | Browser ceiling and alignment |
| `ui/src/components/Sidebar/DurationSlider.tsx` | Opt-in checkbox |
| `ui/src/stores/studioConfigurationSlice.ts` | Slider max when enabled |
| `tests/test_h3_extended_duration.py` | Catalog bytes stay 345 |
| `ui/tests/h3ExtendedDuration.test.ts` | Submit does not inherit 15 s |
