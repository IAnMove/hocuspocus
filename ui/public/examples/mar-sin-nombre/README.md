# Donde el mar no tiene nombre

A Spanish dark maritime folk film built entirely with native HocusPocus media operations. The 720×1280/30 fps master contains 4,180 frames (139⅓ seconds), assembled from 33 layered shots with 15-frame outgoing crossfades. The original 155-second YuE2 song is also included; the film trims 15⅔ seconds from its instrumental introduction.

## Edit the collection

Open the gallery in the running app. Download `scenes.zip`, then load any `.world3d.json` through **Studios → Video 3D → Load scene**. All shots are also saved to the default workspace during native export. The files retain scenery, architecture, sailor, sails, props and effects as independent editable slots. Use the layer list to select hidden objects. The archive includes the media under its original `examples/mar-sin-nombre/assets/` path; the same assets are already served by this app collection.

`plan-es.json` preserves source trims, beat positions, overlap handles and every complete shot document. `assets.json` maps published layers to native job IDs, original filenames and observed SHA-256 hashes. `production-report.json` records processing times and final exports. The clients only submit API requests, author native documents and inspect the actual editor; no alternative media compositor is used.

## Art direction

- The circular cabin window and deck opening use native non-destructive geometry, not an opaque picture of a window over a finished video.
- Six moving oceans sit behind fixed wooden architecture. Close rigging, the mast, sails, table, bucket and lantern add distinct depth and occlusion.
- Cameras keep the horizon level. Ship movement and generated sail/lantern motion are restrained; a small warm light follows measured downbeats.
- Character actions and the bucket fall play once, forward at normal speed. Short ambience and sail sources are reused across different shots, never played backwards or stretched to fill a shot.
- The final musical refrain becomes a continuous cabin-window memory of the six seas, using matched static composition and short crossfades.

## Findings for later improvement

- Automatic matting can remove thin rigging and retain isolated background gaps. Native geometric openings help on architectural plates; better interior-hole and edge recovery would help generally.
- Video matting is much slower than still-image removal on this installation. Preserve resumable native job IDs and expose expected processing cost.
- Native object travel supports paths but lacks a convenient pivoted roll/sway control for ropes, lanterns and ship props.
- H3 can reframe a full-body reference despite a locked-camera prompt. The accepted approach to the sailor is staged as his final portrait; other shots keep fixed source framing.
- Native editor video loads can time out during disk stalls; reviewed previews are checkpointed and reloads stay inside the editor.

Read-only frame decoding and browser playback checks are used for quality assurance. These checks do not modify the production media.
