"""Render every 2D shot of a Series Lab episode on the server ("Generate everything").

Until now an ``animation_2d`` take was made in a browser tab: speech per line,
scene, lip-sync, a WebCodecs recording and an upload. Closing the tab stopped
the batch. This job does the same on the server, one shot at a time, with
the tools an agent would call (run in process, see ``local_mcp``):

1. **Voices.** Each line is spoken with the character's voice for the
   series language (``voicesByLanguage``, else the default voice), trimmed
   of silence, checked with ``qa.speech`` (up to three takes when the
   transcript drifts) and analysed into phonetic mouth cues.
2. **Scene.** ``series_shot_plan`` plans framing, cast, timing, sound and
   cards; ``series_shot_bridge`` compiles the editable Video 2D document. A
   shot in a room (``series_voice_rooms``) plays a processed copy of each
   line, made beside the dry recording; timing and lip-sync stay the dry line's.
3. **Take.** The scene is saved, exported headlessly
   (``scenes.video2d.export``) and imported as a take of the shot, which
   can be approved automatically. A shot with ``foley`` first gets sound
   generated from its exported picture (``generation.sfx``, MMAudio) mixed
   under its own (``series_shot_foley``); without MMAudio it goes in as is.

State is saved per shot and stage, so a restart or a cancel resumes where it
stopped. A recording is keyed by text and voice and reused.
"""
from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import os
import subprocess
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

from services.audio_levels import gain_to, level_file
from services.audio_mix import track_source
from services.production_control import Cancelled
from services.production_resource_gate import ResourceUnavailable, guard_workspace_mcp
from services.series_jobs import SeriesJobStore
from services.series_language_versions import LANGUAGES, localized_view, missing_lines
from services.series_review import episode_mode
from services.series_review_gate import actionable_shots, assembly_blockers, render_passes, video_promotion
from services.series_scene_inputs import audio_content
from services.series_shot_bridge import measure_props, run_series_shot, with_pose_sizes
from services import series_shot3d
from services.series_plate_checks import location_plate_url
from services.series_shot_extras import fx_cues, pauses, sfx_tracks, timing_args
from services.series_sound_cuts import materialize_cuts
from services.series_video_foley import VIDEO_METHODS, pending_video_foley, shot_foley, sound_name, take_file, video_take, wants_video_foley
from services.series_shot_foley import MAX_VOLUME, extract_audio, file_digest, foley_keys, foley_seed, mix_under, normalize_foley, sfx_params
from services.series_document_card import DocumentCardError, document_plate
from services import series_hearing
from services.series_shot_plan import build_shot_spec, kit_ref, language_key, plan_timing, recording_key, sound_tracks, voice_for
from services.speech_text_es import line_notes, pronounce, qa_verdict
from services.series_take_inputs import INPUTS_VERSION, accepted_inputs, render_inputs, stale_shot_ids
from services.series_voice_rooms import RoomError, apply_room, roomed

KIND = "native"
STAGES = ("voices", "scene", "export", "foley", "import", "done")
ACTIVE = ("queued", "running", "cancelling")
MAX_TAKES = 3
# An export the server lost (interrupted by a restart, discarded, forgotten) is asked for again under a new intent.
EXPORT_RETRIES = 3
# A shot's foley is an extra: a generation that has not finished after this long is left out of the take.
FOLEY_WAIT_SECONDS = 1800.0
INTERRUPTED = "The server restarted during this render; resume to continue"
MAX_WER = 0.34
# A take shorter than this (per word, with a floor) is a voice that stopped before speaking, not a line.
MIN_SECONDS_PER_WORD, MIN_LINE_SECONDS = 0.1, 0.25
SPEECH_CODES = {"english": "en", "spanish": "es", "french": "fr", "german": "de", "italian": "it", "portuguese": "pt",
                "japanese": "ja", "korean": "ko", "chinese": "cmn", "russian": "ru"}


class NativeRenderError(RuntimeError):
    def __init__(self, code: str, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.code, self.status = code, status


def audio_seconds(path: str) -> float:
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                           capture_output=True, text=True, check=True, timeout=30)
    return float(probe.stdout.strip())


def trim_silence(source: str, target: str, pad: float = 0.06) -> float:
    """Cut leading and trailing silence, keep a short natural pad; returns the new duration."""
    flt = (f"silenceremove=start_periods=1:start_threshold=-42dB:start_silence={pad},areverse,"
           f"silenceremove=start_periods=1:start_threshold=-42dB:start_silence={pad + 0.06},areverse")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", source, "-af", flt, "-ar", "44100", "-ac", "1", target],
                   check=True, timeout=120)
    return audio_seconds(target)


def shortest_line(text: str) -> float:
    """The shortest plausible recording of ``text``; anything shorter is silence, a click or a cut-off take."""
    return max(MIN_LINE_SECONDS, MIN_SECONDS_PER_WORD * len(text.split()))


@dataclass
class NativeRenderDeps:
    call: Callable[[str, dict], dict]
    workspace_dir: Callable[[str], str]
    read_library: Callable[[str], dict]
    read_kits: Callable[[str], dict]
    compile_shot: Callable[[dict], dict] = run_series_shot
    trim: Callable[[str, str], float] = trim_silence
    probe: Callable[[str], float] = audio_seconds
    # Lines are levelled to the dialogue loudness; music and effects volumes are scaled by their own loudness.
    level: Callable[[str], float] = level_file
    loudness_gain: Callable[[str], float] = gain_to
    # The copy of a recorded line in a room: (workspace folder, file name, preset) -> file name.
    room: Callable[[str, str, str], str] = apply_room
    sleep: Callable[[float], None] = time.sleep
    poll_seconds: float = 3.0
    check_speech: bool = True
    # Sets shot.durationSeconds to the rendered length; a take shorter than its shot is refused on import.
    set_shot_duration: Callable[[str, str, str, str, float], None] | None = None
    # Approves a take in a language version: (workspace, series, episode, language, shot, attempt).
    set_version_take: Callable[[str, str, str, str, str, str], None] | None = None
    set_version_duration: Callable[[str, str, str, str, str, float], None] | None = None
    # Foley (``shot.foley``): the generated clip's sound as a WAV, then that sound under the take (take, foley, target, gain).
    extract_audio: Callable[[str, str], None] = extract_audio
    mix_foley: Callable[[str, str, str, float], None] = mix_under
    foley_wait_seconds: float = FOLEY_WAIT_SECONDS
    clock: Callable[[], float] = time.monotonic
    extra: dict[str, Any] = field(default_factory=dict)


def _discard(path: str) -> None:
    """Remove a generated file and its ``.meta.json`` sidecar; a missing file is fine."""
    stem = os.path.splitext(path)[0]
    for item in (path, f"{stem}.meta.json"):
        try:
            os.remove(item)
        except OSError:
            pass


def _sidecar(path: str) -> str:
    return f"{os.path.splitext(path)[0]}.meta.json"


def _carry_sidecar(raw: str, trimmed: str) -> None:
    """The trimmed line keeps the raw take's provenance (text, voice, model, seed) so the gallery can show and redo it."""
    try:
        with open(_sidecar(raw), encoding="utf-8") as handle:
            sidecar = json.load(handle)
    except (OSError, ValueError):
        return
    if not isinstance(sidecar, dict):
        return
    name = os.path.basename(trimmed)
    asset = sidecar.get("asset") if isinstance(sidecar.get("asset"), dict) else {}
    media = asset.get("media") if isinstance(asset.get("media"), dict) else {}
    try:
        media["size_bytes"] = os.path.getsize(trimmed)
    except OSError:
        pass
    sidecar["asset"] = {**asset, "filename": name, "uri": name, "media": media}
    sidecar["output_filename"] = name
    lineage = sidecar.get("lineage") if isinstance(sidecar.get("lineage"), dict) else {}
    lineage["transformations"] = [*(lineage.get("transformations") or []), {"kind": "trim", "from": os.path.basename(raw)}]
    sidecar["lineage"] = lineage
    temporary = f"{_sidecar(trimmed)}.tmp"
    try:
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(sidecar, handle, ensure_ascii=False)
        os.replace(temporary, _sidecar(trimmed))
    except OSError:
        with contextlib.suppress(OSError):
            os.remove(temporary)


def _replace_with_sidecar(source: str, target: str) -> None:
    os.replace(source, target)
    if os.path.isfile(_sidecar(source)):
        os.replace(_sidecar(source), _sidecar(target))
    else:
        with contextlib.suppress(OSError):
            os.remove(_sidecar(target))


def _ok(result: dict, label: str) -> dict:
    if not isinstance(result, dict) or result.get("_is_error") or result.get("status") == "failed":
        error = (result or {}).get("error") if isinstance(result, dict) else None
        message = error.get("message") if isinstance(error, dict) else json.dumps(result)[:300]
        raise NativeRenderError("tool_failed", f"{label}: {message}", 502)
    return result


def _job_id(result: dict) -> str | None:
    receipt = result.get("receipt") if isinstance(result.get("receipt"), dict) else result
    value = (receipt.get("result") or {}) if isinstance(receipt, dict) else {}
    return value.get("job_id") or (value.get("task") or {}).get("job_id") or result.get("job_id")


def _output_file(status: dict, suffixes: tuple[str, ...]) -> str | None:
    for item in status.get("outputs") or status.get("output_files") or []:
        name = item.get("path") if isinstance(item, dict) else item
        if isinstance(name, str) and name.lower().endswith(suffixes):
            return os.path.basename(name)
    path = status.get("path")
    return os.path.basename(path) if isinstance(path, str) and path.lower().endswith(suffixes) else None


def _renders(shot: dict[str, Any], episode: dict) -> bool:
    """An animation to render, or a video take to promote or give foley."""
    return series_shot3d.wants_render(shot) or wants_video_foley(shot) or bool(video_promotion(episode, shot))


def _drawn(shots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The shots the render draws and voices; a video take only gets its foley (its lines are in the clip)."""
    return [shot for shot in shots if shot.get("productionMethod") not in VIDEO_METHODS]


def speech_params(voice: dict[str, Any], text: str, language: str, seed: int) -> dict[str, Any]:
    """Generation params for one line in one character voice (reference clone or preset)."""
    seconds = min(30, max(4, round(len(text.split()) * 0.6 + 3)))
    # The speech schema requires a resolution even for audio; it does not change the output.
    params: dict[str, Any] = {"prompt": text, "model_type": voice["model"], "seed": seed, "duration_seconds": seconds, "priority": 10,
                              "resolution": "1280x720"}
    if voice.get("model") == "qwen3_tts_base":
        params.update({"model_mode": voice.get("language") or language, "audio_prompt_type": "A",
                       "audio_guide": voice["referenceAudio"], "alt_prompt": voice.get("transcript") or ""})
    elif voice.get("voiceId"):
        params.update({"model_mode": voice["voiceId"], "alt_prompt": voice.get("instructions") or ""})
    return params


class SeriesNativeRender:
    def __init__(self, deps: NativeRenderDeps) -> None:
        self._threads: dict[str, threading.Thread] = {}
        self._cancel: set[str] = set()
        self._lock = threading.Lock()
        self.deps = replace(deps, call=guard_workspace_mcp(deps.call, deps.workspace_dir, cancelled=self._worker_cancelled))

    # Job lifecycle -------------------------------------------------------

    def _store(self, workspace: str) -> SeriesJobStore:
        return SeriesJobStore(self.deps.workspace_dir(workspace), KIND)

    def _episode(self, workspace: str, series_id: str, episode_id: str, language: str | None = None) -> tuple[dict, dict]:
        series = (self.deps.read_library(workspace).get("seriesById") or {}).get(series_id)
        episode = (series or {}).get("episodesById", {}).get(episode_id)
        if not series or not episode:
            raise NativeRenderError("not_found", "Series episode not found", 404)
        try:
            return localized_view(series, episode, language)
        except ValueError as error:
            raise NativeRenderError("no_version", str(error), 404) from error

    def _check_language(self, series: dict, episode: dict, language: str | None, shot_ids: set[str]) -> str:
        original = language_key(series)
        if not language or language == original:
            return original
        if language not in LANGUAGES:
            raise NativeRenderError("invalid_language", f"Unknown language {language}", 400)
        missing = missing_lines(episode, language, shot_ids)
        if missing:
            raise NativeRenderError("untranslated", f"{len(missing)} lines have no {language} text yet; translate the version first", 409)
        return language

    def start(self, workspace: str, series_id: str, episode_id: str, *, shot_ids: list[str] | None = None,
              approve: bool = False, language: str | None = None, changed: bool = False) -> dict[str, Any]:
        """``changed`` renders only the shots that need it (``stale_shots``: no up-to-date approved take, and what the
        episode's review lets through), as ``produce`` does; ``shot_ids`` narrows them."""
        explicit = bool(shot_ids) and not changed
        if changed:
            shot_ids = [shot_id for shot_id in self.stale_shots(workspace, series_id, episode_id, language)
                        if not shot_ids or shot_id in shot_ids]
            if not shot_ids:
                raise NativeRenderError("up_to_date", "Every shot already has an up-to-date approved take", 409)
        raw_series, language, planned, review = self._preflight(workspace, series_id, episode_id, shot_ids, language, explicit)
        for job in self.jobs(workspace):
            if job.get("episodeId") == episode_id and job.get("language") == language and job.get("status") in ACTIVE:
                raise NativeRenderError("already_running", "This episode is already rendering on the server")
        job_id = f"native-{uuid.uuid4().hex[:12]}"
        job = {"jobId": job_id, "workspace": workspace, "seriesId": series_id, "episodeId": episode_id, "status": "queued",
               "approve": bool(approve), "language": language, "original": language == language_key(raw_series),
               "current": 0, "total": len(planned),
               "items": [{"shotId": item["shot"]["id"], "stage": "voices", "status": "queued", "lines": {},
                          **({"pass": item["pass"]} if item["pass"] else {}),
                          **({"attemptId": item["attemptId"]} if item.get("attemptId") else {})} for item in planned],
               **review, "createdAt": time.time(), "message": "Queued"}
        self._launch(workspace, job)
        return job

    def _preflight(self, workspace: str, series_id: str, episode_id: str, shot_ids: list[str] | None,
                   language: str | None, explicit: bool = False) -> tuple[dict[str, Any], str, list[dict[str, Any]], dict[str, Any]]:
        """The series, the language, the shots to render with their review pass, and the episode's review mode and
        the shots that wait for an approval (``series_review_gate``); refuses what would fail later."""
        raw_series, raw_episode = self._episode(workspace, series_id, episode_id)
        wanted = {shot["id"] for shot in raw_episode.get("shots") or [] if _renders(shot, raw_episode) and (not shot_ids or shot["id"] in shot_ids)}
        if not wanted:
            raise NativeRenderError("no_2d_shots", "The episode has no 2D shots (or 3D shots with scene3d) to render", 400)
        language = self._check_language(raw_series, raw_episode, language, wanted)
        series, episode = self._episode(workspace, series_id, episode_id, language)
        planned, review = self._review_passes(workspace, series, episode, wanted, explicit, language == language_key(raw_series))
        shots = [item["shot"] for item in planned if item.get("pass") != "promote"]
        missing = self._missing_kits(workspace, series, shots)
        if missing:
            raise NativeRenderError("missing_kits", f"Make a Character Kit for {', '.join(missing)} before rendering", 400)
        voiceless = self._missing_voices(workspace, series, shots, language, language_key(raw_series))
        if voiceless:
            raise NativeRenderError("no_voice", f"{', '.join(voiceless)} have no {language} voice (voicesByLanguage); "
                                    f"design one before rendering this version", 400)
        return raw_series, language, planned, review

    def _review_passes(self, workspace: str, series: dict, episode: dict, wanted: set[str], explicit: bool,
                       original: bool) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """What the episode's staged review lets this render do (``series_review_gate``); direct episodes render all."""
        mode = episode_mode(episode)
        shots = sorted((shot for shot in episode.get("shots") or [] if shot["id"] in wanted), key=lambda shot: shot.get("order", 0))
        if mode == "direct":
            return [{"shot": shot, "pass": None} for shot in shots], {}
        kits = self.deps.read_kits(workspace)
        root = self.deps.workspace_dir(workspace)
        planned, waiting = render_passes(series, episode, shots, lambda shot: accepted_inputs(series, shot, kits, root),
                                         explicit=explicit, original=original)
        if not planned:
            if waiting:
                raise NativeRenderError("awaiting_review", f"{len(waiting)} shots wait for an approval in this episode's "
                                        f"{mode} review ({_reasons(waiting)}); approve them in Series Lab or with "
                                        "series.shot.review.set", 409)
            raise NativeRenderError("up_to_date", "Every shot asked for already has its approved final take", 409)
        return planned, {"mode": mode, "waiting": waiting}

    def _missing_voices(self, workspace: str, series: dict[str, Any], shots: list[dict[str, Any]], language: str, original: str) -> list[str]:
        """Speakers of a language version whose kit has no voice designed for that language (the default would be the wrong accent)."""
        if language == original:
            return []
        shots = _drawn(shots)
        kits = self.deps.read_kits(workspace)
        names = {item.get("id"): item.get("name") or item.get("id") for item in series.get("characters") or []}
        speakers = dict.fromkeys(beat.get("characterId") for shot in shots for beat in shot.get("dialogueBeats") or []
                                 if str(beat.get("text") or "").strip() and beat.get("characterId"))
        return [str(names.get(cid, cid)) for cid in speakers
                if not ((kits.get((kit_ref(series, cid) or {}).get("id") or "") or {}).get("voicesByLanguage") or {}).get(language)]

    def _missing_kits(self, workspace: str, series: dict[str, Any], shots: list[dict[str, Any]]) -> list[str]:
        """Names of characters seen or heard in ``shots`` without a Character Kit in the workspace (a new template's cast)."""
        shots = _drawn(shots)
        kits = self.deps.read_kits(workspace)
        names = {item.get("id"): item.get("name") or item.get("id") for item in series.get("characters") or []}
        ids = dict.fromkeys(cid for shot in shots for cid in [*(shot.get("visibleCharacterIds") or []),
                                                              *(beat.get("characterId") for beat in shot.get("dialogueBeats") or [])] if cid)
        return [str(names.get(cid, cid)) for cid in ids if (kit_ref(series, cid) or {}).get("id") not in kits]

    def _launch(self, workspace: str, job: dict) -> None:
        """Save the job and run it on a thread; the thread is registered before the save so a reader never sees an orphan."""
        job_id = job["jobId"]
        with self._lock:
            running = self._threads.get(job_id)
            if running and running.is_alive():
                return
            self._cancel.discard(job_id)
            thread = threading.Thread(target=self._run, args=(workspace, job_id), name=f"series-native-{job_id}", daemon=True)
            self._threads[job_id] = thread
        self._store(workspace).save(job)
        thread.start()

    def _reconcile(self, workspace: str, job: dict) -> dict:
        """A job that says it is running without a live thread here was cut by a restart: it is interrupted, once."""
        if job.get("status") not in ACTIVE:
            return job
        thread = self._threads.get(job["jobId"])
        if thread is not None and (thread.ident is None or thread.is_alive()):
            return job
        if thread is not None:
            # It ran here and has ended: its own last save is the job's state. ``job`` may have been read while it ran,
            # and marking that copy interrupted overwrote a finished job (a test failed now and then on it).
            stored = self._store(workspace).load(job["jobId"]) or job
            if stored.get("status") not in ACTIVE:
                return stored
            job = stored
        for item in job.get("items") or []:
            if item.get("status") == "running":
                item["status"] = "queued"
        job.update(status="interrupted", message=INTERRUPTED, finishedAt=time.time())
        self._store(workspace).save(job)
        return job

    def stale_shots(self, workspace: str, series_id: str, episode_id: str, language: str | None = None) -> list[str]:
        """Shots to render in ``language``: no approved take yet, or one made from other inputs (see ``render_inputs``),
        that the episode's staged review lets through; in preview mode also those that need a preview, a final or a
        promotion (``series_review_gate.actionable_shots``)."""
        raw_series, _raw_episode = self._episode(workspace, series_id, episode_id)
        original = (language or language_key(raw_series)) == language_key(raw_series)
        series, episode = self._episode(workspace, series_id, episode_id, language or language_key(raw_series))
        kits = self.deps.read_kits(workspace)
        shots = sorted((shot for shot in episode.get("shots") or [] if _renders(shot, episode)), key=lambda shot: shot.get("order", 0))
        root = self.deps.workspace_dir(workspace)
        stale = stale_shot_ids(series, episode, kits, root)
        stale.extend(shot["id"] for shot in shots if video_promotion(episode, shot) or pending_video_foley(series, episode, shot, root))
        return actionable_shots(series, episode, shots, lambda shot: accepted_inputs(series, shot, kits, root),
                                stale, original=original)

    def review_blockers(self, workspace: str, series_id: str, episode_id: str, language: str | None = None) -> list[dict[str, Any]]:
        """Shots a staged review still holds the cut of ``language`` for (``series_review_gate.assembly_blockers``)."""
        raw_series, raw_episode = self._episode(workspace, series_id, episode_id)
        return assembly_blockers(raw_episode, original=(language or language_key(raw_series)) == language_key(raw_series))

    def jobs(self, workspace: str) -> list[dict[str, Any]]:
        return [self._reconcile(workspace, job) for job in self._store(workspace).list()]

    def status(self, workspace: str, job_id: str) -> dict[str, Any]:
        job = self._store(workspace).load(job_id)
        if not job:
            raise NativeRenderError("not_found", "Render job not found", 404)
        return self._reconcile(workspace, job)

    def cancel(self, workspace: str, job_id: str) -> dict[str, Any]:
        job = self.status(workspace, job_id)
        with self._lock:
            self._cancel.add(job_id)
        if job["status"] in ("queued", "running"):
            job.update(status="cancelling", message="Stopping after the current step")
            self._store(workspace).save(job)
        return job

    def resume(self, workspace: str, job_id: str) -> dict[str, Any]:
        job = self.status(workspace, job_id)
        if job["status"] in ACTIVE:
            return job
        for item in job["items"]:
            if item["status"] != "done":
                item.update(status="queued", error=None)
            if item["stage"] == "export":
                # A failed export retries only when submitted again; the compile is deterministic, so the
                # scene stage rebuilds the same document and replays the same export intent.
                item["stage"] = "scene"
        job.update(status="queued", message="Resuming", error=None)
        self._launch(workspace, job)
        return job

    # Worker --------------------------------------------------------------

    def _save(self, workspace: str, job: dict, **patch: Any) -> None:
        job.update(patch)
        self._store(workspace).save(job)

    def _cancelled(self, job_id: str) -> bool:
        with self._lock:
            return job_id in self._cancel

    def _worker_cancelled(self) -> bool:
        """Whether the job whose worker thread is calling was asked to stop; a wait for the GPU polls it."""
        current = threading.current_thread()
        with self._lock:
            return any(thread is current and job_id in self._cancel for job_id, thread in self._threads.items())

    def _run(self, workspace: str, job_id: str) -> None:
        job = self.status(workspace, job_id)
        self._save(workspace, job, status="running", message="Rendering")
        failed = 0
        for index, item in enumerate(job["items"]):
            if item["status"] == "done":
                continue
            if self._cancelled(job_id):
                self._save(workspace, job, status="cancelled", message="Cancelled; resume to continue")
                return
            self._save(workspace, job, current=index, activeShotId=item["shotId"], message=f"Shot {item['shotId']}")
            try:
                self._render_shot(workspace, job, item, index)
                item.update(status="done", stage="done", error=None)
            except Exception as error:  # one shot must not stop the episode
                failed += 1
                item.update(status="failed", error=f"{type(error).__name__}: {error}"[:500])
                if self._cancelled(job_id) or isinstance(error, ResourceUnavailable):
                    # A cancel, or a disk or GPU the next shot would wait for too: stop here, resumable.
                    self._stop(workspace, job, item, error)
                    return
            self._save(workspace, job)
        done = sum(1 for item in job["items"] if item["status"] == "done")
        self._save(workspace, job, current=len(job["items"]), activeShotId=None, finishedAt=time.time(),
                   status="completed" if not failed else "failed",
                   message=f"{done} of {len(job['items'])} shots rendered" + (f"; {failed} failed, resume to retry" if failed else ""))

    def _stop(self, workspace: str, job: dict, item: dict, error: Exception) -> None:
        if self._cancelled(job["jobId"]):
            self._save(workspace, job, status="cancelled", message="Cancelled; resume to continue")
            return
        self._save(workspace, job, activeShotId=None, finishedAt=time.time(), status="failed",
                   message=f"Stopped at shot {item['shotId']}: {error}"[:300])

    def _render_item(self, workspace: str, job: dict, item: dict, index: int) -> None:
        series, episode = self._episode(workspace, job["seriesId"], job["episodeId"], job["language"])
        shot = next((value for value in episode.get("shots") or [] if value["id"] == item["shotId"]), None)
        if shot is None:
            raise NativeRenderError("not_found", f"Shot {item['shotId']} no longer exists", 404)
        kits = self.deps.read_kits(workspace)
        item["status"] = "running"
        if item["stage"] in ("voices", "scene"):
            # Recorded lines are reused; a resume after a restart (or after a cleanup) only records what is missing.
            self._voices(workspace, job, item, series, shot, kits)
            item["stage"] = "scene"
            self._save(workspace, job)
        three_d = shot.get("productionMethod") == "animation_3d"
        for _attempt in range(EXPORT_RETRIES + 1):
            if item["stage"] == "scene":
                item["inputs"] = render_inputs(series, shot, kits, self.deps.workspace_dir(workspace))
                if three_d:
                    self._scene3d(workspace, job, item, series, episode, shot, kits)
                else:
                    self._scene(workspace, job, item, series, episode, shot, kits, index)
            if item["stage"] != "export" or self._export(workspace, job, item):
                break
            # The export was lost (interrupted, discarded or forgotten by the server): the scene stage asks again
            # with a new intent instead of waiting for a state that cannot come.
        else:
            raise NativeRenderError("export_failed", f"The export was lost {EXPORT_RETRIES + 1} times", 502)
        if item["stage"] == "foley":
            self._foley(workspace, job, item, shot)
        if item["stage"] == "import":
            self._import(workspace, job, item, "animation_3d" if three_d else "animation_2d")

    @staticmethod
    def line_voice(series: dict, beat: dict, kits: dict, language: str) -> tuple[str, dict, str]:
        """A line's text, its character's voice in ``language`` and the key its recording is named by."""
        text = str(beat.get("text") or "").strip()
        ref = kit_ref(series, beat.get("characterId", ""))
        kit = kits.get(ref["id"]) if ref else None
        voice = voice_for(kit, language) if kit else None
        if not voice:
            raise NativeRenderError("no_voice", f"{beat.get('characterId')} has no voice for {language}")
        return text, line_notes(series, beat, voice), recording_key(text, voice)

    def record_line(self, workspace: str, job: dict, series: dict, beat: dict, kits: dict, *, retake: bool = False) -> dict[str, Any]:
        """One line as ``_voices`` records it (``series_line_voice``): its recording when there is one, else a new one.
        ``retake`` records another take under its own name (so another seed) and replaces the recording only once
        that take is good: a failed retake leaves the old recording. The next render of the shot reuses it."""
        text, voice, key = self.line_voice(series, beat, kits, job["language"])
        if not retake:
            return self._reuse(workspace, job, beat["id"], text, key) or self._record(workspace, job, beat["id"], text, voice, key)
        stem, root = self._stem(job, beat["id"], key), self.deps.workspace_dir(workspace)
        take = self._record(workspace, job, beat["id"], text, voice, key, stem=f"{stem[:130]}-take{uuid.uuid4().hex[:6]}")
        _replace_with_sidecar(os.path.join(root, take["filename"]), os.path.join(root, f"{stem}.wav"))
        return {**take, "filename": f"{stem}.wav", "retake": True}

    def _voices(self, workspace: str, job: dict, item: dict, series: dict, shot: dict, kits: dict) -> None:
        for beat in shot.get("dialogueBeats") or []:
            if not str(beat.get("text") or "").strip():
                continue
            text, voice, key = self.line_voice(series, beat, kits, job["language"])
            done = item["lines"].get(beat["id"])
            current = audio_content(self.deps.workspace_dir(workspace), [done["filename"]]) if done else {}
            if done and done.get("key") == key and done.get("audioDigest") == current.get(done["filename"]) != "unavailable":
                continue
            item["lines"][beat["id"]] = self._reuse(workspace, job, beat["id"], text, key) or self._record(workspace, job, beat["id"], text, voice, key)
            self._save(workspace, job)
            if self._cancelled(job["jobId"]):
                raise NativeRenderError("cancelled", "Cancelled")

    @staticmethod
    def recording_stem(episode_id: str, beat_id: str, key: str) -> str:
        """The file name (without ``.wav``) a line's recording is kept under, reused by every render of it."""
        return f"ln-{episode_id}-{beat_id}-{key}"[:150]

    @classmethod
    def _stem(cls, job: dict, beat_id: str, key: str) -> str:
        return cls.recording_stem(job["episodeId"], beat_id, key)

    def _reuse(self, workspace: str, job: dict, beat_id: str, text: str, key: str) -> dict[str, Any] | None:
        """The recording an earlier render made of the same line in the same voice (its file name says so)."""
        filename = f"{self._stem(job, beat_id, key)}.wav"
        path = os.path.join(self.deps.workspace_dir(workspace), filename)
        if not os.path.isfile(path):
            return None
        try:
            duration = self.deps.probe(path)
        except (OSError, ValueError, subprocess.SubprocessError):
            return None
        if duration < shortest_line(text):
            return None  # an empty take an older render kept: record it again
        self.deps.level(path)
        cues = self._cues(workspace, filename, duration, text, job["language"])
        return {"key": key, "filename": filename, "duration": round(duration, 3), "wer": None, "attempt": 0,
                "reused": True, "audioDigest": file_digest(path), **cues}

    def _record(self, workspace: str, job: dict, beat_id: str, text: str, voice: dict, key: str, stem: str | None = None) -> dict[str, Any]:
        root = self.deps.workspace_dir(workspace)
        stem = stem or self._stem(job, beat_id, key)
        final, best_path = os.path.join(root, f"{stem}.wav"), os.path.join(root, f"{stem}.best.wav")
        best: dict[str, Any] | None = None
        try:
            for attempt in range(MAX_TAKES):
                raw = self._speak(workspace, job, stem, text, voice, attempt)
                try:
                    duration = self._trim(os.path.join(root, raw), final)
                    if duration:
                        _carry_sidecar(os.path.join(root, raw), final)
                finally:
                    _discard(os.path.join(root, raw))  # the trimmed take is the recording; the raw one is an intermediate
                if duration < shortest_line(text):
                    # The voice stopped before speaking (only silence, or a click the trim kept): another seed.
                    _discard(final)
                    continue
                wer, limit, notes = self._wer(workspace, f"{stem}.wav", text, job["language"], voice)
                take = {"key": key, "filename": f"{stem}.wav", "duration": round(duration, 3), "wer": wer,
                        "attempt": attempt, **notes}
                if best is None or (wer is not None and (best["wer"] is None or wer < best["wer"])):
                    best = take
                    _replace_with_sidecar(final, best_path)
                if wer is None or wer <= limit:
                    break
        finally:
            # The best take so far becomes the recording even when a later attempt fails, so a resume reuses it.
            if os.path.isfile(best_path):
                _replace_with_sidecar(best_path, final)
        if best is None:
            raise NativeRenderError("speech_empty", f"The voice gave no speech for «{text}» in {MAX_TAKES} takes; "
                                    "try another reference voice or reword the line", 502)
        self.deps.level(final)
        cues = self._cues(workspace, best["filename"], best["duration"], text, job["language"])
        return {**best, **cues, "audioDigest": file_digest(final)}

    def _trim(self, raw: str, final: str) -> float:
        """The trimmed take's length; 0 when nothing was left (ffprobe has no duration for an empty file)."""
        try:
            return self.deps.trim(raw, final)
        except (OSError, ValueError, subprocess.SubprocessError):
            return 0.0

    def _speak(self, workspace: str, job: dict, stem: str, text: str, voice: dict, attempt: int) -> str:
        seed = int(hashlib.sha1(f"{stem}-{attempt}".encode()).hexdigest()[:6], 16)
        text = pronounce(text, voice.get("pronunciationDictionary"))
        intent = f"{stem}-a{attempt}"
        for _ in range(2):
            submitted = _ok(self.deps.call("generation.speech", {"version": 2, "intent_id": intent[:160], "input": {
                "workspace": workspace, "output_name": f"{stem}-raw{attempt}", "params": speech_params(voice, text, job["language"], seed)}}), "speech")
            job_id = _job_id(submitted)
            if not job_id:
                raise NativeRenderError("tool_failed", "Speech generation returned no job id", 502)
            name = self._wait_speech(job, job_id)
            if name:
                return name
            # The intent replayed a job the server no longer knows (it restarted mid-generation): ask again.
            intent = f"{stem}-a{attempt}-{uuid.uuid4().hex[:6]}"
        raise NativeRenderError("tool_failed", "Speech job disappeared twice", 502)

    def _wait_speech(self, job: dict, job_id: str) -> str | None:
        """The audio file of a finished speech job; None when the server does not know the job."""
        return self._wait_output(job, job_id, "Speech", (".wav", ".mp3", ".flac"), "an audio file")

    def _wait_output(self, job: dict, job_id: str, label: str, suffixes: tuple[str, ...], what: str,
                     deadline: float | None = None) -> str | None:
        """The output file of a finished generation job; None when the server does not know the job. With a
        ``deadline`` (``deps.clock``), a job still running then is given up on."""
        while True:
            timeout = 120 if deadline is None else max(1, min(120, round(deadline - self.deps.clock())))
            waited = self.deps.call("jobs.wait", {"version": 1, "input": {"job_id": job_id, "timeout_s": timeout}})
            error = waited.get("error") if isinstance(waited.get("error"), dict) else {}
            if waited.get("_is_error") and not error.get("job_id"):
                if error.get("status") == 404 or "not found" in str(error.get("message") or "").lower():
                    return None
                raise NativeRenderError("tool_failed", f"Waiting for {label.lower()}: {error.get('message') or waited}"[:300], 502)
            payload = error if error.get("job_id") else waited
            state = payload.get("status")
            if state == "completed":
                name = _output_file(payload, suffixes)
                if not name:
                    raise NativeRenderError("tool_failed", f"{label} finished without {what}", 502)
                return name
            if state in ("failed", "cancelled", "discarded"):
                raise NativeRenderError("tool_failed", f"{label} {state}: {payload.get('error') or payload.get('message')}", 502)
            if self._cancelled(job["jobId"]):
                raise NativeRenderError("cancelled", "Cancelled")
            if deadline is not None and self.deps.clock() >= deadline:
                raise NativeRenderError("timeout", f"{label} was still {state or 'waiting'} when its time ran out", 504)

    def _wer(self, workspace: str, filename: str, text: str, language: str, voice: dict | None = None) -> tuple[float | None, float, dict]:
        if not self.deps.check_speech:
            return None, MAX_WER, {}
        return qa_verdict(self.deps.call, workspace, filename, text, language, voice, MAX_WER)

    def _cues(self, workspace: str, filename: str, duration: float, text: str, language: str) -> dict[str, Any]:
        # "auto" uses the optional phoneme engine when it is installed and Rhubarb otherwise, so an install without
        # the 1.3 GB phoneme model still renders with acoustic lip-sync; the line records which engine drew it.
        found = self.deps.call("audio.mouth_cues", {"version": 1, "input": {
            "workspace": workspace, "file": filename, "start": 0, "duration": round(min(90, duration), 3), "dialogue": text,
            "language": SPEECH_CODES.get(language, "en"), "engine": "auto"}})
        result = _ok(found, "Lip-sync analysis").get("result") or {}
        cues = result.get("mouthCues") or result.get("cues") or []
        if not cues:
            raise NativeRenderError("mouth_cues_missing", "Lip-sync analysis returned no mouth cues; review the audio before rendering", 502)
        engine = result.get("engine")
        return {"cues": cues, "driver": result.get("recognizer") or result.get("driver") or engine or "wav2vec2-phoneme",
                **({"engine": engine} if engine else {}),
                **({"fallbackReason": result["fallbackReason"]} if result.get("fallbackReason") else {})}

    def _scene(self, workspace: str, job: dict, item: dict, series: dict, episode: dict, shot: dict, kits: dict, index: int) -> None:
        ordered = sorted(episode.get("shots") or [], key=lambda value: value.get("order", 0))
        position = next(i for i, value in enumerate(ordered) if value["id"] == shot["id"])
        first = position == 0 or ordered[position - 1].get("sceneId") != shot.get("sceneId")
        spec = build_shot_spec(series, episode, shot, workspace=workspace, recorded=self._heard(workspace, series, shot, item["lines"]),
                               first_of_scene=first)
        try:
            plate = document_plate(self.deps.workspace_dir(workspace), shot, spec)
        except DocumentCardError as error:
            raise NativeRenderError("document_card", str(error), 502) from error
        if plate:
            spec["background"] = plate
            spec["texts"] = []
        root = self.deps.workspace_dir(workspace)
        self._balance(root, spec)
        measure_props(spec, root)
        used = {cast["kitId"]: with_pose_sizes(kits[cast["kitId"]], root) for cast in spec["cast"] if cast["kitId"] in kits}
        document = self.deps.compile_shot({"mode": "shot", "kits": used, "shot": spec})
        audio = audio_content(root, (line["filename"] for line in [*spec["lines"], *spec.get("audioTracks", [])]))
        digest = hashlib.sha1(json.dumps([document, audio], sort_keys=True).encode()).hexdigest()[:10]
        saved = _ok(self.deps.call("scenes.document.save", {"version": 1, "intent_id": f"{job['jobId']}-{shot['id']}-{digest}", "input": {
            "workspace": workspace, "name": self._scene_name(job, series, episode, shot), "document": document}}), "save scene")
        item.update(scene=(saved.get("result") or {}).get("name"), duration=document["duration"], digest=digest, stage="export",
                    exportIntent=f"{job['jobId']}-{shot['id']}-{digest}-export{self._retry_suffix(item)}")
        exported = self.deps.call("scenes.video2d.export", {"version": 1, "intent_id": item["exportIntent"],
                                                            "input": {"workspace": workspace, "document": document}})
        _ok(exported, "export")
        self._save(workspace, job)

    def _heard(self, workspace: str, series: dict, shot: dict, recorded: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """The recorded lines as the shot plays them: the room's copy of each when its location (or the shot) has a room."""
        root = self.deps.workspace_dir(workspace)
        try:
            return roomed(series, shot, recorded, lambda filename, preset: self.deps.room(root, filename, preset))
        except RoomError as error:
            raise NativeRenderError("room_failed", f"Voice room: {error}", 502) from error

    def _balance(self, root: str, spec: dict) -> None:
        """Music and effect volumes mean "relative to the dialogue", whatever loudness their file was made at.
        A cue with ``in``/``length`` is first pointed at a file of just that part (``series_sound_cuts``)."""
        materialize_cuts(root, spec.get("audioTracks") or [])
        for track in spec.get("audioTracks") or []:
            path = track_source(root, track.get("filename"))
            if track.get("kind") != "speech" and path is not None and path.is_file():
                track["volume"] = round(min(2.0, float(track.get("volume", 1)) * self.deps.loudness_gain(str(path))), 3)

    def _scene3d(self, workspace: str, job: dict, item: dict, series: dict, episode: dict, shot: dict, kits: dict) -> None:
        """A Video 3D shot: lines timed like a 2D shot, cast objects talk as their kits, exported by the 3D exporter."""
        beats = [beat for beat in shot.get("dialogueBeats") or [] if str(beat.get("text") or "").strip()]
        layout = shot.get("layout2d") if isinstance(shot.get("layout2d"), dict) else {}
        timing, duration = plan_timing([float(item["lines"][beat["id"]]["duration"]) for beat in beats], **timing_args(layout),
                                       at_least=0.0 if beats else float(shot.get("durationSeconds") or 5), pauses=pauses(beats))
        heard = self._heard(workspace, series, shot, item["lines"])
        lines = [{"characterId": beat.get("characterId"), "start": start, "filename": heard[beat["id"]]["filename"],
                  "cues": item["lines"][beat["id"]].get("cues") or []} for beat, (start, _end) in zip(beats, timing)]
        characters = {value["id"]: (kit_ref(series, value["id"]) or {}).get("id") for value in series.get("characters") or []}
        # The scene's ambience, stinger and music play under a 3D shot too, balanced like in a 2D shot.
        ordered = sorted(episode.get("shots") or [], key=lambda value: value.get("order", 0))
        position = next((i for i, value in enumerate(ordered) if value["id"] == shot["id"]), 0)
        first = position == 0 or ordered[position - 1].get("sceneId") != shot.get("sceneId")
        # Its sound effects and screen effects too, at a second or on a line, like in a 2D shot.
        sound = {"audioTracks": [*sound_tracks(series, shot, first), *sfx_tracks(layout, timing, duration)]}
        self._balance(self.deps.workspace_dir(workspace), sound)
        lines, sound["audioTracks"] = series_hearing.shape(series, shot, lines, sound["audioTracks"])
        scene = series_shot3d.build_scene(self.deps.call, workspace, job["jobId"], shot, lines, duration, kits, characters, NativeRenderError,
                                          tracks=sound["audioTracks"], root=self.deps.workspace_dir(workspace),
                                          screen_fx=fx_cues(layout, timing, duration),
                                          plate=location_plate_url(series, shot, workspace))
        config = series_shot3d.normalize_scene3d(shot.get("scene3d")) or {}
        intent = f"{job['jobId']}-{shot['id']}-3d-{scene['renderDigest']}-{scene['revision']}-export{self._retry_suffix(item)}"[:160]
        # A staged review's preview is the cheap faithful look: draft quality, whatever the shot's own.
        quality = "draft" if item.get("pass") == "preview" else config.get("quality", "draft")
        document = series_shot3d.series_frame_document(series, scene.get("document") or {})
        _ok(self.deps.call("scenes.world3d.export", {"version": 1, "intent_id": intent, "input": {
            "workspace": workspace, "document": document, "quality": quality}}), "export 3D")
        # A Video 3D scene has no dialogue beats: the take carries its lines for the episode's subtitles.
        subtitles = [{"text": str(beat.get("text") or "").strip(), "start": start, "end": end} for beat, (start, end) in zip(beats, timing)]
        item.update(scene=scene.get("file"), duration=round(duration, 3), stage="export", exportIntent=intent,
                    exportReceipt="scenes.world3d.export.receipt", subtitles=subtitles)
        self._save(workspace, job)

    @staticmethod
    def _scene_name(job: dict, series: dict, episode: dict, shot: dict) -> str:
        suffix = "" if job.get("original", True) else f"-{job['language']}"
        # The language suffix survives the length cap: a dubbed scene must not be named like the original.
        return f"{series['id']}-{episode['id']}-{shot['id']}"[:100 - len(suffix)] + suffix

    @staticmethod
    def _retry_suffix(item: dict) -> str:
        retries = int(item.get("exportRetries") or 0)
        return f"-r{retries}" if retries else ""

    def _export(self, workspace: str, job: dict, item: dict) -> bool:
        """True when the take's video is there; False when the export was lost and the scene stage must ask again."""
        while True:
            tool = item.get("exportReceipt") or "scenes.video2d.export.receipt"
            receipt = self.deps.call(tool, {"version": 1, "input": {"workspace": workspace, "intent_id": item["exportIntent"]}})
            error = receipt.get("error") if receipt.get("_is_error") and isinstance(receipt.get("error"), dict) else None
            body = receipt.get("result") if isinstance(receipt.get("result"), dict) else receipt
            artifacts = (body.get("receipt") or {}).get("artifacts") or []
            task = body.get("task") or {}
            if artifacts:
                item.update(video=artifacts[0]["name"], stage="foley")
                self._save(workspace, job)
                return True
            lost = task.get("status") in ("interrupted", "discarded") or (
                error is not None and (error.get("status") == 404 or error.get("code") == "receipt_not_found"))
            if lost:
                item.update(stage="scene", exportRetries=int(item.get("exportRetries") or 0) + 1,
                            error=f"export {task.get('status') or 'unknown'}; asking again")
                self._save(workspace, job)
                return False
            if error is not None:
                raise NativeRenderError("tool_failed", f"export receipt: {error.get('message') or error}"[:300], 502)
            if task.get("status") in ("failed", "cancelled"):
                raise NativeRenderError("export_failed", str(task.get("error") or task.get("message") or "export failed")[:300], 502)
            if self._cancelled(job["jobId"]):
                raise NativeRenderError("cancelled", "Cancelled")
            self.deps.sleep(self.deps.poll_seconds)

    def _foley(self, workspace: str, job: dict, item: dict, shot: dict) -> None:
        """Sound generated from the exported picture (``shot.foley``), mixed under the take before its import. It is an
        extra: when MMAudio fails, is not installed or takes too long, the take goes in without it and the item says
        why. A cancel, or a disk or GPU the next shot would wait for too, stops the render here; a resume continues."""
        item.pop("warning", None)
        item.pop("foley", None)
        try:
            foley = normalize_foley(shot.get("foley"))
            if foley:
                item["video"], item["foley"] = self._with_foley(workspace, job, item, shot["id"], foley)
        except (Cancelled, ResourceUnavailable):
            raise
        except Exception as error:  # the take is imported without foley
            if self._cancelled(job["jobId"]):
                raise
            item["warning"] = f"Foley left out: {error}"[:300]
        item["stage"] = "import"
        self._save(workspace, job)

    def _with_foley(self, workspace: str, job: dict, item: dict, shot_id: str, foley: dict) -> tuple[str, dict]:
        """The take with its foley mixed in, and what went into it. The generated sound is kept by export and prompt,
        the mixed take by export, prompt and volume, so a resume or a render of the same picture reuses them."""
        root = self.deps.workspace_dir(workspace)
        export = item["video"]
        sound_key, take_key = foley_keys(file_digest(os.path.join(root, export)), foley)
        stem = f"foley-{job['episodeId']}-{shot_id}"[:120]
        sound, take = f"{stem}-{sound_key}.wav", f"{stem}-{take_key}.mp4"
        record = {**foley, "file": sound, "source": export}
        if os.path.isfile(os.path.join(root, take)):
            return take, {**record, "reused": True}
        if not os.path.isfile(os.path.join(root, sound)):
            generated = os.path.join(root, self._generate_foley(workspace, job, item, shot_id, foley, f"{stem}-{sound_key}"))
            try:
                self.deps.extract_audio(generated, os.path.join(root, sound))
            finally:
                _discard(generated)  # a copy of the take's picture with the new sound: only the sound is kept
        # Like a shot's music and effects: the volume is relative to the dialogue, whatever loudness MMAudio made it at.
        gain = round(min(MAX_VOLUME, foley["volume"] * self.deps.loudness_gain(os.path.join(root, sound))), 3)
        self.deps.mix_foley(os.path.join(root, export), os.path.join(root, sound), os.path.join(root, take), gain)
        return take, {**record, "gain": gain}

    def _generate_foley(self, workspace: str, job: dict, item: dict, shot_id: str, foley: dict, name: str) -> str:
        """The clip ``generation.sfx`` makes from the exported video (the same picture with MMAudio's sound)."""
        seconds = float(item.get("duration") or self.deps.probe(os.path.join(self.deps.workspace_dir(workspace), item["video"])))
        params = sfx_params(workspace, item["video"], foley, foley_seed(shot_id, foley["prompt"]), seconds)
        deadline = self.deps.clock() + self.deps.foley_wait_seconds
        intent = f"{job['jobId']}-{name}"
        for _ in range(2):
            submitted = _ok(self.deps.call("generation.sfx", {"version": 2, "intent_id": intent[:160], "input": {
                "workspace": workspace, "output_name": f"{name}-raw", "params": params}}), "generation.sfx")
            job_id = _job_id(submitted)
            if not job_id:
                raise NativeRenderError("tool_failed", "Foley generation returned no job id", 502)
            output = self._wait_output(job, job_id, "Foley", (".mp4", ".mov", ".webm", ".wav", ".flac", ".mp3"), "a file", deadline)
            if output:
                return output
            # The intent replayed a job the server no longer knows (it restarted mid-generation): ask again.
            intent = f"{job['jobId']}-{name}"[:150] + f"-{uuid.uuid4().hex[:6]}"
        raise NativeRenderError("tool_failed", "Foley job disappeared twice", 502)

    def _render_shot(self, workspace: str, job: dict, item: dict, index: int) -> None:
        """A generated or imported take only gets its foley (``_video_foley``); every other shot renders."""
        if item.get("pass") == "promote":
            # Approve first, then read back the take whose optional foley the cut needs.
            self._approve(workspace, job, item["shotId"], item["attemptId"])
            item.update(stage="done", approved=True)
        series, episode = self._episode(workspace, job["seriesId"], job["episodeId"], job["language"])
        shot = next((value for value in episode.get("shots") or [] if value["id"] == item["shotId"]), {})
        if shot.get("productionMethod") not in VIDEO_METHODS:
            if item.get("pass") != "promote":
                self._render_item(workspace, job, item, index)
            return
        if shot_foley(shot):
            item["status"] = "running"
            self._video_foley(workspace, job, item, series, episode, shot)

    def _video_foley(self, workspace: str, job: dict, item: dict, series: dict, episode: dict, shot: dict) -> None:
        """A generated or imported take's foley (``series_video_foley``): the sound only, made once per take and prompt;
        the cut lays it under the take. Like any foley it is an extra: a failure leaves a warning, not a failed shot."""
        root, foley, asset = self.deps.workspace_dir(workspace), shot_foley(shot), video_take(series, shot)
        source = take_file(asset) if asset else ""
        if not foley or not source or not os.path.isfile(os.path.join(root, source)):
            raise NativeRenderError("no_take", f"Shot {shot['id']} needs a finished take and a foley prompt", 400)
        name = sound_name(os.path.join(root, source), episode["id"], shot["id"], foley)
        item.pop("warning", None)
        item.update(video=source, stage="foley", foley={**foley, "file": name, "source": source})
        try:
            if os.path.isfile(os.path.join(root, name)):
                item["foley"]["reused"] = True
            else:
                item["duration"] = self.deps.probe(os.path.join(root, source))
                generated = os.path.join(root, self._generate_foley(workspace, job, item, shot["id"], foley, name[:-4]))
                try:
                    self.deps.extract_audio(generated, os.path.join(root, name))
                finally:
                    _discard(generated)
        except (Cancelled, ResourceUnavailable):
            raise
        except Exception as error:
            if self._cancelled(job["jobId"]):
                raise
            item["warning"] = f"Foley left out: {error}"[:300]
        item["stage"] = "done"
        self._save(workspace, job)

    def _approve(self, workspace: str, job: dict, shot_id: str, attempt_id: str) -> None:
        if job.get("original", True):
            _ok(self.deps.call("series.take.approve", {"version": 1, "input": {
                "workspace": workspace, "series_id": job["seriesId"], "episode_id": job["episodeId"], "shot_id": shot_id,
                "attempt_id": attempt_id}}), "approve take")
        elif self.deps.set_version_take:
            self.deps.set_version_take(workspace, job["seriesId"], job["episodeId"], job["language"], shot_id, attempt_id)

    def _set_length(self, workspace: str, job: dict, item: dict) -> None:
        """The take's length becomes the shot's, in its own language only (versions keep their own durations)."""
        if not item.get("duration"):
            return
        if job.get("original", True):
            if self.deps.set_shot_duration:
                self.deps.set_shot_duration(workspace, job["seriesId"], job["episodeId"], item["shotId"], float(item["duration"]))
        elif self.deps.set_version_duration:
            self.deps.set_version_duration(workspace, job["seriesId"], job["episodeId"], job["language"], item["shotId"], float(item["duration"]))

    def _import(self, workspace: str, job: dict, item: dict, method: str = "animation_2d") -> None:
        self._set_length(workspace, job, item)
        metadata = {"productionMethod": method, "sceneFilename": item["scene"], "automaticDraft": True,
                    "nativeServerRender": job["jobId"], "duration": item.get("duration"), "language": job["language"],
                    **({"renderInputs": item["inputs"], "renderInputsVersion": INPUTS_VERSION} if item.get("inputs") else {}),
                    **({"dialogueBeats": item["subtitles"]} if item.get("subtitles") else {}),
                    **({"foley": {key: item["foley"][key] for key in ("prompt", "volume", "file")}} if item.get("foley") else {}),
                    **({"reviewStage": item["pass"]} if item.get("pass") in ("preview", "final") else {})}
        imported = _ok(self.deps.call("series.asset.import", {"version": 1, "input": {
            "workspace": workspace, "series_id": job["seriesId"], "file": item["video"], "owner_type": "shot", "owner_id": item["shotId"],
            "kind": "video", "as_take": True, "metadata": metadata}}), "import take")
        attempt = (imported.get("result") or {}).get("attempt") or {}
        item.update(attemptId=attempt.get("id"), stage="done")
        # A preview waits for the user's look; a final follows an approved preview, so it is approved.
        approve = job.get("approve") if item.get("pass") not in ("preview", "final") else item["pass"] == "final"
        if approve and attempt.get("id"):
            self._approve(workspace, job, item["shotId"], attempt["id"])
            item["approved"] = True
        self._save(workspace, job)


def _reasons(waiting: list[dict[str, Any]]) -> str:
    plans = sum(1 for item in waiting if item["reason"] == "plan")
    return ", ".join(part for part in (f"{plans} plans" if plans else "",
                                       f"{len(waiting) - plans} previews" if len(waiting) > plans else "") if part)


def public_job(job: dict[str, Any]) -> dict[str, Any]:
    """Status without the per-line cue arrays."""
    view = copy.deepcopy(job)
    for item in view.get("items") or []:
        item["lines"] = {key: {k: v for k, v in value.items() if k != "cues"} | {"cueCount": len(value.get("cues") or [])}
                         for key, value in (item.get("lines") or {}).items()}
    return view
