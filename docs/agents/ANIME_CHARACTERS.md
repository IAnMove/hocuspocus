# Anime 3D characters

How the app makes an anime character in 3D: one call, three doors, and what the pieces are.

## One call

`model3d.anime.make` `{workspace, name, traits?, base_revision?}` (MCP; `POST /api/v1/model3d/anime`; the Studio 3D panel). No GPU, a few seconds.

`traits`: `gender` (`girl|boy|man`; the head shape follows it: `girl` a wide soft egg with a small V chin, `boy` a longer head with a clean V to a point, `man` a long narrow head with a brow ridge, straight jaw lines to a flat chin and a thick neck, face shape `sharp` by default), `body` (`slim|average|tall`), `height` (m), `skin`, `eye_color`, `lash_color` (default: the hair colour darkened), `hair_style` (`none|short|bangs|bob|long|twin_tails|spiky|ponytail|bun`), `hair_color`, `outfit` (`school|casual|sport`), `outfit_colors` `{top, bottom, shoes, accent}`, `blush`, `face_style` (`anime`: almond eyes, the default; `cute`: the round-eyed mascot face), `face_shape` (`soft|sharp`), `face_source` (`program`, the default, zero GPU; `qwen`: a painted bald face as the kit base, see below), `face_image` (with `qwen`: a keyed bald picture of this workspace), `face` (extra `blob_face` knobs: `nose`, `brows`, `line`, `ink`), `clips`.

### The two face sources

- **`program`**: `blob_face_anime_head` draws the face from traits in ~15 s on CPU. Calibrated on painted anime heads (each eye ≈ 17 % of the face width, 9 % of the skull height, almond, outer corner higher; eye line 58 % down the skull; mouth 84 %), heavy upper lash with a tail, iris taller than the opening and shaded under the lid, limbal ring, three highlights, tapered brows per expression. Any skin, eye and lash colour; `face_shape` tilts and narrows the eyes.
- **`qwen`**: a bald anime face painted by Qwen (`generation.image`, `qwen_image_21_turbo`, prompt: *"Completely bald head, no hair at all, head and neck only, front view, looking straight at the viewer, neutral calm expression, mouth closed, large anime eyes, clean 2000s TV anime cel shading, solid pure white background"*), keyed with `image.remove_background` and passed as `face_image`. `blob_face_qwen` measures it (the anime landmark model gives 0 points on bald heads, so the silhouette prior is used: eye line 0.7 of crown→chin, mouth 0.9, refined by the flat rig's hinted search only when it finds a plausible pair), cuts the two painted eyes with a feathered edge, and pastes them inside the drawn openings of the `anime_head` face (an eyes-only hybrid): lids, lashes, crease, brows, nose, mouth, blush and blink are the drawn ones, so the eleven expressions are as consistent as the drawn style, nothing of the painting is lit twice and no contour of the painting lands on the skull. The painting's skin is sampled and given to the body. Why not the whole painting or Qwen-edited expressions: pasting the painting re-lights its shading and projects its contours onto the cheeks; separately edited expressions drift (measured with the flat rig on `bald_hana_31`: eyes move 0.8–2.5 % of the picture, the mouth 0.1–3.2 %, and the eye size changes ±35 % between neutral and surprised). Limit: the painted eye cannot enlarge for `surprised`.

Both sources give the same kit shape (eleven poses, nine visemes, a blink, `fit`, `shape: mesh`, `skin`), so a scene cannot tell them apart.

Returns `rigged_file`, `file`, `faceAnchor` `{center, radii}`, `traits` (the body), `kit_id`, `poses`, `preview`, `face` `{fit, taper, poses}`, `character` (the traits as resolved).

Then, in a scene: bind `rigged_file` to a model slot (`fit.heightM` = the height), `world3d.scene.face {object_id, kit_id, center, radii}` (the kit carries `fit` and `taper`, nothing else to pass; `pose` picks an expression, `expressions` changes it during the shot), `world3d.scene.talk` for the lines. Toon: `renderLook: "toon"`, `toon {shade: "anime", steps: 2, outline: 3}`. Close-ups: camera within about 60° of the face.

## What it is made of

- **Body**: `model3d.blob.make` traits `family: "anime", mesh: "loft"` (`blob_loft`): one smooth lofted mesh, tapered limbs, a real neck, an egg head with a jaw and ears, fingers and a thumb, shoes with a sole, a closed pleated skirt or trousers or shorts, collar, bow or tie; the `outfit` picks sleeve and leg lengths and the shoe style. Rigged by the automatic humanoid rig (silhouette landmarks, geodesic weights, the Mixamo-style bone names, so clips and Meshy retargets keep working).
- **Hair**: `blob_hair`, curved clumps from a quadratic curve per strand (root on a helmet, pull point, tip) lofted as flattened tubes, written as the GLB's second primitive (material `hair`): the toon look adds a view-space gloss band on it. No spring bones: the rig's skeleton is fixed, so hair follows the Head bone rigidly.
- **Head**: the lofted skull (`blob_loft.SKULL`, read by `skull_profile`): a table MEASURED from Qwen-drawn bald anime head sheets (front and side silhouettes; crown v = 1 to chin v = 0: half-width, front depth, back depth per height, Catmull-Rom between rows, superellipse rings). An anime head is about 0.8 as wide as it is tall (the layout's head `width` is 0.116 of the height, not a ball's 0.138), its widest ring sits at 60 % of the height (0.4 down from the crown), the crown is a flat dome and the jaw is a V down to a small chin; the earlier sphere-over-a-cone was a balloon. A small nose ridge at the drawn nose's height and ears at the eye line (none under `long`, `bob` and `twin_tails`, which fall over them), with a `face` primitive (the skull's front from the chin to the hairline, a hair's breadth outside it) whose UVs project the kit picture from the front (`fit`). The picture is painted into that primitive's material (`faceDecal.shape: "mesh"`, `skin` filled under the drawing), so the face is lit and cel-shaded with the body and outlined with the head, like an old game's face texture; expressions swap the picture. Correct at 0–60°, compressed at 90°, nothing at 180° (the hair carries the back).
- **Face**: `characters.face.make` style `anime_head` (`blob_face_anime_head`) or the painted `qwen` source (`blob_face_qwen`), both with eleven expressions (`neutral, happy, sad, angry, surprised, smug, shy, sleepy, suspicious, tired, shout`), nine visemes and a blink. Style `cute` (`blob_face_head`) keeps the round mascot eyes for balls, slimes and small pets: on a sphere head pass `shape: "cap", taper: 0` to `world3d.scene.face`.

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

## Review round (reviewer measured from stills, applied)

Features sit lower on the skull (eye line 0.63 of the skull box, mouth 0.87, chin-to-mouth 13 %), the iris is taller than the opening and clipped by the lid, brows lighter, the five half-lid poses differ (asymmetric lids, a lifted corner for smug, a small o for sleepy), head visemes have a thin teeth line and a dark inside; the face patch gets no ink hull of its own (the skull's hull carries the jaw), hair strands take 0.4 of the outline width and a narrow gloss band scaled by the hair's luminance; the hairline is lower, the helmet thicker with crown volume and the fringe reaches the brows.

## Gotchas

- The primitives' `torso_top` reaches into the head; the lofted torso closes a neck's length under the chin, so collars and bows hang from `shoulder_top`.
- A `long` hair girl rigs with `neck_not_found` (the hair fills the neck notch of the silhouette): harmless, the Head joint still lands in the egg.
- Turntable copies need an `idle` beat each, or they stand in T-pose.
- The kit's picture is transparent outside the features: the 3D skin shows through, so pass `skin` equal to the head colour (the blink patch is painted in it).
- `fit` assumes the drawn skull is the egg: `ru = rv · rx / ry`; the head traits (`width 0.12`, `height 0.146–0.152`) match `blob_face_head.SKULL`.

## Round 7: a head that is an egg, arms and hair that lie on the body
- **Skull from measurements, not a formula**: `tests/test_blob_body.py::test_anime_skull_is_an_egg_measured_from_anime_heads_not_a_ball` pins the proportions (width/height 0.78–0.88, widest ring at 50–70 % of the height, jaw ring under 0.62 of the widest at 10 % up, crown ring about half of it at 95 %). To re-measure or change the target, draw bald front/side sheets with `generation.image` and compare silhouettes (the front outline of the table matches the Qwen sheets to within a few pixels at 520 px per head height).
- **Face UVs are isotropic**: `face_patch` maps x and y with the same scale (`ry`, `rv`), so a narrower skull does not squash the drawn eyes.
- **Arms**: a shoulder cap (1.2x) tapering to the elbow, a slim wrist (0.58x), a fuller mitten with short fat fingers (an edge-on hand is no longer a spike). Thighs under a skirt or shorts take the garment colour and the pelvis is at least as wide as the legs' tops, so no box shows beside the waist.
- **Hair**: `curve_tube(hug=head centre)` lays each clump as a ribbon along the skull (thin side away from it); before, bangs were blades seen edge-on and read as bars. `short` keeps crown clumps, the other styles a smooth dome.
- **Shirt V**: the shirt under an open jacket is its own panel a hair outside the torso (`_shirt_v`), not a colour change by vertex (it blurred into a glow or jagged when the torso had more segments).
