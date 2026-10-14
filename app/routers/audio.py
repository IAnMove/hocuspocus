"""Audio upload, adopt, trim, mix, analysis, clip suggestions and structure plans.

The handlers are the launch functions, unchanged. Director plan reads sit
between suggest-clips and plan-structure, so those two groups are two
factories. Shared names are the launch objects, assigned onto this module
before a request runs. The analysis registry is ``services.audio_jobs._jobs``,
the kernel registry, not a second dictionary.
"""
from __future__ import annotations

import os
import re
import threading
import time
import traceback
import uuid
from urllib.parse import quote

from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from services import resource_scheduler
from services.audio_jobs import (
    _AUDIO_ANALYSIS_ACTIVE,
    _audio_analysis_job_update,
    _audio_analysis_jobs_lock,
    _publish_audio_analysis_job,
    _run_audio_analysis_job,
)
from services.job_lifecycle import snapshot_job
from services.upload_stream import UploadTooLargeError, UploadTranscodeError


# Bumped from 250 MB → 500 MB when /api/v1/upload-audio was extended
# to accept video files for audio extraction. A 5-min 1080p H.264
# music video runs ~30-100 MB; longer reference clips can push
# higher. 500 MB covers ~25-50 min of typical music-video bitrates.
MAX_AUDIO_UPLOAD_BYTES = 500 * 1024 * 1024   # 500 MB (also covers video-for-audio-extract)

# The launch module binds these to its kernel aliases before a request runs.
wgp = None
_jobs = None
_stream_upload = None
_transcode_upload = None
_get_active_workspace = None
_resolve_request_media_path = None
_safe_join = None
_workspace_dir = None


def _probe_audio_duration(filepath: str) -> float | None:
    try:
        import soundfile as sf

        info = sf.info(filepath)
        if info.samplerate and info.frames:
            return round(float(info.frames) / float(info.samplerate), 3)
    except Exception:
        pass
    return None

async def upload_audio(file: UploadFile = File(...)):
    """Upload an audio file (wav, mp3, flac, ogg, m4a) OR a video file
    (mp4, mov, mkv, webm, avi, m4v) for audio extraction. Video files
    are transparently demuxed to a 16-bit PCM WAV containing only the
    audio track; the source video is deleted afterwards. The response
    shape is identical regardless of input format — callers always
    receive a WAV path."""
    AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac"}
    VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
    ALLOWED_EXTENSIONS = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS

    ext = os.path.splitext(file.filename or "audio.wav")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported format: {ext}. Allowed audio: "
                f"{', '.join(sorted(AUDIO_EXTENSIONS))}. "
                f"Allowed video (audio will be extracted): "
                f"{', '.join(sorted(VIDEO_EXTENSIONS))}."
            ),
        )

    # Starlette counts the actual multipart file bytes while spooling.  Unlike
    # Content-Length, this excludes multipart overhead and cannot reject a
    # valid file sitting exactly at the limit.  The chunk counter below remains
    # authoritative for custom/malformed clients that omit the size.
    if file.size is not None and file.size > MAX_AUDIO_UPLOAD_BYTES:
        await file.close()
        raise HTTPException(status_code=413, detail="File too large (max 500 MB)")

    upload_dir = os.path.join(os.getcwd(), "uploads", "audio")
    os.makedirs(upload_dir, exist_ok=True)

    unique_name = f"{uuid.uuid4().hex}{ext}"
    filepath = os.path.join(upload_dir, unique_name)

    try:
        await _stream_upload(
            file,
            filepath,
            max_bytes=MAX_AUDIO_UPLOAD_BYTES,
        )
    except UploadTooLargeError as err:
        raise HTTPException(status_code=413, detail="File too large (max 500 MB)") from err

    # libsndfile (soundfile) supports wav/flac/ogg natively but NOT the
    # compressed formats users commonly have (mp3, m4a, aac). Downstream code
    # like wgp.slice_audio_window calls sf.SoundFile() directly which raises
    # LibsndfileError: Format not recognised. Transcode those to 16-bit PCM
    # wav here so the rest of the pipeline stays format-agnostic. Video
    # files take the same path with audio-only extraction (no -vn flag
    # needed because the .wav output container can't hold video — ffmpeg
    # naturally drops the video stream — but we pass `vn=None` to be
    # explicit and avoid bitstream-copy attempts on rare containers).
    is_video = ext in VIDEO_EXTENSIONS
    needs_transcode = ext in (".mp3", ".m4a", ".aac") or is_video
    if needs_transcode:
        wav_name = f"{os.path.splitext(unique_name)[0]}.wav"
        wav_path = os.path.join(upload_dir, wav_name)
        source_original = filepath
        transcode_ok = False
        try:
            await _transcode_upload(filepath, wav_path, is_video=is_video)
            transcode_ok = True
            os.remove(source_original)
            filepath = wav_path
            unique_name = wav_name
            if is_video:
                print(
                    f"[upload-audio] Extracted audio track from "
                    f"{file.filename!r} ({ext}) → {wav_name}. Source "
                    f"video deleted."
                )
        except UploadTranscodeError as err:
            detail_prefix = (
                "Failed to extract audio from video"
                if is_video else f"Failed to decode {ext} audio"
            )
            raise HTTPException(
                status_code=400,
                detail=f"{detail_prefix}: {(err.stderr or str(err)).strip()[:300]}",
            ) from err
        except Exception as err:
            raise HTTPException(
                status_code=500,
                detail=(
                    "Audio extraction failed" if is_video
                    else "Audio transcode failed"
                ) + f": {err}",
            ) from err
        finally:
            # If transcode/extract bombed (either branch above raised),
            # clean up the partial wav AND the original upload so orphans
            # don't pile up in uploads/audio/ on repeated failures.
            if not transcode_ok:
                for stale in (wav_path, source_original):
                    if stale and os.path.isfile(stale):
                        try:
                            os.remove(stale)
                        except OSError:
                            pass

    return {
        "filename": unique_name,
        "path": filepath,
        "url": f"/api/v1/uploads/audio/{unique_name}",
        "duration_seconds": _probe_audio_duration(filepath),
    }

async def adopt_audio(request: Request):
    """Adopt audio this machine already holds as the current audio source.

    The counterpart to /api/v1/upload-audio for a file that never left the
    server. Story Lab handing a generated song to Director used to download
    the whole track into the browser only to post the same bytes straight
    back — a round trip over the network for a file sitting on this disk,
    and the one step of that flow that breaks when the UI is driven from
    another machine. Callers send the name instead.

    Audio only, and adopted in place: the uploader owns transcoding and
    demuxing. The response shape mirrors the uploader's so everything
    downstream is identical regardless of how the audio arrived.
    """
    body = await request.json()
    workspace = body.get("workspace") if "workspace" in body else _get_active_workspace()
    filepath = _resolve_request_media_path(
        body.get("audio_path", ""),
        workspace=workspace,
        kinds=("audio",),
    )
    filename = os.path.basename(filepath)
    uploads_audio = os.path.realpath(os.path.join(os.getcwd(), "uploads", "audio"))
    from_uploads = os.path.dirname(os.path.realpath(filepath)) == uploads_audio
    workspace_suffix = f"?workspace={quote(workspace, safe='')}" if workspace else ""
    return {
        "filename": filename,
        "path": filepath,
        "url": (
            f"/api/v1/uploads/audio/{quote(filename, safe='')}"
            if from_uploads
            else f"/api/v1/file/{quote(filename, safe='')}{workspace_suffix}"
        ),
        "duration_seconds": _probe_audio_duration(filepath),
    }

def serve_audio_upload(filename: str):
    """Serve an uploaded audio file."""
    from services.win_safe_files import share_delete_file_response
    base = os.path.join(os.getcwd(), "uploads", "audio")
    filepath = _safe_join(base, filename)
    if filepath is None or not os.path.isfile(filepath):
        raise HTTPException(status_code=404, detail="File not found")
    return share_delete_file_response(filepath)

async def trim_uploaded_audio(request: Request):
    """Create a PCM WAV excerpt used by musical-trailer productions."""
    body = await request.json()
    workspace = body.get("workspace") if "workspace" in body else _get_active_workspace()
    audio_path = _resolve_request_media_path(
        body.get("audio_path", ""),
        workspace=workspace,
    )
    try:
        start = max(0.0, float(body.get("start", 0)))
        end = float(body.get("end", 0))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="start and end must be seconds")
    if end <= start + 0.99:
        raise HTTPException(status_code=400, detail="The selected trailer excerpt must be at least one second")

    upload_dir = os.path.join(os.getcwd(), "uploads", "audio")
    os.makedirs(upload_dir, exist_ok=True)
    filename = f"{uuid.uuid4().hex[:8]}-excerpt.wav"
    output_path = os.path.join(upload_dir, filename)
    try:
        import ffmpeg as _ffmpeg
        (
            _ffmpeg
            .input(audio_path, ss=start)
            .output(output_path, t=end - start, acodec="pcm_s16le", vn=None)
            .overwrite_output()
            .run(quiet=True)
        )
    except Exception as exc:
        if os.path.isfile(output_path):
            try:
                os.remove(output_path)
            except OSError:
                pass
        raise HTTPException(status_code=500, detail=f"Audio trim failed: {exc}") from exc
    return {
        "filename": filename,
        "path": output_path,
        "url": f"/api/v1/uploads/audio/{filename}",
        "start": start,
        "end": end,
        "duration": end - start,
    }

async def mix_audio(request: Request):
    """Mix multiple audio tracks into one file using ffmpeg.

    Body: {
        tracks: [{ path: str, start_time: float, volume: float }, ...],
        workspace: str | null
    }
    First track is the base (full duration). Subsequent tracks are overlaid at their start_time.
    Volume is 0.0-1.0.
    """
    import subprocess

    body = await request.json()
    tracks = body.get("tracks", [])
    if len(tracks) < 2:
        raise HTTPException(status_code=400, detail="At least 2 tracks required (base + overlay)")

    # Validate all track files: user-supplied paths must resolve inside the
    # uploads dir or the outputs tree — the same boundary every other file
    # endpoint enforces via _safe_join. Never feed arbitrary host paths to
    # ffmpeg.
    uploads_root = os.path.realpath(os.path.join(os.getcwd(), "uploads"))
    outputs_root = os.path.realpath(wgp.server_config.get("save_path", "outputs"))

    def _contained(real: str, root: str) -> bool:
        real_n, root_n = os.path.normcase(real), os.path.normcase(root)
        return real_n == root_n or real_n.startswith(root_n + os.sep)

    for i, t in enumerate(tracks):
        path = t.get("path", "")
        real = os.path.realpath(path) if path else ""
        if not real or not (_contained(real, uploads_root) or _contained(real, outputs_root)):
            raise HTTPException(status_code=400, detail=f"Track {i+1}: path not allowed: {path}")
        if not os.path.isfile(real):
            raise HTTPException(status_code=400, detail=f"Track {i+1}: file not found: {path}")
        t["path"] = real

    # Build ffmpeg filter_complex for mixing
    # Input 0 = base track, inputs 1..N = overlay tracks
    inputs = []
    filter_parts = []

    for i, t in enumerate(tracks):
        inputs.extend(["-i", t["path"]])

    # Process each track: apply volume and delay (except base track which starts at 0)
    mix_labels = []
    for i, t in enumerate(tracks):
        vol = max(0.0, min(1.0, float(t.get("volume", 1.0))))
        start_ms = int(float(t.get("start_time", 0)) * 1000)

        filters = []
        if start_ms > 0:
            filters.append(f"adelay={start_ms}|{start_ms}")
        if vol != 1.0:
            filters.append(f"volume={vol:.3f}")

        if filters:
            label = f"t{i}"
            filter_parts.append(f"[{i}]{','.join(filters)}[{label}]")
            mix_labels.append(f"[{label}]")
        else:
            mix_labels.append(f"[{i}]")

    # Combine all tracks with amix
    n = len(tracks)
    mix_input = "".join(mix_labels)
    filter_parts.append(f"{mix_input}amix=inputs={n}:duration=longest:normalize=0")

    filter_complex = ";".join(filter_parts)

    # Output to workspace
    workspace = body.get("workspace")
    out_dir = _workspace_dir(workspace)
    os.makedirs(out_dir, exist_ok=True)
    out_filename = f"mix_{uuid.uuid4().hex[:6]}.wav"
    out_path = os.path.join(out_dir, out_filename)

    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-ac", "1",  # mono output (LTX audio guide works best with mono)
        out_path,
    ]

    print(f"[Audio Mix] Mixing {n} tracks → {out_path}")
    print(f"[Audio Mix] Filter: {filter_complex}")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            print(f"[Audio Mix] ffmpeg error: {result.stderr[-500:]}")
            raise HTTPException(status_code=500, detail=f"ffmpeg failed: {result.stderr[-200:]}")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="Audio mix timed out")

    if not os.path.isfile(out_path):
        raise HTTPException(status_code=500, detail="Mix output file not created")

    print(f"[Audio Mix] Done: {out_filename}")

    return {
        "filename": out_filename,
        "path": out_path,
    }

async def analyze_audio(request: Request):
    """Analyze an audio file: beat detection, sections, optional transcription."""
    from services import audio_analysis
    body = await request.json()

    workspace = body.get("workspace") if "workspace" in body else _get_active_workspace()
    audio_path = _resolve_request_media_path(
        body.get("audio_path", ""),
        workspace=workspace,
    )

    lane = (
        resource_scheduler.local_gpu_lane(0)
        if body.get("transcribe", False)
        else resource_scheduler.cpu_lane("audio")
    )
    try:
        with resource_scheduler.coordinator.acquire(
            lane,
            task_id=f"audio-sync-{uuid.uuid4().hex[:12]}",
            description="Audio analysis",
        ):
            result = audio_analysis.analyze(
                audio_path=audio_path,
                transcribe=body.get("transcribe", False),
                extract_vocals_for_transcription=body.get("extract_vocals", True),
                # Known written lyrics (generated tracks) → Whisper initial_prompt
                lyrics_hint=body.get("lyrics_hint") or None,
            )
        return result
    except ImportError as e:
        raise HTTPException(status_code=501, detail=str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

def audio_analyze_status():
    """Read the current audio-analyze phase for live UI progress.

    Polled by the frontend during the synchronous /audio/analyze call
    so the user sees meaningful sub-status ("Loading transcription
    model (first use downloads ~300MB)..." vs "Transcribing audio...")
    instead of a single "Analyzing audio..." message for the entire
    1-5 minute wait.

    Returns {"step": "<phase>", "detail": "<human-readable message>"}.
    Both empty when no analyze is in flight.
    """
    from services.audio_analysis import get_progress
    return get_progress()

async def suggest_audio_clips(request: Request):
    """Suggest optimal clip boundaries aligned to musical structure."""
    from services import audio_analysis
    body = await request.json()

    analysis = body.get("analysis")
    if not analysis:
        raise HTTPException(status_code=400, detail="analysis is required")

    clip_duration = body.get("clip_duration", 5.0)
    total_duration = body.get("total_duration")

    try:
        clips = audio_analysis.suggest_clip_boundaries(
            analysis=analysis,
            clip_duration=clip_duration,
            total_duration=total_duration,
        )
        return {"clips": clips}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

async def start_audio_analysis_job(request: Request):
    """Queue audio analysis and return immediately with a durable job id."""
    body = await request.json()
    workspace = body.get("workspace") if "workspace" in body else _get_active_workspace()
    audio_path = _resolve_request_media_path(
        body.get("audio_path", ""),
        workspace=workspace,
    )
    body["audio_path"] = audio_path

    job_id = f"audio-analysis-{uuid.uuid4().hex[:12]}"
    supplied_task_id = str(body.get("task_id") or "").strip()
    supplied_root_id = str(body.get("root_task_id") or "").strip()
    supplied_parent_id = str(body.get("parent_task_id") or "").strip()
    for label, value in (
        ("task_id", supplied_task_id),
        ("root_task_id", supplied_root_id),
        ("parent_task_id", supplied_parent_id),
    ):
        if value and not re.fullmatch(r"task-[A-Za-z0-9_-]{1,180}", value):
            raise HTTPException(status_code=400, detail=f"Invalid {label}")
    task_id = supplied_task_id or f"task-audio-analysis-{job_id}"
    root_task_id = supplied_root_id or supplied_parent_id or task_id
    lane = (
        resource_scheduler.local_gpu_lane(0)
        if body.get("transcribe", False)
        else resource_scheduler.cpu_lane("audio")
    )
    job = {
        "id": job_id,
        "task_id": task_id,
        "root_task_id": root_task_id,
        "parent_task_id": supplied_parent_id or None,
        "workspace": workspace,
        "status": "queued",
        "progress": 0,
        "step": 0,
        "total_steps": 10,
        "phase": "queued",
        "message": "Audio analysis queued",
        "output_files": [],
        "error": None,
        "task_timings": [],
        "result": None,
        "created_at": time.time(),
        "updated_at": time.time(),
        "provider": "local",
        "model": "Whisper / pyannote" if body.get("transcribe", False) else "Audio analysis",
        "server_origin": "local",
        "resource_lane": lane.key,
        "acquired_resources": [],
        "project_id": str(body.get("project_id") or ""),
        "_cancel_requested": False,
    }
    with _audio_analysis_jobs_lock:
        _jobs[job_id] = job
    _publish_audio_analysis_job(job)
    threading.Thread(
        target=_run_audio_analysis_job,
        args=(job_id, dict(body)),
        name=f"audio-analysis-{job_id[-6:]}",
        daemon=True,
    ).start()
    return {
        "job_id": job_id,
        "task_id": task_id,
        "root_task_id": root_task_id,
        "parent_task_id": supplied_parent_id or None,
        "status": "queued",
    }

def get_audio_analysis_job(job_id: str, workspace: str | None = None):
    target_workspace = _get_active_workspace() if workspace is None else workspace
    _workspace_dir(target_workspace)
    with _audio_analysis_jobs_lock:
        job = snapshot_job(_jobs.get(job_id)) if _jobs.get(job_id) else None
    if not job or not job_id.startswith("audio-analysis-"):
        raise HTTPException(status_code=404, detail="Audio analysis job not found")
    if str(job.get("workspace") or "default") != str(target_workspace):
        raise HTTPException(status_code=404, detail="Audio analysis job not found")
    return {
        "job_id": job_id,
        "task_id": job.get("task_id"),
        "root_task_id": job.get("root_task_id") or job.get("task_id"),
        "status": job["status"],
        "progress": job["progress"],
        "step": job.get("step", 0),
        "total_steps": job.get("total_steps", 10),
        "phase": job.get("phase", ""),
        "message": job.get("message", ""),
        "error": job.get("error"),
        "result": job.get("result") if job["status"] == "completed" else None,
    }

def cancel_audio_analysis_job(job_id: str, workspace: str | None = None):
    target_workspace = _get_active_workspace() if workspace is None else workspace
    _workspace_dir(target_workspace)
    with _audio_analysis_jobs_lock:
        job = _jobs.get(job_id)
    if not job or not job_id.startswith("audio-analysis-"):
        raise HTTPException(status_code=404, detail="Audio analysis job not found")
    if str(job.get("workspace") or "default") != str(target_workspace):
        raise HTTPException(status_code=404, detail="Audio analysis job not found")
    if job["status"] not in _AUDIO_ANALYSIS_ACTIVE:
        return {"job_id": job_id, "status": job["status"]}
    with _audio_analysis_jobs_lock:
        job["_cancel_requested"] = True
        waiting = job["status"] in {"queued", "waiting_resource"}
    snapshot = _audio_analysis_job_update(
        job_id,
        status="cancelled" if waiting else "cancelling",
        phase="cancelled" if waiting else "cancelling",
        message=(
            "Cancelled before analysis started"
            if waiting else "Cancelling after the current analysis phase…"
        ),
        **({"finished_at": time.time()} if waiting else {}),
    ) or job
    return {
        "job_id": job_id,
        "task_id": snapshot.get("task_id"),
        "status": snapshot.get("status"),
    }

async def plan_audio_structure(request: Request):
    """Plan variable-duration clip structure aligned to beats and sections."""
    from services import audio_analysis
    body = await request.json()

    analysis = body.get("analysis")
    if not analysis:
        raise HTTPException(status_code=400, detail="analysis is required")

    # Resolve frame parameters from the DIRECTOR's video model when given —
    # the frontend's modelOptions belong to the Studio-selected model (often
    # ACE-Step right after generating the track), whose missing fps fell back
    # to 16 and silently shrank every planned clip's duration_frames by
    # 16/25 once rendered at LTX-2's 25 fps.
    fps = body.get("fps", 16)
    frames_steps = body.get("frames_steps", 4)
    frames_minimum = body.get("frames_minimum", 5)
    video_model = body.get("video_model")
    if video_model:
        try:
            md = wgp.get_model_def(video_model) or {}
            if md.get("fps"):
                fps = md["fps"]
            _minf, _fs, _lat = wgp.get_model_min_frames_and_step(video_model)
            frames_minimum, frames_steps = _minf, _fs
        except Exception:
            pass

    try:
        clips = audio_analysis.plan_clip_structure(
            analysis=analysis,
            energy_bias=body.get("energy_bias", 0),
            pacing_profile=body.get("pacing_profile"),
            fps=fps,
            frames_steps=frames_steps,
            frames_minimum=frames_minimum,
            total_duration=body.get("total_duration"),
        )
        return {"clips": clips}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


def create_audio_router(
    *,
    _jobs,
    _stream_upload,
    _transcode_upload,
    _get_active_workspace,
    _resolve_request_media_path,
    _safe_join,
    _workspace_dir,
    wgp,
):
    """Mount upload through suggest-clips at their old position.

    The handlers stay module-level. Each nested function is a one-line
    delegate, so the route keeps its name. ``_jobs`` is the kernel registry;
    the service module receives that same object.
    """
    import services.audio_jobs as audio_jobs

    audio_jobs._jobs = _jobs
    globals().update({
        "_jobs": _jobs,
        "_stream_upload": _stream_upload,
        "_transcode_upload": _transcode_upload,
        "_get_active_workspace": _get_active_workspace,
        "_resolve_request_media_path": _resolve_request_media_path,
        "_safe_join": _safe_join,
        "_workspace_dir": _workspace_dir,
        "wgp": wgp,
    })
    router = APIRouter()
    impl = {
        name: globals()[name]
        for name in (
            "upload_audio",
            "adopt_audio",
            "serve_audio_upload",
            "trim_uploaded_audio",
            "mix_audio",
            "analyze_audio",
            "audio_analyze_status",
            "start_audio_analysis_job",
            "get_audio_analysis_job",
            "cancel_audio_analysis_job",
            "suggest_audio_clips",
        )
    }

    @router.post("/api/v1/upload-audio")
    async def upload_audio(file: UploadFile = File(...)):
        """Upload an audio file (wav, mp3, flac, ogg, m4a) OR a video file
        (mp4, mov, mkv, webm, avi, m4v) for audio extraction. Video files
        are transparently demuxed to a 16-bit PCM WAV containing only the
        audio track; the source video is deleted afterwards. The response
        shape is identical regardless of input format — callers always
        receive a WAV path."""
        return await impl["upload_audio"](file)

    @router.post("/api/v1/audio/adopt")
    async def adopt_audio(request: Request):
        """Adopt audio this machine already holds as the current audio source.

        The counterpart to /api/v1/upload-audio for a file that never left the
        server. Story Lab handing a generated song to Director used to download
        the whole track into the browser only to post the same bytes straight
        back — a round trip over the network for a file sitting on this disk,
        and the one step of that flow that breaks when the UI is driven from
        another machine. Callers send the name instead.

        Audio only, and adopted in place: the uploader owns transcoding and
        demuxing. The response shape mirrors the uploader's so everything
        downstream is identical regardless of how the audio arrived.
        """
        return await impl["adopt_audio"](request)

    @router.get("/api/v1/uploads/audio/{filename}")
    def serve_audio_upload(filename: str):
        """Serve an uploaded audio file."""
        return impl["serve_audio_upload"](filename)

    @router.post("/api/v1/audio/trim")
    async def trim_uploaded_audio(request: Request):
        """Create a PCM WAV excerpt used by musical-trailer productions."""
        return await impl["trim_uploaded_audio"](request)

    @router.post("/api/v1/audio/mix")
    async def mix_audio(request: Request):
        """Mix multiple audio tracks into one file using ffmpeg.

        Body: {
            tracks: [{ path: str, start_time: float, volume: float }, ...],
            workspace: str | null
        }
        First track is the base (full duration). Subsequent tracks are overlaid at their start_time.
        Volume is 0.0-1.0.
        """
        return await impl["mix_audio"](request)

    @router.post("/api/v1/audio/analyze")
    async def analyze_audio(request: Request):
        """Analyze an audio file: beat detection, sections, optional transcription."""
        return await impl["analyze_audio"](request)

    @router.get("/api/v1/audio/analyze/status")
    def audio_analyze_status():
        """Read the current audio-analyze phase for live UI progress.

        Polled by the frontend during the synchronous /audio/analyze call
        so the user sees meaningful sub-status ("Loading transcription
        model (first use downloads ~300MB)..." vs "Transcribing audio...")
        instead of a single "Analyzing audio..." message for the entire
        1-5 minute wait.

        Returns {"step": "<phase>", "detail": "<human-readable message>"}.
        Both empty when no analyze is in flight.
        """
        return impl["audio_analyze_status"]()

    @router.post("/api/v1/audio/analyze/jobs")
    async def start_audio_analysis_job(request: Request):
        """Queue audio analysis and return immediately with a durable job id."""
        return await impl["start_audio_analysis_job"](request)

    @router.get("/api/v1/audio/analyze/jobs/{job_id}")
    def get_audio_analysis_job(job_id: str, workspace: str | None = None):
        return impl["get_audio_analysis_job"](job_id, workspace)

    @router.post("/api/v1/audio/analyze/jobs/{job_id}/cancel")
    def cancel_audio_analysis_job(job_id: str, workspace: str | None = None):
        return impl["cancel_audio_analysis_job"](job_id, workspace)

    @router.post("/api/v1/audio/suggest-clips")
    async def suggest_audio_clips(request: Request):
        """Suggest optimal clip boundaries aligned to musical structure."""
        return await impl["suggest_audio_clips"](request)

    return router


def create_audio_plan_router(*, wgp):
    """Mount plan-structure after the Director plan reads.

    Those reads stay between suggest-clips and this route, which is why
    the route is not part of create_audio_router.
    """
    globals().update({"wgp": wgp})
    router = APIRouter()
    _impl = globals()["plan_audio_structure"]

    @router.post("/api/v1/audio/plan-structure")
    async def plan_audio_structure(request: Request):
        """Plan variable-duration clip structure aligned to beats and sections."""
        return await _impl(request)

    return router
