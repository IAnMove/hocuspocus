from __future__ import annotations

import json
from pathlib import Path

from app.services import asset_catalog
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


def test_inbox_filter_contains_only_noncanonical_assets(tmp_path: Path):
    root = _root(tmp_path / "outputs", "default")
    unmanaged = Path(root["path"]) / "old.png"
    unmanaged.write_bytes(b"old")
    canonical = Path(root["path"]) / "new.png"
    canonical.write_bytes(b"new")
    write_asset_manifest(canonical, build_asset_manifest(canonical, asset_id="asset_new", tool="studio"))

    result = scan_asset_catalog([root], metadata_statuses=("legacy", "missing", "unreadable", "invalid"))

    assert result["total"] == 1
    assert result["assets"][0]["filename"] == "old.png"


def test_catalog_sorts_by_created_time_and_name_with_stable_ids(tmp_path: Path):
    root = _root(tmp_path / "outputs", "default")
    for name, created, asset_id in (
        ("beta.png", 100, "asset_b"),
        ("alpha.png", 200, "asset_a"),
        ("alpha.png", 0, "asset_missing"),
    ):
        output = Path(root["path"]) / f"{asset_id}-{name}"
        output.write_bytes(b"image")
        write_asset_manifest(
            output,
            build_asset_manifest(
                output, asset_id=asset_id, tool="studio",
                timing={"created_at": created, "completed_at": created},
            ),
        )

    newest = scan_asset_catalog([root], sort="created_desc")
    assert [item["id"] for item in newest["assets"]] == ["asset_a", "asset_b", "asset_missing"]
    oldest = scan_asset_catalog([root], sort="created_asc")
    assert [item["id"] for item in oldest["assets"]] == ["asset_b", "asset_a", "asset_missing"]
    by_name = scan_asset_catalog([root], sort="name_asc")
    assert [item["filename"] for item in by_name["assets"]] == [
        "asset_a-alpha.png", "asset_b-beta.png", "asset_missing-alpha.png",
    ]
    by_name_desc = scan_asset_catalog([root], sort="name_desc")
    assert [item["filename"] for item in by_name_desc["assets"]] == [
        "asset_missing-alpha.png", "asset_b-beta.png", "asset_a-alpha.png",
    ]
    page = scan_asset_catalog([root], sort="created_desc", limit=1, offset=0)
    assert page["total"] == 3
    assert page["assets"][0]["id"] == "asset_a"
    default = scan_asset_catalog([root])
    completed = scan_asset_catalog([root], sort="completed_desc")
    assert [item["id"] for item in default["assets"]] == [item["id"] for item in completed["assets"]]


def test_name_desc_keeps_prefix_order_and_stable_ids(tmp_path: Path):
    root = _root(tmp_path / "outputs", "default")
    for name, asset_id in (("a.png", "asset_a"), ("ab.png", "asset_ab"), ("b.png", "asset_b")):
        output = Path(root["path"]) / name
        output.write_bytes(b"image")
        write_asset_manifest(
            output,
            build_asset_manifest(output, asset_id=asset_id, tool="studio"),
        )

    result = scan_asset_catalog([root], sort="name_desc")
    assert [item["filename"] for item in result["assets"]] == ["b.png", "ab.png", "a.png"]


def test_catalog_reparses_only_a_changed_sidecar(tmp_path: Path, monkeypatch):
    root = _root(tmp_path / "outputs", "default")
    output = Path(root["path"]) / "still.png"
    output.write_bytes(b"image")
    write_asset_manifest(
        output,
        build_asset_manifest(output, asset_id="asset_still", tool="studio", prompts={"effective": "first"}),
    )
    reads: list[str] = []
    original = asset_catalog.json.loads

    def counting(text, *args, **kwargs):
        reads.append(text)
        return original(text, *args, **kwargs)

    monkeypatch.setattr(asset_catalog.json, "loads", counting)
    first = scan_asset_catalog([root], sort="created_desc")
    assert first["assets"][0]["prompt_preview"] == "first"
    assert len(reads) == 1
    reads.clear()

    second = scan_asset_catalog([root], sort="created_desc")
    assert second["assets"][0]["prompt_preview"] == "first"
    assert reads == []

    write_asset_manifest(
        output,
        build_asset_manifest(output, asset_id="asset_still", tool="studio", prompts={"effective": "second look"}),
    )
    before = len(reads)
    third = scan_asset_catalog([root], sort="created_desc")
    assert third["assets"][0]["prompt_preview"] == "second look"
    assert len(reads) == before + 1


def test_catalog_accepts_multiple_kinds(tmp_path: Path):
    root = _root(tmp_path / "outputs", "default")
    (Path(root["path"]) / "still.png").write_bytes(b"image")
    (Path(root["path"]) / "clip.mp4").write_bytes(b"video")
    (Path(root["path"]) / "song.wav").write_bytes(b"audio")
    result = scan_asset_catalog([root], kind="image,video")
    assert {item["kind"] for item in result["assets"]} == {"image", "video"}
    assert result["total"] == 2
