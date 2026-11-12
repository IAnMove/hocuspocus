# 3D character styles: the base to refine

One page for any model (or person) who is going to improve a style. A **style** is a *mould* (geometry on the one rig, so every clip and every Meshy retarget keeps working) plus a way to **dress** it (colours, a drawn face, or a texture atlas). The live list, with status, limits and next steps, is `app/services/character_3d_styles.py`; `model3d.blob.presets` returns it under `styles`. Keep it true: after every round, edit that file (`status`, `limits`, `next`).

| style | operation | state | in one line |
|---|---|---|---|
| `blob`, `chibi` | `model3d.blob.make` | stable | round-headed primitives; cute, cheap, no texture |
| `anime` | `model3d.anime.make` | experimental | cel-shaded 3D with a drawn, talking face; reads "cartoon 3D" more than anime |
| `real` | `model3d.real.make` (one server job; by hand: `model3d.anime.make` `style: "real"`) | experimental | PS2/PS3-era realistic person: a mould plus a texture atlas painted by Qwen and draped per pixel; a photo face kit with warped mouths talks (only the mouth moves) |
| `voxel`, `roblox` | (same) `style: "voxel"` or `"roblox"` | experimental | our own boxes on the one rig, a 64x64 picture made from colours (or yours), a decal face with lipsync |
| `ps1`, `clay`, `toon-realistic` | (same) | planned | see the backlog |

Details per style: `ANIME_CHARACTERS.md` (anime and real), `MODEL3D_BLOB.md` (blob, chibi), `BLOB_FACE.md` (faces).

## What a style is made of
1. **Mould**: `blob_builder` (proportions, presets), `blob_loft` (the lofted body, `SKULLS` per head kind, nose, ears, arms, hands), `blob_hair` (strand cards). One Mixamo-style skeleton from `humanoid_rig`.
2. **Dress**: vertex colours (blob, chibi, anime) or a **texture atlas** (real): `blob_texture` writes the guides and the picture into the GLB, `ui/src/features/scene3d/atlasProjection.ts` drapes it per pixel, `hairStrands.ts` gives hair its strands.
3. **Face**: a kit (`blob_face*`, `world3d.scene.face`, `world3d.scene.talk`) or, for `real`, the head picture and the photo face kit made from it (`model3d.real.make` makes both).
4. **Look**: the render preset, e.g. retro `toon {steps 4, outline 0, shade "classic"}` with `look.exposure` 1.5, or anime toon with ink.

## The loop that improved the heads, the hair and the realistic style
1. **See the state** (never trust a number alone): `scripts/dev/character_sheets.py` makes the characters from `specs.json` on **your own** test server and writes a turntable sheet (`--close` for heads). `scripts/dev/skull_preview.py` previews the head tables with no server.
2. **Get a target** and measure it. For a head: ask `generation.image` (Qwen, 1024x1024) for bald front and side model sheets on white, measure the silhouettes (row widths of the non-white mask, normalised to crown = 1 and chin = 0), write them into a table (`SKULL*` in `blob_loft`), overlay the table on the sheet. That is how the anime head stopped being a balloon and how the man/boy heads were made.
3. **Pin it with a test** (`tests/test_blob_body.py`, `tests/test_blob_texture.py`): proportions, UV bounds, what the GLB contains. A change that "looks better" but breaks a pin is a decision, not an accident.
4. **Render, then look as an outsider** (a frame sheet at the size the viewer will see). Say what still reads wrong and rank it. Ask a second model for a read-only critique of the same frames and the code (give it the images and the files, not your conclusion) and apply what survives checking against the code.
5. **Write down**: the registry, the docs, a memory note. Commit every stage on a branch.

Gotchas collected so far: roots of hair must sit outside the face patch; a colour change by vertex blurs across a quad (make a panel); thighs poke above a skirt unless the pelvis covers them; a Qwen repaint at 2048x1536 runs out of memory (keep each picture 2048x1024); a painted background bleeds into the mould's edges unless `bleed` fills it; never call a module like an existing one (`character_styles.py` is the 2D kit styles; the 3D registry is `character_3d_styles.py`); one GPU model family at a time; stop your server.

## Texture recipe for `real` (what to do, in order)
`model3d.real.make` runs these steps on the server (see "Making many realistic characters" below); call them one by one only to try something the job does not do.
1. `model3d.anime.make {style: "real", gender, bottom, hair_style: "none", ...}`: read `guide_body_file` and `guide_head_file`.
2. `generation.image` twice (Qwen, `qwen_image_21_turbo`, `image_refs: [guide]`, `video_prompt_type: "KI"`, `resolution: "2048x1024"`, 8 steps), body first: *"Flat colour texture map for a realistic PS2-era 3D game character, the full body front view on the left and the back view on the right, exactly the same T-pose, silhouette and layout as the reference image, painted over the grey mannequin. <the outfit and the skin>. Even flat lighting, no shading, plain dark background."*; head: *"Three photographic portrait textures of the head and neck of the same realistic <person>, side by side in three tall panels with exactly the same silhouettes and layout as the reference image, left from the front, middle in pure right profile facing left, right the back. <the face, the hair>. Neutral expression, even flat lighting, plain dark background."*
3. `model3d.anime.make` again with the same traits plus `texture` and `texture_head`. To change the clothes repaint only the body guide.

## Roblox, Minecraft and other "tal cual" styles: what is safe
- **Do not download or redistribute Roblox's own avatar meshes, shirt/pants templates, faces or logos**, and do not rip them from the client: their terms forbid extracting assets for use outside the platform, and the characters are their trade dress. This is a practical reading, not legal advice; if a project truly needs the real thing, ask the owner to check the licence.
- What we can do freely is **our own blocky style**: boxes for a head, torso and limbs with R15-like proportions, drawn by us (`roblox` and `voxel` in the registry, `blob_blocky.py`), textured through the same atlas pipeline, with a flat decal face. It reads "Roblox-like" without using anything of theirs. The same for a Minecraft-like voxel person (our own cubes and our own 64x64 pictures).
- Reference **ideas** (proportions, the look) are fine; reference **files** are not.

## Backlog of styles (cheapest first, all reuse the rig and the atlas)
1. ~~blocky~~ done as `voxel` and `roblox` (`blob_blocky`, `blob_face_blocky`). Gotcha learnt: the rig refuses 4-unit-wide box arms in a 8-unit torso (`hands_stuck`); arms 3.5 wide or a wider torso pass.
2. **ps1**: the real mould decimated, a 128x128 atlas with nearest filtering, snapped vertices; strong retro look.
3. **clay / stop-motion**: soft chibi mould, Qwen clay texture, swappable face pieces, stepped motion.
4. **toon-realistic** (`toon_real`, Wind Waker-like; the owner wants it): the real mould with a cel-painted atlas, a thin ink line and a face whose big simple eyes move on their own (gaze) with swappable lids and mouth.
5. **vinyl toy**: big head, glossy plastic, a studio backdrop.
6. **paper doll / cut-out 3D**: flat parts with thickness, the 2.5D kit look in 3D.

For `real` the **face relief** (depth of the painting, `blob_face_relief`) removed the mask look; the next big step is the **photo face kit** (neutral picture from the head tile, a few mouth shapes warped from it, a blink), then sculpted face relief (cheekbones, lips, brow) in the mould so the painted profile has something to sit on.

## Making many realistic characters
**One operation, three doors: `model3d.real.make`.** The Studio 3D panel «Realista (PS2)», the MCP tools `model3d.real.*` (`POST /api/v1/model3d/real…`, one handler per tool and route in `app/routers/model3d_real.py`) and the Wizard's `make_real_character` start the same server job (`app/services/real_character_job.py`); it replaces what `scripts/dev/real_character.py` did from outside. Input: `{workspace, name, gender man|woman, skin?, height?, body?, bottom?, outfit_prompt, face_prompt, seed?, image_model? (qwen_image_21_turbo), texture? / texture_head? (reuse a picture, skip that painting), talk_kit? (true), traits? (more style-real traits), base_revision?}`. About 5 minutes of GPU, nearly all of it the two Qwen pictures.
- **Steps** (each saved on the job file under `.real-character-jobs-v1/`, followed with `model3d.real.status`, stopped with `model3d.real.cancel`): `guides` (`anime_make.real_guides`: the two guides, nothing built yet) -> `body` and `head` (`generation.image` over each guide: `image_refs` the guide, `video_prompt_type: "KI"`, `2048x1024`, 8 steps, CFG 1; the prompts of the texture recipe above with the two texts in them) -> `character` (`make_character` with both pictures and `face_kit=False`: the drawn `anime_head` kit is not made) -> `kit` (a cutout kit `real-<name>` whose base is the front tile, copied as `real-<name>-face-<head key>.png`, rigged by `rig_character` with `mouthStyle: "warp"`).
- **What is reused.** A picture is keyed by a hash of its whole prompt, the seed, the model and the guide bytes (`picture_key`); a picture an earlier job of the name painted (also one that failed later) is found by its key. A rerun with nothing changed paints and builds nothing; a new `outfit_prompt` repaints only the body; a new `face_prompt` repaints the head and remakes the kit (the kit records the head key in its provenance, `real-face-tile`). A failed face kit does not fail the character (`talk_kit_failed`); the next make tries it again.
- **The recipe** is written next to the rigged GLB as `<rigged>.recipe.json`: the input, every resolved trait (with `face_span`, `face_feather`, `face_depth`, `head_join`, ...), both prompts (short and whole), seed, model, guides, the pictures with their keys, the files, `kit_id` and the face kit's report. `model3d.real.get {workspace, name}` reads the newest recipe of a name (`missing` when its GLB was deleted), `model3d.real.list` the newest of each name. **A make that leaves a field out takes it from that recipe**, so a remake names only what changes (`null` clears a field).
- **The reply** has everything `model3d.anime.make` returns plus `kit_id` (the photo kit), `talk_kit {review, mouthFound, warnings}`, `recipe`, `reused` and `warnings`: the make's (`picture_not_2_to_1`, `picture_flat`, `relief_skipped`) and the face kit's (`mouth_not_found`, `eyes_low`, ..., `landmark_models_missing`, `talk_kit_failed`).
- **Prompt library**: `app/shared/real_character_prompts.json` (outfits and faces with Spanish and English labels and English prompts; no real people, no brands), returned by `model3d.real.presets` and offered as quick picks in the panel.
- `scripts/dev/real_character.py` is now a thin caller: it starts `model3d.real.make`, waits for it, then adds the voice and the talking test clip.
- **First run on a new person (Marta, a woman, never seen by the code before):** it worked unattended; the face read as a real person from the front and at three quarters. What it showed: long hair is only paint on the skull (no hair volume behind the head, so the silhouette is a round head), a faint cheek ridge at three quarters, and the woman mould reuses the `boy` head table.
- **Still missing:** a cast sheet of several characters; hair volume (the snug photo cap, or long hair cards) as a trait; expressions beyond the mouth.
