"""Provider-free adversarial checks for Studio image and LoRA resources.

The fixture uses only temporary files and a small Pillow image.  It models the
Studio output workspace separately from source workspaces so a same-named file
cannot silently satisfy a reference from the wrong root.
"""

from copy import deepcopy
import hashlib
from pathlib import Path

import pytest
from PIL import Image, UnidentifiedImageError

from services.studio_image_resources import (
    StudioImageResources,
    validate_lora_multipliers,
)


@pytest.fixture
def resources_fixture(tmp_path):
    uploads = tmp_path / "uploads"
    output = tmp_path / "output-workspace"
    source = tmp_path / "source-workspace"
    other = tmp_path / "other-workspace"
    for root in (uploads, output, source, other):
        root.mkdir()

    workspaces = {
        "output": output,
        "source": source,
        "other": other,
    }
    lora_roots = {}

    def workspace_dir(name):
        return str(workspaces.get(name, tmp_path / name))

    def uploads_dir():
        return str(uploads)

    def list_workspaces():
        return [{"name": name} for name in workspaces]

    def lora_search_dirs(model_type):
        return [str(root) for root in lora_roots.get(model_type, [])]

    compatible_calls = []

    def lora_compatible(model_definition, path):
        compatible_calls.append((model_definition, path))
        return model_definition.get("compatible", True)

    service = StudioImageResources(
        workspace_dir=workspace_dir,
        uploads_dir=uploads_dir,
        list_workspaces=list_workspaces,
        lora_search_dirs=lora_search_dirs,
        lora_compatible=lora_compatible,
    )
    return {
        "service": service,
        "uploads": uploads,
        "output": output,
        "source": source,
        "other": other,
        "workspaces": workspaces,
        "lora_roots": lora_roots,
        "compatible_calls": compatible_calls,
    }


def write_image(path: Path, color=(40, 80, 120)):
    Image.new("RGB", (17, 11), color).save(path)


def canonical_upload(name):
    return f"/api/v1/uploads/{name}"


def canonical_file(name, workspace="source"):
    return f"/api/v1/file/{name}?workspace={workspace}"


def test_media_keeps_upload_and_declared_source_workspace_separate(resources_fixture):
    fixture = resources_fixture
    upload = fixture["uploads"] / "reference.png"
    source = fixture["source"] / "reference.png"
    output_same_name = fixture["output"] / "reference.png"
    write_image(upload, (1, 2, 3))
    write_image(source, (4, 5, 6))
    write_image(output_same_name, (7, 8, 9))

    params = {
        "workspace": "output",
        "image_refs": [canonical_upload("reference.png"), canonical_file("reference.png")],
        "image_start": canonical_file("reference.png"),
        "image_end": canonical_upload("reference.png"),
        "canonical_image_refs": True,
    }
    working, resources = fixture["service"].prepare_media(params)

    assert working["workspace"] == "output"
    assert working["image_refs"] == [str(upload.resolve()), str(source.resolve())]
    assert working["image_start"] == str(source.resolve())
    assert working["image_end"] == str(upload.resolve())
    assert [item["role"] for item in resources] == [
        "image_refs", "image_refs", "image_start", "image_end",
    ]
    assert [item["index"] for item in resources] == [0, 1, 0, 0]
    assert [item["workspace"] for item in resources] == [
        "__uploads__", "source", "source", "__uploads__",
    ]
    assert resources[0]["sha256"] == hashlib.sha256(upload.read_bytes()).hexdigest()
    assert resources[1]["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert working["image_refs"][1] != str(output_same_name.resolve())
    assert "canonical_image_refs" not in working


@pytest.mark.parametrize(
    "reference",
    [
        "/api/v1/file/reference.png?workspace=source&workspace=source",
        "/api/v1/file/reference.png?workspace=unknown",
        "/api/v1/file/reference.png",
        "https://example.invalid/reference.png?workspace=source",
        "/api/v1/file/../outside.png?workspace=source",
        "/api/v1/uploads/../outside.png",
    ],
)
def test_media_rejects_duplicate_unknown_http_and_traversal_references(resources_fixture, reference):
    fixture = resources_fixture
    write_image(fixture["source"] / "reference.png")
    (fixture["other"] / "outside.png").write_bytes(b"outside")

    with pytest.raises(ValueError):
        fixture["service"].prepare_media({"workspace": "output", "image_refs": [reference]})


def test_media_rejects_a_symlink_that_resolves_outside_declared_root(resources_fixture, tmp_path):
    fixture = resources_fixture
    outside = tmp_path / "outside.png"
    write_image(outside)
    link = fixture["source"] / "escape.png"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("file symlinks are unavailable on this platform")

    with pytest.raises(ValueError):
        fixture["service"].prepare_media({
            "workspace": "output",
            "image_refs": [canonical_file("escape.png")],
        })


def test_canonicalize_legacy_uses_exact_contained_absolute_path_and_does_not_adopt_homonyms(
    resources_fixture,
):
    fixture = resources_fixture
    upload = fixture["uploads"] / "same.png"
    source = fixture["source"] / "same.png"
    output = fixture["output"] / "same.png"
    for path in (upload, source, output):
        write_image(path)

    service = fixture["service"]
    assert service.canonicalize_legacy(str(upload)) == "/api/v1/uploads/same.png"
    assert service.canonicalize_legacy(str(source)) == "/api/v1/file/same.png?workspace=source"
    assert service.canonicalize_legacy(str(output)) == "/api/v1/file/same.png?workspace=output"
    with pytest.raises(ValueError):
        service.canonicalize_legacy("same.png")
    nested = fixture["uploads"].parent / ".pinokio-temp"
    nested.mkdir()
    relative = nested / "picked.jpg"
    write_image(relative)
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.chdir(fixture["uploads"].parent)
    try:
        adopted = service.canonicalize_legacy(".pinokio-temp/picked.jpg")
    finally:
        monkeypatch.undo()
    assert adopted.startswith("/api/v1/uploads/")
    outside = fixture["uploads"].parent / "outside.png"
    write_image(outside)
    with pytest.raises(ValueError):
        service.canonicalize_legacy(str(outside))


def test_local_media_roots_never_include_the_filesystem_root(resources_fixture):
    roots = resources_fixture["service"]._local_media_roots()
    assert Path.cwd().resolve() in roots
    assert all(len(root.parts) > 1 for root in roots)


def test_canonicalize_legacy_rejects_absolute_cwd_file_and_root_relative_passwd(resources_fixture, tmp_path, monkeypatch):
    service = resources_fixture["service"]
    leak = Path("/etc/passwd")
    if leak.is_file():
        with pytest.raises(ValueError):
            service.canonicalize_legacy(str(leak))
        with pytest.raises(ValueError):
            service.canonicalize_legacy("etc/passwd")
    app = tmp_path / "app"
    app.mkdir()
    secret = app / "secret.png"
    write_image(secret)
    monkeypatch.chdir(app)
    with pytest.raises(ValueError, match="outside known media"):
        service.canonicalize_legacy(str(secret))


def test_canonicalize_legacy_rejects_symlink_outside_known_media_roots(resources_fixture, tmp_path):
    fixture = resources_fixture
    outside = tmp_path / "not-managed.png"
    write_image(outside)
    link = fixture["source"] / "legacy-link.png"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("file symlinks are unavailable on this platform")

    with pytest.raises(ValueError):
        fixture["service"].canonicalize_legacy(str(link))


def test_nested_named_workspace_wins_over_parent_default_root_and_default_url_is_rejected(tmp_path):
    uploads = tmp_path / "uploads"
    outputs = tmp_path / "outputs"
    named = outputs / "named-workspace"
    uploads.mkdir()
    named.mkdir(parents=True)
    image = named / "nested.png"
    write_image(image)
    workspaces = {"default": outputs, "named": named}

    service = StudioImageResources(
        workspace_dir=lambda name: str(workspaces[name]),
        uploads_dir=lambda: str(uploads),
        list_workspaces=lambda: [{"name": name} for name in workspaces],
        lora_search_dirs=lambda _model_type: [],
        lora_compatible=lambda _definition, _path: True,
    )

    assert service.canonicalize_legacy(str(image)) == "/api/v1/file/nested.png?workspace=named"
    assert service._media("/api/v1/file/nested.png?workspace=named")[0] == str(image.resolve())
    with pytest.raises(ValueError, match="actual source workspace"):
        service._media("/api/v1/file/named-workspace/nested.png?workspace=default")


def test_invalid_pillow_input_is_rejected_before_prepared_media_is_returned(resources_fixture):
    fixture = resources_fixture
    invalid = fixture["uploads"] / "not-an-image.png"
    invalid.write_bytes(b"this is not an image")

    with pytest.raises(UnidentifiedImageError):
        fixture["service"].prepare_media({
            "workspace": "output",
            "image_refs": [canonical_upload("not-an-image.png")],
        })


def test_media_snapshot_is_detached_and_input_order_literals_and_sha_are_preserved(resources_fixture):
    fixture = resources_fixture
    first = fixture["uploads"] / "first.png"
    second = fixture["source"] / "second.png"
    write_image(first, (10, 20, 30))
    write_image(second, (30, 20, 10))
    params = {
        "workspace": "output",
        "prompt": '  literal "mañana"\nsecond line  ',
        "image_refs": [canonical_file("second.png"), canonical_upload("first.png")],
        "nested": {"keep": [1, 2, 3]},
    }
    before = deepcopy(params)

    working, resources = fixture["service"].prepare_media(params)

    assert params == before
    assert working is not params
    assert working["nested"] is not params["nested"]
    assert working["prompt"] == before["prompt"]
    assert [item["url"] for item in resources] == params["image_refs"]
    assert [item["sha256"] for item in resources] == [
        hashlib.sha256(second.read_bytes()).hexdigest(),
        hashlib.sha256(first.read_bytes()).hexdigest(),
    ]
    params["image_refs"].reverse()
    params["nested"]["keep"].append(4)
    assert working["image_refs"] == [str(second.resolve()), str(first.resolve())]
    assert working["nested"] == {"keep": [1, 2, 3]}


def test_lora_lookup_is_model_specific_and_records_identity_without_mutating_params(resources_fixture):
    fixture = resources_fixture
    model_a_root = fixture["uploads"].parent / "loras-a"
    model_b_root = fixture["uploads"].parent / "loras-b"
    model_a_root.mkdir()
    model_b_root.mkdir()
    a = model_a_root / "style.safetensors"
    b = model_b_root / "style.safetensors"
    a.write_bytes(b"model-a-lora")
    b.write_bytes(b"model-b-lora")
    fixture["lora_roots"]["model-a"] = [model_a_root]
    fixture["lora_roots"]["model-b"] = [model_b_root]
    params = {"model_type": "model-a", "activated_loras": ["style.safetensors"]}
    before = deepcopy(params)

    resources = fixture["service"].prepare_loras(params, {"compatible": True})

    assert params == before
    assert resources == [{
        "role": "lora",
        "name": "style.safetensors",
        "sha256": hashlib.sha256(a.read_bytes()).hexdigest(),
        "size_bytes": a.stat().st_size,
    }]
    assert fixture["compatible_calls"] == [({"compatible": True}, str(a.resolve()))]


def test_lora_missing_ambiguous_incompatible_and_path_escape_are_rejected(resources_fixture):
    fixture = resources_fixture
    missing_root = fixture["uploads"].parent / "loras-missing"
    missing_root.mkdir()
    fixture["lora_roots"]["missing"] = [missing_root]
    with pytest.raises(ValueError, match="missing or ambiguous"):
        fixture["service"].prepare_loras(
            {"model_type": "missing", "activated_loras": ["missing.safetensors"]},
            {},
        )

    first_root = fixture["uploads"].parent / "loras-first"
    second_root = fixture["uploads"].parent / "loras-second"
    first_root.mkdir()
    second_root.mkdir()
    (first_root / "same.safetensors").write_bytes(b"first")
    (second_root / "same.safetensors").write_bytes(b"second")
    fixture["lora_roots"]["ambiguous"] = [first_root, second_root]
    with pytest.raises(ValueError, match="missing or ambiguous"):
        fixture["service"].prepare_loras(
            {"model_type": "ambiguous", "activated_loras": ["same.safetensors"]},
            {},
        )

    compatible_root = fixture["uploads"].parent / "loras-incompatible"
    compatible_root.mkdir()
    (compatible_root / "incompatible.safetensors").write_bytes(b"incompatible")
    fixture["lora_roots"]["incompatible"] = [compatible_root]
    with pytest.raises(ValueError, match="incompatible"):
        fixture["service"].prepare_loras(
            {"model_type": "incompatible", "activated_loras": ["incompatible.safetensors"]},
            {"compatible": False},
        )

    fixture["lora_roots"]["escape"] = [first_root]
    with pytest.raises(ValueError, match="exact LoRA"):
        fixture["service"].prepare_loras(
            {"model_type": "escape", "activated_loras": ["../same.safetensors"]},
            {},
        )


def test_lora_lookup_rejects_a_symlink_that_resolves_outside_model_roots(resources_fixture, tmp_path):
    fixture = resources_fixture
    model_root = fixture["uploads"].parent / "loras-symlink"
    model_root.mkdir()
    outside = tmp_path / "outside.safetensors"
    outside.write_bytes(b"outside model adapter")
    link = model_root / "escape.safetensors"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("file symlinks are unavailable on this platform")
    fixture["lora_roots"]["symlink"] = [model_root]

    with pytest.raises(ValueError, match="outside its model"):
        fixture["service"].prepare_loras(
            {"model_type": "symlink", "activated_loras": ["escape.safetensors"]},
            {},
        )


def test_lora_multiplier_count_and_nonfinite_values_are_rejected():
    too_many = {
        "activated_loras": ["one.safetensors", "two.safetensors"],
        "loras_multipliers": "1 0.5 0.25",
        "num_inference_steps": 4,
    }
    with pytest.raises(ValueError, match="exceeds"):
        validate_lora_multipliers(too_many, maximum_phases=2)

    for value in ("nan", "inf", "-inf", "1;nan"):
        with pytest.raises(ValueError, match="finite"):
            validate_lora_multipliers(
                {
                    "activated_loras": ["one.safetensors"],
                    "loras_multipliers": value,
                    "num_inference_steps": 4,
                },
                maximum_phases=2,
            )


def test_lora_multiplier_phases_are_validated_without_normalizing_or_mutating_input():
    params = {
        "activated_loras": ["one.safetensors", "two.safetensors"],
        "loras_multipliers": "1;0 0;1",
        "num_inference_steps": 4,
        "model_switch_phase": 1,
    }
    before = deepcopy(params)

    assert validate_lora_multipliers(params, maximum_phases=2) is None
    assert params == before
    with pytest.raises(ValueError, match="at most 2 phases"):
        validate_lora_multipliers(
            {
                **params,
                "loras_multipliers": "1;0;0 0;1;0",
            },
            maximum_phases=2,
        )
