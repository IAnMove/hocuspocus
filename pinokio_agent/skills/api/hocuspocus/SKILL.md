---
name: hocuspocus-native-backplates
description: Generate Qwen background plates and export editable Video 3D shots through the native HTTP contracts.
---

# HocusPocus API

## Clients

`clients/native.py` provides JSON HTTP requests and a fixed-camera backplate document.
Pass the discovered base URL, workspace, durable image URL and animated GLB URL at runtime.
`backplate_shot(key, image_url, actor_url, t0=..., duration=..., clip=..., start=..., end=...)`
wraps the document as an authored `kind:"scene3d"` production shot. Choose the clip index
and name from the actual GLB; Walking/Idle defaults describe the sample asset only.

## PS1 style

Use `style:{preset:"ps1-backplates"}` and explicit authored shots. Generate each empty
background once with Qwen Image 2.1, inspect it, and reuse it across actor movements.
The LLM chooses places, palette, camera perspective per image, actors, GLB clips,
paths, light, durations and cuts. Keep the camera fixed within a shot.
The production validator rejects H3, lip-sync, automatic shot planning, moving cameras and rendered sets
with `invalid_backplate_shot` before work starts; stills may be used for an animatic.
An existing workspace song can be supplied as `song.file` to avoid music generation.
Use a complete authored spec with `production.run`; the brief-only `production.plan`
helper and internal chat have no dedicated PS1 action. This skill is for tool-capable external agents.

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
