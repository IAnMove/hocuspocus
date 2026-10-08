#!/usr/bin/env python3
"""Compare series shots with a golden set stored outside the repository.

Not part of CI. The manifest, copied media, and references live in
``HOCUS_GOLDEN_DIR`` (default ``/mnt/outputs/golden``). ``record`` stores
keyframes, loudness, and duration from each shot's media. ``check`` compares
the current media with those references and writes an HTML report
(before | now | difference). A ``kind: rig`` row redraws one warp mouth with
the flat rig, so a rig constant change fails the check.

``render`` asks a test server for ``series.episode.render_native`` with the
manifest's ``shot_ids``. It does not render by itself during ``check``.
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

import numpy as np
from PIL import Image

_APP = Path(__file__).resolve().parents[1] / "app"
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

DEFAULT_DIR = Path("/mnt/outputs/golden")
KEYFRAME_AT = (0.1, 0.5, 0.9)


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


def ssim_score(left: Path, right: Path) -> float:
    """Global SSIM of two grayscale images. Different sizes score 0."""
    first, second = _gray(left), _gray(right)
    if first.shape != second.shape or first.size == 0:
        return 0.0
    c1 = (0.01 * 255) ** 2
    c2 = (0.03 * 255) ** 2
    mean_a, mean_b = float(first.mean()), float(second.mean())
    var_a, var_b = float(first.var()), float(second.var())
    cov = float(((first - mean_a) * (second - mean_b)).mean())
    top = (2 * mean_a * mean_b + c1) * (2 * cov + c2)
    bottom = (mean_a ** 2 + mean_b ** 2 + c1) * (var_a + var_b + c2)
    return top / bottom if bottom else 1.0


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
        media = _shot_media(root, shot)
        if media is None or not media.is_file():
            return {"id": shot_id, "role": shot.get("role") or "", "ok": False, "error": "media missing"}
        current = _metrics(media)
        names = extract_frames(media, current_dir, float(current["seconds"]))
    frames = _compare_frames(reference, current_dir, names, report, shot_id)
    threshold = float(shot.get("ssim_threshold") or 0.98)
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
                         "<h1>Conjunto dorado</h1><table><tr><th>Plano</th><th>Papel</th><th>SSIM</th><th>LUFS</th><th>Fotogramas</th></tr>"]
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


def render_native(root: Path, base_url: str, token_file: Path) -> None:
    """Ask one test server to render each manifest group. Prints job ids only."""
    token = token_file.read_text(encoding="utf-8").strip()
    if not token:
        raise SystemExit("the token file is empty")
    url = base_url.rstrip("/") + "/api/v1/mcp"
    for (workspace, series_id, episode_id), shot_ids in _groups(load_manifest(root)["shots"]).items():
        payload = {
            "jsonrpc": "2.0", "id": uuid.uuid4().hex,
            "method": "tools/call",
            "params": {"name": "series.episode.render_native", "arguments": {
                "version": 1, "intent_id": uuid.uuid4().hex,
                "input": {"workspace": workspace, "series_id": series_id, "episode_id": episode_id, "shot_ids": shot_ids},
            }},
        }
        job_id = _find_job_id(_post_json(url, token, payload))
        print(f"{series_id} {episode_id} shots={len(shot_ids)} job={job_id or 'unknown'}")


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


def command_record(root: Path) -> int:
    for shot in load_manifest(root)["shots"]:
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
    result = _run([
        _tool("ffmpeg"), "-y", "-f", "lavfi", "-i", "color=c=0x336699:s=64x48:d=0.4",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=0.4",
        "-shortest", str(path),
    ])
    if result.returncode != 0:
        raise SystemExit(result.stderr[-400:] or "could not make the self-test video")


def command_selftest() -> int:
    with tempfile.TemporaryDirectory(prefix="golden-selftest-") as tmp:
        root = Path(tmp)
        media = root / "media"
        media.mkdir()
        _selftest_video(media / "clip.mp4")
        manifest = {
            "shots": [
                {"id": "clip", "role": "video", "media": "media/clip.mp4", "ssim_threshold": 0.99},
                {"id": "rig", "kind": "rig", "role": "rig-warp", "ssim_threshold": 0.999},
            ]
        }
        (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        command_record(root)
        if command_check(root) != 0:
            return 1
        frame = root / "refs" / "clip" / "f0.png"
        image = np.array(Image.open(frame).convert("RGB"))
        image[:8, :8] = (255, 0, 0)
        Image.fromarray(image).save(frame)
        broken = command_check(root)
        if broken == 0:
            print("selftest expected the edited frame to fail")
            return 1
    print("selftest ok")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare a golden set of series shots stored outside the repo.")
    parser.add_argument("command", choices=("record", "check", "render", "selftest"))
    parser.add_argument("--golden-dir", default=None)
    parser.add_argument("--base-url", default="http://127.0.0.1:42021")
    parser.add_argument("--token-file", default="")
    args = parser.parse_args(argv)
    if args.command == "selftest":
        return command_selftest()
    root = golden_root(args.golden_dir)
    if args.command == "record":
        return command_record(root)
    if args.command == "check":
        return command_check(root)
    if not args.token_file:
        raise SystemExit("render needs --token-file")
    render_native(root, args.base_url, Path(args.token_file))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
