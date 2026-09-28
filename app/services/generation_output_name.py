"""Optional generation filenames and the published file identity.

The native saver still names an omitted request from the truncated prompt.
A caller-supplied ``output_name`` replaces that stem. Names that leave the
workspace, or that contain a path separator, fail with ``invalid_output_name``
before any model runs. Status and ``generation.receipt`` project the produced
file as an asset id, a canonical file URL, and a workspace-relative path.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote

from services.asset_catalog import _stable_unmanaged_id
from services.asset_manifest import SCHEMA_NAME


INVALID_OUTPUT_NAME = "invalid_output_name"
_MESSAGE = "Output name must be a single file name inside the workspace"
_MAX_NAME_LENGTH = 180
_PROBE_ROOT = Path("/hocus-output-name-root")


class OutputNameError(ValueError):
    """A requested output name is not a single file inside the workspace."""

    def __init__(self, message: str = _MESSAGE) -> None:
        super().__init__(message)
        self.code = INVALID_OUTPUT_NAME


def _forbidden_character(name: str) -> bool:
    for char in name:
        if char in "/\\:{}" or ord(char) < 32 or ord(char) == 127:
            return True
    return False


def _escapes_workspace(name: str) -> bool:
    if name in {".", ".."} or os.path.isabs(name):
        return True
    try:
        resolved = (_PROBE_ROOT / name).resolve()
    except (OSError, ValueError):
        return True
    return resolved.parent != _PROBE_ROOT or not resolved.is_relative_to(_PROBE_ROOT)


def validate_output_name(value: object) -> str:
    """Return a safe file name, or raise ``OutputNameError``."""
    if not isinstance(value, str) or not value or value != value.strip():
        raise OutputNameError()
    if len(value) > _MAX_NAME_LENGTH or _forbidden_character(value) or _escapes_workspace(value):
        raise OutputNameError()
    return value


def apply_output_name(body: dict) -> str | None:
    """Install ``output_filename`` when ``output_name`` is present.

    ``None`` and a missing key keep the historical truncated-prompt name.
    """
    if not isinstance(body, dict) or "output_name" not in body or body.get("output_name") is None:
        if isinstance(body, dict):
            body.pop("output_name", None)
        return None
    name = validate_output_name(body.pop("output_name"))
    body["output_filename"] = name
    return name


def legacy_prompt_stem(prompt: str, *, max_bytes: int | None = None) -> str:
    """Stem the native saver uses when ``output_filename`` is blank."""
    from shared.utils.utils import sanitize_file_name, truncate_for_filesystem

    return sanitize_file_name(truncate_for_filesystem(str(prompt or ""), max_bytes)).strip()


def chosen_image_filename(output_name: str | None, *, filename_prefix: str) -> str:
    """MiniMax Image-01 file name. Omitted requests keep the stamped name."""
    if output_name:
        stem = Path(validate_output_name(output_name)).stem
        if not stem or stem in {".", ".."}:
            raise OutputNameError()
        return f"{stem}.jpg"
    stamp = time.strftime("%Y-%m-%d-%Hh%Mm%Ss")
    return f"{stamp}_{filename_prefix}_{uuid.uuid4().hex[:8]}.jpg"


def _contains_output_name(command: dict) -> bool:
    if "output_name" in command:
        return True
    payload = command.get("input")
    if not isinstance(payload, dict):
        return False
    if "output_name" in payload:
        return True
    params = payload.get("params")
    return isinstance(params, dict) and "output_name" in params


def _pop_name(container: dict, found: list[object]) -> None:
    if "output_name" in container:
        found.append(container.pop("output_name"))


def prepare_command_output_name(command: object) -> tuple[object, str | None]:
    """Remove ``output_name`` before a closed generation schema sees it.

    Non-generation commands are left untouched so their own schemas still
    reject the field. The caller's original object is not mutated.
    """
    if not isinstance(command, dict):
        return command, None
    operation = command.get("operation")
    if not isinstance(operation, str) or not operation.startswith("generation."):
        return command, None
    if operation == "generation.receipt" or not _contains_output_name(command):
        return command, None
    cloned = json.loads(json.dumps(command))
    found: list[object] = []
    _pop_name(cloned, found)
    payload = cloned.get("input")
    if isinstance(payload, dict):
        _pop_name(payload, found)
        params = payload.get("params")
        if isinstance(params, dict):
            _pop_name(params, found)
    present = [item for item in found if item is not None]
    if not present:
        return cloned, None
    if any(item != present[0] for item in present):
        raise OutputNameError("output_name was supplied more than once")
    return cloned, validate_output_name(present[0])


def _fingerprint(effective: dict) -> str:
    content = {
        "version": effective.get("version"),
        "operation": effective.get("operation"),
        "input": effective.get("input"),
    }
    encoded = json.dumps(
        content, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def attach_output_name(frozen: dict, params: dict, name: str | None) -> tuple[dict, dict]:
    """Put a validated name on the native params and the content fingerprint."""
    if not name:
        return frozen, params
    if not isinstance(params, dict) or not isinstance(frozen, dict):
        raise OutputNameError()
    effective = json.loads(json.dumps(frozen.get("effective")))
    target = effective.get("input") if isinstance(effective, dict) else None
    if not isinstance(target, dict):
        raise OutputNameError()
    nested = target.get("params")
    if isinstance(nested, dict):
        nested["output_name"] = name
    else:
        target["output_name"] = name
    updated = {**frozen, "effective": effective, "fingerprint": _fingerprint(effective)}
    return updated, {**params, "output_name": name}


def _sidecar_asset_id(path: Path) -> str | None:
    sidecar = path.with_suffix(".meta.json")
    try:
        value = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or value.get("schema") != SCHEMA_NAME:
        return None
    asset = value.get("asset")
    if not isinstance(asset, dict):
        return None
    text = str(asset.get("id") or "").strip()
    return text or None


def _canonical_url(filename: str, workspace: str) -> str:
    return f"/api/v1/file/{quote(filename, safe='')}?workspace={quote(workspace, safe='')}"


def _produced_file(filename: object, workspace: str, workspace_dir: str) -> dict[str, str] | None:
    name = str(filename or "").strip()
    if not name or _forbidden_character(name) or _escapes_workspace(name):
        return None
    asset_id = _stable_unmanaged_id(workspace or "default", name)
    if workspace_dir:
        root = Path(workspace_dir).resolve()
        candidate = (root / name).resolve()
        if candidate.parent != root or not candidate.is_relative_to(root):
            return None
        asset_id = _sidecar_asset_id(candidate) or asset_id
    return {
        "asset_id": asset_id,
        "canonical_url": _canonical_url(name, workspace or "default"),
        "path": name,
    }


def _file_names(filenames: object) -> list[object]:
    if not isinstance(filenames, list):
        return []
    return [item for item in filenames if str(item or "").strip()]


def status_output_fields(
    filenames: object,
    *,
    workspace: str,
    workspace_dir: str,
) -> dict[str, Any]:
    """Asset id, canonical URL and workspace-relative path for produced files."""
    outputs = [
        item for item in (
            _produced_file(name, workspace, workspace_dir) for name in _file_names(filenames)
        ) if item
    ]
    first = outputs[0] if outputs else {}
    return {
        "outputs": outputs,
        "asset_id": first.get("asset_id"),
        "canonical_url": first.get("canonical_url"),
        "path": first.get("path"),
    }


def generation_receipt_view(
    receipt: dict,
    task: dict | None,
    *,
    workspace: str,
    workspace_dir: str,
) -> dict[str, Any]:
    """Read-model for ``generation.receipt``. The stored admission is unchanged."""
    refs: object = []
    if isinstance(task, dict):
        refs = task.get("result_refs") or []
    view = {"receipt": receipt, "task": task}
    view.update(status_output_fields(refs, workspace=workspace, workspace_dir=workspace_dir))
    return view
