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

`model3d.rig` accepts `engine: "humanoid"` on a GLB of one person in a T or A
pose. Set `pose` to `"t"` or `"a"` and `animations` to ids from
`humanoid_animations` in `/api/v1/rig/capabilities` (`walk`, `wave`,
`dance_side`, and the rest of that list). Procedural ids such as `spin` are
rejected. The job is CPU-only. A mesh that is not a person — hands stuck to
the torso, or only one leg — finishes with error `not_humanoid` and a reason.
The published GLB keeps the source mesh and adds a Mixamo-named skeleton.

`model3d.animate` adds clips to a GLB that already has that skeleton:

```json
{
  "version": 1,
  "intent_id": "pet-clips-1",
  "input": {
    "workspace": "my-video",
    "source": "pet-rigged.glb",
    "clips": ["walk", "wave", "dance_side"],
    "bpm": 120
  }
}
```

`input.import.file` may name a `.bvh`, `.glb` or `.gltf` already in the same
workspace. The reply's `result.clips` is `[{index, name, duration}]`. Video 3D
plays one of those by `clip: {index, name}` on a model slot. A file without
the 25 standard bones fails with `standard humanoid skeleton not found`.
Same intent and body replays the published file. How to prompt a T-pose still,
and the Hunyuan3D settings that kept the arms apart, are in the
[humanoid rig guide](HUMANOID_RIG.md).

Reuse the exact intent and body on transport retries. The instance-local
SQLite admission journal replays a submitted job across adapter/server
restarts. Changed parameters conflict. If admission became uncertain after
an error, a retry reports `submission_uncertain` and does not submit again:
inspect Activity rather than inventing another intent. Native in-memory job
status is not restored by a server restart. Job request/PID files live in
`app/settings/model3d-jobs`, separate from shared checkpoint directories,
so one worktree cannot reap another worktree's worker on startup.
