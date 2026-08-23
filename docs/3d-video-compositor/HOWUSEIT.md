# HOWUSEIT — 3D Video compositor (Scene Animator)

Agent operations guide for Loreframe Lab’s programmatic compositor.

This document is **phase 1**. It explains how the existing tools work so an LLM can plan and assemble scenes. It does not add an “intention → finished clip” pipeline (phase 2) and it does not hook Story Lab / trailers / videoclips / series (phase 3).

UI tab: **3D Video** (`mediaFilter: scene3d`). Code: `ui/src/components/Sidebar/SceneAnimatorPanel.tsx`. Scene type: `ui/src/types/index.ts` (`Scene`, `SceneLayer`).

---

## 1. What this system is

A **layered compositor**, not MiniMax H3.

| Tool | Tab | Job |
|---|---|---|
| Hunyuan3D | **3D** gallery + sidebar Hunyuan3D Studio | Make a `.glb` mesh (text and/or photos) |
| Rig & Animate | **Animate** | Add a procedural skeleton + looping clips to a `.glb` |
| Scene Animator | **3D Video** | Stack images, videos, GLBs, camera, rain/fog/etc. Animate them. Record a clip |
| MiniMax H3 | Studio / Story Lab | Native video + stereo audio (acting, dialogue, locations) |
| Video Editor | **Video Editor** | Join compositor clips with H3 clips |

Use the compositor when you need **controllable motion of a known object** over plates: a ship crossing stars, a UFO rising behind mountains, a logo flying in, rain over a still. Use H3 when you need **performance, speech, or a living location**. Mix them: H3 for people/places, compositor for the vehicle insert, Video Editor to cut them together.

Do **not** ask H3 to “keep this exact GLB flying on a perfect path.” H3 will invent a new ship. The compositor keeps the mesh.

---

## 2. Hard limits (read before planning)

1. **Recording is browser-only.** There is no `POST /api/v1/scenes/render`. Record copies the live preview canvas (`MediaRecorder` → WebM download). The Scene Animator tab must be open, GLBs must be loaded in `model-viewer`, then the user (or a future browser driver) presses Record.
2. **Saving a scene to the gallery** (`POST /api/v1/scenes`) needs a PNG preview (`data:image/png;base64,...`). The UI paints one from the canvas. A headless agent cannot currently persist a scene without that preview.
3. **Hunyuan and H3 both use the GPU.** Do not start a 3D job while H3 is sampling. Wait for idle jobs.
4. **Transforms are 2.5D.** The ship moves on the frame (x/y %, scale, spin, orbit). It is not a 3D world with real depth. Parallax fakes depth. That is enough for Star Trek–style flybys.
5. **Recorded WebM is a local download**, not an automatic gallery output. Import it into Video Editor (or upload) to join with H3 MP4s.
6. **Coordinate space is percent of the frame.** `x: 50, y: 50` is centre. `x: -10` is off the left edge. `scale: 1` is “full layer size” (3D layers occupy ~52% × 75% of the frame at scale 1).

---

## 3. Coordinate and timing model

```
Scene
  width, height, fps (30 | 60), duration (seconds)
  layers[]  (z-order: lower z = further back)
    camera     — pan / zoom / roll / shake; applied to every visual layer
    image      — still plate (stars, mountains, title card)
    video      — moving plate (H3 sky, ocean, crowd)
    model3d    — Hunyuan / rigged GLB
    overlay    — extra 2D graphic
    effect     — procedural atmosphere (rain, fog, speedlines, …)
```

Layer transform (percent unless noted):

- `x`, `y`: 0–100 typical; values outside the frame are valid for fly-ins
- `scale`: 1 = default
- `opacity`: 0–1
- `rotation`: 2D degrees (images/video)
- `rotationX`, `rotationY`: model-viewer orbit in degrees (3D only; default start is often `rotationX: 75`)
- `parallax`: 0 = ignore camera pan (distant stars), 1 = normal, >1 = foreground
- `fill`: image/video cover the whole frame

Animation:

- `start` / `end` points (legacy two-keyframe)
- optional `keyframes[]` with `time` in **layer-local seconds**
- `duration`, `curve`: `linear` | `ease` | `dramatic` | `bounce`
- `offset`: scene time before local motion starts
- `speed`, `loop`, `trimStart`, `trimEnd`
- `spin` + `rotationSpeed` for turntables
- `orbit` around another layer (`targetLayerId`, `radiusX/Y`, `turns`, `facing`)
- `relationship`: `parent` | `follow` | `lookAt`
- rigged GLB: `clip`, `clipOffset`, `clipSpeed`, `clipLoop`

Camera shake lives on the **camera** layer: `animation.shake = { amount, frequency, seed }`.

---

## 4. UI map (human or agent driving the browser)

1. Generate or pick assets:
   - Images / Videos / Character Creator / Hunyuan3D / Animate
2. Open **3D Video**.
3. Add layers from generated outputs (picker) or upload.
4. Set scene size (match the H3 aspect if you will cut together: 16:9 e.g. 1280×720 or 960×544).
5. Assign motion presets (see §7).
6. Optional: camera preset + atmosphere.
7. **Save to Loreframe Lab** → writes `*.scene.json` + preview PNG (gallery tab **Scenes**).
8. **Record** → WebM download. Then import into **Video Editor** with H3 clips.

Motion JSON can be imported separately (2 MB max) via the panel’s movement loader.

---

## 5. Asset APIs (phase 1, fully scriptable)

Base URL: the running Lab (`http://127.0.0.1:<port>`). Workspace query: `?workspace=default` on file URLs; **never** put that query into probe/source filenames.

### 5.1 List outputs

`GET /api/v1/outputs?media_type=image|video|model3d|scene&limit=50`

3D files are `.glb`. Scenes are `*.scene.json`.

### 5.2 MiniMax H3 video (plates, people, locations)

`POST /api/v1/generate`

```json
{
  "prompt": "integrated_multimodal_description: [Shot 1] ...\n\noverall_soundscape: N/A\n\nnon_diegetic_music: N/A",
  "model_type": "minimax_h3_legacy",
  "resolution": "960x544",
  "video_length": 124,
  "num_inference_steps": 20,
  "guidance_scale": 1.0,
  "generation_mode": "video",
  "h3_reference_mode": "first_frame",
  "spoken_language": "Español de España"
}
```

H3 lattice: 17n+5 frames, min 124 (~5.17 s), max 345 (~14.4 s). Dialogue only as `<d>[Spanish] …</d>`. Mute shots: no `<d>`, plus closed-lips visual (compiler adds it). **Do not describe sound.**

Poll `GET /api/v1/status/{job_id}` until `completed`. Output name is in `output_files`.

### 5.3 Still plates (image models)

Same `POST /api/v1/generate` with `generation_mode: "image"` and an image `model_type` (production profile image, often Flux / MiniMax image). Use these as compositor backgrounds when you do not need H3 motion in the plate.

### 5.4 Hunyuan3D mesh

`GET /api/v1/model3d/capabilities` — check `installed`.

`POST /api/v1/model3d/generate`

Text-to-3D (ship, saucer, prop):

```json
{
  "operation": "generate",
  "preset": "balanced",
  "model_id": "hunyuan3d-2-turbo",
  "prompt": "A small classic flying saucer, metallic disc, three landing spheres, no people",
  "output_format": "glb"
}
```

Presets: `eco` (mini turbo, no texture), `balanced` (2-turbo + texture), `quality` (2.1 + PBR, heavy), `multiview` (needs photos).

Photo-to-3D (best identity). Character Creator already does: H3 orbit → stills at frames 2/21/42/63 → **hunyuan3d-2mv-turbo**. Direct API:

```json
{
  "operation": "generate",
  "preset": "multiview",
  "model_id": "hunyuan3d-2mv-turbo",
  "images": {
    "front": "front.png",
    "left": "left.png",
    "right": "right.png",
    "back": "back.png"
  }
}
```

Image values are workspace filenames, upload names, or `/api/v1/file/...` **without** `?workspace=` (the resolver strips it, but filenames are safer).

Poll `GET /api/v1/model3d/status/{job_id}`. Result `filename` is a `.glb`.

Retexture: `"operation": "retexture", "source_model": "existing.glb"`. Do not retexture a rigged GLB; retexture the static mesh, then rig.

### 5.5 Rig a ship / creature (optional)

`POST /api/v1/rig/generate`

```json
{
  "source": "my_saucer.glb",
  "engine": "procedural",
  "rig_profile": "vehicle",
  "animations": ["hover", "spin"]
}
```

Profiles: `prop`, `vehicle`, `humanoid`, `quadruped`, `flying`, `serpentine`. Engine: `procedural` (always) or `unirig` (if installed). Output is a new `*_rigged_*.glb`. In the compositor, set `animation.clip` to a baked clip name (`hover`, `spin`, …).

### 5.6 Upload a local file

`POST /api/v1/upload` multipart field `file`. Returns `{ filename, path, url }`.

### 5.7 Save a scene project (gallery)

`POST /api/v1/scenes`

```json
{
  "scene": { "version": 1, "name": "UFO flyby", "width": 1280, "height": 720, "fps": 30, "duration": 6, "layers": [ ] },
  "preview": "data:image/png;base64,...."
}
```

Returns `{ name, type: "scene", url, thumbnail_url }`. Appears in the **Scenes** tab. Opening it in the UI stages it into 3D Video.

Without a real PNG preview the endpoint rejects the body.

### 5.8 Video Editor (join plates)

Import H3 MP4s + recorded WebM. Multi-select in **From Loreframe Lab**. Export MP4. Mix concat uses a 0.5 s freeze + 0.4 s crossfade when there is no driving audio.

---

## 6. Layer cookbook (what to stack)

**Background (z low, parallax 0–0.35)**  
Stars, nebula, mountains, city night, ocean. Prefer a **still** if H3 would invent extra UFOs. Prefer an **H3 video** if you want living clouds/water and the ship is the only 3D object.

**Mid (parallax 1)**  
The hero GLB. Motion preset, optional spin. Keep scale modest so it reads as “out there.”

**Foreground (parallax 1.4–2, optional)**  
Vignette, cockpit frame, rain, speedlines. Makes the ship feel like it passes the camera.

**Camera**  
Locked for graphic flybys. Slow push-in for “credits roll.” Handheld only if the plate is live-action-ish.

**Atmosphere** (`type: "effect"`), kinds:

`rain`, `snow`, `dust`, `embers`, `fog`, `smoke`, `ash`, `fireflies`, `confetti`, `bokeh`, `sparkles`, `bubbles`, `speedlines`, `leaves`

Defaults live in `ATMOSPHERE_PRESETS` (density, speed, size, wind, color). Space flybys: `bokeh` or `speedlines`. Mountain reveal: `fog` or `rain`. Magic: `sparkles` / `fireflies`.

---

## 7. Motion presets (copy these ids)

Apply to a **model3d** (or overlay) layer. Numbers are start/end x,y,scale.

| id | Use |
|---|---|
| `space-cruise` | Slow left→right ship, slight rise. Star Trek establishing. |
| `meteor` | Fast diagonal fly-by. |
| `hero-flyover` | Big cinematic pass over the frame. |
| `pass-camera` | Object grows as it passes the lens. |
| `hover` | Bob in place (saucer over a town). |
| `landing` / `liftoff` | Vertical enter/exit. |
| `turntable` | Product spin (identity turnaround, not a shot). |
| `orbit-layer` | Circle another layer (needs `orbit.targetLayerId`). |
| `fade-reveal` | Opacity 0→1, good for titles. |
| `portal-arrival` | Scale pop-in. |
| `exit-frame` | Panic leave. |

Camera presets: `camera-locked`, `camera-pan-right`, `camera-pan-left`, `camera-push-in`, `camera-pull-out`, `camera-crane-up`, `camera-dutch-drift`, `camera-handheld`, `camera-whip-pan`, `camera-dolly`.

Photo (Ken Burns on a still): `photo-ken-burns-left`, `photo-documentary-push`, `photo-reveal-pullback`, …

Curves: `linear` for graphic space; `ease` for cinema; `dramatic` for action; `bounce` for cartoons/game.

---

## 8. Recipe: UFO behind mountains + H3 town + space cruise

Goal: three shots cut together.

**Shot A — H3 (town / people), ~8 s**  
MiniMax, 16:9, clay or live look as required. No UFO in the prompt (H3 will invent a bad one). Optional dialogue in `<d>`.

**Shot B — compositor (UFO rises behind ridge), ~6 s**

1. Image plate: mountain range, dusk, empty sky (image model or a still from H3 with no craft).
2. Hunyuan `balanced`: “classic 1950s flying saucer, brushed metal disc, no windows with faces, no people.”
3. Scene 1280×720, 30 fps, duration 6.
4. Layer `bg` image, `fill: true`, `parallax: 0.2`, `z: 0`.
5. Layer `ufo` model3d, start `{ x: 48, y: 62, scale: 0.12 }` (hidden behind ridge), end `{ x: 58, y: 28, scale: 0.42 }`, curve `ease`, `spin: true`, `rotationSpeed: 18`, `parallax: 1`, `z: 20`.
6. Layer `fog` effect, kind `fog`, `z: 10` (between mountains and craft if you want it in cloud).
7. Camera `camera-locked` or gentle `camera-push-in`.
8. Record WebM.

**Shot C — compositor (space cruise), ~5 s**

1. Plate: starfield still, or H3 “empty star field, no ships, no planets with faces.”
2. Reuse the same saucer GLB.
3. Preset `space-cruise` (start x 8 → end x 92).
4. Optional `bokeh` or `speedlines` overlay, parallax 1.6.
5. Camera locked. Record.

**Join**  
Video Editor: A (H3) → B (WebM) → C (WebM). Same 16:9.

Do not generate the saucer again in H3 for B/C.

---

## 9. Minimal scene JSON (agent-authored)

IDs must be unique strings. `source` for gallery files: `/api/v1/file/<filename>` (no query). Camera has empty `source`.

```json
{
  "version": 1,
  "name": "saucer-cruise",
  "width": 1280,
  "height": 720,
  "fps": 30,
  "duration": 5,
  "composition": { "showGrid": false, "gridSize": 10, "snap": false, "safeArea": "none" },
  "layers": [
    {
      "id": "cam",
      "name": "Camera",
      "type": "camera",
      "source": "",
      "visible": true,
      "z": 1000,
      "transform": { "x": 50, "y": 50, "scale": 1, "opacity": 1, "rotation": 0 },
      "animation": {
        "start": { "x": 50, "y": 50, "scale": 1, "rotation": 0 },
        "end": { "x": 50, "y": 50, "scale": 1, "rotation": 0 },
        "duration": 5,
        "curve": "linear"
      }
    },
    {
      "id": "stars",
      "name": "Starfield",
      "type": "image",
      "source": "/api/v1/file/starfield.png",
      "visible": true,
      "z": 0,
      "fill": true,
      "parallax": 0.15,
      "transform": { "x": 50, "y": 50, "scale": 1, "opacity": 1, "rotation": 0 },
      "animation": {
        "start": { "x": 50, "y": 50, "scale": 1, "opacity": 1 },
        "end": { "x": 50, "y": 50, "scale": 1.06, "opacity": 1 },
        "duration": 5,
        "curve": "linear"
      }
    },
    {
      "id": "saucer",
      "name": "Saucer",
      "type": "model3d",
      "source": "/api/v1/file/saucer.glb",
      "visible": true,
      "z": 20,
      "parallax": 1,
      "transform": { "x": 8, "y": 54, "scale": 0.48, "opacity": 1, "rotation": 0, "rotationX": 75, "rotationY": 0 },
      "animation": {
        "start": { "x": 8, "y": 54, "scale": 0.48, "opacity": 1 },
        "end": { "x": 92, "y": 43, "scale": 0.68, "opacity": 1 },
        "duration": 5,
        "curve": "ease",
        "spin": true,
        "rotationSpeed": 25
      }
    }
  ]
}
```

Open this in **3D Video** (import scene JSON). Assign missing assets if paths 404. Record.

---

## 10. Decision tree

```
Need spoken acting / a real location evolving?
  → MiniMax H3 (maybe several shots)

Need THIS exact object moving on a path (ship, UFO, logo, prop)?
  → Hunyuan GLB + Scene Animator
      Identity of a character as mesh?
        → Character Creator orbit → 4 stills → hunyuan3d-2mv-turbo
      Need hover/walk on the mesh itself?
        → Rig profile vehicle/flying/humanoid, then compositor clip

Need rain/fog/speedlines over a plate?
  → effect layer; do not prompt H3 for “cinematic rain” if you can composite it

Need both in one sequence?
  → H3 shots + compositor shots → Video Editor
```

---

## 11. Phase 2 / 3 (not built)

**Phase 2 — the page executes an LLM recipe and saves an MP4**

Do this **in the browser tab**, not as a Python overnight script. The canvas recorder already knows how to paint GLBs (it copies `model-viewer`’s canvas). A server-side 3D renderer is unnecessary.

1. **Recipe JSON** (LLM output only; no prose). Versioned object:
   - `assets[]`: `{ id, kind: image|video|model3d, prompt, model/preset }`
   - `scene`: width/height/fps/duration + layers that reference asset ids and a motion preset (`space-cruise`, …)
   - `record: true`
2. **Writer**: a small LLM call whose system prompt is this HOWUSEIT file + a JSON schema. User intent in, recipe out.
3. **Runner in 3D Video** (new “Run recipe” control):
   1. Create each asset with the existing generate / Hunyuan APIs. Poll until `completed`. Never run Hunyuan while H3 is sampling.
   2. Rewrite layer `source` to `/api/v1/file/<filename>`.
   3. `replaceScene(scene)` in Scene Animator and wait until each `model3d` layer has a paintable canvas.
   4. Call the existing `record()` path, but on `MediaRecorder.onstop` **upload** the blob (`POST /api/v1/upload`) instead of only downloading.
   5. Optional: transcode WebM → MP4 with the current FFmpeg lane, then `maybeRefreshGallery`.
   6. `POST /api/v1/scenes` with a PNG from `paintScene` so the project is in **Scenes**.
4. **Failure**: keep the partial scene + toast; do not jump tabs.

That is enough for “UFO behind mountains, then a space cruise”: two compositor records + one H3 town plate, then Video Editor.

**Phase 3 — optional compositor shots inside Story Lab / trailers / videoclips / series**  
Director marks some shots `tool: compositor` with a mesh + plate + preset. Only after phase 2 returns an MP4 into the gallery / `result_kind` pipeline.

Until then, agents follow this file **manually**: generate assets via API, tell the user the exact layer recipe, or import a scene JSON for them to record.

---

## 12. Files to read next

| Path | Why |
|---|---|
| `ui/src/types/index.ts` | `Scene` / `SceneLayer` schema |
| `ui/src/components/Sidebar/SceneAnimatorPanel.tsx` | Presets, atmosphere, record, save |
| `ui/src/lib/sceneTimeline.ts` | Evaluation of x/y/scale over time |
| `ui/src/lib/sceneFile.ts` | Export/import JSON |
| `app/services/model3d_service.py` | Hunyuan models and presets |
| `app/services/rig_service.py` | Rig profiles and clips |
| `docs/minimax-h3-prompting.md` | H3 prompt dialect |

When in doubt: **one identity per mesh, one path per compositor shot, H3 never draws that mesh.**
