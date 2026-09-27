# Dark Fantasy · 58 editable perspective templates

Open **Studios → Video 3D → Shot library** and select the **Dark Fantasy** filter.
The collection contains ten landscape studies, ten 720 × 1280 vertical
compositions, ten vertical PSX variants, and twenty new layered scenes with
animated distant landscapes, plus eight fixed-camera studies. Play and rate the new collection at
`/examples/dark-worlds/`; see the [Living Dark Fantasy guide](../dark-worlds/README.md).
The **PSX** filter also includes mixed-style scenes in the
[Creative collection](../creative/README.md).
Vertical presets open in 9:16 automatically, with their authored camera framing.
Each six-second scene (eight seconds for the wounded knight) includes its original generated images, transparent character
cutouts, camera movement, lighting, atmospheric effects and floor finish. No model
inference or AI video generator is required to render these templates.

These are **2.5D scenes**: painted 2D characters and scenery arranged in a 3D
compositor, with real perspective, spatial effects, occlusion and reflections.
The figures do not have a skeleton or an unseen 3D back; use modest camera arcs.

Replace a character image and choose **Character / transparent cutout** under its
surface control. The image retains its aspect ratio and alpha. Position, scale,
camera framing and effects remain editable. **Align visible feet to the ground**
ignores transparent bottom margins; **Contact shadow** reinforces their support.
The original fifty presets use grounded cutouts, stationary foreground figures and slow, level
camera moves. The eight new studies keep the camera fixed; one uses held transparent poses while the landscape continues moving. See [Time Has Weight](../dark-stillness/README.md).

Cinematic floor finishes include the original tiles, a seamless reflective surface,
no floor, and **Floor from backdrop**. The latter projects the painted backdrop
onto a real ground plane. Its lower-image slider brings foreground floor detail
under the cutouts while retaining the distant artwork. Export uses the same native renderer as
preview. Use **Save scene** to retain a revision in the current workspace, or
**My scenarios → Export scenario** to share a JSON template.

The accompanying `.world3d-template.json` files also import through My scenarios.
They reference the bundled `/examples/dark-fantasy/` resources, so recipients need
a HocusPocus version containing this collection. `PROVENANCE.json` records image
prompts and app generation jobs. The knight, oracle and tree PNGs were isolated by
HocusPocus's background-removal tool. The previews are frames from the native editor.

## Contrast and PSX

Near silhouettes, middle figures and distant light occupy separate depth planes.
Change their position and scale to explore parallax. In an image layer, choose
**Character / transparent cutout → Image appearance** to edit its tint, keep its
painted lighting or use the scene lights, and enable **PSX on this layer only**.
The PSX intensity slider controls texture pixel density. Alpha remains part of the
layer, so its background stays separate. Changes survive scene and template export.

Five PSX examples use the existing full-frame effect in **Effects**; the other
five apply PSX only to character layers. The latter leave painted scenery and
spatial effects unchanged. This is a stylized pixel/palette treatment, not a
PlayStation hardware emulator or a conversion into a low-poly rigged character.
Turn off the full-frame cue before testing character-only PSX on one of the other
examples. No additional model download is needed.
