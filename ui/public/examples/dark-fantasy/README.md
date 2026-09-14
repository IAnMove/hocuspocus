# Dark Fantasy · 30 editable perspective templates

Open **Studios → Video 3D → Shot library** and select the **Dark Fantasy** filter.
The collection contains ten landscape studies, ten new 720 × 1280 vertical
compositions, and ten vertical PSX variants. The **PSX** filter selects the variants.
Vertical presets open in 9:16 automatically, with their authored camera framing.
Each six-second scene includes its original generated images, transparent character
cutouts, camera movement, lighting, atmospheric effects and floor finish. No model
inference or AI video generator is required to render these templates.

These are **2.5D scenes**: painted 2D characters and scenery arranged in a 3D
compositor, with real perspective, spatial effects, occlusion and reflections.
The figures do not have a skeleton or an unseen 3D back; use modest camera arcs.

Replace a character image and choose **Character / transparent cutout** under its
surface control. The image retains its aspect ratio and alpha. Position, scale,
camera framing and effects remain editable. Images with transparent margins may
need their vertical position adjusted to place visible feet on the floor.

Cinematic floor finishes include the original tiles, a seamless reflective surface,
and no floor for floating compositions. Export uses the same native renderer as
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
