# Walk puppet

`method: "puppet"` cuts **one drawing** into a catalog walk. Pose by pose stays the default. One guided clip stays `method: "video"`.

The same operation is the Marioneta option in Characters › Animaciones, MCP `characters.animation.make` (`method`, optional `reference`) and the Wizard action `make_character_animation`. `characters.animation.make_set` stays pose by pose unless `method` is passed. Puppet on a sheet that is not a catalog walk (`idle-directions`) fails that sheet with `puppet_not_a_walk`.

## Which drawing

The catalog has no pose id `idle-rest`.

| Direction | Reference animation | Pose |
|---|---|---|
| front | `idle` | `rest` |
| side, and any direction not listed | `walk-12` | `contact-a` |
| front34 | `walk-front34` | `contact-a` |
| back34 | `walk-back34` | `contact-a` |
| back | `walk-back` | `contact-a` |

`reference: {animation, pose}` overrides that pair. A reference the kit does not have yet is drawn inside the same job (its file name ends in `ref`) and is **not** saved as a second animation.

A pose together with puppet is `puppet_is_a_cycle`: the method makes the whole cycle.

## Clothes

See-through, when it is installed, separates the garments. The arrays are cached in the workspace folder `puppet-layers/<sha256 of the drawing, 20 hex>/`. The kit stores only `provenance.layers` (a boolean). The library drops keys it does not know, so layer URLs are not a kit field.

Without See-through the cut follows the bones, `provenance.layers` is false, and the job warns `puppet_no_layers`. The panel shows that caveat whenever Marioneta is selected: the panel does not ask whether See-through is installed.

The drawing then needs the legs apart and no skirt. A short bottom (`bottomwear` ending above halfway from the knee to the ankle) stays on the torso. Trousers go to the legs. A footwear layer that starts well above the ankle is the whole leg.

## What is kept

`provenance` on the animation is `{method: "puppet", reference: {animation, pose}, start, layers}`. `start` is the phase of the cycle whose pose matches the drawing (the first frame is that drawing). The gait check is not skipped: with one-shot and `autoApprove`, `walk_gait` still measures the sheet. Puppet frames do not carry a per-frame gait. Planted feet stay within one pixel of each other. They are not bit-identical.

## Limits

The hip is one block, so a skirt does not swing. Front and side are the views that were checked by hand; `front34`, `back34` and `back` use the same cutter and were not. See-through can glue trousers and boots into `footwear`. A missing limb fails the job with `puppet_failed` and leaves no half sheet.
