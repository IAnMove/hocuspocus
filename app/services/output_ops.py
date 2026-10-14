"""Gallery thumbnail, metadata, extra info, rejoin, group, move and delete.

The handlers are the full server's functions, moved verbatim. ``configure``
binds the caller's workspace, favorites, seed recovery and model loader
before a request. The thumbnail cache directory is the same path the full
server built from ``app/_launch_runtime.py``.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import traceback
import uuid

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse

from services.media_dimensions import note_preview as _note_media_preview
from services.output_listing import _resolve_output_file

# dirname(app/_launch_runtime.py)/../cache/media-thumbnails, from app/services/.
_MEDIA_THUMBNAIL_CACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "cache",
    "media-thumbnails",
)

_workspace_dir = None
_safe_join = None
_extract_output_seed = None
_load_favorites = None
_save_favorites = None
_resolve_output_move_path = None
_ensure_llm_loaded = None


def configure(
    *,
    workspace_dir,
    safe_join,
    extract_output_seed,
    load_favorites,
    save_favorites,
    resolve_output_move_path,
    ensure_llm_loaded,
) -> None:
    """Bind the caller's workspace, favorites, seed recovery and model loader."""
    global _workspace_dir, _safe_join, _extract_output_seed, _load_favorites
    global _save_favorites, _resolve_output_move_path, _ensure_llm_loaded
    _workspace_dir = workspace_dir
    _safe_join = safe_join
    _extract_output_seed = extract_output_seed
    _load_favorites = load_favorites
    _save_favorites = save_favorites
    _resolve_output_move_path = resolve_output_move_path
    _ensure_llm_loaded = ensure_llm_loaded


def _resolve_gallery_file(filename: str, workspace: str | None = None) -> str | None:
    """An output in ``workspace``, or an upload for the virtual Uploads view."""
    if workspace == "__uploads__":
        source = _safe_join(os.path.join(os.getcwd(), "uploads"), filename)
        return source if source and os.path.isfile(source) else None
    return _resolve_output_file(filename, workspace)

def serve_output_thumbnail(filename: str, workspace: str | None = None, size: str | None = None):
    """Lazily create one small static preview for an image or video output."""
    from services.media_thumbnails import FITTED_THUMBNAIL_SIZES, ensure_fitted_thumbnail, ensure_media_thumbnail

    source = _resolve_gallery_file(filename, workspace)
    if not source:
        raise HTTPException(status_code=404, detail="Output not found")
    extension = os.path.splitext(source)[1].lower()
    image_extensions = {".png", ".jpg", ".jpeg", ".webp"}
    video_extensions = {".mp4", ".webm", ".gif", ".mov", ".mkv", ".avi", ".m4v"}
    if extension not in image_extensions | video_extensions:
        raise HTTPException(status_code=400, detail="This output has no media thumbnail")
    if size is not None and size not in FITTED_THUMBNAIL_SIZES:
        raise HTTPException(status_code=400, detail="Unknown thumbnail size")
    try:
        is_video = extension in video_extensions
        thumbnail = (ensure_fitted_thumbnail(source, _MEDIA_THUMBNAIL_CACHE_DIR, is_video=is_video, size=size)
                     if size else ensure_media_thumbnail(source, _MEDIA_THUMBNAIL_CACHE_DIR, is_video=is_video))
        if size:
            _note_media_preview(source, thumbnail)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not create thumbnail: {exc}") from exc
    return FileResponse(
        thumbnail,
        media_type="image/webp" if thumbnail.endswith(".webp") else "image/jpeg",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )

def get_output_metadata(name: str, workspace: str | None = None):
    """Get metadata for an output file. Tries sidecar first, then embedded."""
    out_dir = _workspace_dir(workspace)
    filepath = _safe_join(out_dir, name)
    if filepath is None or not os.path.isfile(filepath):
        raise HTTPException(status_code=404, detail="Output file not found")

    # Helper: read embedded metadata from the media file
    def _read_embedded():
        ext = os.path.splitext(name)[1].lower()
        try:
            if ext in (".mp4", ".mkv"):
                from shared.utils.video_metadata import read_metadata_from_video
                return read_metadata_from_video(filepath)
            elif ext in (".png", ".jpg", ".jpeg", ".webp"):
                from shared.utils.audio_video import read_image_metadata
                return read_image_metadata(filepath)
            elif ext in (".wav", ".mp3"):
                from shared.utils.audio_metadata import read_audio_metadata
                return read_audio_metadata(filepath)
        except Exception:
            pass
        return None

    # Strategy 1: Read sidecar .meta.json
    meta_path = os.path.join(out_dir, os.path.splitext(name)[0] + ".meta.json")
    if os.path.isfile(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                sidecar = json.load(f)
            # Merge actual seed from embedded metadata if sidecar has seed=-1
            params = sidecar.get("params", {})
            if params.get("seed", -1) == -1:
                embedded = _read_embedded()
                if embedded and "seed" in embedded:
                    params["seed"] = embedded["seed"]
                else:
                    resolved_seed = _extract_output_seed(name)
                    if resolved_seed is not None:
                        params["seed"] = resolved_seed
            # Legacy Director finals may contain a wall-clock total (including
            # review/stopped time) and only a pipeline ID in params. Recover
            # active timings plus the exact model and resolution from the
            # checkpoint. New sidecars carry the basis and render context, so
            # they avoid the extra checkpoint read.
            pipeline_id = (
                sidecar.get("director_pipeline_id")
                or params.get("director_pipeline_id")
                or params.get("_director_pipeline_id")
            )
            needs_pipeline_context = bool(
                pipeline_id
                and (
                    sidecar.get("generation_timing_basis") != "active_stages"
                    or not params.get("model_type")
                    or not params.get("resolution")
                )
            )
            if needs_pipeline_context:
                from services.director_pipeline import (
                    enrich_output_metadata_with_pipeline_timing,
                    load_pipeline_state,
                )
                pipeline = load_pipeline_state(out_dir, str(pipeline_id))
                if pipeline:
                    sidecar = enrich_output_metadata_with_pipeline_timing(
                        sidecar,
                        pipeline,
                    )
            return {"source": "sidecar", **sidecar}
        except Exception:
            pass

    # Strategy 2: Read embedded metadata from media file
    embedded = _read_embedded()
    if embedded:
        return {"source": "embedded", "params": embedded}

    return {"source": "none", "params": None}

def _saved_video_context_for_extra_info(name: str):
    """Load sidecar/pipeline context without reading the media itself."""
    out_dir = _workspace_dir()
    filepath = _safe_join(out_dir, name)
    if filepath is None or not os.path.isfile(filepath):
        raise HTTPException(status_code=404, detail="Output video not found")
    if os.path.splitext(filepath)[1].lower() not in {".mp4", ".mkv", ".webm", ".mov", ".gif"}:
        raise HTTPException(status_code=400, detail="Extra info is available for videos only")

    meta_path = os.path.splitext(filepath)[0] + ".meta.json"
    if not os.path.isfile(meta_path):
        raise HTTPException(
            status_code=400,
            detail="This video has no saved prompt metadata; media re-analysis is disabled",
        )
    try:
        with open(meta_path, "r", encoding="utf-8") as handle:
            metadata = json.load(handle)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=500, detail="Could not read the video's saved metadata") from error
    if not isinstance(metadata, dict):
        raise HTTPException(status_code=500, detail="The video's saved metadata is invalid")

    params = metadata.get("params") if isinstance(metadata.get("params"), dict) else {}
    pipeline_id = (
        metadata.get("director_pipeline_id")
        or params.get("director_pipeline_id")
        or params.get("_director_pipeline_id")
    )
    pipeline = None
    # Pipeline IDs are generated as short hex strings. Validate before asking
    # for its checkpoint filename. Read that JSON directly: the Extra info
    # feature must not invoke media recovery/reconciliation or analyse frames.
    if pipeline_id and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", str(pipeline_id)):
        pipeline_path = _safe_join(out_dir, f"_director_pipeline_{pipeline_id}.json")
        if pipeline_path and os.path.isfile(pipeline_path):
            try:
                with open(pipeline_path, "r", encoding="utf-8") as handle:
                    candidate = json.load(handle)
                if isinstance(candidate, dict):
                    pipeline = candidate
            except (OSError, ValueError, json.JSONDecodeError):
                pipeline = None

    if pipeline and (
        metadata.get("generation_timing_basis") != "active_stages"
        or not params.get("model_type")
        or not params.get("resolution")
    ):
        from services.director_pipeline import enrich_output_metadata_with_pipeline_timing
        metadata = enrich_output_metadata_with_pipeline_timing(metadata, pipeline)

    from services.video_extra_info import build_saved_clip_info, build_saved_video_context
    context = build_saved_video_context(metadata, pipeline)
    try:
        file_stat = os.stat(filepath)
        file_size_bytes = file_stat.st_size
        file_modified_at = file_stat.st_mtime
    except OSError:
        file_size_bytes = 0
        file_modified_at = None
    clip = build_saved_clip_info(
        name,
        metadata, pipeline=pipeline,
        file_size_bytes=file_size_bytes,
        file_modified_at=file_modified_at,
    )
    return meta_path, metadata, context, clip

def get_video_extra_info(name: str, language: str = "en"):
    """Return cached publishing copy for one language, if it exists."""
    from services.video_extra_info import normalize_language

    try:
        code, label = normalize_language(language)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    _, metadata, context, clip = _saved_video_context_for_extra_info(name)
    stored = metadata.get("video_extra_info")
    cached = stored.get(code) if isinstance(stored, dict) else None
    # Ignore stale copy if a sidecar/pipeline prompt was edited after it was
    # generated. The next explicit Generate click refreshes and persists it.
    available = bool(
        isinstance(cached, dict)
        and cached.get("source_fingerprint") == context.get("source_fingerprint")
    )
    return {
        "available": available,
        "language": code,
        "language_label": label,
        "data": cached if available else None,
        "prompt_count": context.get("prompt_count", 0),
        "director_context": context.get("director_context", False),
        "clip": clip,
    }

async def generate_output_extra_info(name: str, request: Request):
    """Generate and persist platform copy from saved prompts only."""
    from services import llm_service
    from services.video_extra_info import (
        generate_video_extra_info,
        normalize_language,
    )

    body = await request.json()
    try:
        code, _ = normalize_language(body.get("language", "en"))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    meta_path, metadata, context, _ = _saved_video_context_for_extra_info(name)
    stored = metadata.get("video_extra_info")
    cached = stored.get(code) if isinstance(stored, dict) else None
    if (
        not body.get("regenerate")
        and isinstance(cached, dict)
        and cached.get("source_fingerprint") == context.get("source_fingerprint")
    ):
        return {"cached": True, "data": cached}

    try:
        _ensure_llm_loaded()
        generated = generate_video_extra_info(context, code, llm_service.generate)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(error)) from error

    generated["generated_at"] = time.time()
    latest = metadata
    try:
        # Re-read before the atomic update so another metadata writer cannot
        # be accidentally discarded while the LLM is working.
        with open(meta_path, "r", encoding="utf-8") as handle:
            candidate = json.load(handle)
        if isinstance(candidate, dict):
            latest = candidate
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    saved = latest.get("video_extra_info")
    if not isinstance(saved, dict):
        saved = {}
        latest["video_extra_info"] = saved
    saved[code] = generated
    temp_path = f"{meta_path}.{uuid.uuid4().hex[:8]}.tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(latest, handle, indent=2, ensure_ascii=False, default=str)
        os.replace(temp_path, meta_path)
    except OSError as error:
        try:
            if os.path.isfile(temp_path):
                os.remove(temp_path)
        except OSError:
            pass
        raise HTTPException(status_code=500, detail="Could not save generated extra info") from error
    return {"cached": False, "data": generated}

def rejoin_clips(body: dict):
    """Re-concatenate clips from a multi-clip group.

    Body: { group_id: str, audio_file?: str }
    Finds all clip files matching the group_id and re-concatenates them.
    """
    from services.mix_concat import concatenate_multi_clip_videos
    group_id = body.get("group_id")
    if not group_id:
        raise HTTPException(status_code=400, detail="group_id is required")

    out_dir = _workspace_dir()
    # Scan all sidecar files to find clips belonging to this group
    clips_by_index: dict[int, dict] = {}
    audio_path = None
    audio_start_sec = 0.0
    for fname in os.listdir(out_dir):
        if not fname.endswith(".meta.json"):
            continue
        meta_path = os.path.join(out_dir, fname)
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            params = meta.get("params", {})
            mci = params.get("multi_clip_info")
            if not mci or mci.get("group_id") != group_id:
                continue
            media_name = fname.replace(".meta.json", "")
            # Try common extensions
            media_path = None
            for ext in (".mp4", ".mkv", ".webm"):
                candidate = os.path.join(out_dir, media_name + ext)
                if os.path.isfile(candidate):
                    media_path = candidate
                    break
            if not media_path:
                continue
            clips_by_index[mci["index"]] = {
                "path": media_path,
                "total": mci["total"],
            }
            # Get audio from first clip's params
            if mci["index"] == 0 and not audio_path:
                ag = mci.get("concat_audio_path") or params.get("audio_guide", "")
                if ag and os.path.isfile(ag):
                    audio_path = ag
                    try:
                        audio_start_sec = max(
                            0.0, float(mci.get("audio_start_sec", 0) or 0),
                        )
                    except (TypeError, ValueError):
                        audio_start_sec = 0.0
        except Exception:
            continue

    if not clips_by_index:
        raise HTTPException(status_code=404, detail=f"No clips found for group {group_id}")

    total = max(c["total"] for c in clips_by_index.values())
    # Build ordered list of clip paths
    clip_paths = []
    for i in range(total):
        if i in clips_by_index:
            clip_paths.append(clips_by_index[i]["path"])
        else:
            print(f"[Rejoin] Warning: missing clip index {i} for group {group_id}")

    if len(clip_paths) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 clips to rejoin")

    # Allow override audio from request body
    body_audio = body.get("audio_file")
    if body_audio and os.path.isfile(body_audio):
        audio_path = body_audio

    # Generate output path
    import time
    timestamp = time.strftime("%Y-%m-%d_%H%M%S")
    concat_name = f"{timestamp}_rejoin_multiclip.mp4"
    concat_path = os.path.join(out_dir, concat_name)

    success = concatenate_multi_clip_videos(
        clip_paths,
        concat_path,
        audio_path,
        audio_start_sec=audio_start_sec,
    )
    if not success or not os.path.isfile(concat_path):
        raise HTTPException(status_code=500, detail="Concatenation failed")

    return {"filename": concat_name, "clip_count": len(clip_paths)}

def get_group_clips(group_id: str):
    """Get all clip files belonging to a multi-clip group."""
    out_dir = _workspace_dir()
    clips: list[dict] = []
    for fname in os.listdir(out_dir):
        if not fname.endswith(".meta.json"):
            continue
        meta_path = os.path.join(out_dir, fname)
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            params = meta.get("params", {})
            mci = params.get("multi_clip_info")
            if not mci or mci.get("group_id") != group_id:
                continue
            media_name = fname.replace(".meta.json", "")
            media_file = None
            for ext in (".mp4", ".mkv", ".webm"):
                candidate = media_name + ext
                if os.path.isfile(os.path.join(out_dir, candidate)):
                    media_file = candidate
                    break
            if media_file:
                clips.append({
                    "filename": media_file,
                    "index": mci["index"],
                    "total": mci["total"],
                    "prompt": params.get("prompt", ""),
                })
        except Exception:
            continue
    clips.sort(key=lambda c: c["index"])
    return {"group_id": group_id, "clips": clips}

async def move_output(name: str, request: Request):
    """Move an output file and its sidecar metadata to another workspace."""
    import shutil

    body = await request.json()
    target_ws = body.get("workspace", "")
    if not target_ws:
        raise HTTPException(status_code=400, detail="workspace is required")

    import re as _re
    if target_ws != "default" and not _re.match(r'^[a-zA-Z0-9][a-zA-Z0-9_-]*$', target_ws):
        raise HTTPException(status_code=400, detail="Invalid workspace name")

    src_dir = _workspace_dir(body.get("source_workspace") or None)
    dst_dir = _workspace_dir(target_ws)
    if os.path.realpath(src_dir) == os.path.realpath(dst_dir):
        raise HTTPException(status_code=400, detail="Already in that workspace")

    src_file = _resolve_output_move_path(src_dir, name)
    dst_file = _resolve_output_move_path(dst_dir, name)
    if not src_file or not dst_file:
        raise HTTPException(status_code=400, detail="Invalid output path")
    if not os.path.isfile(src_file):
        print(f"[Move] File not found: {name}")
        raise HTTPException(status_code=404, detail="File not found")

    os.makedirs(os.path.dirname(dst_file), exist_ok=True)
    print(f"[Move] {name} -> {target_ws}")

    try:
        shutil.move(src_file, dst_file)
    except PermissionError:
        # File locked by browser — copy to destination, then deferred cleanup of source
        import gc
        gc.collect()
        try:
            # Copy may have already happened during shutil.move's internal copy+delete
            if not os.path.isfile(dst_file):
                shutil.copy2(src_file, dst_file)
            # Source is locked — schedule background deletion
            def _deferred_source_delete(path):
                for _ in range(30):
                    time.sleep(3)
                    try:
                        gc.collect()
                        os.remove(path)
                        print(f"[Move] Deferred source cleanup: {os.path.basename(path)}")
                        return
                    except Exception:
                        pass
                # Last resort: rename to hidden trash
                try:
                    trash = os.path.join(os.path.dirname(path), f".trash_{int(time.time())}_{os.path.basename(path)}")
                    os.rename(path, trash)
                except Exception:
                    print(f"[Move] Warning: could not clean up source: {os.path.basename(path)}")
            threading.Thread(target=_deferred_source_delete, args=(src_file,), daemon=True).start()
            print(f"[Move] File copied to {target_ws}, source cleanup deferred")
        except Exception as e:
            print(f"[Move] Copy failed: {e}")
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Failed to move file: {e}")
    except Exception as e:
        print(f"[Move] Failed: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to move file: {e}")

    # Move sidecar metadata and the 3D card preview image, when present
    for sidecar_name in (os.path.splitext(name)[0] + ".meta.json", os.path.splitext(name)[0] + ".preview.png"):
        src_sidecar = _resolve_output_move_path(src_dir, sidecar_name)
        dst_sidecar = _resolve_output_move_path(dst_dir, sidecar_name)
        if src_sidecar and dst_sidecar and os.path.isfile(src_sidecar):
            try:
                os.makedirs(os.path.dirname(dst_sidecar), exist_ok=True)
                shutil.move(src_sidecar, dst_sidecar)
            except Exception:
                pass

    # Update favorites (lock held across the read-modify-write)
    from services.win_safe_files import favorites_lock
    with favorites_lock:
        favs = _load_favorites()
        if name in favs:
            favs.discard(name)
            _save_favorites(favs)

    return {"moved": name, "to": target_ws}

def delete_output(name: str, workspace: str | None = None):
    """Delete an output file and its sidecar metadata.

    Uses safe_delete() which handles Windows file-lock edge cases:
        1. Tries os.remove directly (works when share-delete was used
           on the serve side — the new default since this commit).
        2. Falls back to renaming to a hidden ".trash_*" sibling that
           the gallery filters out, plus a background queue that retries
           the actual delete every few seconds for up to 30 minutes.
        3. As a last resort returns {"deleted": False, "reason": "locked"}
           — but with share-delete on the serve side this is now nearly
           impossible to reach in normal use.

    ``workspace`` is the folder the gallery was listing. Without it the
    active workspace is used, which is wrong if another tab switched
    folders while a batch delete was still in flight.
    """
    import gc
    from services.win_safe_files import safe_delete
    out_dir = _workspace_dir(workspace)
    filepath = _safe_join(out_dir, name)
    if filepath is None or not os.path.isfile(filepath):
        return {"deleted": name}

    # Hint the GC to drop any lingering references (e.g. PIL image
    # objects from a recent metadata read) BEFORE we try to delete.
    gc.collect()

    result = safe_delete(filepath)
    if result.get("deferred"):
        print(f"[Delete] {name}: deferred — file renamed for background cleanup")
    elif result.get("deleted"):
        pass  # immediate success, no log needed
    else:
        print(f"[Delete] {name}: {result.get('reason', 'unknown')} — UI will still treat as deleted")

    # Delete sidecar metadata (small JSON, virtually never locked)
    meta_path = os.path.join(out_dir, os.path.splitext(name)[0] + ".meta.json")
    if os.path.isfile(meta_path):
        try:
            os.remove(meta_path)
        except Exception:
            pass

    # Delete the 3D card preview image if one was saved alongside the model
    preview_path = os.path.join(out_dir, os.path.splitext(name)[0] + ".preview.png")
    if os.path.isfile(preview_path):
        try:
            os.remove(preview_path)
        except Exception:
            pass

    # Remove from favorites (lock held across the read-modify-write)
    from services.win_safe_files import favorites_lock
    with favorites_lock:
        favs = _load_favorites()
        if name in favs:
            favs.discard(name)
            _save_favorites(favs)

    # Remove from search index
    try:
        from services.search_index import get_search_index
        get_search_index().remove_file(name)
    except Exception:
        pass

    return {"deleted": name}
