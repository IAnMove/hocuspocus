# Example mascot face packs

Procedural talking faces. Not a recording or clone of a person.
**License:** `LICENSE` in this folder (CC0 1.0). Free to use for anyone.

## Packs

9 visemes `rest M A E I O U F L` × 6 expressions
`neutral happy angry worried surprised sleepy`.

Classic: `tv`, `skull`, `voxel`, `anime`, `cubeskull`.
Cube-front (skin fills the square): `felt`, `clay`, `pixel`, `porcelain`,
`cat`, `oni`, `stencil`, `alien`, `pumpkin`, `ice`, `mushroom`, `vector`,
`halftone`, `steampunk`, `gummy`.

Images: Grok Imagine, 2026-09-11. Canonical stills, then mouth/expression
edits. Sheets assembled in `ui/scripts/assemble_face_packs.py` (128 px tiles).

## Audio and example clips

- `neutral-vowels.wav`, 8 s mono 22.05 kHz PCM. Synthetic formant vowels
  (A E I O U). SHA-256
  `66e633eefa7f4d34dd96139e5b298a47392562a493d5e833ecba4f759a51951e`.
- `hangar-talk.mp4`, `sea-talk.mp4`, `voxel-talk.mp4` — CRT/skull and voxel
  two-shots.
- `felt-talk.mp4`, `pumpkin-talk.mp4`, `cat-talk.mp4` — cube-front two-shots.

Soundtrack is the WAV; character speech is silent so vowels are not doubled.

## Product

- Video 3D → Voice and lip-sync: pick a bundled pack.
- Character Creator → Lipsync face (cube plane): prompts + stills → 9×6.
- `HOWTO.md` for the grid. Expression stays on a row; vowels walk columns.
- Rig for the walker shots: `/examples/tv-head-humanoid.glb` (not CC0).
