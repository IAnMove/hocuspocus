"""An asset identity must resolve to one exact image location, never a basename."""
import pytest

from services.asset_manifest import build_asset_manifest, write_asset_manifest
from tests.test_studio_image_resources import resources_fixture, write_image


def managed_image(path, identity):
    write_image(path)
    write_asset_manifest(path, build_asset_manifest(path, asset_id=identity, tool="studio-image"))


@pytest.mark.parametrize("reference", ["asset_exact", "/api/v1/assets/asset_exact"])
def test_asset_id_resolves_real_manifest_in_source_workspace(resources_fixture, reference):
    fixture = resources_fixture
    source = fixture["source"] / "same name.png"
    managed_image(source, "asset_exact")
    managed_image(fixture["output"] / "same name.png", "asset_unrelated")
    params, resources = fixture["service"].prepare_media({"workspace": "output", "image_refs": [reference]})
    assert params["image_refs"] == [str(source)]
    assert resources[0]["workspace"] == "source"
    assert resources[0]["url"] == reference
    canonical = fixture["service"].canonicalize_legacy(reference)
    assert canonical == "/api/v1/file/same%20name.png?workspace=source"
    restored, _ = fixture["service"].prepare_media({"workspace": "output", "image_refs": [canonical]})
    assert restored["image_refs"] == [str(source)]


def test_ambiguous_asset_id_requires_exact_url(resources_fixture):
    fixture = resources_fixture
    managed_image(fixture["source"] / "reference.png", "asset_shared")
    managed_image(fixture["other"] / "reference.png", "asset_shared")
    with pytest.raises(ValueError, match="multiple locations"):
        fixture["service"].prepare_media({"image_refs": ["asset_shared"]})
    with pytest.raises(ValueError, match="multiple locations"):
        fixture["service"].canonicalize_legacy("asset_shared")
    params, _ = fixture["service"].prepare_media({"image_refs": ["/api/v1/file/reference.png?workspace=source"]})
    assert params["image_refs"] == [str(fixture["source"] / "reference.png")]


def test_unknown_identity_never_falls_back_to_filename(resources_fixture):
    fixture = resources_fixture
    managed_image(fixture["source"] / "asset_missing.png", "asset_actual")
    with pytest.raises(ValueError, match="existing image asset"):
        fixture["service"].prepare_media({"image_refs": ["asset_missing"]})


def test_optional_native_frame_slots_keep_their_order(resources_fixture):
    fixture = resources_fixture
    source = fixture["source"] / "frame.png"
    managed_image(source, "asset_frame")
    params, resources = fixture["service"].prepare_media({"image_start": ["", "asset_frame", ""]})
    assert params["image_start"] == ["", str(source), ""]
    assert [(item["role"], item["index"]) for item in resources] == [("image_start", 1)]
