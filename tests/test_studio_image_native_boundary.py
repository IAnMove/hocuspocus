"""Verify prepared Studio images survive the real native media boundary."""
from copy import deepcopy

import pytest
from PIL import Image

from services.studio_image_conditioning import validate_image_selectors
from services.studio_image_resources import StudioImageResources
from services.wangp_submission import prepare_generation_inputs
from tests.test_image_generation_commands import FakeNative, _command, _run


@pytest.mark.parametrize("new_family", [False, True])
@pytest.mark.parametrize("image_mode", [1, 2])
def test_source_workspace_image_survives_native_preparation(tmp_path, new_family, image_mode):
    folders = {name: tmp_path / name for name in ("source", "destination", "uploads")}
    for folder in folders.values():
        folder.mkdir()
    Image.new("RGB", (8, 8), "blue").save(folders["source"] / "same.png")
    Image.new("RGB", (8, 8), "red").save(folders["destination"] / "same.png")
    resources = StudioImageResources(
        workspace_dir=lambda name: folders[name], uploads_dir=lambda: folders["uploads"],
        list_workspaces=lambda: [{"name": name} for name in ("source", "destination")],
        lora_search_dirs=lambda _: [], lora_compatible=lambda *_: True,
    )
    params = {"image_mode": image_mode, "video_prompt_type": "I", "canonical_image_refs": True,
              "image_refs": ["/api/v1/file/same.png?workspace=source"]}
    prepared, identities = resources.prepare_media(params)
    prepare_generation_inputs(prepared, {"image_outputs": True, "wangp_1272": new_family},
                              "destination", uploads_dir=folders["uploads"],
                              workspace_dir=folders["destination"], prepared_images=True)
    assert prepared["image_refs"] == [str(folders["source"] / "same.png")]
    assert identities[0]["workspace"] == "source"
    with Image.open(prepared["image_refs"][0]) as picture:
        assert picture.getpixel((0, 0)) == (0, 0, 255)
    assert params["canonical_image_refs"] is True


def test_json_cannot_claim_that_native_paths_are_already_resolved(tmp_path):
    body = {"image_mode": 1, "image_refs": [str(tmp_path / "outside" / "secret.png")],
            "prepared_images": True, "prepared_studio_images": True}
    with pytest.raises(ValueError):
        prepare_generation_inputs(body, {"image_outputs": True, "wangp_1272": True},
                                  "destination", uploads_dir=tmp_path / "uploads",
                                  workspace_dir=tmp_path / "destination")


@pytest.mark.parametrize("field", ["image_refs", "image_guide", "image_mask", "image_start", "image_end"])
def test_reference_without_consuming_selector_is_rejected(field):
    with pytest.raises(ValueError, match="selector must be enabled"):
        validate_image_selectors({field: ["/api/v1/uploads/image.png"]}, {})


@pytest.mark.parametrize("params", [
    {"image_start": ["", "/api/v1/uploads/image.png"], "image_prompt_type": "S"},
    {"image_end": ["/api/v1/uploads/image.png", ""], "image_prompt_type": "E"},
])
def test_active_empty_frame_slots_are_rejected_before_native_validation(params):
    with pytest.raises(ValueError, match="empty frame slots"):
        validate_image_selectors(params, {"end_frames_always_enabled": True})


def test_native_conditioning_pairs_are_preserved_and_missing_images_rejected():
    params = {field: ["/api/v1/uploads/image.png"]
              for field in ("image_refs", "image_guide", "image_mask", "image_start", "image_end")}
    params.update(image_prompt_type="SE", video_prompt_type="IVA")
    before = deepcopy(params)
    validate_image_selectors(params, {})
    assert params == before
    with pytest.raises(ValueError, match="requires an image"):
        validate_image_selectors({"video_prompt_type": "I"}, {})
    with pytest.raises(ValueError, match="selector must be enabled"):
        validate_image_selectors({**params, "video_prompt_type": "IVAU"}, {})


def test_admission_freezes_native_defaults_and_preserves_explicit_values(tmp_path):
    native = FakeNative(tmp_path)
    defaults = {"output_filename": "original_{seed}", "custom_guide": None,
                "perturbation_layers": [9], "guidance_scale": 99}
    service = native.service()
    service.runtime_defaults = lambda: defaults
    command = _command("freeze-native-settings")
    first = _run(service.submit(command))
    defaults["output_filename"] = "changed_{seed}"
    defaults["perturbation_layers"].append(15)
    replay = _run(service.submit(command))
    assert replay["receipt"] == first["receipt"]
    entry = native.registry("workspace-a").command_admission(command["intent_id"])
    snapshot = entry["effective"]["runtime"]["params"]
    assert snapshot["output_filename"] == "original_{seed}"
    assert snapshot["perturbation_layers"] == [9]
    assert snapshot["guidance_scale"] == command["input"]["guidance_scale"]
    assert len(native.dispatch_calls) == 1
