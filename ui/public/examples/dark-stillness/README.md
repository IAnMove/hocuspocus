# El tiempo pesa · Fixed cameras and held poses

Open `/examples/dark-stillness/` in HocusPocus to play and rate eight portrait clips,
download their native scene/template documents, and collect six transparent
character PNGs. The first seven clips last six seconds; the wounded knight lasts
eight. All are 720 × 1280 at 30 fps, rendered by the application's Video 3D exporter.

The first four scenes study atmosphere under a stationary viewpoint. Three more
contrast bright characters, dark nearby silhouettes and distant moving landscapes;
the seventh applies PSX only to its character. The final scene holds seven poses
from four separate drawings while snow and mist keep their continuous clock.
The knight kneels, rests a hand on the ground, lowers himself and rises again.

## Editing

1. Open **Studios → Video 3D → Shot library → Dark Fantasy**, or download a scene
   and use **Open shot JSON**. Reusable template files import through **My scenarios**.
2. In the scene inspector, choose **Fixed camera** to keep both eye and target
   stationary. This mode ignores camera framing animation. The other camera
   families remain available.
3. Select a cutout character and enable **Animate this layer → Held poses**.
   Choose or upload transparent PNGs, reorder them, set each hold's duration,
   height, horizontal displacement and lift from the ground. Empty transparent
   margins are excluded from alignment. The global start, speed and loop controls
   apply to the sequence; disabling loop holds its last pose.
4. To use continuous actor motion, select an image or video with an existing alpha
   channel and enable **Preserve transparency**. Transparent WebM is suitable.
   This preserves alpha; it does not remove a background from an opaque video.
5. Background video and architecture are separate layers. Edit `exterior-video`
   for timing and `background` for its window openings. Source camera prompts
   request stationary plates; generated clouds, moon and silhouettes can still
   show small synthesis variations.

The poses are separate generated illustrations, rather than a skinned 3D model;
armor details can vary. Replace individual drawings to refine identity. Their
timing, transparency and alignment remain native editable data, not a flattened
character video.

## Reproduction and provenance

Character art and referenced poses were generated through HocusPocus's MiniMax
Image-01 endpoint and isolated through its background-removal tool. Four new
environment clips were generated with the installed MiniMax H3 Fused Turbo,
four inference steps. Existing architectural frames and foreground props from
the Living Dark Fantasy collection are reused as independently editable layers.
No new model weights were needed.

`PROVENANCE.json` records source requests, job IDs, published source filenames and
checksums. `RENDERS.json` records native scene/export receipts and clip validation.
Final frames and MP4s are produced by HocusPocus; packaging clients only transport
requests, copy published assets and inspect the results. The example URLs resolve
in an installation containing this collection.
