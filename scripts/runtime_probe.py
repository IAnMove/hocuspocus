"""Pinokio preflight. Runs with its managed base Python; installs nothing."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from services.install_catalog import optional_engines  # noqa: E402
from services.runtime_profiles import detect_profiles  # noqa: E402

FEATURES = {
    "core": "the editing studio (projects, Video 2D/3D editors, comics, Wizard and remote providers)",
    "wangp": "local video and image generation (WanGP)",
    "hunyuan3d": "local image-to-3D (Hunyuan3D)",
    "minimax_h3": "MiniMax H3 Legacy (ComfyUI)",
    "sam": "inpaint masks (SAM 3.1)",
    "rigging": "AI rigging (UniRig)",
    "trellis2": "optional official image-to-3D (TRELLIS.2)",
    "template_semantic": "template semantic search (CPU)",
}


def unavailable(result: dict) -> list[str]:
    """What this computer cannot run and why, grouped by reason. Shown by the Install dialogs."""
    blocked: dict[str, list[str]] = {}
    for name, item in result["engines"].items():
        if name != "core" and not item["supported"] and not item.get("supersededBy"):
            reason = item["reason"].removeprefix(f"{item['label']} ")  # group shared driver limits
            blocked.setdefault(reason[:1].upper() + reason[1:], []).append(FEATURES.get(name, item["label"]))
    return [f"Not available here: {', '.join(features)}. {reason}" for reason, features in blocked.items()]


def summary(result: dict) -> list[str]:
    """What this computer installs, what it cannot run and why, in plain words."""
    engines = result["engines"]
    if engines["wangp"]["supported"]:
        lines = ["Installs the full studio with local NVIDIA generation."]
    elif engines["core"]["supported"]:
        lines = [f"Installs {FEATURES['core']}; no local AI models."]
    else:
        return [f"Nothing can be installed on this computer: {engines['core']['reason']}"]
    lines += unavailable(result)
    on_request = optional_engines()
    optional = [FEATURES.get(name, item["label"]) for name, item in engines.items()
                if item["supported"] and name in on_request and not item.get("installed")]
    if optional:
        lines.append(f"Optional, from the Advanced menu: {', '.join(optional)}.")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform")
    parser.add_argument("--arch")
    parser.add_argument("--gpu")
    parser.add_argument("--require-installed", help="Stop Start after an incomplete managed migration")
    args = parser.parse_args()
    result = detect_profiles(platform=args.platform, arch=args.arch, gpu=args.gpu)
    result["summary"] = summary(result)
    result["unavailable"] = unavailable(result)
    # Shown by the Install dialog next to each extra's size. A top-level key, not hashed into any recipe.
    result["diskFreeGiB"] = round(shutil.disk_usage(ROOT).free / 2 ** 30, 1)
    target = ROOT / "app" / ".runtime" / "capabilities.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(result, indent=2), encoding="utf-8")
    temporary.replace(target)
    for item in result["engines"].values():
        print(f"[Runtime] {item['label']}: {item['id']} — {item['reason'] or item['warning'] or 'recipe available'}")
    for line in result["summary"]:
        print(f"[Runtime] {line}")
    if args.require_installed:
        item = result["engines"][args.require_installed]
        if not item["supported"] or not item["installed"]:
            raise SystemExit("Error: HOCUS_RUNTIME_FAILED. Run Install or Update to repair the selected runtime before Start.")


if __name__ == "__main__":
    main()
