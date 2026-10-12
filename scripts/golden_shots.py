#!/usr/bin/env python3
"""Compare series shots with a golden set stored outside the repository.

Not part of CI. The manifest, copied media, and references live in
``HOCUS_GOLDEN_DIR`` (default ``/mnt/outputs/golden``). ``record`` stores
keyframes, loudness, and duration from each shot's media; it does not replace
references that exist unless ``--force``. ``check`` compares the current media
with those references and writes an HTML report (before | now | difference).
A ``kind: rig`` row redraws one warp mouth with the flat rig, so a rig constant
change fails the check.

``render`` asks a test server (``--base-url``; the live ports are refused) for
``series.episode.render_native`` with the manifest's ``shot_ids``. ``fetch``
copies the takes those jobs made into ``current/``, and from then on ``check``
compares those new takes, not the copies the references were recorded from.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

import numpy as np
from PIL import Image

_APP = Path(__file__).resolve().parents[1] / "app"
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

DEFAULT_DIR = Path("/mnt/outputs/golden")
KEYFRAME_AT = (0.1, 0.5, 0.9)
# SSIM is taken over every 8x8 window and the worst one counts, so a mouth-sized change fails on a 1080p frame.
# On the Plus Ultra golden frames: a 2D shot rendered again from the same inputs is identical (1.0); the same shot
# re-encoded (x264 crf 23) has its worst window at 0.38-0.86; an 80x40 black box puts it at 0.03 or below, where
# the whole-frame SSIM stayed at 0.98-0.9999.
SSIM_WINDOW = 8
DEFAULT_SSIM = 0.9
# The live instance and the running production: a render there adds takes to the library they are writing.
LIVE_PORTS = frozenset({42003, 42042})
RENDERS = "renders.json"
CURRENT = "current"


def golden_root(explicit: str | None) -> Path:
    raw = explicit or os.environ.get("HOCUS_GOLDEN_DIR") or str(DEFAULT_DIR)
    return Path(raw).expanduser().resolve()


def load_manifest(root: Path) -> dict[str, Any]:
    path = root / "manifest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("shots"), list):
        raise SystemExit(f"{path} needs a shots list")
    return data


def _inside(root: Path, path: Path) -> Path:
    base = root.resolve()
    resolved = path.resolve()
    if base != resolved and base not in resolved.parents:
        raise SystemExit(f"{path} is outside the golden directory")
    return resolved


def _shot_media(root: Path, shot: dict[str, Any]) -> Path | None:
    name = shot.get("media")
    if not isinstance(name, str) or not name:
        return None
    return _inside(root, root / name)


def _tool(name: str) -> str:
    found = shutil.which(name)
    if not found:
        raise SystemExit(f"{name} is not on PATH")
    return found


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=False, capture_output=True, text=True)


def probe_media(path: Path) -> dict[str, float]:
    """Duration in frames and frames per second. A still image is one frame."""
    if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
        return {"frames": 1.0, "fps": 1.0, "seconds": 0.0}
    result = _run([
        _tool("ffprobe"), "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=avg_frame_rate,nb_frames,duration",
        "-of", "json", str(path),
    ])
    if result.returncode != 0:
        raise SystemExit(result.stderr.strip() or f"ffprobe failed for {path.name}")
    streams = json.loads(result.stdout or "{}").get("streams") or [{}]
    stream = streams[0] if streams else {}
    rate = str(stream.get("avg_frame_rate") or "0/1")
    num, _, den = rate.partition("/")
    fps = float(num) / float(den or 1) if float(den or 1) else 0.0
    seconds = float(stream.get("duration") or 0)
    frames = stream.get("nb_frames")
    count = float(frames) if isinstance(frames, str) and frames.isdigit() else seconds * fps
    return {"frames": count, "fps": fps or 1.0, "seconds": seconds}


def measure_lufs(path: Path) -> float | None:
    """Integrated loudness, or None when the file has no measurable audio."""
    if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
        return None
    result = _run([
        _tool("ffmpeg"), "-nostats", "-i", str(path),
        "-af", "loudnorm=print_format=json", "-f", "null", "-",
    ])
    text = result.stderr
    start = text.rfind("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        payload = json.loads(text[start:end + 1])
        value = float(payload["input_i"])
    except (ValueError, KeyError, TypeError):
        return None
    if value < -70:
        return None
    return value


def extract_frames(path: Path, dest: Path, seconds: float) -> list[str]:
    """Write key frames and return their file names. A still is copied once."""
    dest.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
        target = dest / "f0.png"
        shutil.copyfile(path, target)
        return ["f0.png"]
    names: list[str] = []
    span = seconds if seconds > 0 else 0.0
    for index, fraction in enumerate(KEYFRAME_AT):
        name = f"f{index}.png"
        at = min(span * fraction, max(0.0, span - 0.04))
        target = dest / name
        result = _run([
            _tool("ffmpeg"), "-y", "-i", str(path), "-ss", f"{at:.3f}",
            "-frames:v", "1", str(target),
        ])
        if result.returncode != 0 or not target.is_file():
            raise SystemExit(result.stderr[-400:] or f"could not read a frame of {path.name}")
        names.append(name)
    return names


def _gray(path: Path) -> np.ndarray:
    image = Image.open(path).convert("L")
    return np.asarray(image, dtype=np.float64)


def _window_mean(values: np.ndarray, size: int) -> np.ndarray:
    """The mean of every ``size`` x ``size`` window, from an integral image."""
    total = np.pad(values, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    return (total[size:, size:] - total[:-size, size:] - total[size:, :-size] + total[:-size, :-size]) / (size * size)


def ssim_score(left: Path, right: Path, window: int = SSIM_WINDOW) -> float:
    """The worst local SSIM of two grayscale images, over every ``window`` x ``window`` patch. Different sizes score
    0. An image smaller than a window is one window."""
    first, second = _gray(left), _gray(right)
    if first.shape != second.shape or first.size == 0:
        return 0.0
    size = min(window, *first.shape)
    c1 = (0.01 * 255) ** 2
    c2 = (0.03 * 255) ** 2
    mean_a, mean_b = _window_mean(first, size), _window_mean(second, size)
    var_a = _window_mean(first * first, size) - mean_a ** 2
    var_b = _window_mean(second * second, size) - mean_b ** 2
    cov = _window_mean(first * second, size) - mean_a * mean_b
    top = (2 * mean_a * mean_b + c1) * (2 * cov + c2)
    bottom = (mean_a ** 2 + mean_b ** 2 + c1) * (var_a + var_b + c2)
    return float((top / bottom).min())


def difference_image(left: Path, right: Path, dest: Path) -> None:
    first, second = Image.open(left).convert("RGB"), Image.open(right).convert("RGB")
    if second.size != first.size:
        second = second.resize(first.size)
    gap = np.abs(np.asarray(first, np.int16) - np.asarray(second, np.int16))
    Image.fromarray(gap.astype(np.uint8)).save(dest)


def rig_frame() -> Image.Image:
    """One warp mouth on a synthetic face. A rig constant change moves these pixels."""
    from services.flat_rig_warp import MouthLine, warp_state

    side = 220
    rgba = np.zeros((side, side, 4), np.uint8)
    rows, cols = np.mgrid[0:side, 0:side]
    face = (cols - 110) ** 2 / 70 ** 2 + (rows - 100) ** 2 / 90 ** 2 <= 1
    rgba[face, :3] = (214, 176, 148)
    rgba[face, 3] = 255
    rgba[104:108, 70:150, :3] = (42, 28, 26)
    rgba[104:108, 70:150, 3] = 255
    line = MouthLine(np.array([106.0]), 70.0, 150.0, True, "hint")
    return warp_state(rgba, line, "wide")


def _metrics(path: Path) -> dict[str, Any]:
    probed = probe_media(path)
    return {"lufs": measure_lufs(path), "frames": probed["frames"], "fps": probed["fps"], "seconds": probed["seconds"]}


def _write_metrics(dest: Path, metrics: dict[str, Any], frames: list[str]) -> None:
    payload = {**metrics, "keyframes": frames}
    (dest / "metrics.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def record_shot(root: Path, shot: dict[str, Any]) -> None:
    dest = _inside(root, root / "refs" / str(shot["id"]))
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    if shot.get("kind") == "rig":
        frame = dest / "f0.png"
        rig_frame().save(frame)
        _write_metrics(dest, {"lufs": None, "frames": 1.0, "fps": 1.0, "seconds": 0.0}, ["f0.png"])
        return
    media = _shot_media(root, shot)
    if media is None or not media.is_file():
        raise SystemExit(f"{shot.get('id')} has no media to record")
    metrics = _metrics(media)
    names = extract_frames(media, dest, float(metrics["seconds"]))
    _write_metrics(dest, metrics, names)


def _frame_delta(reference: float, current: float) -> float:
    return abs(current - reference)


def _compare_frames(reference: Path, current: Path, names: list[str], report: Path, shot_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name in names:
        left, right = reference / name, current / name
        score = ssim_score(left, right) if left.is_file() and right.is_file() else 0.0
        diff_name = f"{shot_id}-{Path(name).stem}-diff.png"
        if left.is_file() and right.is_file():
            difference_image(left, right, report / diff_name)
        rows.append({
            "name": name,
            "ssim": score,
            "before": str(left),
            "now": str(right),
            "diff": diff_name if left.is_file() and right.is_file() else "",
        })
    return rows


def _renderable(shot: dict[str, Any]) -> bool:
    return shot.get("kind") != "rig" and bool(shot.get("shot_id"))


def _compared_media(root: Path, shot: dict[str, Any]) -> tuple[Path | None, str]:
    """After ``render``, a rendered row compares the take ``fetch`` brought (``current/<id>.*``) and has none until
    then. Before any render it compares the copy its references were recorded from."""
    if _renderable(shot) and (root / RENDERS).is_file():
        found = sorted((root / CURRENT).glob(f"{shot['id']}.*")) if (root / CURRENT).is_dir() else []
        return (_inside(root, found[0]), "new take") if found else (None, "new take")
    return _shot_media(root, shot), "recorded copy"


def check_shot(root: Path, shot: dict[str, Any], work: Path, report: Path) -> dict[str, Any]:
    shot_id = str(shot["id"])
    reference = root / "refs" / shot_id
    metrics_path = reference / "metrics.json"
    if not metrics_path.is_file():
        return {"id": shot_id, "role": shot.get("role") or "", "ok": False, "error": "no references (run record)"}
    stored = json.loads(metrics_path.read_text(encoding="utf-8"))
    current_dir = work / shot_id
    if shot.get("kind") == "rig":
        current_dir.mkdir(parents=True, exist_ok=True)
        rig_frame().save(current_dir / "f0.png")
        current = {"lufs": None, "frames": 1.0, "fps": 1.0, "seconds": 0.0}
        names = ["f0.png"]
    else:
        media, source = _compared_media(root, shot)
        if media is None or not media.is_file():
            missing = "no new take (run fetch)" if source == "new take" else "media missing"
            return {"id": shot_id, "role": shot.get("role") or "", "ok": False, "error": missing}
        current = _metrics(media)
        names = extract_frames(media, current_dir, float(current["seconds"]))
    frames = _compare_frames(reference, current_dir, names, report, shot_id)
    threshold = float(shot.get("ssim_threshold") or DEFAULT_SSIM)
    ssim_min = min((row["ssim"] for row in frames), default=0.0)
    lufs_delta = _lufs_delta(stored.get("lufs"), current.get("lufs"))
    lufs_limit = float(shot.get("lufs_tolerance") or 1)
    frame_delta = _frame_delta(float(stored.get("frames") or 0), float(current["frames"]))
    frame_limit = float(shot.get("frame_tolerance") or 1)
    ok = ssim_min >= threshold and frame_delta <= frame_limit and (lufs_delta is None or lufs_delta <= lufs_limit)
    return {
        "id": shot_id, "role": shot.get("role") or shot.get("kind") or "", "ok": ok,
        "ssim": ssim_min, "ssim_threshold": threshold, "lufs_delta": lufs_delta,
        "frame_delta": frame_delta, "frames": frames,
    }


def _lufs_delta(reference: Any, current: Any) -> float | None:
    if reference is None and current is None:
        return None
    if not isinstance(reference, (int, float)) or not isinstance(current, (int, float)):
        return 99.0
    return abs(float(current) - float(reference))


def _esc(value: Any) -> str:
    return (str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _copy_report_image(src: str, report: Path, name: str) -> str:
    if not src or not Path(src).is_file():
        return ""
    target = report / name
    if Path(src).resolve() != target.resolve():
        shutil.copyfile(src, target)
    return name


def write_report(report: Path, rows: list[dict[str, Any]]) -> None:
    report.mkdir(parents=True, exist_ok=True)
    blocks: list[str] = ["<!DOCTYPE html><meta charset=utf-8><title>Golden shots</title>",
                         "<style>body{font-family:sans-serif} img{max-width:280px;vertical-align:top} .bad{color:#900}</style>",
                         "<h1>Conjunto dorado</h1><table><tr><th>Plano</th><th>Papel</th><th>SSIM local mínimo</th><th>LUFS</th><th>Fotogramas</th></tr>"]
    for row in rows:
        mark = "" if row.get("ok") else " class=bad"
        lufs = "—" if row.get("lufs_delta") is None else f"{row['lufs_delta']:.2f}"
        blocks.append(
            f"<tr{mark}><td>{_esc(row.get('id'))}</td><td>{_esc(row.get('role'))}</td>"
            f"<td>{row.get('ssim', 0):.4f}</td><td>{lufs}</td><td>{row.get('frame_delta', '')}</td></tr>"
        )
    blocks.append("</table>")
    for row in rows:
        for frame in row.get("frames") or []:
            before = _copy_report_image(frame.get("before", ""), report, f"{row['id']}-{Path(frame['name']).stem}-before.png")
            now = _copy_report_image(frame.get("now", ""), report, f"{row['id']}-{Path(frame['name']).stem}-now.png")
            diff = frame.get("diff") or ""
            blocks.append(
                f"<h2>{_esc(row['id'])} {_esc(frame['name'])} SSIM {frame['ssim']:.4f}</h2>"
                f"<p>antes | ahora | diferencia</p>"
                f"<img src='{_esc(before)}'><img src='{_esc(now)}'><img src='{_esc(diff)}'>"
            )
    (report / "index.html").write_text("\n".join(blocks) + "\n", encoding="utf-8")
    (report / "summary.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")


def _groups(shots: list[dict[str, Any]]) -> dict[tuple[str, str, str], list[str]]:
    grouped: dict[tuple[str, str, str], list[str]] = {}
    for shot in shots:
        if shot.get("kind") == "rig" or not shot.get("shot_id"):
            continue
        key = (str(shot.get("workspace") or ""), str(shot.get("series_id") or ""), str(shot.get("episode_id") or ""))
        grouped.setdefault(key, []).append(str(shot["shot_id"]))
    return grouped


def test_server(base_url: str | None) -> str:
    """The test server's base URL. A missing URL and the live ports are refused."""
    if not base_url:
        raise SystemExit("render and fetch need --base-url of a test server")
    try:
        parts = urlsplit(base_url)
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError as error:
        raise SystemExit(f"--base-url: {error}") from error
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise SystemExit("--base-url must be http(s)://host:port")
    if port in LIVE_PORTS:
        raise SystemExit(f"port {port} is a live instance; render only on a test server")
    return base_url.rstrip("/")


def _token(token_file: Path) -> str:
    token = token_file.read_text(encoding="utf-8").strip()
    if not token:
        raise SystemExit("the token file is empty")
    return token


def _post_json(url: str, token: str, payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload).encode()
    request = urllib.request.Request(url, data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode() or "{}")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:300]
        raise SystemExit(f"render HTTP {error.code}: {detail}") from error


def _find_job_id(payload: Any) -> str:
    if isinstance(payload, dict):
        if isinstance(payload.get("jobId"), str):
            return payload["jobId"]
        for value in payload.values():
            found = _find_job_id(value)
            if found:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = _find_job_id(item)
            if found:
                return found
    return ""


def _call_tool(url: str, token: str, name: str, data: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "jsonrpc": "2.0", "id": uuid.uuid4().hex, "method": "tools/call",
        "params": {"name": name, "arguments": {"version": 1, "intent_id": uuid.uuid4().hex, "input": data}},
    }
    return _post_json(url, token, payload)


def render_native(root: Path, base_url: str, token_file: Path) -> None:
    """Ask one test server to render each manifest group. Prints job ids only. The jobs go to ``renders.json`` for
    ``fetch``, and the takes an earlier ``fetch`` brought are cleared."""
    base, token = test_server(base_url), _token(token_file)
    url = base + "/api/v1/mcp"
    jobs = []
    for (workspace, series_id, episode_id), shot_ids in _groups(load_manifest(root)["shots"]).items():
        job_id = _find_job_id(_call_tool(url, token, "series.episode.render_native", {
            "workspace": workspace, "series_id": series_id, "episode_id": episode_id, "shot_ids": shot_ids}))
        jobs.append({"workspace": workspace, "series_id": series_id, "episode_id": episode_id, "job_id": job_id})
        print(f"{series_id} {episode_id} shots={len(shot_ids)} job={job_id or 'unknown'}")
    if (root / CURRENT).exists():
        shutil.rmtree(_inside(root, root / CURRENT))
    (root / RENDERS).write_text(json.dumps({"base_url": base, "jobs": jobs}, indent=2) + "\n", encoding="utf-8")


def _job(response: dict[str, Any]) -> dict[str, Any]:
    content = (response.get("result") or {}).get("structuredContent") or {}
    job = (content.get("result") or {}).get("job") if isinstance(content, dict) else None
    if not isinstance(job, dict):
        raise SystemExit(f"render status: {json.dumps(content)[:300]}")
    return job


def _download(url: str, token: str, target: Path) -> None:
    request = urllib.request.Request(url, method="GET")
    request.add_header("Authorization", f"Bearer {token}")
    partial = target.with_name(target.name + ".part")
    try:
        with urllib.request.urlopen(request, timeout=300) as response, partial.open("wb") as handle:
            shutil.copyfileobj(response, handle)
    except urllib.error.HTTPError as error:
        raise SystemExit(f"fetch HTTP {error.code} for {target.name}") from error
    partial.replace(target)


def fetch_takes(root: Path, base_url: str, token_file: Path) -> int:
    """Copy each new take of the ``render`` jobs to ``current/<row id>``. A shot still rendering is listed; fetch
    again later. Returns 1 while a rendered row has no new take."""
    base, token = test_server(base_url), _token(token_file)
    if not (root / RENDERS).is_file():
        raise SystemExit("no renders.json: run render first")
    renders = json.loads((root / RENDERS).read_text(encoding="utf-8"))
    rows = {(str(shot.get("workspace") or ""), str(shot.get("series_id") or ""), str(shot.get("episode_id") or ""),
             str(shot["shot_id"])): str(shot["id"]) for shot in load_manifest(root)["shots"] if _renderable(shot)}
    current = _inside(root, root / CURRENT)
    current.mkdir(exist_ok=True)
    fetched: set[str] = set()
    for job in renders.get("jobs") or []:
        if not job.get("job_id"):
            continue
        state = _job(_call_tool(base + "/api/v1/mcp", token, "series.episode.render_native.status",
                                {"workspace": job["workspace"], "job_id": job["job_id"]}))
        for item in state.get("items") or []:
            row = rows.get((job["workspace"], job["series_id"], job["episode_id"], str(item.get("shotId"))))
            if not row:
                continue
            if item.get("status") != "done" or not item.get("video"):
                print(f"waiting\t{row}\t{item.get('status')} {item.get('stage') or ''}".rstrip())
                continue
            video = str(item["video"])
            _download(f"{base}/api/v1/file/{quote(video)}?workspace={quote(job['workspace'])}", token,
                      current / f"{row}{Path(video).suffix or '.mp4'}")
            fetched.add(row)
            print(f"fetched\t{row}")
    missing = sorted(set(rows.values()) - fetched)
    print(f"{len(fetched)} fetched, {len(missing)} without a new take")
    return 1 if missing else 0


def _print_rows(rows: list[dict[str, Any]]) -> int:
    failed = 0
    for row in rows:
        state = "ok" if row.get("ok") else "FAIL"
        if not row.get("ok"):
            failed += 1
        extra = row.get("error") or f"ssim={row.get('ssim', 0):.4f} frames={row.get('frame_delta', 0)}"
        print(f"{state}\t{row.get('id')}\t{row.get('role', '')}\t{extra}")
    print(f"{len(rows) - failed} passed, {failed} failed")
    return 1 if failed else 0


def command_record(root: Path, force: bool = False) -> int:
    shots = load_manifest(root)["shots"]
    kept = [str(shot["id"]) for shot in shots if (root / "refs" / str(shot["id"])).exists()]
    if kept and not force:
        raise SystemExit(f"references exist for {', '.join(kept)}; record --force replaces them")
    for shot in shots:
        record_shot(root, shot)
        print(f"recorded {shot.get('id')}")
    return 0


def command_check(root: Path) -> int:
    report = root / "report"
    if report.exists():
        shutil.rmtree(report)
    report.mkdir(parents=True)
    rows: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="golden-check-") as tmp:
        for shot in load_manifest(root)["shots"]:
            rows.append(check_shot(root, shot, Path(tmp), report))
        write_report(report, rows)
    print(f"report {report / 'index.html'}")
    return _print_rows(rows)


def _selftest_video(path: Path) -> None:
    """Half a second of a 1080p test pattern with a tone: the size of a series frame."""
    result = _run([
        _tool("ffmpeg"), "-y", "-f", "lavfi", "-i", "testsrc2=s=1920x1080:r=24:d=0.5",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=0.5",
        "-shortest", "-pix_fmt", "yuv420p", str(path),
    ])
    if result.returncode != 0:
        raise SystemExit(result.stderr[-400:] or "could not make the self-test video")


def _refused(action) -> bool:
    try:
        action()
    except SystemExit:
        return True
    return False


def _cover_mouth(frame: Path) -> None:
    """Paint an 80x40 box, about a mouth on a 1080p frame, in the middle of ``frame``."""
    image = np.array(Image.open(frame).convert("RGB"))
    top, left = image.shape[0] // 2 - 20, image.shape[1] // 2 - 40
    patch = image[top:top + 40, left:left + 80]
    patch[:] = 0 if patch.mean() > 127 else 255
    Image.fromarray(image).save(frame)


def command_selftest() -> int:
    with tempfile.TemporaryDirectory(prefix="golden-selftest-") as tmp:
        root = Path(tmp)
        media = root / "media"
        media.mkdir()
        _selftest_video(media / "clip.mp4")
        manifest = {
            "shots": [
                {"id": "clip", "role": "video", "media": "media/clip.mp4", "workspace": "test", "series_id": "s",
                 "episode_id": "e", "shot_id": "e1s01"},
                {"id": "rig", "kind": "rig", "role": "rig-warp", "ssim_threshold": 0.999},
            ]
        }
        (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        command_record(root)
        if command_check(root) != 0:
            return 1
        refusals = {
            "record over references": lambda: command_record(root),
            "render without --base-url": lambda: test_server(None),
            "render on :42003": lambda: test_server("http://127.0.0.1:42003"),
            "render on :42042": lambda: test_server("http://localhost:42042/"),
        }
        for name, action in refusals.items():
            if not _refused(action):
                print(f"selftest expected {name} to be refused")
                return 1
        (root / RENDERS).write_text(json.dumps({"jobs": []}), encoding="utf-8")
        if command_check(root) == 0:
            print("selftest expected a render without a fetched take to fail")
            return 1
        (root / CURRENT).mkdir()
        shutil.copyfile(media / "clip.mp4", root / CURRENT / "clip.mp4")
        if command_check(root) != 0:
            return 1
        _cover_mouth(root / "refs" / "clip" / "f1.png")
        if command_check(root) == 0:
            print("selftest expected a mouth-sized change on a 1080p frame to fail")
            return 1
    print("selftest ok")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare a golden set of series shots stored outside the repo.")
    parser.add_argument("command", choices=("record", "check", "render", "fetch", "selftest"))
    parser.add_argument("--golden-dir", default=None)
    parser.add_argument("--base-url", default=None, help="a test server; the live ports 42003 and 42042 are refused")
    parser.add_argument("--token-file", default="")
    parser.add_argument("--force", action="store_true", help="record: replace the references that exist")
    args = parser.parse_args(argv)
    if args.command == "selftest":
        return command_selftest()
    root = golden_root(args.golden_dir)
    if args.command == "record":
        return command_record(root, force=args.force)
    if args.command == "check":
        return command_check(root)
    test_server(args.base_url)
    if not args.token_file:
        raise SystemExit(f"{args.command} needs --token-file")
    if args.command == "fetch":
        return fetch_takes(root, args.base_url, Path(args.token_file))
    render_native(root, args.base_url, Path(args.token_file))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
