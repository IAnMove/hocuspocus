# Humanoid rig

A character standing in a T or A pose can take the standard Mixamo-named
skeleton, the built-in clip library, and animations imported from other tools.
Everything runs on CPU in about a second; only generating the mesh uses the GPU.
Fingers, face and quadrupeds are out of scope.

In the app: **Studios → Animate**, engine **Humanoid (standard)**. Over MCP:
`model3d.rig` with `engine: "humanoid"`, then `model3d.animate`
([Model3D over MCP](MODEL3D_MCP.md)).

## What a model needs

- Standing upright (Y up), facing the front, in a **T pose** (arms straight out,
  or raised up to about 35° above horizontal) or an **A pose** (arms down and
  out, up to about 70° below horizontal).
- A visible gap **under each arm** and **between the legs** when seen from the
  front. Chubby mascots, big heads, ears, hats and box-built robots with gaps
  between pieces are fine.
- A model facing backwards is turned automatically and reported.
- A figurine on a base or pedestal wider than its feet is fine: the feet stand
  on the top of the base, the base moves with the hips, and the result lists
  `on_a_base`.

What the engine refuses, instead of guessing a skeleton (`not_humanoid` plus a
reason): arms against the body or hanging straight down (`hands_stuck`), arms
raised well above the shoulders (`arms_raised`), a body turned at an angle to
the front view (`turned`), legs together, a dress or a robe (`single_leg`),
legs too short or hidden (`legs_too_short`), very different left and right
sides (`asymmetry`), a model lying down (`not_upright`) and an empty mesh
(`degenerate`). A GLB with Draco, meshopt or quantized geometry fails with
`invalid_input`; export it without compression. Nothing is written when a
model is refused; regenerate it in a T or A pose, or use the Procedural engine
for props and creatures.

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

Hands fused into a mitten are expected: this rig has no finger bones.

### Hunyuan3D settings that kept the arms apart

One generation on 2026-10-01 with Hunyuan3D 2 Mini Turbo
(`hunyuan3d-2mini-turbo`): steps 5, guidance 5.0, octree 384, chunks 20000,
marching cubes `dmc`, texture `none`, FlashVDM off, CPU offload on, background
removal on, face cap 80000, seed 1207. About 53 seconds of wall time; the mesh
was about 1.0 m tall, faced +Z and had a gap at each armpit and between the
legs. One of one attempts was usable; five repeats were not run.

## How it works

1. **Landmarks.** The mesh is rasterized seen from the front. The gap between
   the feet is followed up to the crotch, the narrowest row under the head is
   the neck, and the arms are the thin branches left when the torso core is
   opened away. Depth for every joint comes from the mesh slice through it.
   Thresholds are fractions of the height, so a mascot and an adult both work.
2. **Skeleton.** 25 Mixamo-named bones (`Hips` … `RightToe_End`, no prefix).
   Each bone's local axes are the character's axes in a perfect T pose (+X
   left, +Y up, +Z forward); the rest rotations bend them onto the modeled
   pose. A clip value of zero always means "T pose", so the same clip fits a
   T-pose and an A-pose model. `Hips` carries a scale of `height / 1.7`.
3. **Weights.** Up to four bones per vertex. Each bone seeds the surface it
   clearly owns and distances grow along the mesh, so the bottom of a big head
   never follows the arm under it and one thigh never drags the other.
   Everything above the neck notch and within the head's width belongs to the
   head and neck. Loose pieces (eyes, buttons, robot boxes) copy the weights
   of the nearest surface.
4. **Clips.** Built for this body: feet are planted with two-bone IK and kept
   on the floor, hands reach targets relative to the chest (the clap meets
   palm to palm; a shrug opens the palms upward),
   and the arm limits measured on the mesh keep arms out of a big belly or head.
   Every loop lasts whole beats at the chosen BPM (60–180) and closes exactly.

The rigged GLB keeps the original mesh, materials and textures. Its `Hips` node
stores the facts later clips need in `extras.hocuspocus_humanoid` (version,
floor, facing, arm limits, chest depth). A sidecar `<file>.humanoid.json` keeps
the landmarks, detected pose, confidence and warnings.

## Clips

| Category | Clips |
| --- | --- |
| Movement | Walk, Run, Jump, Sit Down (in place) |
| Gestures | Wave, Cheer, Clap, Victory, Talk, Nod, Look Around, Bow, Point, Shrug |
| Dance | Dance Bounce, Dance Side, Dance Arms |
| Standing | Idle, Breathe |
| Action | Punch |

Clip names are what Video 3D plays: a model slot uses `clip: {index, name}`.

## Add animations later

**Studios → Animate → Add animations to a rigged character** lists the GLBs in
the workspace that carry the skeleton. Pick one, choose clips and/or a `.bvh`,
`.glb` or `.gltf` animation file, and a new GLB is saved; the original stays.
Imported files may come from Mixamo, VRM/VRoid, Unreal, a Blender metarig, Daz
or CMU motion capture: bones are matched by name and the spine by hierarchy,
any up axis, facing or unit works, rig prefixes such as `Bip01`,
`Character1_` or `Armature|` are ignored, every animation in the file is imported,
and the hips' forward drift is removed so the clip plays in place. Bones the
rig does not have (fingers, props) are skipped and listed.

Rigs made by the first humanoid release (identity rest rotations, no `extras`
marker) still accept new clips: each bone is corrected to the canonical frame.

## Known limits

- No fingers, face or eyes; the hand moves as one piece. What generated meshes offer for hands, and the proposed next
  steps, are in `docs/development/HUMANOID_HANDS_RESEARCH.md`.
- Raising arms that were modeled steep (A pose past ~55°) stretches the
  shoulders a little; the result lists `arms_steep`.
- Characters with arms modeled down at the sides, robes or fused legs are
  refused rather than rigged badly.
- Walk and run play in place; Video 3D moves the slot.
