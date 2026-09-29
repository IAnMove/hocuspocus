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
URLs include the workspace query. Rigid generated meshes have no implied
skeleton or animation.

Reuse the exact intent and body on transport retries. The instance-local
SQLite admission journal replays a submitted job across adapter/server
restarts. Changed parameters conflict. If admission became uncertain after
an error, a retry reports `submission_uncertain` and does not submit again:
inspect Activity rather than inventing another intent. Native in-memory job
status is not restored by a server restart. Job request/PID files live in
`app/settings/model3d-jobs`, separate from shared checkpoint directories,
so one worktree cannot reap another worktree's worker on startup.
