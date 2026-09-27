"""Shot board: where each montage clip comes from, its takes, and how to redo it.

A montage clip made by a generation keeps its full parameters in the sidecar
``<clip>.meta.json`` (prompt, seed, start image, model, resolution…). The board
reads that sidecar, so montages saved before this feature work unchanged. A
shot can be regenerated with the same parameters (optionally a new prompt or
seed) through the ordinary generation queue; the result arrives as a new take
that the user can select. Selecting a take swaps the clip media and keeps the
previous media as a take, so nothing is lost.
"""
from __future__ import annotations

import json
import re
import subprocess
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import quote

from services.montage_documents import MAX_TAKES, MontageError, MontageStore

PRIVATE_PARAMS = ("provider",)
PROMPT_MAX = 4000
RETIMED_NOTE = re.compile(r"^(?P<source>.+?\.(?:mp4|mov|webm|mkv)) slowed ")


def _file_url(name: str, workspace: str) -> str:
    return "/api/v1/file/" + quote(name) + "?workspace=" + quote(workspace, safe="")


@lru_cache(maxsize=2048)
def _probe_duration(path: str, _mtime: float) -> float:
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                             capture_output=True, text=True, timeout=20, check=True).stdout.strip()
        return float(out)
    except (OSError, subprocess.SubprocessError, ValueError):
        return 0.0


def media_duration(path: Path) -> float:
    try:
        return _probe_duration(str(path), path.stat().st_mtime)
    except OSError:
        return 0.0


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _generated_from(origin: dict[str, Any] | None, source: str) -> str:
    """The generated file behind a clip: itself, or the file a render copy was derived from."""
    origin = origin or {}
    if origin.get("kind") == "render":
        if origin.get("derivedFrom"):
            return str(origin["derivedFrom"])
        match = RETIMED_NOTE.match(str(origin.get("note") or ""))
        if match:
            return match.group("source")
    return Path(source.split("?")[0]).name


def _sidecar(root: Path, origin: dict[str, Any] | None, source: str) -> tuple[str, dict[str, Any] | None]:
    generated = _generated_from(origin, source)
    names = [str(origin["meta"])] if origin and origin.get("meta") else []
    names.append(Path(generated).with_suffix(".meta.json").name)
    for name in names:
        data = _read_json(root / Path(name).name)
        if data:
            return Path(name).name, data
    return "", None


def _regenerable_params(meta: dict[str, Any] | None) -> dict[str, Any] | None:
    params = ((meta or {}).get("generation") or {}).get("parameters")
    if not isinstance(params, dict) or not params.get("model_type") or not params.get("prompt"):
        return None
    return {key: value for key, value in params.items() if not key.startswith("_") and key not in PRIVATE_PARAMS}


def describe_origin(root: Path, workspace: str, origin: dict[str, Any] | None, source: str) -> dict[str, Any]:
    """Human-facing provenance of one clip or take."""
    info: dict[str, Any] = {"kind": (origin or {}).get("kind") or "upload"}
    for key in ("scene", "note", "productionId", "shotId", "takeId"):
        if origin and origin.get(key):
            info[key] = origin[key]
    sidecar, meta = _sidecar(root, origin, source)
    if not meta:
        info["canRegenerate"] = False
        return info
    params = _regenerable_params(meta) or {}
    generation = meta.get("generation") or {}
    start = params.get("image_start")
    info.update({
        "sidecar": sidecar,
        "generatedFrom": _generated_from(origin, source),
        "model": (generation.get("model") or {}).get("id") or params.get("model_type"),
        "prompt": params.get("prompt") or ((generation.get("prompts") or {}).get("effective")),
        "seed": params.get("seed"),
        "resolution": params.get("resolution"),
        "frames": params.get("video_length"),
        "capability": (meta.get("origin") or {}).get("capability"),
        "jobId": (meta.get("execution") or {}).get("job_id"),
        "canRegenerate": bool(params),
    })
    if isinstance(start, str) and start:
        name = Path(start).name
        info["startImage"] = {"name": name, "url": _file_url(name, workspace)}
    return info


def timeline_slots(clips: list[dict[str, Any]], duration_of: Callable[[dict[str, Any]], float]) -> list[tuple[float, float]]:
    """Start/end of each clip on the montage timeline (crossfades overlap the previous clip)."""
    slots = []
    cursor = 0.0
    for index, clip in enumerate(clips):
        length = max(0.0, (clip.get("trimEnd") or duration_of(clip)) - (clip.get("trimStart") or 0))
        start = cursor
        slots.append((round(start, 3), round(start + length, 3)))
        overlap = clip.get("transitionDuration") or 0 if clip.get("transition", "none") != "none" and index < len(clips) - 1 else 0
        cursor = start + length - min(overlap, length)
    return slots


class ShotBoard:
    """Reads and edits shots of a saved montage. Generation goes through ``submit``."""

    def __init__(self, store: MontageStore, *, workspace_dir: Callable[[str], str],
                 submit: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]] | None = None,
                 job_status: Callable[[str], dict[str, Any] | None] | None = None) -> None:
        self.store = store
        self.workspace_dir = workspace_dir
        self.submit = submit
        self.job_status = job_status

    def _root(self, workspace: str) -> Path:
        return Path(self.workspace_dir(workspace))

    # ---- reading -------------------------------------------------------
    def _resolve_pending(self, root: Path, take: dict[str, Any]) -> dict[str, Any]:
        job = take["pending"]["jobId"]
        for meta_path in root.glob("*.meta.json"):
            meta = _read_json(meta_path)
            if not meta or (meta.get("execution") or {}).get("job_id") != job:
                continue
            output = meta.get("output_filename") or (meta.get("asset") or {}).get("filename")
            if output and (root / output).is_file():
                return {**{k: v for k, v in take.items() if k != "pending"}, "source": output,
                        "origin": {"kind": "generation", "meta": meta_path.name}, "status": "completed"}
        status = (self.job_status(job) if self.job_status else None) or {}
        state = str(status.get("status") or "queued")
        return {**take, "status": "failed" if state in ("failed", "error", "cancelled") else state,
                **({"error": str(status.get("error"))[:300]} if status.get("error") else {})}

    def _take_view(self, root: Path, workspace: str, take: dict[str, Any]) -> dict[str, Any]:
        if "pending" in take:
            take = self._resolve_pending(root, take)
            if "source" not in take:
                return take
        return {**take, "status": take.get("status", "completed"), "url": _file_url(take["source"], workspace),
                "duration": round(media_duration(root / Path(take["source"]).name), 3),
                "provenance": describe_origin(root, workspace, take.get("origin"), take["source"])}

    def shots(self, workspace: str, file: str) -> dict[str, Any]:
        saved = self.store.get(workspace, file)
        montage = saved["montage"]
        root = self._root(workspace)
        clips = montage.get("clips") or []
        slots = timeline_slots(clips, lambda clip: media_duration(root / Path(clip["source"].split("?")[0]).name))
        shots = []
        for index, (clip, (start, end)) in enumerate(zip(clips, slots)):
            shots.append({
                "index": index, "id": clip["id"], "name": clip["name"], "start": start, "end": end,
                "source": clip["source"], "url": _file_url(Path(clip["source"]).name, workspace),
                "trimStart": clip.get("trimStart", 0), "trimEnd": clip.get("trimEnd", 0), "lyric": clip.get("lyric", ""),
                "provenance": describe_origin(root, workspace, clip.get("origin"), clip["source"]),
                "takes": [self._take_view(root, workspace, take) for take in clip.get("takes") or []],
            })
        return {"file": saved["file"], "workspace": workspace, "name": montage.get("name"),
                "revision": montage.get("revision", 1), "duration": slots[-1][1] if slots else 0, "shots": shots}

    # ---- editing -------------------------------------------------------
    @staticmethod
    def _clip(montage: dict[str, Any], clip_id: str) -> dict[str, Any]:
        matches = [clip for clip in montage.get("clips") or [] if clip.get("id") == clip_id]
        if not matches:
            raise MontageError("Clip not found in this montage", status=404, code="clip_not_found")
        if len(matches) > 1:
            raise MontageError("Clip ids are not unique in this montage", status=409, code="ambiguous_clip")
        return matches[0]

    def _save(self, workspace: str, file: str, montage: dict[str, Any], expected_revision: int) -> dict[str, Any]:
        document = {key: value for key, value in montage.items() if key not in ("revision", "updatedAt", "kind")}
        return self.store.save(workspace, document, file=file, expected_revision=expected_revision)

    def regeneration_params(self, workspace: str, file: str, clip_id: str, *, prompt: str | None = None,
                            seed: int | None = None) -> dict[str, Any]:
        montage = self.store.get(workspace, file)["montage"]
        clip = self._clip(montage, clip_id)
        root = self._root(workspace)
        _, meta = _sidecar(root, clip.get("origin"), clip["source"])
        params = _regenerable_params(meta)
        if not params:
            raise MontageError("This shot has no generation parameters to reuse", status=409, code="not_regenerable")
        start = params.get("image_start")
        if isinstance(start, str) and start and not (root / Path(start).name).is_file():
            raise MontageError("The start image of this shot is no longer in the workspace", status=409, code="missing_input")
        if prompt is not None:
            if not prompt.strip() or len(prompt) > PROMPT_MAX:
                raise MontageError(f"prompt must be 1-{PROMPT_MAX} characters")
            params["prompt"] = prompt.strip()
        previous = int(params.get("seed") or 0)
        params["seed"] = int(seed) if seed is not None else (previous + 7919) % 2_147_483_647
        params["workspace"] = workspace
        params["repeat_generation"] = 1
        return params

    async def regenerate(self, workspace: str, file: str, clip_id: str, *, intent_id: str, expected_revision: int,
                         prompt: str | None = None, seed: int | None = None) -> dict[str, Any]:
        if self.submit is None:
            raise MontageError("Generation is not available on this server", status=503, code="unavailable")
        params = self.regeneration_params(workspace, file, clip_id, prompt=prompt, seed=seed)
        current = self.store.get(workspace, file)["montage"]
        if current.get("revision", 1) != expected_revision:
            raise MontageError(f"Montage changed (revision {current.get('revision', 1)}); reload first",
                               status=409, code="revision_conflict")
        clip = self._clip(current, clip_id)
        if len(clip.get("takes") or []) >= MAX_TAKES:
            raise MontageError(f"A shot keeps at most {MAX_TAKES} takes; remove one first", status=409, code="too_many_takes")
        params["provenance"] = {"actor": "user", "capability": "generate", "command": {"command_id": intent_id}}
        receipt = await self.submit(params)
        job = (receipt or {}).get("job_id")
        if not job:
            raise MontageError(f"Generation was not queued: {(receipt or {}).get('error') or 'no job id'}",
                               status=409, code="not_queued")
        take = {"id": f"take-{job}", "pending": {"jobId": job, "intentId": intent_id},
                "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S"), "note": f"seed {params['seed']}"}
        clip["takes"] = [*(clip.get("takes") or []), take]
        saved = self._save(workspace, file, current, expected_revision)
        return {"jobId": job, "take": take, "revision": saved["revision"]}

    def select(self, workspace: str, file: str, clip_id: str, take_id: str, *, expected_revision: int,
               retime: bool = True) -> dict[str, Any]:
        montage = self.store.get(workspace, file)["montage"]
        clip = self._clip(montage, clip_id)
        root = self._root(workspace)
        takes = [self._take_view(root, workspace, take) if "pending" in take else take for take in clip.get("takes") or []]
        chosen = next((take for take in takes if take["id"] == take_id), None)
        if not chosen:
            raise MontageError("Take not found", status=404, code="take_not_found")
        if "source" not in chosen:
            raise MontageError("This take is not finished yet", status=409, code="take_pending")
        slot = (clip.get("trimEnd") or media_duration(root / Path(clip["source"]).name)) - (clip.get("trimStart") or 0)
        source, origin = chosen["source"], chosen.get("origin")
        available = media_duration(root / Path(source).name)
        if retime and available and slot and available + 0.05 < slot:
            source, origin = self._retimed(root, source, slot, available)
        previous = {"id": f"take-was-{int(time.time())}", "source": clip["source"], "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    **({"origin": clip["origin"]} if clip.get("origin") else {}), "note": "previous selection"}
        kept = [self._stored_take(take) for take in takes if take["id"] != take_id]
        clip["takes"] = [previous, *kept][:MAX_TAKES]
        clip["source"], clip["trimStart"] = source, 0
        clip["trimEnd"] = round(min(slot, media_duration(root / Path(source).name) or slot), 4)
        clip.pop("origin", None)
        if origin:
            clip["origin"] = origin
        saved = self._save(workspace, file, montage, expected_revision)
        return {"clip": clip_id, "source": source, "revision": saved["revision"]}

    @staticmethod
    def _stored_take(take: dict[str, Any]) -> dict[str, Any]:
        keep = ("id", "source", "origin", "createdAt", "note", "pending")
        return {key: take[key] for key in keep if key in take and not (key == "pending" and "source" in take)}

    @staticmethod
    def _retimed(root: Path, source: str, slot: float, available: float) -> tuple[str, dict[str, Any]]:
        factor = slot / max(0.1, available - 0.1)
        target = f"{Path(source).stem[:60]}_retimed{factor:.2f}x.mp4"
        if not (root / target).exists():
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(root / Path(source).name), "-an", "-vf",
                            f"setpts={factor:.4f}*PTS", "-c:v", "libx264", "-crf", "14", "-preset", "medium",
                            "-pix_fmt", "yuv420p", str(root / target)], check=True, timeout=600)
        return target, {"kind": "render", "derivedFrom": source, "note": f"{source} slowed {factor:.2f}x to cover its slot"}


__all__ = ["ShotBoard", "describe_origin", "media_duration", "timeline_slots"]
