"""Territory notices for catalogue families. No downloads and no GPU."""
from __future__ import annotations

import json

from services import install_catalog
from services.mcp_compact import summarize_model_catalog
from services.model_licences import annotate_catalog, for_family, for_id, licence_id_for

# Families whose licence text excludes the EU, the UK and South Korea.
# hunyuan3d is not a family key: that UI bucket also lists TRELLIS.2, Pixal3D and UniRig.
RESTRICTIVE = {
    "hunyuan": ["EU", "UK", "KR"],
    "hunyuan_1_5": ["EU", "UK", "KR"],
    "minimax_h3": ["EU", "UK", "KR", "US"],
    "h3_advanced": ["EU", "UK", "KR", "US"],
}


def test_every_restrictive_family_carries_one_record():
    seen = {}
    for family, places in RESTRICTIVE.items():
        record = for_family(family)
        assert record["territoryExcluded"] == places
        assert record["url"].startswith("https://")
        assert record["commercial"] is True
        assert record["note"]
        seen[family] = record["id"]
    assert seen["h3_advanced"] == seen["minimax_h3"]
    assert for_family("hunyuan")["id"] != for_family("hunyuan_1_5")["id"]
    assert for_family("hunyuan3d") is None
    assert for_family("wan") is None
    assert for_family("qwen") is None
    assert for_id("missing") is None
    assert licence_id_for({"model_type": "hunyuan3d-2", "family": "hunyuan3d"}) == "hunyuan3d"
    assert licence_id_for({"model_type": "hunyuan3d-2.1", "family": "hunyuan3d"}) == "hunyuan3d"
    assert licence_id_for({"model_type": "trellis2", "family": "hunyuan3d"}) is None
    assert licence_id_for({"model_type": "pixal3d", "family": "hunyuan3d"}) is None
    assert licence_id_for({"model_type": "unirig", "family": "hunyuan3d"}) is None


def test_variants_do_not_copy_the_record():
    avatar = json.loads((install_catalog.ROOT / "app" / "defaults" / "hunyuan_avatar.json").read_text())
    assert "territoryExcluded" not in json.dumps(avatar)
    data = json.loads((install_catalog.APP_DIR / "runtime" / "model_licences.json").read_text())
    ids = [record["id"] for record in data["records"]]
    assert len(ids) == len(set(ids))
    assert data["families"]["h3_advanced"] == "minimax_h3"
    assert "hunyuan3d" not in data["families"]
    assert data["modelPrefixes"]["hunyuan3d"] == "hunyuan3d"
    assert set(data["records"][0]) == {"id", "url", "territoryExcluded", "commercial", "note"}


def test_install_components_reference_the_record_without_blocking():
    hunyuan = install_catalog.get("hunyuan3d")
    legacy = install_catalog.get("minimax_h3")
    plain = install_catalog.get("creation_models")
    assert hunyuan.licence == "hunyuan3d"
    assert legacy.licence == "minimax_h3"
    assert plain.licence is None
    hunyuan_row = hunyuan.as_dict()
    assert hunyuan_row["licence"]["territoryExcluded"] == ["EU", "UK", "KR"]
    assert "US" in legacy.as_dict()["licence"]["territoryExcluded"]
    plain_row = plain.as_dict()
    assert "licence" not in plain_row
    assert set(plain_row) == {"id", "engine", "title", "summary", "estimatedBytes", "restartRequired"}


def test_mcp_listing_returns_the_family_record_once():
    payload = annotate_catalog({
        "families": [
            {"id": "hunyuan", "label": "Hunyuan Video", "order": 20},
            {"id": "wan", "label": "Wan", "order": 0},
        ],
        "models": [
            {"model_type": "hunyuan_avatar", "name": "Hunyuan Avatar", "family": "hunyuan", "description": "Animate"},
            {"model_type": "hunyuan", "name": "Hunyuan", "family": "hunyuan"},
            {"model_type": "t2v", "name": "Wan", "family": "wan", "description": "Wan"},
        ],
    })
    summary = summarize_model_catalog(payload)
    hunyuan = next(item for item in summary["families"] if item["id"] == "hunyuan")
    wan = next(item for item in summary["families"] if item["id"] == "wan")
    assert hunyuan["licence"]["id"] == "hunyuan"
    assert hunyuan["licence"]["territoryExcluded"] == ["EU", "UK", "KR"]
    assert "licence" not in wan
    avatar = next(item for item in summary["models"] if item["id"] == "hunyuan_avatar")
    base = next(item for item in summary["models"] if item["id"] == "hunyuan")
    other = next(item for item in summary["models"] if item["id"] == "t2v")
    assert avatar["licenceId"] == base["licenceId"] == "hunyuan"
    assert "territoryExcluded" not in avatar
    assert "licenceId" not in other
    mixed = summarize_model_catalog(annotate_catalog({
        "families": [{"id": "hunyuan3d", "label": "Hunyuan3D", "order": 350}],
        "models": [
            {"model_type": "hunyuan3d-2", "name": "Hunyuan3D 2", "family": "hunyuan3d"},
            {"model_type": "trellis2", "name": "TRELLIS.2", "family": "hunyuan3d"},
            {"model_type": "unirig", "name": "UniRig", "family": "hunyuan3d"},
        ],
    }))
    bucket = mixed["families"][0]
    assert "licence" not in bucket
    assert bucket["licenceRecords"][0]["id"] == "hunyuan3d"
    assert bucket["licenceRecords"][0]["territoryExcluded"] == ["EU", "UK", "KR"]
    by_id = {item["id"]: item for item in mixed["models"]}
    assert by_id["hunyuan3d-2"]["licenceId"] == "hunyuan3d"
    assert "licenceId" not in by_id["trellis2"]
    assert "licenceId" not in by_id["unirig"]
