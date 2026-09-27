# macOS compatibility contract

Status: Apple Silicon core/remote implemented on `development-mac-integration`.
Physical Mac install/start/export QA is still required before merging to
`development`.
Apple Silicon core/remote is the first supported Mac profile. Intel Mac is
explicitly out of the first launch. This document is the live contract, not
the full engineering estimate.

## Authority

`GET /api/v1/system/capabilities` is the platform authority. The UI and MCP
must not infer support from GPU names. Mutating endpoints that need a local
NVIDIA engine call `require_capability_http` and return `409` with
`detail.code = feature_unavailable`.

Each capability has `state` (`available`, `disabled`, `hidden`),
`reason_code`, optional `provider` and optional `alternative`.

- **hidden**: never offered when creating work on this machine.
- **disabled**: kept when opening a project/recipe that already used it;
  configuration is preserved; the user can switch to the `alternative`.
- Opening a Linux/NVIDIA project on Mac must not delete options or data.

## Profiles

| Profile | Machine | Local NVIDIA engines |
|---|---|---|
| `linux-nvidia-local` / `windows-nvidia-local` | Current default | available |
| `macos-arm64-core-remote` | Darwin arm64 | hidden |
| `macos-intel-unsupported` | Darwin x86_64 | hidden |
| `core-remote` | Forced non-NVIDIA | hidden |

Core surfaces that stay available on Apple Silicon: projects, editors,
Video3D, remote LLM/image/music/3D (including Meshy). FFmpeg and Rhubarb
are `available` only when the binary is present; otherwise `disabled`.

## Integration line

Work lands on `development-mac-integration`, not on `development`, until the
Apple Silicon profile can install and start. PRs into that line should be
large working slices, not a contract-only drip.

## Core/remote profile

`select_profiles("darwin", "arm64", …)` is supported via the `core` engine
(`app/env`, FastAPI/UI, no Torch). WanGP, MiniMax H3, Hunyuan3D, SAM and
UniRig stay unsupported and are skipped by `installEngines`. `launch.py`
starts `core_runtime` instead of `_launch_runtime` so the server does not
import CUDA. `POST /api/v1/generate`, recast, upscale, Hunyuan3D, UniRig, Director pipeline
start and local audio analysis return `409 feature_unavailable`, including MCP
`generate`. Local llama.cpp load is blocked; remote MiniMax/OpenAI/Grok/Anthropic
loads, generate and song-writer stay available. Meshy/Hi3D `POST /api/v1/model3d/generate`
and MiniMax Music `POST /api/v1/stories/music-candidates/jobs` run without CUDA.
Wizard conversations/workflows, Story library, Character Kits and Series CRUD
persist as workspace JSON. The production profile defaults to MiniMax text/image/music
and Meshy 3D. MCP `tools/list` omits local generate/recast/upscale.
The Pinokio Advanced menu hides SAM and UniRig installers on Darwin.
Settings hides CUDA/VRAM/Triton controls when `show_cuda_controls` is false.
Studio Generate stays available for MiniMax Image-01; video/audio local engines
stay hidden with an NVIDIA hint. Video Editor probe/export
and Video3D scene/recording save use FFmpeg/WebCodecs, not CUDA. Comics CRUD
and remote MiniMax image keys are available.

Linux/Windows NVIDIA recipes and receipt IDs (`linux-x64-nvidia-wangp`)
are unchanged.
