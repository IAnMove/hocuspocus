# Humanoid rig

A T-pose or A-pose person can take the standard Mixamo-named skeleton and the
built-in clip library. Fingers, face, and quadrupeds stay out of scope. The
rig runs on CPU. Only the mesh generation below uses the GPU.

## Ask for a T-pose still

Use one front view, full body, plain background. A prompt that produced a
usable mesh:

> A small stylized pet creature standing in a perfect T-pose, full body from
> the top of the head to both feet, facing the camera straight on. Both arms
> extend straight out to the sides at shoulder height, with a clear gap
> between each arm and the torso. Legs are slightly apart and straight. Large
> round head, short limbs, simple smooth surfaces, character model sheet.
> Plain flat light-gray studio background, even soft light, centered, feet
> fully in frame.

Keep the arms away from the torso and the legs apart. Hands fused into a
mitten are expected: this rig has no finger bones.

## Hunyuan3D settings that kept the arms apart

One real generation, 2026-10-01, on the cached shape model. Hunyuan3D 2.1
weights were not on disk, so this used Hunyuan3D 2 Mini Turbo
(`hunyuan3d-2mini-turbo`, subfolder `hunyuan3d-dit-v2-mini-turbo`).

| Setting | Value |
| --- | --- |
| steps | 5 |
| guidance | 5.0 |
| octree | 384 |
| chunks | 20000 |
| marching cubes | `dmc` |
| texture | `none` |
| FlashVDM | off |
| CPU offload | on |
| background removal | on |
| face cap | 80000 |
| seed | 1207 |

Wall time was about 53 seconds. Shape sampling and volume decode took 21
seconds. The mesh is about 1.0 m tall, faces +Z, and has a visible gap at
each armpit and between the legs. Landmarks landed in 1.6 seconds and the
rig accepted it.

That is 1 of 1 attempts usable. Five repeats were not run: the check is one
GPU generation. A lower octree (the eco preset's 128) was not tried.

## After the mesh

`model3d.rig` with `engine: "humanoid"` and `pose: "t"`. Then
`model3d.animate` for `walk`, `wave`, and `dance_side`. The call shapes are
in [Model3D over MCP](MODEL3D_MCP.md). A mesh with the hands stuck to the
body, or with one leg, returns `not_humanoid` and a reason instead of a
broken skeleton.
