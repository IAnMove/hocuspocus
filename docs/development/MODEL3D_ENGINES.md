# TRELLIS.2 and Pixal3D adapters

These are optional **local image-to-3D engines**, not remote API aliases and
not an automatic replacement for Hunyuan3D. The existing `/api/v1/model3d`
queue, GPU lane, cancellation, watchdog, simulation and asset publication
are reused. The existing family id `hunyuan3d` remains a UI compatibility
group; each asset records the actual engine and model id.
Enable the new entries through Settings → Model Visibility (3D); existing
model visibility preferences are preserved rather than overwritten.

## Status and scope

TRELLIS.2 now has an opt-in Pinokio installer and explicit, pinned weight
management; see [TRELLIS2.md](TRELLIS2.md) for supported hardware and the API.
Pixal3D remains a manual adapter. Both retain strict input validation and
isolated subprocess execution. Contract tests do not establish real GPU
quality or clean-machine installation validation.
`runtime.installed` describes the runtime, not downloaded weights or a
successful generation. TRELLIS reports compatibility and `weights_downloaded`
separately and refuses generation until both are ready. It never downloads
weights during generation. Pixal3D still downloads on first use.

| Input | TRELLIS.2 | Pixal3D |
|---|---|---|
| Image | One front image | One front image |
| Text prompt | Disabled, rejected by API | Disabled, rejected by API |
| Multi-view | Not exposed by this adapter | Not integrated: requires camera metadata and separate weights |
| Resolution | 512, 1024, 1536 | 1024, 1536 |
| Low VRAM | Not exposed | On-demand loading |
| Camera FOV | Not exposed | 0 automatic; 0.01–3.13 radians manual |
| Output | GLB, native PBR | GLB, native PBR |
| Hunyuan Paint/presets/octree | Disabled, rejected by API | Disabled, rejected by API |

Disabled view selections are retained in the UI but never included in a
single-image request. This is not a promise that hidden views are consumed.

## Isolated installation

For managed TRELLIS.2 installation, use Advanced > Install TRELLIS.2 and
follow [TRELLIS2.md](TRELLIS2.md). The following manual configuration is
retained for Pixal3D and administrator-owned upstream checkouts. TRELLIS
manual configurations must still download the pinned offline bundle through
the catalog; an administrator path never authorizes automatic weight downloads.

Do **not** install these dependencies into `app/env` or the Hunyuan environment.
Use a separate environment and upstream checkout for each engine. The default
local location `app/services/model3d_runtimes/` is gitignored; third-party
sources, environments, caches and weights must never be committed.

Reviewed upstream source revisions (2026-09-06):

- [TRELLIS.2 installation](https://github.com/microsoft/TRELLIS.2/tree/75fbf0183001ed9876c8dbb35de6b68552ee08bd):
  Linux, NVIDIA >=24 GB VRAM; CUDA Toolkit 12.4 recommended. Follow its
  `setup.sh` installation flags in an isolated Conda environment.
- [Pixal3D installation](https://github.com/TencentARC/Pixal3D/tree/f7cf38429b0bd264f1995f0f8743a88b1c728b94):
  first prepare TRELLIS.2 dependencies, then its requirements, NATTEN 0.21.0
  compiled for the actual GPU, and the linked utils3d wheel. Do not use
  `requirements-hfdemo.txt` on arbitrary consumer hardware.
- [TRELLIS.2 export example](https://github.com/microsoft/TRELLIS.2/blob/75fbf0183001ed9876c8dbb35de6b68552ee08bd/example.py)
- [Pixal3D inference entry](https://github.com/TencentARC/Pixal3D/blob/f7cf38429b0bd264f1995f0f8743a88b1c728b94/inference.py)

Configure the backend process environment before starting HocusPocus:

```bash
export HOCUSPOCUS_TRELLIS2_ROOT=/absolute/path/to/TRELLIS.2
export HOCUSPOCUS_TRELLIS2_PYTHON=/absolute/path/to/trellis-environment/bin/python
export HOCUSPOCUS_PIXAL3D_ROOT=/absolute/path/to/Pixal3D
export HOCUSPOCUS_PIXAL3D_PYTHON=/absolute/path/to/pixal-environment/bin/python
```

Paths are administrator configuration, never request fields. Restart the
backend after changing its environment. The UI displays the installation
hint until an engine is configured. Configure only engines you intend to use.
Availability does not imply sufficient free VRAM. This adapter currently
declares Linux only; Windows/AMD/community ports require separate validation.

## API example

Use an image previously uploaded into the selected workspace:

```json
{
  "provider": "local",
  "model_id": "pixal3d",
  "workspace": "default",
  "images": {"front": "reference.png"},
  "seed": 1234,
  "resolution": 1024,
  "low_vram": true,
  "camera_fov": 0,
  "texture_mode": "native-pbr",
  "output_format": "glb"
}
```

POST to `/api/v1/model3d/generate`; poll the returned `job_id` using
`/api/v1/model3d/status/{job_id}`. Cancel using
`POST /api/v1/model3d/jobs/{job_id}/cancel`. TRELLIS.2 uses `model_id=trellis2`,
`low_vram=false`, `camera_fov=0`. Omit Hunyuan-specific parameters entirely.

## Validation and release acceptance

CI: Python contracts and fake adapter tests, UI switching/payload tests,
lint, types, existing cancellation/provenance tests and simulated E2E.
No model download or GPU allocation in these tests.

Local, before declaring real support release-validated:

- Install each pinned upstream into a fresh isolated environment.
- Generate one GLB per engine from the same reference; open and rotate it,
  verify PBR materials, Library visibility and model/seed/input metadata.
- Exercise each resolution that the release claims to support; record VRAM,
  time, hardware, source revision and weight revision actually used.
- Test Pixal3D automatic/manual FOV and low-VRAM mode.
- Switch from Hunyuan multi-view to both engines; verify disabled inputs and
  that the network request contains only the front image and supported fields.
- Cancel while waiting and during inference; confirm no asset publication,
  worker exit and release of the GPU lane. Restart during inference and check
  orphan cleanup. OS hard-kill can leave system-temp preprocessing files;
  these are not published as Library assets.
- Regression: Hunyuan single/multi-view and retexture; simulated runs must be
  clearly simulated. Record failures, not just completed PRs.

Do not claim that a model's license also covers all its auxiliary weights.
Review upstream NOTICE/model cards before redistributing or commercial use.
