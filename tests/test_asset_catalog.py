from __future__ import annotations

import json
from pathlib import Path

from app.services.asset_catalog import find_asset, scan_asset_catalog
from app.services.asset_manifest import build_asset_manifest, write_asset_manifest


def _root(path: Path, workspace: str) -> dict[str, str]:
    path.mkdir(parents=True, exist_ok=True)
    return {"workspace_id": workspace, "path": str(path)}


def test_catalog_lists_every_explicit_workspace_without_leaking_paths(tmp_path: Path):
    first = _root(tmp_path / "first", "first")
    second = _root(tmp_path / "second", "second")
    (Path(first["path"]) / "one.png").write_bytes(b"one")
    (Path(second["path"]) / "two.wav").write_bytes(b"two")

    result = scan_asset_catalog([first, second])
    assert result["total"] == 2
    assert {item["kind"] for item in result["assets"]} == {"image", "audio"}
    encoded = json.dumps(result)
    assert str(tmp_path) not in encoded
    assert all(item["metadata_status"] == "missing" for item in result["assets"])


def test_unmanaged_identity_is_stable_and_scoped_by_workspace(tmp_path: Path):
    alpha = _root(tmp_path / "alpha", "alpha")
    beta = _root(tmp_path / "beta", "beta")
    (Path(alpha["path"]) / "same.mp4").write_bytes(b"a")
    (Path(beta["path"]) / "same.mp4").write_bytes(b"b")

    first = scan_asset_catalog([alpha, beta])
    second = scan_asset_catalog([alpha, beta])
    assert [item["id"] for item in first["assets"]] == [item["id"] for item in second["assets"]]
    assert len({item["id"] for item in first["assets"]}) == 2


def test_canonical_copies_are_one_asset_with_two_locations(tmp_path: Path):
    alpha = _root(tmp_path / "alpha", "alpha")
    beta = _root(tmp_path / "beta", "beta")
    for root in (alpha, beta):
        output = Path(root["path"]) / "shared.png"
        output.write_bytes(b"image")
        write_asset_manifest(
            output,
            build_asset_manifest(
                output, asset_id="asset_shared", tool="studio-image",
                prompts={"effective": "a shared tower"},
            ),
        )

    result = scan_asset_catalog([alpha, beta])
    assert result["total"] == 1
    assert result["assets"][0]["workspace_ids"] == ["alpha", "beta"]
    assert len(result["assets"][0]["locations"]) == 2


def test_catalog_search_filter_pagination_and_detail(tmp_path: Path):
    root = _root(tmp_path / "outputs", "default")
    for index, prompt in enumerate(("enchanted server", "quiet forest", "server choir")):
        output = Path(root["path"]) / f"clip-{index}.mp4"
        output.write_bytes(bytes([index]))
        write_asset_manifest(
            output,
            build_asset_manifest(
                output, asset_id=f"asset_{index}", tool="story-music-video",
                prompts={"effective": prompt}, model={"id": "minimax-h3"},
                timing={"completed_at": 1_700_000_000 + index},
            ),
        )

    filtered = scan_asset_catalog([root], search="server", kind="video", limit=1)
    assert filtered["total"] == 2
    assert len(filtered["assets"]) == 1
    detail = find_asset([root], filtered["assets"][0]["id"])
    assert detail is not None
    assert detail["manifest"]["generation"]["model"]["id"] == "minimax-h3"


def test_catalog_ignores_sidecars_previews_hidden_files_and_symlinks(tmp_path: Path):
    root = _root(tmp_path / "outputs", "default")
    directory = Path(root["path"])
    (directory / "real.png").write_bytes(b"image")
    (directory / "real.meta.json").write_text("{}", encoding="utf-8")
    (directory / "real.preview.png").write_bytes(b"preview")
    (directory / ".hidden.png").write_bytes(b"hidden")
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"outside")
    (directory / "escape.png").symlink_to(outside)

    result = scan_asset_catalog([root])
    assert [item["filename"] for item in result["assets"]] == ["real.png"]
    assert result["assets"][0]["metadata_status"] == "legacy"
