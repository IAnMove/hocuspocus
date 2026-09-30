---
name: hocuspocus-native-backplates
description: Generate Qwen background plates and export editable Video 3D shots through the native HTTP contracts.
---

# HocusPocus API

## Clients

`clients/native.py` provides JSON HTTP requests and a fixed-camera backplate document.
Pass the discovered base URL, workspace, durable image URL and animated GLB URL at runtime.

## Operations

- Create an output workspace with `POST /api/v1/workspaces`, `{name}`.
- Submit images with `POST /api/v1/generation/commands`: `{version:1, operation:"generation.image", intent_id, input:{workspace, model_type, prompt, resolution, num_inference_steps, seed, guidance_scale}}`.
- Read the receipt's `taskIds` through `GET /api/v1/tasks/{task_id}?workspace=...`.
- Export the authored native document with `POST /api/v1/scenes/world3d/export`: `{version:1, operation:"scenes.world3d.export", intent_id, input:{workspace, document, refs:[]}}`.
- Read the export task to completion. Admission is not a rendered video.

## Outputs

Keep commands, receipts, native `.world3d.scene.json` documents, Qwen images and MP4s in the output workspace.
Reuse an intent only for an identical request. Preserve the original audio and model assets.

## Notes

An image slot with `surface:"environment"` is a screen background. `dressing:"none"`,
`floorStyle:"none"` and a fixed camera leave the generated environment intact.
Animated characters can travel in depth; matching the image's perspective and lighting
requires visual review. This basic recipe does not implement foreground occlusion or collisions.
