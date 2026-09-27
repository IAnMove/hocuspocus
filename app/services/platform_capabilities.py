"""Platform capability authority for NVIDIA-local vs core/remote profiles.

The UI and MCP must not infer support from GPU names. This module never
imports Torch or CUDA libraries.
"""
from __future__ import annotations

import platform
import shutil
from typing import Any, Mapping

FEATURE_UNAVAILABLE = "feature_unavailable"

AVAILABLE = "available"
DISABLED = "disabled"
HIDDEN = "hidden"

PROFILE_LINUX_NVIDIA = "linux-nvidia-local"
PROFILE_WINDOWS_NVIDIA = "windows-nvidia-local"
PROFILE_MACOS_ARM64 = "macos-arm64-core-remote"
PROFILE_MACOS_INTEL = "macos-intel-unsupported"
PROFILE_CORE_REMOTE = "core-remote"

ALWAYS_ON = (
    "projects",
    "editors",
    "video3d",
    "remote_llm",
    "remote_image",
    "remote_music",
    "remote_3d",
)
NVIDIA_LOCAL = (
    "local_llm",
    "wangp_local",
    "minimax_h3_local",
    "hunyuan3d_local",
    "local_audio_ai",
    "sam_inpaint",
    "unirig_ai",
    "whisper_local",
)
NVIDIA_ALTERNATIVE = {
    "local_llm": "remote_llm",
    "wangp_local": "remote_image",
    "minimax_h3_local": "remote_image",
    "hunyuan3d_local": "remote_3d",
    "local_audio_ai": "remote_music",
    "sam_inpaint": "editors",
    "unirig_ai": "editors",
    "whisper_local": "editors",
}


class CapabilityDenied(Exception):
    """Raised when a mutating path asks for a capability that is not available."""

    def __init__(
        self,
        capability: str,
        state: str,
        reason_code: str,
        alternative: str | None,
    ) -> None:
        super().__init__(capability)
        self.capability = capability
        self.state = state
        self.reason_code = reason_code
        self.alternative = alternative

    def as_detail(self) -> dict[str, Any]:
        return {
            "code": FEATURE_UNAVAILABLE,
            "capability": self.capability,
            "state": self.state,
            "reason_code": self.reason_code,
            "alternative": self.alternative,
        }


def host_platform() -> str:
    return platform.system().lower()


def host_machine() -> str:
    machine = (platform.machine() or "").lower()
    if machine in {"aarch64", "arm64"}:
        return "arm64"
    if machine in {"x86_64", "amd64"}:
        return "x86_64"
    return machine or "unknown"


def resolve_profile(
    system: str,
    machine: str,
    *,
    nvidia_local: bool | None = None,
) -> str:
    if system == "darwin":
        return PROFILE_MACOS_ARM64 if machine == "arm64" else PROFILE_MACOS_INTEL
    if nvidia_local is False:
        return PROFILE_CORE_REMOTE
    if system == "windows":
        return PROFILE_WINDOWS_NVIDIA
    if system == "linux":
        return PROFILE_LINUX_NVIDIA
    return PROFILE_CORE_REMOTE


def _entry(state: str, reason_code: str, *, alternative: str | None = None, provider: str | None = None) -> dict[str, Any]:
    return {
        "state": state,
        "reason_code": reason_code,
        "provider": provider,
        "alternative": alternative,
    }


def _binary_state(present: bool) -> dict[str, Any]:
    if present:
        return _entry(AVAILABLE, "binary_present", provider="local")
    return _entry(DISABLED, "missing_binary", alternative="manual")


def _nvidia_local_entries() -> dict[str, dict[str, Any]]:
    return {
        capability: _entry(AVAILABLE, "nvidia_local", provider="local-nvidia")
        for capability in NVIDIA_LOCAL
    }


def _core_remote_entries(*, hide: bool) -> dict[str, dict[str, Any]]:
    state = HIDDEN if hide else DISABLED
    reason = "macos_core_remote" if hide else "requires_nvidia"
    return {
        capability: _entry(
            state,
            reason,
            provider="local-nvidia",
            alternative=NVIDIA_ALTERNATIVE[capability],
        )
        for capability in NVIDIA_LOCAL
    }


def build_capabilities(
    *,
    system: str,
    machine: str,
    nvidia_local: bool | None = None,
    ffmpeg_present: bool | None = None,
    rhubarb_present: bool | None = None,
) -> dict[str, Any]:
    profile = resolve_profile(system, machine, nvidia_local=nvidia_local)
    capabilities = {
        capability: _entry(AVAILABLE, "core", provider="core")
        for capability in ALWAYS_ON
    }
    if profile in {PROFILE_LINUX_NVIDIA, PROFILE_WINDOWS_NVIDIA}:
        capabilities.update(_nvidia_local_entries())
        show_cuda = True
        mode = "nvidiaLocal"
    elif profile == PROFILE_MACOS_INTEL:
        capabilities.update(_core_remote_entries(hide=True))
        show_cuda = False
        mode = "macosIntel"
    else:
        capabilities.update(_core_remote_entries(hide=True))
        show_cuda = False
        mode = "macosCoreRemote" if profile == PROFILE_MACOS_ARM64 else "coreRemote"

    ffmpeg = True if ffmpeg_present is None else ffmpeg_present
    rhubarb = False if rhubarb_present is None else rhubarb_present
    if ffmpeg_present is None:
        ffmpeg = shutil.which("ffmpeg") is not None
    if rhubarb_present is None:
        rhubarb = shutil.which("rhubarb") is not None
    capabilities["ffmpeg"] = _binary_state(ffmpeg)
    capabilities["rhubarb"] = _binary_state(rhubarb)

    return {
        "platform": system,
        "arch": machine,
        "profile": profile,
        "accelerators": {
            "cuda": profile in {PROFILE_LINUX_NVIDIA, PROFILE_WINDOWS_NVIDIA},
            "mps": profile == PROFILE_MACOS_ARM64,
            "metal": profile == PROFILE_MACOS_ARM64,
        },
        "ui": {
            "mode": mode,
            "show_cuda_controls": show_cuda,
        },
        "capabilities": capabilities,
    }


def platform_capabilities(**overrides: Any) -> dict[str, Any]:
    return build_capabilities(
        system=overrides.get("system") or host_platform(),
        machine=overrides.get("machine") or host_machine(),
        nvidia_local=overrides.get("nvidia_local"),
        ffmpeg_present=overrides.get("ffmpeg_present"),
        rhubarb_present=overrides.get("rhubarb_present"),
    )


def capability_state(capability: str, snapshot: Mapping[str, Any] | None = None) -> str:
    snap = snapshot or platform_capabilities()
    entry = snap.get("capabilities", {}).get(capability)
    if not isinstance(entry, Mapping):
        return HIDDEN
    state = entry.get("state")
    return state if state in {AVAILABLE, DISABLED, HIDDEN} else HIDDEN


def visible_capabilities(
    snapshot: Mapping[str, Any] | None = None,
    *,
    include_disabled: bool = True,
) -> list[str]:
    snap = snapshot or platform_capabilities()
    allowed = {AVAILABLE, DISABLED} if include_disabled else {AVAILABLE}
    return [
        name
        for name, entry in snap.get("capabilities", {}).items()
        if isinstance(entry, Mapping) and entry.get("state") in allowed
    ]


def require_capability(capability: str, snapshot: Mapping[str, Any] | None = None) -> None:
    snap = snapshot or platform_capabilities()
    entry = snap.get("capabilities", {}).get(capability)
    if not isinstance(entry, Mapping):
        raise CapabilityDenied(capability, HIDDEN, "unknown_capability", None)
    state = str(entry.get("state") or HIDDEN)
    if state == AVAILABLE:
        return
    raise CapabilityDenied(
        capability,
        state,
        str(entry.get("reason_code") or "requires_nvidia"),
        entry.get("alternative"),
    )



