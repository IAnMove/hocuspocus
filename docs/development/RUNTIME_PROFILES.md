# Platform recipes and isolated AI runtimes

One HocusPocus repository selects installation recipes through
[`profiles.json`](../../app/runtime/profiles.json). Install and Update execute
the same builder; updating code loads the new setup script after the Git pull.
External source repositories remain pinned in
[`vendors.json`](../../app/runtime/vendors.json), also exposed through
`vendor_revisions.js` for Pinokio. A platform override can select
different repositories, Python versions, wheels and dependencies without forking
the entire application.

## Available recipes

All current recipes require **x64 and NVIDIA**. Selection checks OS,
architecture and the NVIDIA driver; an unknown driver is explicitly unverified.
An unsupported optional engine is reported and skipped, while an unsupported
core stops installation. This is installation compatibility, not a promise that
every model fits in the available VRAM.

| Engine | Linux / Windows | Environment | Python / Torch / CUDA |
|---|---|---|---|
| HocusPocus / WanGP, including native H3 | Both | `app/env` (venv) | 3.10 / 2.7.0 Linux, 2.7.1 Windows / 12.8 |
| Hunyuan3D and procedural rigging | Both | `app/services/hunyuan3d/env` (conda) | 3.10 / 2.7.0 / 12.8 |
| H3 **Legacy**, ComfyUI | Both | `app/services/minimax_h3/env` (conda) | 3.11 / 2.10.0 / 13.0 |
| SAM, optional | Both | `app/services/sam/env` (conda) | 3.12 / 2.7.0 / 12.8 |
| UniRig, optional | Linux | `app/services/rigging/env` (conda) | 3.11 / 2.7.0 / 12.8 |

CUDA 13 requires driver 580 or newer. CUDA 12 recipes use NVIDIA's minor
compatibility floor; newer drivers are recommended, especially for JIT kernels.
Hunyuan and UniRig still need a compatible CUDA compiler; Hunyuan on Windows
needs Visual Studio Build Tools. The installer actually imports Torch and runs
a small CUDA calculation before accepting each environment. It does not execute
models as part of this check.

### Windows native toolchain

The Hunyuan recipe uses CUDA Toolkit 12.8 and x64 MSVC 14.2x/14.3x/14.4x.
`scripts/windows_toolchain.py` discovers side-by-side Visual Studio installations
with Microsoft's `vswhere`, selects a compatible toolset instead of VS 18's
MSVC 14.50+, and activates its Windows SDK environment. Missing toolsets or a
different CUDA toolkit stop Windows preflight with recovery instructions.
Install VS 2022 Build Tools with v143 or VS 2019 with v142 and a Windows SDK
if no compatible toolset exists. Existing VS installations are not removed.

Windows native package builds and the 2.1 mesh painter use that same environment.
CUDA libraries are found in either the NVIDIA `lib/x64` layout or Pinokio/conda's
`lib` layout. No machine-specific paths are committed, and Linux build commands
are unchanged. Retry Install after correcting prerequisites; Reset is unnecessary.
The pinned 2.1 rasterizer also needs explicit `int64_t` tensor dimensions on
MSVC (C2398), and `int64_t` pointers instead of Linux's 64-bit `long` (LNK2001
on Windows, where `long` is 32-bit). Its Windows wheel is built from a temporary
source copy containing those fixes. The vendor checkout remains untouched; an unexpected upstream
source layout fails instead of silently applying a partial patch.

The launcher hides optional SAM/UniRig install entries on known incompatible
OS/architecture/GPU combinations using the existing recipe catalog. Unknown
hardware inventory keeps the options visible. This menu filtering does not
change the studio's internal feature navigation or add macOS/MPS support.

## Preventing dependency contamination

- Each engine uses its own Python executable; Windows conda uses `env/python.exe`,
  whereas the main venv uses `env/Scripts/python.exe`.
- ABI constraints cover Torch, NumPy and engine-specific packages. Full resolved
  dependency lists live in `app/runtime/locks`. Package installation always
  supplies the selected interpreter, both constraint files and explicit indexes.
- Inherited Python paths, user packages and pip/uv destination/configuration
  overrides cannot redirect the package helper into a different environment.
  Worker processes also discard parent environment library paths and put the
  selected engine's `lib`/`lib64` ahead of any remaining `LD_LIBRARY_PATH`.
  Credentials, CUDA visibility and system toolchains retain their existing
  handling. Pinokio's conda base, identified by `CONDA_PYTHON_EXE`, supplies
  machine tools such as nvcc/FFmpeg and stays on `PATH` after the engine;
  its libraries remain reachable after matching libraries in the engine's
  `lib`/`lib64`. This does not override every wheel's private RUNPATH directory;
  loader failures in those packages still require a targeted runtime check.
- TorchCodec 0.5 matches the main Torch 2.7 on Linux. Windows uses the existing
  video-reader fallbacks because that TorchCodec version has no Windows wheel.
  SAM uses NumPy 1.26.4, matching its pinned upstream requirements.
- Native extensions use explicit versions and the same constraints. A full lock
  is not a security sandbox or a guarantee of bit-identical compiled binaries.

## Installation, update and recovery

Use **Install** for a fresh checkout, then **Start**. On an existing checkout,
stop its HocusPocus application before **Update**. Update refuses a dirty tree
and only accepts a fast-forward; it then uses the same installation recipes.
Optional SAM/UniRig environments are refreshed only if previously installed.
Assets, projects and output files are not migrated or deleted by this process.

Setup writes a management intent before modifying an environment. Success is
recorded only after dependency checks, imports and a real CUDA calculation.
The receipt contains the recipe fingerprint and the complete installed package
set. A later package change invalidates it. Missing source files or a different
vendor HEAD also trigger repair. Setup restores missing tracked dependency files
without overwriting existing edits or untracked files; staged custom deletions
require manual reconciliation. Once migration has started, old
installation markers cannot make an incomplete environment available to workers
or Start. Run Install/Update again to repair it; a failure is not a success.

Shell failures are made visible to Pinokio even when a command exits without an
error message. Child scripts explicitly return success; parents check this
receipt because Pinokio can otherwise continue after an aborted child.

**Reset is destructive:** it removes managed environments, vendor checkouts and
the UI build, including the existing Hunyuan model cache under `app/ckpts/model3d`.
It is not necessary for routine updates or retries.

Read `/api/v1/runtime-capabilities` on the running app for the selected recipes
and installed status. `python scripts/runtime_probe.py` provides a local report
without installing packages or downloading weights. The report is generated
under ignored `app/.runtime/`, never committed.

## Maintaining recipes and validation

To update a dependency, change its recipe/requirements, then explicitly resolve
each affected platform, for example:

```sh
python scripts/lock_runtime_dependencies.py --engine wangp --platform linux
python scripts/lock_runtime_dependencies.py --engine wangp --platform win32
```

This uses uv and Node, accesses package indexes and the pinned ComfyUI
requirements when needed, and writes lock/constraint files. It does not install
AI environments. Review the diff, run the contract tests, and validate a real
installation on the target OS before publishing. Resolution is not equivalent
to building CUDA extensions or generating media.

The automated checks exercise platform selection, malformed receipts, altered
packages, inherited dependency paths, explicit install destinations, and real
host-shell failure propagation. Windows CI runs those lightweight checks in
addition to the existing Windows media tests. The initial local checks also ran
Pinokio itself through successful preflight, successful child completion, and a
silent failed child whose parent must not publish completion.

Remaining work: full Windows/Linux installation and model smoke on the final
branch; CPU/AMD/Intel/MPS recipes; a UI for optional components; transactional
environment replacement with automatic rollback. Current Update repairs in
place and stops on failure; it does not promise rollback to the previous stack.

References: [Python venv](https://docs.python.org/3/library/venv.html),
[NVIDIA CUDA release notes](https://docs.nvidia.com/cuda/cuda-toolkit-release-notes/index.html),
[TorchCodec compatibility](https://github.com/meta-pytorch/torchcodec),
[pinned SAM requirements](https://github.com/facebookresearch/sam3/blob/8f0b7f4d4e7eda2ed606ebde6702c93359ad01da/pyproject.toml).
## Windows startup verification

The Windows WanGP recipe uses xFormers 0.0.31.post1, which fixes the native
extension packaging in 0.0.31. It removes the external Flash Attention package:
2.8.2 conflicts with xFormers and the evaluated 2.7.4 Windows wheels lack RTX
3070 kernels. xFormers, PyTorch SDPA and SageAttention remain available.
Installation checks the Diffusers transformer import used by Quanto and runs
a small xFormers CUDA attention calculation before writing a success receipt.
Package metadata alone does not catch import or GPU-kernel failures. Linux
attention pins are unchanged.
