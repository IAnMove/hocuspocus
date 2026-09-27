# Skate Portal — Salto entre mundos

Open `/examples/skate-portal/` on your running HocusPocus instance. The gallery contains a silent 7.6-second vertical montage, four native MP4 shots, editable scene documents, reusable templates, the original generated jump and its transparent WebM.

Load a `.world3d.json` with **Studios → Video 3D → Load shot**. Import a `.world3d-template.json` in **My scenarios**. The native scene list also contains the four saved shots under **Salto entre mundos** on the authoring installation.

The sequence combines the coast and cloud-road videos from [Moving Cutouts](../moving-cutouts/README.md), a new illustrated skater jump, a separate video inside each portal, and editable actor trajectories. The cut at the top of the jump preserves source frame, position, scale and framing. The final wider shot reveals the destination. All output is composed in HocusPocus; no separate production renderer is used.

The original movement is generated with the installed MiniMax H3 Fused Turbo model, then processed by **Tools → Remove background**. Video 3D renders the shots; Video Editor assembles them. Portal media uses the cue's elapsed time, waits for decoded frames, and releases videos/textures on replacement. It no longer autoplays independently of preview/export.

`montaje.json` records the actual public Video Editor export request and canonical sources on the authoring installation. It is an API/edit record, not a UI project-import format. On another installation, download the four MP4 shots and add them in order in Video Editor; their full durations are the intended edit. The saved final MP4 also has the app's native Video Editor recipe and source manifest. Scene JSON retains independent actor, background, portal and motion controls.

The matte is automatic; a small trace of the source contact shadow can remain around the wheels. The jump path adds stylized height to a painted video cutout; it does not reconstruct a fully three-dimensional skater. Existing background clips are reused without additional generation. See `provenance.json` for generation settings, source identity and native publication records.
