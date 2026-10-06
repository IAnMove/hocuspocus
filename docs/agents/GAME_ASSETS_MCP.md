# Game assets over MCP

Profile `game` is served at `/api/v1/mcp/game`. It lists the `game.*` tools plus the local generation, job, character and Model3D tools those steps call. Start with `game.guide`.

Every call is `{version: 1, input: {...}}`. `input` rejects unknown fields. `workspace` is required except on `game.presets`.

## Flow

`game.guide` → `game.create` → `game.style.sheet` → the user approves → `game.style.approve` → `game.assets.from_list` with `check: true` → the same call without `check` → `game.produce` → `game.produce.status` → the user reviews → `game.produce` again for animations → `game.export`.

Do not approve a style or an asset unless the user asked. Describe style by traits, not by a brand, console, studio or artist. Measure one asset before a large batch. `rerender` is only for stale assets.

## Tools

| Tool | Mutates | Calls |
|---|---|---|
| `game.guide` | no | `GET /api/v1/games/{id}` when `game_id` is set. Returns `{guide, bible}`. |
| `game.presets` | no | `GET /api/v1/games/presets` |
| `game.list` | no | `GET /api/v1/games` |
| `game.get` | no | `GET /api/v1/games/{id}` |
| `game.create` | yes | `POST /api/v1/games` with `{workspace, game}` |
| `game.update` | yes | `PUT /api/v1/games/{id}` with `patch` and `base_revision` |
| `game.style.sheet` | yes | `POST /api/v1/games/{id}/style/sheet` |
| `game.style.approve` | yes | `POST /api/v1/games/{id}/style/approve` with `references[{asset_id, attempt_id}]` |
| `game.assets.from_list` | yes | `POST /api/v1/games/{id}/assets/from-list`. `check: true` does not write. `format` is `lines`, `csv` or `json`. |
| `game.asset.update` | yes | `PATCH /api/v1/games/{id}/assets/{asset_id}` |
| `game.asset.approve` | yes | `POST .../approve` with `attempt_id` |
| `game.asset.reject` | yes | `POST .../reject` with `attempt_id` and a required `note` |
| `game.asset.lock` | yes | `POST .../lock` with `locked` |
| `game.produce` | yes | `POST /api/v1/games/{id}/produce` |
| `game.produce.status` | no | `GET /api/v1/games/produce/jobs/{job_id}`. Optional `wait_s` ≤ 120. |
| `game.produce.cancel` | yes | `POST .../jobs/{job_id}/cancel` |
| `game.produce.resume` | yes | `POST .../jobs/{job_id}/resume` |
| `game.export` | yes | `POST /api/v1/games/{id}/export`. Returns `{file, url, counts, missing}`. |

A 409 means the `base_revision` is stale. Read the game again and retry with the new revision. Long renders return a job id. Poll `game.produce.status` or `jobs.wait`. Reuse the same intent when a job is interrupted.

The profile also includes `generation.image`, `generation.video`, `generation.sfx`, `generation.music`, `generation.speech`, `studio.key`, `jobs.wait`, `jobs.leftovers`, `jobs.resume`, `jobs.discard`, `characters.list`, `characters.get`, `characters.save`, `model3d.generate`, `model3d.status`, `model3d.rig`, `model3d.rig.status`, `model3d.animate`, `media.options` and `scenes.assets.inspect`.
