# Optional official TRELLIS.2 generator

TRELLIS.2 uses Microsoft's `microsoft/TRELLIS.2-4B` image-to-3D model. It
exports a GLB with native PBR materials through the existing Model3D GPU lane,
worker cancellation, watchdog, orphan recovery and workspace Library publisher.
The model id is `trellis2`; assets retain this model/provider identity. Official
refers to the upstream Microsoft weights, not completed local GPU acceptance.
Hunyuan remains the default. Selecting or enabling this entry never installs
dependencies or downloads weights.

## Requirements

- Linux x64 and NVIDIA with nominal 24 GB VRAM or more. The inventory check
  requires 24,064 MiB, allowing the small reservation reported by 24 GB cards.
  GPU identity must be verified for CUDA lane 0; memory on other GPUs is not
  summed. `CUDA_VISIBLE_DEVICES` is respected.
- Ampere, Ada or Hopper (compute capability 8.x–9.x). The managed CUDA 12.4 /
  Torch 2.6.0 / FlashAttention 2.7.3 recipe excludes Blackwell, Volta and Turing.
  Unknown GPU memory/architecture blocks this optional engine.
- NVIDIA driver >=550.54.14. The installer provisions its own CUDA Toolkit
  12.4 and GCC/G++ 12 in a separate Conda environment, leaving the main
  HocusPocus and Hunyuan environments separate.
- At least 40 GiB free before installation; download also checks the remaining
  size of all uncached weights plus 2 GiB headroom. Reserve 40–60 GiB overall.
  32–64 GB RAM is recommended, not an upstream minimum.
- Hugging Face access to [DINOv3](https://huggingface.co/facebook/dinov3-vitl16-pretrain-lvd1689m)
  and [RMBG-2.0](https://huggingface.co/briaai/RMBG-2.0). Accept each model's
  terms on its page and use **Advanced > Log in to Hugging Face**. HocusPocus
  neither accepts terms nor substitutes auxiliary weights automatically.

Windows, macOS, ARM, AMD and smaller GPUs can continue using the studio and
other available engines. TRELLIS installation is optional and hardware-gated;
it never changes the whole application's platform metadata.
These limits intentionally follow the managed recipe, not community ports.
[Upstream requirements](https://github.com/microsoft/TRELLIS.2#installation)
declare Linux, NVIDIA >=24 GB and recommend CUDA Toolkit 12.4.

## Install, download and select

1. Stop HocusPocus, then choose **Advanced > Install TRELLIS.2** in Pinokio.
   Source and CUDA extension builds can take a while (`MAX_JOBS=2`). This
   installs the runtime only; the standard Install never includes TRELLIS.
2. Restart HocusPocus. Under **Settings > Model Visibility > 3D**, enable
   **TRELLIS.2 · Official Microsoft 4B** and click its download icon.
   The icon stays disabled on incompatible hardware or before runtime setup.
   If Pinokio has cached the old recipe modules, restart Pinokio before setup.
3. Wait for download completion, then select TRELLIS in image-to-3D. Supply
   exactly one front reference image. Choose 512, 1024 or 1536 resolution;
   generation is disabled until the runtime, hardware and weights are ready.

Weights are fetched only by the explicit download request, with all gated
weight access checked before large files download. A completed receipt lists
each pinned component and its file sizes; partial/deleted/truncated bundles
remain unavailable. A local pipeline config points to these exact snapshots.
Generation runs offline and cannot fetch missing weights. Retry Download to
repair missing files. The auxiliary models load their upstream Python code
from the pinned snapshot in the isolated worker.

Update refreshes TRELLIS only when its runtime was previously installed;
it does not download weights. Reset removes the local managed runtime and its
weights via the existing `model3d_runtimes` and `ckpts/model3d` cleanup paths.
Deleting TRELLIS in Settings removes only its complete bundle/cache and does
not affect Hunyuan, Pixal3D or the installed runtime. Download/generation
activity blocks deletion.

## Supported request

One image, seed and resolution; GLB/native PBR only. Text, multi-view,
retexturing, Hunyuan Paint, octree, guidance and low-VRAM toggles are rejected
instead of being silently ignored. There is no automatic rigging/animation.
Upstream GLB alpha is preserved but defaults to OPAQUE; transparency needs
material configuration in the destination editor. Resolution acceptance is a
request contract, not a measured memory/time guarantee on every 24 GB GPU.

Upload the image to the workspace first. Replace `BASE` with the URL shown by
Pinokio and use the exact workspace name; `reference.png` is a workspace file.

```javascript
const BASE = 'http://127.0.0.1:<port>';
const response = await fetch(`${BASE}/api/v1/models/trellis2/download`, {method: 'POST'});
if (!response.ok) throw new Error(await response.text());
// Poll GET /api/v1/models/downloads/status until trellis2 is completed.
const jobResponse = await fetch(`${BASE}/api/v1/model3d/generate`, {
  method: 'POST', headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({provider: 'local', model_id: 'trellis2', workspace: 'default',
    images: {front: 'reference.png'}, seed: 1234, resolution: 512})
});
if (!jobResponse.ok) throw new Error(await jobResponse.text());
const job = await jobResponse.json();
const status = await fetch(`${BASE}/api/v1/model3d/status/${job.job_id}`).then(r => r.json());
```

```python
import requests
BASE = 'http://127.0.0.1:<port>'
r = requests.post(f'{BASE}/api/v1/models/trellis2/download')
r.raise_for_status()
# Poll GET /api/v1/models/downloads/status until trellis2 is completed.
r = requests.post(f'{BASE}/api/v1/model3d/generate', json={
    'provider': 'local', 'model_id': 'trellis2', 'workspace': 'default',
    'images': {'front': 'reference.png'}, 'seed': 1234, 'resolution': 512,
})
r.raise_for_status()
job_id = r.json()['job_id']
status = requests.get(f'{BASE}/api/v1/model3d/status/{job_id}').json()
```

```bash
curl -X POST "$BASE/api/v1/models/trellis2/download"
curl "$BASE/api/v1/models/downloads/status"
curl -X POST "$BASE/api/v1/model3d/generate" -H 'Content-Type: application/json' \
  -d '{"provider":"local","model_id":"trellis2","workspace":"default","images":{"front":"reference.png"},"seed":1234,"resolution":512}'
curl "$BASE/api/v1/model3d/status/$JOB_ID"
curl -X POST "$BASE/api/v1/model3d/jobs/$JOB_ID/cancel"
```

MCP `model3d.generate` uses the same native HTTP contract, GPU lane and
workspace publication. `/api/v1/model3d/capabilities` reports per-engine
`compatible`, `weights_downloaded` and `install_hint` alongside runtime state.

## Pins, licensing and validation

Source revision: `75fbf0183001ed9876c8dbb35de6b68552ee08bd`.
Native source revisions are recorded in `app/runtime/vendors.json`, with
recursive Git submodules. Python dependencies are resolved in
`app/runtime/locks/linux-trellis2.txt`; native builds use the same constraints.
Weights and auxiliary snapshot revisions are in `services/trellis2/assets.py`.
No vendor code, environments, weights or credentials are committed.

Microsoft's model/code are MIT. That does not cover DINOv3, RMBG-2.0, CUDA,
nvdiffrast, nvdiffrec or the other dependencies: consult their own terms.
This integration downloads them from their providers on request and does not
redistribute them or assert an unrestricted commercial license.

Validation on 2026-10-10: hardware/request contracts, complete bundle checks,
worker dispatch/seed/export with test doubles, existing GPU admission,
cancellation/provenance regressions, launcher plans and UI availability.
No real TRELLIS GLB was generated: the local Hugging Face account lacks access
to both auxiliary repositories (HEAD requests return `GatedRepoError`).
The installer smoke was started after refreshing a stale Pinokio recipe cache;
the clean installation and CUDA build are not yet claimed verified. Keep the PR
in draft until clean installation and real GLB/PBR checks from
[MODEL3D_ENGINES.md](MODEL3D_ENGINES.md#validation-and-release-acceptance) pass.
