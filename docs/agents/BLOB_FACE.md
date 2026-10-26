# Blob face

A 2D face for a round 3D head. The drawing is a Character Kit. The model stays a model.

## Draw

`characters.face.make` `{workspace, traits, name?, kit_id?, base_revision?}`. Idempotent by `intent_id`.

`traits`: `eyes` (`dot|oval|halflid|wide`, or `{shape, size, separation}`), `brows` (`thick|thin|none`), `nose` (`none|dot|line|bulb`), `moustache` (`none|walrus|pencil|handlebar`, or `{style, color}`), `glasses` (`none|round|square`), `freckles`, `stubble`, `ink` (`#rrggbb`), `line` (2–24), `mouth` (`paper|ink`).

Same traits, same kit id. The kit has the pose `neutral` plus `angry`, `surprised`, `sad`, `happy`, `suspicious`, `tired`, `shout`, nine approved mouths, and a blink. Open it in Characters.

The panel **Crear cara** posts `POST /api/v1/character-kits/face`. The Wizard action is `make_character_face`.

## Place

`world3d.scene.face` `{scene_id, base_revision, object_id, kit_id, pose?, bone?, center?, radii?, size?, face_anchor?, source_url?, expressions?}`.

`center` and `radii` are metres in model space. `face_anchor.size` is a **diameter** (each axis is halved). Without either, the Head bone's skinned vertices are measured; `extras.faceAnchor` on the glTF wins. `size` (default 1.04, range 1–1.2) is how far the cap sits outside the head, not the diameter.

`expressions` is `[{start, pose}]`, at most 32. The kit must have nine approved mouths. An image slot is `not_a_model`.

The viewer section **Cara 2D** sets the kit and the expression. It keeps a center the command already stored.

## Talk

`world3d.scene.talk` on that model writes the same cues, blink and soundtrack as a cutout, onto `faceDecal.art`. The slot stays `model3d`. A model with no face is `not_a_cutout`.

The cap is a child of `Head`, flat (no toon ink, no cel shading). From ±30° it still meets the head.

## Plane face (a painted head)

`shape: "plane"` on `world3d.scene.face` hangs the kit as a flat picture on the Head bone instead of the cap: a whole painted head with its hair (a Qwen drawing keyed with `image.remove_background`, rigged with `characters.save` + `characters.rig.flat`), on a body made with `hair.style: "none"` so the skull stays behind the picture. `plane: [width, height, lift]` (which alone also selects the plane) sizes it in head radii (default `3.3 x 3.3`, lift `-0.5`: a square picture with hair above and a neck below is wider than the skull and its centre lower). `size` is how far in front of the head centre it sits. The plane follows the bone (nods turn it) and does not turn toward the camera: keep the camera within about 30° of the face. The default cap and its documents are unchanged.

Recipe that read as anime («Hasta el mar» v3): a square 1024 head drawn by Qwen with the top of a uniform (the painted bust covers the 3D shoulders; `build: "slim"`, head `0.12`, tops in the painted colours), the painted skull 1.3x the 3D skull (`plane` ≈ `[1024 / (skull px / 2) x 1.3 x 1.08, 1024 / (skull px / 2) x 1.3, -(512 - skull centre px) / 1024 x height]`), `characters.rig.flat` with `mouthStyle: "ink"` (a `hints.base.mouth` when the painted mouth is not found), toon `shade: "anime"`, and a Qwen-painted sky and sea plate as an added image cutout (`imageLook: {unlit: true, tiles: 3}`, 11 m tall at z -9) with `dressing: "none"`.

## Anime style

`traits.style: "anime"` draws the same kit (8 poses, 9 mouths, blink, exact anchors) with big shaded eyes (iris bands, highlights, lashes), thin brows, a tiny nose, small mouths and an optional blush. `eye_color` (`#rrggbb`) colours the iris, `blush` (bool) adds the cheeks. The mouths are drawn 1.8x so they still read at video size. `skin` should equal the head colour of the body (`traits.colors.head` from `model3d.blob.make`): the blink patch is painted in that colour and a different one shows as a pale oval.
