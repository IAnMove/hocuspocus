"""Director music and character-reference description.

These two routes are not next to each other in the full server. The LLM
prompt tools stay between them so their route order does not change. The
handlers below are the launch functions, unchanged. Shared names are the
launch objects, assigned onto this module before a request runs. Launch
assigns the workspace-collection registry after it builds that registry.
"""

from __future__ import annotations

import asyncio
import os

from fastapi import APIRouter, HTTPException, Request

from routers.llm import (
    _SONG_WRITER_FALLBACK,
    _SONG_WRITER_FALLBACK_INSTRUMENTAL,
    _SONG_WRITER_FALLBACK_MINIMAX_MUSIC3,
    _parse_song_output,
)
from services import execution_mode


# The real registry is created later in the launch module.
_workspace_collection_registry = None

def _ensure_llm_loaded():
    """Auto-load LLM if not already loaded. Reloads if configured model changed."""
    from services import llm_routing

    services = wgp.server_config.get("services", {})
    desired_provider, profile_model, desired_remote_url = _effective_llm_routing(services)
    llm_routing._ensure_llm_loaded(
        services=services,
        provider=desired_provider,
        model=profile_model,
        remote_url=desired_remote_url,
        device=services.get("llm_device", _llm_default_device()),
        default_model=_DEFAULT_LLM_REPO,
    )

def _resolve_wangp_visual_media(value, workspace):
    from services.wangp_submission import resolve_wangp_media
    workspace = workspace or _get_active_workspace()
    return resolve_wangp_media(value, workspace, uploads_dir=os.path.join(os.getcwd(), 'uploads'), workspace_dir=_workspace_dir(workspace))

def _build_music_gen_params(model_type: str, lyrics: str, style: str, duration_seconds, seed) -> dict:
    """Build an ACE-Step generation params dict by seeding from the model's
    OWN default settings — the exact same source the Studio Music UI starts
    from (served via /api/v1/models/{model_type} → wgp.get_default_settings).
    This guarantees parity: every model-specific field the ACE-Step pipeline
    needs (LM sampling temperature/top_k/top_p, audio_scale, scheduler_type,
    shift, num_inference_steps, etc.) is present. A hand-built subset omitted
    the LM sampling fields, which made the XL "Strong Think" LM path fail with
    'NoneType object does not support item assignment'. We override only the
    song content, duration, and seed, then force audio-only generation."""
    try:
        params = dict(wgp.get_default_settings(model_type) or {})
    except Exception as e:
        print(f"[generate-music] get_default_settings failed for {model_type}: {e}")
        params = {}
    params["model_type"] = model_type
    params["prompt"] = lyrics or "[Instrumental]"
    params["alt_prompt"] = style or ""
    params.setdefault("negative_prompt", "")
    if duration_seconds:
        try:
            params["duration_seconds"] = float(duration_seconds)
        except (TypeError, ValueError):
            pass
    try:
        params["seed"] = int(seed)
    except (TypeError, ValueError):
        params["seed"] = -1
    # Force audio-only, single-prompt generation (no video output).
    params["video_length"] = 0
    params["image_mode"] = 0
    params["multi_prompts_gen_type"] = 2
    params["generation_mode"] = "audio"
    return params

def _music3_writer_duration_instruction(duration_seconds) -> str:
    """Keep local MiniMax-Music3 song writing proportional to its target runtime."""
    try:
        duration = min(300.0, max(5.0, float(duration_seconds or 120)))
    except (TypeError, ValueError):
        duration = 120.0
    label = f"{duration:g}"
    return (
        "TARGET RUNTIME CONTRACT:\n"
        f"- The generated track is {label} seconds long.\n"
        "- Scale sections, lyric density, repetitions, transitions and instrumental "
        "space to this runtime; do not write a full song that will be cut off.\n"
        f"- In ### Arrangement, plan material from 0:00 to approximately {label} seconds."
    )

async def director_generate_music(request: Request):
    """Generate a music track for Director Music Video mode. Dual-mode:
      - If `style`/`lyrics` are supplied, render them directly.
      - Else if `description` is supplied, write the song first (optionally
        informed by a reference image via the vision LLM), then render.
    Blocks until the track is rendered (consistent with the awaited
    upload→analyze→plan-structure chain) and returns the ABSOLUTE
    {audio_path} so the frontend can feed it straight into /audio/analyze.
    Returns {audio_path, filename, style, lyrics}."""
    import asyncio
    from services.generation_provenance import normalize_submission_provenance
    body = await request.json()
    provenance = normalize_submission_provenance(body.pop("provenance", None))
    description = (body.get("description") or "").strip()
    style = (body.get("style") or "").strip()
    lyrics = (body.get("lyrics") or "").strip()
    instrumental = bool(body.get("instrumental"))
    model_type = body.get("model_type") or "ace_step_v1_5_xl_sft_lm_4b"
    duration_seconds = body.get("duration_seconds")
    seed = body.get("seed")
    # ``workspace`` is the physical output-folder name. A Workspace
    # collection is an optional, explicit provenance reference and must never
    # be inferred from this folder.
    workspace = body.get("workspace") or _get_active_workspace()
    collection_id = provenance.get("workspace_id")
    if collection_id and not _workspace_collection_registry.get(collection_id):
        raise HTTPException(status_code=400, detail="Unknown Workspace collection")
    try:
        execution_mode.validate_generation(workspace)
    except execution_mode.ExecutionModeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    selected_model = wgp.get_model_def(model_type)
    if selected_model is None:
        raise HTTPException(status_code=400, detail=f"Unknown model: {model_type}")
    is_minimax_music3 = str(selected_model.get("architecture") or model_type) == "minimax_music3"

    image_paths = body.get("image_paths") or []
    if not image_paths and body.get("reference_image_path"):
        image_paths = [body["reference_image_path"]]
    image_paths = [p for p in image_paths if p and os.path.isfile(p)]

    if instrumental:
        lyrics = "[Instrumental]"

    # Write the song from the description when we don't already have content.
    if (not style or not lyrics) and description:
        from services import llm_service
        from services.guide_loader import load_guide
        _ensure_llm_loaded()
        if is_minimax_music3 and instrumental:
            system_prompt = load_guide("music", "song_writer_minimax_music3_instrumental") or _SONG_WRITER_FALLBACK_MINIMAX_MUSIC3
        elif is_minimax_music3:
            system_prompt = load_guide("music", "song_writer_minimax_music3") or _SONG_WRITER_FALLBACK_MINIMAX_MUSIC3
        elif instrumental:
            system_prompt = load_guide("music", "song_writer_instrumental") or _SONG_WRITER_FALLBACK_INSTRUMENTAL
        else:
            system_prompt = load_guide("music", "song_writer") or _SONG_WRITER_FALLBACK
        if is_minimax_music3:
            system_prompt = f"{system_prompt.rstrip()}\n\n{_music3_writer_duration_instruction(duration_seconds)}"
        try:
            raw = await asyncio.to_thread(
                llm_service.generate,
                prompt=description,
                system_prompt=system_prompt,
                max_new_tokens=body.get("max_new_tokens", 1536 if is_minimax_music3 else 1024),
                temperature=body.get("temperature", 0.85),
                top_p=body.get("top_p", 0.9),
                seed=body.get("seed"),
                image_paths=image_paths or None,
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Song writing failed: {e}")
        w_style, w_lyrics = _parse_song_output(raw, instrumental)
        style = style or w_style
        lyrics = lyrics or w_lyrics

    if not lyrics:
        raise HTTPException(status_code=400, detail="Provide a description, or style + lyrics")

    gen_params = _build_music_gen_params(model_type, lyrics, style, duration_seconds, seed)
    gen_params["_initiator"] = str(body.get("initiator") or "Director · Music video")[:200]

    out_dir = _workspace_dir(workspace)
    os.makedirs(out_dir, exist_ok=True)

    # Wire director_pipeline's shared refs (_jobs / _run_generation / _gen_lock)
    # before using _submit_and_wait — without this they're None and the first
    # line `_jobs[job_id] = job` raises "'NoneType' object does not support
    # item assignment". Every other _submit_and_wait caller calls this first.
    _init_pipeline()
    from services.director_pipeline import _submit_and_wait
    try:
        output_files = await asyncio.to_thread(
            _submit_and_wait,
            gen_params,
            # Music3 can decode several minutes of stereo audio on a single
            # consumer GPU; keep the HTTP worker alive long enough for the
            # local job while retaining the shorter guard for ACE-Step.
            timeout_s=3600 if is_minimax_music3 else 1800,
            workspace=workspace,
            out_dir=out_dir,
            provenance=provenance,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Music generation failed: {e}")
    if not output_files:
        raise HTTPException(status_code=500, detail="Music generation produced no output")

    filename = output_files[0]
    audio_path = os.path.join(out_dir, filename)
    return {
        "audio_path": audio_path,
        "filename": filename,
        "style": style,
        "lyrics": lyrics,
        "job_id": getattr(output_files, "job_id", None),
        "task_id": getattr(output_files, "task_id", None),
        "root_task_id": getattr(output_files, "root_task_id", None),
    }

async def _enhance_with_wangp(prompt: str, mode: str, enhancer_enabled: int, image_paths: list = None):
    """Run the Wan2GP prompt enhancer using wgp's built-in offload system."""
    import secrets
    from PIL import Image
    from shared.prompt_enhancer.prompt_enhance_utils import generate_cinematic_prompt
    from mmgp import offload

    # Setup enhancer with proper GPU offload (same as Wan2GP does internally)
    if wgp.enhancer_offloadobj is None:
        print(f"[Enhance] Loading Wan2GP enhancer (mode {enhancer_enabled}) with GPU offload...")
        pipe = {}
        kwargs = {}
        wgp.download_models()
        wgp.setup_prompt_enhancer(pipe, kwargs)
        profile = wgp.compute_profile(-1, "video")
        mmgp_profile = wgp.init_pipe(pipe, kwargs, profile)
        wgp.enhancer_offloadobj = offload.profile(pipe, profile_no=mmgp_profile, **kwargs)

    if wgp.prompt_enhancer_llm_model is None:
        raise RuntimeError("Prompt enhancer model failed to load")

    is_video = mode in ("video", "avatar")
    temperature = wgp.server_config.get("prompt_enhancer_temperature", 0.6)
    top_p = wgp.server_config.get("prompt_enhancer_top_p", 0.9)
    seed = secrets.randbits(32) if wgp.server_config.get("prompt_enhancer_randomize_seed", True) else 0

    # Load images if provided
    prompt_images = None
    if image_paths:
        loaded = []
        for img_path in image_paths:
            if img_path and os.path.isfile(img_path):
                try:
                    loaded.append(Image.open(img_path))
                    print(f"[Enhance] Including image: {os.path.basename(img_path)}")
                except Exception as e:
                    print(f"[Enhance] Failed to load image {img_path}: {e}")
        if loaded:
            prompt_images = loaded

    post_image_caption_hook = None
    if prompt_images and wgp.enhancer_offloadobj is not None:
        if hasattr(wgp.prompt_enhancer_image_caption_model, "vision_tower_model") and hasattr(wgp.prompt_enhancer_llm_model, "generate_messages"):
            post_image_caption_hook = wgp.enhancer_offloadobj.unload_all

    def _run():
        return generate_cinematic_prompt(
            wgp.prompt_enhancer_image_caption_model,
            wgp.prompt_enhancer_image_caption_processor,
            wgp.prompt_enhancer_llm_model,
            wgp.prompt_enhancer_llm_tokenizer,
            [prompt],
            prompt_images,
            video_prompt=is_video,
            text_prompt=False,
            max_new_tokens=512,
            do_sample=True,
            temperature=temperature,
            top_p=top_p,
            seed=seed,
            post_image_caption_hook=post_image_caption_hook,
        )

    result = await asyncio.get_event_loop().run_in_executor(None, _run)

    # Unload from GPU to free VRAM
    if wgp.enhancer_offloadobj is not None:
        wgp.enhancer_offloadobj.unload_all()

    enhanced = result[0] if isinstance(result, list) and result else (result or prompt)
    print(f"[Enhance] Wan2GP enhanced: {len(enhanced)} chars")
    return {"original": prompt, "enhanced": enhanced}

async def describe_character_refs(request: Request):
    """Build an A Prompt with MiniMax vision or the configured internal LLM."""
    from services import llm_service
    from services.character_sheet import DESCRIBE_SCHEMA, describe_character_sheet

    body = await request.json()
    workspace = body.get("workspace") if "workspace" in body else _get_active_workspace()
    raw_paths = body.get("image_paths") or []
    if not isinstance(raw_paths, list) or not raw_paths:
        raise HTTPException(status_code=400, detail="image_paths is required")
    image_paths = []
    for value in raw_paths:
        resolved = _resolve_model3d_input_path(str(value or ""), workspace)
        if not resolved or not os.path.isfile(resolved):
            raise HTTPException(status_code=400, detail="Character reference image not found")
        image_paths.append(resolved)

    services = wgp.server_config.get("services", {})
    from services.provider_profile import character_describe_backend, resolve_minimax_key

    backend = character_describe_backend(_effective_llm_routing(services)[0])
    if backend == "unavailable":
        raise HTTPException(
            status_code=400,
            detail="Auto-describe only works with MiniMax or the internal LLM. Type an A Prompt, or switch Settings → LLM.",
        )

    def complete(system_prompt: str, user_prompt: str, paths: list[str]) -> str:
        if backend == "minimax":
            api_key = resolve_minimax_key(services, "llm")
            if not api_key:
                raise ValueError("Configure the MiniMax LLM API key in Settings → Services first")
            return llm_service.generate_openai_compatible(
                prompt=user_prompt,
                system_prompt=system_prompt,
                model_id="MiniMax-M3",
                base_url="https://api.minimax.io/v1",
                api_key=api_key,
                max_new_tokens=1200,
                temperature=0.2,
                json_schema=DESCRIBE_SCHEMA,
                image_paths=paths,
            )
        _ensure_llm_loaded()
        return llm_service.generate(
            prompt=user_prompt,
            system_prompt=system_prompt,
            max_new_tokens=1200,
            temperature=0.2,
            json_schema=DESCRIBE_SCHEMA,
            image_paths=paths,
        )

    try:
        a_prompt = describe_character_sheet(
            kind=body.get("kind") or "character",
            image_paths=image_paths,
            roles=body.get("roles") or None,
            complete=complete,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"a_prompt": a_prompt, "kind": body.get("kind") or "character"}

def create_director_music_router(
    *,
    wgp,
    _get_active_workspace,
    _workspace_dir,
    _init_pipeline,
    _effective_llm_routing,
    _llm_default_device,
    _DEFAULT_LLM_REPO,
):
    """Mount Director music at its old position in the full server.

    The handler stays module-level: its complexity is above the limit for
    new code, and this route is a one-line delegate to that same function.
    """
    globals().update({
        "wgp": wgp,
        "_get_active_workspace": _get_active_workspace,
        "_workspace_dir": _workspace_dir,
        "_init_pipeline": _init_pipeline,
        "_effective_llm_routing": _effective_llm_routing,
        "_llm_default_device": _llm_default_device,
        "_DEFAULT_LLM_REPO": _DEFAULT_LLM_REPO,
    })
    router = APIRouter()
    # The wrapper below is also named director_generate_music, which makes
    # that name local to this factory. Read the module handler first.
    _impl = globals()["director_generate_music"]

    @router.post("/api/v1/director/generate-music")
    async def director_generate_music(request: Request):
        return await _impl(request)

    create_director_music_router.director_generate_music = director_generate_music
    return router


def create_character_describe_router(*, _resolve_model3d_input_path):
    """Mount character description at its old position, after the prompt tools."""
    globals().update({
        "_resolve_model3d_input_path": _resolve_model3d_input_path,
    })
    router = APIRouter()
    _impl = globals()["describe_character_refs"]

    @router.post("/api/v1/characters/describe-refs")
    async def describe_character_refs(request: Request):
        return await _impl(request)

    create_character_describe_router.describe_character_refs = describe_character_refs
    return router
