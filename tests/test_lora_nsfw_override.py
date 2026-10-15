"""NSFW override of a LoRA, including one that lives in a LINKED install's loras folder (assets-02).

The listing (/loras/installed) walks the primary loras root plus every linked install's; the override used
to walk only the primary root and answered 404 for a LoRA the listing shows. Linked folders are read-only to
the product, so the override of a linked file lives in the primary-mirror sidecar the listing already reads
first, seeded from the linked file's own sidecar so the row keeps its name, trigger words and preview.
"""
from __future__ import annotations

import asyncio
import json
import os
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.services import lora_library

LINKED_SIDECAR = {"name": "Transition", "nsfw": True, "trainedWords": ["trans"], "modelId": 7, "versionId": 9}


class _Request:
    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


def _override(filename, nsfw):
    return asyncio.run(lora_library.set_lora_nsfw_override(_Request({"filename": filename, "nsfw": nsfw})))


def _listed(filename):
    return next(row for row in lora_library.list_all_installed_loras()["loras"] if row["filename"] == filename)


def _tree(root):
    return {os.path.join(d, f): open(os.path.join(d, f), "rb").read() for d, _dirs, files in os.walk(root) for f in files}


@pytest.fixture
def layout(tmp_path, monkeypatch):
    primary = tmp_path / "primary" / "loras"
    (primary / "ltx2").mkdir(parents=True)
    (primary / "ltx2" / "own.safetensors").write_bytes(b"x" * 16)
    linked_app = tmp_path / "linked" / "app"
    (linked_app / "ckpts").mkdir(parents=True)
    linked = linked_app / "loras"
    (linked / "ltx2").mkdir(parents=True)
    (linked / "ltx2" / "ltx2.3-transition.safetensors").write_bytes(b"y" * 16)
    (linked / "ltx2" / "ltx2.3-transition.civitai.json").write_text(json.dumps(LINKED_SIDECAR), encoding="utf-8")
    monkeypatch.setattr(lora_library, "wgp", SimpleNamespace(server_config={"loras_root": str(primary)}))
    monkeypatch.setattr(lora_library, "_get_linked_model_folders", lambda: [str(linked_app / "ckpts")])
    return SimpleNamespace(primary=primary, linked=linked, mirror=primary / "ltx2" / "ltx2.3-transition.civitai.json")


def test_override_of_a_linked_lora_is_accepted_and_keeps_the_rows_metadata(layout):
    before = _tree(layout.linked)
    assert _listed("ltx2.3-transition.safetensors")["nsfw"] is True

    assert _override("ltx2.3-transition.safetensors", False) == {
        "filename": "ltx2.3-transition.safetensors", "nsfw": False, "nsfw_overridden": True}

    row = _listed("ltx2.3-transition.safetensors")
    assert (row["nsfw"], row["nsfw_overridden"], row["linked"]) == (False, True, True)
    assert row["name"] == "Transition" and row["trained_words"] == ["trans"] and row["civitai_model_id"] == 7
    assert _tree(layout.linked) == before, "a linked install is read-only"
    mirror = json.loads(layout.mirror.read_text(encoding="utf-8"))
    assert mirror["nsfw_override"] is False and mirror["name"] == "Transition"


def test_clearing_the_override_of_a_linked_lora_falls_back_to_the_civitai_flag(layout):
    _override("ltx2.3-transition.safetensors", False)

    assert _override("ltx2.3-transition.safetensors", None) == {
        "filename": "ltx2.3-transition.safetensors", "nsfw": True, "nsfw_overridden": False}
    row = _listed("ltx2.3-transition.safetensors")
    assert (row["nsfw"], row["nsfw_overridden"], row["name"]) == (True, False, "Transition")


def test_clearing_a_flag_that_was_never_set_does_not_create_a_mirror_sidecar(layout):
    assert _override("ltx2.3-transition.safetensors", None)["nsfw_overridden"] is False
    assert not layout.mirror.exists()


def test_override_of_a_primary_lora_still_writes_beside_the_file(layout):
    assert _override("own.safetensors", True) == {"filename": "own.safetensors", "nsfw": True, "nsfw_overridden": True}
    sidecar = layout.primary / "ltx2" / "own.civitai.json"
    assert json.loads(sidecar.read_text(encoding="utf-8")) == {"nsfw_override": True}
    assert _listed("own.safetensors")["nsfw_overridden"] is True


def test_a_lora_that_no_root_has_is_still_a_404(layout):
    with pytest.raises(HTTPException) as refusal:
        _override("nowhere.safetensors", True)
    assert refusal.value.status_code == 404
