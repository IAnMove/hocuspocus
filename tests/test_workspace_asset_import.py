"""assets.import_from_workspace copies a file from another workspace with its provenance, confined to that workspace."""
from __future__ import annotations

import hashlib
import json

import pytest
from fastapi import HTTPException

from tests.media_tool_fixtures import Install


def _manifest(name: str, workspace: str, asset_id: str = "asset_hunyuan_1") -> dict:
    return {"schema": "hocuspocus.asset-manifest", "schema_version": 1,
            "asset": {"id": asset_id, "kind": "model3d", "filename": name, "uri": name, "media": {}},
            "origin": {"tool": "model3d", "workspace_id": workspace, "output_folder": workspace, "actor": "user"},
            "execution": {"status": "completed", "mode": "real"},
            "generation": {"prompts": {"effective": "a wooden galleon"}, "model": {"id": "hunyuan3d"}, "parameters": {}, "inputs": []},
            "timing": {}, "lineage": {"parents": [], "transformations": []}, "technical": {}}


def test_a_model_comes_with_its_sidecar_preview_and_provenance(tmp_path):
    install = Install(tmp_path)
    main, series = install.folder("main"), install.folder("plus-ultra")
    (main / "models").mkdir()
    (main / "models" / "galleon.glb").write_bytes(b"glTF-binary")
    (main / "models" / "galleon.meta.json").write_text(json.dumps(_manifest("galleon.glb", "main")))
    (main / "models" / "galleon.preview.png").write_bytes(b"png")
    result = install.call("assets.import_from_workspace", {"workspace": "plus-ultra", "source_workspace": "main",
                                                           "file": "models/galleon.glb"})["result"]
    digest = hashlib.sha256(b"glTF-binary").hexdigest()
    assert result["file"] == "galleon.glb" and result["sha256"] == digest and result["bytes"] == 11
    assert result["source"] == {"workspace": "main", "file": "models/galleon.glb"} and result["sidecar"] is True
    assert "workspace=plus-ultra" in result["url"] and "already_present" not in result
    assert (series / "galleon.glb").read_bytes() == b"glTF-binary" and (series / "galleon.preview.png").is_file()
    meta = json.loads((series / "galleon.meta.json").read_text())
    assert meta["copied_from"]["workspace"] == "main" and meta["copied_from"]["file"] == "models/galleon.glb"
    assert meta["copied_from"]["sha256"] == digest and meta["copied_from"]["copiedAt"].endswith("Z")
    assert meta["generation"]["prompts"]["effective"] == "a wooden galleon"  # the source's metadata is kept
    assert meta["origin"]["workspace_id"] == "plus-ultra" and meta["asset"]["id"] != "asset_hunyuan_1"
    assert meta["lineage"]["parents"][-1] == {"id": "asset_hunyuan_1", "kind": "model3d", "uri": "models/galleon.glb",
                                              "role": "copied_from"}
    again = install.call("assets.import_from_workspace", {"workspace": "plus-ultra", "source_workspace": "main",
                                                          "file": "models/galleon.glb"})["result"]
    assert again["already_present"] is True and again["file"] == "galleon.glb"


def test_the_default_workspace_root_is_a_source_too(tmp_path):
    install = Install(tmp_path)
    (install.folder("default") / "zeppelin.glb").write_bytes(b"glb")
    result = install.call("assets.import_from_workspace", {"workspace": "ep", "source_workspace": "default",
                                                           "file": "zeppelin.glb"})["result"]
    assert result["file"] == "zeppelin.glb" and (install.folder("ep") / "zeppelin.glb").read_bytes() == b"glb"
    back = install.call("assets.import_from_workspace", {"workspace": "default", "source_workspace": "ep",
                                                         "file": "zeppelin.glb", "destination_filename": "zep2.glb"})["result"]
    assert back["file"] == "zep2.glb" and (install.folder("default") / "zep2.glb").is_file()


def test_a_file_without_sidecar_gets_one_that_records_the_copy(tmp_path):
    install = Install(tmp_path)
    install.folder("main")
    (install.folder("main") / "rayo.png").write_bytes(b"\x89PNG fake")
    install.folder("ep")
    result = install.call("assets.import_from_workspace", {"workspace": "ep", "source_workspace": "main", "file": "rayo.png",
                                                           "destination_filename": "pu-rayo.png"})["result"]
    meta = json.loads((install.folder("ep") / "pu-rayo.meta.json").read_text())
    assert result["file"] == "pu-rayo.png" and result["sidecar"] is True
    assert meta["origin"]["tool"] == "assets.import_from_workspace" and meta["execution"]["mode"] == "import"
    assert meta["copied_from"]["workspace"] == "main" and meta["lineage"]["parents"][0]["role"] == "copied_from"


def test_conflicts_overwrite_and_extension(tmp_path):
    install = Install(tmp_path)
    (install.folder("main") / "theme.wav").write_bytes(b"new theme")
    (install.folder("ep") / "theme.wav").write_bytes(b"old theme")
    payload = {"workspace": "ep", "source_workspace": "main", "file": "theme.wav"}
    with pytest.raises(HTTPException) as exists:
        install.call("assets.import_from_workspace", payload)
    assert exists.value.status_code == 409 and exists.value.detail["code"] == "destination_exists"
    assert (install.folder("ep") / "theme.wav").read_bytes() == b"old theme"
    replaced = install.call("assets.import_from_workspace", {**payload, "overwrite": True})["result"]
    assert replaced["bytes"] == 9 and (install.folder("ep") / "theme.wav").read_bytes() == b"new theme"
    with pytest.raises(HTTPException) as renamed:
        install.call("assets.import_from_workspace", {**payload, "destination_filename": "theme.mp3"})
    assert renamed.value.detail["code"] == "invalid_output_name"


def test_a_shared_stem_sidecar_is_never_clobbered(tmp_path):
    install = Install(tmp_path)
    (install.folder("main") / "song.png").write_bytes(b"cover")
    ep = install.folder("ep")
    (ep / "song.wav").write_bytes(b"audio")
    (ep / "song.meta.json").write_text(json.dumps({"asset": {"filename": "song.wav"}}))
    result = install.call("assets.import_from_workspace", {"workspace": "ep", "source_workspace": "main", "file": "song.png"})["result"]
    assert result["sidecar"] is False and json.loads((ep / "song.meta.json").read_text())["asset"]["filename"] == "song.wav"


@pytest.mark.parametrize("file, code", [
    ("../ep/secret.png", "path_not_allowed"), ("/etc/passwd", "path_not_allowed"), ("a/../../x.png", "path_not_allowed"),
    (".mcp-intents/x.json", "path_not_allowed"), ("missing.glb", "media_not_found"),
])
def test_paths_stay_inside_the_source_workspace(tmp_path, file, code):
    install = Install(tmp_path)
    install.folder("main")
    install.folder("ep")
    with pytest.raises(HTTPException) as error:
        install.call("assets.import_from_workspace", {"workspace": "ep", "source_workspace": "main", "file": file})
    assert error.value.detail["code"] == code


def test_default_cannot_reach_into_a_sibling_workspace(tmp_path):
    install = Install(tmp_path)
    (install.folder("private") / "draft.png").write_bytes(b"draft")
    install.folder("ep")
    with pytest.raises(HTTPException) as error:
        install.call("assets.import_from_workspace", {"workspace": "ep", "source_workspace": "default", "file": "private/draft.png"})
    assert error.value.detail["code"] == "path_not_allowed" and "source_workspace private" in error.value.detail["message"]
    link = install.folder("main") / "escape.png"
    link.symlink_to(install.folder("private") / "draft.png")
    with pytest.raises(HTTPException) as symlink:
        install.call("assets.import_from_workspace", {"workspace": "ep", "source_workspace": "main", "file": "escape.png"})
    assert symlink.value.detail["code"] == "path_not_allowed"
    with pytest.raises(HTTPException) as same:
        install.call("assets.import_from_workspace", {"workspace": "ep", "source_workspace": "ep", "file": "x.png"})
    assert same.value.detail["code"] in ("invalid_command", "media_not_found")


def test_an_unknown_source_workspace_is_refused_without_creating_it(tmp_path):
    from services.production_media_common import MediaToolError
    from services.workspace_asset_import import run
    base = tmp_path / "outputs"
    (base / "show").mkdir(parents=True)
    workspace_dir = lambda name: str(base if name == "default" else base / name)
    with pytest.raises(MediaToolError) as error:
        run({"version": 1, "input": {"workspace": "show", "source_workspace": "typo", "file": "a.glb"}},
            workspace_dir=workspace_dir, uploads_dir=str(tmp_path / "uploads"))
    assert error.value.code == "invalid_workspace" and not (base / "typo").exists()
