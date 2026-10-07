# Game assets

One studio holds the art, sound and meshes of one game. The tuned view is a side-view platformer: characters face right, and left is the same sprite mirrored. `topdown` is stored and is not tuned. Styles are traits (palette, line, light, shading). Presets, prompts and this document do not name a brand, console, studio or artist.

The pack is generic. It is PNG plus a TexturePacker-style atlas, GLB, WAV/OGG with loop points, and `manifest.json`. There is no Godot `.tres` and no Unity `.meta`.

Approving a style and approving or rejecting an asset are human decisions. No flow approves itself. The acceptance playthrough may approve inside `game-lab` only when the person asked for that playthrough, and the report must say so. That playthrough has not been run. See [GAME_ASSETS_ACEPTACION_2026-10-07.md](GAME_ASSETS_ACEPTACION_2026-10-07.md).

Generated PNG, WAV and GLB files stay in the workspace under `app/outputs/` (gitignored `outputs/`). They are not committed and installers do not download them.

The board is [GAME_ASSETS_BOARD.md](GAME_ASSETS_BOARD.md). The agent guide is [../agents/GAME_ASSETS_MCP.md](../agents/GAME_ASSETS_MCP.md).

## Names

| What | Name |
|---|---|
| Library | `<workspace>/.game-library-v1.json` |
| Attempt files | `<workspace>/game/<gameId>/<assetId>/<attemptId>/` |
| Jobs | `<workspace>/.game-jobs-v1/<jobId>.json` |
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

A game has `id` (unique slug), `title`, `revision`, `createdAt`, `updatedAt`, `genre` (`platformer` | `topdown` | `other`), `view` (`side` | `topdown`), `style`, `assets` and `exports`.

`revision` starts at 0 and increases by 1 on a library write that goes through `_bump` (create, update, approve, reject, lock, produce attempt). `PUT` and `PATCH` send `base_revision`. A mismatch is HTTP 409. Export appends an `exports` row and does **not** bump `revision`. A second export at the same revision is `game-exports/<id>-r<revision>-2.zip`. The folder inside the zip stays `<id>-r<revision>/`.

`exports` rows are `{id, revision, file, createdAt, counts}`. `counts` is a per-kind tally plus `total`. The HTTP response is `{file, url, counts, missing}`. `missing` lists every asset whose status is not `approved`, as `{id, kind, status}`.

### Style

`normalize_style` keeps `revision`, `approval` (`draft` | `approved`), `approvedAt`, `preset`, `traits`, `negative`, `palette`, `paletteMode` (`locked` | `free`), `pixel`, `light` (`top-left` | `top` | `front`), `screen` (`auto` | `green` | `magenta`), `references` (`{assetId, attemptId}`), `model3d`, `audio` and `qa`.

`style.qa` is `{"vision": bool}`. Missing `qa`, or a `vision` value that is not a real bool, stays `true`. Only a bool `false` turns the style check off. `qa` is **not** part of `_style_signature`, so toggling vision does not send an approved style back to `draft`. It is also **not** part of the asset fingerprint in `game_inputs.py`.

A style change that does touch the signature (preset, traits, negative, palette, palette mode, pixel, light, screen, references, and `model3d` or `audio` when those kinds apply) returns `approval` to `draft` and can mark unlocked approved or rejected assets `stale`.

### Asset and attempt

Kinds: `character`, `sprite`, `animation`, `item`, `icon`, `ui`, `tile`, `tileset`, `background`, `vfx`, `sfx`, `music`, `jingle`, `voice`, `model3d`, `character3d`.

Statuses: `pending` → `generating` → `review` → `approved` | `rejected`, plus `failed` and `stale`. `failed` goes back to `pending` on a new attempt. An approved or rejected asset becomes `stale` when its fingerprint changes, unless `locked` is true. `add_attempt` does not change status. The producer sets `review` after a successful attempt and `pending` after a failed one.

An asset patch may set `name`, `description`, `tags`, `spec`, `notes` and `candidates`. Status is not one of those keys.

An attempt stores `id`, `createdAt`, `status` (`ok` | `failed`), `inputs` (16 hex chars), `files`, `metrics`, `warnings`, `provenance`, `decision` and `note`. A reject note is required and is fed into the next prompt.

**Warnings are not one shape.** Animation, audio, 3D and the style check emit string codes. Tile and background seam checks still emit `{code, message}` objects. Readers accept both. Nothing in this list blocks the batch.

| Code | When |
|---|---|
| `loop_not_closed` | Animation loop error above 0.05 (5%). The trial table wins over a 0.5 cutoff. |
| `identity_drift` | Above 0.20. The figure includes pose change, so it does not by itself separate a good cycle from a bad one. |
| `foot_drift` | Foot movement above 20% of the width. |
| `halo` | Halo above 2% **and** the raw frame corners are still the screen color. `halo_pct` is `None` once the backdrop is gone, and then this warning is not emitted. |
| `strip_count_mismatch` | A strip yielded fewer figures than requested. |
| `loop_seam` | Music or jingle sample jump above 0.05, or RMS change above 2 dB. |
| `over_budget` | Mesh triangles more than 10% above `maxTriangles`. |
| `clip_missing` | A requested rig clip is absent. |
| `seam_visible` | Tile seam error above 1.5. Object form: `{code, message}`. Does not block. |
| `style_mismatch` | Vision score 1 or 2. |
| `style_check_unavailable` | `analyze` is down, or the reply has no score from 1 to 5. |
| `duplicate_of:<id>` | dHash distance of 6 or less against another **approved** asset of the same kind. |

### Limits

- 500 assets per game (`MAX_ASSETS`).
- 12 attempts per asset (`MAX_ATTEMPTS`). Older attempts drop off the end.
- Library file at most 50 MiB.
- Default candidate counts: character 3, sprite 2, animation 1, item 3, icon 3, ui 2, tile 2, tileset 2, background 2, vfx 1, sfx 1, music 2, jingle 2, voice 1, model3d 2, character3d 1.

## Kinds and produce order

| Kind | Spec that matters | Chain |
|---|---|---|
| `character` | `role` player/enemy/npc/boss, `heightPx`, `facing: "right"`, optional `kitId` | Qwen on chroma, cutout, pixel or illustration post |
| `sprite` | optional `character`, `pose`, `heightPx` | Same, with the character as a reference |
| `animation` | `character`, `action`, `frames`, `fps`, `loop`, `method` `h3` or `strip` | H3 clip or one Qwen strip, then a sheet |
| `item` | `sizePx` 32, optional `anim` | Still, or a strip when it animates |
| `icon` | `sizePx` 32, `frame` none/round/square | Same family as an item |
| `ui` | `element`, size, `nineSlice` | Cutout plus `nine.json` when sliced |
| `tile` | `sizePx`, `variants` | Qwen texture, inpaint heal, palette reduce |
| `tileset` | `layout: "platform-3x3"`, `sizePx` | Nine terrain pieces and a seam check |
| `background` | size, `layers`, `loopX`, `method` | Separate layers. `qwen_image_layered_20B` is not installed, so `layered` is not the live path |
| `vfx` | `effect`, frames, fps, size, `blend` add/alpha | H3 on black, then alpha and a sheet |
| `sfx` | `variants`, `seconds`, `engine` mmaudio/retro, optional `trigger` | Variants are files `"1"`, `"2"`, … inside one attempt |
| `music` | `loopSeconds`, optional `bpm`, `mood` | ACE-Step, bar cut, LUFS. Loop points are **sample indices** |
| `jingle` | `seconds`, `mood` | Short ACE-Step, bar cut, fade |
| `voice` | `character`, `lines`, optional `traits` | `generation.speech` |
| `model3d` | triangle cap, texture, `multiview` | Qwen concept, then Hunyuan. An empty orbit does not fail the attempt |
| `character3d` | optional `character`, `profile`, `clips` | Mesh plus `model3d.rig`. A side-view mesh fails the front-facing humanoid check (`not_humanoid`) |

Produce order, low rank first: characters; then sprite, item, icon, ui, tile, tileset, background; then animation and vfx; then model3d and character3d; then sfx, music, jingle and voice. An asset whose dependency is not **approved** is skipped with `waiting_dependency`. It is not approved for you.

`dependsOn` is filled from `spec.character` and `spec.source` while normalizing.

## Algorithms

### One scale

`compose_start_frame` uses `height_frac` 0.62 and `feet_frac` 0.85. Every frame of a character uses that one scale. Frames are not refit one by one.

### Pixel post (`game_pixel.to_pixel`)

1. `Image.BOX` down to the pixel grid.
2. Alpha to 0 or 255 at 128.
3. Opaque pixels quantize to the palette in OKLab. An empty palette uses median cut.
4. Specks and lonely colors are cleaned.
5. Outline `dark-1px`, `black-1px`, or `none`.
6. Ordered dither only when the style asks for it.

`pixel_metrics` reports `offPalettePct`, `haloPct` and `colors` on a 0–100 scale, measured before quantization.

Illustration uses Lanczos on premultiplied alpha and pulls chroma out of the fringe (`to_illustration`).

### Animation defaults

`GAME_ANIMATION_DEFAULTS` is the trial table. Video model `minimax_h3` at 30 steps, `544x960`, 124 frames requested, magenta `#FF00FF`. `groupActions` is false: one step per action, clips are not shared. Walk, run, spin and bob default to `strip`. Every other action defaults to `h3`. An explicit `h3` or `strip` wins. Closed loops use the same start and end image when the action ends in the standing pose.

`pack_rows` puts one animation on one row. The pivot is the bottom center of the cell, `{x: cell_w // 2, y: cell_h - 1}`. The atlas is `{frames, meta}` with `frameTags`, `pivot`, `loop`, `size` and `image`. Duration is milliseconds.

### Audio

WAV keeps its `smpl` loop chunk. OGG is copied when the attempt stored one, otherwise encoded when the encoder is present. Export writes `audio/loops.json` with `{file, loopStart, loopEnd, bpm, lufs}`. `loopStart` and `loopEnd` are sample indices.

### Meshes

Hunyuan is asked to stay inside the triangle budget (`reduce_face` / `target_face_num`, default cap 3000). `over_budget` fires above 110% of that cap and does not block. Files are `model` and, for a character, `rig`. `metrics.clips` is the list of clip names.

### Style check

After a successful image attempt, `note_style` calls inherited `analyze` with up to three style references and the candidate last. Image kinds are character, sprite, item, icon, ui, tile, tileset, background, animation and vfx. Sfx, music, jingle, voice, model3d and character3d are skipped. The candidate file is `main`, else `preview`, else `sheet`, else a `layer*` PNG.

The prompt asks for JSON `{"score": n, "reason": "short"}` from 1 to 5. Parsing takes the first `{` through the last `}`. Score 1 or 2 adds `style_mismatch` and `metrics.styleScore`. A missing analyzer adds `style_check_unavailable` and does not fail the batch. `style.qa.vision: false` skips the call. Duplicates use a 64-bit dHash (9×8 grayscale, each pixel against the one on its right). Distance ≤ 6 against another approved asset of the same kind adds `duplicate_of:<id>`. The asset is not compared with itself. An unreadable image is skipped.

### Fingerprint

`asset_inputs` is `sha1` of sorted JSON, first 16 hex chars. The payload is kind, spec, description, notes, the style keys listed above, `model3d` or `audio` when the kind uses them, the `approvedAttemptId` of each dependency, `style.references`, and `GENERATOR_VERSION[kind]`. `stale_assets` returns unlocked approved or rejected assets whose stored digest differs.

## UI

The panel sections are setup, style, cast, list, produce, review, play and export. Play draws approved assets on a 640×360 canvas (integer scale, pixelated). Missing sprites are named rectangles and listed. Export lists approved and not-approved assets and writes the zip. Play has no MCP tool. Export is `game.export`.

## Release notes

`ui/src/whatsNew.ts` is one short line per **merged** PR. Bumping the first `pr` shows the welcome again. The newest entry is PR 813. These game-asset changes are unmerged drafts, so no line was added. The root `README.md` has no What’s new section (`## What you can do` is the feature list). Add the welcome line after the series merges, not before.
