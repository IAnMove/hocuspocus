# Anime 3D characters

How the app makes an anime character in 3D: one call, three doors, and what the pieces are.

## One call

`model3d.anime.make` `{workspace, name, traits?, base_revision?}` (MCP; `POST /api/v1/model3d/anime`; the Studio 3D panel). No GPU, a few seconds.

`traits`: `gender` (`girl|boy`), `body` (`slim|average|tall`), `height` (m), `skin`, `eye_color`, `lash_color` (default: the hair colour darkened), `hair_style` (`none|short|bangs|bob|long|twin_tails|spiky|ponytail|bun`), `hair_color`, `outfit` (`school|casual|sport`), `outfit_colors` `{top, bottom, shoes, accent}`, `blush`, `face` (extra `blob_face` knobs: `nose`, `brows`, `line`, `ink`), `clips`.

Returns `rigged_file`, `file`, `faceAnchor` `{center, radii}`, `traits` (the body), `kit_id`, `poses`, `preview`, `face` `{fit, taper, poses}`, `character` (the traits as resolved).

Then, in a scene: bind `rigged_file` to a model slot (`fit.heightM` = the height), `world3d.scene.face {object_id, kit_id, center, radii}` (the kit carries `fit` and `taper`, nothing else to pass; `pose` picks an expression, `expressions` changes it during the shot), `world3d.scene.talk` for the lines. Toon: `renderLook: "toon"`, `toon {shade: "anime", steps: 2, outline: 3}`. Close-ups: camera within about 60° of the face.

## What it is made of

- **Body**: `model3d.blob.make` traits `family: "anime", mesh: "loft"` (`blob_loft`): one smooth lofted mesh, tapered limbs, a real neck, an egg head with a jaw and ears, fingers and a thumb, shoes with a sole, a closed pleated skirt or trousers or shorts, collar, bow or tie; the `outfit` picks sleeve and leg lengths and the shoe style. Rigged by the automatic humanoid rig (silhouette landmarks, geodesic weights, the Mixamo-style bone names, so clips and Meshy retargets keep working).
- **Hair**: `blob_hair`, curved clumps from a quadratic curve per strand (root on a helmet, pull point, tip) lofted as flattened tubes, written as the GLB's second primitive (material `hair`): the toon look adds a view-space gloss band on it. No spring bones: the rig's skeleton is fixed, so hair follows the Head bone rigidly.
- **Face**: `characters.face.make` style `anime_head` (`blob_face_head`): a whole-head picture (the skull box is `fit`), eleven expressions (`neutral, happy, sad, angry, surprised, smug, shy, sleepy, suspicious, tired, shout`), nine visemes and a blink, drawn from traits with a VRoid-like eye (iris bands, limbal ring, three highlights, coloured lash line, crease, lower lash), brows, a nose dot, blush, mouth corners. Projected on the head cap from the front (`faceDecal.fit`), hugging the egg (`faceDecal.taper`): correct at 0–60°, compressed at 90°, nothing at 180° (the hair geometry carries the back).

## What old games did, and what we borrowed

| Where | Technique | Licence / status | Borrowed |
| --- | --- | --- | --- |
| N64/GC Zelda (Wind Waker) | eyes, brows and mouth as separate texture layers on a face region, swapped per expression | n/a (idea) | the whole face as a swapped texture on a curved cap: expressions = pose pictures, visemes = mouth sprites, blink = patch |
| VRM 1.0 (`vrm-c/vrm-specification`) | expression presets `happy, angry, sad, relaxed, surprised, aa, ih, ou, ee, oh, blink, look*`, bound to morph targets, material colours or UV offsets | spec, open; `three-vrm` MIT (three r167+, ours is r0.183) | the preset list shape (we have 11 expressions + 9 visemes), MToon ideas: tinted shade, rim, outline, hair gloss band |
| VRoid Studio | hair as separate mesh clumps with a highlight band; face texture from layered parts | proprietary app, VRM out | hair as curved clumps; gloss band in view space |
| Talking Head Anime 3 (`pkhungurn`) | one anime picture -> expression and head-turn parameters | code MIT, weights CC BY 4.0 (commercial ok with credit) | not used; a future lever for turning a painted head without geometry |
| MakeHuman / MB-Lab / CharMorph | parametric human bodies | AGPL code (MakeHuman exports CC0 from the official build); MB-Lab AGPL on models; CharMorph claims non-AGPL models | not used: realistic, not anime; our loft is parametric already |
| Inochi2D | 2D mesh deformers on layered art | BSD-2 | not used; the same idea as a flat kit with warp mouths |
| Hunyuan3D | image to mesh | licence excludes the EU | excluded |

## Gotchas

- The primitives' `torso_top` reaches into the head; the lofted torso closes a neck's length under the chin, so collars and bows hang from `shoulder_top`.
- A `long` hair girl rigs with `neck_not_found` (the hair fills the neck notch of the silhouette): harmless, the Head joint still lands in the egg.
- Turntable copies need an `idle` beat each, or they stand in T-pose.
- The kit's picture is transparent outside the features: the 3D skin shows through, so pass `skin` equal to the head colour (the blink patch is painted in it).
- `fit` assumes the drawn skull is the egg: `ru = rv · rx / ry`; the head traits (`width 0.12`, `height 0.146–0.152`) match `blob_face_head.SKULL`.
