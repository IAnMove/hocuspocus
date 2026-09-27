# Portal Rides

Two 720 × 1280, 30 fps native HocusPocus studies, 6.53 seconds for Downhill and 5.1 seconds for Ash Rider, without sound:

- **Downhill**: a transparent illustrated skater on an independently moving, sloping road. A portal changes the coast into a cloud landscape during the natural-speed ollie.
- **Ash Rider**: a knight riding a flying dragon, crossing from snowy mountains into a volcanic citadel. The actor, landscape, portal and foreground mist remain separate.

Open `/examples/portal-rides/` to play, rate, download or compare the clips. Import a `.world3d.json` using **Studios → Video 3D → Load shot**, or import its `.world3d-template.json` into **My scenes**. Their resources are bundled under `/examples/`.

The app's **Cinematic stage → Endless road** exposes speed, slope and a continuity offset in seconds. To join shots without a road jump, add the preceding scene duration to that offset. A cutout's **Image appearance → Tilt** rotates around its foot anchor; use the same angle as the road. Export and preview evaluate the absolute scene clock, including backward seeks.

All production operations used public HocusPocus APIs: MiniMax image jobs; local H3 Fused Turbo video jobs; `/api/v1/tools/upscale` with `rife2`; `/api/v1/tools/remove-background`; scene saving and `/api/v1/scenes/world3d/export`. No external compositing or alternate video renderer was used. Source cutouts have 315 frames at 48 fps; the skater plays at speed 1; the dragon plays at speed .8, still providing more than 30 unique source frames per exported second. Its source starts at 2.4 seconds to skip a brief wing-matte failure earlier in the take; the full transparent download retains that earlier section. The first, tightly framed dragon take was rejected because its wingtips clipped the canvas. `provenance.json` records the accepted jobs and native publications.

The characters' motion remains generated footage: background removal can retain tiny source shadows or imperfect edges. This collection has no soundtrack. Templates preserve camera, road, media clocks, effect paths and layer transforms for further editing.
