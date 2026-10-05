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
- Cloth that fills those gaps is fine when it hangs off the body: a cape over
  the shoulders and upper arms (`covered_arms`), a cape, coat tails or an open
  robe over the legs (`covered_legs`). The arms and legs are found on the body
  under it, and the cloth follows the shoulders or hangs from the hips.
- A long robe or skirt down to the ankles is fine when the feet show under
  its hem (`legs_hidden`): the legs are placed from the feet, and the robe hangs
  from the hips and thighs, so a stride sways it instead of tearing it and a
  bent knee does not fold it.

What the engine refuses, instead of guessing a skeleton (`not_humanoid` plus a
reason): arms against the body or hanging straight down (`hands_stuck`), arms
raised well above the shoulders (`arms_raised`), a body turned at an angle to
the front view (`turned`), legs together, or a dress or robe down to the floor
that hides the feet (`single_leg`), legs too short or hidden (`legs_too_short`), very different left and right
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
   Rays along the depth axis tell cloth from body: a pixel whose solid spans
   all miss the slab around the body's middle plane is cloth (a cape tent with
   air inside, a cape behind the legs, the hollow of an open robe). When cloth
   filled a gap, the arms or legs are looked for again without it.
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
   of the nearest surface. Cloth below the hips and a robe that hides the legs
   hang from the hips: the hips alone at the waist, the thighs taking over
   lower down (about half of their swing), left and right blended across the
   middle, and no pull from the knees. Cloth above the hips, such as a cape,
   has its weights blurred along the surface.
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

### Foot landings

Each clip records when a foot touches down, for footsteps that follow the animation. The landings are stored on the
animation as `extras.hocuspocus_contacts`:

```json
[{"t": 0.4667, "foot": "right", "strength": 0.261}, {"t": 0.9667, "foot": "left", "strength": 0.261}]
```

- `t` is in clip seconds.
- `strength` (0–1) is the downward speed of the foot just before it lands. A jump landing is around 0.76; a walk step is
  around 0.26.

How a landing is detected:

- A landing is the first frame a foot is back within 1.2 % of the leg length above the floor, after rising above 3.5 %.
  A clip that keeps both feet down (Idle, Wave, Clap) records none.
- Heights are measured against the floor, so in-place walks count like real steps.
- Library clips and imported animations get the same detection. A looping library clip is scanned once around its loop.
- Walk lands within one frame of the frame where its recipe puts the foot back down.
- Run lands about two frames after the start of its stance phase, because the body is still coming down from the
  flight phase.

The rig sidecar, the `model3d.rig` result and the `model3d.animate` result list the same `contacts` for each clip.
pygltflib drops empty lists when it saves, so a clip without landings has no key.

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

## Sequence clips on a slot

A Video 3D model slot can chain clips with crossfades instead of playing a single
`clip`. While `clips` is present it drives the model, and `clip` and
`clipPlayback` are ignored:

```json
"clips": [
  {"clip": {"index": 0, "name": "Idle"}, "start": 0},
  {"clip": {"index": 1, "name": "Wave"}, "start": 1.5, "fade": 0.6},
  {"clip": {"index": 3, "name": "Path Walk"}, "start": 3, "loop": false}
]
```

- **`start`.** In scene seconds. A cue lasts until the next one starts, or until the shot ends.
- **`fade`.** Seconds, 0.3 by default; 0 is a cut. The next cue fades in over its own first `fade` seconds with a
  smooth curve, while the cue before it keeps playing.
- **`speed`, `offset` and `loop`.** They set the clip time: `offset` is where the clip starts, `speed` goes from 0.1 to
  4, and `loop` defaults to true. Without a loop, the clip holds its last frame.
- **`duration`.** Stops the cue's clock early and holds the pose.
- **Before the first cue.** The model holds the first cue's start pose.
- **Limits.** Up to 32 cues; invalid cues are dropped and the rest are sorted by start.

The weights at any time come from `clipWeightsAt(cues, sceneSeconds, shotDuration, clipDuration)`, a pure function of
scene time. Seeking, scrubbing and motion-blur subframes therefore always give the same pose.

- **Same clip twice.** Two cues of the same clip share one animation action, so a fade between them cuts to the cue
  with more weight.
- **A baked walk as a cue.** A baked Path Walk can be one cue: the slot stays still while that bake matches its path,
  as above.
- **Footsteps.** Foot landings for a sequence come from `cueContactsInScene`.

## Walk a path without sliding

Video 3D used to move a model along its path while the clip walked in place,
so the soles skated. **Video 3D → Travel → Walk without sliding** (or
`model3d.animate` with `path`) bakes a new clip, «Path Walk», on the rigged
character:

- **Footprints.** The hips follow the path (a centripetal Catmull-Rom curve
  through the points). Every footprint stays fixed in the world while its foot
  carries the body, and each swing goes from one footprint to the next, turning
  with the path.
- **Steps.** Steps lengthen with speed, between 0.35 and 0.85 leg lengths. A
  path faster than a natural walk (2.6 leg lengths per second) is still baked,
  and the result lists `path_too_fast`.
- **Start and stop.** The walk starts and ends standing, with the feet side by
  side.
- **Measured.** A planted foot slips less than 0.2 % of the leg on straight,
  90° and S-shaped paths. The body faces the path, except for the walk's own
  5° hip twist.

The clip moves the hips, so the slot stays at its start: the scene records
`motion.walk = {sourceUrl, clip, key}`. If the path, the slot's position, turn
or scale, or the shot length change, the bake is stale. The slot then slides
again until the walk is baked anew. A new GLB is saved; the original stays.

`motion.points` adds waypoints between the start and `to`. Video 3D walks them
on the same curve the bake uses.

## Sit, reach and look

`model3d.animate` with `interactions` bakes clips that meet the scene. Their points are in the model's own metres;
Video 3D exposes `modelSpacePoint` on the stage to convert a scene point.

- **`{kind: "sit", seat: [x, y, z], stand_up?, look?}`** lowers the hips onto the middle of the seat's top and stays
  seated, or stands up again at the end with `stand_up`. The hips end within 2 cm of the seat, the feet stay on the
  floor, and the torso leans forward while sitting down. Natural seat heights are 0.3–0.9 leg lengths above the
  floor; outside that the result lists `seat_height_unusual`. A seat too far behind the feet lists `seat_out_of_reach`.
- **`{kind: "reach", target, hand?: left | right | auto, hold?, look?}`** brings a wrist to the target and holds it,
  or returns it with `hold: false`.
  - The torso turns the reaching shoulder toward the target, bends, and crouches for low targets. It does so only as
    much as needed: the smallest lean that reaches is found by bisection.
  - A reachable target is reached to within 1 % of the arm.
  - A target the arm cannot reach even with the lean lists `target_out_of_reach`.
- **`{kind: "look", target}`** turns the head and neck toward a point (±70° of yaw).

Each interaction takes a `duration` (0.8–30 s) and a `name`. Warnings come back prefixed with the clip's name.

## Known limits

- No fingers, face or eyes; the hand moves as one piece. What generated meshes offer for hands, and the proposed next
  steps, are in `docs/development/HUMANOID_HANDS_RESEARCH.md`.
- Raising arms that were modeled steep (A pose past ~55°) stretches the
  shoulders a little; the result lists `arms_steep`.
- Characters with arms modeled down at the sides, robes or fused legs are
  refused rather than rigged badly.
- Walk and run play in place; Video 3D moves the slot.
