"""Save a new aspect of an existing montage without changing the original."""

from __future__ import annotations

from typing import Any

from services.montage_documents import MontageError, MontageStore, slug_file

FORMATS = {
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
    "4:5": (1080, 1350),
}
FITS = ("blur", "fill")


def _copy_clip(clip: dict[str, Any], fit: str) -> dict[str, Any]:
    copied = dict(clip)
    copied["fit"] = fit
    return copied


def _place_overlay(item: dict[str, Any]) -> dict[str, Any]:
    placed = dict(item)
    placed["width"] = min(float(item["width"]), 90.0)
    placed["y"] = min(80.0, max(12.0, float(item["y"])))
    return placed


def derived_document(source: dict[str, Any], *, aspect: str, fit: str, file: str, revision: int) -> dict[str, Any]:
    if aspect not in FORMATS:
        raise MontageError("format must be 9:16, 1:1 or 4:5")
    if fit not in FITS:
        raise MontageError("fit must be blur or fill")
    width, height = FORMATS[aspect]
    soundtrack = source.get("soundtrack")
    return {
        "version": 1,
        "kind": "montage",
        "name": f"{source['name']} ({aspect})"[:160],
        "width": width,
        "height": height,
        "fps": source["fps"],
        "clips": [_copy_clip(clip, fit) for clip in source["clips"]],
        "soundtrack": dict(soundtrack) if isinstance(soundtrack, dict) else None,
        "audioCues": [dict(item) for item in source.get("audioCues") or []],
        "overlays": [_place_overlay(item) for item in source.get("overlays") or []],
        "duck": source.get("duck") or 0,
        "notes": source.get("notes") or "",
        "derivedFrom": {"file": file, "revision": int(revision)},
    }


def derive_saved(store: MontageStore, payload: dict[str, Any]) -> dict[str, Any]:
    saved = store.get(payload["workspace"], payload["file"])
    source = saved["montage"]
    document = derived_document(
        source,
        aspect=str(payload.get("format") or ""),
        fit=str(payload.get("fit") or ""),
        file=saved["file"],
        revision=int(source.get("revision") or 1),
    )
    output = payload.get("output_file")
    target = output if isinstance(output, str) and output else slug_file(document["name"])
    if target == saved["file"]:
        raise MontageError("A derived montage needs its own file", code="invalid_file")
    return store.save(
        payload["workspace"],
        document,
        file=target if output else None,
        expected_revision=payload.get("expected_revision"),
    )
