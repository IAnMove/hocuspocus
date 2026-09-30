# Qwen defaults and prerendered game backgrounds

New production specs and new global production profiles prefer local Qwen Image 2.1.
Omitted image settings use 40 steps, including named looks that previously inherited
Flux's four-step setting. Explicit model and step choices remain authoritative;
existing saved production specs and user profiles are not migrated.

The production default inspects NVIDIA capacity without initializing CUDA. A single
10–16 GiB device selects Qwen Image 2.1 GGUF Q4_K; >=16 GiB selects INT8 ConvRot.
Unknown hardware, multiple GPUs and devices below 10 GiB retain the Qwen selector
and need an explicit suitable configuration. Model installation and resource checks
still apply. This is a conservative capacity heuristic, not a benchmark proving
which model is best. The independent Studio picker retains its saved selection.

## Native backplate workflow

1. Generate an empty fixed-camera environment image with Qwen. Describe the horizon,
   walkable foreground and light direction. Inspect the result before exporting clips.
2. Author a native Video 3D document with the image as `surface: "environment"`, a
   fixed camera, `dressing: "none"` and `floorStyle: "none"`.
3. Place an existing animated GLB in that coordinate system. Match its apparent scale,
   foot placement, travel direction and light to the image. Keep camera motion off.
4. Export through `scenes.world3d.export`; compose the clips and existing song in Montage.
   Retain the native documents, commands, receipts and source references for editing.

The reusable HTTP client and native document recipe are in
`pinokio_agent/skills/api/hocuspocus/clients/native.py`. They call the app's public
contracts and reuse its existing renderer. No 3D environment is generated or rendered.

This first recipe handles clear walkable areas. Walking behind a painted doorway,
matching cast shadows and enforcing boundaries require authored occlusion and grounding
work. Passing the technical export checks does not approve the visual composition.
