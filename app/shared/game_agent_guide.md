# Making a game pack in HocusPocus (guide for agents)

This is how an agent with the `game` MCP profile builds a side-view game pack on the local machine.
Images, video, sound, speech and meshes stay on this computer. Do not invent brand, console, studio or artist names.
Describe a look by traits: palette, outline, shading, pixel grid.

## Flow

1. `game.guide` — read this guide and, with `game_id`, the bible (style, counts, references, what waits for review).
2. `game.create` — title, genre `platformer`, view `side`. Top-down is stored and is not tuned. Send an `id`
   (a lowercase slug of at most 64 characters, not `presets` or `produce`): a retry then answers 409 `game_exists`
   instead of creating a second game.
3. `game.style.sheet` — four samples (character, item, tile, background). The user looks at them.
4. `game.style.approve` — only after the user says the style is right. Send `{asset_id, attempt_id}` for the samples
   the user picked, with attempt ids read from `game.get`.
5. `game.assets.from_list` with `check: true` — problems and the estimate come back, nothing is written.
6. `game.assets.from_list` without `check` — write the list when the check was clean.
7. `game.produce` — pending, rejected and failed assets, in dependency order. Poll `game.produce.status` (`wait_s` at most 120).
8. The user reviews. `game.asset.approve` or `game.asset.reject` (a note is required; it enters the next prompt).
9. `game.produce` again for animations and anything still open. `rerender: true` only for stale assets, or for assets in review that the user wants redone, named in `asset_ids`.
10. `game.export` — ZIP of approved assets only. Every other asset, stale ones too, is listed in `missing`.

## The asset list

Send `text` (format `lines`, the default, or `csv`) or `items` (format `json`), never both.
`replace: true` deletes every asset the list leaves out, so send it only with the complete list.

- A line is `<kind> <id>: <description> | option | option`. Lines starting with `#` are skipped.
- Kinds: `personaje`/`character`, `sprite`, `anim`/`animation`, `objeto`/`item`, `icono`/`icon`, `ui`, `tile`,
  `tileset`, `fondo`/`background`, `efecto`/`vfx`, `sfx`/`sonido`, `musica`/`music`, `jingle`, `voz`/`voice`,
  `model3d`, `character3d`.
- `anim heroe: idle, andar, saltar` makes one animation per action, with ids `heroe-idle`, `heroe-walk`, …
- Options: `jugador`, `enemigo`, `npc`, `jefe`, `9-slice`, `retro`, `multivista`, `variantes N`, `capas N`, `N frames`, `tamano N`,
  `bucle N s`, `bpm N`, `metodo tira|h3`, `anim girar|flotar|glow`.
- CSV needs `kind` and `id` columns; `name`, `description` and `options` (split by `|`) are optional.
- A JSON item with `spec` and no `options` keeps that spec. Put `seed` (a whole number from 0) in `spec` to repeat a result.

Each problem is `{line, code, message}`. Codes: `unknown_kind`, `invalid_line`, `unknown_option`, `invalid_spec`,
`unknown_action`, `missing_character`, `size_not_on_grid`, `duplicate_id`, `too_many_assets`, `model_not_installed`.
A write with problems is refused with 422 `invalid_list` and the same list.

## Attempts, statuses and jobs

- Asset status: `pending`, `generating`, `review`, `approved`, `rejected`, `failed`, `stale`.
- Approve and reject take an attempt id from `game.get` (`assets[].attempts[].id`). With several candidates the
  ids are `<attemptId>-a1`, `<attemptId>-a2`, …; the job step's `attemptId` is only their prefix.
- Approving a new attempt makes assets built on the old one stale. Rejecting an attempt that is not the approved
  one leaves the asset approved. Approve, reject and unlock check the other assets for stale inputs again.
- A job is `queued`, `running`, `cancelling`, then `completed`, `failed`, `cancelled` or `interrupted`.
  A step is `queued`, `running`, `done`, `failed` or `skipped` (`reason`: `not_open` or `waiting_dependency`).
- `game.produce.cancel` stops the job; a step cut in its tool wait goes back to `queued`. `game.produce.resume`
  continues a cancelled, interrupted or failed job, and runs `waiting_dependency` steps once the dependency is approved.
- Game jobs are read with `game.produce.status`, not `jobs.wait`. Game tools take no `intent_id`.

## Errors

- 409 `revision_conflict` — read the game again and retry with its `revision`.
- 409 `already_running` — another job for this game is active. Poll it; do not start a second one.
- 409 `game_exists` — the id is taken. Read that game or pick another id; a retry fails the same way.
- 422 — `problems` lists every field or line to fix. 404 — the game, asset, attempt or job is not there.

## Rules

- Never approve a style or an asset unless the user asked. No step approves itself.
- Styles are traits. Do not name a brand, a console, a studio or an artist.
- Measure one asset before a large batch. Read the estimate from the check.
- `rerender` only for stale assets, or for assets in review the user asked to redo (name them in `asset_ids`). A locked asset stays put when the style changes.
- Characters face right. Left is the mirrored sprite. One scale for every frame of a character.
- Walk and run, and the item spin and bob, default to a still strip. Other actions default to one video clip. Do not group actions.
- The pack is PNG plus atlas JSON, GLB, WAV/OGG with loop points, and `manifest.json`. No engine project files.
- Generated media stays in the workspace. Do not commit PNGs, WAVs or GLBs.

## What the bible contains

`game.guide` returns `{guide, bible}`. The bible has the preset, traits, palette, pixel grid and audio settings,
counts by kind and status, the approved style references, and the first assets in `review`, which wait for a person.
A game with hundreds of assets stays under 6 KB: the rest of the review queue is `awaitingMore`.
