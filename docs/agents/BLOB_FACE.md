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
