# HOWUSEIT — Character Kits and Face Rig

Operator guide for reusable **2D cutout puppets**: one reviewed body or pose,
mouth overlays, an optional blink, and pose-local face anchors. This is not
Character Creator's Hunyuan turntable and not MiniMax H3 lip-sync.

UI: **3D Video** sidebar (`SceneAnimatorPanel` → Character Kits). Code:
`ui/src/lib/characterKit.ts`, `ui/src/lib/characterKitFaceRig.ts`, and
`ui/src/lib/cutoutDialogue.ts`. Persistence:
`app/services/character_kit_library.py`. Cleanup:
`POST /api/v1/character-kits/face-rig/cleanup`. HTTP boundary:
`app/_launch_runtime.py`.

Related: [3D Video compositor](../3d-video-compositor/HOWUSEIT.md),
[Character Creator orbit](../3d-video-compositor/HOWUSEIT.md#54-hunyuan3d-mesh).

---

## 1. What this system is

| Tool | Tab | Job |
|---|---|---|
| Character Creator | **Characters** | Identity photo → H3 360° orbit → Hunyuan multi-view **mesh** |
| Character Kit library | **3D Video** | Output-folder-scoped 2D puppet (base pose + mouth overlays + blink) |
| Face Rig | **3D Video** → Paso 2 · Labios / ojos | Generate, clean, place, and review overlays |
| Cutout dialogue | **3D Video** | Held/snap mouth keyframes from known text or speech |
| Recipe runner | **3D Video** | Compiles `dialogueBeats` and only **approved** kit pieces |

Use a kit when you need a **repeatable graphic character** that can speak with
four mouth sprites. Use Character Creator when you need a **3D mesh**. Use H3
when you need a **performed** face rather than a paper-cutout flap.

The compositor does not claim phoneme-perfect lip-sync. Cadence is bounded and
graphic.

### Output folder versus Workspace collection

Character Kit routes currently scope a **physical output folder**. Their
`workspace` query/body field retains that name for compatibility; it accepts
`default` or `[A-Za-z0-9][A-Za-z0-9_-]*`. It is **not** a logical Workspace
collection ID. The explicit Workspace collection registry
(`/api/v1/workspace-collections`) groups project, asset, and Production IDs
without creating or moving files. See the
[domain model and asset provenance contract](../development/DOMAIN_MODEL_AND_ASSET_PROVENANCE.md).

---

## 2. Hard limits and persistence rules

1. **Library file:** `{output-folder}/.character-kit-library-v1.json`. It holds
   at most **100** kits, **32** poses per kit, **20 MB** encoded JSON, and **500**
   provenance objects per kit.
2. **Compare-and-swap:** every write sends `baseRevision`. Stale clients get
   `409` with `code: character_kit_revision_conflict`, plus expected and current
   revisions. Reload the library; do not retry the same revision.
3. **Persistent sources only:** `blob:` sources are rejected. Use an
   `/api/v1/file/...` or `/api/v1/uploads/...` reference, or a filename in the
   output folder. Face Rig handoff also rejects transient browser images.
4. **Review gates:** only `approved` pieces mount or enter Recipe inventory.
   Generated Face Rig states, mouth packs, and cleaned overlays remain `pending`
   until reviewed and saved.
5. **Mouth states:** `closed`, `small`, `wide`, and `round`. Eye states are
   `open` and `blink`; the Face Rig generator calls the first one `open-eyes`.
   Unknown keys are rejected with `400`.
6. **Pose-local anchors:** offsets are relative to the character, not the 16:9
   frame. Defaults are mouth `{ offsetX: 0, offsetY: -18, scale: 0.05,
   rotation: 0 }` and eyes `{ offsetX: 0, offsetY: -28, scale: 0.12,
   rotation: 0 }`. Bounds are offset ±200, scale 0.001–20, rotation ±360.
7. **`lookNotes` is UI-only:** style and trait notes help the current editor
   build prompts, but `normalize_character_kit` strips the field on save.
8. **Delete is record-only:** deleting a kit removes its library entry, not its
   pose PNGs, cleaned overlays, or scene layers.

---

## 3. Data model

```text
CharacterKitLibrary { version: 1, revision, activeId, kits{} }

CharacterKit
  id, name, style: cutout | children-illustration | anime-2d
  identityReference?, base?, poses{}
  mouth { closed?, small?, wide?, round? }
  eyes { open?, blink? }
  anchors { [poseId]: { mouth, mouthStates?, eyes? } }
  provenance[]
```

Each asset is `{ id, name, source, kind: image|overlay, alphaStatus,
reviewState, prompt?, model?, workspace? }`. The optional asset `workspace` is
the legacy physical output-folder token, not a Workspace collection ID.

`alphaStatus` is `unknown`, `transparent`, or `opaque`. An image is considered
transparent when at least 1% of pixels have alpha below 250.

`mountCharacterKitLayers` parents each approved overlay to its pose, sets
`faceBinding`, and starts with the closed mouth visible. Mounting a kit pose
already present in a scene updates its existing layers instead of adding
duplicates.

Recipe inventory flattens only approved pieces. The active kit is ordered first
so a large output folder does not evict its complete face set under the global
inventory cap.

---

## 4. Operator workflow

### 4.1 From Character Creator

1. Stay on **character** (not object). Capture a turnaround view or upload the
   subject.
2. **Create / open CharacterKit Face Rig** stores the handoff in
   `sessionStorage` (`hocuspocus:character-kit-face-rig-handoff`) and switches
   to **3D Video**.
3. If a kit already uses that source as `base` or `identityReference`, the
   editor reopens it. Otherwise it drafts a new kit whose handed-off base pose
   is approved for the initial review step.

Character Creator does not generate visemes. Object mode is rejected with the
message *Face Rig is for Character Kits.*

### 4.2 From a compositor layer

1. Open **3D Video** and add a full-body cutout (generated image or transparent
   PNG).
2. Choose **New kit from selected base layer**, or assign **Selected → base /
   pose / mouth / blink**.
3. Review alpha and approve the pose before Face Rig generation.
4. Open **Paso 2 · Labios / ojos**: choose style and traits, generate missing
   states, optionally apply a mouth pack, **Clean**, place, **Lock all mouths**,
   then approve each state.
5. **Save kit** (PATCH), then **Mount pose** into the current scene.

Until **Save kit** is pressed, changes are editor state only; the LLM and other
scenes cannot see pending pieces.

### 4.3 Face Rig generation

Prompts are built by `characterKitPosePrompt` and `faceRigPrompt`. The user
supplies style and traits; the helper requests an isolated transparent overlay
or a full-body standing cutout for the pose.

Image jobs use the selected Studio image model with `strictReference: true` and
the approved pose as identity. The negative prompt forbids a full head/body,
skin rectangle, background, text, glow, and shadow.

The six generator states are `closed`, `small`, `wide`, `round`, `open-eyes`,
and `blink`. The first four populate `kit.mouth`; the last two populate
`kit.eyes`. Every generated state starts `pending`.

**Mouth packs** are static assets (no GPU generation):
`GET /character-kit-presets/mouths/manifest.json`. Available packs currently
include `paper-cut`, `children-illustration`, `limited-anime`, `felt-puppet`,
`comic-ink`, and `watercolor`. Applying a pack attaches pending overlays; place
and approve them before mounting.

**Wipe mouth box** paints an ellipse with nearby samples and uploads a new PNG
named like `<kit-id>-<pose-id>-mouthless.png`. It registers a new pose and does
not delete the original.

**Cleanup** (`POST /api/v1/character-kits/face-rig/cleanup`) runs rembg U2Net
and crop-to-alpha. `padding` is 0–64 (default 8). It writes
`{stem}.cleanup-{8hex}.png` and never overwrites the original. The endpoint
accepts an image inside the uploads root or the selected output folder; a full
body source will be cropped to its opaque bounding box, so cleanup is intended
for one overlay.

Placement warnings from `assessFaceRigPlacement` never auto-approve. Typical
mouth scale is ≤ 0.12 and blink scale ≤ 0.20. Full-body cutouts usually put the
mouth above the chest (`offsetY` more negative than −8).

**Lock all mouths** copies one calibrated mouth box to
`closed`, `small`, `wide`, and `round` for that pose. The equivalent eye action
copies the box to `open-eyes` and `blink`.

### 4.4 Preview speech (Face Rig only)

`previewFaceRigDialogue` plans **2–4 seconds** of visemes with the same cadence
as scene dialogue. Missing shapes fall back from `wide` to `small`, `round`, or
`closed` as available. The preview does not write scene keyframes.

---

## 5. Cutout dialogue in a scene

Bind overlays to the selected pose first (`faceBinding` plus a parent
relationship). A speaking kit needs at least one of `small`, `wide`, `round`,
or a legacy overlay identified as `open`; `closed` is optional but provides a
safe resting shape.

| Action | Result |
|---|---|
| Animate from line | `planCutoutDialogue(text, start, end, fps)` → opacity keyframes |
| Detect from audio | speech units → per-word plans, then the same compiler |

Cadence in `ui/src/lib/cutoutDialogue.ts`:

- Minimum hold is `max(2/fps, 0.12s)`.
- Consonants and punctuation map to `closed`; `o/u` to `round`; `a/e` to
  `wide`; other vowels to `small`.
- First and last beats settle on `closed` so a cut does not freeze on an open
  shape.
- A very short vowel-bearing word gets one centre pulse when cadence allows it.
- Missing speaking sprites fall back to the available open/wide/small/round
  layer.

Persisted scene records use `dialogueBeats[]`:

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

`confidence` is `known-text`, `aligned-audio`, or `energy-fallback`. Editing
text, speaker, or timing recompiles mouth keyframes through
`rebuildCutoutDialogueLayers`. Never target the hero/base plate as a mouth
layer.

Narrative templates with mouth slots include `cutout-talking-head`
(`mouth-open` / `mouth-closed`) and `cutout-speaking-blink`. Hold/snap-only
templates (`cutout-dialogue-hold`, `cutout-reaction-snap`) do not flap a mouth.

---

## 6. Recipes

The Recipe runner (`ui/src/lib/sceneRecipe.ts`) receives approved kit inventory
tagged `APPROVED_CHARACTER_KIT id=…; role=base|pose/…|mouth/…|eyes/…`.

Rules given to the planner:

- Keep body and face pieces from the **same kit ID**.
- Spoken cutout dialogue needs a `speech` audio entry and a top-level
  `dialogueBeats` entry with `audioTrackId`, exact text, time range, and
  `mouthLayerIds`.
- Multi-shot recipes must set per-shot `audioTrackIds` and `dialogueBeatIds`.
  `[]` means silent / no mouths. Do not copy the full mix into every shot.

`compileRecipeDialogue` turns those beats into ordinary hold keyframes. The
export sidecar stores the compiled scene plus the recipe.

---

## 7. HTTP contract

These routes are scoped to a physical output folder. The query/body field is
called `workspace` for compatibility. This differs from Director pipeline
routes, which always use the server's active output folder, and from logical
Workspace collection routes.

Set a base URL for the running HocusPocus instance in the examples below:

```bash
export HOCUSPOCUS_URL=http://127.0.0.1:7860
```

### `GET /api/v1/character-kits/library?workspace=default`

Returns the normalized library, or an empty
`{ version: 1, revision: 0, activeId: "", kits: {} }` when the file is missing.

```bash
curl "$HOCUSPOCUS_URL/api/v1/character-kits/library?workspace=default"
```

### `PATCH /api/v1/character-kits/library/kits/{kit_id}`

Creates or replaces one kit while leaving its neighbours untouched. `baseRevision`
is required by the compare-and-swap contract; `makeActive` defaults to true.

```bash
curl -X PATCH "$HOCUSPOCUS_URL/api/v1/character-kits/library/kits/luma" \
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
        "base": {
          "mouth": { "offsetX": 0, "offsetY": -18, "scale": 0.05, "rotation": 0 }
        }
      },
      "provenance": []
    }
  }'
```

`400` means the body or kit is invalid. `409` means another client advanced
the library revision; reload before writing again.

### `DELETE /api/v1/character-kits/library/kits/{kit_id}`

Uses the same CAS contract. Body: `{ "workspace": "default", "baseRevision": 1 }`.
Returns `404` if the kit ID is missing. Source files are deliberately retained.

### `POST /api/v1/character-kits/face-rig/cleanup`

```bash
curl -X POST "$HOCUSPOCUS_URL/api/v1/character-kits/face-rig/cleanup" \
  -H "Content-Type: application/json" \
  -d '{ "workspace": "default", "source": "mouth-wide.png", "padding": 8 }'
```

The response includes `filename`, public `source`, `original`, `width`,
`height`, alpha metrics, `method: "rembg-u2net"`, `model: "u2net"`, and
`padding`. `400` / `404` indicate a missing or disallowed image.

---

## 8. Pitfalls

- Treating Face Rig as a 3D blendshape or H3 speech. It is a small set of PNG
  overlays plus opacity holds.
- Mounting before review. The compositor rejects unapproved poses and overlays.
- Saving from two browser tabs with the same revision. The second tab receives
  `409` and must reload.
- Mixing kit A's mouth with kit B's body in a hand-edited recipe. Inventory
  guidance prevents this, but a manually edited JSON can still be inconsistent.
- Naming overlays without mouth/viseme tokens or `faceBinding`. Discovery has
  a legacy label fallback; mounted kits set semantic bindings explicitly.
- Expecting `lookNotes` to survive Save kit.
- Running cleanup on a full-body pose when you intended to clean only one
  overlay; the endpoint crops the opaque bounding box.
- Trying Face Rig from Character Creator object mode; it is rejected on purpose.
- Confusing an output-folder token in these routes with a Workspace collection
  ID. The latter is metadata and does not select files.

---

## 9. Files to read next

| Path | Why |
|---|---|
| `ui/src/lib/characterKit.ts` | Types, mounting, and Recipe inventory |
| `ui/src/lib/characterKitFaceRig.ts` | Prompts, packs, anchors, wipe, preview |
| `ui/src/lib/cutoutDialogue.ts` | Viseme planner and keyframe compiler |
| `ui/src/lib/characterKitHandoff.ts` | Creator → 3D Video session handoff |
| `ui/src/lib/sceneRecipe.ts` | `dialogueBeats` and `APPROVED_CHARACTER_KIT` |
| `app/services/character_kit_library.py` | CAS store and validation |
| `app/services/character_kit_face_cleanup.py` | rembg and crop |
| `ui/public/character-kit-presets/mouths/manifest.json` | Pack IDs and files |
| `tests/test_character_kit_library.py` | Server contract |
| `ui/tests/characterKitFaceRig.test.mjs` | Client Face Rig contract |
