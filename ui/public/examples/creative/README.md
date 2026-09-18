# Creative · 40 editable vertical perspective templates

Open **Studios → Video 3D → Shot library → Creative**. Each template is a six-second
720 × 1280 scene with original artwork, separate transparent characters and props,
spatial effects and a slow, level camera. The library includes native preview
thumbnails. Apply a template, edit its layers and choose **Export video**.

These are 2.5D compositions: image planes arranged in a 3D stage. They use real
perspective and occlusion, but the figures have no skeleton or unseen 3D back.
Rendering uses HocusPocus's native compositor, without an AI video generator.

## New Perspectives collection

**Shot library → Perspectives** contains 20 additional scenes. Open
**View and rate the 20 new clips** in the library, or visit
`/examples/perspective-lab/` on your installation. Each card plays a native
six-second export, opens a larger player, downloads its editable shot/template,
and stores ratings and notes locally. See the [review guide](../perspective-lab/README.md).

**Estación abisal** now includes an animated ocean background generated through
HocusPocus with the installed MiniMax H3 model. Its characters, props, background
depth and selective PSX controls remain editable. Disable **Animate this background
with a video** to return to the still image.

## Styles you can mix

| Template | PSX treatment |
| --- | --- |
| Último ramen | Characters |
| El jardín del mañana | Props |
| Museo bermellón | Background |
| Turno en la luna | Characters |
| Caravana de papel | Props |
| Hotel Esmeralda | Characters |
| Piscina de las seis | Props |
| Lluvia de índigo | Characters |
| Estación abisal | Background |
| El teatro silencioso | Props |
| Andén del sol | Characters |
| La sala de cobalto | Props |
| Mercado mandarina | Background |
| Hangar botánico | Characters |
| El valle de tinta | Props |
| Archivo azul | Characters |
| Última partida | Props |
| Equilibrio dorado | Background |
| Invernadero orbital | Characters |
| Lavandería de medianoche | Props |

In an image layer, open **Character / transparent cutout → Image appearance**.
Toggle **PSX on this layer only** and adjust its intensity. Other layers retain
their own appearance. A PSX background also styles the floor projected from it.
The collection has no full-frame PSX cue, so selective changes remain independent.
This is a texture and palette treatment, not a PlayStation hardware emulator.

## Grounding and depth

**Align visible feet to the ground** trims transparent bottom padding without
resizing the painted figure. **Contact shadow** adds an editable soft shadow at
its base. Position Y controls the resulting ground height; the presets use zero.
For images that block browser canvas readback, automatic alignment is unavailable;
import the image into HocusPocus first or adjust the height manually.

**Floor from backdrop** uses the scene artwork on a real ground plane. Adjust
**Lower backdrop portion used as floor** to sample more of the painted foreground.
The distant edge retains the original view. Use the floor color for uncovered
edges, or choose another floor finish. A planar background image is required.

Move layers in depth to vary parallax. Keep modest camera moves with cutout art;
all presets avoid roll, vertical turns and levitation. Shadows, camera, effects
and layer styling remain editable and survive save/import/export.

## Sharing

Use **Save scene**, or **My scenarios → Export scenario**. The accompanying
`.world3d-template.json` files can also be imported there. They reference bundled
`/examples/creative/` resources, so recipients need this HocusPocus collection.

`PROVENANCE.json` records the native image-generation and background-removal
jobs, prompts and asset hashes, including subsequent floor-art revisions.
Thumbnails and demonstration videos use the same renderer as the editor.
