# Music finalization (phase 5)

Status: server-side publish of a reserved music attempt. Inference stays
outside this module. No GPU, no provider calls.

Reservation is [MUSIC_SUBMISSION.md](MUSIC_SUBMISSION.md). This step takes
the reserved `generation_id` and already-produced audio bytes.

## Stages

1. `bytes` — audio file is in the workspace. Duration is stored separately
   from any requested length. WAV is measured from frames. Non-WAV (MiniMax
   MP3) keeps the worker-reported `duration_seconds` when headers are not
   WAV.
2. `manifest` — asset sidecar + generation record projection.
3. `candidate` — Story library row for the reserved candidate ID.

If sidecar/metadata fails after bytes exist, status is `repair_pending`.
The wav is not deleted. Repeating finalize resumes without inference.

## Selection

If the cue already has `selectedCandidateId` pointing at another song,
finalization still marks the reserved candidate `ready` and does **not**
steal the selection.

## Cancel

Cancel before bytes: no candidate publish. Cancel after bytes: existing
audio is kept; reconcile reports `needs_inference: false`.

## Command

```python
from app.services.music_finalization import finalize_reserved_music, reconcile_reserved_music
```

Tests use a fake worker (tiny WAV). Real generation is not part of CI.
