# HOWUSEIT — 3D Video compositor (Scene Animator)

Agent operations guide for HocusPocus’s programmatic compositor.

This document is the agent operations guide. The **3D Video** tab provides the Recipe runner (intent → JSON → assets → editable scene → MP4), template mounting and the selected-layer copilot. Story Lab / trailers / videoclips remain separate consumers.

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
| Character Kits | **3D Video** sidebar | Reusable 2D cutout puppets + Face Rig mouth overlays. Operator guide: [Character Kits](../character-kits/HOWUSEIT.md) |

Use the compositor when you need **controllable motion of a known object** over plates: a ship crossing stars, a UFO rising behind mountains, a logo flying in, rain over a still. Use H3 when you need **performance, speech, or a living location**. Mix them: H3 for people/places, compositor for the vehicle insert, Video Editor to cut them together. Use a **Character Kit** when the known object is a graphic puppet that must speak with mouth overlays—not a Hunyuan mesh and not H3 lip-sync.

Do **not** ask H3 to “keep this exact GLB flying on a perfect path.” H3 will invent a new ship. The compositor keeps the mesh.

---

## 2. Hard limits (read before planning)

1. **Frame rendering is browser-only.** There is no server-side scene renderer. Export samples the live compositor canvas in the browser; the Scene Animator tab must remain open and GLBs must be loaded in `model-viewer`.
2. **Saving a scene to the gallery** (`POST /api/v1/scenes`) needs a PNG preview (`data:image/png;base64,...`). The UI paints one from the canvas. A headless agent cannot currently persist a scene without that preview.
3. **Hunyuan and H3 both use the GPU.** Do not start a 3D job while H3 is sampling. Wait for idle jobs.
4. **Transforms are 2.5D.** The ship moves on the frame (x/y %, scale, spin, orbit). It is not a 3D world with real depth. Parallax fakes depth. That is enough for Star Trek–style flybys.
5. **Export produces an MP4 in Videos.** The browser capture is validated/transcoded by the Lab and its sidecar stores the exported Scene plus a recipe reconstructed from the final edited scene. Import that MP4 into Video Editor to join it with H3 clips.
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
7. **Save to HocusPocus** → writes `*.scene.json` + preview PNG (gallery tab **Scenes**).
8. **Export MP4** → validated H.264 MP4 in **Videos**. Then import it into **Video Editor** with H3 clips.

Motion JSON can be imported separately (2 MB max) via the panel’s movement loader.

---

## 5. Asset APIs (phase 1, fully scriptable)

Base URL: the running HocusPocus instance (`http://127.0.0.1:<port>`). The
legacy `workspace` query selects a physical output folder on file URLs;
**never** put that query into probe/source filenames. It is not a logical
Workspace collection selector.

### 5.1 List outputs

`GET /api/v1/outputs?media_type=image|video|model3d|scene&limit=50`

Assembled Director / Series joins also accept `result_kind=music_video|trailer|series_episode` (the Capítulos tab treats `chapter` as a match for `series_episode`). See [Video Editor / mixes](../video-editor/HOWUSEIT.md) §6.

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

H3 lattice: 17n+5 frames. The Recipe runner chooses 124 (~5.17 s), 243 (~10.1 s), or 362 (~15.1 s) from the longest shot that uses the plate. It also maps the compositor canvas to a validated H3 canvas: 16:9 → `960x544`, 9:16 → `544x960`, square → `736x736`. Dialogue only as `<d>[Spanish] …</d>`. Mute shots: no `<d>`, plus closed-lips visual (compiler adds it). **Do not describe sound.**

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

Photo-to-3D (best identity). The **Characters** tab (`mediaFilter: characters`) already does: optional MiniMax-M3 vision A Prompt → H3 Ref2VA orbit (personaje or objeto; one subject image is enough, max 9 refs) → stills at frames 2/21/42/63 → **hunyuan3d-2mv-turbo**. Orbit canvas is `768x1344`, 124 frames, 25 steps (4 if Turbo LoRA).

Vision A Prompt (hosted MiniMax-M3, not the local LLM; requires Settings → Services MiniMax key):

`POST /api/v1/characters/describe-refs`

```json
{
  "kind": "character",
  "image_paths": ["subject.png"],
  "roles": ["subject"],
  "workspace": "default"
}
```

`kind` is `character` or `object`. `roles` ∈ `subject` | `face` | `outfit` | `extra` | `accessory`. Response: `{ "a_prompt": "<Picture 1> - keep … Ignore …", "kind": "character" }`.

Direct Hunyuan API:

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

Image values are output-folder filenames, upload names, or `/api/v1/file/...`
**without** `?workspace=` (the resolver strips it, but filenames are safer).

In **Hunyuan3D Studio**, every reference slot offers both **Upload** (local disk) and **HocusPocus** (images already stored in the active output folder). The selected HocusPocus filename is sent with that output-folder token, so no duplicate upload is needed.

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

Import H3 MP4s + recorded WebM. Multi-select in **From HocusPocus**. Export MP4.

Director / Series **auto-joins** (not the editor) use a 0.5 s last-frame freeze + ~0.4 s crossfade when there is no driving audio. Full probe/export/`result_kind` contract: [Video Editor / mixes](../video-editor/HOWUSEIT.md).

### 5.9 Character Kits (2D puppets)

Character Kit library: `GET`, `PATCH`, and `DELETE`
`/api/v1/character-kits/library…`. Face Rig overlay cleanup:
`POST /api/v1/character-kits/face-rig/cleanup`. Both routes use the physical
output-folder token in their `workspace` field; it is not a logical Workspace
collection ID. Character Creator can hand a saved view into this editor via
`hocuspocus:character-kit-face-rig-handoff`, but it does not generate visemes.

Only **approved** poses and overlays mount into the scene or enter Recipe
inventory (`APPROVED_CHARACTER_KIT`). Spoken cutout dialogue is persisted as
`scene.dialogueBeats` and compiled into held/snap opacity keyframes; it is not
phoneme-perfect lip-sync. Read the full CAS, review, mouth-pack, and dialogue
contract in [Character Kits / Face Rig](../character-kits/HOWUSEIT.md).

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

## 10. Music rhythm → editable animation

The compositor can reuse the Music Video Director's real audio analyzer. It
extracts BPM, beat positions with normalized strength, heuristic downbeats,
an onset-energy envelope and coarse song sections from an attached MP3/WAV.

In **3D Video → Scene audio**:

1. Attach an existing song/audio output and set its scene start time.
2. Select the 3D object, image/overlay, video layer or camera that should react.
3. Under **Music rhythm → animation**, select the track and click
   **Analyze BPM and beats**.
4. Choose **Every beat** or **Downbeats only**.
5. Choose a reaction:
   - **Scale pulse** — preserves the current path and accents scale.
   - **Bounce** — adds a short vertical/scale hit.
   - **Peek on beat** — hides the object between beats and makes it appear on
     every hit (the direct “something peeks out on each beat” use case).
   - **Camera punch** — a deliberately restrained zoom accent.
6. Set intensity and click **Apply to _selected layer_**.

The audio track's `startTime` is applied to the beat grid before keyframes are
created. Existing layer motion is sampled and baked together with the reaction
into ordinary `SceneKeyframe` records, so preview, timeline edits, save/import
and MP4 capture all use the same deterministic path. Applying rhythm is an
authoring operation: use Undo if you want the previous transform timeline.

Long/high-BPM inputs are capped to a safe number of cues. Downbeats are a
four-beat heuristic anchored to strong beats, not a full meter classifier yet.
The analyzer already returns onset energy and song sections; mapping those to
continuous effect density, lighting and section-level choreography is the next
stage, not silently inferred by this first control.

---

## 11. Decision tree

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

## 12. Phase 2 / 3

**Phase 2 — built in the 3D Video tab (Recipe runner)**

Do this **in the browser tab**, not as a Python overnight script. UI: `SceneRecipePanel`. Code: `ui/src/lib/sceneRecipe.ts`, `ui/src/lib/sceneRecipeAssets.ts`.

1. **Interpretation contract**: the selected LLM receives a closed JSON Schema plus a multilingual virtual-production guide. It silently separates subjects, setting, chronological beats, format, camera and atmosphere; generation prompts are written in concise cinematic English while proper names and quoted dialogue are preserved.
2. **Validation and repair**: local llama-server output is grammar-constrained. Other providers receive the exact schema in context. HocusPocus then validates unique ids, asset/layer compatibility, supported presets, rig clips and references; one malformed response gets a bounded correction pass before any GPU job starts.
3. **Manual**: pick GLBs/plates already in Outputs, **Write recipe**, **Compose**. Output sidecar prompts and embedded clip names are passed to the LLM as untrusted inventory descriptions, so it can understand assets whose filenames are vague. A requested rig profile is applied even to a manually loaded static GLB. Edit the inspector, then Record.
4. **Auto**: **Generate + compose** creates missing plates/meshes. One `identity` per object — a UFO series uses **one** GLB and several `shots[]`. Static environments use image plates; inherently moving scenery can use an H3 video plate. Rain, fog, snow and particles use procedural effects instead of redundant generated overlays. Default `record`/`save` are false so you preview first.
5. GPU jobs and Hunyuan poll with timeouts; **Cancel** aborts the run. If Lab dies (segfault), the runner errors instead of spinning forever.
6. After compose, switch shots in the recipe panel without regenerating the mesh. A recipe rig `clip` is mounted into the Scene Animator and disables unintended turntable spin.
7. Approved Character Kits enter inventory as `APPROVED_CHARACTER_KIT` rows. Spoken cutout shots need a `speech` audio entry and a top-level `dialogueBeats` row whose `mouthLayerIds` name the overlays. Keep body and face pieces from the same kit ID.

Keep the 3D Video tab visible while it records. Browser capture is validated
and published as H.264 MP4; import that output in Video Editor to join it with
H3 clips.

**Phase 3 — not built.** Director marks some shots `tool: compositor` inside Story Lab / trailers / videoclips / series only after phase 2 clips are in the gallery.

---

## 13. Files to read next

| Path | Why |
|---|---|
| `ui/src/types/index.ts` | `Scene` / `SceneLayer` schema |
| `ui/src/components/Sidebar/SceneAnimatorPanel.tsx` | Presets, atmosphere, record, save |
| `ui/src/lib/sceneTimeline.ts` | Evaluation of x/y/scale over time |
| `ui/src/lib/sceneRhythm.ts` | Beat/downbeat map and deterministic rhythm keyframes |
| `ui/src/lib/sceneFile.ts` | Export/import JSON |
| `app/services/audio_analysis.py` | Librosa BPM, beats, downbeats, onset envelope and sections |
| `app/services/model3d_service.py` | Hunyuan models and presets |
| `app/services/rig_service.py` | Rig profiles and clips |
| `docs/minimax-h3-prompting.md` | H3 prompt dialect |
| `docs/video-editor/HOWUSEIT.md` | Cut compositor WebM with H3 MP4s; mix kinds |
| `docs/character-kits/HOWUSEIT.md` | Character Kit library, Face Rig, and cutout dialogue |
| `ui/src/features/characters/orbitPrompt.ts` | Orbit A/B prompts and still-frame indices |

When in doubt: **one identity per mesh, one path per compositor shot, H3 never draws that mesh.**
