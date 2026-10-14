"""Settings HTTP surface moved out of the full server.

The routes are not contiguous, so each factory is mounted where its first
route used to be. Bodies are unchanged. The core server keeps its own
torch-free copies.
"""
from __future__ import annotations

import os
import time
import uuid

from fastapi import APIRouter, HTTPException, Request

from services import debug_trace, execution_mode
from services import settings_store
from services.settings_store import (
    _DEFAULT_LLM_REPO,
    _PUBLIC_LLM_PROVIDERS,
    _apply_linked_model_folders,
    _get_linked_model_folders,
    _llm_default_device,
    _load_presets,
    _mask_key,
    _save_presets,
    _validated_memory_profile_updates,
)


def create_primary_settings_router(*, wgp):
    """The base parameter defaults."""
    router = APIRouter()

    @router.get("/api/v1/primary-settings")
    def get_primary_settings():
        """Get the base primary_settings (all parameter defaults)."""
        return wgp.primary_settings

    return router


def create_settings_config_router(*, wgp, _save_server_config, launch_file, APP_VERSION):
    """Presets, system config and the linked-folder scan."""
    settings_store.wgp = wgp
    # scan_model_folders reads __file__ to find sibling installs. Bind the
    # launch module's path so that walk stays the one it did before.
    __file__ = launch_file
    router = APIRouter()

    @router.get("/api/v1/presets")
    def list_presets():
        """List all saved generation presets."""
        return {"presets": _load_presets()}
    @router.post("/api/v1/presets")
    async def create_preset(request: Request):
        """Save a new generation preset."""
        body = await request.json()
        name = body.get("name", "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="name is required")

        preset = {
            "id": uuid.uuid4().hex[:8],
            "name": name,
            "mode": body.get("mode", "video"),
            "model_type": body.get("model_type", ""),
            "prompt": body.get("prompt", ""),
            "activated_loras": body.get("activated_loras", []),
            "loras_multipliers": body.get("loras_multipliers", ""),
            "lora_weights": body.get("lora_weights", {}),
            "params": body.get("params", {}),
            "created_at": time.time(),
        }

        presets = _load_presets()
        presets.append(preset)
        _save_presets(presets)
        return preset
    @router.delete("/api/v1/presets/{preset_id}")
    def delete_preset(preset_id: str):
        """Delete a preset by ID."""
        presets = _load_presets()
        new_presets = [p for p in presets if p.get("id") != preset_id]
        if len(new_presets) == len(presets):
            raise HTTPException(status_code=404, detail="Preset not found")
        _save_presets(new_presets)
        return {"deleted": preset_id}
    @router.get("/api/v1/system-config")
    def get_system_config():
        """Return system-level settings for the UI System tab."""
        cfg = wgp.server_config
        return {
            "app_version": APP_VERSION,
            "attention_mode": cfg.get("attention_mode", "auto"),
            "transformer_quantization": cfg.get("transformer_quantization", "int8"),
            "vae_config": cfg.get("vae_config", 0),
            "compile": cfg.get("compile", ""),
            "video_profile": cfg.get("video_profile", 2),
            "image_profile": cfg.get("image_profile", 2),
            "audio_profile": cfg.get("audio_profile", 3.5),
            "video_output_codec": cfg.get("video_output_codec", "libx264_8"),
            "image_output_codec": cfg.get("image_output_codec", "jpeg_95"),
            "enhancer_enabled": cfg.get("enhancer_enabled", 0),
            "prompt_enhancer_quantization": cfg.get("prompt_enhancer_quantization", "quanto_int8"),
            "attention_modes_available": list(wgp.attention_modes_supported),
            # Read from server_config (persisted) rather than wgp.args, which
            # only reflects the CLI default until wgp.py applies the saved
            # value on startup. Either source returns the right value after
            # the wgp.py override runs, but reading from server_config is
            # consistent with all the other fields above and avoids depending
            # on startup ordering.
            "vram_safety_coefficient": cfg.get("vram_safety_coefficient", wgp.args.vram_safety_coefficient),
            # Linked model folders: the external (absolute, outside-the-app)
            # entries of checkpoints_paths. The app-owned entries ("ckpts", ".")
            # are managed automatically and never shown to the user.
            "model_folders": _get_linked_model_folders(),
            # Boot-only acceptance policy. The UI may display this state but can
            # never mutate it, so the Wizard cannot turn fake execution on.
            "execution_mode": execution_mode.policy().mode,
            "execution_workspace": execution_mode.policy().workspace,
            "execution_allow_paid": execution_mode.policy().allow_paid,
            "execution_simulation_step_delay": execution_mode.policy().step_delay,
        }
    @router.put("/api/v1/system-config")
    async def update_system_config(request: Request):
        """Update system-level settings. Accepts partial JSON body."""
        body = await request.json()
        profile_updates = _validated_memory_profile_updates(body)

        ALLOWED_KEYS = {
            "attention_mode", "transformer_quantization", "vae_config",
            "compile", "video_profile", "image_profile", "audio_profile",
            "video_output_codec", "image_output_codec",
            "enhancer_enabled", "prompt_enhancer_quantization",
            "vram_safety_coefficient",
        }

        updated = {}
        # Linked model folders map onto checkpoints_paths (validated + applied
        # live); the raw key is deliberately NOT in ALLOWED_KEYS so clients
        # can't bypass the validation and write-pinning invariants. Processed
        # FIRST because its validation raises 400 before mutating anything —
        # a mixed body must not leave other keys half-applied.
        if "model_folders" in body:
            updated["model_folders"] = _apply_linked_model_folders(body["model_folders"])

        for key, value in body.items():
            if key in ALLOWED_KEYS:
                wgp.server_config[key] = value
                updated[key] = value

        if not updated:
            raise HTTPException(status_code=400, detail="No valid fields to update")

        # Persist to disk
        _save_server_config()

        # Apply runtime side effects where possible
        if "attention_mode" in updated:
            wgp.attention_mode = updated["attention_mode"]
        if "vae_config" in updated:
            wgp.vae_config = updated["vae_config"]
        if "compile" in updated:
            wgp.compile = updated["compile"]
        if "vram_safety_coefficient" in updated:
            wgp.args.vram_safety_coefficient = float(updated["vram_safety_coefficient"])
        # WanGP selects these defaults when the next model is loaded. Updating
        # server_config alone leaves its startup snapshots active indefinitely.
        # The resident model's loaded_profile and offload object remain untouched.
        for key, value in profile_updates.items():
            setattr(wgp, f"default_profile_{key.removesuffix('_profile')}", value)
        if "video_profile" in profile_updates:
            wgp.default_profile = profile_updates["video_profile"]

        return {"status": "ok", "updated": updated}
    @router.get("/api/v1/model-folders/scan")
    def scan_model_folders():
        """Discover sibling Pinokio apps with a Wan2GP-style ckpts folder.

        Maestro lives at <pinokio>/api/<name>/app, so sibling installs (e.g. an
        existing Wan2GP) are <pinokio>/api/*/app/ckpts. Returns lightweight
        candidates for the Settings -> Linked Model Folders UI; size stats are
        top-level-files-only so scanning stays instant on multi-hundred-GB
        folders.
        """
        from shared.utils.files_locator import is_external_root
        app_dir = os.path.dirname(os.path.abspath(__file__))
        own_ckpts = os.path.normpath(os.path.join(app_dir, "ckpts"))
        api_root = os.path.dirname(os.path.dirname(app_dir))
        linked = {os.path.normcase(os.path.normpath(p)) for p in _get_linked_model_folders()}

        candidates = []
        try:
            entries = list(os.scandir(api_root))
        except OSError:
            entries = []
        for entry in entries:
            if not entry.is_dir():
                continue
            ckpts = os.path.normpath(os.path.join(entry.path, "app", "ckpts"))
            if ckpts == own_ckpts or not os.path.isdir(ckpts):
                continue
            if not is_external_root(ckpts):
                continue
            file_count = 0
            dir_count = 0
            size_bytes = 0
            try:
                for f in os.scandir(ckpts):
                    if f.is_file():
                        file_count += 1
                        try:
                            size_bytes += f.stat().st_size
                        except OSError:
                            pass
                    elif f.is_dir():
                        dir_count += 1
            except OSError:
                continue
            if file_count == 0 and dir_count == 0:
                continue
            candidates.append({
                "app": entry.name,
                "path": ckpts,
                "files": file_count,
                "folders": dir_count,
                "size_gb": round(size_bytes / 1e9, 1),
                "linked": os.path.normcase(ckpts) in linked,
            })
        candidates.sort(key=lambda c: c["size_gb"], reverse=True)
        return {"candidates": candidates}

    return router


def create_settings_services_router(
    *,
    wgp,
    _save_server_config,
    _effective_llm_routing,
    _active_production_profile,
    _normalize_production_profile,
    _PRODUCTION_PROFILE_CONFIG_KEY,
):
    """Services config, API keys masked on the way out."""
    settings_store.wgp = wgp
    router = APIRouter()

    @router.get("/api/v1/services-config")
    def get_services_config():
        """Return services settings with API keys masked."""
        services = wgp.server_config.get("services", {})
        provider, profile_model, profile_remote_url = _effective_llm_routing(services)
        # Enforce: NSFW must be off when using a public provider
        nsfw = services.get("nsfw_mode", False) and provider not in _PUBLIC_LLM_PROVIDERS
        return {
            "llm_model_id": profile_model or services.get("llm_model_id", _DEFAULT_LLM_REPO),
            "llm_device": services.get("llm_device", _llm_default_device()),
            "llm_provider": provider,
            "llm_remote_url": profile_remote_url,
            "enhance_llm_model_id": services.get("enhance_llm_model_id", ""),
            "enhance_llm_device": services.get("enhance_llm_device", "cuda"),
            "google_api_key": _mask_key(services.get("google_api_key", "")),
            "google_api_key_set": bool(services.get("google_api_key", "")),
            "openai_api_key": _mask_key(services.get("openai_api_key", "")),
            "openai_api_key_set": bool(services.get("openai_api_key", "")),
            "deepseek_api_key": _mask_key(services.get("deepseek_api_key", "")),
            "deepseek_api_key_set": bool(services.get("deepseek_api_key", "")),
            "compatible_api_key": _mask_key(services.get("compatible_api_key", "")),
            "compatible_api_key_set": bool(services.get("compatible_api_key", "")),
            "compatible_base_url": services.get("compatible_base_url", ""),
            "anthropic_api_key": _mask_key(services.get("anthropic_api_key", "")),
            "anthropic_api_key_set": bool(services.get("anthropic_api_key", "")),
            "minimax_api_key": _mask_key(services.get("minimax_api_key", "")),
            "minimax_api_key_set": bool(services.get("minimax_api_key", "")),
            "minimax_llm_api_key": _mask_key(services.get("minimax_llm_api_key", "")),
            "minimax_llm_api_key_set": bool(services.get("minimax_llm_api_key") or services.get("minimax_api_key")),
            "minimax_image_api_key": _mask_key(services.get("minimax_image_api_key", "")),
            "minimax_image_api_key_set": bool(services.get("minimax_image_api_key") or services.get("minimax_api_key")),
            "minimax_music_api_key": _mask_key(services.get("minimax_music_api_key", "")),
            "minimax_music_api_key_set": bool(services.get("minimax_music_api_key") or services.get("minimax_api_key")),
            "grok_api_key": _mask_key(services.get("grok_api_key", "")),
            "grok_api_key_set": bool(services.get("grok_api_key", "")),
            "meshy_api_key": _mask_key(services.get("meshy_api_key", "")),
            "meshy_api_key_set": bool(services.get("meshy_api_key", "")),
            "hi3d_api_key": _mask_key(services.get("hi3d_api_key", "")),
            "hi3d_api_key_set": bool(services.get("hi3d_api_key", "")),
            # Director v2 (layered architecture: structured shot planning,
            # mode-specific renderers, prompt validation) is now the default
            # as of 2026-05-03 after weeks of real-world validation. v1 had
            # a known polish-pass failure mode where smaller LLMs (Gemma 4
            # 4B) would hallucinate dialogue into image_prompts. v2 doesn't
            # exhibit that. Existing users who explicitly set use_director_v2
            # to false (legacy v1) keep that choice; only fresh installs and
            # users who never touched the toggle see the new default.
            "use_director_v2": services.get("use_director_v2", True),
            "nsfw_mode": nsfw,
            "nsfw_accepted_at": services.get("nsfw_accepted_at", None),
            # Off by default: Director prompts reach the models as the planner
            # wrote them. The model-aware third pass is opt-in; native H3 video
            # prompts bypass its creative rewriting.
            "director_prompt_polish": services.get("director_prompt_polish", "off"),
            # Raw prompts: the Director adds no style prefix, locks or polish.
            "raw_prompts": services.get("raw_prompts") is True, "director_reference_anchor": services.get("director_reference_anchor", "always"), "director_lighting_continuity": services.get("director_lighting_continuity", "auto"), "director_keep_reference_wardrobe": services.get("director_keep_reference_wardrobe") is not False,
            # Safe workflow overlap: every local GPU and remote server keeps
            # capacity one; only genuinely different resources run together.
            "workflow_parallelism_enabled": services.get("workflow_parallelism_enabled", True),
            # Structured JSONL tracing of LLM calls and user actions.
            "debug_trace_enabled": services.get("debug_trace_enabled", False),
            "debug_trace_log_path": debug_trace.current_log_path(),
            "civitai_api_key": _mask_key(services.get("civitai_api_key", "")),
            "civitai_api_key_set": bool(services.get("civitai_api_key", "")),
            # Voice Reference is a stable, user-facing capability now. Fresh
            # installs expose its controls by default, while an explicitly saved
            # False value remains respected.
            "voice_reference_enabled": services.get("voice_reference_enabled", True),
            "ltx_progressive_pipeline": services.get("ltx_progressive_pipeline", False),
            # Master gate for experimental features. When False (default for
            # fresh installs and a sane "ship-ready" baseline), the Services
            # panel hides external API keys and the Studio prompt enhancer
            # config; the Edit mode picker hides Inpaint. Voice Reference is
            # intentionally independent of this gate.
            "show_experimental": services.get("show_experimental", False),
            # Storage Manager: opt-in gate for removing duplicate files FROM
            # linked installs (the inverse of Reclaim). Default off — deleting
            # from another install is informed-consent territory.
            "storage_allow_linked_removal": services.get("storage_allow_linked_removal", False),
            # Performance auto-tune master switch. When True (default), the
            # Settings → System Performance section collapses to a single
            # "Detected: <hardware> → <profile>" card with all underlying
            # knobs hidden under "Show advanced settings". The auto-tune
            # values are applied at first launch (see wgp._init_default_config)
            # and reapplied if the user clicks "Re-detect". When False, the
            # user has manually configured something — we stop overwriting
            # their choices and show the full advanced UI by default.
            "auto_performance": services.get("auto_performance", True),
            # Multi-shot LoRA mode (Maque IC-LoRA and similar). When True,
            # Pass 2 emits storyboard-format video_prompts for medium-length
            # shots (20-30s), letting the LoRA cut between camera angles
            # inside a single generation. Short reaction shots (≤15s) and
            # long sustained shots (40s+ continuous action — sex acts,
            # climactic confrontations) keep the regular single-camera
            # video_prompt format because internal cuts would break either
            # the punchy timing or the sustained-take feel.
            #
            # Off by default — power-user feature for now. User must have
            # the matching IC-LoRA enabled in their video_loras selection
            # for the storyboard format to actually produce internal cuts;
            # without the LoRA, the storyboard text still renders but as
            # a single-take with no cuts. Future direction: a LoRA
            # capabilities catalog (see docs/project_lora_catalog.md) that
            # auto-enables this mode when a multi-shot-capable LoRA is in
            # the active set.
            "director_multishot_lora_mode": services.get("director_multishot_lora_mode", False),
            # FlashVSR (DiT super-resolution) spatial-upsampling settings.
            # variant: 1=tiny (fast/low-VRAM), 2=full (best quality, uses full VAE),
            # 3=tiny-long (tiny for long videos). topk_ratio 0..4 controls sparse-
            # attention density (higher = more motion fidelity, slower). backend:
            # auto / triton_sparse (bundled) / sparge (optional install, best motion).
            "flashvsr_mode": services.get("flashvsr_mode", 1),
            "flashvsr_topk_ratio": services.get("flashvsr_topk_ratio", 0.0),
            "flashvsr_backend": services.get("flashvsr_backend", "auto"),
        }
    @router.put("/api/v1/services-config")
    async def update_services_config(request: Request):
        """Update services configuration. API keys are stored in full, returned masked."""
        body = await request.json()

        ALLOWED_KEYS = {
            "llm_model_id", "llm_device", "llm_provider", "llm_remote_url",
            "enhance_llm_model_id", "enhance_llm_device",
            "google_api_key", "openai_api_key", "deepseek_api_key", "compatible_api_key",
            "compatible_base_url", "anthropic_api_key", "minimax_api_key",
            "minimax_llm_api_key", "minimax_image_api_key", "minimax_music_api_key",
            "grok_api_key", "meshy_api_key", "hi3d_api_key",
            "use_director_v2", "nsfw_mode", "nsfw_accepted_at", "director_prompt_polish",
            "raw_prompts", "debug_trace_enabled", "workflow_parallelism_enabled",
            "civitai_api_key", "voice_reference_enabled", "ltx_progressive_pipeline",
            "show_experimental", "auto_performance", "storage_allow_linked_removal",
            "director_multishot_lora_mode", "director_reference_anchor", "director_lighting_continuity", "director_keep_reference_wardrobe",
            "flashvsr_mode", "flashvsr_topk_ratio", "flashvsr_backend",
        }

        services = wgp.server_config.setdefault("services", {})
        updated = {}

        for key, value in body.items():
            if key not in ALLOWED_KEYS:
                continue
            # Don't overwrite a real key with its masked version
            if key.endswith("_api_key") and value and "..." in value:
                continue
            services[key] = value
            updated[key] = _mask_key(value) if key.endswith("_api_key") else value
            if key.endswith("_api_key"):
                updated[f"{key}_set"] = bool(value)

        # Enforce: cannot enable NSFW with a public LLM provider
        provider = _effective_llm_routing(services)[0]
        if services.get("nsfw_mode") and provider in _PUBLIC_LLM_PROVIDERS:
            services["nsfw_mode"] = False
            updated["nsfw_mode"] = False

        # When switching TO a public provider, auto-disable NSFW
        if "llm_provider" in body and body["llm_provider"] in _PUBLIC_LLM_PROVIDERS:
            if services.get("nsfw_mode"):
                services["nsfw_mode"] = False
                updated["nsfw_mode"] = False

        if not updated:
            raise HTTPException(status_code=400, detail="No valid fields to update")

        wgp.server_config["services"] = services

        # Keep the global text profile and the legacy LLM controls coherent. API
        # keys remain solely in services; only credential-free routing is mirrored.
        if "llm_provider" in body or "llm_model_id" in body:
            try:
                profile = _active_production_profile()
                profile["text"]["provider"] = str(
                    services.get("llm_provider") or profile["text"]["provider"]
                )
                profile["text"]["model"] = str(
                    services.get("llm_model_id") or profile["text"]["model"]
                )
                if services.get("llm_remote_url"):
                    profile["text"]["base_url"] = str(services.get("llm_remote_url") or "")
                wgp.server_config[_PRODUCTION_PROFILE_CONFIG_KEY] = _normalize_production_profile(profile)
            except ValueError:
                pass

        _save_server_config()

        return {"status": "ok", "updated": updated}

    create_settings_services_router.get_services_config = get_services_config
    return router
