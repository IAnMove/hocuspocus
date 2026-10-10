"""One line's voice, recorded now: Series Lab's shot inspector and ``series.shot.voice``.

The server render records every line of a shot before it draws it (``series_native_render``): the
character's voice for the language, trimmed, checked with ``qa.speech`` and analysed into mouth cues, as
``ln-<episode>-<beat>-<key>.wav``, where the key is a digest of the text and the voice. This records ONE
line through that same path, so the next render of the shot finds the file and reuses it:

* after its text (or its speaker) changed, the line's new recording;
* a ``retake`` of an unchanged line is another take with another seed. It replaces the recording only once it
  is good, so a failed retake keeps the old one.

The shot's take is not touched: render the shot again to hear the line in it. A recording newer than the
shot's latest take is listed with ``newerThanTake``, so the inspector can say the take is out of date.

A recording is a GPU job that can wait for the speech model, so it runs as a small job
(``.series-jobs-v1/voice``) that a caller follows with ``status``; one line records once at a time, and
nothing records while the episode renders on the server (the render could take that line's recording
in the middle of a take).
"""
from __future__ import annotations

import os
import threading
import time
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any
from urllib.parse import quote

from services.series_jobs import SeriesJobStore
from services.series_kit_pins import kits_for_episode
from services.series_language_versions import LANGUAGES, localized_view
from services.series_native_render import ACTIVE, NativeRenderError, SeriesNativeRender
from services.series_shot_edit import find_shot
from services.series_shot_plan import language_key
from services.series_voice_rooms import line_rooms, room_filename

KIND = "voice"
INTERRUPTED = "The server restarted while this line was recording; record it again"


class LineVoiceError(NativeRenderError):
    pass


def spoken_beats(shot: dict[str, Any]) -> list[dict[str, Any]]:
    return [beat for beat in shot.get("dialogueBeats") or [] if isinstance(beat, dict) and str(beat.get("text") or "").strip()]


def find_line(shot: dict[str, Any], ref: Any) -> dict[str, Any]:
    """A spoken line of the shot by its beat id, or by its number among the shot's lines (1 = the first)."""
    beats = spoken_beats(shot)
    for beat in beats:
        if beat.get("id") == ref:
            return beat
    number = ref if isinstance(ref, int) and not isinstance(ref, bool) else int(ref) if isinstance(ref, str) and ref.isdigit() else 0
    if 1 <= number <= len(beats):
        return beats[number - 1]
    raise LineVoiceError("line_not_found", f"Shot {shot.get('id')} has {len(beats)} lines; there is no line {ref}", 404)


def _mtime(path: str) -> float | None:
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def _iso_seconds(value: Any) -> float | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp() if value else None
    except ValueError:
        return None


def _latest_take_time(shot: dict[str, Any]) -> float | None:
    done = [item for item in shot.get("attempts") or [] if isinstance(item, dict) and item.get("status") == "completed"]
    return _iso_seconds((done[-1].get("completedAt") or done[-1].get("createdAt"))) if done else None


def _file_url(name: str, workspace: str) -> str:
    return f"/api/v1/file/{quote(name)}?workspace={quote(workspace)}"


def line_voices(render: SeriesNativeRender, workspace: str, series: dict[str, Any], episode: dict[str, Any], shot: dict[str, Any],
                kits: dict[str, Any], language: str) -> list[dict[str, Any]]:
    """Each spoken line of the (localized) shot with its recording: the file the render would reuse, when it is there,
    the room copy the shot plays, and whether it was made after the shot's latest take."""
    root = render.deps.workspace_dir(workspace)
    rooms, take_time = line_rooms(series, shot), _latest_take_time(shot)
    lines = []
    for number, beat in enumerate(spoken_beats(shot), start=1):
        entry: dict[str, Any] = {"beatId": beat["id"], "number": number, "characterId": beat.get("characterId"),
                                 "text": str(beat.get("text") or "").strip(), "recorded": False}
        try:
            _text, _voice, key = render.line_voice(series, beat, kits, language)
        except NativeRenderError as error:
            lines.append({**entry, "voice": False, "problem": str(error)})
            continue
        filename = f"{render.recording_stem(episode['id'], beat['id'], key)}.wav"
        recorded_at = _mtime(os.path.join(root, filename))
        entry.update(voice=True, key=key, filename=filename, recorded=recorded_at is not None)
        if recorded_at is not None:
            entry.update(url=_file_url(filename, workspace), recordedAt=recorded_at,
                         newerThanTake=take_time is not None and recorded_at > take_time)
            room = rooms.get(beat["id"])
            if room and os.path.isfile(os.path.join(root, room_filename(filename, room))):
                entry.update(room=room, roomUrl=_file_url(room_filename(filename, room), workspace))
            elif room:
                entry["room"] = room
        lines.append(entry)
    return lines


class SeriesLineVoice:
    """Record one line now with the render's own speech path; small jobs followed by ``status``."""

    def __init__(self, render: SeriesNativeRender, read_library: Callable[[str], dict], read_kits: Callable[[str], dict]) -> None:
        self.render, self.read_library, self.read_kits = render, read_library, read_kits
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.Lock()

    def _store(self, workspace: str) -> SeriesJobStore:
        return SeriesJobStore(self.render.deps.workspace_dir(workspace), KIND)

    def _shot(self, workspace: str, series_id: str, episode_id: str, shot_ref: Any, language: str | None) -> tuple[dict, dict, dict, str]:
        """The series, episode and shot in ``language`` (the series' own by default), and that language."""
        raw_series = (self.read_library(workspace).get("seriesById") or {}).get(series_id)
        raw_episode = ((raw_series or {}).get("episodesById") or {}).get(episode_id)
        if not isinstance(raw_episode, dict):
            raise LineVoiceError("not_found", "Series episode not found", 404)
        original = language_key(raw_series)
        language = language or original
        if language not in LANGUAGES:
            raise LineVoiceError("invalid_language", f"Unknown language {language}", 400)
        try:
            series, episode = localized_view(raw_series, raw_episode, None if language == original else language)
            shot, _number = find_shot(episode, shot_ref)
        except ValueError as error:
            raise LineVoiceError(getattr(error, "code", "no_version"), str(error), getattr(error, "status", 404)) from error
        return series, episode, shot, language

    def voices(self, workspace: str, series_id: str, episode_id: str, shot_ref: Any, language: str | None = None) -> dict[str, Any]:
        series, episode, shot, language = self._shot(workspace, series_id, episode_id, shot_ref, language)
        lines = line_voices(self.render, workspace, series, episode, shot, self._kits(workspace, episode), language)
        active = [job for job in self.jobs(workspace) if job.get("shotId") == shot["id"] and job.get("status") in ACTIVE]
        return {"shotId": shot["id"], "language": language, "lines": lines, "recording": active}

    def _kits(self, workspace: str, episode: dict[str, Any]) -> dict[str, Any]:
        """The kits the episode's render uses: the latest, or the revisions it pins (``series_kit_pins``)."""
        return kits_for_episode(self.read_kits(workspace), episode, self.render.deps.workspace_dir(workspace))

    def jobs(self, workspace: str) -> list[dict[str, Any]]:
        return [self._reconcile(workspace, job) for job in self._store(workspace).list()]

    def status(self, workspace: str, job_id: str) -> dict[str, Any]:
        try:
            job = self._store(workspace).load(job_id)
        except ValueError as error:
            raise LineVoiceError("not_found", str(error), 404) from error
        if not job:
            raise LineVoiceError("not_found", "Voice job not found", 404)
        return self._reconcile(workspace, job)

    def _reconcile(self, workspace: str, job: dict[str, Any]) -> dict[str, Any]:
        """A job that says it is recording without its thread here was cut by a restart."""
        thread = self._threads.get(job.get("jobId", ""))
        if job.get("status") not in ACTIVE or (thread is not None and (thread.ident is None or thread.is_alive())):
            return job
        if thread is not None:
            stored = self._store(workspace).load(job["jobId"]) or job
            if stored.get("status") not in ACTIVE:
                return stored
        job.update(status="interrupted", error=INTERRUPTED, finishedAt=time.time())
        self._store(workspace).save(job)
        return job

    def start(self, workspace: str, series_id: str, episode_id: str, shot_ref: Any, line_ref: Any, *, retake: bool = False,
              language: str | None = None) -> dict[str, Any]:
        """Record (or ``retake``) one line of a shot; returns the job (an already recording one for that line)."""
        series, episode, shot, language = self._shot(workspace, series_id, episode_id, shot_ref, language)
        beat = find_line(shot, line_ref)
        self.render.line_voice(series, beat, self._kits(workspace, episode), language)  # no voice: refused now, not in the job
        for job in self.render.jobs(workspace):
            if job.get("episodeId") == episode_id and job.get("status") in ACTIVE:
                raise LineVoiceError("render_running", "The episode is rendering on the server; record the line when it ends "
                                     "(or stop the render)", 409)
        with self._lock:
            for job in self.jobs(workspace):
                if job.get("episodeId") == episode_id and job.get("beatId") == beat["id"] and job.get("language") == language \
                        and job.get("status") in ACTIVE:
                    return job
            job = {"jobId": f"voice-{uuid.uuid4().hex[:12]}", "workspace": workspace, "seriesId": series_id, "episodeId": episode_id,
                   "shotId": shot["id"], "beatId": beat["id"], "characterId": beat.get("characterId"), "text": beat["text"],
                   "language": language, "retake": bool(retake), "status": "queued", "createdAt": time.time()}
            thread = threading.Thread(target=self._run, args=(workspace, job["jobId"]), name=f"series-voice-{job['jobId']}", daemon=True)
            self._threads[job["jobId"]] = thread
            self._store(workspace).save(job)
        thread.start()
        return job

    def _run(self, workspace: str, job_id: str) -> None:
        store = self._store(workspace)
        job = store.load(job_id) or {}
        job.update(status="running", updatedAt=time.time())
        store.save(job)
        try:
            series, episode, shot, language = self._shot(workspace, job["seriesId"], job["episodeId"], job["shotId"], job["language"])
            beat = find_line(shot, job["beatId"])
            if str(beat.get("text") or "").strip() != job["text"]:
                raise LineVoiceError("line_changed", "The line changed while it waited to record; record it again", 409)
            line = self.render.record_line(workspace, {"jobId": job_id, "episodeId": job["episodeId"], "language": language},
                                           series, beat, self._kits(workspace, episode), retake=job["retake"])
            result = {key: line[key] for key in ("filename", "duration", "wer", "attempt", "key", "reused", "retake") if key in line}
            job.update(status="completed", result={**result, "url": _file_url(line["filename"], workspace),
                                                   "cueCount": len(line.get("cues") or [])})
        except Exception as error:  # the job reports whatever stopped the recording
            job.update(status="failed", error=f"{error}"[:500], errorCode=getattr(error, "code", type(error).__name__))
        job.update(finishedAt=time.time(), updatedAt=time.time())
        store.save(job)


__all__ = ["KIND", "LineVoiceError", "SeriesLineVoice", "find_line", "line_voices", "spoken_beats"]
