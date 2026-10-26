"""``shot.lipsync.redo``: regenerate one shot's mouth as a new take.

The original clip, the selected production clip and the series approval stay.
A missing weight stack returns the disk size and does not start a download
until ``confirm_download`` is true, which uses the existing model download.
No GPU is required to refuse or to record a take a caller-supplied worker wrote.
"""
from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any, Callable

from services.production_media_common import (
    WORKSPACE, MediaToolError, operation_schema, read_input, resolve_source, uploads_root, workspace_folder,
)
from services.shot_lipsync_catalog import ENGINES, PROMPT, missing_files, video_length
from services.shot_lipsync_save import save_clip, save_production, save_series

OPERATION = "shot.lipsync.redo"
_KEYS = frozenset({
    "workspace", "engine", "series_id", "episode_id", "shot", "production_id",
    "clip", "source", "audio", "span", "offset", "confirm_download",
})
_ID_MAX = 80

# Tests replace ``worker``. None uses the full server's generation queue.
worker: Callable[[dict, str], str] | None = None


def catalog() -> dict[str, Any]:
    return operation_schema(OPERATION, (
        "Redo the lips of one finished shot as a new take, keeping the original. engine is infinitetalk "
        "(video-to-video, Apache-2.0). longcat_avatar stays in the model catalog and is not offered: "
        "it does not read the shot video. Name one target: "
        "production_id + shot, series_id + episode_id + shot, or clip. audio is the driving sound "
        "(a production uses its song when audio is omitted; a series uses its recorded line, "
        "placed at the line's start, and does not use the score cue). "
        "span is [start, end] seconds of that sound. The result is a new take; the selected clip and any "
        "series approval stay. When the int8 weights are missing the call returns their disk size and does "
        "not download; confirm_download true starts the existing model download and does not wait for it. "
        "Returns file, kept_original, verdict (qa.lipsync: ok, retake or unreliable) and qa."
    ), {
        "workspace": WORKSPACE,
        "engine": {"type": "string", "enum": ["infinitetalk"]},
        "production_id": {"type": "string", "minLength": 1, "maxLength": _ID_MAX},
        "series_id": {"type": "string", "minLength": 1, "maxLength": 120},
        "episode_id": {"type": "string", "minLength": 1, "maxLength": 120},
        "shot": {"type": "string", "minLength": 1, "maxLength": _ID_MAX},
        "clip": {"type": "string", "minLength": 1, "maxLength": 2000},
        "source": {"type": "string", "minLength": 1, "maxLength": 2000,
                   "description": "Video to follow when the target is a shot. Omit it to use the shot's current take."},
        "audio": {"type": "string", "minLength": 1, "maxLength": 2000},
        "span": {"type": "array", "minItems": 2, "maxItems": 2, "items": {"type": "number"},
                 "description": "Seconds [start, end] of the audio to drive and to score."},
        "offset": {"type": "number", "minimum": 0, "maximum": 36000,
                   "description": "Seconds into the audio where the clip starts. When span is set, the take starts at span start and the score uses that offset."},
        "confirm_download": {"type": "boolean"},
    }, ["workspace", "engine"])


def weights_root() -> Path:
    return Path(__file__).resolve().parents[1] / "ckpts"


def run(arguments: Any, *, workspace_dir, uploads_dir) -> dict[str, Any]:
    payload = read_input(arguments, _KEYS, ("workspace", "engine"))
    workspace = payload["workspace"]
    folder, uploads = workspace_folder(workspace_dir, workspace), uploads_root(uploads_dir)
    target = resolve_target(payload, folder, uploads, workspace)
    if target["locked"]:
        raise MediaToolError("shot_locked", "This shot is locked.", 409)
    gap = missing_files(target["engine"], weights_root())
    if gap:
        return _weights(payload, target["engine"], gap)
    guides = prepare_guides(target, folder)
    video = _adopt(folder, enqueue(_body(target, workspace, guides, folder), folder))
    qa = score_take(video, guides["audio_path"], _score_offset(guides), guides["span"])
    saved = _save(folder, workspace, target, video, qa)
    return {**saved, "engine": target["engine"], "verdict": qa.get("verdict"), "qa": qa}


def resolve_target(payload: dict, folder: str, uploads: str, workspace: str) -> dict[str, Any]:
    engine = _engine(payload.get("engine"))
    _confirm_flag(payload)
    _one_target(payload)
    span = _span(payload.get("span"))
    offset = _number(payload.get("offset"), "offset")
    if payload.get("clip"):
        return _clip_target(payload, folder, uploads, workspace, engine, span, offset)
    if payload.get("production_id"):
        return _production_target(payload, folder, uploads, workspace, engine, span, offset)
    return _series_target(payload, folder, uploads, workspace, engine, span, offset)


def prepare_guides(target: dict, folder: str) -> dict[str, Any]:
    """Absolute paths. InfiniteTalk and LongCat are not ``wangp_1272``, so the queue
    never resolves a workspace-relative name and drops the file."""
    span = target["span"]
    owned: list[str] = []
    if target.get("placed"):
        owned.append(os.path.abspath(target["audio"]))
    audio = trim_span(target["audio"], folder, span[0], span[1]) if span else target["audio"]
    if span:
        owned.append(os.path.abspath(audio))
    return {
        "video": os.path.abspath(target["video"]), "audio": os.path.abspath(audio),
        "audio_path": target["audio"], "span": span, "offset": target["offset"],
        "trimmed": owned[-1] if owned else None, "owned": owned,
    }


def enqueue(body: dict, folder: str) -> str:
    if worker is not None:
        return worker(body, folder)
    return _server_queue(body, folder)


def _score_offset(guides: dict) -> float:
    """The take starts at the span, so frame 0 is ``span[0]`` of the original audio."""
    span = guides.get("span")
    if span:
        return float(span[0])
    return float(guides.get("offset") or 0.0)


def score_take(video: str, audio: str, offset: float, span: tuple[float, float] | None) -> dict[str, Any]:
    try:
        result = measure_lips(video, audio, offset, span)
    except Exception:
        return {"verdict": "unreliable", "reason": "qa_unavailable"}
    if not isinstance(result, dict) or not result.get("verdict"):
        return {"verdict": "unreliable", "reason": "qa_unavailable"}
    return result


def measure_lips(video: str, audio: str, offset: float, span: tuple[float, float] | None) -> dict[str, Any]:
    from services.lipsync_qa import measure
    return measure(video, audio, offset=offset, span=span)


def trim_span(audio: str, folder: str, start: float, end: float) -> str:
    import subprocess
    from services.production_media_common import available_name

    dest = os.path.join(folder, available_name(folder, "lipsync-audio.wav"))
    try:
        result = subprocess.run(
            ["ffmpeg", "-v", "error", "-nostdin", "-y", "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}",
             "-i", audio, "-vn", "-acodec", "pcm_s16le", dest],
            capture_output=True, check=False,
        )
    except OSError as exc:
        raise MediaToolError("audio_trim_failed", "ffmpeg could not cut the audio span.") from exc
    if result.returncode != 0 or not os.path.isfile(dest):
        raise MediaToolError("audio_trim_failed", "ffmpeg could not cut the audio span.")
    return dest


def start_download(model_type: str) -> dict[str, Any]:
    from services.model_downloads import download_model
    result = download_model(model_type)
    status = getattr(result, "status_code", None)
    if status is not None:
        raise MediaToolError("model_unavailable", "The model download could not start.", int(status))
    return result if isinstance(result, dict) else {"status": "downloading", "model_type": model_type}


def _weights(payload: dict, engine: str, gap: list[dict]) -> dict[str, Any]:
    total = sum(int(item["bytes"]) for item in gap)
    spec = ENGINES[engine]
    detail = {
        "model_type": spec["model_type"], "bytes": total, "files": gap,
        "license": spec["license"], "engine": engine,
    }
    if payload.get("confirm_download") is True:
        started = start_download(spec["model_type"])
        return {"status": "downloading", "bytes": total, "files": gap, "license": spec["license"],
                "engine": engine, "model_type": spec["model_type"], "download": started}
    raise MediaToolError(
        "model_unavailable", f"{engine} weights are not installed ({total} bytes on disk).", 409, extra=detail,
    )


def source_seconds(path: str) -> float:
    """Duration of a source take. The error stays a short sentence: ffprobe's text is not included."""
    import json
    import subprocess
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", path],
            capture_output=True, check=False, text=True,
        )
        duration = float((json.loads(result.stdout or "{}").get("format") or {}).get("duration"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        duration, result = 0.0, None
    if result is None or result.returncode != 0 or duration <= 0 or duration > 36000:
        raise MediaToolError("duration_unreadable", "The source video duration could not be read.")
    return duration


def _body(target: dict, workspace: str, guides: dict, folder: str) -> dict[str, Any]:
    from services.production_media_common import available_name
    spec = ENGINES[target["engine"]]
    token = _safe_token(target.get("shot") or Path(target["original_name"]).stem)
    span = guides["span"]
    seconds = source_seconds(guides["video"]) if span is None and target["kind"] in {"series", "clip"} else None
    body = {
        "workspace": workspace, "model_type": spec["model_type"], "prompt": PROMPT,
        "resolution": spec["resolution"], "num_inference_steps": spec["steps"],
        "guidance_scale": spec["guidance_scale"], "audio_guidance_scale": spec["audio_guidance_scale"],
        "video_prompt_type": spec["video_prompt_type"], "audio_prompt_type": "A",
        "video_guide": guides["video"], "audio_guide": guides["audio"],
        "sliding_window_size": spec["sliding_window_size"], "force_fps": str(int(spec["fps"])),
        "video_length": video_length(target["engine"], span, seconds=seconds),
        "output_name": available_name(folder, f"lipsync-{token}-{target['engine']}.mp4"),
    }
    if "denoising_strength" in spec:
        body["denoising_strength"] = spec["denoising_strength"]
    return body


def _server_queue(body: dict, folder: str) -> str:
    import services.studio_generate as studio
    if studio._new_generation_job is None or studio._jobs is None:
        raise MediaToolError(
            "generation_unavailable",
            "Lip redo needs the full generation server. The rest of the app is unchanged.", 503,
        )
    try:
        submitted = asyncio.run(studio.generate(_Request(body)))
    except Exception as exc:
        status = getattr(exc, "status_code", 502)
        detail = getattr(exc, "detail", None)
        raise MediaToolError("generation_failed", str(detail or exc), int(status) if isinstance(status, int) else 502) from exc
    job_id = submitted.get("job_id") if isinstance(submitted, dict) else None
    if not job_id:
        raise MediaToolError("generation_failed", "The generation server did not queue a job.", 502)
    job = _wait_job(studio._jobs, job_id)
    if job.get("status") != "completed":
        reason = job.get("error") or job.get("status") or "failed"
        raise MediaToolError("generation_failed", f"Generation failed: {reason}.", 502)
    files = job.get("output_files") or []
    if not files:
        raise MediaToolError("generation_failed", "Generation finished without a video.", 502)
    raw = str(files[-1])
    return raw if os.path.isabs(raw) else os.path.join(folder, raw)


def _wait_job(jobs: dict, job_id: str) -> dict:
    while True:
        job = jobs.get(job_id) if isinstance(jobs, dict) else None
        if not isinstance(job, dict):
            raise MediaToolError("generation_failed", "The generation job disappeared.", 502)
        if job.get("status") in {"completed", "failed", "cancelled"}:
            return job
        time.sleep(0.5)


def _adopt(folder: str, produced: str) -> str:
    real_folder = os.path.realpath(folder)
    real = os.path.realpath(produced)
    prefix = real_folder + os.sep
    video = os.path.splitext(real)[1].lower() in {".mp4", ".webm", ".mov"}
    if not real.startswith(prefix) or not os.path.isfile(real) or not video:
        raise MediaToolError("generation_failed", "The worker did not write a video in the workspace.", 502)
    return real


def _save(folder: str, workspace: str, target: dict, video: str, qa: dict) -> dict[str, Any]:
    kind, engine = target["kind"], target["engine"]
    if kind == "production":
        return save_production(folder, workspace, target, video, qa, engine)
    if kind == "series":
        return save_series(folder, workspace, target, video, qa, engine)
    return save_clip(folder, workspace, target, video, qa, engine)


def _clip_target(payload, folder, uploads, workspace, engine, span, offset) -> dict[str, Any]:
    if payload.get("source"):
        raise MediaToolError("invalid_command", "A clip target does not take source.")
    video = resolve_source(payload["clip"], workspace, folder, uploads, ("video",), "clip")
    if not payload.get("audio"):
        raise MediaToolError("audio_required", "Name the audio file for this clip.")
    audio = resolve_source(payload["audio"], workspace, folder, uploads, ("audio",), "audio")
    return _target("clip", engine, video, audio, span, offset, payload, False)


def _production_target(payload, folder, uploads, workspace, engine, span, offset) -> dict[str, Any]:
    production_id, shot_id = _token(payload.get("production_id"), "production_id"), _token(payload.get("shot"), "shot")
    path = os.path.join(folder, f"{production_id}.shots.json")
    body = _json_file(path)
    if body is None:
        raise MediaToolError("shot_not_found", "Production shots were not found.", 404)
    row = next((item for item in body.get("shots") or [] if isinstance(item, dict) and item.get("key") == shot_id), None)
    if row is None:
        raise MediaToolError("shot_not_found", "Production shot was not found.", 404)
    video = _video_file(payload, row.get("clip"), workspace, folder, uploads)
    audio = _named_audio(payload, workspace, folder, uploads) or _song_file(folder, production_id, workspace, uploads)
    if audio is None:
        raise MediaToolError("audio_required", "Name the audio file for this shot.")
    chosen = span if span is not None else _row_span(row)
    return _target("production", engine, video, audio, chosen, offset, payload, _locked(folder, production_id, shot_id, row))


def _series_target(payload, folder, uploads, workspace, engine, span, offset) -> dict[str, Any]:
    from services.series_library import read_series_library
    from services.shot_lipsync_save import _series_shot

    series_id = _text(payload.get("series_id"), "series_id")
    episode_id = _text(payload.get("episode_id"), "episode_id")
    shot_id = _token(payload.get("shot"), "shot")
    library = read_series_library(folder, workspace)
    _series, _episode, _index, shot = _series_shot(library, series_id, episode_id, shot_id)
    video = _video_file(payload, _series_clip(library, shot, series_id), workspace, folder, uploads)
    audio = _named_audio(payload, workspace, folder, uploads)
    placed = False
    if audio is None:
        audio, placed = _line_drive(episode_id, shot, folder), True
    return _target("series", engine, video, audio, span, offset, payload, shot.get("locked") is True, placed)


def _dict_rows(value: Any) -> list[dict]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _video_uri(assets: dict, attempt: dict) -> str | None:
    if attempt.get("status") != "completed":
        return None
    ids = attempt.get("outputAssetIds") if isinstance(attempt.get("outputAssetIds"), list) else []
    for asset_id in ids:
        asset = assets.get(asset_id) if isinstance(assets.get(asset_id), dict) else {}
        uri = asset.get("uri")
        if asset.get("kind") == "video" and isinstance(uri, str):
            return uri
    return None


def _series_clip(library: dict, shot: dict, series_id: str) -> str | None:
    projects = library.get("seriesById") if isinstance(library.get("seriesById"), dict) else {}
    series = projects.get(series_id) if isinstance(projects.get(series_id), dict) else {}
    assets = series.get("assets") if isinstance(series.get("assets"), dict) else {}
    attempts = _dict_rows(shot.get("attempts"))
    approved = shot.get("approvedAttemptId")
    preferred = [item for item in attempts if item.get("id") == approved]
    ordered = preferred if preferred else list(reversed(attempts))
    for attempt in ordered:
        uri = _video_uri(assets, attempt)
        if uri:
            return uri
    return None


def _spoken(shot: dict) -> list[dict]:
    beats = shot.get("dialogueBeats")
    if not isinstance(beats, list):
        return []
    return [beat for beat in beats if isinstance(beat, dict) and str(beat.get("text") or "").strip()]


def _recorded_line(folder: str, episode_id: str, beat_id: str) -> str | None:
    """The dry ``ln-<episode>-<beat>-<key>.wav``. A room copy is what the mix plays; the mouth uses the dry take.
    Several keys means the line was re-recorded: the newest file is the one the shot would reuse."""
    if not beat_id or "/" in beat_id or "\\" in beat_id:
        return None
    prefix = f"ln-{episode_id}-{beat_id}-"
    found: list[str] = []
    try:
        names = os.listdir(folder)
    except OSError:
        return None
    for name in names:
        if not name.startswith(prefix) or not name.endswith(".wav"):
            continue
        if ".room-" in name or "-raw" in name or ".best." in name or "-take" in name:
            continue
        found.append(os.path.join(folder, name))
    if not found:
        return None
    return max(found, key=lambda path: os.path.getmtime(path) if os.path.isfile(path) else 0)


def _line_drive(episode_id: str, shot: dict, folder: str) -> str:
    """The shot's recorded lines, each delayed to the start ``plan_timing`` gives them. The score cue is music."""
    beats = _spoken(shot)
    if not beats:
        raise MediaToolError("audio_required", "This shot has no recorded line. Name the audio file.")
    files, missing = [], []
    for number, beat in enumerate(beats, start=1):
        path = _recorded_line(folder, episode_id, str(beat.get("id") or ""))
        (files if path else missing).append(path or str(number))
    if missing:
        verb = "is" if len(missing) == 1 else "are"
        raise MediaToolError(
            "audio_required",
            f"Line {', '.join(missing)} of the shot {verb} not recorded. Name the audio file or record the line.",
        )
    from services.series_shot_extras import pauses, timing_args
    from services.series_shot_plan import plan_timing
    layout = shot.get("layout2d") if isinstance(shot.get("layout2d"), dict) else {}
    timing, _length = plan_timing([source_seconds(path) for path in files], **timing_args(layout), pauses=pauses(beats))
    return _place_lines(folder, [(start, path) for (start, _end), path in zip(timing, files)])


def _place_graph(starts: list[float]) -> str:
    parts, labels = [], []
    for index, start in enumerate(starts):
        delay = max(0, int(round(float(start) * 1000)))
        label = "out" if len(starts) == 1 else f"a{index}"
        parts.append(f"[{index}]adelay={delay}:all=1[{label}]")
        labels.append(f"[{label}]")
    if len(starts) == 1:
        return parts[0]
    return ";".join(parts) + f";{''.join(labels)}amix=inputs={len(starts)}:normalize=0:duration=longest[out]"


def _place_lines(folder: str, lines: list[tuple[float, str]]) -> str:
    import subprocess
    from services.production_media_common import available_name
    dest = os.path.join(folder, available_name(folder, "lipsync-audio.wav"))
    command = ["ffmpeg", "-v", "error", "-nostdin", "-y"]
    for _start, path in lines:
        command.extend(["-i", path])
    command.extend([
        "-filter_complex", _place_graph([start for start, _path in lines]),
        "-map", "[out]", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", dest,
    ])
    try:
        result = subprocess.run(command, capture_output=True, check=False)
    except OSError as exc:
        raise MediaToolError("audio_trim_failed", "ffmpeg could not place the line audio.") from exc
    if result.returncode != 0 or not os.path.isfile(dest):
        raise MediaToolError("audio_trim_failed", "ffmpeg could not place the line audio.")
    return dest


def _song_file(folder: str, production_id: str, workspace: str, uploads: str) -> str | None:
    import json
    path = os.path.join(folder, f"{production_id}.production.json")
    body = _json_file(path)
    song = body.get("song") if isinstance(body, dict) else None
    file_name = song.get("file") if isinstance(song, dict) else None
    if not isinstance(file_name, str) or not file_name:
        return None
    return resolve_source(file_name, workspace, folder, uploads, ("audio",), "audio")


def _video_file(payload, fallback, workspace, folder, uploads) -> str:
    name = payload.get("source") or fallback
    if not isinstance(name, str) or not name:
        raise MediaToolError("clip_not_found", "This shot has no video take to redo.", 404)
    return resolve_source(name, workspace, folder, uploads, ("video",), "source")


def _named_audio(payload, workspace, folder, uploads) -> str | None:
    if not payload.get("audio"):
        return None
    return resolve_source(payload["audio"], workspace, folder, uploads, ("audio",), "audio")


def _target(kind, engine, video, audio, span, offset, payload, locked, placed=False) -> dict[str, Any]:
    return {
        "kind": kind, "engine": engine, "video": video, "audio": audio, "span": span, "offset": offset,
        "locked": locked, "placed": placed, "original_name": os.path.basename(video),
        "shot": payload.get("shot"), "production_id": payload.get("production_id"),
        "series_id": payload.get("series_id"), "episode_id": payload.get("episode_id"),
    }


def _locked(folder: str, production_id: str, shot_id: str, row: dict) -> bool:
    from services.production_shot_review import load_review
    if row.get("locked") is True:
        return True
    body = load_review(folder, production_id)
    shots = body.get("shots") if isinstance(body, dict) else None
    item = shots.get(shot_id) if isinstance(shots, dict) else None
    return bool(isinstance(item, dict) and item.get("locked"))


def _row_span(row: dict) -> tuple[float, float] | None:
    start, end = row.get("start"), row.get("end")
    if isinstance(start, bool) or isinstance(end, bool):
        return None
    if isinstance(start, (int, float)) and isinstance(end, (int, float)) and 0 <= float(start) < float(end) <= 36000:
        return float(start), float(end)
    return None


def _json_file(path: str) -> dict | None:
    import json
    if not os.path.isfile(path):
        return None
    try:
        body = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MediaToolError("shots_unreadable", "The shot record could not be read.", 422) from exc
    return body if isinstance(body, dict) else None


def _one_target(payload: dict) -> None:
    modes = (
        bool(payload.get("series_id") or payload.get("episode_id")),
        bool(payload.get("production_id")),
        bool(payload.get("clip")),
    )
    if sum(modes) != 1:
        raise MediaToolError("invalid_command", "Name one target: a series shot, a production shot, or a clip.")
    if modes[0] and not (payload.get("series_id") and payload.get("episode_id") and payload.get("shot")):
        raise MediaToolError("invalid_command", "A series shot needs series_id, episode_id and shot.")
    if modes[1] and not payload.get("shot"):
        raise MediaToolError("invalid_command", "A production shot needs shot.")


def _engine(value: Any) -> str:
    if value not in ENGINES:
        raise MediaToolError(
            "invalid_command",
            "engine must be infinitetalk. longcat_avatar does not read the shot video "
            "(input_frames and image_start are unused), so it is not a lip redo engine.",
        )
    return str(value)


def _confirm_flag(payload: dict) -> None:
    if "confirm_download" in payload and payload["confirm_download"] not in (True, False):
        raise MediaToolError("invalid_command", "confirm_download must be true or false.")


def _span(value: Any) -> tuple[float, float] | None:
    if value is None:
        return None
    if not isinstance(value, list) or len(value) != 2:
        raise MediaToolError("invalid_command", "span must be [start, end] in seconds.")
    start, end = _number(value[0], "span"), _number(value[1], "span")
    if not start < end:
        raise MediaToolError("invalid_command", "span end must be after span start.")
    return start, end


def _number(value: Any, field: str) -> float:
    if value is None:
        return 0.0
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= float(value) <= 36000:
        raise MediaToolError("invalid_command", f"{field} must be a number from 0 to 36000.")
    return float(value)


def _token(value: Any, field: str) -> str:
    text = _text(value, field)
    if len(text) > _ID_MAX or any(char in text for char in "/\\"):
        raise MediaToolError("invalid_command", f"{field} must be a single name.")
    return text


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise MediaToolError("invalid_command", f"{field} is required.")
    return value


def _safe_token(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in "-_" else "-" for char in value).strip("-")
    return (safe or "shot")[:60]


class _Request:
    trusted_tool = OPERATION

    def __init__(self, body: dict) -> None:
        self._body = dict(body)

    async def json(self) -> dict:
        return dict(self._body)
