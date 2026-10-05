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
   cards; ``series_shot_bridge`` compiles the editable Video 2D document.
3. **Take.** The scene is saved, exported headlessly
   (``scenes.video2d.export``) and imported as a take of the shot, which
   can be approved automatically.

State is saved per shot and stage, so a restart or a cancel resumes where it
stopped. A recording is keyed by text and voice and reused.
"""
from __future__ import annotations

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
from services.production_resource_gate import guard_workspace_mcp
from services.series_jobs import SeriesJobStore
from services.series_language_versions import LANGUAGES, localized_view, missing_lines
from services.series_shot_bridge import run_series_shot, with_pose_sizes
from services import series_shot3d
from services.series_shot_extras import fx_cues, pauses, sfx_tracks, timing_args
from services.series_shot_plan import build_shot_spec, kit_ref, language_key, plan_timing, recording_key, sound_tracks, voice_for
from services.series_take_inputs import render_inputs, stale_shot_ids

KIND = "native"
STAGES = ("voices", "scene", "export", "import", "done")
ACTIVE = ("queued", "running", "cancelling")
MAX_TAKES = 3
# An export the server lost (interrupted by a restart, discarded, forgotten) is asked for again under a new intent.
EXPORT_RETRIES = 3
INTERRUPTED = "The server restarted during this render; resume to continue"
MAX_WER = 0.34
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
    sleep: Callable[[float], None] = time.sleep
    poll_seconds: float = 3.0
    check_speech: bool = True
    # Sets shot.durationSeconds to the rendered length; a take shorter than its shot is refused on import.
    set_shot_duration: Callable[[str, str, str, str, float], None] | None = None
    # Approves a take in a language version: (workspace, series, episode, language, shot, attempt).
    set_version_take: Callable[[str, str, str, str, str, str], None] | None = None
    set_version_duration: Callable[[str, str, str, str, str, float], None] | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _discard(path: str) -> None:
    """Remove a generated file and its ``.meta.json`` sidecar; a missing file is fine."""
    stem = os.path.splitext(path)[0]
    for item in (path, f"{stem}.meta.json"):
        try:
            os.remove(item)
        except OSError:
            pass


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
        self.deps = replace(deps, call=guard_workspace_mcp(deps.call, deps.workspace_dir))
        self._threads: dict[str, threading.Thread] = {}
        self._cancel: set[str] = set()
        self._lock = threading.Lock()

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
              approve: bool = False, language: str | None = None) -> dict[str, Any]:
        raw_series, language, shots = self._preflight(workspace, series_id, episode_id, shot_ids, language)
        for job in self.jobs(workspace):
            if job.get("episodeId") == episode_id and job.get("language") == language and job.get("status") in ACTIVE:
                raise NativeRenderError("already_running", "This episode is already rendering on the server")
        job_id = f"native-{uuid.uuid4().hex[:12]}"
        job = {"jobId": job_id, "workspace": workspace, "seriesId": series_id, "episodeId": episode_id, "status": "queued",
               "approve": bool(approve), "language": language, "original": language == language_key(raw_series),
               "current": 0, "total": len(shots),
               "items": [{"shotId": shot["id"], "stage": "voices", "status": "queued", "lines": {}} for shot in shots],
               "createdAt": time.time(), "message": "Queued"}
        self._launch(workspace, job)
        return job

    def _preflight(self, workspace: str, series_id: str, episode_id: str, shot_ids: list[str] | None,
                   language: str | None) -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        """The series, the language and the 2D shots to render; refuses what would fail later."""
        raw_series, raw_episode = self._episode(workspace, series_id, episode_id)
        wanted = {shot["id"] for shot in raw_episode.get("shots") or [] if series_shot3d.wants_render(shot)
                  and (not shot_ids or shot["id"] in shot_ids)}
        if not wanted:
            raise NativeRenderError("no_2d_shots", "The episode has no 2D shots (or 3D shots with scene3d) to render", 400)
        language = self._check_language(raw_series, raw_episode, language, wanted)
        series, episode = self._episode(workspace, series_id, episode_id, language)
        shots = sorted((shot for shot in episode.get("shots") or [] if shot["id"] in wanted), key=lambda shot: shot.get("order", 0))
        missing = self._missing_kits(workspace, series, shots)
        if missing:
            raise NativeRenderError("missing_kits", f"Make a Character Kit for {', '.join(missing)} before rendering", 400)
        voiceless = self._missing_voices(workspace, series, shots, language, language_key(raw_series))
        if voiceless:
            raise NativeRenderError("no_voice", f"{', '.join(voiceless)} have no {language} voice (voicesByLanguage); "
                                    f"design one before rendering this version", 400)
        return raw_series, language, shots

    def _missing_voices(self, workspace: str, series: dict[str, Any], shots: list[dict[str, Any]], language: str, original: str) -> list[str]:
        """Speakers of a language version whose kit has no voice designed for that language (the default would be the wrong accent)."""
        if language == original:
            return []
        kits = self.deps.read_kits(workspace)
        names = {item.get("id"): item.get("name") or item.get("id") for item in series.get("characters") or []}
        speakers = dict.fromkeys(beat.get("characterId") for shot in shots for beat in shot.get("dialogueBeats") or []
                                 if str(beat.get("text") or "").strip() and beat.get("characterId"))
        return [str(names.get(cid, cid)) for cid in speakers
                if not ((kits.get((kit_ref(series, cid) or {}).get("id") or "") or {}).get("voicesByLanguage") or {}).get(language)]

    def _missing_kits(self, workspace: str, series: dict[str, Any], shots: list[dict[str, Any]]) -> list[str]:
        """Names of characters seen or heard in ``shots`` without a Character Kit in the workspace (a new template's cast)."""
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
        for item in job.get("items") or []:
            if item.get("status") == "running":
                item["status"] = "queued"
        job.update(status="interrupted", message=INTERRUPTED, finishedAt=time.time())
        self._store(workspace).save(job)
        return job

    def stale_shots(self, workspace: str, series_id: str, episode_id: str, language: str | None = None) -> list[str]:
        """Shots to render in ``language``: no approved take yet, or one made from other inputs (see ``render_inputs``)."""
        raw_series, _raw_episode = self._episode(workspace, series_id, episode_id)
        series, episode = self._episode(workspace, series_id, episode_id, language or language_key(raw_series))
        return stale_shot_ids(series, episode, self.deps.read_kits(workspace))

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
                self._render_item(workspace, job, item, index)
                item.update(status="done", stage="done", error=None)
            except Exception as error:  # one shot must not stop the episode
                failed += 1
                item.update(status="failed", error=f"{type(error).__name__}: {error}"[:500])
            self._save(workspace, job)
        done = sum(1 for item in job["items"] if item["status"] == "done")
        self._save(workspace, job, current=len(job["items"]), activeShotId=None, finishedAt=time.time(),
                   status="completed" if not failed else "failed",
                   message=f"{done} of {len(job['items'])} shots rendered" + (f"; {failed} failed, resume to retry" if failed else ""))

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
                item["inputs"] = render_inputs(series, shot, kits)
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
        if item["stage"] == "import":
            self._import(workspace, job, item, "animation_3d" if three_d else "animation_2d")

    def _voices(self, workspace: str, job: dict, item: dict, series: dict, shot: dict, kits: dict) -> None:
        for beat in shot.get("dialogueBeats") or []:
            text = str(beat.get("text") or "").strip()
            if not text:
                continue
            ref = kit_ref(series, beat.get("characterId", ""))
            kit = kits.get(ref["id"]) if ref else None
            voice = voice_for(kit, job["language"]) if kit else None
            if not voice:
                raise NativeRenderError("no_voice", f"{beat.get('characterId')} has no voice for {job['language']}")
            key = recording_key(text, voice)
            done = item["lines"].get(beat["id"])
            if done and done.get("key") == key and os.path.isfile(os.path.join(self.deps.workspace_dir(workspace), done["filename"])):
                continue
            item["lines"][beat["id"]] = self._reuse(workspace, job, beat["id"], text, key) or self._record(workspace, job, beat["id"], text, voice, key)
            self._save(workspace, job)
            if self._cancelled(job["jobId"]):
                raise NativeRenderError("cancelled", "Cancelled")

    @staticmethod
    def _stem(job: dict, beat_id: str, key: str) -> str:
        return f"ln-{job['episodeId']}-{beat_id}-{key}"[:150]

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
        self.deps.level(path)
        cues = self._cues(workspace, filename, duration, text, job["language"])
        return {"key": key, "filename": filename, "duration": round(duration, 3), "wer": None, "attempt": 0, "reused": True, **cues}

    def _record(self, workspace: str, job: dict, beat_id: str, text: str, voice: dict, key: str) -> dict[str, Any]:
        root = self.deps.workspace_dir(workspace)
        stem = self._stem(job, beat_id, key)
        final, best_path = os.path.join(root, f"{stem}.wav"), os.path.join(root, f"{stem}.best.wav")
        best: dict[str, Any] | None = None
        try:
            for attempt in range(MAX_TAKES):
                raw = self._speak(workspace, job, stem, text, voice, attempt)
                try:
                    duration = self.deps.trim(os.path.join(root, raw), final)
                finally:
                    _discard(os.path.join(root, raw))  # the trimmed take is the recording; the raw one is an intermediate
                wer = self._wer(workspace, f"{stem}.wav", text, job["language"])
                take = {"key": key, "filename": f"{stem}.wav", "duration": round(duration, 3), "wer": wer, "attempt": attempt}
                if best is None or (wer is not None and (best["wer"] is None or wer < best["wer"])):
                    best = take
                    os.replace(final, best_path)
                if wer is None or wer <= MAX_WER:
                    break
        finally:
            # The best take so far becomes the recording even when a later attempt fails, so a resume reuses it.
            if os.path.isfile(best_path):
                os.replace(best_path, final)
        self.deps.level(final)
        cues = self._cues(workspace, best["filename"], best["duration"], text, job["language"])
        return {**best, **cues}

    def _speak(self, workspace: str, job: dict, stem: str, text: str, voice: dict, attempt: int) -> str:
        seed = int(hashlib.sha1(f"{stem}-{attempt}".encode()).hexdigest()[:6], 16)
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
        while True:
            waited = self.deps.call("jobs.wait", {"version": 1, "input": {"job_id": job_id, "timeout_s": 120}})
            error = waited.get("error") if isinstance(waited.get("error"), dict) else {}
            if waited.get("_is_error") and not error.get("job_id"):
                if error.get("status") == 404 or "not found" in str(error.get("message") or "").lower():
                    return None
                raise NativeRenderError("tool_failed", f"Waiting for speech: {error.get('message') or waited}"[:300], 502)
            payload = error if error.get("job_id") else waited
            state = payload.get("status")
            if state == "completed":
                name = _output_file(payload, (".wav", ".mp3", ".flac"))
                if not name:
                    raise NativeRenderError("tool_failed", "Speech finished without an audio file", 502)
                return name
            if state in ("failed", "cancelled", "discarded"):
                raise NativeRenderError("tool_failed", f"Speech {state}: {payload.get('error') or payload.get('message')}", 502)
            if self._cancelled(job["jobId"]):
                raise NativeRenderError("cancelled", "Cancelled")

    def _wer(self, workspace: str, filename: str, text: str, language: str) -> float | None:
        if not self.deps.check_speech:
            return None
        checked = self.deps.call("qa.speech", {"version": 1, "input": {"workspace": workspace, "file": filename, "text": text, "language": language}})
        return None if checked.get("_is_error") else (checked.get("result") or {}).get("wer")

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
        spec = build_shot_spec(series, episode, shot, workspace=workspace, recorded=item["lines"], first_of_scene=first)
        root = self.deps.workspace_dir(workspace)
        self._balance(root, spec)
        used = {cast["kitId"]: with_pose_sizes(kits[cast["kitId"]], root) for cast in spec["cast"] if cast["kitId"] in kits}
        document = self.deps.compile_shot({"mode": "shot", "kits": used, "shot": spec})
        digest = hashlib.sha1(json.dumps(document, sort_keys=True).encode()).hexdigest()[:10]
        saved = _ok(self.deps.call("scenes.document.save", {"version": 1, "intent_id": f"{job['jobId']}-{shot['id']}-{digest}", "input": {
            "workspace": workspace, "name": self._scene_name(job, series, episode, shot), "document": document}}), "save scene")
        item.update(scene=(saved.get("result") or {}).get("name"), duration=document["duration"], digest=digest, stage="export",
                    exportIntent=f"{job['jobId']}-{shot['id']}-{digest}-export{self._retry_suffix(item)}")
        exported = self.deps.call("scenes.video2d.export", {"version": 1, "intent_id": item["exportIntent"],
                                                            "input": {"workspace": workspace, "document": document}})
        _ok(exported, "export")
        self._save(workspace, job)

    def _balance(self, root: str, spec: dict) -> None:
        """Music and effect volumes mean "relative to the dialogue", whatever loudness their file was made at."""
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
        lines = [{"characterId": beat.get("characterId"), "start": start, "filename": item["lines"][beat["id"]]["filename"],
                  "cues": item["lines"][beat["id"]].get("cues") or []} for beat, (start, _end) in zip(beats, timing)]
        characters = {value["id"]: (kit_ref(series, value["id"]) or {}).get("id") for value in series.get("characters") or []}
        # The scene's ambience, stinger and music play under a 3D shot too, balanced like in a 2D shot.
        ordered = sorted(episode.get("shots") or [], key=lambda value: value.get("order", 0))
        position = next((i for i, value in enumerate(ordered) if value["id"] == shot["id"]), 0)
        first = position == 0 or ordered[position - 1].get("sceneId") != shot.get("sceneId")
        # Its sound effects and screen effects too, at a second or on a line, like in a 2D shot.
        sound = {"audioTracks": [*sound_tracks(series, shot, first), *sfx_tracks(layout, timing, duration)]}
        self._balance(self.deps.workspace_dir(workspace), sound)
        scene = series_shot3d.build_scene(self.deps.call, workspace, job["jobId"], shot, lines, duration, kits, characters, NativeRenderError,
                                          tracks=sound["audioTracks"], root=self.deps.workspace_dir(workspace),
                                          screen_fx=fx_cues(layout, timing, duration))
        config = series_shot3d.normalize_scene3d(shot.get("scene3d")) or {}
        intent = f"{job['jobId']}-{shot['id']}-3d-{scene['revision']}-export{self._retry_suffix(item)}"[:160]
        _ok(self.deps.call("scenes.world3d.export", {"version": 1, "intent_id": intent, "input": {
            "workspace": workspace, "document": scene["document"], "quality": config.get("quality", "draft")}}), "export 3D")
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
                item.update(video=artifacts[0]["name"], stage="import")
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
                    **({"renderInputs": item["inputs"]} if item.get("inputs") else {}),
                    **({"dialogueBeats": item["subtitles"]} if item.get("subtitles") else {})}
        imported = _ok(self.deps.call("series.asset.import", {"version": 1, "input": {
            "workspace": workspace, "series_id": job["seriesId"], "file": item["video"], "owner_type": "shot", "owner_id": item["shotId"],
            "kind": "video", "as_take": True, "metadata": metadata}}), "import take")
        attempt = (imported.get("result") or {}).get("attempt") or {}
        item.update(attemptId=attempt.get("id"), stage="done")
        if job.get("approve") and attempt.get("id"):
            self._approve(workspace, job, item["shotId"], attempt["id"])
            item["approved"] = True
        self._save(workspace, job)


def public_job(job: dict[str, Any]) -> dict[str, Any]:
    """Status without the per-line cue arrays."""
    view = copy.deepcopy(job)
    for item in view.get("items") or []:
        item["lines"] = {key: {k: v for k, v in value.items() if k != "cues"} | {"cueCount": len(value.get("cues") or [])}
                         for key, value in (item.get("lines") or {}).items()}
    return view
