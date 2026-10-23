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
(`idle`, `walk`, `wave`, `talk`, `dance_side`, the action clips `aim`, `shoot`, `claw`, `hit`, `hover`, `kneel_pray`,
`crouch` and the rest of that list) and,
optionally, `animation_bpm` (60–180; every loop lasts whole beats). Procedural
ids such as `spin` are rejected. The job is CPU-only and takes about a second.

The clips are baked for that body: feet stay on the floor, arms stay clear of
a big head or belly, and an A-pose character plays the same motion as a T-pose
one. A finished job lists `humanoid: {pose, arm_drop, confidence, warnings,
clips}`, where `clips` is `[{index, name, duration, loop, contacts}]` (`contacts`: foot landings; `loop: false` marks a hold such as Kneel Pray that a slot plays once, see the [humanoid rig guide](HUMANOID_RIG.md)). A mesh the engine cannot
rig safely fails with `error_code: "not_humanoid"` and `error_reason` one of
`hands_stuck` (arms against the body or straight down), `arms_raised` (arms
well above the shoulders), `turned` (the body is at an angle to the front
view), `single_leg` (no gap between the legs, and no feet under a robe), `legs_too_short`, `asymmetry`,
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

`path` (`{points: [[x, z], ...], duration, name?}`, 2–64 points, 0.5–120 s)
adds a walk along the points with the feet planted. The points are in the
model's own metres: the ground under the hips, starting where the walk starts.
The clip moves the hips, so the Video 3D slot should stay still: set
`motion.walk`, as described in the [humanoid rig guide](HUMANOID_RIG.md).
`interactions` (up to 8) adds sit, reach and look clips toward model-space points: a seat's top, a prop or a look
target (see the [humanoid rig guide](HUMANOID_RIG.md)).
`clips`, `import`, `path` and `interactions` are each optional, but one is required. `import.file` is
a `.bvh`, `.glb` or `.gltf` inside the workspace; the UI uploads it with
`POST /api/v1/model3d/animation-files?workspace=…&filename=…` (raw body, up to
64 MB), which stores it under `animation-imports/` and out of the gallery.
Every animation in the file is retargeted: Mixamo, VRM/VRoid, Unreal, Blender
metarig, Daz and CMU bone names map, any up axis, facing or unit works, the
hips' forward drift is removed so the clip plays in place, and unknown bones
(fingers, props) are listed in `warnings`. A `.gltf` must embed its buffers.
`GET /api/v1/model3d/humanoid-rigs?workspace=…` lists the GLBs that carry the
skeleton, newest first, with their clip names.

The reply's `result.clips` is `[{index, name, duration, contacts}]`. Video 3D plays one
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

## Meshy (cloud generation, rigging and animation)

Meshy is a paid cloud service. It needs the user's own API key in Settings → Services, and every call spends the user's
credits: ask before you generate, rig or animate, and give the cost. A job whose key is missing fails at once and points
at Settings. Everything Meshy makes is downloaded into the workspace as a normal asset with a manifest
(`params.provider: "meshy"`, `params.meshy`: task ids, credits, expiry), so the user can reopen it in the app.
Meshy deletes API outputs after **3 days**; the files are saved when the task ends and no signed link is kept.

### Generate with options

`model3d.generate` with `provider: "meshy"` (or a production profile whose 3D provider is Meshy) takes an optional
`meshy` object next to `prompt` / `image_path` (the prompt may be up to 800 characters):

```json
{"workspace": "my-video", "provider": "meshy", "prompt": "a brass robot, full body",
 "meshy": {"ai_model": "meshy-6-lite", "pose_mode": "t-pose", "target_polycount": 20000, "enable_pbr": true}}
```

| option | values |
| --- | --- |
| `ai_model` | `meshy-6-lite` (cheapest), `meshy-6`, `meshy-7.1`, `latest` (default); `meshy-t2` / `meshy-t2.5` with `model_type: "smart-topology"` |
| `pose_mode` | `a-pose`, `t-pose`, `""`. Use `a-pose` or `t-pose` for a character you will rig |
| `should_remesh`, `topology`, `target_polycount` | default remesh on at 30000 triangles (a dense mesh is too heavy for the Video 3D renderer); `topology` triangle or quad, 100–300000 |
| `geometry_resolution` | `standard`, `2k`, `4k` (only `meshy-7.1` / `latest`) |
| `enable_pbr`, `texture_resolution`, `texture_prompt` | texture; `4k` / `8k` need a model other than `meshy-6-lite` |
| `auto_size`, `origin_at` | Meshy estimates the real height; the origin goes at the `bottom` (default) or `center` |

A contradictory or unknown option is refused (HTTP 400) before any credit is spent. `lowpoly` is retired by Meshy on
2026-10-30 and is not offered. Cost: `meshy-6` / `meshy-7.1` preview 20 + texture 10 credits, `meshy-6-lite` 5 + 10; an
image to a textured model 30 (15 with lite). The gallery picture is saved as `<name>.preview.png`.

### Rig and animate (`engine: "meshy"`)

`model3d.rig` with `engine: "meshy"` rigs a workspace GLB in Meshy's cloud: 5 credits. The model must be a **textured
humanoid**, a `.glb` of at most 100 MB, upright, **facing +Z**, and not Draco or meshopt compressed. `height_meters`
(default 1.7) sets its size. The job saves the rigged GLB and, free with the rig, `<name>-walking.glb` and
`<name>-running.glb` beside it.

`animations` lists Meshy library entries as `action_id` numbers or `key` strings (find them with
`model3d.meshy.animations`; at most 10, 3 credits each). Then a second Meshy task adds them and the published GLB holds
the rig and **one clip per animation, in the order given**. Without `animations` the published GLB is the rigged one.

```json
{"version": 1, "intent_id": "hero-meshy-1", "input": {"workspace": "my-video", "source": "hero.glb",
 "engine": "meshy", "height_meters": 1.7, "animations": ["walk_forward", 14]}}
```

A finished job (`model3d.rig.status`) lists `clips: [{index, name, duration, loop: null, action_id, key, library_name}]`
(Meshy does not say whether a clip loops), `files: [{filename, url, role, clips}]` for the main file and the walking and
running siblings, and `meshy: {rig_task_id, animation_task_id, consumed_credits, expires_at, height_meters, actions}`.
`clip: {index, name}` works in a Video 3D slot as for any other rig. If the animation task fails after the rig was
paid for, the rigged GLB is still saved and `warnings` says so. Cancelling a task Meshy has not started deletes it
(refunded); one already running cannot be stopped, finishes at Meshy, and nothing is saved here.

| failure | `error_code` / `error_reason` |
| --- | --- |
| Meshy cannot find a humanoid pose (HTTP 422) | `not_humanoid` / `meshy_pose_estimation_failed`: generate the model with `pose_mode` `a-pose` or `t-pose` |
| no credits (402) | `meshy_insufficient_credits` |
| bad key (401) | `meshy_invalid_key` |
| over 100 MB, not a GLB, Draco / meshopt | `invalid_input` / `too_large`, `not_glb`, `draco`, `meshopt` |
| unknown library entry | `invalid_input` / `unknown_animation` (nothing paid) |
| too many unfinished tasks for the plan | `meshy_busy` (the call waits up to ten minutes first) |

Nothing is written when a job fails. Meshy's rate limit (429) is waited out with its `Retry-After`.

### The animation library

`model3d.meshy.animations` (and `GET /api/v1/rig/meshy/animations`) reads Meshy's library for free: filters `search`
(name or key), `category` (`WalkAndRun`, `BodyMovements`, `DailyActions`, `Fighting`, `Dancing`), `sub_category`,
`limit` (default 100) and `offset`. Each entry has `action_id`, `name`, `key`, `category`, `sub_category` and
`preview_url`. The list is cached for ten minutes. Never hardcode ids: read them from the library.

### Meshy terms

Each user brings their own Meshy API key; HocusPocus never shares or proxies one (Meshy terms 1.2 and 2.6). On Meshy's
free plan the outputs are licensed CC BY 4.0, so credit Meshy; paid plans own their outputs. Meshy deletes API outputs
after 3 days, and for non-Enterprise plans Meshy may use inputs and outputs to improve its service, so do not send
material the user wants kept private. Every Meshy result is recorded with `provider: meshy` in its manifest.
