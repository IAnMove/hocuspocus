# GLB animation import contract

Status: G1 inspector accepted. G2 HTTP factory exists unmounted; it is not a
public file reader until a later adapter is owned and wired.

The inspector is a CPU-only, stdlib reader. It does not import torch, trimesh,
pygltflib, bpy, WanGP, or `_launch_runtime.py`. It does not render, download,
or follow external resources.

## Public API

```python
from services.procedural_3d import inspect_glb, inspect_glb_bytes, GlbInspectorLimits

report = inspect_glb(path, limits=None)
report = inspect_glb_bytes(data, limits=None)
```

`path` is an internal argument. It is not authorization to expose an arbitrary
filesystem path over HTTP. Asset IDs and workspace membership stay with the
catalog resolver; this module must not be mounted as a public file reader.

`inspect_glb` raises `FileNotFoundError` or `IsADirectoryError` for OS-level
path problems. Malformed or unsupported GLB content is returned as a report,
not raised.

Schema version: `glb-inspection-v1`.

## Report

| Field | Meaning |
|---|---|
| `status` | `valid`, `unsupported`, or `corrupt`. Corrupt wins over unsupported. |
| `file_size_bytes` | Size of the bytes inspected. Oversized files are not read. |
| `sha256` | SHA-256 of those bytes, or `null` when the file was not read. |
| `gltf_version` | Exact `asset.version` string, or `null`. |
| `meshes` / `nodes` / `skins` / `materials` | Index plus the exact `name` string (empty if absent). Names are never guessed. |
| `animations[]` | One record per clip, addressed by `index`. |
| `buffers[]` | `uri_kind` and whether the buffer was blocked. |
| `extensions_used` / `extensions_required` | Copied from the document. Required extensions mark the file unsupported. |
| `issues[]` | `code`, `severity`, `message`, optional JSON-style `path`. |

Each animation clip keeps:

- `index` and the exact `name` (empty string when missing; never synthesized)
- `channel_count`, `sampler_count`
- unique `interpolations`, `target_paths`, and `target_node_indices`
- a bounded `channels` sample (not a second identity)
- `duration_seconds` and `duration_status`
- `name_collision` when another clip shares the same exact name (including two empty names)

Duration is the maximum finite sampled input time across channels of that clip.
It is read from accessor bytes, not from `min`/`max`. Those fields, when
present, are compared and a mismatch is recorded; they do not replace samples.
`duration_status` is:

- `verified` — finite FLOAT SCALAR samples were read
- `unknown` — samples could not be read (blocked URI, sparse accessor, limits)
- `invalid` — samples exist but are unusable (wrong type, empty, all NaN/Inf)

A missing duration is `null`. It is never reported as `0.0` to mean “unknown”.
Clip-level `verified` requires every channel of that clip to verify; a blocked,
sparse, over-limit, or invalid channel makes the clip `unknown` or `invalid`
and clears `duration_seconds`.

NaN, Infinity, and non-FLOAT component types are not converted into seconds.

## Names and semantics

Clip identity for any future selector is `(index, exact name)`. Duplicate or
empty names stay distinct by index. The inspector does not map names onto
idle/run/walk/dance/rig enums, does not invent aliases, and does not infer an
action from channel count, duration, or skeleton layout. A clip named
`Hip_Hop_Dance_1` is reported with that string; that is not visual validation
that the clip is a dance.

## Foot landings written by the humanoid rig

Animations that the humanoid rig writes carry `extras.hocuspocus_contacts`: `[{t, foot: "left"|"right", strength}]`,
sorted by time, with `t` in clip seconds. The key is absent when the clip has no landing.

three.js `GLTFLoader` copies animation extras to `clip.userData`, and Video 3D reads them in `catalogFromClips` into
`Scene3DClipCatalogEntry.contacts`.

`footContactsInScene(contacts, clipDuration, sceneDuration, clipPlayback)` (`ui/src/features/scene3d/performance.ts`)
turns the landings into scene times with the clock of `performanceClipTime`:

- the clip plays from `start` at `speed`;
- it wraps when it loops;
- when it plays once, a landing counts only while the clip is playing.

A slot with the idle performance holds frame 0, so the caller skips it. The inspector above does not validate this key.

## Buffers and URIs

Only these payloads are decoded, under size limits:

- the GLB BIN chunk, only for buffer 0 when `uri` is omitted
- `data:` URIs with `;base64`, clipped to `byteLength`

Every other URI is reported and blocked. The inspector must not:

- open relative files next to the GLB
- follow `file://`
- fetch `http://` or `https://`
- decode `%2e%2e` / traversal sequences into paths
- run a URL parser for the purpose of loading a resource

Images with external URIs are likewise blocked. They are compatibility issues,
not an invitation to download textures.

## Limits

`GlbInspectorLimits` caps file bytes, JSON bytes, chunk count, JSON items,
accessors, animations, channels, time samples, accessor work, and data URIs.
Crossing a cap yields `unsupported` (or `corrupt` when the container itself is
truncated or misaligned). Limits are part of the contract; they are not hints.

## Unmounted HTTP factory (G2)

`create_procedural_3d_assets_router(resolve_glb_asset=...)` in
`app/routers/procedural_3d_assets.py` is **not** mounted on the application.
A factory plus tests is not a usable feature.

```http
GET /api/v1/procedural-3d/assets/{asset_id}/inspection?workspace={workspace_id}
```

- Client identity is `asset_id` + `workspace_id` only. Paths, URLs and
  filenames are rejected as invalid requests (400).
- The injected callback is called as
  `resolve_glb_asset(workspace_id=..., asset_id=...)` and returns a `Path` or
  `None`. This module does not call `find_asset`, does not list workspaces,
  and does not read `uploads`.
- The JSON body is the G1 report. It must not include absolute paths,
  filenames, or catalog records.
- Missing/unknown assets and resolver failures are generic 404s. Exception
  text from disk or the callback must not reach the client.
- A `Path` from the callback is not by itself a safe open: the future adapter
  must confirm the workspace exists before creating directories, search only
  that root, require a regular `.glb` contained in it, and refuse symlinks.
  There is a TOCTOU race between resolve and `inspect_glb`; closing it belongs
  to the adapter, not this factory.

## Out of scope

- Mounting this router in `_launch_runtime.py`
- model-viewer / compositor playback
- GPU, AI generation, and private GLB redistribution
- Treating this report as proof that a clip will play correctly
