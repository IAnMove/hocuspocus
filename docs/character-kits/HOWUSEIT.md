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
[Character Creator orbit](../3d-video-compositor/HOWUSEIT.md#54-hunyuan3d-mesh),
[Studio Tools rembg](../tools/HOWUSEIT.md) (general image background removal;
Face Rig cleanup is a different endpoint).

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
7. **`lookNotes` persist:** style and trait notes are stored on the kit
   (max 4000 characters) and shown when Story Lab or Series links the
   character. Face Rig still uses them to build overlay prompts.
8. **Delete is record-only:** deleting a kit removes its library entry, not its
   pose PNGs, cleaned overlays, or scene layers.
9. **Voice is local only.** Presets use `qwen3_tts_customvoice` plus a named
   id (`vivian`, `serena`, `uncle_fu`, `dylan`, `eric`, `ryan`, `aiden`,
   `ono_anna`, `sohee`) and optional direction (max 1000 chars). Custom
   recordings use `qwen3_tts_base`, `voxcpm2_base`, or `drama3_base` with `voiceId: "reference"`;
   a VoxCPM2 recording may add a speaking style (`instructions`, max 300 chars).
   Drama 3 cloning requires the transcript and takes no style. `drama3_voicedesign`
   stores a designed voice (`voiceId: "design"`, optional direction, no recording).
   Do not store credentials on the kit.

---

## 3. Data model

```text
CharacterKitLibrary { version: 1, revision, activeId, kits{} }

CharacterKit
  id, name, style: cutout | children-illustration | anime-2d
  identityReference?, base?, poses{}
  mouth { closed?, small?, wide?, round? }
  eyes { open?, blink? }
  voice? PresetCharacterVoice | CustomCharacterVoice | DesignCharacterVoice
    preset: { provider: local, model: qwen3_tts_customvoice, voiceId, instructions? }
    custom: { provider: local, model: qwen3_tts_base | voxcpm2_base | drama3_base, voiceId: "reference",
              name, referenceAudio, transcript, language, instructions? (VoxCPM2 only) }
    design: { provider: local, model: drama3_voicedesign, voiceId: "design", name, language, instructions? }
  lookNotes?
  speech3d? { model, digest, settings? }
  anchors { [poseId]: { mouth, mouthStates?, eyes?, blink?, blinkSource?, mouthSources? } }
  animations? { [animationId]: { sheet, frames[], fps, loop, facing, reviewState, view?, prompt?, model?, createdAt? } }
  provenance[]
```

Each asset is `{ id, name, source, kind: image|overlay, alphaStatus,
reviewState, prompt?, model?, workspace? }`. The optional asset `workspace` is
the legacy physical output-folder token, not a Workspace collection ID.

`alphaStatus` is `unknown`, `transparent`, or `opaque`. An image is considered
transparent when at least 1% of pixels have alpha below 250.

`anchors[pose].mouthSources` (`{state: url}`) are a pose's own mouth drawings:
the flat rig's warp mouths, square patches cut from that pose's lower face.
They share the review of `kit.mouth[state]`, which holds the base pose's. While
it does, each pose mounts its own (`characterKitMouthSource`) and a pose with
none mounts no mouth, never another pose's face. A drawing put on `kit.mouth`
later is shared by every pose again.

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

### 4.5 Preferred voice (preset or recording)

`CharacterVoiceFields` on the kit (and Character Creator speech) stores a
public preference only. Audition generates a short sample; choosing a voice
does not create audio.

**Named preset** (`qwen3_tts_customvoice`): pick a catalog speaker and optional
acting notes. Tijeral ships these presets; they are not cloned actors.

**Add your own voice** (`qwen3_tts_base`, `voxcpm2_base`, or `drama3_base`):

1. Choose **Add your own voice: import or record**.
2. Name the voice (max 120 chars) and pick the **Voice engine**: VoxCPM2,
   the default (48 kHz, 30 languages, optional **Speaking style** such as
   «susurrando»; with a style VoxCPM2 clones from the sample alone), or Qwen3.
3. Import WAV/MP3/M4A/FLAC/OGG (or record on HTTPS / localhost).
4. Enter the **exact transcript** of that sample (max 4000 chars). This is
   not the dialogue to generate later.
5. Pick the language for new lines (`auto` or one of
   `CHARACTER_VOICE_LANGUAGES`).
6. Audition, then **Save everything** on the character.

Constraints from `uploadVoiceReference` / `parseCharacterVoice`:

- Duration 3–30 seconds. A microphone overrun keeps the first 30 s instead
  of rejecting the take. Imports longer than 30 s are rejected.
- File ≤ 20 MB, nonempty, decodable in the browser.
- `referenceAudio` is a persistent `/api/v1/uploads/…` or
  `/api/v1/file/…?workspace=` URL. Host paths, credentials, and query
  strings on uploads are rejected.
- Saved custom voices appear in the selector for other kits (`saved:<id>`).
  Existing takes stay; new or regenerated 2D/3D dialogue uses the stored
  recording + transcript.

### 4.6 Painted / graphic-novel characters that talk

Character Creator › **Style** › **Graphic novel (painted)** (`graphic-novel`
in `app/shared/character_styles.json`, MCP `characters.styles`) is the path
for painted art: bold ink, flat black shadows. Its prompts ask for what the
flat rig must find: both eyes with clean white sclera, never in the shadow,
and the closed mouth painted as one short dark line, on a plain screen.
**Save and make it talk** rigs with the preset's `rig`,
`{"mouthStyle": "warp"}`: each pose talks with its own drawing (the upper lip
stays, the lower lip, chin and beard move down, the gap is a flat mouth in its
ink). The kit records the preset (`provenance`
`{"method": "character-style-create", "style": "graphic-novel"}`), so a first
rig with no `style` uses it too, and every later rig (a pose added, a mouth
line saved, an agent's re-rig) keeps the kit's last look: style keys left out
are the last rig's. Only an explicit `style.mouthStyle` changes the mouths.

What to check after each rig:

- the review sheet: each pose opens between the lips, not at the nose or a
  moustache;
- the rig result's `poses.<pose>.mouthLine` and `warnings`. The creator names
  the poses with `mouth_line_guessed` (no painted line where the mouth was
  put) or `mouth_line_unsure` (unsure face points).

Fix a pose in **Prepare 2D speech** › Face Rig › **Mouth line**: drag the dot
onto the line between the lips and the ends to the corners, then **Save
mouth**. An agent does the same with `characters.rig.flat.preview` and
`hints: {"<pose>": {"mouth": [x, y], "mouthWidth": w}}`.

A face in a full figure is small and its moving lips read less: add a bust
pose (*bust, head and shoulders*) for close dialogue.

### 4.7 Animations: walk, gestures and anime expressions

**Characters › Animaciones del personaje** (a drawer right under "Crear personaje desde una descripción"; the character just saved is the one it opens on) makes small animations of a saved
character. Each one is a few poses of the same figure joined into a sprite sheet that the Video 2D cards play. The list is
`app/shared/character_animations.json` (MCP `characters.animations`):

| group | animations |
|---|---|
| Cycles (5) | `walk` (four poses of the gait, side view, looks right), `run`, `step` (two poses: the stride and the legs together), `idle` (breathing), `jump` |
| Gestures (11) | `wave`, `nod`, `shake` (head no), `point`, `shrug`, `bow`, `clap`, `cheer`, `salute`, `facepalm`, `think` |
| Anime expressions (18) | `angry`, `surprised`, `sad`, `happy`, `embarrassed`, `scared`, `smug`, `confused`, `determined`, `tired`, `love`, `disgusted`, `bored`, `worried`, `nervous` (nervous laugh), `laughing`, `wink`, `pout`: two poses each, from a hint to the full expression (anger vein, shock lines, sweat drop, hearts) |

**Three doors, one job.** The Animaciones panel (**Crear**), any MCP client (`characters.animation.make`, then
`characters.animation.status` / `.cancel` / `.review`) and Ask to the Wizard (`make_character_animation`: "hazle una cara de enfado a
Heroína"; `review_character_animation`) all start the same server job, `POST /api/v1/character-kits/animations/make` (`services/character_animation_job.py`). The
panel only asks and follows it (a poll, quick while a job runs and slow otherwise), so a run survives a reload, a tab change or a
restart, and an animation an agent started shows up in the panel (and the other way round). One animation is made at a time on the
server (one GPU); asking for one already being made returns that job. The job is a small file under
`.character-animation-jobs-v1` of the workspace.

What the job does:

1. Each pose is one Qwen picture made with the character's own picture (`identityReference`, else `base`) as
   `image_refs`, one after another, on a plain screen colour (default model `qwen_image_21_turbo`, 8 steps and no negative prompt; another model runs its own steps and a
   distilled one takes no negative prompt). The style preset the kit was made in (`character-style-create` in its provenance)
   keeps its look through `animation.identity` in `character_styles.json`. Every picture has its own file name and intent id, so a
   pose made again never overwrites the picture the saved animation still uses.
2. Each pose is keyed (`studio.key`) as soon as it arrives. A failed pose stops the job and stays on screen; the next job for that
   animation (**Reintentar**, or the same request again) keeps the poses already made, also after a cancel or a restart
   (`interrupted`), and **Rehacer** under a frame (`pose` in the request) makes only that pose again of a finished animation.
3. The sheet is joined (`POST /api/v1/character-kits/animations/sheet` is the same step for an agent that makes the poses itself,
   MCP `characters.animation.sheet`): each keyed pose is cropped, scaled so the figure keeps its size (`scaleBy`, below), stood on
   one line (96 % of the cell) and its upper body centred (the mean of the top 55 % of the pose, so swinging legs and arms do not
   move the torso). It writes `<kit>-<animation>-sheet-<8hex>.png` and never overwrites one.
4. The animation joins the kit as `reviewState: pending`, read again from the library just before it is saved, so a character edited
   meanwhile keeps its edits. Play it (the player uses the card's own frame rule), then approve or reject it in the panel.
   **Approve** is a person's decision unless the owner turned on «Modo un solo disparo» (next section): nothing approves it otherwise.

**«Modo un solo disparo» (one-shot mode).** Settings › Services has a switch (`agent_autonomy`: `review`, the default, or
`one_shot`) so that one request to an agent can go from the idea to a finished animation. Off, nothing changes: a person approves.
On, an agent may decide what a person normally decides, through the same operation from every door
(`services/character_animation_review.py`, `POST /api/v1/character-kits/animations/review`): MCP `characters.animation.review`
{character_id, animation, decision approve | reject, note} and Ask to the Wizard (`review_character_animation`). In `review` mode they
answer an error that says to approve it in Characters › Animaciones or turn the mode on. The review is stamped on the animation
(`reviewedBy` `person` or `agent`, `reviewNote`, `reviewedAt`; older data has none and reads as a person's) and the card shows
«aprobada por el agente» with the note as its tooltip; **Aprobar** and **Rechazar** on the card take the decision back and stamp
`reviewedBy: person`. A rejected animation keeps its sheet and poses, so **Rehacer** or `pose` makes one again; an agent never
overturns a decision a person gave.

`characters.animation.make` and the Wizard's `make_character_animation` take `autoApprove` / `auto_approve`. In `one_shot` the job
reads the sheet it wrote (`services/character_animation_checks.py`), approves it as the agent only if every check passes and reports
`autoApproved` and `checks` (id, ok, value, limit); otherwise the animation stays pending and the failed checks say why. In `review`
mode it is ignored and the job says so (`autoApproveNote`). The checks, set against 57 real Qwen sheets (all passed the picture checks):

| check | passes when |
|---|---|
| `cell_count` | the cells are the poses of the animation, in a grid that holds them |
| `cell_size` | the sheet is exactly columns × rows cells of the contract height (640) |
| `filled_cells` | every figure covers at least 3 % of its cell (real: 15 to 55 %) |
| `clean_alpha` | at most 25 % of a figure's pixels are half-transparent (real: 1 to 5 %) |
| `silhouette` | a figure fills at most 90 % of its box, so a key that left a rectangle fails (real: 53 to 75 %) |
| `ground_line` | the lowest row of every figure is on the line `feet`, within 2 % of the cell (real: 0.1 %) |
| `scale_spread` | the smallest figure is at least 80 % of the biggest (legs 80 %, head 70 %, measured before the sheet equalised them; jump and bow 45 %); real walks 0.93 to 0.99 |
| `scale_measure` | the sheet was scaled by what was asked, not by the height it falls back to when the legs or head cannot be measured |

The checks catch a pose drawn at another size, a bad key, a missing pose or a broken sheet. They do not judge identity (a walk sheet
of a younger-looking character passes): the agent still looks at the sheet and rejects it when it is out of model.

**An animation of your own** ("A medida" in the panel; `custom {title, view, poses}` in the request): a name, a framing (`bust`,
`front`, `side`) and one line per pose (up to 6, 600 characters each). The words stay on the kit with each pose, so any pose can be
made again alone, and on the job, so an animation not on the kit yet stays on screen after a reload. The defaults of one (fps, loop,
`scaleBy` and `facing` by framing) live in `custom` of `app/shared/character_animations.json`, one place for the panel and the server.

`scaleBy` keeps the figure one size from pose to pose, because the model draws every pose at a slightly different size and frames it a
little differently (up to 6 % between the cells of one wave, and 30 % in the head of one pair of busts, where the second pose showed
more of the body):
- `height` (cycles): all poses share one scale, the tallest fills 86 % of a cell, so a crouch stays lower than a stand.
- `base` (a whole figure making a gesture): each pose is scaled so its legs, the bottom 20 % of the picture, are as wide as in the
  others. A raised hand only makes a figure taller, and arms hanging beside the coat make the rest of the body wider than with the
  arms up (scaling by the whole lower body made the figure 20 % smaller in the cheer pose with its arms down), but the legs do not move.
- `face` (a bust): each pose is scaled so its head is as big as in the others. The head is read with the face landmarks of the flat rig
  (DWPose, on the CPU); when no face is found in some pose the sheet is joined by `height` and the reply says so (`scaleBy` is the mode
  used, `requestedScaleBy` the one asked for, `measures` what was measured). The width of the head was tried first and failed: a
  head turned or tipped back is narrower.
The catalog gives each animation its own (`front` → `base`, `bust` → `face`, `side` → `height`).

The Video 2D card that plays it is named in the list: `walk-cycle-sheet` for cycles (controls `frames`, `columns`, `facing`,
`step`: two steps make a cycle), `walk-two-pose` for `step` (one step is a sheet of two poses; the figure stops on the last cell) and `character-reaction` for gestures and expressions (`frames`, `columns`, `fps`, `loop`,
`framing`, `mark`). The panel prints the controls for the animation it shows.

Limits: 48 animations per kit, 12 poses per sheet. The server drops a sheet it cannot read (`400`). Qwen cannot tell the near leg from the far one in a side view: the second contact pose and the
second passing pose of `walk` often come out like the first ones (a fourth pose may even come out as a stride, not a passing).
The cycle then plays two drawings twice, which still reads as a walk; make a pose again until it differs, or keep it. A
bust is asked for with an explicit crop (`views.bust` and `viewNegatives` in the catalog) because a full-length reference
picture pulls the composition: without it an expression came out as a whole figure with a small face. A cutout pose is one
picture, so the animation is limited animation (a few poses a second), not fluid motion; a bust (`view: bust`) is made for
expressions and a whole figure for gestures and cycles. A figure looks the way the picture says: a layer cannot be mirrored,
so the card walks it the way it looks (`facing`); only a sheet `sequence` can be drawn mirrored (`mirror: true`), which is how a
Series shot lets a character walk in against the way its sheet looks.

### 4.8 Animations in a Series shot

A Series script plays an **approved** animation of the kit (`app/services/series_cast_animation.py`,
`ui/scripts/seriesSheet.ts`). A pending or rejected sheet is refused by the script check (and by `series.shot.update`) with
«animation 'walk' of 'ana' is pending approval: approve it in Characters › Animaciones»: the person approves it first.

- **`animation` on a `layout2d.cast` entry:** an id of the kit (`"wave"`, `"angry"`, one of your own) or
  `{"id", "at", "duration", "loop"}`: `at` is seconds inside the shot (default 0). `duration` defaults to one pass of the sheet
  (its cells at its fps; a `pingpong` there and back); an expression with no duration lasts at least 2.5 s. An explicit duration
  under 1.5 s on an expression warns `expression_too_short` and is still played. `loop` is `loop`, `pingpong` or `once` (the sheet's own by default; a `once`
  sheet holds its last cell until the window ends). The cast entry still says where the character stands (`x`) and which pose it has.
- **What is drawn:** during the window the sheet uses the pose's final transform, after the edge snap, centered on the character's `x`, at that size and that base, with no extra zoom. It is drawn as the `walk-cycle-sheet` and `character-reaction`
  cards draw it (equal cells, the figure 86 % of a cell high, the boots on the line at 96 %). A body sheet is as tall as the pose and stands on the pose's feet. A face sheet (`scaleBy: face` on a pose taller than it is wide) is the head only: the figure is `pose height × 0.18 / 0.5` and hangs from the crown. An expression fades in and out over about 0.25 s; a gesture or a cycle does not. The pose picture, its mouths and
  its eyes are hidden meanwhile and come back when the window ends, so a character who speaks over a body sheet does not move its lips.
- **A sheet never plays while its own character speaks.** A sheet has no lip-sync and hides the pose with its mouth, whatever its
  group, so the server render (`app/services/series_expression_silence.py`) keeps every approved animation clear of the lines of the
  character that plays it, using the real length of the recorded takes. It covers an `expression`, a `gesture`, a `custom` sheet (the
  ones `characters.animation.make` creates) and one with no group; only a `cycle` and `walk` (continuous body motion) are left alone.
  If the window `[at, at + duration]` overlaps one of that character's lines, it is moved: first to end 0.2 s before the character's
  first line (when that fits inside the shot, and after the walk-in sheet), else to the first silence of that character that holds
  it plus 0.2 s on each side, else dropped and the character keeps its pose. A window with no `duration` lasts one pass (an
  expression at least 2.5 s), as the compiler plays it. The render job's item lists `expression_moved_for_speech` (from → to) or
  `expression_dropped_during_speech`; the script is not changed. A character who *listens* while another speaks keeps its sheet; a
  shot with no recorded lines is not touched. `{"id": "angry", "allowDuringSpeech": true}` opts one animation out. A `character-reaction`
  card plays its sheet from the first second and cannot be moved: `series.shot.card.apply` warns `expression_during_speech` (same
  criterion) when the character speaks in the shot.
  The sheet is its own layer (`kit-<kit>-sheet-<id>`, a `sheet` sequence with `start` = the window's start second); stop-motion
  holds (`motionStep`) apply to it like to every picture.
- **`enterGait: "walk"` with the kit's approved `walk` sheet:** the sheet plays on loop for the whole entrance, on the same slide
  at the same pace, with no bob or sway (the drawings step), one cycle (two steps) per `2 × enterStep` seconds, so the footfalls
  and the `repeat: "steps"` sounds land on the feet. It is mirrored when the character enters against the way the sheet looks
  (`facing`: a sheet that looks right entering from the right). Without an approved `walk` sheet the entrance is the bob it
  always was (the check warns `walk_sheet_not_approved` when the sheet exists but is not approved).
- **Limits:** one animation per cast entry; an `animation` that would start inside a walk-in that plays the walk sheet is refused
  by the check (start it at the walk's end; the compiler moves it there if it gets past the check). A bust expression goes with a bust pose in a `medium` or `close` shot and is sized from the head, not from the whole pose.

### 4.9 A whole Video 2D card as a shot's take

`series.shot.card.apply` (MCP) and `apply_series_shot_card` (Wizard) put any card of `scenes.templates.catalog` on a 2D Series
shot as a **new take**, in one call: `POST /api/v1/series/{series}/episodes/{episode}/shots/{shot}/card`
(`app/services/series_shot_card.py`). Before it, a walk-in took five steps by hand (find the card, compile it, edit it, export it,
import and approve the take).

```json
{"workspace": "cast", "card": "walk-cycle-sheet",
 "cast": [{"slot": "subject_1", "characterId": "gloria", "animation": "walk"}]}
```

- **Characters:** the `subject_N` slots take the shot's own people (in the shot's order) or the `cast` you give. The sheet cards
  (`walk-cycle-sheet`, `walk-two-pose`, `character-reaction`) play the character's **approved** animation sheet: `walk` by default
  for the walk cards, always named (`wave`, `angry`...) for `character-reaction`; `frames`, `columns` and `facing`/`step` or
  `fps`/`loop` come from the sheet. A pending or rejected sheet is refused with the words of §4.8. Every other card draws a pose
  picture (`poseId`, else the pose the shot gives that character).
- **The rest of the card:** `background` is the shot's location plate; `foreground` and props come from `assets`
  (`{slot: workspace file or URL}`); `controls` are the card's own. The card lasts as long as the shot (held inside the card's 3 to 12
  seconds; longer shots are refused) and the shot takes the take's length, as the server render does.
- **Lines:** a shot with spoken lines needs them recorded (`series.shot.voice`, or one render): the speech and the subtitles are laid
  into the scene (`audioTracks`, `dialogueBeats`), timed as the render times them. A card has no mouths.
- **What it leaves:** the scene `<series>-<episode>-<shot>-card-<card>.scene.json` in the workspace
  opens in Video 2D, and the take (`productionMethod: animation_2d`, `sceneFilename`, `cardId`, `cardBindings`, the shot's
  `renderInputs`) is a candidate in Series Lab. The same inputs again find the same take and leave that scene file alone
  (a person may have edited it); other inputs replace the scene, reject the earlier unapproved take as superseded and attach a new one.
- **Approval:** `approve: true` approves the take only in «Modo un solo disparo» (`agent_autonomy` = `one_shot`); in `review` mode it
  is refused (403 `agent_review_off`) and the person approves in Series Lab. A take a person approved is never replaced: the new one stays a
  candidate and the reply says so (`approvalNote`).
- **Export:** the scene is exported by `scenes.video2d.export`, the exporter the server render uses (a 5 s card takes seconds on a CPU).
  If it is not ready after 60 s the reply is `status: "exporting"`; send the same request again and it attaches the take.

### 4.10 Voice band

A kit voice may carry `voiceType` (`man`, `woman`, `child`, `robot`), `pitchBandHz` `[low, high]`, `maxBrightness` (share of power at or above 3000 Hz) and `maxCentroidHz`. With none of them, a render records the line as before: `pitch_out_of_range` still only warns and does not ask for another take. With any of them, each take is measured (median pitch, that brightness, spectral centroid) and a take outside the band is spoken again, up to 3 seeds. If none lands inside, the best take is kept and the line warns `voice_out_of_band`. A man whose median pitch sits in the woman register (150–249 Hz) is retried even when a custom `pitchBandHz` would have allowed it. A missing measurement is not a failure.

The default numbers are in `app/shared/voice_bands.json`, measured from real lines, not guessed: man 80–136 Hz, woman 108–249 Hz, child 180–230 Hz with centroid at most 510 Hz, robot 90–145 Hz. A stored field overrides its default. The type is never inferred from the character's description.

**Cleanliness.** Every take is also measured for noise, whatever the voice (`services/voice_cleanliness.py`, the raw take before the trim): the noise floor (5th percentile of 50 ms frames, dBFS), the SNR (90th percentile minus the floor) and the share of energy between 40 and 100 Hz. A take with a floor above -60 dBFS, an SNR under 45 dB or 35 % or more of its energy in the bass is "unclean" and is spoken again, up to the same 3 seeds as the band; the cleanest take is kept and, if none is clean, the render does not stop: the item warns `voice_unclean` with the numbers (`cleanliness`) and the remedy. A clip under 1.5 s, or one with almost no pause, cannot show its floor: it is `inconclusive` and is never retried or warned (only the bass check applies). Reused recordings are not measured again. `qa.speech` and a completed `series.shot.voice` job (`result.cleanliness`, `result.warnings`) return the same object for any workspace file. Voices made with Drama `voicedesign` measured a floor of -47 to -55 dBFS and 26 to 36 dB of SNR; a clone of a clean VoxCPM2 reference measured -93 dBFS and 76 dB. For final lines, design the reference with VoxCPM2 and clone it with Drama `drama3_base`; do not use `drama3_voicedesign`.

Three doors, one function (`services/voice_band.py` `set_voice_band`):

- `POST /api/v1/character-kits/library/kits/{kit_id}/voice-band` with `{workspace, voiceType?, pitchBandHz?, maxBrightness?, maxCentroidHz?, language?, baseRevision?}`. A bad value is HTTP 400.
- MCP `characters.voice.band` posts that same body (`character_id` is the kit id; `language` selects `voicesByLanguage`).
- Ask to the Wizard: `set_voice_band`.

```bash
curl -X POST "$HOCUSPOCUS_URL/api/v1/character-kits/library/kits/gary/voice-band" \
  -H "Content-Type: application/json" \
  -d '{"workspace":"default","voiceType":"man"}'
```

```javascript
await fetch(`${base}/api/v1/character-kits/library/kits/gary/voice-band`, {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ workspace: 'default', voiceType: 'man' }),
})
```

```python
import json, urllib.request
body = json.dumps({"workspace": "default", "voiceType": "man"}).encode()
request = urllib.request.Request(base + "/api/v1/character-kits/library/kits/gary/voice-band", data=body, method="POST")
request.add_header("Content-Type", "application/json")
urllib.request.urlopen(request)
```

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

### `GET /api/v1/character-kits/animations/catalog`

The animation catalog (`character_animations.json`: groups, views, the sheet contract and every animation with its poses).

### `POST /api/v1/character-kits/animations/prompt`

`{animation, pose, description?, style?, screen?}` → `{prompt, negative, screen, resolution}`. `404` for an unknown
animation, pose or style.

### `POST /api/v1/character-kits/animations/sheet`

`{workspace, sources[1..12], name?, columns?, scaleBy?}` → `{filename, source, width, height, count, columns, rows, cell, feet,
figure, scaleBy, requestedScaleBy, measures, poses}`. Sources are keyed workspace or upload images; `400` for a source with nothing opaque in it.

### `POST /api/v1/series/{series}/episodes/{episode}/shots/{shot}/card`

`{workspace, card, controls?, cast?: [{slot?, characterId, animation?, poseId?}], assets?, language?, approve?}` → `{status:
"completed" | "exporting", shotId, number, card, scene, sceneUrl, bindings, controls, duration, warnings, take?: {attemptId,
assetId, approved, reused, superseded}, approvalNote?, exportIntent?}`. `shot` is the shot id or its number. Errors carry
`{code, message}`: `template_unknown`, `template_retired`, `template_bad_control` (the compiler's own), `shot_not_found` (404), `shot_not_2d`, `animation_not_approved`,
`animation_not_found`, `animation_required`, `card_not_sheet`, `slot_missing`, `bad_slot`, `bad_asset`, `unknown_pose`,
`unknown_character`, `lines_not_recorded`, `card_shorter_than_shot`, `agent_review_off` (403), `export_failed`, `tool_failed`.

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
- Expecting Story Lab’s acting-notes field to be the TTS engine. TTS lives
  on the kit (`voice`); the story row is casting notes for this plot.
- Running cleanup on a full-body pose when you intended to clean only one
  overlay; the endpoint crops the opaque bounding box.
- Trying Face Rig from Character Creator object mode; it is rejected on purpose.
- Confusing an output-folder token in these routes with a Workspace collection
  ID. The latter is metadata and does not select files.
- Rigging realistic or graphic-novel art (small eyes, eye bags, spectacles,
  flat black shadows) with the paper mouths. The flat rig
  (`POST /api/v1/character-kits/library/kits/{id}/flat-rig`,
  `characters.rig.flat`) detects such a face and finds its mouth lower down.
  The cartoon paper mouths still clash with the art: send
  `style: {"mouthStyle": "ink"}`. The painted mouth then stays as the rest
  shape, and the open shapes are drawn in its own ink. With
  `{"mouthStyle": "warp"}` each pose talks with its own drawing: the lower lip,
  chin and beard move down and the gap is inked, one set of patches per pose
  (`anchors[pose].mouthSources`). A full figure's small face is read and
  warped enlarged, then fitted back (`faceSize` per pose). If a pose's mouth
  or eyes are found in the wrong place, send
  `hints: {"<pose id>": {"mouth": [x, y], "eyes": [x, y], "mouthWidth": w}}`,
  in % of that pose's keyed image, or place the mouth line in the Face Rig's
  **Mouth line** editor, which previews the warped states live. The kit
  provenance keeps hints for later rigs, and `null` clears a pose's hints. See
  `docs/agents/VIDEO_PRODUCTION_RUNBOOK.md`.

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
