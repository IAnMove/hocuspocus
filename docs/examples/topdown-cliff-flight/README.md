# Flight over the abyss

Reusable World3D preset: `topdown-cliff-flight`, under Cinema / Dark Fantasy.

The fixed portrait camera looks down on a single dragon and rider. The distant gorge and the two cliff edges move forward at different speeds. Each cliff is an independent image layer with an editable polygon window; the dragon uses the editor's green color key. Mist and airborne dust are native World3D effects. The dragon glides in a single direction; there is no reversed video or ping-pong loop.

The images were generated through HocusPocus MiniMax Image on 2026-09-16:

- `dragon.jpg`: job `minimax-image-e26d978df9c4`, corrected dorsal view with one head at the top and one tail at the bottom.
- `canyon.jpg`: job `minimax-image-4fade8d395b3`, overhead gorge without a horizon.
- `cliff-left.jpg`: job `minimax-image-e05b22a5fc5a`, foreground basalt ledge.
- `cliff-right.jpg`: job `minimax-image-f8dab11b4c94`, foreground basalt ledge.

The foreground ledges use editable polygon masks. Automatic background removal was evaluated but discarded because it removed parts of the rock. Their masks are deliberately inset and can be adjusted with the image window controls.

Open the preset in the 3D editor to replace the images, adjust the cliff windows, motion endpoints, color key, and effects. The preset ships with local assets and does not require a particular workspace or generation provider to render.

The associated Spanish song, *Alas sobre el abismo*, was generated with Music YuE2 through HocusPocus (job `c29b9157`). The demonstration uses the native World3D export and Video Editor soundtrack assembly. Music is a separate project asset rather than an implicit soundtrack in every copy of the template.

Known production limitations: native server export writes a PNG sequence before encoding, which can produce substantial temporary disk traffic; its canonical progress currently stays at zero during frame capture. This preset uses a stable glide, not an articulated wingbeat animation.
