# Model3D over MCP

The opt-in MCP endpoint exposes the existing native Model3D REST contract.
The same job manager validates images, acquires the local GPU lane, starts
the isolated Hunyuan3D worker and publishes the asset in the workspace.
Check `/api/v1/model3d/capabilities` before a real generation. An installed
runtime is not proof of successful inference; inspect a completed GLB too.

```json
{
  "version": 1,
  "intent_id": "tree-1",
  "input": {
    "workspace": "my-video",
    "image_path": "/api/v1/file/tree.png?workspace=my-video",
    "preset": "eco",
    "texture_mode": "none",
    "reduce_face": true,
    "target_face_num": 900,
    "output_format": "glb"
  }
}
```

Call `model3d.generate` with that envelope. `input` is the existing
`POST /api/v1/model3d/generate` body; its options and image path validation
are unchanged. Replace `image_path` with `prompt` for text input. Text uses
the existing MiniMax reference-image configuration and fails visibly when
that configuration is unavailable; there is no substitute model.
See the [native Model3D guide](../3d-video-compositor/HOWUSEIT.md).

The reply is `{version, operation, status, result}`; `result.job_id` is the
native job id. Poll `model3d.status`:

```json
{"version": 1, "input": {"workspace": "my-video", "job_id": "<returned-job-id>"}}
```

`result` retains the native progress, phase, error, filename and URL. File
URLs include the workspace query. A generated mesh has no skeleton until
`model3d.rig` runs.

## Humanoid rig and clips

`model3d.rig` accepts `engine: "humanoid"` on a GLB of one person standing in
a T or A pose. The pose is detected (`pose` is an ignored hint). Set
`animations` to ids from `humanoid_animations` in `/api/v1/rig/capabilities`
(`idle`, `walk`, `wave`, `talk`, `dance_side` and the rest of that list) and,
optionally, `animation_bpm` (60–180; every loop lasts whole beats). Procedural
ids such as `spin` are rejected. The job is CPU-only and takes about a second.

The clips are baked for that body: feet stay on the floor, arms stay clear of
a big head or belly, and an A-pose character plays the same motion as a T-pose
one. A finished job lists `humanoid: {pose, arm_drop, confidence, warnings,
clips}`, where `clips` is `[{index, name, duration}]`. A mesh the engine cannot
rig safely fails with `error_code: "not_humanoid"` and `error_reason` one of
`hands_stuck` (arms against the body or straight down), `arms_raised` (arms
well above the shoulders), `turned` (the body is at an angle to the front
view), `single_leg` (no gap between the legs), `legs_too_short`, `asymmetry`,
`not_upright` or `degenerate`. A source the engine cannot read, such as a
Draco or meshopt compressed GLB, fails with `error_code: "invalid_input"`.
Nothing is written in either case.

`model3d.animate` adds clips to a GLB that already has the skeleton:

```json
{
  "version": 1,
  "intent_id": "pet-clips-1",
  "input": {
    "workspace": "my-video",
    "source": "pet-rigged.glb",
    "clips": ["walk", "wave", "dance_side"],
    "bpm": 120,
    "import": {"file": "animation-imports/samba-1a2b3c4d.glb"}
  }
}
```

`clips` and `import` are each optional, but one is required. `import.file` is
a `.bvh`, `.glb` or `.gltf` inside the workspace; the UI uploads it with
`POST /api/v1/model3d/animation-files?workspace=…&filename=…` (raw body, up to
64 MB), which stores it under `animation-imports/` and out of the gallery.
Every animation in the file is retargeted: Mixamo, VRM/VRoid, Unreal, Blender
metarig, Daz and CMU bone names map, any up axis, facing or unit works, the
hips' forward drift is removed so the clip plays in place, and unknown bones
(fingers, props) are listed in `warnings`. A `.gltf` must embed its buffers.
`GET /api/v1/model3d/humanoid-rigs?workspace=…` lists the GLBs that carry the
skeleton, newest first, with their clip names.

The reply's `result.clips` is `[{index, name, duration}]`. Video 3D plays one
of those by `clip: {index, name}` on a model slot. Same intent and body
replays the published file. A request the worker refuses answers HTTP 422 with
`detail.code` `invalid_input` (a file without the 25 standard bones reports
`standard humanoid skeleton not found`; an animation file without a humanoid,
a compressed mesh or an unknown clip id read the same way) or `not_humanoid`,
and the same intent replays that answer. A worker crash answers HTTP 500
`animate_failed` with nothing written; retry it with a new intent. How to prepare a model, and what the
engine refuses, are in the [humanoid rig guide](HUMANOID_RIG.md).

Reuse the exact intent and body on transport retries. The instance-local
SQLite admission journal replays a submitted job across adapter/server
restarts. Changed parameters conflict. If admission became uncertain after
an error, a retry reports `submission_uncertain` and does not submit again:
inspect Activity rather than inventing another intent. Native in-memory job
status is not restored by a server restart. Job request/PID files live in
`app/settings/model3d-jobs`, separate from shared checkpoint directories,
so one worktree cannot reap another worktree's worker on startup.
