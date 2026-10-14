"""Gallery listing and file serving shared by both servers.

``list_outputs``, ``_resolve_output_file`` and ``serve_file`` are the full
server's functions, moved verbatim. ``configure`` binds the caller's
workspace, favorites and engine before a request. The scan cache lives
here: one dict and one lock per process. The full server keeps aliases
of those same objects.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from urllib.parse import quote

from fastapi import HTTPException, Response

_output_scan_cache_lock = threading.Lock()
_output_scan_cache: dict[str, dict] = {}
_OUTPUT_SCAN_CACHE_MAX_AGE_SECONDS = 5.0

_workspace_dir = None
_safe_join = None
wgp = None


def _load_favorites() -> set:
    """Empty until ``configure`` binds the caller's favorites."""
    return set()


def configure(*, workspace_dir, load_favorites, safe_join, engine) -> None:
    """Bind the caller's workspace, favorites, path join and engine."""
    global _workspace_dir, _load_favorites, _safe_join, wgp
    _workspace_dir = workspace_dir
    _load_favorites = load_favorites
    _safe_join = safe_join
    wgp = engine


def _resolve_output_file(filename: str, workspace: str | None = None) -> str | None:
    """Resolve one output only inside its explicit or active workspace."""
    root = _workspace_dir(workspace)
    candidate = _safe_join(root, filename)
    return candidate if candidate and os.path.isfile(candidate) else None


def list_outputs(response: Response, limit: int = 0, offset: int = 0, favorites_only: bool = False, multiclip_only: bool = False, edits_only: bool = False, search: str = "", workspace: str = "", media_type: str = "", result_kind: str = "", order: str = "", origin: str = ""):
    """List generated output files (newest first) from the active workspace.

    Each row carries ``origin`` ({actor: agent | wizard, capability}) when an agent or the Wizard asked for the file,
    and ``origin=agent`` keeps only those (``mcp`` or ``wizard`` one of them; services/output_origin.py).

    Supports pagination via limit/offset query params.
    Returns {outputs, total} where total is the full count before pagination.
    When limit=0 (default), returns all items (backwards compatible).

    workspace="__uploads__" lists the uploads folder instead (the gallery's
    virtual "Uploads" view) so user-supplied media can be previewed and
    reused. Browse-only: the server-side active workspace is untouched and
    generations never save here. Uploads have no sidecars, so the metadata
    passes below fall through naturally.
    """
    response.headers["Cache-Control"] = "no-store"
    if workspace == "__uploads__":
        out_dir = os.path.join(os.getcwd(), "uploads")
    else:
        out_dir = _workspace_dir(workspace or None)
    workspace_suffix = (
        f"?workspace={quote(workspace, safe='')}" if workspace else ""
    )
    workspace_extra = (
        f"&workspace={quote(workspace, safe='')}" if workspace else ""
    )
    if not os.path.isdir(out_dir):
        return {"outputs": [], "total": 0}

    media_exts = {".mp4", ".webm", ".gif", ".png", ".jpg", ".jpeg", ".webp", ".wav", ".mp3", ".glb", ".gltf", ".obj", ".ply", ".stl", ".usdz", ".zip"}
    video_exts = {".mp4", ".webm", ".gif"}
    audio_exts = {".wav", ".mp3"}
    model3d_exts = {".glb", ".gltf", ".obj", ".ply", ".stl", ".usdz", ".zip"}

    def model3d_thumbnail_url(name: str, params: dict) -> str | None:
        """Return a cheap static image preview for a 3D output card.

        The gallery must never instantiate a second ``model-viewer`` for its
        80px history cards: parsing many GLB files there is surprisingly
        expensive.  The Hunyuan3D worker saves the normalized front view as a
        ``<output>.preview.png`` sibling (for text-only jobs that is the
        generated conditioning image), so prefer it.  Older outputs fall back
        to the input views recorded in the sidecar; when neither exists the
        client renders a lightweight 3D icon instead.
        """
        preview_name = os.path.splitext(name)[0] + ".preview.png"
        if os.path.isfile(os.path.join(out_dir, preview_name)):
            return f"/api/v1/file/{preview_name}{workspace_suffix}"
        images = params.get("images")
        if not isinstance(images, dict):
            return None
        front = images.get("front")
        if not isinstance(front, str) or not front:
            return None
        try:
            source = os.path.realpath(front)
            if not os.path.isfile(source):
                return None
            uploads_root = os.path.realpath(os.path.join(os.getcwd(), "uploads"))
            outputs_root = os.path.realpath(wgp.server_config.get("save_path", "outputs"))
            filename = os.path.basename(source)
            if source.startswith(uploads_root + os.sep):
                return f"/api/v1/uploads/{filename}"
            if source.startswith(outputs_root + os.sep):
                return f"/api/v1/file/{filename}{workspace_suffix}"
        except OSError:
            pass
        return None

    favs = _load_favorites()

    # Building the gallery index requires stat'ing every media file and
    # parsing every metadata sidecar. The UI polls while a generation is
    # active, so doing that work on each heartbeat caused unnecessary disk
    # load and visible layout churn. Reuse a workspace snapshot while the
    # directory is unchanged, with a short TTL as a safety net for in-place
    # metadata edits that do not update the directory mtime.
    try:
        directory_signature = os.stat(out_dir).st_mtime_ns
    except OSError:
        return {"outputs": [], "total": 0}
    now = time.monotonic()
    with _output_scan_cache_lock:
        cached_snapshot = _output_scan_cache.get(out_dir)
        cache_is_fresh = (
            cached_snapshot is not None
            and cached_snapshot.get("signature") == directory_signature
            and now - float(cached_snapshot.get("created_at", 0)) < _OUTPUT_SCAN_CACHE_MAX_AGE_SECONDS
        )

    if cache_is_fresh:
        raw_entries = cached_snapshot["raw_entries"]
        sidecar_cache = cached_snapshot["sidecar_cache"]
        clip_groups = cached_snapshot["clip_groups"]
    else:
        raw_entries = []
        for name in os.listdir(out_dir):
            # Director's historical H3 builds wrote soundtrack slices beside
            # user assets. They are private model inputs, not generated songs.
            # New runs use the hidden .director-tmp directory; retain these
            # prefix guards so scratch files left by an interrupted old run do
            # not displace the real soundtrack in the media library.
            if name.startswith((
                ".trash_",
                ".",
                "_director_h3_audio_",
                "_rerun_audio_",
            )):
                continue
            # 3D preview sidecars are served as card thumbnails, not gallery items.
            if name.endswith(".preview.png"):
                continue
            # Atomic image writes keep a media extension for PIL. They are
            # incomplete until renamed and must never become gallery tiles.
            if re.search(r"\.tmp_[0-9a-f]{8}\.[^.]+$", name):
                continue
            filepath = os.path.join(out_dir, name)
            if not os.path.isfile(filepath):
                continue
            ext = os.path.splitext(name)[1].lower()
            if ext not in media_exts and not name.endswith(".scene.json") and not name.endswith(".comic.json"):
                continue
            try:
                raw_entries.append((name, filepath, ext, os.path.getmtime(filepath)))
            except OSError:
                continue

        # Sort by creation time (newest first) before any filtering.
        raw_entries.sort(key=lambda e: e[3], reverse=True)

        # Read each sidecar once per snapshot and retain only the fields used
        # by the gallery. Favorites remain outside the cache so toggles are
        # reflected immediately.
        sidecar_cache: dict[str, dict] = {}
        clip_groups: dict[str, dict] = {}
        try:
            from services.output_result_kind import classify_output_result_kind, production_cuts, production_result_kind
            cuts = production_cuts(out_dir)
        except Exception:
            def classify_output_result_kind(name, params=None, metadata=None):
                return None
            def production_result_kind(name, params, cuts):
                return None
            cuts = {}
        from services.output_origin import output_origin
        for name, filepath, ext, mtime in raw_entries:
            meta_path = os.path.join(out_dir, os.path.splitext(name)[0] + ".meta.json")
            if not os.path.isfile(meta_path):
                continue
            try:
                with open(meta_path, "r", encoding="utf-8") as mf:
                    meta = json.load(mf)
            except Exception:
                continue
            params = meta.get("params") if isinstance(meta.get("params"), dict) else {}
            sidecar_cache[name] = {
                "origin": output_origin(meta),
                "mode": meta.get("generation_mode"),
                "edit_sub_mode": params.get("edit_sub_mode"),
                "multi_clip_info": params.get("multi_clip_info"),
                "resolution": params.get("resolution"),
                "result_kind": classify_output_result_kind(name, params, meta) or production_result_kind(name, params, cuts),
                "thumbnail_url": model3d_thumbnail_url(name, params) if ext in model3d_exts else None,
                # Output sidecars are written only after the generated asset
                # has been published.  Their historical ``created_at`` field
                # therefore represents completion time, despite the old name.
                # Prefer an explicit completion field when newer producers
                # provide one and retain mtime as the legacy/import fallback.
                "completed_at": next((
                    float(meta[key])
                    for key in ("completed_at", "finished_at", "created_at")
                    if isinstance(meta.get(key), (int, float)) and float(meta[key]) > 0
                ), None),
            }
            mci = sidecar_cache[name]["multi_clip_info"]
            if mci and mci.get("group_id"):
                gid = mci["group_id"]
                if gid not in clip_groups:
                    clip_groups[gid] = {"total": mci.get("total", 0), "highest_index": -1, "has_final": False}
                clip_groups[gid]["highest_index"] = max(clip_groups[gid]["highest_index"], mci.get("index", 0))

        for info in clip_groups.values():
            if info["highest_index"] >= info["total"] - 1:
                info["has_final"] = True

        with _output_scan_cache_lock:
            if len(_output_scan_cache) >= 16 and out_dir not in _output_scan_cache:
                oldest = min(
                    _output_scan_cache,
                    key=lambda key: float(_output_scan_cache[key].get("created_at", 0)),
                )
                _output_scan_cache.pop(oldest, None)
            _output_scan_cache[out_dir] = {
                "signature": directory_signature,
                "created_at": now,
                "raw_entries": raw_entries,
                "sidecar_cache": sidecar_cache,
                "clip_groups": clip_groups,
            }

    # Second pass: build the file list using the cached sidecar data.
    from services.media_dimensions import listing_fields as media_listing_fields
    files = []
    for name, filepath, ext, mtime in raw_entries:
        is_scene = name.endswith(".scene.json")
        is_comic = name.endswith(".comic.json")
        ftype = "comic" if is_comic else ("scene" if is_scene else ("video" if ext in video_exts else ("audio" if ext in audio_exts else ("model3d" if ext in model3d_exts else "image"))))
        cached = sidecar_cache.get(name) or {}
        mode = cached.get("mode")
        edit_sub_mode = cached.get("edit_sub_mode")
        metadata_completed_at = cached.get("completed_at")
        mci = cached.get("multi_clip_info")
        is_intermediate_clip = False
        if mci and mci.get("group_id"):
            gid = mci["group_id"]
            group = clip_groups.get(gid, {})
            if group.get("has_final"):
                is_intermediate_clip = True
            elif mci.get("index", 0) < group.get("highest_index", 0):
                is_intermediate_clip = True

        if is_intermediate_clip:
            continue
        # The file may vanish between os.scandir() and here (temp files renamed
        # mid-generation, etc.). Skip the entry rather than crashing the endpoint.
        try:
            size = os.path.getsize(filepath)
        except (FileNotFoundError, OSError):
            continue
        files.append({
            "name": name,
            "type": ftype,
            "mode": mode,
            # Surface edit_sub_mode so the gallery's Edits filter can
            # identify retake/inpaint/outpaint/restyle/edit_anything outputs.
            "edit_sub_mode": edit_sub_mode,
            "result_kind": cached.get("result_kind"),
            "origin": cached.get("origin"),
            "favorite": name in favs,
            "size": size,
            "created_at": mtime,
            "completed_at": metadata_completed_at or mtime,
            "completion_time_source": "metadata" if metadata_completed_at else "file",
            "url": f"/api/v1/file/{name}{workspace_suffix}",
            "thumbnail_url": (
                f"/api/v1/file/{name[:-len('.comic.json')]}.comic.preview.png{workspace_suffix}"
                if is_comic and os.path.isfile(os.path.join(out_dir, name[:-len(".comic.json")] + ".comic.preview.png"))
                else (f"/api/v1/file/{os.path.splitext(name)[0]}.preview.png{workspace_suffix}"
                      if is_scene and os.path.isfile(os.path.join(out_dir, os.path.splitext(name)[0] + ".preview.png"))
                      else (f"/api/v1/outputs/thumbnail/{quote(name, safe='')}?v={int(mtime * 1_000_000)}-{size}{workspace_extra}"
                            if ftype in {"image", "video"}
                            else cached.get("thumbnail_url")))
            ),
        })

    def listed_result(selected, total):
        # Read image headers and schedule colour/size work only for this page,
        # not the entire workspace on every gallery heartbeat.
        for item in selected:
            item.update(media_listing_fields(
                item["type"], os.path.join(out_dir, item["name"]),
                item["size"], item["created_at"],
                (sidecar_cache.get(item["name"]) or {}).get("resolution"),
            ))
        return {"outputs": selected, "total": total}

    if media_type:
        files = [item for item in files if item["type"] == media_type]
    from services.output_origin import filter_by_origin
    files = filter_by_origin(files, origin)
    # Ordered before paging so every page follows the gallery's chosen order.
    if order == "oldest":
        files.reverse()
    elif order == "favorites":
        files.sort(key=lambda item: not item["favorite"])

    wanted_kind = str(result_kind or "").strip()
    if wanted_kind:
        try:
            from services.output_result_kind import result_kind_matches_filter
        except Exception:
            def result_kind_matches_filter(kind, wanted):
                return str(kind or "") == str(wanted or "")
        files = [
            item for item in files
            if item.get("type") == "video"
            and result_kind_matches_filter(item.get("result_kind"), wanted_kind)
        ]
        return listed_result(files, len(files))

    # Special filters: return ALL matches, bypass pagination
    if edits_only:
        files = [
            item for item in files
            if item.get("edit_sub_mode") or item.get("mode") == "avatar"
        ]
        return listed_result(files, len(files))
    if favorites_only:
        files = [f for f in files if f["favorite"]]
        return listed_result(files, len(files))
    if multiclip_only:
        # 1. Explicit multiclip files
        multiclips = [f for f in files if "multiclip" in f["name"].lower() and f["type"] == "video"]
        multiclip_names = {f["name"] for f in multiclips}

        # 2. Sliding window final outputs: group videos by seed+prompt, keep only the largest
        # Filename pattern: datetime_seedNNNN_prompt_text.mp4
        import re as _re_mc
        seed_pattern = _re_mc.compile(r'^\d{4}-\d{2}-\d{2}-\d{2}h\d{2}m\d{2}s_(seed\d+_.+)\.(mp4|webm|mkv)$', _re_mc.IGNORECASE)
        groups: dict[str, list[dict]] = {}
        for f in files:
            if f["type"] != "video" or f["name"] in multiclip_names:
                continue
            # Skip tmp files
            if "_tmp." in f["name"]:
                continue
            m = seed_pattern.match(f["name"])
            if m:
                group_key = m.group(1)  # seed123_prompt text
                groups.setdefault(group_key, []).append(f)

        # From groups with multiple files (sliding window), keep only the largest
        sw_finals = []
        print(f"[Multiclip] Found {len(groups)} seed+prompt groups from {len(files)} total files")
        for group_key, group_files in groups.items():
            if len(group_files) > 1:
                # Verify files are close in time (within 2 hours)
                times = [f["created_at"] for f in group_files]
                time_span = max(times) - min(times)
                if time_span < 7200:
                    largest = max(group_files, key=lambda f: f["size"])
                    print(f"[Multiclip] SW group '{group_key[:60]}': {len(group_files)} files, span={time_span:.0f}s, largest={largest['name'][:60]}")
                    sw_finals.append(largest)
                else:
                    print(f"[Multiclip] SW group '{group_key[:60]}': {len(group_files)} files, SKIPPED (time span {time_span:.0f}s > 7200)")

        combined = multiclips + sw_finals
        combined.sort(key=lambda f: f["created_at"], reverse=True)
        print(f"[Multiclip] Result: {len(multiclips)} multiclips + {len(sw_finals)} sliding window finals = {len(combined)} total")
        return listed_result(combined, len(combined))
    if search:
        from services.search_index import get_search_index
        idx = get_search_index()
        matching_names = idx.search(search, out_dir)
        # Combine index results with filename fallback (in case index missed
        # a file that was created between index builds)
        query_lower = search.lower()
        # The index is keyed by sidecar stem ("clip" for clip.mp4 and
        # clip.meta.json); comparing full names never matched a prompt.
        files = [
            f for f in files
            if os.path.splitext(f["name"])[0] in matching_names or query_lower in f["name"].lower()
        ]
        return listed_result(files, len(files))

    total = len(files)
    if limit > 0:
        files = files[offset:offset + limit]
    return listed_result(files, total)


def serve_file(filename: str, workspace: str | None = None, sha256: str | None = None):
    """Serve an output file from the explicit or active workspace.

    Uses share_delete_file_response so that on Windows the file can be
    deleted/renamed by the gallery delete button even while the browser
    is actively streaming it (e.g. mid-video playback). Without share-
    delete, Python's default open() locks the file for delete and the
    user has to close the entire app to clean up.
    """
    from services.win_safe_files import share_delete_file_response
    filepath = _resolve_output_file(filename, workspace)
    if filepath:
        return share_delete_file_response(filepath, expected_sha256=sha256)
    # Uploads folder — the gallery's virtual "Uploads" view lists these
    #    files with the same /api/v1/file/ URLs every other gallery flow
    #    builds (thumbnails, playback, send-to-input). Upload names are
    #    hash-uniquified at upload time, and outputs are checked first, so
    #    an output name can never be shadowed by an upload.
    filepath = _safe_join(os.path.join(os.getcwd(), "uploads"), filename) if workspace in {None, "", "__uploads__"} else None
    if filepath and os.path.isfile(filepath):
        return share_delete_file_response(filepath, expected_sha256=sha256)
    raise HTTPException(status_code=404, detail="File not found")

