# 3D character styles: the base to refine

One page for any model (or person) who is going to improve a style. A **style** is a *mould* (geometry on the one rig, so every clip and every Meshy retarget keeps working) plus a way to **dress** it (colours, a drawn face, or a texture atlas). The live list, with status, limits and next steps, is `app/services/character_3d_styles.py`; `model3d.blob.presets` returns it under `styles`. Keep it true: after every round, edit that file (`status`, `limits`, `next`).

| style | operation | state | in one line |
|---|---|---|---|
| `blob`, `chibi` | `model3d.blob.make` | stable | round-headed primitives; cute, cheap, no texture |
| `anime` | `model3d.anime.make` | experimental | cel-shaded 3D with a drawn, talking face; reads "cartoon 3D" more than anime |
| `real` | `model3d.anime.make` `style: "real"` | experimental | PS2/PS3-era realistic person: a mould plus a texture atlas painted by Qwen and draped per pixel; no expressions yet |
| `voxel`, `roblox` | (same) `style: "voxel"` or `"roblox"` | experimental | our own boxes on the one rig, a 64x64 picture made from colours (or yours), a decal face with lipsync |
| `ps1`, `clay`, `toon-realistic` | (same) | planned | see the backlog |

Details per style: `ANIME_CHARACTERS.md` (anime and real), `MODEL3D_BLOB.md` (blob, chibi), `BLOB_FACE.md` (faces).

## What a style is made of
1. **Mould**: `blob_builder` (proportions, presets), `blob_loft` (the lofted body, `SKULLS` per head kind, nose, ears, arms, hands), `blob_hair` (strand cards). One Mixamo-style skeleton from `humanoid_rig`.
2. **Dress**: vertex colours (blob, chibi, anime) or a **texture atlas** (real): `blob_texture` writes the guides and the picture into the GLB, `ui/src/features/scene3d/atlasProjection.ts` drapes it per pixel, `hairStrands.ts` gives hair its strands.
3. **Face**: a kit (`blob_face*`, `world3d.scene.face`, `world3d.scene.talk`) or, for `real`, the head picture (kit from a photo: not built yet).
4. **Look**: the render preset, e.g. retro `toon {steps 4, outline 0, shade "classic"}` with `look.exposure` 1.5, or anime toon with ink.

## The loop that improved the heads, the hair and the realistic style
1. **See the state** (never trust a number alone): `scripts/dev/character_sheets.py` makes the characters from `specs.json` on **your own** test server and writes a turntable sheet (`--close` for heads). `scripts/dev/skull_preview.py` previews the head tables with no server.
2. **Get a target** and measure it. For a head: ask `generation.image` (Qwen, 1024x1024) for bald front and side model sheets on white, measure the silhouettes (row widths of the non-white mask, normalised to crown = 1 and chin = 0), write them into a table (`SKULL*` in `blob_loft`), overlay the table on the sheet. That is how the anime head stopped being a balloon and how the man/boy heads were made.
3. **Pin it with a test** (`tests/test_blob_body.py`, `tests/test_blob_texture.py`): proportions, UV bounds, what the GLB contains. A change that "looks better" but breaks a pin is a decision, not an accident.
4. **Render, then look as an outsider** (a frame sheet at the size the viewer will see). Say what still reads wrong and rank it. Ask a second model for a read-only critique of the same frames and the code (give it the images and the files, not your conclusion) and apply what survives checking against the code.
5. **Write down**: the registry, the docs, a memory note. Commit every stage on a branch.

Gotchas collected so far: roots of hair must sit outside the face patch; a colour change by vertex blurs across a quad (make a panel); thighs poke above a skirt unless the pelvis covers them; a Qwen repaint at 2048x1536 runs out of memory (keep each picture 2048x1024); a painted background bleeds into the mould's edges unless `bleed` fills it; never call a module like an existing one (`character_styles.py` is the 2D kit styles; the 3D registry is `character_3d_styles.py`); one GPU model family at a time; stop your server.

## Texture recipe for `real` (what to do, in order)
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
One command per character (against your own test server; about 5 minutes of GPU, nearly all of it the two Qwen pictures):
`python scripts/dev/real_character.py --port <port> --token-file <worktree>/.server.token --outputs <worktree>/app/outputs --name Marta --gender woman --skin "#E3B58F" --body "<clothes, in English>" --face "<face and hair, in English>" --say "<a line>" --voice "<a voice description>"`.
It runs the whole chain through the app's own tools: `model3d.anime.make` (mould + guides) -> `generation.image` twice (Qwen over each guide) -> `model3d.anime.make` with the pictures -> `characters.save` + `characters.rig.flat` (warp mouth kit) -> `generation.speech` + `audio.mouth_cues` -> a turntable-while-talking Video 3D scene. It skips what already exists, so a rerun after a failure resumes. A character is then described by five things only (gender and skin, the body prompt, the face prompt, the voice, the seed), which is what to store to remake it.
- **A new outfit for the same person:** repaint only the body guide (`generation.image`) and call `model3d.anime.make` again with the same `texture_head`; the face kit stays.
- **A new face on the same body:** repaint only the head guide, remake the kit.
- **First run on a new person (Marta, a woman, never seen by the code before):** it worked unattended; the face read as a real person from the front and at three quarters. What it showed: long hair is only paint on the skull (no hair volume behind the head, so the silhouette is a round head), a faint cheek ridge at three quarters, and the woman mould reuses the `boy` head table.
- **What is missing to call it a product:** a server-side job `model3d.real.make` with the same steps (so MCP, the Studio panel and the Wizard call one operation and the user can reopen and edit the result), a prompt library (outfits, ages, skin tones) and a cast sheet; hair volume (the snug photo cap, or long hair cards) as a trait; expressions beyond the mouth.
