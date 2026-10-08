"""One output-name rule for generation: keep the existing file, save the next as name (2).

``reserve`` follows ``wgp.get_available_filename``: the first collision is
``name(2).ext``, then ``name(3).ext``. Nothing in this module overwrites.
"""
from __future__ import annotations

import os


_MAX_COLLISIONS = 10000


def reserve(directory: str, name: str) -> tuple[str, bool]:
    """Return ``(final_name, taken)`` for one file inside ``directory``.

    ``taken`` is false when ``name`` itself is free. The caller creates the
    file; this function only chooses a name that does not exist yet.
    """
    base_name = os.path.basename(str(name or ""))
    stem, extension = os.path.splitext(base_name)
    if not stem or stem in {".", ".."}:
        raise ValueError("output name must be a single file name")
    candidate = f"{stem}{extension}"
    taken = False
    for counter in range(2, _MAX_COLLISIONS + 2):
        path = os.path.join(directory, candidate)
        if not os.path.exists(path):
            return candidate, taken
        taken = True
        candidate = f"{stem}({counter}){extension}"
    raise ValueError("output name is exhausted")


def _taken_rename(requested: str, final: str) -> bool:
    """True when ``final`` is the ``(2)`` form of ``requested``."""
    if not requested or not final or requested == final:
        return False
    requested_stem, requested_ext = os.path.splitext(os.path.basename(requested))
    final_stem, final_ext = os.path.splitext(os.path.basename(final))
    if requested_ext != final_ext or not final_stem.startswith(requested_stem + "(") or not final_stem.endswith(")"):
        return False
    number = final_stem[len(requested_stem) + 1:-1]
    return number.isdigit() and int(number) >= 2


def _text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def requested_output_name(source: object) -> str:
    """The caller's file name, before a collision suffix was added."""
    if not isinstance(source, dict):
        return ""
    direct = _text(source.get("output_name_requested"))
    if direct:
        return direct
    params = source.get("params") if isinstance(source.get("params"), dict) else {}
    request = source.get("request") if isinstance(source.get("request"), dict) else {}
    metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
    for candidate in (
        params.get("output_filename"), params.get("output_name"),
        request.get("output_name"), metadata.get("output_name_requested"),
    ):
        text = _text(candidate)
        if text:
            return text
    return ""


def _final_name(view: dict, source: object) -> str:
    if isinstance(source, dict):
        files = source.get("output_files")
        if isinstance(files, list):
            for item in files:
                text = _text(item)
                if text:
                    return os.path.basename(text)
    text = _text(view.get("path"))
    return os.path.basename(text) if text else ""


def _usage(source: object, task: object) -> dict | None:
    for container in (source, task):
        if not isinstance(container, dict):
            continue
        usage = container.get("token_usage")
        if isinstance(usage, dict):
            return usage
        metadata = container.get("metadata")
        if isinstance(metadata, dict) and isinstance(metadata.get("token_usage"), dict):
            return metadata["token_usage"]
    return None


def _measured(usage: dict | None) -> bool:
    if not isinstance(usage, dict):
        return False

    def counter(name: str) -> int:
        try:
            return int(usage.get(name) or 0)
        except (TypeError, ValueError):
            return 0

    return any(counter(name) > 0 for name in ("prompt", "completion", "total", "calls"))


def _normalized(usage: dict) -> dict[str, int]:
    def counter(name: str) -> int:
        try:
            return max(0, int(usage.get(name) or 0))
        except (TypeError, ValueError):
            return 0

    return {
        "prompt": counter("prompt"),
        "completion": counter("completion"),
        "total": counter("total"),
        "calls": counter("calls"),
    }


def annotate_generation_view(payload: dict, source: object = None) -> dict:
    """Public generation receipt or status: honest tokens, and a rename when one happened.

    A zero counter that no LLM call wrote is ``token_usage: null``. A file
    saved as ``name (2)`` reports ``outputName`` and warning ``output_name_taken``.
    """
    if not isinstance(payload, dict):
        return payload
    view = dict(payload)
    task = view.get("task") if isinstance(view.get("task"), dict) else None
    usage = _usage(source, task)
    if _measured(usage):
        view["token_usage"] = _normalized(usage or {})
        view["token_usage_source"] = "llm"
    else:
        view["token_usage"] = None
        view["token_usage_source"] = "not_measured"
    if task is not None:
        copied = dict(task)
        copied["token_usage"] = view["token_usage"]
        copied["token_usage_source"] = view["token_usage_source"]
        view["task"] = copied
    requested = requested_output_name(source if source is not None else task)
    final = _final_name(view, source)
    if _taken_rename(requested, final):
        view["outputName"] = {"requested": os.path.basename(requested), "final": final, "taken": True}
        warnings = [item for item in view.get("warnings") or [] if isinstance(item, dict)]
        warnings.append({
            "code": "output_name_taken",
            "message": f"{os.path.basename(requested)} already existed; saved as {final}",
        })
        view["warnings"] = warnings
    return view
