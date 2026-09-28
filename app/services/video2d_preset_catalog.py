"""Camera and finish presets from the shared catalogs.

``add_layer`` accepts ``kind: camera`` entries in ``motion_presets.json``.
``set_finish`` accepts entries in ``finish_presets.json``. Motion-kind ids
stay out of ``add_layer``.
"""
from __future__ import annotations

from services.video2d_catalogs import CATALOGS


def camera_presets() -> dict[str, dict]:
    presets: dict[str, dict] = {}
    for entry in CATALOGS["scenes.motion.catalog"]["entries"]:
        if not isinstance(entry, dict) or entry.get("kind") != "camera":
            continue
        identity = entry.get("id")
        start, end = entry.get("start"), entry.get("end")
        if not isinstance(identity, str) or not isinstance(start, dict) or not isinstance(end, dict):
            continue
        preset = {"start": dict(start), "end": dict(end), "duration": entry.get("duration"), "curve": entry.get("curve")}
        shake = entry.get("shake")
        if isinstance(shake, dict):
            preset["shake"] = dict(shake)
        presets[identity] = preset
    return presets


def finish_presets() -> dict[str, dict]:
    presets: dict[str, dict] = {}
    for entry in CATALOGS["scenes.finish.catalog"]["entries"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            continue
        presets[entry["id"]] = {key: value for key, value in entry.items() if key != "id"}
    return presets


__all__ = ["camera_presets", "finish_presets"]
