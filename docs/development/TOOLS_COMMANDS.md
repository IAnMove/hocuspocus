# Tools upscale commands

The first shared Tools operation is `tools.upscale`, version 2. It accepts the
same envelope used by the other shared commands:

```json
{
  "version": 2,
  "operation": "tools.upscale",
  "intent_id": "intent-123",
  "input": {
    "workspace": "my-workspace",
    "workspace_collection_id": "collection-123",
    "params": {
      "source": "/api/v1/file/poster.png?workspace=source",
      "source_workspace": "source",
      "source_kind": "image",
      "method": "lanczos2",
      "seed": -1,
      "wangp_processor_settings": {}
    }
  }
}
```

`workspace` is the output workspace. An optional `workspace_collection_id`
identifies the logical collection associated with the command; it is retained
in the durable command snapshots, provenance and fingerprint and is not a native processor setting. `source` is either an exact asset ID
(`asset_...`) or one canonical local API reference: an upload URL, a
workspace-qualified file URL, or an exact asset URL. `source_workspace` is
optional; when supplied for a source URL it must match that URL's workspace.
Use `__uploads__` for an upload URL. For an asset ID with several catalog locations, omit the scope
only when there is exactly one location, otherwise select one exact
`source_workspace`. Absolute host paths, remote URLs, traversal, fragments,
missing scopes and ambiguous source locations are rejected.
The source kind must be `image` or `video`, and `method` is required rather
than selected by a default.

The current method names come from the native Tools worker and are published
by `tools_upscale_schema()`. The preparation layer calls the existing WangGP
processor selection and settings validators. `WangpProcessorSettings` is the
only typed settings model; processor prompts retain their literal spelling.
The preparation adapter resolves processor reference images against their
explicit source workspace and records size and SHA-256 identity after Pillow
verification. The current native scalar-settings validator still rejects H3
reference-image arrays; that option is not yet end-to-end supported. Image sources receive the same
verification. Video sources receive the existing `video_editor.probe_media`
probe and must report positive dimensions and duration.

The freeze result keeps `original` detached and value-preserving. `effective`
adds only `seed=-1` and an empty processor-settings object when omitted. Its
fingerprint covers operation, output workspace and effective parameters while
excluding `intent_id` and caller metadata. The optional collection identity is
part of that fingerprint. The public receipt reports the physical output workspace;
collection identity is not a separate public receipt field. Resource identities are attached by the shared
submission service after preparation; the adapter does not create a queue or
write a journal.

The adapter transfers the prepared request to the existing
`/api/v1/tools/upscale` native endpoint through an in-process callback. The
endpoint remains the authority for its established confined source resolver
and the existing `tools_upscale.py` worker remains the execution authority.
Real mode selects `_run_tool_upscale`; simulation mode selects the existing
`_run_generation` harness through the shared operation adapter. No model or
processor is downloaded by this command contract.

This slice covers upscale only. Revoice, recast, music, audio and model3d
require their own explicit contracts and are not advertised by this catalog
entry. Still-image background removal is `image.remove_background` (version 1,
`auto` / `u2net` / `screen`); see [Tools HOWUSEIT](../tools/HOWUSEIT.md). Resource preparation proves identity and media
inspectability; final output decoding and processor quality remain execution
QA responsibilities.
