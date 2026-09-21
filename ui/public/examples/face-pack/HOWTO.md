# How to make a mascot face pack

Bundled examples in this folder (`*-pack.png`, `*-visemes.png`, `*-talk.mp4`,
`neutral-vowels.wav`) are **CC0** — free for anyone. See `LICENSE`.

A face pack is a PNG the TV-head screen samples while someone talks.
**Mouth (viseme) and expression are independent.** Happy + A is still happy;
only the mouth changes.

## Layout (required)

One PNG, no divider lines, no text, no extra panels.

| | 9 columns, left → right |
|---|---|
| **Visemes** | `rest` `M` `A` `E` `I` `O` `U` `F` `L` |
| **Rows** (top → bottom) | `neutral` `happy` `angry` `worried` `surprised` `sleepy` |

- Square tiles. Same face position, scale and background in every cell.
- Tile size 64–256 px. A 128 px tile makes a 1152×768 sheet.
- Width must be `9 × tile`. Height must be `6 × tile`.
- Face only (no body, no scene). Flat single-color background.
- `rest` is a closed or almost-closed mouth. Do not bake a smile into `rest`
  unless that is the character at rest.

The engine looks up `column = viseme`, `row = expression`. Talking never
moves the row by itself.

## Cube-front plane (required look)

The tile is the **front face of a cube**, not a round portrait. Skin fills the
square edge to edge; only eyes, nose and mouth. Prompts:
Character Creator → **Lipsync face (cube plane)**. Prompts live in
`ui/src/features/scene3d/speech/facePackPrompts.ts`.

CLI: `python3 ui/scripts/assemble_face_pack_from_dir.py stills/ -o pack.png`
with files named `rest.png`, `A.png`, `happy.png`, …

## Two ways to author

### A. Draw the full 9×6 sheet (54 cells)

Best result. For each expression, draw all nine mouths with that same
expression (eyes/brows frozen, mouth only changes).

### B. Draw 9 visemes + 6 expressions (15 stills)

1. Nine visemes on the **neutral** face (mouth only).
2. Six expressions with the **rest** mouth (eyes/brows only).
3. Composite: copy the viseme mouth onto each expression, same crop.
   `ui/scripts/assemble_face_packs.py` does this for the bundled packs.

## Load it in Video 3D

Put the PNG on a TV-head (`headfront` plane) as `speech.facePack`.
Bundled examples live next to this file. Voice and lip-sync → **Mascot face**
picks a bundled pack; **Expression while talking** holds the row while
vowels walk the columns.

## Check

`validFacePackSize(width, height)` rejects sheets that are not 9×6 or whose
tiles exceed 256 px.
