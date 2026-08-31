# HOWUSEIT — Character Kits and Face Rig

Operator guide for reusable **2D cutout puppets**: one reviewed body/pose, mouth visemes, an optional blink, and pose-local face anchors. This is not Character Creator’s Hunyuan turntable and not MiniMax H3 lip-sync.

UI: **3D Video** sidebar (`SceneAnimatorPanel` → Character Kits). Code: `ui/src/lib/characterKit.ts`, `ui/src/lib/characterKitFaceRig.ts`, `ui/src/lib/cutoutDialogue.ts`. Persistence: `app/services/character_kit_library.py`. Cleanup: `POST /api/v1/character-kits/face-rig/cleanup`. HTTP: `app/_launch_runtime.py`.

Related: [3D Video compositor](../3d-video-compositor/HOWUSEIT.md), [Character Creator orbit](../3d-video-compositor/HOWUSEIT.md) §5.4.

---

## 1. What this system is

| Tool | Tab | Job |
|---|---|---|
| Character Creator | **Characters** | Identity photo → H3 360° orbit → Hunyuan multi-view **mesh** |
| Character Kit library | **3D Video** | Workspace-scoped 2D puppet (base pose + mouths + blink) |
| Face Rig | **3D Video** → Paso 2 · Labios / ojos | Generate, clean, place, and review overlays |
| Cutout dialogue | **3D Video** | Held/snap mouth keyframes from known text or speech |
| Recipe runner | **3D Video** | Compiles `dialogueBeats` and only **approved** kit pieces |

Use a kit when you need a **repeatable graphic character** that can speak with four mouth sprites. Use Character Creator when you need a **3D mesh**. Use H3 when you need a **performed** face, not a paper flap.

The compositor never claims phoneme-perfect lipsync. Cadence is bounded and graphic.

---

## 2. Hard limits

1. **Library file** is `{workspace}/.character-kit-library-v1.json`. Max **100** kits, **32** poses, **20 MB** encoded JSON, **500** provenance objects per kit.
2. **Compare-and-swap.** Every write sends `baseRevision`. Stale clients get `409` `{ "code": "character_kit_revision_conflict", "expectedRevision", "currentRevision" }`. Reload the library; do not retry the same revision.
3. **No blob/data URLs.** Sources must be persistent (`/api/v1/file/…`, `/api/v1/uploads/…`, or a workspace filename). Face Rig handoff from Character Creator also rejects transient images.
4. **Only `approved` pieces mount or enter the recipe inventory.** Generated Face Rig states start as `pending`. Cleanup does not approve. Mouth-pack apply does not approve.
5. **Mouth states** are only `closed` | `small` | `wide` | `round`. Eyes are `open` | `blink` (`open` is unused by the current compiler). Unknown keys `400`.
6. **Anchors are pose-local**, not 16:9 frame percents. Default mouth `{ offsetX: 0, offsetY: -18, scale: 0.05 }`. Default blink `{ offsetX: 0, offsetY: -28, scale: 0.12 }`. Bounds: offset ±200, scale 0.001–20, rotation ±360.
7. **Workspace token** is `default` or `[A-Za-z0-9][A-Za-z0-9_-]*`. Kits follow the output-directory workspace, not the Workspaces *tab*.
8. **`lookNotes` is not persisted.** The UI keeps style/traits for the current editor session. `normalize_character_kit` drops unknown fields, including `lookNotes`. After reload, re-enter style + traits before regenerating overlays.
9. **Deleting a kit does not delete files.** Pose PNGs, cleaned overlays, and scene layers stay on disk.

---

## 3. Data model

```
CharacterKitLibrary { version: 1, revision, activeId, kits{} }

CharacterKit
  id, name, style: cutout | children-illustration | anime-2d
  identityReference?, base?, poses{}
  mouth { closed?, small?, wide?, round? }
  eyes { blink? }
  anchors { [poseId]: { mouth, mouthStates?, eyes? } }
  provenance[]
```

Each asset: `{ id, name, source, kind: image|overlay, alphaStatus, reviewState, prompt?, model?, workspace? }`.

`alphaStatus`: `unknown` | `transparent` | `opaque`. Transparent if ≥1% of pixels have alpha < 250.

Mount (`mountCharacterKitLayers`) parents each approved overlay to the pose, sets `faceBinding`, and starts with closed mouth visible. Re-mounting the same kit pose ids into a scene that already has them fails.

Recipe inventory flattens only approved pieces. The **active** kit is ordered first so a large workspace does not evict its complete face set under the global inventory cap.

---

## 4. Operator workflow

### 4.1 From Character Creator

1. Stay on **character** (not object). Capture a turnaround view or upload the subject.
2. **Create / open CharacterKit Face Rig** writes `sessionStorage` key `hocuspocus:character-kit-face-rig-handoff` and switches to **3D Video**.
3. If a kit already uses that source as `base` or `identityReference`, the editor reopens it. Otherwise it drafts a new kit with the pose **already approved**.

Character Creator itself does not generate visemes. Error if kind is `object`: *Face Rig is for Character Kits.*

### 4.2 From a compositor layer

1. Open **3D Video**. Add a full-body cutout (generated image or transparent PNG).
2. **New kit from selected base layer**, or assign **Selected → base / pose / mouth / blink**.
3. Review alpha (transparent vs opaque). Approve the pose before Face Rig generation.
4. **Paso 2 · Labios / ojos**: style chips + traits → generate pose (if needed) or generate each viseme. Optional: apply a mouth pack, **Clean**, place, **Lock all mouths**, then approve.
5. **Save kit** (PATCH). **Mount pose** into the current scene.

### 4.3 Face Rig generation

Prompts are built in `characterKitPosePrompt` / `faceRigPrompt`. The user only supplies style and traits; the helper asks for an isolated transparent overlay (or a full-body standing cutout for the pose).

Image jobs use the Studio image model with `strictReference: true` and the approved pose as identity. Negative prompt forbids a full head/body/skin rectangle.

**Mouth packs** (no GPU): `GET /character-kit-presets/mouths/manifest.json`. Packs: `paper-cut`, `children-illustration`, `limited-anime`, `felt-puppet`, `comic-ink`, `watercolor`. Apply attaches pending overlays; you still place and approve them.

**Wipe mouth box** paints an ellipse with nearby skin samples and registers a new pose file (`character-kit-mouth-wipe`). It does not delete the original.

**Cleanup** (`POST /api/v1/character-kits/face-rig/cleanup`): rembg U2Net + crop-to-alpha. `padding` 0–64 (default 8). Writes `{stem}.cleanup-{8hex}.png` and never overwrites the original. `400` if the source is outside uploads/workspace or the matte is empty.

Placement warnings (`assessFaceRigPlacement`) never auto-approve. Typical mouth scale is ≤ 0.12; blink ≤ 0.20. Mouths on a full-body cutout usually sit above the chest (`offsetY` more negative than −8).

**Lock all mouths** copies one calibrated mouth box onto `closed/small/wide/round` for that pose.

### 4.4 Preview speech (Face Rig only)

`previewFaceRigDialogue` plans **2–4 s** of visemes with the same cadence as scene dialogue. Missing shapes fall back (`wide` → `small` → `round` → `closed`). This preview does **not** write scene keyframes.

---

## 5. Cutout dialogue (scene)

Requires at least one speaking overlay (`Open` / `Small` / `Wide` / `Round`). Optional `Closed`. Bind overlays to the selected pose first (`faceBinding` + `parent`).

| Action | Result |
|---|---|
| Animate from line | `planCutoutDialogue(text, start, end, fps)` → opacity keyframes |
| Detect from audio | speech units → per-word plans, then the same compiler |

Cadence (verified in `cutoutDialogue.ts`):

- Minimum hold `max(2/fps, 0.12s)`.
- Viseme from glyphs: consonants/punctuation → `closed`; `o/u` → `round`; `a/e` → `wide`; other vowels → `small`.
- First and last beats are **closed** so cuts do not freeze on an open mouth.
- Very short words with a vowel get one centre pulse so they are not closed/closed after the edge guard.
- Missing viseme sprites fall back to Open / Wide / Small / Round, in that order.

Persisted on the scene as `dialogueBeats[]`:

```json
{
  "id": "beat-1",
  "text": "The square is frozen.",
  "start": 0.4,
  "end": 2.8,
  "mouthLayerIds": ["kit-luma-mouth-wide", "kit-luma-mouth-closed"],
  "audioTrackId": "speech-1",
  "confidence": "known-text"
}
```

`confidence` is `known-text` | `aligned-audio` | `energy-fallback`. Editing text, speaker, or timing **recompiles** mouth keyframes (`rebuildCutoutDialogueLayers`). Never target the hero/base plate as a mouth layer.

Narrative templates that already ship mouth slots: `cutout-talking-head` (`mouth-open` / `mouth-closed`) and `cutout-speaking-blink`. Hold/snap-only templates (`cutout-dialogue-hold`, `cutout-reaction-snap`) do **not** flap a mouth.

---

## 6. Recipes

The Recipe runner (`ui/src/lib/sceneRecipe.ts`) receives approved kit inventory tagged `APPROVED_CHARACTER_KIT id=…; role=base|pose/…|mouth/…|eyes/…`.

Rules the LLM is given:

- Keep body and face pieces from the **same kit id**.
- Spoken cutout dialogue needs a `speech` audio entry **and** a top-level `dialogueBeats` entry with `audioTrackId`, exact text, time range, and `mouthLayerIds`.
- Multi-shot recipes must set per-shot `audioTrackIds` and `dialogueBeatIds`. `[]` means silent / no mouths. Do not copy the full mix into every shot.

Compiler: `compileRecipeDialogue` → ordinary hold keyframes. Export sidecar stores the compiled scene plus the recipe.

---

## 7. HTTP

Workspace query on GET; body field on writes. Routes do **not** use the Director “active workspace only” rule — pass the output-directory name.

### `GET /api/v1/character-kits/library?workspace=default`

Returns the normalized library, or an empty `{ version: 1, revision: 0, activeId: "", kits: {} }` when the file is missing.

```bash
curl "$MAESTRO_URL/api/v1/character-kits/library?workspace=default"
```

### `PATCH /api/v1/character-kits/library/kits/{kit_id}`

Create or replace **one** kit. Neighbours are untouched. `makeActive` defaults true.

```bash
curl -X PATCH "$MAESTRO_URL/api/v1/character-kits/library/kits/luma" \
  -H "Content-Type: application/json" \
  -d '{
    "workspace": "default",
    "baseRevision": 0,
    "makeActive": true,
    "kit": {
      "version": 1,
      "id": "luma",
      "name": "Luma",
      "style": "cutout",
      "base": {
        "id": "luma-base",
        "name": "Luma base",
        "source": "luma-base.png",
        "kind": "image",
        "alphaStatus": "transparent",
        "reviewState": "approved"
      },
      "poses": {},
      "mouth": {},
      "eyes": {},
      "anchors": {
        "base": { "mouth": { "offsetX": 0, "offsetY": -18, "scale": 0.05, "rotation": 0 } }
      },
      "provenance": []
    }
  }'
```

`400` invalid body. `409` revision conflict.

### `DELETE /api/v1/character-kits/library/kits/{kit_id}`

Same CAS. Body: `{ "workspace", "baseRevision" }`. `404` if the id is missing.

### `POST /api/v1/character-kits/face-rig/cleanup`

```bash
curl -X POST "$MAESTRO_URL/api/v1/character-kits/face-rig/cleanup" \
  -H "Content-Type: application/json" \
  -d '{ "workspace": "default", "source": "mouth-wide.png", "padding": 8 }'
```

Response includes `filename`, `source`, `original`, `width`, `height`, `alpha`, `method: "rembg-u2net"`, `padding`. `400` / `404` if the file is not permitted.

---

## 8. Pitfalls

- Treating Face Rig as a 3D blendshape or as H3 speech. It is four PNG overlays + opacity holds.
- Mounting before review → `Review and approve … before mounting`.
- Two browser tabs saving the same workspace → `409`; the second tab must reload.
- Mixing kit A’s mouth with kit B’s body in a recipe. The inventory text forbids it; the compiler will not catch a hand-edited JSON mix.
- Naming overlays without `mouth` / viseme tokens and without `faceBinding`. Discovery falls back to labels; kit mounts set `faceBinding` explicitly.
- Expecting `lookNotes` to survive Save kit.
- Running cleanup on a pose (full body). The endpoint mattes **one overlay**; it will crop a whole character to its opaque bbox.
- Character Creator object mode → Face Rig. Rejected on purpose.

---

## 9. Files to read next

| Path | Why |
|---|---|
| `ui/src/lib/characterKit.ts` | Types, mount, recipe inventory |
| `ui/src/lib/characterKitFaceRig.ts` | Prompts, packs, anchors, wipe, preview |
| `ui/src/lib/cutoutDialogue.ts` | Viseme planner + keyframe compiler |
| `ui/src/lib/characterKitHandoff.ts` | Creator → 3D Video session handoff |
| `ui/src/lib/sceneRecipe.ts` | `dialogueBeats` + `APPROVED_CHARACTER_KIT` |
| `app/services/character_kit_library.py` | CAS store and validation |
| `app/services/character_kit_face_cleanup.py` | rembg + crop |
| `ui/public/character-kit-presets/mouths/manifest.json` | Pack ids and files |
| `tests/test_character_kit_library.py` | Server contract |
| `ui/tests/characterKitFaceRig.test.mjs` | Client Face Rig contract |
