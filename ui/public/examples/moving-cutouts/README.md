# Fuera del lienzo · Moving cutouts

Open `/examples/moving-cutouts/` in HocusPocus to play, compare and rate six
portrait compositions. Each lasts six seconds at 720 × 1280, 30 fps, and has an
editable native scene and reusable template. Two transparent actor WebMs are
included for reuse: a walking knight and an illustrated longboard rider.

## The six compositions

1. **El caminante de ceniza** — a walking knight against moving mist and ruins.
2. **Hacia las brasas** — the same performance in front of lava and static arches.
3. **Sal y velocidad** — a skater over a turquoise sea and coral coastline.
4. **La ciudad pasa** — the rider against a passing violet city.
5. **Carretera de nubes** — floating blue stone and slower peach clouds.
6. **El mar al otro lado** — a PSX rider, static stone and a moving sea in a window.

## Create your own moving layer

In **Studio → Tools → Remove background**, choose an existing video from the
library or upload one. Run the tool and watch frame progress in Activity. The
original remains intact; the result is a transparent VP9 WebM with its original
audio re-encoded to Opus. Images still produce PNGs. No separate script is needed.

Open one of these shots from **Video 3D → Shot library → Animated backgrounds**
or import its downloaded shot JSON. Select the actor in the item list and use
**Animate this layer** to choose your WebM. Keep **Preserve transparency** enabled.
Move or scale the actor, adjust its speed and change the background independently.
The final MP4 combines the layers; retain the WebM to reuse transparency elsewhere.
These demonstration compositions are silent; the source WebMs include audio.

The tool accepts up to 60 seconds / 1800 frames, at up to 60 fps; the output long
edge is at most 1920 px. Edge matting reduces background-colored fringes. Temporal
smoothing damps small changes, but it is not object tracking: inspect hair, fine
objects, occlusions and fast motion on your intended background. An isolated
subject against a simple, contrasting backdrop generally separates more cleanly.
In the skater sample, a thin remnant of the original ground is still visible near
the wheels in some frames. The downloadable alpha video lets you inspect this
before choosing a composition.

## Native production and sharing

Character artwork was generated with HocusPocus's MiniMax Image-01 endpoint.
Their motion and four new backgrounds use the installed MiniMax H3 Fused Turbo
through its normal job API. The app's Tools worker removes actor backgrounds;
the native Video 3D exporter renders all six compositions. Existing architecture
and a lava clip come from the previous Dark Stillness collection.

`PROVENANCE.json` records generation requests, job IDs and source checksums.
`RENDERS.json` records native export receipts and decoded video validation.
Portable templates use the bundled example URLs; an installation containing
these examples can resolve the media. Ratings and notes are stored in your
browser and can be downloaded as JSON for sharing.
