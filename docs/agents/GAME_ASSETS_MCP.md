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

The profile also includes `generation.image`, `generation.video`, `generation.sfx`, `generation.music`, `generation.speech`, `studio.key`, `jobs.wait`, `jobs.leftovers`, `jobs.resume`, `jobs.discard`, `characters.list`, `characters.get`, `characters.save`, `model3d.generate`, `model3d.status`, `model3d.rig`, `model3d.rig.status`, `model3d.animate`, `media.options` and `scenes.assets.inspect`. `analyze` is inherited the same way. The style check calls it through loopback. It is not a `game.*` tool.

## Style check

Image attempts (character, sprite, item, icon, ui, tile, tileset, background, animation, vfx) ask `analyze` for a score from 1 to 5 against up to three style references. The candidate is the last image. A score of 1 or 2 adds the warning `style_mismatch` and `metrics.styleScore`. If `analyze` is down, the warning is `style_check_unavailable` and the batch continues. Set `style.qa.vision` to false to skip it. The default is true. Changing that flag does not reset style approval.

A dHash within distance 6 of another approved asset of the same kind adds `duplicate_of:<id>`.

## Limits

500 assets per game. 12 attempts per asset. A library file above 50 MiB is rejected. Export does not bump `revision`. A second zip at the same revision is `game-exports/<id>-r<revision>-2.zip`.

## Warnings

Warnings do not block. Most codes are strings: `loop_not_closed` (loop error above 0.05), `identity_drift`, `foot_drift`, `halo`, `strip_count_mismatch`, `loop_seam`, `over_budget`, `clip_missing`, `style_mismatch`, `style_check_unavailable`, `duplicate_of:<id>`. Tile seam warnings are still objects, `{code: "seam_visible", message}`. Read both shapes.

An asset whose dependency is not approved is skipped with `waiting_dependency`. Do not approve it to unblock the batch unless the user asked.

## What this profile does not do

Play is a UI canvas. There is no `game.play` tool. The pack is PNG, atlas JSON, GLB and WAV/OGG. It does not write Godot or Unity project files. Audio and 3D kinds are not style-scored. Walk, run, spin and bob default to a sprite strip. Other body actions default to one MiniMax H3 clip. Actions are not grouped into one clip.

## Acceptance

The full `game-lab` playthrough is allowed to approve a style and assets by MCP only when the user asked for that acceptance, and the report must say so. Construction tests must not approve anything. The 2026-10-07 report records that the playthrough was not run.
