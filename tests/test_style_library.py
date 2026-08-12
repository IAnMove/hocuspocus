import json

import pytest
from fastapi import HTTPException

from routers.style_library import create_style_library_router
from services.style_library import MINIMAX_H3_1K_SOURCE, StyleLibrary


def _seed_library(tmp_path):
    library = StyleLibrary(tmp_path / "styles")
    library.raw_dir.mkdir(parents=True)
    library.preview_dir.mkdir(parents=True)
    source = {
        **MINIMAX_H3_1K_SOURCE,
        "revision": "revision-123",
        "lastModified": "2026-08-10T02:58:09Z",
    }
    records = []
    for number, prompt, group in (
        (1, "Cinematic rain over a neon city", "Cinematic"),
        (2, "Flat-color animated comedy", "Animation"),
        (3, "Documentary wildlife close-up", "Documentary"),
    ):
        sample = f"{number:06d}"
        style_id = f"minimax-h3-1k-{sample}"
        (library.raw_dir / f"{sample}.txt").write_text(prompt, encoding="utf-8")
        (library.raw_dir / f"{sample}.mp4").write_bytes(b"video")
        (library.preview_dir / f"{style_id}.jpg").write_bytes(b"preview")
        records.append({
            "id": style_id,
            "modelFamily": "minimax",
            "title": f"Sample {sample}",
            "prompt": prompt,
            "collection": "MiniMax H3 1K",
            "group": group,
            "tags": [group.casefold()],
            "sourceOrder": number,
            "sourceFilename": f"{sample}.txt",
            "videoFilename": f"{sample}.mp4",
            "source": source,
            "importedAt": 100 + number,
        })
    library.manifest_path.write_text(json.dumps({
        "version": 1,
        "source": source,
        "styles": records,
        "deletedIds": [],
        "updatedAt": 200,
    }), encoding="utf-8")
    return library


def test_styles_keep_source_attribution_and_support_filters_and_sorting(tmp_path):
    library = _seed_library(tmp_path)

    result = library.list_styles(
        model_family="minimax",
        collection="MiniMax H3 1K",
        group="Animation",
        query="comedy",
        sort="prompt_asc",
    )

    assert result["total"] == 1
    [style] = result["styles"]
    assert style["source"]["id"] == "huggingface:ostris/minimax_h3_1k"
    assert style["source"]["revision"] == "revision-123"
    assert style["source"]["license"] is None
    assert style["previewUrl"].endswith(f"/{style['id']}/preview")
    assert result["facets"]["groups"] == ["Animation"]


def test_style_deletion_is_tombstoned_and_removes_local_assets(tmp_path):
    library = _seed_library(tmp_path)
    style_id = "minimax-h3-1k-000002"

    result = library.delete_style(style_id)

    assert result["deleted"] is True
    assert library.list_styles()["total"] == 2
    manifest = json.loads(library.manifest_path.read_text(encoding="utf-8"))
    assert style_id in manifest["deletedIds"]
    assert not (library.raw_dir / "000002.mp4").exists()
    assert not (library.raw_dir / "000002.txt").exists()
    assert not (library.preview_dir / f"{style_id}.jpg").exists()


def test_delete_endpoint_requires_explicit_confirmation(tmp_path):
    library = _seed_library(tmp_path)
    router = create_style_library_router(library)
    endpoints = {route.path: route.endpoint for route in router.routes}
    delete_endpoint = endpoints["/api/v1/style-library/styles/{style_id}"]

    with pytest.raises(HTTPException, match="confirm=true") as captured:
        delete_endpoint("minimax-h3-1k-000001", False)

    assert captured.value.status_code == 400
    assert delete_endpoint("minimax-h3-1k-000001", True)["deleted"] is True
