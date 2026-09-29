#!/usr/bin/env python3
"""Read-only, CPU-only evaluation of a persisted music-production package.

This is an offline acceptance tool, not another production runner or an artistic
judge. Exit 0 means only the listed structural/media-header checks passed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import time
from fractions import Fraction
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, unquote, urlsplit


def positive(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("expected a finite positive number")
    try:
        number = float(value)
    except OverflowError as error:
        raise ValueError("expected a finite positive number") from error
    if not math.isfinite(number) or number <= 0:
        raise ValueError("expected a finite positive number")
    return number


def probe_video(path: Path) -> dict:
    """Inspect local stream headers, without decoding, rendering or networking."""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-threads", "1", "-protocol_whitelist", "file,pipe",
         "-show_entries", "format=duration:stream=codec_type,width,height,avg_frame_rate,duration",
         "-of", "json", str(path)],
        capture_output=True, text=True, timeout=20, check=True,
    )
    data = json.loads(result.stdout)
    streams = data.get("streams") or []
    video = next(stream for stream in streams if stream.get("codec_type") == "video")
    # Use VIDEO duration: a long audio stream must not hide truncated pictures.
    duration = positive(float(video.get("duration", 0)))
    return {"duration_s": duration, "width": positive(video.get("width")),
            "height": positive(video.get("height")),
            "fps": positive(float(Fraction(video.get("avg_frame_rate", "0/1")))),
            "has_audio": any(stream.get("codec_type") == "audio" for stream in streams)}


class Audit:
    def __init__(self, root: Path, probe: Callable[[Path], dict]):
        self.root, self.probe = root.resolve(), probe
        self.artifacts: dict[str, dict] = {}
        self.issues: list[dict] = []
        self.stamps: dict[Path, tuple] = {}

    def fail(self, code: str, subject: str, detail: str) -> None:
        self.issues.append({"code": code, "subject": subject, "detail": detail})

    @staticmethod
    def stamp(path: Path) -> tuple:
        stat = path.stat()
        return stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns

    def artifact(self, name: object, subject: str) -> Path | None:
        if not isinstance(name, str) or not name:
            self.fail("missing_reference", subject, "exact workspace filename required")
            return None
        if name in self.artifacts:
            return self.root / name
        # Persisted package references are basenames, never paths or URLs.
        path = self.root / name
        try:
            contained = path.resolve().is_relative_to(self.root)
        except (OSError, RuntimeError):
            contained = False
        if name in (".", "..") or any(c in name for c in ("/", "\\", ":", "\x00")) or not contained:
            self.fail("unsafe_path", subject, "reference must remain inside the workspace")
            return None
        try:
            if not path.is_file() or not path.stat().st_size:
                self.fail("missing_artifact", subject, name)
                return None
            self.stamps[path] = self.stamp(path)
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(block)
            self.artifacts[name] = {"sha256": digest.hexdigest(), "bytes": self.stamps[path][1]}
            return path
        except OSError:
            self.fail("unreadable_artifact", subject, name)
            return None

    def document(self, name: object, subject: str) -> dict:
        path = self.artifact(name, subject)
        if path is None:
            return {}
        try:
            if path.stat().st_size > 10 * 1024 * 1024:
                raise ValueError("JSON exceeds 10 MiB")
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("JSON must be an object")
            return data
        except (OSError, ValueError):
            self.fail("invalid_json", subject, path.name)
            return {}

    def media(self, name: object, subject: str) -> dict:
        path = self.artifact(name, subject)
        if path is None:
            return {}
        if "probe" in self.artifacts[path.name]:
            return self.artifacts[path.name]["probe"]
        try:
            metadata = self.probe(path)
            for key in ("duration_s", "width", "height", "fps"):
                positive(metadata[key])
            if not isinstance(metadata.get("has_audio"), bool):
                raise ValueError("audio presence was not measured")
            self.artifacts[path.name]["probe"] = metadata
            return metadata
        except FileNotFoundError:
            self.fail("probe_unavailable", subject, "ffprobe executable missing")
        except (OSError, ValueError, KeyError, TypeError, StopIteration, ZeroDivisionError, subprocess.SubprocessError):
            self.fail("probe_failed", subject, "valid local video stream headers could not be measured")
        return {}

    def unchanged(self) -> None:
        for path, stamp in self.stamps.items():
            try:
                same = self.stamp(path) == stamp
            except OSError:
                same = False
            if not same:
                self.fail("artifact_changed", path.name, "changed during evaluation; rerun on a stable package")


def rows(audit: Audit, document: dict, field: str) -> list[dict]:
    values = document.get(field)
    if not isinstance(values, list) or not values or len(values) > 2000 or any(not isinstance(row, dict) for row in values):
        audit.fail("invalid_rows", field, "expected 1..2000 objects")
        return []
    return values


def dimensions(audit: Audit, document: dict, subject: str) -> dict:
    try:
        return {key: positive(document.get(key)) for key in ("width", "height", "fps")}
    except ValueError:
        audit.fail("invalid_number", subject, "width, height and fps must be finite and positive")
        return {}


def compare_media(audit: Audit, metadata: dict, expected: dict, duration: float, subject: str) -> None:
    if not metadata or not expected:
        return
    tolerance = max(0.1, 2 / expected["fps"])
    if abs(metadata["duration_s"] - duration) > tolerance:
        audit.fail("duration_mismatch", subject, f"expected {duration:.3f}s ± {tolerance:.3f}s; measured {metadata['duration_s']:.3f}s")
    if (metadata["width"], metadata["height"]) != (expected["width"], expected["height"]):
        audit.fail("resolution_mismatch", subject, "stream dimensions differ from the saved document")
    if abs(metadata["fps"] - expected["fps"]) > 0.005:
        audit.fail("fps_mismatch", subject, "average frame rate differs from the saved document")


def timeline(audit: Audit, shots: list[dict]) -> float:
    cursor, seen = 0.0, set()
    for shot in shots:
        key = shot.get("key")
        if not isinstance(key, str) or not key or key in seen:
            audit.fail("duplicate_shot", "shots", "keys must be distinct nonempty strings")
        else:
            seen.add(key)
        try:
            end = positive(shot.get("end"))
            start = shot.get("start")
            if isinstance(start, bool) or not isinstance(start, (int, float)) or start < 0 or start >= end:
                raise ValueError("invalid start")
            start = float(start)
            if not math.isfinite(start):
                raise ValueError("invalid start")
            if abs(start - cursor) > 0.002:  # manifest times are rounded to milliseconds
                audit.fail("timeline_discontinuity", str(key), f"expected start {cursor:.3f}s; got {start:.3f}s")
            cursor = end
        except (ValueError, OverflowError):
            audit.fail("invalid_number", str(key), "expected finite 0 <= start < end")
    return cursor


def check_shot(audit: Audit, shot: dict, clip: dict, production_id: str, workspace_id: str) -> None:
    key = str(shot.get("key"))
    doc = audit.document(shot.get("scene_doc"), key + ":scene_doc")
    if doc and (type(doc.get("version")) is not int or doc["version"] != 1):
        audit.fail("unsupported_version", key, "scene version must be 1")
    expected = dimensions(audit, doc, key) if doc else {}
    media = audit.media(shot.get("scene_video"), key + ":scene_video")
    try:
        span = positive(shot.get("end")) - float(shot["start"])
        duration = positive(doc.get("duration")) if doc else span
        compare_media(audit, media, expected, span, key)
        if abs(duration - span) > 0.002:
            audit.fail("scene_duration_mismatch", key, "saved scene duration differs from manifest span")
        trim_start, trim_end = clip.get("trimStart", 0), clip.get("trimEnd")
        if isinstance(trim_start, bool) or not isinstance(trim_start, (int, float)) or trim_start != 0 or abs(positive(trim_end) - span) > 0.002:
            audit.fail("trim_mismatch", key, "production clips must cover the entire shot from zero")
    except (ValueError, TypeError, KeyError, OverflowError):
        audit.fail("invalid_number", key, "scene span, duration or trim is invalid")
    origin = clip.get("origin")
    wanted = {"kind": "scene2d", "productionId": production_id, "shotId": shot.get("key"), "scene": shot.get("scene_doc")}
    if not isinstance(origin, dict) or any(origin.get(field) != value for field, value in wanted.items()):
        audit.fail("origin_mismatch", key, "montage origin does not identify the manifest's production, shot and scene")
    check_source(audit, clip.get("source"), shot.get("scene_video"), workspace_id, key)
    if clip.get("transition", "none") != "none":
        audit.fail("unsupported_transition", key, "this evaluator covers production packages with no transitions")


def check_source(audit: Audit, value: object, file: object, workspace_id: str, subject: str) -> None:
    try:
        source = urlsplit(str(value or ""))
        matched = (not source.scheme and not source.netloc and not source.fragment
                   and unquote(source.path) == "/api/v1/file/" + str(file)
                   and parse_qs(source.query).get("workspace") == [workspace_id])
    except ValueError:
        matched = False
    if not matched:
        audit.fail("source_mismatch", subject, "montage source does not identify the manifest's scene video and workspace")


def evaluate(workspace: Path, production_file: str, *, workspace_id: str | None = None,
             probe: Callable[[Path], dict] | None = None) -> dict:
    started = time.monotonic()
    audit = Audit(workspace, probe or probe_video)
    state = audit.document(production_file, "production")
    production_id = production_file.removesuffix(".production.json")
    workspace_id = workspace_id or state.get("workspace") or workspace.name
    if not production_file.endswith(".production.json"):
        audit.fail("invalid_production_file", "production", "expected an exact .production.json filename")
    if state.get("status") != "completed" or state.get("error"):
        audit.fail("production_not_completed", "production", "a finished, error-free production is required")
    package = state.get("package")
    manifest = audit.document(package.get("manifest") if isinstance(package, dict) else None, "manifest")
    montage = audit.document(state.get("montage_file"), "montage")
    for subject, doc in (("manifest", manifest), ("montage", montage)):
        if doc and (type(doc.get("version")) is not int or doc["version"] != 1):
            audit.fail("unsupported_version", subject, "version must be 1")
    if manifest.get("production_id") != production_id:
        audit.fail("production_mismatch", "manifest", "production_id differs from the state filename")
    # First-run packages are saved before montage export, so null is legitimate.
    if manifest.get("montage") is not None and manifest["montage"] != state.get("montage_file"):
        audit.fail("montage_mismatch", "manifest", "manifest refers to another montage")
    shots, clips = rows(audit, manifest, "shots"), rows(audit, montage, "clips")
    duration = timeline(audit, shots)
    if [shot.get("key") for shot in shots] != [clip.get("id") for clip in clips]:
        audit.fail("shot_order_mismatch", "montage", "montage clips must match every manifest shot in order")
    for shot, clip in zip(shots, clips):
        check_shot(audit, shot, clip, production_id, workspace_id)
    final = audit.media(state.get("final"), "final")
    compare_media(audit, final, dimensions(audit, montage, "montage"), duration, "final")
    if montage.get("soundtrack") and final and not final["has_audio"]:
        audit.fail("missing_audio", "final", "montage declares a master soundtrack but export has no audio stream")
    audit.unchanged()
    passed = not audit.issues
    return {"version": 1, "production_id": production_id,
            "execution": {"verdict": "pass" if final else "fail", "scope": "local_video_stream_headers"},
            "technical": {"verdict": "pass" if passed else "fail",
                          "scope": ["package_completeness", "timeline", "montage_references", "stream_headers"],
                          "not_evaluated": ["full_decode", "render_snapshot_parity", "caption_legibility", "motion", "lipsync", "cadence", "identity"]},
            "artistic": {"verdict": "pending", "reason": "requires viewing the exact hashed exports"},
            "publication": "requires_artistic_review" if passed else "blocked",
            "expected_duration_s": duration, "artifacts": audit.artifacts, "issues": audit.issues,
            "measurement": {"elapsed_seconds": round(time.monotonic() - started, 6), "gpu_used": False}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-dir", type=Path, required=True)
    parser.add_argument("--workspace-id", help="workspace query value; defaults to the directory name")
    parser.add_argument("--production-file", required=True)
    args = parser.parse_args(argv)
    report = evaluate(args.workspace_dir, args.production_file, workspace_id=args.workspace_id)
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    if any(issue["code"] == "probe_unavailable" for issue in report["issues"]):
        return 2
    return 0 if report["technical"]["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
