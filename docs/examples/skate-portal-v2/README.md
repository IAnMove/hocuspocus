# Portal Ride — three expanding world transitions

Open `/examples/skate-portal-v2/` in HocusPocus to watch and rate the 13.2-second vertical film (720 × 1280, 30 fps, silent).

Seven native Video 3D documents reuse the generated, transparent skateboarder and three independently moving backgrounds. Each portal appears at scale zero, rotates along a keyframed path, and expands during an ollie. Screen projection preserves the destination landscape at full-frame scale; the next shot matches its video clock, camera and actor landing pose.

Download a **Plano** JSON and open it with **Video 3D → Load shot**, or import its reusable template into **My scenes**. Edit portal points in **World effects → Animated path**. Their times use the scene clock, angles may include full turns, and zero scale hides the portal. Dragging an animated effect writes a point at the current scene time. A full path replaces its nearest point when edited with the gizmo.

**Landscape inside the portal → Window into the next world** keeps video aligned to the viewport. Continue with the same camera and video time for a seamless expanding transition. Video start, speed and looping are editable. Disable this mode for a conventional portal with local texture coordinates.

The cutout is reused from `/examples/skate-portal/skate-jump.webm`; backgrounds and the actor reference are included in `/examples/moving-cutouts/`. Download the seven MP4 files and add them in order to Video Editor to reassemble them on another installation. `montaje.json` records the native export request; it is not an editor-project import file. `provenance.json` records the actual app receipts.

Generation, background removal, rendering and assembly use HocusPocus. No separate video renderer was used. The actor has one reusable generated ollie; transitions continue its landing pose, while the next run-up reuses the crouch. All layers remain replaceable.
