# Game assets over MCP

Profile `game` is served at `/api/v1/mcp/game`. It lists the `game.*` tools plus the local generation, job, character and Model3D tools those steps call. Start with `game.guide`; its `guide` is `app/shared/game_agent_guide.md` (list syntax, statuses, attempt ids, errors).

Every call is `{version: 1, input: {...}}`. The handler checks the call against the tool schema before it reaches a route: unknown fields, a string where a boolean or an integer belongs, an unknown `kinds` value, or a game id of `presets` or `produce` answer 422 `invalid_command` with `problems: [{field, message}]`. `workspace` is required except on `game.presets`. Game and asset ids are lowercase slugs of at most 64 characters.

## Flow

`game.guide` → `game.create` → `game.style.sheet` → the user approves → `game.style.approve` → `game.assets.from_list` with `check: true` → the same call without `check` → `game.produce` → `game.produce.status` → the user reviews → `game.produce` again for animations → `game.export`.

Do not approve a style or an asset unless the user asked. Describe style by traits, not by a brand, console, studio or artist. Measure one asset before a large batch. `rerender` is only for stale assets, or for assets in review that the user asked to redo, named in `asset_ids`.

## Tools

| Tool | Mutates | Calls |
|---|---|---|
| `game.guide` | no | `GET /api/v1/games/{id}` when `game_id` is set. Returns `{guide, bible}`. |
| `game.presets` | no | `GET /api/v1/games/presets`. Returns `{presets, actions}`. |
| `game.list` | no | `GET /api/v1/games` |
| `game.get` | no | `GET /api/v1/games/{id}` |
| `game.create` | yes | `POST /api/v1/games` with `{workspace, game}`. An existing explicit `game.id` is 409 `game_exists`. Without an id, a title slug that is taken gets `-2`, `-3`, … |
| `game.update` | yes | `PUT /api/v1/games/{id}` with `patch` and `base_revision`. A style change returns the style to draft and marks unlocked approved or rejected assets stale. A new preset resets the keys the preset fills. |
| `game.style.sheet` | yes | `POST /api/v1/games/{id}/style/sheet`. Adds the four style samples when missing, then produces only those. |
| `game.style.approve` | yes | `POST /api/v1/games/{id}/style/approve` with `base_revision` and `references[{asset_id, attempt_id}]` (at most 20, each an `ok` attempt) |
| `game.assets.from_list` | yes | `POST /api/v1/games/{id}/assets/from-list`. `check: true` returns `{items, problems, estimate}` and does not write. Exactly one of `text` (format `lines` or `csv`) or `items` (format `json`). `replace: true` deletes the assets the list leaves out, and an empty list is refused (`empty_list`). |
| `game.asset.update` | yes | `PATCH /api/v1/games/{id}/assets/{asset_id}` with `base_revision`. A `spec` patch replaces the whole spec. `spec.seed` is a whole number from 0. |
| `game.asset.approve` | yes | `POST .../approve` with an `ok` `attempt_id` |
| `game.asset.reject` | yes | `POST .../reject` with `attempt_id` and a required `note`. An asset with another approved attempt stays approved. |
| `game.asset.lock` | yes | `POST .../lock` with `locked`. Unlocking checks staleness again. |
| `game.produce` | yes | `POST /api/v1/games/{id}/produce`. Pending, rejected and failed assets. `candidates` 1–8 applies to this job only. |
| `game.produce.status` | no | `GET /api/v1/games/produce/jobs/{job_id}`. Optional `wait_s` ≤ 120. |
| `game.produce.cancel` | yes | `POST .../jobs/{job_id}/cancel` |
| `game.produce.resume` | yes | `POST .../jobs/{job_id}/resume` |
| `game.export` | yes | `POST /api/v1/games/{id}/export`. Returns `{file, url, counts, missing}`; only approved assets are packed. |

Attempt ids come from `game.get` (`assets[].attempts[].id`). A job that renders several candidates stores `<attemptId>-a1`, `<attemptId>-a2`, …, each with its own files, metrics and warnings; the step's `attemptId` is only the prefix. Sfx variants are files inside one attempt.

`missing` lists every asset that is not approved as `{id, kind, status}`, and every approved asset that lost files with a `problem` and its `files`.

## Jobs

A job is `queued`, `running`, `cancelling`, then `completed`, `failed`, `cancelled` or `interrupted`. A step is `queued`, `running`, `done`, `failed` or `skipped` (`reason` `not_open` or `waiting_dependency`).

`game.produce.cancel` answers `cancelling` (“Stopping; resume to continue”). A step cut while it waits on a tool goes back to `queued`. `game.produce.resume` continues a cancelled, interrupted or failed job with the same attempt ids. It also runs `waiting_dependency` steps once their dependency is approved. An active job comes back unchanged.

## Errors

The tool error is the route's own `{code, message, problems}` plus `retryable`. `retryable` is true for a 409 other than `game_exists`, and for `server_unavailable`.

- 409 `revision_conflict`: the `base_revision` is stale. Read the game again and retry with its revision.
- 409 `already_running`: `game.produce`, `game.style.sheet` or `game.produce.resume` while another job for that game is active. Poll that job.
- 409 `game_exists`: not retryable. Read the existing game or create one with another id.
- 409 `nothing_to_export`: no approved asset has a file to pack. A retry fails the same way until something is approved.
- 422: `problems` lists each field, list line or library rule to fix (`invalid_list`, `invalid_spec`, `invalid_attempt_file`, `reserved_id`, `invalid_style`, …). A `text`/`items` that does not match `format` is 422 `invalid_list` before any route is called.
- 404: the game, asset, attempt or job is not there.
- 502 `server_unavailable`: the local server did not answer or is not ready. Retry later.

Long renders return a job id. Poll `game.produce.status`; `jobs.wait` reads the generation queue, not game jobs. Game tools take no `intent_id`: a cancelled or interrupted job continues with `game.produce.resume`, and finished steps are not repeated.

The profile also includes `generation.image`, `generation.video`, `generation.sfx`, `generation.music`, `generation.speech`, `studio.key`, `jobs.wait`, `jobs.leftovers`, `jobs.resume`, `jobs.discard`, `characters.list`, `characters.get`, `characters.save`, `model3d.generate`, `model3d.status`, `model3d.rig`, `model3d.rig.status`, `model3d.animate`, `media.options` and `scenes.assets.inspect`. `analyze` is not in this profile. The style check calls it on the full `/api/v1/mcp` endpoint through loopback.

## Style check

J16 is still being finished; details may change. Still attempts (character, sprite, item, icon, ui, tile, tileset) ask `analyze` for a score from 1 to 5 against up to three reference images. The candidate is the last image. Sheets, backgrounds, audio and 3D are not scored, and a still with no reference image is not either. The score is stored as `metrics.styleScore`. A score of 1 or 2 also adds `style_mismatch`. If `analyze` is down, times out or gives no score, the warning is `style_check_unavailable` and the batch continues. A timeout pauses scoring for five minutes. If the check raises, the attempt is kept with a `style_check_failed` object.

Set `style.qa.vision` to false to skip scoring. The default is true. Changing it does not reset style approval.

The duplicate check always runs on stills. A dHash within distance 6 of another approved asset of the same kind adds `duplicate_of:<id>`.

## Limits

500 assets per game. Above 12 attempts per asset, the oldest rejected or failed ones are dropped; approved and undecided attempts stay. A library file above 50 MiB is rejected. `candidates` is 1–8 per job. Export does not bump `revision`. A second zip at the same revision is `game-exports/<id>-r<revision>-2.zip`.

## Warnings

Warnings do not block. Most codes are strings: `loop_not_closed` (loop error above 0.05), `identity_drift`, `foot_drift`, `halo`, `strip_count_mismatch`, `loop_seam` (music), `loop_no_downbeats`, `loudness_off_target`, `sfx_silent`, `over_budget`, `triangles_unknown`, `clip_missing`, `orbit_empty`, `style_mismatch`, `style_check_unavailable`, `duplicate_of:<id>`. Two are objects: `{code: "seam_visible", message, file}` from tiles, tilesets and backgrounds, and `{code: "style_check_failed", message}`. Read both shapes.

An asset whose dependency is not approved is skipped with `waiting_dependency`. Do not approve it to unblock the batch unless the user asked.

## What this profile does not do

Play is a UI canvas. There is no `game.play` tool. The pack is PNG, atlas JSON, GLB and WAV/OGG. It does not write Godot or Unity project files. Only stills are style-scored. Walk, run, spin and bob default to a sprite strip. Other body actions default to one MiniMax H3 clip. Actions are not grouped into one clip.

## Acceptance

The full `game-lab` playthrough is allowed to approve a style and assets by MCP only when the user asked for that acceptance, and the report must say so. Construction tests must not approve anything. The 2026-10-07 report records that the playthrough was not run.
