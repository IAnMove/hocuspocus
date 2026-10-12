# Game assets

One studio holds the art, sound and meshes of one game. The tuned view is a side-view platformer: characters face right, and left is the same sprite mirrored. `topdown` is stored and is not tuned. Styles are traits (palette, line, light, shading). Preset labels, traits, prompts and this document do not name a brand, console, studio or artist. One preset id, `lowpoly-ps1`, still carries a console abbreviation. Prompts never include the id.

The pack is generic. It is PNG plus a TexturePacker-style atlas, GLB, WAV/OGG with loop points, and `manifest.json`. There is no Godot `.tres` and no Unity `.meta`.

Approving a style and approving or rejecting an asset are human decisions. No flow approves itself. The acceptance playthrough may approve inside `game-lab` only when the person asked for that playthrough, and the report must say so. That playthrough has not been run. See [GAME_ASSETS_ACEPTACION_2026-10-07.md](GAME_ASSETS_ACEPTACION_2026-10-07.md).

Generated PNG, WAV and GLB files stay in the workspace under `app/outputs/` (gitignored). They are not committed and installers do not download them.

J0–J17 are in `development` (#887, #894, #901, merged 2026-10-07). The board is [GAME_ASSETS_BOARD.md](GAME_ASSETS_BOARD.md). The agent guide is [../agents/GAME_ASSETS_MCP.md](../agents/GAME_ASSETS_MCP.md).

## Names

| What | Name |
|---|---|
| Library | `<workspace>/.game-library-v1.json` |
| Attempt files | `<workspace>/game/<gameId>/<assetId>/<attemptId>/`, candidates in `a1/`, `a2/`, …, tool outputs in `raw/` |
| Jobs | `<workspace>/.game-jobs-v1/<jobId>.json`, job id `game-produce-<8 hex>` |
| Timings | `<workspace>/.game-timings.json` |
| Export | `<workspace>/game-exports/<gameId>-r<revision>.zip` |
| Services | `app/services/game_*.py`, `app/services/game_generators/` |
| Routers | `app/routers/game_library.py`, `app/routers/game_produce.py` |
| MCP | prefix `game.*`, profile `game` at `/api/v1/mcp/game` |
| UI | `ui/src/features/game-assets/`, `ui/src/api/gameAssets.ts`, i18n `gameAssets`, filter `gameAssets`, agent tab `game_assets` |

The visible tab is “Game assets” / “Recursos de juego”. The short label is “Game” / “Juego”. The description is “Sprites, animation, audio and models for one game.” / “Sprites, animación, audio y modelos de un juego.”

## Data contract

```jsonc
{"schema": "hocuspocus.game-library", "version": 1, "games": [Game]}
```

A game has `id`, `title`, `revision`, `createdAt`, `updatedAt`, `genre` (`platformer` | `topdown` | `other`), `view` (`side` | `topdown`), `style`, `assets` and `exports`.

### Ids

Game and asset ids are slugs: lowercase letters, digits and single hyphens, at most 64 characters (`invalid_slug`). `con`, `prn`, `aux`, `nul`, `com1`–`com9` and `lpt1`–`lpt9` are `reserved_id`, because Windows cannot make those folders. A game id cannot be `presets` or `produce`, which are routes (`reserved_id`).

An explicit game id that is taken is 409 `game_exists`. Without an id, the title becomes the slug: accents folded, cut to 64 at a hyphen, `juego` when empty, `-juego` after a reserved name. A taken slug gets `-2`, `-3`, …

Two assets of one game cannot share an id (`duplicate_id`).

### Revision

`revision` is 1 after create. Every write through `_bump` adds 1: game update, list write, asset patch, a stored attempt, approve, reject, lock and style approval. The producer's status-only writes (`generating`, back to `pending`) and an export do not bump it.

`PUT /api/v1/games/{id}`, `PATCH .../assets/{assetId}` and `POST .../style/approve` require `base_revision`. Approve, reject and lock accept it. A mismatch is 409 `revision_conflict`.

`exports` rows are `{id, revision, file, createdAt, counts}`. `id` is `e1`, `e2`, … See [Export](#export).

### Style

`normalize_style` keeps `revision`, `approval` (`draft` | `approved`), `approvedAt`, `preset` (default `pixel-16`), `traits`, `negative`, `palette`, `paletteMode` (`locked` | `free`), `pixel`, `light` (`top-left` | `top` | `front`), `screen` (`auto` | `green` | `magenta`), `references` (`{assetId, attemptId}`), `model3d`, `audio` and `qa`.

A patch merges into the stored style. `pixel`, `model3d`, `audio` and `qa` merge key by key. A new `preset` first drops `traits`, `negative`, `palette`, `pixel`, `model3d` and `audio`, so the new preset's values apply unless the same patch sets them.

`_style_signature` covers preset, traits, negative, palette, palette mode, pixel, light, screen, `model3d`, `audio` and references. A change to any of them returns `approval` to `draft`, adds 1 to `style.revision` and marks stale assets (see [Fingerprint](#fingerprint)). Only kinds that read `model3d` or `audio` go stale when those change.

`style.qa` is `{"vision": bool}`. Missing `qa`, or a `vision` value that is not a real bool, stays `true`. Only a bool `false` turns vision off. `qa` is outside the signature and the fingerprint, so toggling vision changes neither approval nor staleness.

Style approval takes `references`. Each must name an existing `ok` attempt (`reference_not_ok`). It sets `approved`, adds 1 to `style.revision` and checks staleness again.

### Asset

Kinds: `character`, `sprite`, `animation`, `item`, `icon`, `ui`, `tile`, `tileset`, `background`, `vfx`, `sfx`, `music`, `jingle`, `voice`, `model3d`, `character3d`.

Statuses: `pending`, `generating`, `review`, `approved`, `rejected`, `failed`, `stale`. The producer sets `generating` when it starts an asset, `review` after it stores a candidate, and `pending` after a failed attempt or a cut step. `failed` is valid and produce treats it as open. The producer does not set it.

- Approve needs an `ok` attempt (`attempt_not_ok`). It clears the previous approved decision and sets `approved`.
- Reject needs a note (`note_required`). If the rejected attempt was the approved one, the asset becomes `rejected`. Otherwise an asset with an approved attempt stays `approved`. The newest rejection note enters the next prompt as `Fix: <note>`.
- Approve, reject and unlock check the other assets for staleness again. The decided asset is not made stale by its own decision.
- A locked asset never goes stale. Lock does not change status.

An asset patch may set `name`, `description`, `tags`, `spec`, `notes` and `candidates`. `spec` replaces the whole spec. Status is not one of those keys. `dependsOn` is filled from `spec.character`.

### Attempt

An attempt stores `id`, `createdAt`, `status` (`ok` | `failed`), `inputs` (16 hex chars), `files`, `metrics`, `warnings`, `provenance`, `decision` and `note`. A failed attempt keeps its error in `note`.

`files` maps plain keys (`^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`) to workspace-relative POSIX paths. A backslash becomes `/`. A leading `/`, a drive letter, an empty part or `..` is 422 `invalid_attempt_file`.

One candidate keeps the step's attempt id and folder. N > 1 candidates are `<attemptId>-a1` … `<attemptId>-aN` in `<attemptId>/a1/` …. Each is its own attempt with its own files, metrics and warnings. The job step's `attemptId` is only the prefix. Sfx is the exception: its variants are files `"1"`, `"2"`, … inside one attempt, and it ignores `candidates`.

`add_attempt` appends, or replaces an attempt with the same id in place (a resumed step reuses its id). It does not change status. Above 12 attempts, the oldest rejected or failed ones are dropped. The approved attempt and undecided `ok` attempts stay, so an asset can hold more than 12.

After a success, tool outputs named `<assetId>-*` in the workspace root move into `<attemptId>/raw/`. A file that matches a longer sibling id stays for that sibling.

### Seeds

`spec.seed` is a whole number from 0 (`invalid_seed` otherwise). Normalising keeps it. Without it, generators use 1. `0` is honoured.

| Generator | Seed |
|---|---|
| Stills, strips, 3D concept | One image call at `seed`, batch = candidates |
| H3 animation, VFX, mesh | Candidate `aN` uses `seed + N - 1` |
| Tile, tileset, background | Candidate i (from 0) uses `seed + 1000·i`. Tile variant k and background layer k add k |
| Music, jingle | Candidate i (from 0) uses `seed + i` |
| Sfx | Variant n uses `seed + n - 1` |
| Voice | Candidate i, line n uses `seed + i·lines + n - 1` |

### Warnings

Warnings never block an attempt. Each new warning is `{code, message}`, plus `file`, `candidate` or `ref` when those apply. `seam_visible` carries `file`. `duplicate_of` carries `ref` (the other asset id). A failed Ogg loop encode is `{code: "ogg_fallback", message}` and the message is the ffmpeg sentence. Readers still accept a legacy string.

| Code | When |
|---|---|
| `loop_not_closed` | H3 loop error above 0.05. The J0 trial table wins over the brief's 0.5. |
| `identity_drift` | OKLab color-histogram distance of opaque pixels, first frame to the middle frame, above 0.20. Pose change is `metrics.poseChange` and does not warn. |
| `foot_drift` | H3 only. The feet move more than 20% of the frame width. |
| `halo` | Halo above 2% **and** the raw frame corners are still the screen colour. Otherwise `haloPct` is `None` and there is no warning. |
| `strip_count_mismatch` | A strip yielded a different number of figures than requested. |
| `loop_seam` | Music only. Wrap sample jump above 0.05, or RMS change above 2 dB between the first and last 50 ms. |
| `loop_no_downbeats` | Music without a usable downbeat pair. The loop is cut on a four-bar grid from the tempo. |
| `loudness_off_target` | Music, jingle or voice still more than 1 LU from its target after leveling. |
| `sfx_silent` | An sfx variant is silent. |
| `over_budget` | Mesh triangles more than 10% above `maxTriangles`. |
| `triangles_unknown` | The mesh triangles could not be counted. |
| `clip_missing` | A wanted rig clip is not in the rigged GLB. |
| `orbit_empty` | A multiview orbit gave no views. The mesh uses the single image. |
| `seam_visible` | Seam error still above 1.5 after the second heal. Object. |
| `style_mismatch` | Stills only. Style score 1 or 2. |
| `style_check_unavailable` | `analyze` failed, timed out, is paused, or gave no score from 1 to 5. |
| `style_check_failed` | The style check raised. Object. |
| `duplicate_of` | Stills only. dHash distance 6 or less to another **approved** asset of the same kind. `ref` is that id. |
| `ogg_fallback` | Music or jingle. ffmpeg could not write the Ogg loop, so the WAV remains. |

### Limits

- 500 assets per game (`too_many_assets`).
- 12 attempts per asset, pruned as above.
- Library file at most 50 MiB (`too_large`).
- Ids at most 64 characters.
- Default candidates: character 3, sprite 2, animation 1, item 3, icon 3, ui 2, tile 2, tileset 2, background 2, vfx 1, sfx 1, music 2, jingle 2, voice 1, model3d 2, character3d 1. A produce call may set `candidates` 1–8 for that job. A JSON list item may set 1–8.

## Kinds and produce order

| Kind | Spec (defaults) | Chain |
|---|---|---|
| `character` | `role` player/enemy/npc/boss, `heightPx` (style sprite height), `facing: "right"`, optional `kitId` | Qwen still on the screen colour, key, crop, pixel or illustration post, placed on the cell |
| `sprite` | optional `character`, `pose`, `heightPx` | Same, with the approved character as a reference |
| `animation` | `character` (required), `action`, `frames`, `fps`, `loop`, `method` `h3`/`strip`, `mirror` true | One H3 clip per candidate, or one batched Qwen strip, then a sheet |
| `item` | `sizePx` 32, optional `anim` spin/bob/glow with `frames` 8 | Still, or a strip when it animates |
| `icon` | `sizePx` 32, `frame` none/round/square | Still |
| `ui` | `element` button/panel/bar/frame/cursor, `widthPx` 96, `heightPx` 32, `nineSlice` true | Still plus `nine.json`. Every UI asset gets `nine.json` |
| `tile` | `sizePx` (style tile), `variants` 1 | Qwen texture at 1024, seam heal, pixel post. Variants are `main`, `variant-2`, … |
| `tileset` | `layout: "platform-3x3"`, `sizePx` | One chunk keyed and cut into nine cells. The centre heals at 1024. `tiles.json` names the cells |
| `background` | `widthPx` 640, `heightPx` 360, `layers` 3, `loopX` true, `method` separate/layered | Separate layers. `layered` without `qwen_image_layered_20B` fails `model_not_installed`; with it, it still runs the separate path |
| `vfx` | `effect`, `frames` 12, `fps` 18, `sizePx` 64, `blend` add/alpha | H3 clip on black, alpha from the brightest channel, a centred sheet |
| `sfx` | `variants` 3, `seconds` 1.0, `engine` mmaudio/retro, `retroPreset`, optional `trigger` | MMAudio, or the CPU sfxr synth. Without `engine`, a pixel preset plus a keyword such as jump or coin picks `retro` |
| `music` | `loopSeconds` 60, optional `bpm`, `mood` | ACE-Step, downbeat loop, crossfade, LUFS |
| `jingle` | `seconds` 4, `mood` victory/defeat/levelup/custom | ACE-Step, cut on the nearest downbeat, 300 ms fade |
| `voice` | `character` (required), `lines`, optional `traits` | `generation.speech` with the character kit's voice, else voice design from `traits` |
| `model3d` | `maxTriangles`, `texture`, `multiview` false | Qwen concept, then Hunyuan3D |
| `character3d` | optional `character`, `profile` humanoid/quadruped/flying/prop/vehicle/serpentine, `clips`, `maxTriangles`, `texture` | Mesh plus `model3d.rig` |

Produce order, low rank first: characters; then sprite, item, icon, ui, tile, tileset, background; then animation and vfx; then model3d and character3d; then sfx, music, jingle and voice. An asset whose dependency is not **approved** is skipped with `waiting_dependency`. It is not approved for you.

## List and production

`POST /api/v1/games/{id}/assets/from-list` takes `text` (lines), `csv` or `items` (JSON). `check: true` returns `{items, problems, estimate}` and writes nothing. Without `check`, any problem is 422 `invalid_list` with the same `problems`. `replace: true` with no item adds `empty_list`. A problem is `{line, code, message}`. Codes: `unknown_kind`, `invalid_line`, `unknown_option`, `invalid_spec`, `unknown_action`, `missing_character`, `size_not_on_grid`, `duplicate_id`, `too_many_assets`, `model_not_installed`, `empty_list`.

`estimate` is `{minutes, source, byKind}`. Each generator gives step counts (`image`, `h3`, `h3_turbo`, `music`, `sfx`, `3d`, `rig`) that already include candidates. A step costs the median of this workspace's last 30 samples, else the J0 trial value, else a default. `source` is `history(n)`, `trial` or `defaults`. A retro sfx costs no GPU step. When an asset finishes, its wall time is split over its steps in proportion to their estimate.

`POST /api/v1/games/{id}/produce` takes `asset_ids`, `kinds`, `rerender` and `candidates`. It picks `pending`, `rejected` and `failed` assets. `rerender` adds unlocked `stale` assets and `review` assets named in `asset_ids`. Steps run in produce order, one asset at a time. A step is `queued`, `running`, `done`, `failed` or `skipped` (`reason` `not_open` or `waiting_dependency`). One failed asset does not stop the batch.

A job is `queued`, `running`, `cancelling`, then `completed`, `failed`, `cancelled` or `interrupted`. One job per game may be active: start, style sheet and resume answer 409 `already_running`.

- Cancel sets `cancelling` with the message “Stopping; resume to continue”. A step cut while it waits on a tool goes back to `queued`, and its asset to `pending`. The job ends `cancelled`.
- Resume returns an active job unchanged. Otherwise it queues unfinished steps, steps a shutdown cut, and `waiting_dependency` steps whose dependencies are now approved. Attempt ids stay the same.
- After a restart, a job that says `running` without a live worker becomes `interrupted`.

`POST .../style/sheet` adds the samples `style-sample-character`, `-item`, `-tile` and `-background` when they are missing, then produces only those.

## Algorithms

### One scale

The H3 start frame comes from `compose_start_frame` with `heightFrac` 0.62 and `feetFrac` 0.85. Every frame of an animation uses one scale, measured on its first frame. Frames are not refit one by one.

### Pixel post (`game_pixel.to_pixel`)

1. `Image.BOX` down by the integer scale.
2. Alpha to 0 or 255 at 128. An opaque pixel with fewer than two opaque neighbours is dropped.
3. With ordered dither, a 4×4 Bayer offset moves the colour first.
4. Opaque pixels snap to the palette in OKLab. A free palette or an empty one uses median cut.
5. Without dither, a colour that matches none of its eight neighbours takes their most common colour.
6. Outline `dark-1px` (darkest palette colour), `black-1px`, or `none`.

`pixel_metrics` reports `offPalettePct` and `haloPct` (0–100, measured before quantization) and `colors`, the palette size.

Illustration uses Lanczos on premultiplied alpha and pulls chroma out of the fringe (`to_illustration`).

### Animation

`GAME_ANIMATION_DEFAULTS` is the J0 trial table. H3 is `minimax_h3` at 30 steps, `544x960`, 124 frames. A strip is one Qwen image at `1536x512`. `groupActions` is false: one step per action, clips are not shared. Walk, run, spin and bob default to `strip`. Other actions default to `h3`. An explicit `method` wins. An animated item always uses a strip.

The backdrop is `style.screen`. `auto` is green, or magenta when the character or animation description names green. The table's `screen` and `chroma` entries are not read. When the action ends in the standing pose (`endsInStance`), the clip starts and ends on the same image.

An H3 loop takes the cycle `find_cycle` finds at the clip's frame rate. Strip figures are split into blobs, keep the strip's ground line and are centred on their own feet. Metrics are `loopError`, `identityDrift`, `footDrift`, `haloPct`, `palette`, `scale`, `method`, `frames`, `fps`, `loop`, and `cycleFrames` (H3) or `stripFigures` (strip).

### Sheets

`pack_rows` puts one animation on one row. Cells share one size: the largest frame plus padding, rounded up to the pixel grid. Character, item and icon frames sit bottom-centre, pivot `{x: cell_w // 2, y: cell_h - 1}`. VFX frames are centred, pivot `{x: cell_w // 2, y: cell_h // 2}`.

The atlas is `{frames, meta}`. `meta` has `frameTags` (inclusive `from`/`to`), `pivot`, `loop` (per tag), `mirror`, `size` and `image`. VFX adds `blend`. Duration is `round(1000 / fps)` ms. An animation sets `meta.mirror` from `spec.mirror`.

### Tiles and backgrounds

A tile is painted at 1024, rolled so the seam is in the middle, inpainted under a seam mask and unrolled. A second pass runs when the seam error stays above 1.5. Tileset centres and background frames heal at 1024 square, the Qwen inpaint size that completes.

A background with `loopX` heals each raw layer before keying. `loopX: false` skips the heal. Layer 0 is the opaque sky. Each later layer gets a depth phrase (far, middle, near), is keyed, cut to its visible rows and set on the bottom edge. Parallax factors are 0.1, 0.3, 0.6, and 1.0 for the last layer.

### Audio

Music and jingles send ACE-Step `[Instrumental]` as lyrics and the description as `alt_prompt`. Music asks for `loopSeconds` plus four bars plus 8 s.

`best_loop` returns `(start, end_exclusive, score, xf)`. It picks a downbeat pair a multiple of four bars long near the target, scored on chroma and MFCC similarity at the seam. `xf` is one mean bar. `render_loop` cuts `y[start:end]` with a linear crossfade of `xf` samples.

The stored music WAV is the loop itself. Its `smpl` chunk is `0 .. len-1`, end inclusive. Leveling to `musicLufs` keeps the chunk. The Ogg carries `LOOPSTART=0` and `LOOPLENGTH=len`. Metrics `loopStart` and `loopEnd` are sample indices.

A jingle is cut on the downbeat nearest `seconds` and faded out over 300 ms. Sfx are trimmed, faded, made mono, resampled to `sampleRate`, then peak-normalised to `sfxPeakDb` (at most 0 dBFS). Voice lines are mono at -16 LUFS.

### Meshes

Hunyuan3D gets `reduce_face: true` and `target_face_num` from `spec.maxTriangles`, else `style.model3d.maxTriangles`, else 3000. `texture_resolution` is `spec.texture` (the service clamps it to 256–1024), and the candidate's seed. Its preset is `multiview` with `multiview`, `quality` for a `painted` look, else `balanced`. A `model3d` reuses the approved character plate when there is one. A `character3d` always generates its own concept: "T-pose, front view, arms horizontal, plain light grey background", with the approved character's art as the image reference when there is one, so the mesh keeps the approved look. The orbit sends that image as `image_refs`, which is what the character-sheet engine requires.

Rig clips are `spec.clips`, else the role's clips. A clip takes the engine's nearest name (humanoid `attack` → `punch`, procedural `punch` → `attack`). Only clips the engine accepts are sent, else `idle`. The others come back as `clip_missing`.

Triangles are counted per primitive mode: lists `n / 3`, strips and fans `n - 2`. Files are `model`, `rig` for a character, and `concept` when it was generated. Metrics are `triangles`, `bones`, `clips` and `missingClips`. A corrupt GLB, a GLB without a mesh, or a rig without a skin fails the attempt. The humanoid rig wants a front-facing model. J8 saw a side-view mesh fail with `not_humanoid`.

### Style check

Only stills are checked: character, sprite, item, icon, ui, tile and tileset. Sheets (animation, vfx, an animated item), backgrounds, audio and 3D are skipped. The candidate is its `main` PNG.

`note_style` sends `analyze` up to three prompt references (style references first) whose files exist, then the candidate, all as `/api/v1/file` URLs. Without a reference, no call is made. Each call has a new `request_id` and at most 120 s. A timeout or a transport error pauses vision for 300 s. A cancelled job stops the wait.

A score from 1 to 5 is rounded and stored as `metrics.styleScore`. 1 or 2 also adds `style_mismatch`. No score, a timeout or a pause adds `style_check_unavailable`. If the check raises, the producer adds `style_check_failed` and keeps the attempt. `style.qa.vision: false` skips the call only.

The producer saves every candidate and marks the step done before it runs the check. `stamp_attempt` then writes each candidate's score and warnings; it keeps the files, the decision and the asset status. A restart during the check keeps the candidates without a score.

The duplicate check always runs. It hashes the image over black with `game_image_ops.dhash` (64 bits). A flat image has no hash. A distance of 6 or less to the approved still of another asset of the same kind adds `{code: "duplicate_of", ref: id}`.

### Fingerprint

`asset_inputs` is `sha1` of sorted JSON, first 16 hex chars. The payload is kind, spec, description, notes, the style keys `preset`, `traits`, `negative`, `palette`, `paletteMode`, `pixel`, `light` and `screen`, `model3d` or `audio` when the kind uses them, the `approvedAttemptId` of each dependency, `style.references` minus the asset's own entry, and `GENERATOR_VERSION[kind]`. An asset approved as a style reference therefore does not go stale.

`stale_assets` returns unlocked approved or rejected assets whose stored digest differs. The stored digest is the approved attempt's, else the latest decided attempt's.

## Export

`POST /api/v1/games/{id}/export` packs the approved attempt of every `approved` asset. It reads the files outside the library lock, so a produce job can keep saving. Only the `exports` row is written under the lock. If that write fails, the zip is removed.

The zip is written beside its final name and renamed, so a failed export leaves no partial file. The name is `game-exports/<id>-r<revision>.zip`, then `-2`, `-3`, … when taken. Entries live under `<id>-r<revision>/`. Entry names are sanitised. A name already used gets `-2`, `-3`, …

No approved asset with a file to pack is 409 `nothing_to_export`, and no zip is written.

The reply is `{file, url, counts, missing}`. `counts` tallies packed assets per kind plus `total`. `missing` lists every asset that is not `approved` as `{id, kind, status}`. It also lists approved assets that lost files as `{id, kind, status, problem, files}`, with `problem` `no_approved_attempt`, `not_packed` or `files_missing`.

| Kind | In the zip |
|---|---|
| `character` + `animation` | `characters/<id>/<id>.png` and `<id>.json`, one row per animation in catalog order; `<id>-base.png` |
| `sprite`, `ui`, `tile`, `tileset` | `sprites/`, `ui/`, `tiles/`; variants as `<id>-variant-N.png`; `nine.json` or `tiles.json` as `<id>.json` |
| `icon` | `icons/<id>.png`, or one `icons/<tag>.png` sheet when several icons share their first tag |
| `item` | `items/<id>.png`, plus `<id>.json` when it animates |
| `background` | `backgrounds/<id>/layer-N.png` and `parallax.json` |
| `vfx` | `vfx/<id>.png` and `vfx/<id>.json` |
| `model3d`, `character3d` | `models/<id>.glb` (the rig when there is one) |
| audio | `audio/sfx/`, `audio/music/`, `audio/jingles/`, `audio/voice/`, `audio/loops.json` |
| all | `manifest.json` (`hocuspocus.game-pack` v1), `provenance.json`, `README.txt` |

- A sheet uses `spec.fps`, else the fps recorded on the attempt, else 8. It uses `spec.loop`, else the recorded loop.
- A character sheet has `meta.mirror` true unless the view is `topdown` or one of its animations sets `mirror: false`.
- `parallax.json` is rewritten with the packed layer names.
- A VFX atlas keeps the generator's centre pivot. `README.txt` says so.
- `audio/loops.json` lists each music WAV as `{file, loopStart, loopEnd, bpm, lufs}`. `loopEnd` is inclusive.
- A stored Ogg is copied. Otherwise each WAV is encoded to Ogg when soundfile can. A music Ogg gets `LOOPSTART` and `LOOPLENGTH`, or is not written.

## UI

J15 landed with #901. The panel sections are setup, style, cast, list, produce, review, play and export. Play draws approved assets on a 640×360 canvas (integer scale, pixelated). Missing sprites are named rectangles and listed. It uses only approved attempts and plays sheets by their frameTags, durations, loop, pivot and mirror. Keys reach it only while the canvas has focus. Export lists approved and not-approved assets and writes the zip. Play has no MCP tool. Export is `game.export`.

## Release notes

`ui/src/whatsNew.ts` is one short line per **merged** PR. Bumping the first `pr` shows the welcome again. The newest entry is PR 813. #887, #894 and #901 are merged without a welcome line. The root `README.md` has no What’s new section (`## What you can do` is the feature list).
