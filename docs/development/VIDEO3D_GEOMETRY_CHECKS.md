# Video 3D geometry checks

Phase 6.F2 of the local-quality roadmap (`docs/development/calidad-local/06-control-calidad.md`). Before the frames of a
server export, the render page samples the shot and reports geometry problems. **They only warn: nothing is blocked.**

## What is checked

The shot is sampled every 0.25 s (at most 240 samples, always including the end). At each sample the stage paints and
measures every loaded model in its current pose. Skinned meshes are measured skinned.

| Code | Severity | When |
|---|---|---|
| `below_floor` | fail | Part of a character is more than 2 % of its height under its ground. |
| `floating` | watch | A character stays more than 4 % of its height above its ground for 0.6 s or longer. A jump is shorter, so it is not reported. |
| `intersects` | watch | A character's box shares more than 25 % of the smaller box's volume with another model (a prop or another character). |
| `camera_inside` | fail | The camera is inside a model's box, shrunk by 5 %. |
| `out_of_frame` | watch | A character's box stays outside the camera frustum for 0.5 s or longer. |

- **Characters and props.** Characters are models with animations; models without them are props. Images and screens
  are not checked.
- **Which ground counts.** A grounded slot stands on its own height. A character placed between −1 m and +0.25 m is
  meant to stand on the world floor. One placed higher is taken as flying on purpose and its ground is not checked.
- **Results.** Consecutive flagged samples become `{code, severity, slot, other?, start, end, detail}` intervals. The
  verdict is the worst severity: `ok`, `watch` or `fail`.

## Where it shows

- **Server render.** `window.__world3dExport.checkGeometry()` runs after the snapshot loads and before any frame; the
  stage is a pure function of time, so the frames do not change (measured byte-identical). The worker writes
  `geometry.json`, the task metadata keeps it, and `scenes.world3d.export.receipt` returns it as `receipt.geometry`.
- **Browser.** A client can call `stage.geometrySample(t, doc)` and `checkGeometry(samples)` from
  `ui/src/features/scene3d/geometryChecks.ts`. The Video 3D editor button «Revisar geometría» samples the open shot,
  lists the same warnings, and jumps the playhead. It does not block export.
- **Receipt review (6.F4).** After a server export, Video 3D and Video 2D show “Review before you export”. The panel
  joins `receipt.qa` and `receipt.geometry`, lists fail ahead of watch, and jumps the playhead from a warning or from
  a marked contact-sheet cell. The sheet is eight times spread across the shot; each cell takes the worst warning
  that covers that time. A fail does not ask for confirmation and does not disable export.

## Measured (2026-10-03)

Real headless renders through `run_owned_browser`, on a rigged human and a box table, over a 2 s shot (9 samples):

| Scene | Report |
|---|---|
| Character standing, in view | `ok`, no warnings |
| Character placed 0.3 m under the floor | `fail`: `below_floor` from 0 to 2 s |
| Character overlapping the table | `watch`: `intersects` hero/table from 0 to 2 s |
| Camera inside the table | `fail`: `camera_inside` from 0 to 2 s |
| Character 6 m off to the side of a fixed camera | `watch`: `out_of_frame` from 0 to 2 s |

The frames of the standing scene are identical with and without the geometry pass (48 of 48).

## Limits

- **Boxes, not meshes.** Two characters standing close, with their arms out, can overlap as boxes. That is why
  `intersects` is only a `watch`.
- **Not measured.** Sets and atmosphere dressing are not checked; only loaded models are.
