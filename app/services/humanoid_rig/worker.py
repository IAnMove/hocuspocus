"""CPU humanoid rig worker. Runs under the Hunyuan3D Python, one job, then exits."""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

from services.humanoid_rig.errors import InvalidInput, NotHumanoid


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
    from services.humanoid_rig.rig import rig_humanoid

    source = _source(request)
    event("skeleton", 0.2, "Finding humanoid landmarks")
    bpm = float(request.get("animation_bpm") or 120)
    clip_ids = [str(item) for item in (request.get("animations") or ["idle"])]
    rigged, sidecar = rig_humanoid(source.read_bytes(), clip_ids, bpm)
    output.write_bytes(rigged)
    sidecar_path = output.with_suffix(".humanoid.json")
    sidecar_path.write_text(json.dumps(sidecar), encoding="utf-8")
    print("MAESTRO_RESULT " + json.dumps({
        "ok": True,
        "output": str(output),
        "joints": len(sidecar["bones"]),
        "height": sidecar["height"],
        "confidence": sidecar["confidence"],
        "warnings": sidecar["warnings"],
        "animations": clip_ids,
        "clips": [{key: row[key] for key in ("index", "name", "duration", "contacts") if key in row} for row in sidecar["clips"]],
        "pose": sidecar["pose"],
        "arm_drop": sidecar["arm_drop"],
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
        str(request.get("import_label") or "Imported"),
        request.get("path"),
        request.get("interactions"),
    )
    output.write_bytes(data)
    print("MAESTRO_RESULT " + json.dumps({"ok": True, "output": str(output), "clips": clips, "warnings": warnings}), flush=True)
    event("completed", 1.0, "Humanoid clips saved")


def _source(request: dict) -> Path:
    source = Path(str(request["source"]))
    if not source.is_file():
        raise InvalidInput(f"Source model not found: {source.name}")
    return source


if __name__ == "__main__":
    try:
        main()
    except NotHumanoid as exc:
        event("failed", 0.0, str(exc))
        print("MAESTRO_RESULT " + json.dumps({"ok": False, "error": exc.code, "reason": exc.reason}), flush=True)
        sys.exit(2)
    except InvalidInput as exc:
        event("failed", 0.0, str(exc))
        print("MAESTRO_RESULT " + json.dumps({"ok": False, "error": exc.code, "reason": str(exc)}), flush=True)
        sys.exit(2)
    except Exception as exc:
        traceback.print_exc()  # a crash, not a refusal: keep the trace in the job log
        event("failed", 0.0, str(exc))
        print("MAESTRO_RESULT " + json.dumps({"ok": False, "error": "rig_failed", "reason": str(exc)}), flush=True)
        sys.exit(1)
