"""LLM HTTP surface: load/generate, song-writer, H3 windows, enhance, describe.

The launcher injects config, routing and WanGP-adjacent primitives so this
module never imports WanGP or the launch runtime. Director music generation
stays in launch (Paso 5); it reuses the song-writer helpers exported here.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import traceback
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Request


# The song-writer system prompts live in editable guide files (loaded via
# services.guide_loader.load_guide at request time, cached after first read):
#   app/services/llm_guides/music/song_writer.md            (vocals)
#   app/services/llm_guides/music/song_writer_instrumental.md
#   app/services/llm_guides/music/song_writer_minimax.md
# Edit those to tune the prompt without touching code. These short fallbacks are
# only used if a guide file is missing/unreadable.
_SONG_WRITER_FALLBACK = (
    "You are a songwriter for ACE-Step 1.5. From the user's brief, output EXACTLY "
    "two sections and nothing else:\n[STYLE]\nA dense prose paragraph describing "
    "genre, instruments, mood, production, and vocal type (no numeric BPM/key).\n"
    "[LYRICS]\nOriginal lyrics with [Verse]/[Chorus]/[Bridge] section tags on their "
    "own lines, ~6-10 syllables per line. Keep STYLE and LYRICS consistent."
)
_SONG_WRITER_FALLBACK_INSTRUMENTAL = (
    "You are a music producer for ACE-Step 1.5. Output EXACTLY two sections:\n"
    "[STYLE]\nA dense prose paragraph describing genre, instruments, mood, "
    "production, and energy — instrumental, no vocals, no numeric BPM/key.\n"
    "[LYRICS]\n[Instrumental]"
)
_SONG_WRITER_FALLBACK_MINIMAX = (
    "You write prompts for MiniMax Music. Output exactly [STYLE] and [LYRICS]. "
    "Write both STYLE and LYRICS in the language requested by the user. STYLE is one "
    "comma-separated line of 10-300 characters containing "
    "genre, mood, instruments, vocal direction, tempo and production. Never put "
    "reference song or artist names in STYLE. LYRICS use supported tags such as "
    "[Verse], [Pre Chorus], [Chorus], [Bridge], [Inst], [Solo] and [Outro], each "
    "on its own line, with short singable lines. For instrumentals leave LYRICS empty."
)


def _parse_song_output(raw, instrumental):
    """Split the song-writer LLM output into (style, lyrics)."""
    text = str(raw or "").strip()
    style, lyrics = "", ""
    sm = re.search(r"\[STYLE\](.*?)(?=\[LYRICS\]|\Z)", text, re.IGNORECASE | re.DOTALL)
    lm = re.search(r"\[LYRICS\](.*?)(?=\[LYRIA\]|\Z)", text, re.IGNORECASE | re.DOTALL)
    if sm:
        style = sm.group(1).strip()
    if lm:
        lyrics = lm.group(1).strip()
    if not style and not lyrics:
        # LLM ignored the format — keep the whole thing as lyrics.
        lyrics = text
    if instrumental:
        lyrics = "[Instrumental]"
    return style, lyrics


def _parse_lyria_output(raw):
    """Extract the optional paste-ready Google Lyria prompt."""
    match = re.search(r"\[LYRIA\](.*)\Z", str(raw or ""), re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else ""


def _optional_lyria_warning(lyria_prompt: str, requested: bool) -> str:
    """Describe a missing optional Lyria result without rejecting the song."""
    if requested and not re.search(
        r"\[\d+:\d{2}\s*-\s*\d+:\d{2}\]", str(lyria_prompt or ""),
    ):
        return "The LLM omitted the optional timed Lyria prompt; MiniMax style and lyrics were preserved."
    return ""


def _minimax_song_request_prompt(body: dict, description: str, instrumental: bool) -> str:
    """Build a labelled brief so references never leak into the final provider prompt."""
    model = str(body.get("model") or "music-3.0").strip()
    language = str(body.get("language") or "English").strip()[:80]
    try:
        duration = max(20, min(360, int(body.get("duration_seconds") or 90)))
    except (TypeError, ValueError):
        duration = 90
    sections = [
        f"MODE: {'instrumental' if instrumental else 'vocal song'}",
        f"TARGET MODEL: {model}",
        f"STYLE AND LYRICS LANGUAGE: {language}",
        f"LANGUAGE RULE: Write the visible STYLE prompt and all sung words in {language}. "
        "Keep only provider structural tags such as [Verse] and [Chorus] in English.",
        f"TARGET DURATION: approximately {duration} seconds",
        "DURATION NOTE: MiniMax Music has no exact duration API parameter. Treat the target "
        "as a strict lyric and arrangement budget: keep the section count and sung lines "
        "proportionate to it; do not add repeated verses, choruses or extended outros merely "
        "to retell more story.",
        f"CORE REQUEST:\n{description[:8000]}",
    ]
    labelled_inputs = (
        ("REFERENCE SONG (analysis input only; omit its title and artist from STYLE)", "reference_song", 500),
        ("DESIRED STYLE", "style_direction", 3000),
        ("DESIRED LYRICS OR STRUCTURE", "lyrics_direction", 6000),
        ("STORY CONTEXT", "story_context", 8000),
    )
    for label, key, limit in labelled_inputs:
        value = str(body.get(key) or "").strip()
        if value:
            sections.append(f"{label}:\n{value[:limit]}")
    if model in {"music-cover", "music-cover-free"}:
        sections.append(
            "COVER RULE: STYLE describes only the new target sound; replacement LYRICS "
            "must stay within 1000 characters."
        )
    return "\n\n".join(sections)


def _normalize_minimax_song_output(style: str, lyrics: str, instrumental: bool, model: str):
    """Return provider-safe MiniMax fields while preserving editable lyrics."""
    style = re.sub(r"\s+", " ", str(style or "")).strip()
    if len(style) > 300:
        style = style[:300].rsplit(" ", 1)[0].rstrip(" ,.;:")
    if instrumental:
        return style, ""
    lyrics_limit = 1000 if model in {"music-cover", "music-cover-free"} else 3500
    lyrics = str(lyrics or "").strip()[:lyrics_limit].rstrip()
    return style, lyrics


def _ace_song_request_prompt(description: str, language: str, instrumental: bool) -> str:
    """Keep the editable ACE-Step prompt in the language selected by the user."""
    target = str(language or "English").strip()[:80] or "English"
    if instrumental:
        rule = f"Write the visible STYLE prompt in {target}."
    else:
        rule = (
            f"Write both the visible STYLE prompt and all lyrics in {target}; "
            "keep structural tags such as [Verse] and [Chorus] in English."
        )
    return f"OUTPUT LANGUAGE: {target}. {rule}\n\n{str(description or '').strip()}"


def _song_writer_image_paths(body: dict) -> list:
    """Optional reference images that may inform STYLE; missing files are dropped."""
    image_paths = body.get("image_paths") or []
    if not image_paths and body.get("reference_image_path"):
        image_paths = [body["reference_image_path"]]
    return [p for p in image_paths if p and os.path.isfile(p)]


def _song_writer_prompts(
    body: dict, description: str, instrumental: bool, target: str, language: str,
) -> tuple[str, str, bool]:
    """Return (system_prompt, user_prompt, include_lyria) for the selected contract."""
    from services.guide_loader import load_guide
    include_lyria = False
    if target == "minimax":
        system_prompt = load_guide("music", "song_writer_minimax") or _SONG_WRITER_FALLBACK_MINIMAX
        include_lyria = bool(body.get("include_lyria"))
        if include_lyria:
            lyria_guide = load_guide("music", "song_writer_lyria")
            if lyria_guide:
                system_prompt = f"{system_prompt}\n\n{lyria_guide}"
        user_prompt = _minimax_song_request_prompt(body, description, instrumental)
    elif instrumental:
        system_prompt = load_guide("music", "song_writer_instrumental") or _SONG_WRITER_FALLBACK_INSTRUMENTAL
        user_prompt = _ace_song_request_prompt(description, language, True)
    else:
        system_prompt = load_guide("music", "song_writer") or _SONG_WRITER_FALLBACK
        user_prompt = _ace_song_request_prompt(description, language, False)
    return system_prompt, user_prompt, include_lyria


def _generate_song_writer_text(
    llm_service: Any,
    ensure_llm_loaded: Callable[[], None],
    llm_override: dict | None,
    user_prompt: str,
    system_prompt: str,
    body: dict,
    include_lyria: bool,
    image_paths: list,
):
    """Call the scoped writing LLM or the loaded default; HTTP 500 on provider errors."""
    max_new_tokens = body.get("max_new_tokens", 3000 if include_lyria else 1024)
    paths = image_paths or None
    try:
        if llm_override:
            return llm_service.generate_openai_compatible(
                prompt=user_prompt,
                system_prompt=system_prompt,
                model_id=llm_override["model"],
                base_url=llm_override["base_url"],
                api_key=llm_override["api_key"],
                max_new_tokens=max_new_tokens,
                temperature=body.get("temperature", 0.85),
                top_p=body.get("top_p", 0.9),
                image_paths=paths,
            )
        ensure_llm_loaded()
        return llm_service.generate(
            prompt=user_prompt,
            system_prompt=system_prompt,
            max_new_tokens=max_new_tokens,
            temperature=body.get("temperature", 0.85),
            top_p=body.get("top_p", 0.9),
            seed=body.get("seed"),
            image_paths=paths,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _song_writer_payload(raw, instrumental: bool, target: str, include_lyria: bool, model: str) -> dict:
    """Parse STYLE/LYRICS (and optional Lyria) into the write-song JSON body."""
    style, lyrics = _parse_song_output(raw, instrumental)
    lyria_prompt = _parse_lyria_output(raw) if target == "minimax" and include_lyria else ""
    if target == "minimax":
        style, lyrics = _normalize_minimax_song_output(style, lyrics, instrumental, model)
        if len(style) < 10:
            raise HTTPException(status_code=502, detail="The LLM did not return a valid MiniMax style prompt")
        if not instrumental and not lyrics:
            raise HTTPException(status_code=502, detail="The LLM did not return MiniMax lyrics")
    lyria_warning = _optional_lyria_warning(lyria_prompt, include_lyria)
    return {
        "style": style,
        "lyrics": lyrics,
        "lyria_prompt": lyria_prompt,
        "warnings": [lyria_warning] if lyria_warning else [],
        "raw": raw,
    }


def create_llm_router(
    *,
    get_services_config: Callable[[], dict[str, Any]],
    effective_llm_routing: Callable[..., tuple[str, str, str]],
    llm_provider_credentials: Callable[..., tuple[str, str]],
    llm_default_device: Callable[[], str],
    default_llm_repo: str,
    ensure_llm_loaded: Callable[[], None],
    comic_writing_llm: Callable[[dict], dict | None],
) -> APIRouter:
    """Build the contiguous LLM control/generate/song-writer router."""

    router = APIRouter()

    @router.get("/api/v1/llm/status")
    def llm_status():
        """Get LLM service status."""
        from services import llm_service
        return llm_service.get_status()

    @router.post("/api/v1/llm/load")
    async def llm_load(request: Request):
        """Load the LLM model."""
        from services import llm_service
        body = {}
        if request.headers.get("content-type", "").startswith("application/json"):
            body = await request.json()

        services = get_services_config()
        profile_provider, profile_model, profile_remote_url = effective_llm_routing(services)
        model_id = body.get("model_id", profile_model or default_llm_repo)
        device = body.get("device", services.get("llm_device", llm_default_device()))
        provider = body.get("provider", profile_provider)
        remote_url = body.get("remote_url", profile_remote_url)
        api_key, remote_url = llm_provider_credentials(provider, services, remote_url)

        try:
            llm_service.load_model(model_id=model_id, device=device, provider=provider, remote_url=remote_url, api_key=api_key)
            return {"status": "ok", **llm_service.get_status()}
        except Exception as e:
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=str(e))

    @router.post("/api/v1/llm/unload")
    def llm_unload():
        """Unload the LLM model to free memory."""
        from services import llm_service
        llm_service.unload_model()
        return {"status": "ok"}

    @router.get("/api/v1/llm/models")
    def list_llm_models(provider: str = ""):
        """Return available LLM model options. Pass provider to include remote models."""
        from services import llm_service
        services = get_services_config()
        profile_provider, _profile_model, profile_remote_url = effective_llm_routing(services)
        p = provider or profile_provider
        api_key, remote_url = llm_provider_credentials(p, services, profile_remote_url)
        return {"models": llm_service.get_available_models(provider=p, remote_url=remote_url, api_key=api_key)}

    @router.get("/api/v1/llm/stream-status")
    def llm_stream_status():
        """Return current LLM streaming state for real-time display."""
        from services import llm_service
        return llm_service.get_stream_status()

    @router.post("/api/v1/llm/generate")
    async def llm_generate(request: Request):
        """Generate text with the local LLM."""
        from services import llm_service
        body = await request.json()

        prompt = body.get("prompt", "")
        if not prompt:
            raise HTTPException(status_code=400, detail="prompt is required")

        json_schema = body.get("json_schema")
        if json_schema is not None:
            if not isinstance(json_schema, dict):
                raise HTTPException(status_code=400, detail="json_schema must be an object")
            if len(json.dumps(json_schema, ensure_ascii=False)) > 100_000:
                raise HTTPException(status_code=400, detail="json_schema is too large")

        ensure_llm_loaded()

        try:
            result = llm_service.generate(
                prompt=prompt,
                system_prompt=body.get("system_prompt", ""),
                max_new_tokens=body.get("max_new_tokens", 256),
                temperature=body.get("temperature", 0.7),
                top_p=body.get("top_p", 0.9),
                frequency_penalty=body.get("frequency_penalty", 0.0),
                presence_penalty=body.get("presence_penalty", 0.0),
                seed=body.get("seed"),
                json_schema=json_schema,
            )
            return {"text": result}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.post("/api/v1/llm/test")
    async def llm_test():
        """Send a tiny hello prompt to verify LLM connectivity and config."""
        from services import llm_service

        try:
            # Remote providers are cheap to reconnect. Recreate their client state
            # so a just-edited URL or API key is what this explicit test validates.
            services = get_services_config()
            provider = effective_llm_routing(services)[0]
            if provider in ("remote", "ollama", "openai", "anthropic", "minimax", "grok") and llm_service.is_loaded():
                llm_service.unload_model()
            ensure_llm_loaded()
            response = llm_service.generate(
                prompt="Reply with only: ok",
                max_new_tokens=12,
                temperature=0.1,
            )
            return {
                "ok": True,
                "response": response.strip() or "(no output)",
                "status": llm_service.get_status(),
            }
        except Exception as e:
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=str(e))

    @router.post("/api/v1/llm/write-song")
    async def llm_write_song(request: Request):
        """Produce a provider-ready style prompt and structured lyrics.

        Existing callers default to ACE-Step. Story Lab explicitly selects the
        MiniMax contract and may supply separately labelled inspiration, desired
        style, lyric direction, and story context. Returns {style, lyrics, raw}.
        """
        from services import llm_service
        body = await request.json()
        description = (body.get("description") or "").strip()
        if not description:
            raise HTTPException(status_code=400, detail="description is required")
        instrumental = bool(body.get("instrumental"))
        target = str(body.get("target") or "ace-step").strip().lower()
        model = str(body.get("model") or "music-3.0").strip()
        language = str(body.get("language") or "English").strip()[:80]
        image_paths = _song_writer_image_paths(body)
        system_prompt, user_prompt, include_lyria = _song_writer_prompts(
            body, description, instrumental, target, language,
        )
        llm_override = comic_writing_llm(body) if body.get("writingProvider") else None
        raw = _generate_song_writer_text(
            llm_service,
            ensure_llm_loaded,
            llm_override,
            user_prompt,
            system_prompt,
            body,
            include_lyria,
            image_paths,
        )
        return _song_writer_payload(raw, instrumental, target, include_lyria, model)

    return router


def _h3_plan_model_def(get_model_def: Callable[[str], Any], model_type: str):
    """Require a sliding-window MiniMax H3 model definition."""
    model_def = get_model_def(model_type) or {}
    if not str(model_def.get("architecture") or "").startswith("minimax_h3"):
        raise HTTPException(status_code=400, detail="H3 window planning requires a MiniMax H3 model.")
    if model_def.get("omni_reference"):
        raise HTTPException(status_code=400, detail="MiniMax H3 Omni does not use sliding windows.")
    return model_def


def _h3_planning_inputs(body: dict, model_type: str) -> dict:
    """Collect window-memory inputs using the same field aliases as the Studio UI."""
    return {
        "model_type": model_type,
        "resolution": body.get("resolution") or "864x480",
        "video_length": body.get("total_frames") or body.get("video_length") or 124,
        "sliding_window_size": body.get("window_frames") or body.get("sliding_window_size") or 345,
        "sliding_window_overlap": body.get("overlap_frames", body.get("sliding_window_overlap", 1)),
        "sliding_window_discard_last_frames": body.get("discard_frames", body.get("sliding_window_discard_last_frames", 0)),
        "sliding_window_memory_override": bool(body.get("sliding_window_memory_override", False)),
    }


def _h3_plan_image_paths(body: dict) -> list:
    return [
        path for path in (body.get("image_paths") or [])
        if isinstance(path, str) and path and os.path.isfile(path)
    ]


def _h3_plan_nsfw(
    get_services_config: Callable[[], dict[str, Any]],
    effective_llm_routing: Callable[..., tuple[str, str, str]],
    public_llm_providers: set[str] | frozenset[str],
) -> bool:
    services = get_services_config()
    provider = effective_llm_routing(services)[0]
    return services.get("nsfw_mode", False) and provider not in public_llm_providers


def _enhance_request_image_paths(body: dict) -> list:
    """Support both a single image_path and an image_paths array."""
    image_paths = body.get("image_paths") or []
    if not image_paths and body.get("image_path"):
        image_paths = [body["image_path"]]
    return image_paths


async def _maybe_enhance_with_wangp(
    body: dict,
    prompt: str,
    generation_mode: str,
    needs_h3_context_ir: bool,
    enhancer_enabled: int,
    enhance_with_wangp: Callable[..., Any],
) -> tuple[bool, Any]:
    """Use Wan2GP when enabled, except MiniMax H3 which needs Context-IR."""
    if enhancer_enabled > 0 and not needs_h3_context_ir:
        try:
            image_paths = _enhance_request_image_paths(body)
            return True, await enhance_with_wangp(
                prompt, generation_mode, enhancer_enabled, image_paths=image_paths,
            )
        except Exception as e:
            print(f"[Enhance] Wan2GP enhancer failed, falling back to LLM: {e}")
            return False, None
    if enhancer_enabled > 0 and needs_h3_context_ir:
        print("[Enhance] MiniMax H3 requires structured Context-IR; using HocusPocus Lab's model-specific LLM guide")
    return False, None


def _resolve_enhance_llm(
    body: dict,
    services: dict[str, Any],
    get_model_def: Callable[[str], Any],
) -> tuple[Any, Any, bool]:
    """Pick the enhance model: per-model raw enhancer, else the configured enhance LLM."""
    enhance_model = services.get("enhance_llm_model_id", "")
    enhance_device = services.get("enhance_llm_device", "cuda")
    raw_enhancer_mode = False
    _enh_mt = body.get("model_type", "")
    if _enh_mt:
        try:
            _md = get_model_def(_enh_mt)
            _pe = (_md or {}).get("prompt_enhancer_model")
            if _pe:
                enhance_model = _pe
                raw_enhancer_mode = True
                print(f"[Enhance] Per-model enhancer for {_enh_mt}: {_pe} (raw passthrough)")
        except Exception as e:
            print(f"[Enhance] Per-model enhancer lookup failed: {e}")
    return enhance_model, enhance_device, raw_enhancer_mode


def _ensure_enhance_llm_ready(
    llm_service: Any,
    enhance_model: Any,
    enhance_device: Any,
    ensure_llm_loaded: Callable[[], None],
) -> None:
    if enhance_model:
        if llm_service.is_loaded():
            status = llm_service.get_status()
            if status.get("model_id") != enhance_model:
                llm_service.unload_model()
                llm_service.load_model(model_id=enhance_model, device=enhance_device)
        else:
            llm_service.load_model(model_id=enhance_model, device=enhance_device)
    else:
        ensure_llm_loaded()


def _lora_sidecar_trigger_words(lora_dir: str, lora_name: str) -> list:
    sidecar_path = os.path.join(lora_dir, os.path.splitext(lora_name)[0] + ".civitai.json")
    trigger_words: list = []
    if os.path.isfile(sidecar_path):
        try:
            with open(sidecar_path, "r", encoding="utf-8") as sf:
                sidecar = json.loads(sf.read())
            trigger_words = sidecar.get("trainedWords", []) or []
        except Exception:
            pass
    print(f"[Enhance] LoRA '{lora_name}': triggers={trigger_words[:3]}, sidecar={os.path.isfile(sidecar_path)}")
    return trigger_words


def _lora_trigger_hint_block(trigger_lines: list[str]) -> str:
    any_leet = any(any(c.isdigit() for c in ln) for ln in trigger_lines)
    leet_block = (
        " Some trigger words are coded tokens with letters replaced by "
        "numbers (e.g. 'o'→'0', 'i'→'1', 's'→'5', 'e'→'3', 'a'→'4'). "
        "If you see one with digits, copy it EXACTLY as written — do "
        "not decode it into plain English."
    ) if any_leet else ""
    return (
        "\n\n[LORA TRIGGER WORDS — these are exact tokens the model was "
        "trained on. Pick the ONE most relevant trigger and include it "
        "somewhere in the prompt IF AND ONLY IF it forms a natural, "
        "grammatical part of a sentence. If you cannot weave it in "
        "naturally, OMIT IT ENTIRELY.\n\n"
        "FORBIDDEN INSERTION PATTERNS (any of these ruins the prompt):\n"
        "- At the start as a standalone tag:  'Unchained, the doctor...'\n"
        "- As a comma-offset appositive:      'the doctor, Unchained, in white...'\n"
        "- As a parenthetical:                'the doctor (Unchained) in white...'\n"
        "- As a standalone label anywhere:    '...in the exam room. Unchained. She...'\n"
        "- Attached to an unrelated character: 'the doctor, Mystic XXX, leans...'\n\n"
        "ACCEPTABLE INSERTIONS only if grammatically natural:\n"
        "- Body/appearance descriptor trigger ('detailed muscle definition'): "
        "scoped to the right character inside a sentence — "
        "'the man with detailed muscle definition lifts the crate...'\n"
        "- Style tag trigger ('Mystic XXX', 'Unchained'): use only when the "
        "trigger names a genre or action the scene actually depicts. If it "
        "does not fit grammatically, OMIT IT. Do not force it in.\n\n"
        "Do NOT invent variants. Do NOT include a trigger that does not "
        "match the scene." + leet_block + "]\n"
    ) + "\n".join(trigger_lines)


def _lora_trigger_hint_text(body: dict, model_type: str, get_lora_dir: Callable[[str], str]) -> str:
    """Inject CivitAI trainedWords only; guide prose is not a trigger source."""
    lora_hint_text = ""
    activated_loras = body.get("activated_loras") or []
    print(f"[Enhance] LoRA check: activated_loras={activated_loras}, model_type={model_type}")
    if not (activated_loras and model_type):
        return lora_hint_text
    try:
        lora_dir = get_lora_dir(model_type)
        print(f"[Enhance] LoRA dir: {lora_dir}")
        trigger_lines = []
        for lora_name in activated_loras:
            trigger_words = _lora_sidecar_trigger_words(lora_dir, lora_name)
            if trigger_words:
                trigger_lines.append(f"- {', '.join(trigger_words[:5])}")
        if trigger_lines:
            lora_hint_text = _lora_trigger_hint_block(trigger_lines)
            print(f"[Enhance] Loaded {len(trigger_lines)} trigger block(s): {lora_hint_text[:200]}")
        else:
            print(f"[Enhance] No LoRA triggers extractable from {len(activated_loras)} LoRA(s)")
    except Exception as e:
        print(f"[Enhance] LoRA hint loading failed: {e}")
    return lora_hint_text


def _run_llm_enhance(
    llm_service: Any,
    prompt: str,
    lora_hint_text: str,
    body: dict,
    nsfw: bool,
    model_type: str,
    llm_image_paths: list,
    raw_enhancer_mode: bool,
) -> dict:
    try:
        result = llm_service.enhance_prompt(
            prompt=prompt,
            lora_system_hint=lora_hint_text,
            mode=body.get("mode", "video"),
            max_new_tokens=body.get("max_new_tokens", 512),
            temperature=body.get("temperature", 0.6),
            nsfw=nsfw,
            model_type=model_type,
            image_paths=llm_image_paths if llm_image_paths else None,
            duration_seconds=body.get("duration_seconds"),
            window_count=body.get("window_count"),
            window_size_seconds=body.get("window_size_seconds"),
            tts_enhance_mode=body.get("tts_enhance_mode"),
            tts_voice_count=body.get("tts_voice_count", 2),
            raw_enhancer_mode=raw_enhancer_mode,
            reference_context=body.get("reference_context"),
        )
        return {"original": prompt, "enhanced": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def create_llm_prompt_router(
    *,
    get_services_config: Callable[[], dict[str, Any]],
    effective_llm_routing: Callable[..., tuple[str, str, str]],
    public_llm_providers: set[str] | frozenset[str],
    ensure_llm_loaded: Callable[[], None],
    get_model_def: Callable[[str], Any],
    get_lora_dir: Callable[[str], str],
    get_cached_hardware: Callable[[], dict],
    get_enhancer_enabled: Callable[[], int],
    enhance_with_wangp: Callable[..., Any],
) -> APIRouter:
    """Build the LLM prompt tools that sit after Director generate-music."""

    router = APIRouter()

    @router.post("/api/v1/llm/plan-h3-windows")
    async def llm_plan_h3_windows(request: Request):
        """Expand one H3 First/Last concept into exact per-window prompts."""

        body = await request.json()
        prompt = str(body.get("prompt") or "").strip()
        model_type = str(body.get("model_type") or "")
        if not prompt:
            raise HTTPException(status_code=400, detail="prompt is required")
        model_def = _h3_plan_model_def(get_model_def, model_type)
        planning_inputs = _h3_planning_inputs(body, model_type)
        from models.minimax_h3.minimax_h3_handler import apply_h3_window_memory_policy

        adjustment = apply_h3_window_memory_policy(
            planning_inputs,
            model_def,
            get_cached_hardware(),
        )
        if adjustment and adjustment.get("unsupported"):
            raise HTTPException(status_code=400, detail=adjustment["message"])

        from services.h3_window_planner import plan_h3_sliding_windows

        try:
            ensure_llm_loaded()
        except Exception as load_error:
            # The pure planner has a deterministic no-LLM fallback. Keep H3
            # usable on installs where the optional local planning model has not
            # been downloaded yet, and surface that state in planned_by.
            print(f"[MiniMax H3] Planner LLM unavailable; using fallback: {load_error}")
        nsfw = _h3_plan_nsfw(get_services_config, effective_llm_routing, public_llm_providers)
        image_paths = _h3_plan_image_paths(body)
        total_frames = int(planning_inputs["video_length"])
        window_frames = int(planning_inputs["sliding_window_size"])
        overlap_frames = int(planning_inputs["sliding_window_overlap"] or 0)
        discard_frames = int(planning_inputs["sliding_window_discard_last_frames"] or 0)
        try:
            result = await asyncio.to_thread(
                plan_h3_sliding_windows,
                prompt,
                model_type=model_type,
                resolution=str(planning_inputs["resolution"]),
                total_frames=total_frames,
                window_frames=window_frames,
                overlap_frames=overlap_frames,
                discard_frames=discard_frames,
                fps=float(model_def.get("fps", 24) or 24),
                has_start_image=bool(body.get("has_start_image")),
                has_end_image=bool(body.get("has_end_image")),
                image_paths=image_paths or None,
                nsfw=bool(nsfw),
            )
            result["effective_window_frames"] = window_frames
            return result
        except Exception as error:
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=str(error)) from error

    @router.post("/api/v1/llm/enhance-prompt")
    async def llm_enhance_prompt(request: Request):
        """Enhance a generation prompt. Routes to Wan2GP enhancer or local LLM based on config."""
        body = await request.json()

        prompt = body.get("prompt", "")
        if not prompt:
            raise HTTPException(status_code=400, detail="prompt is required")

        model_type = str(body.get("model_type", "") or "")
        generation_mode = str(body.get("mode", "video") or "video")
        needs_h3_context_ir = (
            model_type.lower().startswith("minimax_h3")
            and generation_mode in ("video", "avatar")
        )
        enhancer_enabled = get_enhancer_enabled()
        used_wangp, wangp_result = await _maybe_enhance_with_wangp(
            body, prompt, generation_mode, needs_h3_context_ir, enhancer_enabled, enhance_with_wangp,
        )
        if used_wangp:
            return wangp_result

        from services import llm_service

        services = get_services_config()
        provider = effective_llm_routing(services)[0]
        nsfw = services.get("nsfw_mode", False) and provider not in public_llm_providers
        enhance_model, enhance_device, raw_enhancer_mode = _resolve_enhance_llm(
            body, services, get_model_def,
        )
        _ensure_enhance_llm_ready(llm_service, enhance_model, enhance_device, ensure_llm_loaded)
        return _run_llm_enhance(
            llm_service,
            prompt,
            _lora_trigger_hint_text(body, model_type, get_lora_dir),
            body,
            nsfw,
            model_type,
            _enhance_request_image_paths(body),
            raw_enhancer_mode,
        )

    @router.post("/api/v1/llm/describe-image")
    async def llm_describe_image(request: Request):
        """Describe an uploaded image using the LLM."""
        from services import llm_service
        body = await request.json()

        image_path = body.get("image_path", "")
        if not image_path:
            raise HTTPException(status_code=400, detail="image_path is required")

        ensure_llm_loaded()

        try:
            result = llm_service.describe_image(
                image_path=image_path,
                prompt=body.get("prompt", "Describe this image in detail."),
                max_new_tokens=body.get("max_new_tokens", 256),
            )
            return {"description": result}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    return router
