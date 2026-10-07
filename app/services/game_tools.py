"""MCP wrappers for one game-asset attempt.

Intent ids are ``game-<game>-<asset>-<attempt>-<step>`` so a resume hits the
same journal entry. Image ``priority`` stays inside ``params``. Sides that
are not multiples of 32 are rejected before the job is submitted.
"""
from __future__ import annotations

import time
from pathlib import Path
from urllib.parse import quote, urlencode

from services.game_generators.base import GenContext
from services.lyrics_language import detect_language


class GameToolError(Exception):
    """A generation tool failed before an attempt file existed."""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        super().__init__(message or code)


_TERMINAL = frozenset({"completed", "failed", "cancelled", "discarded", "error"})


def file_ref(ctx: GenContext, path) -> str:
    """Workspace file URL. Nested paths are served by ``/api/v1/file``.

    The path and the workspace are percent-encoded, as ``wangp_media_url``
    does, so names with spaces or ``+`` survive the round trip.
    """
    rel = str(path).replace("\\", "/").lstrip("/")
    return f"/api/v1/file/{quote(rel)}?{urlencode({'workspace': ctx.workspace})}"


def resolve_path(ctx: GenContext, path) -> Path:
    """Find a tool output, absolute or workspace-relative."""
    candidate = Path(str(path))
    if candidate.is_file():
        return candidate
    root = Path(ctx.workspace_dir(ctx.workspace))
    nested = root / str(path).lstrip("/")
    if nested.is_file():
        return nested
    named = root / candidate.name
    if named.is_file():
        return named
    return candidate


def _intent(ctx: GenContext, step: str) -> str:
    return f"game-{ctx.game['id']}-{ctx.asset['id']}-{ctx.attempt_id}-{step}"


def _check(ctx: GenContext) -> None:
    if ctx.cancelled():
        raise GameToolError("cancelled", "the attempt was cancelled")


def _note(ctx, *, tool, model, seed, prompt, refs, job_id, seconds) -> None:
    ctx.steps.append({
        "tool": tool,
        "model": model,
        "seed": seed,
        "prompt": prompt,
        "refs": list(refs or []),
        "jobId": job_id,
        "seconds": round(float(seconds), 3),
    })


def _mapping(value) -> dict:
    return value if isinstance(value, dict) else {}


def _raise_tool(result: dict) -> None:
    if result.get("_is_error") or result.get("_rpc_error") or result.get("_http_error"):
        raise GameToolError("tool_error", str(result.get("error") or result)[:300])


def _status_payload(result: dict) -> dict:
    _raise_tool(result)
    error = result.get("error")
    if isinstance(error, dict) and ("status" in error or "job_id" in error or "output_files" in error):
        return error
    inner = result.get("result")
    if isinstance(inner, dict) and any(key in inner for key in ("status", "output_files", "filename", "file", "job_id")):
        return inner
    return result


def _job_id(submitted: dict) -> str:
    _raise_tool(submitted)
    if str(submitted.get("status") or "") == "failed":
        raise GameToolError("rejected", str(submitted.get("error") or submitted.get("message") or "the tool refused the request")[:300])
    receipt = _mapping(submitted.get("receipt"))
    nested = _mapping(receipt.get("result")) or receipt
    task = _mapping(nested.get("task")) or _mapping(submitted.get("task")) or _mapping(_mapping(submitted.get("result")).get("task"))
    result = _mapping(submitted.get("result"))
    job = nested.get("job_id") or task.get("job_id") or result.get("job_id") or submitted.get("job_id")
    if not job:
        raise GameToolError("no_job", "admission returned no job_id")
    return str(job)


def _wait_job(ctx: GenContext, job_id: str, intent_id: str | None = None) -> dict:
    """Wait until the image job finishes. A restart leaves it interrupted: resume that same job once."""
    resumed = False
    while True:
        _check(ctx)
        payload = _status_payload(ctx.call("jobs.wait", {"version": 1, "input": {"job_id": job_id, "timeout_s": 110}}))
        status = str(payload.get("status") or "")
        if status in _TERMINAL:
            return payload
        if status == "interrupted":
            if intent_id and not resumed:
                resumed = True
                _raise_tool(ctx.call("jobs.resume", {"version": 1, "input": {"intent_id": intent_id}}))
                continue
            raise GameToolError("interrupted", "the generation stopped when the server restarted")
        if not payload.get("timed_out") and status not in {"", "queued", "running", "pending", "started"}:
            raise GameToolError("no_status", "jobs.wait returned no terminal status")


def _files_of(payload: dict) -> list[str]:
    files = [str(item) for item in (payload.get("output_files") or []) if item]
    if files:
        return files
    found = []
    for item in payload.get("outputs") or []:
        if isinstance(item, dict):
            path = item.get("path") or item.get("canonical_url")
            if path:
                found.append(str(path))
    return found


def _require_files(payload: dict) -> list[str]:
    status = str(payload.get("status") or "")
    if status in {"failed", "cancelled", "discarded", "error"}:
        raise GameToolError(status or "failed", str(payload.get("error") or payload.get("message") or status))
    files = _files_of(payload)
    if not files:
        raise GameToolError("empty_output", "completed job returned no files")
    return files


def _resolution(resolution: str) -> str:
    text = str(resolution).lower().replace(" ", "")
    if "x" not in text:
        raise GameToolError("resolution", "resolution must be <width>x<height>")
    width, height = text.split("x", 1)
    if not width.isdigit() or not height.isdigit():
        raise GameToolError("resolution", "resolution must be <width>x<height>")
    if int(width) % 32 or int(height) % 32 or int(width) <= 0 or int(height) <= 0:
        raise GameToolError("resolution", "sides must be multiples of 32")
    return text


def _api_refs(ctx: GenContext, refs) -> list[str]:
    prepared = []
    for ref in refs or []:
        text = str(ref)
        prepared.append(text if text.startswith("/") or text.startswith("asset_") else file_ref(ctx, text))
    return prepared


def _source_name(ctx: GenContext, path) -> str:
    text = str(path)
    if text.startswith("/api/") or text.startswith("asset_"):
        return text
    root = str(Path(ctx.workspace_dir(ctx.workspace)))
    if text.startswith(root):
        return text[len(root):].lstrip("/")
    return text


def _finish(ctx, *, tool, model, seed, prompt, refs, job_id, started) -> None:
    _note(ctx, tool=tool, model=model, seed=seed, prompt=prompt, refs=refs, job_id=job_id, seconds=time.perf_counter() - started)
    ctx.log(f"{tool} {job_id}")


def image(ctx, step, *, prompt, negative, resolution, refs=(), seed, batch=1, guide=None, mask=None, priority=10) -> list[str]:
    """Submit ``generation.image`` and wait until ``output_files`` is non-empty."""
    snapped = _resolution(resolution)
    _check(ctx)
    prepared = _api_refs(ctx, refs)
    params = {
        "prompt": prompt,
        "negative_prompt": negative,
        "model_type": "qwen_image_21",
        "resolution": snapped,
        "seed": int(seed),
        "guidance_scale": 1,
        "num_inference_steps": 40,
        "priority": int(priority),
        "batch_size": max(1, int(batch)),
    }
    if guide and mask:
        params["image_guide"] = guide if str(guide).startswith("/") else file_ref(ctx, guide)
        params["image_mask"] = mask if str(mask).startswith("/") else file_ref(ctx, mask)
        params["video_prompt_type"] = "VAGI" if prepared else "VAG"
        params["model_mode"] = 0
    elif prepared:
        params["video_prompt_type"] = "I"
    if prepared:
        params["image_refs"] = prepared
    started = time.perf_counter()
    submitted = ctx.call("generation.image", {
        "version": 2,
        "intent_id": _intent(ctx, step),
        "input": {"workspace": ctx.workspace, "output_name": f"{ctx.asset['id']}-{step}", "params": params},
    })
    job_id = _job_id(submitted)
    files = _require_files(_wait_job(ctx, job_id, _intent(ctx, step)))
    _finish(ctx, tool="generation.image", model="qwen_image_21", seed=int(seed), prompt=prompt, refs=prepared, job_id=job_id, started=started)
    return files


def key(ctx, step, path, screen) -> str:
    """Key ``path`` on the CPU. Returns ``result.file`` and does not crop."""
    _check(ctx)
    started = time.perf_counter()
    result = ctx.call("studio.key", {
        "version": 1,
        "intent_id": _intent(ctx, step),
        "input": {"workspace": ctx.workspace, "source": _source_name(ctx, path), "mode": screen},
    })
    payload = _status_payload(result)
    name = payload.get("file") or _mapping(result.get("result")).get("file")
    if not name:
        raise GameToolError("key_failed", "studio.key returned no file")
    _finish(ctx, tool="studio.key", model="screen", seed=None, prompt="", refs=[str(path)], job_id=str(name), started=started)
    return str(name)


def _video(ctx, step, params) -> str:
    _check(ctx)
    started = time.perf_counter()
    submitted = ctx.call("generation.video", {
        "version": 3,
        "intent_id": _intent(ctx, step),
        "input": {"workspace": ctx.workspace, "params": params},
    })
    job_id = _job_id(submitted)
    files = _require_files(_wait_job(ctx, job_id, _intent(ctx, step)))
    _finish(ctx, tool="generation.video", model=str(params.get("model_type") or ""), seed=params.get("seed"), prompt=str(params.get("prompt") or ""), refs=[], job_id=job_id, started=started)
    return files[0]


def video_fl2va(ctx, step, *, prompt, start, end=None, frames, model, resolution, steps=None, seed=None) -> str:
    """First-and-last-frame video. ``end`` is omitted when the action leaves the stance."""
    params = {"prompt": prompt, "model_type": model, "resolution": resolution, "video_length": int(frames), "image_start": start}
    if seed is not None:
        params["seed"] = int(seed)
    if end:
        params["image_end"] = end
    if steps is not None:
        params["num_inference_steps"] = int(steps)
    return _video(ctx, step, params)


def video_ref2va(ctx, step, *, prompt, references, frames, model, resolution, steps=None) -> str:
    """Reference-to-video. This mode does not take ``image_start`` or ``image_end``."""
    params = {
        "prompt": prompt,
        "model_type": model,
        "resolution": resolution,
        "video_length": int(frames),
        "references": list(references),
    }
    if steps is not None:
        params["num_inference_steps"] = int(steps)
    return _video(ctx, step, params)


def orbit(ctx, step, ref) -> str:
    """Four-view orbit through the legacy ``generate`` tool, via HTTP loopback."""
    _check(ctx)
    image_ref = ref if str(ref).startswith("/") else file_ref(ctx, ref)
    params = {
        "generation_mode": "video",
        "model_type": "minimax_h3_legacy",
        "character_sheet_engine": "poopman333_6_panel",
        "resolution": "768x1344",
        "video_length": 124,
        "num_inference_steps": 25,
        "image_start": image_ref,
        "workspace": ctx.workspace,
        "prompt": "character turnaround, front, side, back and other side, neutral pose, feet visible",
    }
    started = time.perf_counter()
    submitted = ctx.loopback("generate", {"request_id": _intent(ctx, step), "params": params})
    job_id = _job_id(submitted if isinstance(submitted, dict) else {})
    files = _require_files(_wait_job(ctx, job_id, _intent(ctx, step)))
    _finish(ctx, tool="generate", model="minimax_h3_legacy", seed=None, prompt=params["prompt"], refs=[image_ref], job_id=job_id, started=started)
    return files[0]


def _audio(ctx, tool, step, params, output_name) -> str:
    _check(ctx)
    started = time.perf_counter()
    submitted = ctx.call(tool, {
        "version": 2,
        "intent_id": _intent(ctx, step),
        "input": {"workspace": ctx.workspace, "output_name": output_name, "params": params},
    })
    job_id = _job_id(submitted)
    files = _require_files(_wait_job(ctx, job_id, _intent(ctx, step)))
    _finish(ctx, tool=tool, model=str(params.get("model_type") or ""), seed=params.get("seed"), prompt=str(params.get("prompt") or ""), refs=[], job_id=job_id, started=started)
    return files[0]


def sfx(ctx, step, *, prompt, seconds, seed, output_name=None) -> str:
    """MMAudio effect. Both prompt fields carry the same text."""
    params = {
        "prompt": prompt,
        "MMAudio_prompt": prompt,
        "model_type": "mmaudio_v2",
        "duration_seconds": float(seconds),
        "seed": int(seed),
        "priority": 10,
    }
    return _audio(ctx, "generation.sfx", step, params, output_name or f"{ctx.asset['id']}-{step}")


def music(ctx, step, *, prompt, alt_prompt, seconds, seed, bpm=120, output_name=None) -> str:
    """ACE-Step instrumental. ``prompt`` is the lyrics field, usually ``[Instrumental]``.

    Sung lyrics go in their own language (es/en told from the words); English only when nothing tells.
    """
    sung = detect_language(prompt)
    params = {
        "prompt": prompt,
        "alt_prompt": alt_prompt,
        "model_type": "ace_step_v1_5_xl_sft_lm_4b",
        "seed": int(seed),
        "duration_seconds": float(seconds),
        "lyrics_language": sung or "en",
        "custom_settings": {"bpm": int(bpm), "keyscale": "C major", "timesignature": 4, **({"language": sung} if sung else {})},
        "priority": 10,
    }
    return _audio(ctx, "generation.music", step, params, output_name or f"{ctx.asset['id']}-{step}")


def speech(ctx, step, *, prompt, model, seed=1, output_name=None, extra=None) -> str:
    """One spoken line. Extra native params are passed through to the speech command."""
    params = {"prompt": prompt, "model_type": model, "seed": int(seed), "priority": 10}
    if extra:
        params.update(extra)
    return _audio(ctx, "generation.speech", step, params, output_name or f"{ctx.asset['id']}-{step}")


def _poll(ctx: GenContext, tool: str, job_id: str) -> dict:
    while True:
        _check(ctx)
        payload = _status_payload(ctx.call(tool, {"version": 1, "input": {"workspace": ctx.workspace, "job_id": job_id}}))
        status = str(payload.get("status") or "")
        if status in _TERMINAL:
            if status != "completed":
                # ``message`` is often the last progress line ("Queued Hunyuan3D generation"); the error says why.
                raise GameToolError(status or "failed", str(payload.get("error") or payload.get("message") or status))
            return payload
        time.sleep(2)


def _model_file(payload: dict) -> str:
    if payload.get("filename") or payload.get("file"):
        return str(payload.get("filename") or payload.get("file"))
    files = _files_of(payload)
    if not files:
        raise GameToolError("empty_output", "the 3D tool returned no file")
    return files[0]


def model3d(ctx, step, *, image_path, images=None, preset=None, reduce_face=None, target_face_num=None,
            texture_resolution=None, seed=None) -> str:
    """Hunyuan mesh. Waits on ``model3d.status`` and returns ``result.filename``.

    ``texture_resolution`` is clamped by the service to 256–1024 px; ``seed`` makes candidates differ.
    """
    _check(ctx)
    payload = {"workspace": ctx.workspace, "image_path": image_path}
    if texture_resolution is not None:
        payload["texture_resolution"] = int(texture_resolution)
    if seed is not None:
        payload["seed"] = int(seed)
    if images:
        payload["images"] = images
    if preset:
        payload["preset"] = preset
    if reduce_face is not None:
        payload["reduce_face"] = bool(reduce_face)
    if target_face_num is not None:
        payload["target_face_num"] = int(target_face_num)
    started = time.perf_counter()
    submitted = ctx.call("model3d.generate", {"version": 1, "intent_id": _intent(ctx, step), "input": payload})
    finished = _poll(ctx, "model3d.status", _job_id(submitted))
    name = _model_file(finished)
    _finish(ctx, tool="model3d.generate", model="hunyuan3d", seed=seed, prompt="", refs=[str(image_path)], job_id=_job_id(submitted), started=started)
    return name


def rig(ctx, step, *, source, engine="humanoid", animations=None, rig_profile=None) -> str:
    """Rig a GLB. Waits on ``model3d.rig.status``."""
    _check(ctx)
    payload = {
        "workspace": ctx.workspace,
        "source": source,
        "engine": engine,
        "animations": list(animations or ["idle", "walk"]),
    }
    if rig_profile:
        payload["rig_profile"] = rig_profile
    started = time.perf_counter()
    submitted = ctx.call("model3d.rig", {"version": 1, "intent_id": _intent(ctx, step), "input": payload})
    job_id = _job_id(submitted)
    finished = _poll(ctx, "model3d.rig.status", job_id)
    name = _model_file(finished)
    _finish(ctx, tool="model3d.rig", model=engine, seed=None, prompt="", refs=[str(source)], job_id=job_id, started=started)
    return name
