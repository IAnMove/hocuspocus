"""Seek-friendly local video copies for the native frame-by-frame compositor.

Every frame is independently decodable. Original assets and saved documents stay
unchanged; transparent VP9 keeps its alpha channel. Remote URLs are never fetched.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import time
from urllib.parse import parse_qs, quote, unquote, urlsplit


LIMIT = 2 * 1024**3
MAX_PROXY = 512 * 1024**2


def local_video(url, workspace, workspace_root, app_root):
    parsed = urlsplit(str(url or ""))
    if parsed.scheme or parsed.netloc:
        return None
    path = unquote(parsed.path)
    roots = [("/api/v1/uploads/", app_root / "uploads"),
             ("/examples/", app_root.parent / "ui/dist/examples")]
    scoped = parse_qs(parsed.query).get("workspace", [workspace])[0]
    if scoped == workspace:
        roots.append(("/api/v1/file/", workspace_root))
    for prefix, root in roots:
        if not path.startswith(prefix):
            continue
        source = (root / path[len(prefix):]).resolve()
        if source.is_relative_to(root.resolve()) and source.is_file() and source.suffix.lower() in {".mp4", ".webm"}:
            return source
    return None


def _encode(source, target, cancelled):
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "json", str(source)], capture_output=True, text=True, timeout=15, check=True)
    duration = float(json.loads(probe.stdout)["format"]["duration"])
    if not 0 < duration <= 60:
        return False
    alpha = source.suffix.lower() == ".webm"
    codec = (["-c:v", "libvpx-vp9", "-lossless", "1", "-pix_fmt", "yuva420p", "-auto-alt-ref", "0", "-deadline", "good", "-cpu-used", "8"]
             if alpha else ["-c:v", "libx264", "-crf", "14", "-preset", "ultrafast", "-pix_fmt", "yuv420p"])
    temporary = target.with_name(target.stem + ".partial" + target.suffix)
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    if alpha:
        command += ["-c:v", "libvpx-vp9"]
    command += ["-threads", "2", "-i", str(source), "-map", "0:v:0", "-an", *codec, "-g", "1", "-threads", "2", str(temporary)]
    try:
        # Error output goes to a file: a full pipe must never block cancellation.
        with temporary.with_suffix(".log").open("w+") as errors:
            process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=errors)
            try:
                deadline = time.monotonic() + 120
                while process.poll() is None:
                    if cancelled() or time.monotonic() > deadline or (temporary.exists() and temporary.stat().st_size > MAX_PROXY):
                        process.terminate()
                        process.wait(timeout=5)
                        return False
                    time.sleep(.05)
                if process.returncode:
                    return False
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
        temporary.replace(target)
        return True
    finally:
        temporary.unlink(missing_ok=True)
        temporary.with_suffix(".log").unlink(missing_ok=True)


def prepare_media_snapshot(snapshot, *, app_root, workspace_root, cancelled):
    """Called while holding the export GPU lease, which also serializes cache writes."""
    result = deepcopy(snapshot)
    workspace = result["workspace"]
    cache = workspace_root / ".world3d-media-cache"
    used = set()
    document = result["document"]
    entries = [slot["screen"] for slot in document.get("slots", []) if isinstance(slot.get("screen"), dict) and slot["screen"].get("media") == "video"]
    entries += [fx for fx in document.get("worldSfx", []) if fx.get("kind") == "media_portal"]
    for entry in entries:
        if cancelled():
            break
        source = local_video(entry.get("sourceUrl"), workspace, workspace_root, app_root)
        if source is None:
            continue
        stat = source.stat()
        identity = f"v1:{source}:{stat.st_mtime_ns}:{stat.st_size}"
        target = cache / (hashlib.sha256(identity.encode()).hexdigest()[:32] + source.suffix.lower())
        try:
            cache.mkdir(exist_ok=True)
            if not target.is_file() and not _encode(source, target, cancelled):
                continue
            target.touch()
            used.add(target)
            entry["sourceUrl"] = f"/api/v1/file/.world3d-media-cache/{target.name}?workspace={quote(workspace, safe='')}"
        except (OSError, ValueError, KeyError, subprocess.SubprocessError):
            # Optimization failure retains the original native decode path.
            continue
    if cache.is_dir():
        files = sorted((p for p in cache.iterdir() if p.suffix in {".mp4", ".webm"}), key=lambda p: p.stat().st_mtime)
        size = sum(p.stat().st_size for p in files)
        for path in files:
            if size <= LIMIT:
                break
            if path not in used:
                size -= path.stat().st_size
                path.unlink(missing_ok=True)
    return result
