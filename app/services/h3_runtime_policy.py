"""H3 catalog and request policy, independent of launch and WanGP imports.

Presets and runtime recipes adapted from Maestro a5dddd4 (see model UPSTREAM.md).
"""
from __future__ import annotations

def turbo_option(model_def: dict) -> dict | None:
    """Return the managed Turbo preset exposed by a compatible H3 model."""

    model_def = model_def or {}
    architecture = str(model_def.get("architecture") or "")
    if (
        not architecture.startswith("minimax_h3")
        or model_def.get("minimax_h3_fused_turbo", False)
    ):
        return None

    from models.minimax_h3.turbo import (
        MINIMAX_H3_TURBO_MANIFEST,
        minimax_h3_turbo_preset,
        minimax_h3_turbo_presets_for_workflow,
    )

    workflow = "ref2va" if model_def.get("omni_reference") else "fl2va"
    full_checkpoint = bool(
        model_def.get("minimax_h3_full_checkpoint", False)
    )
    compatible_presets = minimax_h3_turbo_presets_for_workflow(
        workflow,
        full_checkpoint=full_checkpoint,
    )
    default_preset = minimax_h3_turbo_preset(
        workflow=workflow,
        full_checkpoint=full_checkpoint,
    )
    presets = [
        {
            "id": str(preset["id"]),
            "label": str(preset["label"]),
            "status": str(preset["status"]),
            "filename": str(preset["filename"]),
            "steps": int(preset["steps"]),
            "weight": float(preset["weight"]),
            "weight_min": float(preset.get("weight_min", 0.0)),
            "weight_max": float(preset.get("weight_max", 2.0)),
            "description": str(preset.get("description") or ""),
            "revision": str(preset["revision"]),
            "workflow": str(preset.get("workflow") or "all"),
            "runtime": str(preset.get("runtime") or "standard_lora"),
            "full_checkpoint_only": bool(preset.get("full_checkpoint_only", False)),
        }
        for preset in compatible_presets
    ]
    upstream = MINIMAX_H3_TURBO_MANIFEST.get("upstream_watch") or {}
    return {
        "filename": str(default_preset["filename"]),
        "label": "Turbo mode",
        "experimental": True,
        "preset_id": str(default_preset["id"]),
        "version_label": str(default_preset["label"]),
        "steps": int(default_preset["steps"]),
        "weight": float(default_preset["weight"]),
        "presets": presets,
        "upstream_url": str(upstream.get("model_card_url") or ""),
        "guide": (
            "Experimental MiniMax H3 accelerators filtered for this "
            f"{workflow.upper()} checkpoint. Standard LoRAs use Maestro's "
            "normal low-step schedule; Alibaba PAI Acc presets use their "
            "required Parallel Decoding Distillation heads and eight-step "
            "schedule. Alibaba's official Ref2VA PDD recipe recommends "
            "high-detail references, while Maestro also honors the faster "
            "Match output setting. Mutable Hugging Face main is never loaded silently."
        ),
    }

def managed_turbo_downloads() -> dict:
    from models.minimax_h3.turbo import MINIMAX_H3_TURBO_PRESETS, MINIMAX_H3_TURBO_MANIFEST
    return {
        item["filename"]: {
            **{key: item[key] for key in ("revision", "remote_path", "sha256", "size")},
            "repo_id": item.get("repo_id", MINIMAX_H3_TURBO_MANIFEST["repo_id"]),
            "label": item["label"],
            "support_url": item.get("model_card_url", "https://huggingface.co/" + MINIMAX_H3_TURBO_MANIFEST["repo_id"]),
        }
        for item in MINIMAX_H3_TURBO_PRESETS
    }


def normalize_studio_h3_policy(body: dict, model_def: dict | None = None) -> dict:
    """Effective Studio H3 policy on the generation request.

    Invalid planning/audio enums fall back. Semantic Bridge stays off unless a
    supported model supplies alpha in (0, 1]. Spoken prompt text is not rewritten.
    """
    model = str(
        body.get("model_type")
        or (model_def or {}).get("architecture")
        or ""
    )
    if not model.startswith("minimax_h3"):
        return body
    style = str(body.get("minimax_h3_planning_style") or "faithful").strip().lower()
    body["minimax_h3_planning_style"] = style if style in {"faithful", "creative"} else "faithful"
    policy = str(body.get("minimax_h3_audio_policy") or "native").strip().lower()
    body["minimax_h3_audio_policy"] = policy if policy in {"native", "legacy"} else "native"
    supported = model in {"minimax_h3", "minimax_h3_full"}
    try:
        alpha = float(body.get("minimax_h3_semantic_bridge_alpha") or 0)
    except (TypeError, ValueError):
        alpha = 0.0
    if not supported or alpha < 0 or alpha > 1:
        alpha = 0.0
    body["minimax_h3_semantic_bridge_alpha"] = alpha
    magnitude = body.get("minimax_h3_semantic_bridge_magnitude")
    if magnitude not in {"global", "none", "per_token"}:
        body["minimax_h3_semantic_bridge_magnitude"] = "per_token"
    return body


def normalize_h3_runtime_request(body: dict, model_def: dict) -> bool:
    normalize_studio_h3_policy(body, model_def)
    from models.minimax_h3.turbo import normalize_minimax_h3_turbo_request
    if model_def.get("minimax_h3_fused_turbo"):
        from models.minimax_h3.fused_turbo import normalize_fused_h3_request
        normalize_fused_h3_request(body)
        return False
    return normalize_minimax_h3_turbo_request(
        body,
        full_checkpoint=bool(model_def.get("minimax_h3_full_checkpoint")),
        workflow="ref2va" if model_def.get("omni_reference") else "fl2va",
    )


def lora_compatible(model_def: dict, path: str) -> bool:
    if model_def.get("minimax_h3_fused_turbo"):
        return False
    if not str(model_def.get("architecture", "")).startswith("minimax_h3"):
        return True
    from models.minimax_h3.turbo import minimax_h3_turbo_preset_for_path
    preset = minimax_h3_turbo_preset_for_path(path)
    return not preset or preset.get("workflow", "all") in {
        "all", "ref2va" if model_def.get("omni_reference") else "fl2va",
    }


def reference_context(references: list) -> str:
    """Build an ordered role map without a browser/enhancement prerequisite."""
    counts = {"image": 0, "video": 0, "audio": 0}
    labels = {"image": "Picture", "video": "Video", "audio": "Audio"}
    lines = []
    def audio(role, intent):
        counts["audio"] += 1
        meaning = {
            "drive": "AUDIO REUSE / PERFORMANCE DRIVER; retention=fully_copy; preserve source performance",
            "style": "AUDIO REFERENCE; retention=weak_reference; borrow rhythm/style without copying words",
            "voice": "VOICE REFERENCE; retention=reference; use timbre for new dialogue without copying source words or acoustics",
        }.get(intent, "VOICE REFERENCE; retention=reference")
        lines.append(f'<Audio {counts["audio"]}>: {role}; intent={meaning}')
    for ref in references or []:
        kind = ref.get("type")
        if kind not in counts:
            continue
        role = str(ref.get("role") or ref.get("filename") or "reference")
        if kind == "audio":
            audio(role, ref.get("audio_intent", "voice"))
            continue
        counts[kind] += 1
        label = f'<{labels[kind]} {counts[kind]}>'
        lines.append(f"{label}: {role}; visual identity/appearance only" if kind == "image" else f"{label}: {role}; motion/camera/scene reference")
        if kind == "video" and (ref.get("has_audio") or ref.get("audio_path")) and ref.get("include_audio") is not False:
            audio(f"soundtrack paired with {label}", "drive")
    return "\n".join(lines + [f"Reference manifest version: {_reference_version(references)}"])


def _reference_version(references):
    import hashlib, json
    from pathlib import Path
    identities = []
    for ref in references or []:
        item = dict(ref)
        for key in ("path", "audio_path"):
            try:
                stat = Path(ref[key]).stat()
                item[key + "_version"] = [stat.st_size, stat.st_mtime_ns]
            except (KeyError, OSError):
                pass
        identities.append(item)
    digest = hashlib.sha256(json.dumps(identities, sort_keys=True).encode()).hexdigest()[:24]
    return digest


def release_special_loras(model) -> None:
    """Restore PDD heads before model reuse, including interrupted generations."""
    release = getattr(model, "release_special_loras", None)
    if release is not None:
        release()


def resolve_model_attention(attention: str, model_def: dict, supported) -> str:
    if attention in {"sol", "sla"} and (
        not model_def.get(f"{attention}_attention", False) or attention not in supported
    ):
        print(f"[H3] {attention} unavailable for this model/runtime; using dense attention.")
        return "sdpa"
    return attention


def normalize_optional_conditioning(body: dict, model_def: dict) -> None:
    from models.minimax_h3.semantic_bridge import normalize_request
    normalize_request(body, model_def)


def conditioning_kwargs(model_def: dict, alpha=0, magnitude="per_token") -> dict:
    if not str(model_def.get("architecture") or "").startswith("minimax_h3"):
        return {}
    return {"minimax_h3_semantic_bridge_alpha": alpha,
            "minimax_h3_semantic_bridge_magnitude": magnitude}
