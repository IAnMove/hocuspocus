# Making a game pack in HocusPocus (guide for agents)

This is how an agent with the `game` MCP profile builds a side-view game pack on the local machine.
Images, video, sound, speech and meshes stay on this computer. Do not invent brand, console, studio or artist names.
Describe a look by traits: palette, outline, shading, pixel grid.

## Flow

1. `game.guide` — read this guide and, with `game_id`, the bible (style, counts, references, what is waiting).
2. `game.create` — title, genre `platformer`, view `side`. Top-down is stored and is not tuned.
3. `game.style.sheet` — four samples (character, object, tile, background). The user looks at them.
4. `game.style.approve` — only after the user says the style is right. Send the sample attempt ids as references.
5. `game.assets.from_list` with `check: true` — problems and the estimate come back, nothing is written.
6. `game.assets.from_list` without `check` — write the list when the check was clean.
7. `game.produce` — pending assets, in dependency order. Poll `game.produce.status` (`wait_s` at most 120).
8. The user reviews. `game.asset.approve` or `game.asset.reject` (a note is required; it enters the next prompt).
9. `game.produce` again for animations and anything still pending. `rerender: true` only for stale assets.
10. `game.export` — ZIP of approved assets only. Unapproved assets are listed in `missing`.

## Rules

- Never approve a style or an asset unless the user asked. No step approves itself.
- Styles are traits. Do not name a brand, a console, a studio or an artist.
- Measure one asset before a large batch. Read the estimate from the check.
- `rerender` only for stale assets. A locked asset stays put when the style changes.
- Characters face right. Left is the mirrored sprite. One scale for every frame of a character.
- Walk and run default to a still strip. Other body actions default to one video clip. Do not group actions.
- The pack is PNG plus atlas JSON, GLB, WAV/OGG with loop points, and `manifest.json`. No engine project files.
- Generated media stays in the workspace. Do not commit PNGs, WAVs or GLBs.

## What the bible contains

`game.guide` returns `{guide, bible}`. The bible has the preset, traits, palette, pixel grid and audio settings,
counts by kind and status, the approved style references, and the first assets still waiting for a person.
A game with hundreds of assets stays under 6 KB: the rest of the queue is `awaitingMore`.
