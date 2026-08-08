# Workflow resources and smart asset imports

## Scheduling policy

Maestro schedules expensive work by the resource that executes it, not by its
media type. Every resource lane has capacity one by default:

- `local_gpu:<index>`: image and video work on the same GPU is sequential.
- `local_cpu:llm`: a CPU planner may overlap local GPU rendering.
- `remote:<origin>`: calls to the same remote scheme/host/port are sequential.
- Different remote origins or different GPU indices are independent lanes.

`Settings → Services → Parallel workflows by resource` is enabled by default.
Turning it off disables producer/consumer overlap without changing queued work.
It never increases concurrency within one GPU or remote host.

Director currently pipelines MiniMax Image-01 with local MiniMax H3 in automatic
mode. As soon as a shot image is complete, H3 may render that shot while the
remote service prepares the next image. Guided mode remains phase-based because
the user reviews the complete image set before video generation. A remote or
CPU planning LLM may also run while unrelated local GPU work continues.

The active pipeline publishes its resolved lanes and progress in the Activity
footer. With debug trace enabled, resource-plan, parallel-start and asset-ready
events are written to the correlated JSONL trace.

## Smart Story Lab assets

The Assets tab accepts up to 24 images plus one optional batch description.
Maestro uploads the images, sends them to the selected vision-capable Story Lab
provider in their original order, and asks for one closed-schema classification
per image. The analysis may group multiple views under one target identifier.

Nothing is applied automatically. The review screen lets the user edit:

- inclusion;
- character, location, world, prop, style or ignore classification;
- existing or new destination;
- reusable name, description and visual prompt.

Applying a batch preserves existing references, attaches grouped views to the
same entity and creates new characters or locations as editable drafts. The
backend accepts only files already staged under Maestro's upload directory, so
the multimodal endpoint cannot be used to read arbitrary filesystem paths.

## Next compatible extensions

- Remote video providers can use the same producer/consumer path after their
  adapter supplies a `video_base_url` and supports per-shot submission.
- Multiple local GPUs are already distinct lane identities; model workers still
  need explicit GPU routing before Maestro can exploit them.
- Configurable capacity above one is intentionally not exposed. Provider rate
  limits and local server saturation should be measured before allowing it.
