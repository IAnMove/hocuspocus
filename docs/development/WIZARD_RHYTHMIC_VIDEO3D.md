# Wizard rhythmic Video3D workflow

`create_rhythmic_3d_video` is the first complete durable Wizard production workflow. It turns either an exact existing audio output or a generated song into a saved, editable Video3D scene and a published MP4.

## Contract

The capability requires explicit `confirm: true`, a scene name and the exact name of an existing visual output. It accepts either `audio_output_name` or a music `prompt`. An existing audio file is resolved unambiguously in the active workspace; a prompt queues Studio Music and stores its canonical task ID.

```text
resolve/generate song -> wait exact task -> create scene -> add visual + camera
-> attach exact audio -> analyze once -> bake keyframes -> save scene -> MP4
```

The song step is the only queued step. It advances only from that exact canonical task's completion event. A failed or cancelled song ends the workflow before Video3D receives a mutation.

## Video3D operations

The common registry now exposes small operations that make the workflow auditable and usable independently:

- `create_3d_scene`, `set_3d_scene_properties`;
- `add_3d_scene_layer`, `update_3d_scene_layer`, `remove_3d_scene_layer`;
- `attach_3d_scene_audio`, `analyze_3d_scene_audio`;
- `apply_3d_choreography`, plus migrated `open_3d_scene`, `save_3d_scene` and `export_3d_scene`.

They cross the typed scene UI bus. The mounted Video3D panel resolves exact gallery outputs, applies the real local state operation, and returns a structured result rather than a sentence inferred by the LLM.

## Rhythm behavior and recovery

Audio analysis runs once per attached track. The workflow checkpoint stores a bounded compact grid (BPM, duration, 200 beats and 200 downbeats), not raw audio or a giant onset envelope. On a reload, a choreography retry rebuilds the same editable keyframes from that grid without a second analysis.

The visual layer follows ordinary beats with the requested pulse/bounce/peek profile. A dedicated camera reacts only to downbeats with restrained `camera-punch` keyframes. No global flashing is introduced. Every result is an ordinary timeline keyframe that remains visible and editable in Video3D.

Saving precedes MP4 export. Therefore an encoder/export failure leaves the editable scene output intact and the workflow becomes `partial`; Resume retries only the export step. Layer creation is idempotent by exact name and the build step can recreate an absent in-browser scene after a reload.

## Test boundary

`ui/tests/rhythmic3dWorkflow.test.mjs` uses in-memory adapters: song failure creates no scene mutation; export failure retains the saved scene and Resume retries only export; analysis is not repeated. It uses no GPU, audio model or external provider. The opt-in real smoke remains a separate Phase 8 item.
