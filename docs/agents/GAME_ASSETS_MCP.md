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
| `game.presets` | no | `GET /api/v1/games/presets` |
| `game.list` | no | `GET /api/v1/games` |
| `game.get` | no | `GET /api/v1/games/{id}` |
| `game.create` | yes | `POST /api/v1/games` with `{workspace, game}`. An existing explicit `game.id` is 409 `game_exists`. |
| `game.update` | yes | `PUT /api/v1/games/{id}` with `patch` and `base_revision` |
| `game.style.sheet` | yes | `POST /api/v1/games/{id}/style/sheet` |
| `game.style.approve` | yes | `POST /api/v1/games/{id}/style/approve` with `references[{asset_id, attempt_id}]` |
| `game.assets.from_list` | yes | `POST /api/v1/games/{id}/assets/from-list`. `check: true` does not write. Exactly one of `text` (format `lines` or `csv`) or `items` (format `json`). `replace: true` deletes the assets the list leaves out. |
| `game.asset.update` | yes | `PATCH /api/v1/games/{id}/assets/{asset_id}`. A `spec` patch replaces the whole spec. |
| `game.asset.approve` | yes | `POST .../approve` with `attempt_id` |
| `game.asset.reject` | yes | `POST .../reject` with `attempt_id` and a required `note` |
| `game.asset.lock` | yes | `POST .../lock` with `locked` |
| `game.produce` | yes | `POST /api/v1/games/{id}/produce` |
| `game.produce.status` | no | `GET /api/v1/games/produce/jobs/{job_id}`. Optional `wait_s` ≤ 120. |
| `game.produce.cancel` | yes | `POST .../jobs/{job_id}/cancel` |
| `game.produce.resume` | yes | `POST .../jobs/{job_id}/resume` |
| `game.export` | yes | `POST /api/v1/games/{id}/export`. Returns `{file, url, counts, missing}`; only approved assets are packed. |

Attempt ids come from `game.get` (`assets[].attempts[].id`). A job that renders several candidates stores `<attemptId>-a1`, `<attemptId>-a2`, …; the step's `attemptId` is only the prefix.

## Errors

The tool error is the route's own `{code, message, problems}` plus `retryable`.

- 409 `revision_conflict`: the `base_revision` is stale. Read the game again and retry with its revision.
- 409 `already_running`: `game.produce`, `game.style.sheet` or `game.produce.resume` while another job for that game is active. Poll that job.
- 409 `game_exists`: not retryable. Read the existing game or create one with another id.
- 422: `problems` lists each field, list line or library rule to fix (`invalid_list`, `invalid_spec`, `reserved_id`, `invalid_style`, …).
- 404: the game, asset, attempt or job is not there. A 502 `server_unavailable` means the local server did not answer; retry later.

Long renders return a job id. Poll `game.produce.status`; `jobs.wait` reads the generation queue, not game jobs. Game tools take no `intent_id`: a cancelled or interrupted job continues with `game.produce.resume`, and finished steps are not repeated.

The profile also includes `generation.image`, `generation.video`, `generation.sfx`, `generation.music`, `generation.speech`, `studio.key`, `jobs.wait`, `jobs.leftovers`, `jobs.resume`, `jobs.discard`, `characters.list`, `characters.get`, `characters.save`, `model3d.generate`, `model3d.status`, `model3d.rig`, `model3d.rig.status`, `model3d.animate`, `media.options` and `scenes.assets.inspect`.
