"""CPU humanoid rig worker. Runs under the Hunyuan3D Python, one job, then exits."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from services.humanoid_rig.errors import NotHumanoid


def event(phase: str, progress: float, message: str) -> None:
    print("MAESTRO_EVENT " + json.dumps({"phase": phase, "progress": progress, "message": message}), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    request = json.loads(Path(args.request).read_text(encoding="utf-8"))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if request.get("mode") == "animate":
        _animate(request, output)
        return
    _rig(request, output)


def _rig(request: dict, output: Path) -> None:
    from services.humanoid_rig.clips import clip_library
    from services.humanoid_rig.rig import rig_humanoid

    source = _source(request)
    event("skeleton", 0.2, "Finding humanoid landmarks")
    bpm = float(request.get("animation_bpm") or 120)
    clip_ids = [str(item) for item in (request.get("animations") or ["idle"])]
    rigged, sidecar = rig_humanoid(source.read_bytes(), clip_library(bpm, clip_ids))
    output.write_bytes(rigged)
    sidecar_path = output.with_suffix(".humanoid.json")
    sidecar_path.write_text(json.dumps(sidecar), encoding="utf-8")
    clips = _clip_rows(clip_ids, bpm)
    print("MAESTRO_RESULT " + json.dumps({
        "ok": True,
        "output": str(output),
        "joints": len(sidecar["bones"]),
        "height": sidecar["height"],
        "confidence": sidecar["confidence"],
        "animations": clip_ids,
        "clips": clips,
        "pose": request.get("pose") or "t",
    }), flush=True)
    event("completed", 1.0, "Humanoid rig saved")


def _animate(request: dict, output: Path) -> None:
    from services.humanoid_rig.animate import animate_humanoid

    source = _source(request)
    event("animating", 0.4, "Adding humanoid clips")
    imported = request.get("import_file")
    payload = Path(imported).read_bytes() if imported else None
    suffix = Path(imported).suffix if imported else ""
    data, clips, warnings = animate_humanoid(
        source.read_bytes(),
        [str(item) for item in (request.get("animations") or [])],
        float(request.get("animation_bpm") or 120),
        payload,
        suffix,
    )
    output.write_bytes(data)
    print("MAESTRO_RESULT " + json.dumps({"ok": True, "output": str(output), "clips": clips, "warnings": warnings}), flush=True)
    event("completed", 1.0, "Humanoid clips saved")


def _source(request: dict) -> Path:
    source = Path(str(request["source"]))
    if not source.is_file():
        raise RuntimeError(f"Source model not found: {source}")
    return source


def _clip_rows(clip_ids: list[str], bpm: float) -> list[dict]:
    from services.humanoid_rig.clips import clip_library

    return [
        {"index": index, "name": clip["name"], "duration": clip["duration"]}
        for index, clip in enumerate(clip_library(bpm, clip_ids))
    ]


if __name__ == "__main__":
    try:
        main()
    except NotHumanoid as exc:
        event("failed", 0.0, str(exc))
        print("MAESTRO_RESULT " + json.dumps({"ok": False, "error": exc.code, "reason": exc.reason}), flush=True)
        sys.exit(2)
    except Exception as exc:
        event("failed", 0.0, str(exc))
        print("MAESTRO_RESULT " + json.dumps({"ok": False, "error": "rig_failed", "reason": str(exc)}), flush=True)
        sys.exit(1)
