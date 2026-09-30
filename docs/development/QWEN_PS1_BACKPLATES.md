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

## Reusable named style

Select `style: {"preset": "ps1-backplates"}` in an authored production spec. It supplies
the empty-environment art direction, Qwen image defaults and readable lyric styling.
The LLM still decides the subject, palette, places, movements and edits. It should
generate and inspect each background once, then reuse the image and an animated GLB.

The native client avoids writing the full camera and slot document for every shot:

```python
from native import backplate_shot  # clients/native.py from the app skill

spec = {
    "title": "A painted world",
    "song": {"file": "track.wav", "lyrics": "[Instrumental]", "caption": "instrumental",
             "duration": 24, "bpm": 120},
    "style": {"preset": "ps1-backplates"},
    "shots": [
        backplate_shot("station", station_url, actor_url, t0=0, duration=8,
                       clip={"index": 0, "name": "Walking"}),
        backplate_shot("archive", archive_url, actor_url, t0=8, duration=8,
                       start=(-1.3, 0, -.6), end=(.8, 0, .5)),
        backplate_shot("terrace", terrace_url, actor_url, t0=16, duration=8),
    ],
}
```

Copy the existing song into the selected workspace and resolve the image/actor URLs
there. Walking/Idle defaults match the sample GLB; select the actual clip index/name
for other models. Edit each native document's fixed camera, light and slots to match
the painted perspective. Submit the complete spec through `production.run`, or export
the documents through World3D and compose them in Montage as in the verified sample.

The selected style rejects `h3`, on-screen singing, automatic `shots` mappings, missing
backgrounds/actors, camera movement, 3D set dressing, floors, pixel worlds and atmosphere overrides
before production work. It also catches `scene3d.subject` overrides that would discard
the background, and checks both regular shots and fill shots. The preset id is retained
in expanded specs so the guard runs on resume. Native normalized documents with omitted
`dressing` still mean no set. Stills and existing clips remain available for animatics
and reuse. These are structural checks; the image's perspective and empty foreground
still require visual review.

This is a named backend style and an external-agent recipe. The internal chat does
not yet have a dedicated PS1 capability or button, and the brief-only `production.plan`
helper does not select it. Use explicit shots, rather than that helper's automatic plan.

Suggested request to a tool-capable assistant:
“Haz un videoclip en estilo `ps1-backplates`: fondos vacíos de Qwen Image 2.1,
personajes GLB animados y cámara fija. Usa mi canción y mis personajes existentes.
Propón los planos y muestra los fondos para revisión antes de exportar.”
