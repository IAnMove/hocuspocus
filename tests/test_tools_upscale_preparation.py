"""Provider-free source and processor preparation checks for Tools upscale."""

from copy import deepcopy
import hashlib

import pytest
from fastapi import HTTPException
from PIL import Image

from services.asset_manifest import build_asset_manifest, write_asset_manifest
from services.tools_upscale_commands import (
    _canonical_request_source,
    _request_ready_params,
    _resolve_source,
)
from services.tools_upscale_preparation import prepare_tools_upscale


class FakeResources:
    def __init__(self, roots, references):
        self.roots = roots
        self.references = references

    def workspace_dir(self, name):
        return str(self.roots[name])

    def uploads_dir(self):
        return str(self.roots["__uploads__"])

    def _media(self, value):
        path, workspace = self.references[value]
        return str(path), workspace


@pytest.fixture
def prepared_fixture(tmp_path):
    roots = {name: tmp_path / name for name in ("source", "destination", "__uploads__")}
    for root in roots.values():
        root.mkdir()
    source = roots["source"] / "poster.png"
    reference = roots["source"] / "face.png"
    Image.new("RGB", (19, 13), "navy").save(source)
    Image.new("RGB", (7, 11), "orange").save(reference)
    source_url = "/api/v1/file/poster.png?workspace=source"
    reference_url = "/api/v1/file/face.png?workspace=source"
    resources = FakeResources(
        roots,
        {source_url: (source, "source"), reference_url: (reference, "source")},
    )

    def resolver(_params, **_kwargs):
        return str(source), source.name, "source", "image", "asset-poster", "destination", str(roots["destination"])

    def capabilities():
        return [{"value": "lanczos2", "kind": "spatial", "media": ("image",), "enabled": True}]

    def validate(spatial, temporal, image):
        assert (spatial, temporal, image) == ("lanczos2", "", True)
        return ""

    def settings(method, values):
        assert method == "lanczos2"
        return dict(values)

    return {
        "roots": roots,
        "source": source,
        "reference": reference,
        "source_url": source_url,
        "reference_url": reference_url,
        "resources": resources,
        "resolver": resolver,
        "capabilities": capabilities,
        "validate": validate,
        "settings": settings,
    }


def _params(fixture, **extra):
    params = {
        "workspace": "destination",
        "source": fixture["source_url"],
        "source_kind": "image",
        "method": "lanczos2",
        "seed": -1,
        "wangp_processor_settings": {},
    }
    params.update(extra)
    return params


def _prepare(fixture, params, **extra):
    kwargs = {
        "resources": fixture["resources"],
        "resolve_source": fixture["resolver"],
        "processor_capabilities": fixture["capabilities"],
        "validate_processors": fixture["validate"],
        "processor_settings": fixture["settings"],
    }
    kwargs.update(extra)
    return prepare_tools_upscale(params, **kwargs)


def test_image_source_is_confined_inspected_and_snapshotted(prepared_fixture):
    params = _params(prepared_fixture)
    before = deepcopy(params)
    native, resources = _prepare(prepared_fixture, params)

    assert params == before
    assert native["source_path"] == str(prepared_fixture["source"])
    assert native["source_workspace"] == "source"
    assert native["source_asset_id"] == "asset-poster"
    assert native["source_kind"] == "image"
    assert native["generation_mode"] == "image"
    assert resources[0]["role"] == "source"
    assert resources[0]["workspace"] == "source"
    assert resources[0]["media"]["width"] == 19
    assert resources[0]["sha256"]
    assert resources[0]["size_bytes"] == prepared_fixture["source"].stat().st_size


def test_source_workspace_is_forwarded_and_must_match_resolved_source(prepared_fixture):
    seen = {}

    def resolver(request, **_kwargs):
        seen.update(request)
        return (
            str(prepared_fixture["source"]), prepared_fixture["source"].name,
            "source", "image", "asset-poster", "destination",
            str(prepared_fixture["roots"]["destination"]),
        )

    native, _ = _prepare(
        prepared_fixture,
        _params(prepared_fixture, source_workspace="source"),
        resolve_source=resolver,
    )

    assert seen["source_workspace"] == "source"
    assert native["source_workspace"] == "source"

    with pytest.raises(HTTPException, match="source_workspace"):
        _prepare(
            prepared_fixture,
            _params(prepared_fixture, source_workspace="destination"),
            resolve_source=resolver,
        )


def test_asset_scope_preflight_rejects_ambiguity_and_keeps_explicit_identity(prepared_fixture):
    destination = prepared_fixture["roots"]["destination"] / "poster.png"
    Image.new("RGB", (19, 13), "white").save(destination)
    for path, workspace in ((prepared_fixture["source"], "source"), (destination, "destination")):
        write_asset_manifest(
            path,
            build_asset_manifest(path, asset_id="asset-shared", workspace_id=workspace, tool="fixture"),
        )
    calls = []

    def native_resolver(body, **_kwargs):
        calls.append(deepcopy(body))
        path = prepared_fixture["source"] if body["source_workspace"] == "source" else destination
        return str(path), path.name, body["source_workspace"], "image", "asset-shared", "destination", str(
            prepared_fixture["roots"]["destination"]
        )

    resolve = _resolve_source({
        "_resolve_tool_source": native_resolver,
        "_tool_asset_roots": lambda: [
            {"workspace_id": name, "path": str(path)}
            for name, path in prepared_fixture["roots"].items()
        ],
    })
    request = {
        "source": "/api/v1/assets/asset-shared",
        "source_kind": "image",
        "workspace": "destination",
    }
    with pytest.raises(HTTPException) as ambiguous:
        resolve(request)
    assert ambiguous.value.status_code == 409
    assert ambiguous.value.detail["code"] == "ambiguous_source"
    assert calls == []

    with pytest.raises(HTTPException) as missing:
        resolve({**request, "source_workspace": "missing"})
    assert missing.value.status_code == 409
    assert missing.value.detail["code"] == "source_workspace_mismatch"
    assert calls == []

    native, resources = _prepare(
        prepared_fixture,
        _params(
            prepared_fixture,
            source="/api/v1/assets/asset-shared",
            source_workspace="source",
        ),
        resolve_source=resolve,
    )
    assert calls[-1] == {
        "source_kind": "image",
        "workspace": "destination",
        "asset_id": "asset-shared",
        "source_workspace": "source",
    }
    assert native["source_workspace"] == "source"
    assert native["source_asset_id"] == "asset-shared"
    source_hash = hashlib.sha256(prepared_fixture["source"].read_bytes()).hexdigest()
    destination_hash = hashlib.sha256(destination.read_bytes()).hexdigest()
    assert source_hash != destination_hash
    assert resources[0]["sha256"] == source_hash


def test_processor_reference_is_resolved_before_validator_and_keeps_order(prepared_fixture):
    seen = {}

    def settings(method, values):
        seen["values"] = deepcopy(values)
        return {"spatial_upsampler_reference_images": values["spatial_upsampler_reference_images"]}

    # A small valid MP4 is unnecessary here: the injected probe is the
    # provider-free media boundary, and the source bytes are still hashed.
    clip = prepared_fixture["roots"]["source"] / "poster.mp4"
    clip.write_bytes(b"fixture video")
    native, resources = _prepare(
        prepared_fixture,
        _params(
            prepared_fixture,
            method="h3facerefine",
            source_kind="video",
            source="/api/v1/file/poster.mp4?workspace=source",
            wangp_processor_settings={
                "spatial_upsampler_reference_images": [prepared_fixture["reference_url"]],
            },
        ),
        processor_capabilities=lambda: [{
            "value": "h3facerefine", "kind": "spatial", "media": ("video",), "enabled": True,
        }],
        validate_processors=lambda spatial, temporal, image: "",
        processor_settings=settings,
        processor_parameters=lambda _method: [
            {"name": "spatial_upsampler_reference_images", "type": "array"},
        ],
        resolve_source=lambda _params, **_kwargs: (
            str(clip), clip.name, "source", "video", "asset-clip", "destination",
            str(prepared_fixture["roots"]["destination"]),
        ),
        probe_video=lambda _path: {"duration": 1.5, "width": 96, "height": 54, "fps": 24},
    )

    assert native["source_kind"] == "video"
    assert seen["values"]["spatial_upsampler_reference_images"] == [
        str(prepared_fixture["reference"])
    ]
    assert native["wangp_processor_settings"]["spatial_upsampler_reference_images"] == [
        str(prepared_fixture["reference"])
    ]
    assert [item["role"] for item in resources] == ["source", "processor_reference"]
    assert resources[1]["index"] == 0
    assert resources[1]["workspace"] == "source"


def test_video_source_requires_a_positive_probe(prepared_fixture):
    clip = prepared_fixture["roots"]["source"] / "poster.mp4"
    clip.write_bytes(b"fixture video")

    def resolver(_params, **_kwargs):
        return str(clip), clip.name, "source", "video", "asset-clip", "destination", None

    with pytest.raises(HTTPException, match="duration"):
        _prepare(
            prepared_fixture,
            _params(
                prepared_fixture,
                source="/api/v1/file/poster.mp4?workspace=source",
                source_kind="video",
            ),
            resolve_source=resolver,
            processor_capabilities=lambda: [],
            validate_processors=lambda *_args: "",
            processor_settings=lambda _method, values: dict(values),
            probe_video=lambda _path: {"duration": 0, "width": 96, "height": 54},
        )


def test_invalid_image_is_rejected_before_native_snapshot(prepared_fixture):
    invalid = prepared_fixture["roots"]["source"] / "invalid.png"
    invalid.write_bytes(b"not an image")

    with pytest.raises(HTTPException, match="could not be decoded"):
        _prepare(
            prepared_fixture,
            _params(prepared_fixture, source="/api/v1/file/invalid.png?workspace=source"),
            resolve_source=lambda _params, **_kwargs: (
                str(invalid), invalid.name, "source", "image", "asset-invalid", "destination", None,
            ),
        )


def test_disabled_or_wrong_media_processor_is_rejected(prepared_fixture):
    with pytest.raises(HTTPException, match="disabled"):
        _prepare(
            prepared_fixture,
            _params(prepared_fixture),
            processor_capabilities=lambda: [{
                "value": "lanczos2", "kind": "spatial", "media": ("image",), "enabled": False,
            }],
        )


def test_processor_unknown_setting_is_rejected_without_mutating_input(prepared_fixture):
    params = _params(prepared_fixture, wangp_processor_settings={"spatial_upsampler_prompt": "literal"})
    before = deepcopy(params)
    with pytest.raises(HTTPException, match="not declared"):
        _prepare(prepared_fixture, params, processor_settings=lambda _method, _values: {})
    assert params == before


def test_factory_source_adapter_accepts_prepared_asset_id_without_losing_it():
    seen = []

    def resolver(body, **kwargs):
        seen.append((body, kwargs))
        return "resolved"

    resolve = _resolve_source({"_resolve_tool_source": resolver})
    result = resolve({
        "source_kind": "image",
        "workspace": "destination",
        "asset_id": "asset-poster",
    }, expected_kinds=("image",))

    assert result == "resolved"
    assert seen == [(
        {
            "source_kind": "image",
            "workspace": "destination",
            "asset_id": "asset-poster",
        },
        {"expected_kinds": ("image",)},
    )]


def test_scoped_file_source_does_not_depend_on_global_asset_discovery():
    def unavailable_catalog():
        raise OSError("An unrelated catalog root is unavailable")

    request = {
        "source": "/api/v1/file/poster.png?workspace=source",
        "source_kind": "image", "workspace": "destination",
    }
    resolve = _resolve_source({
        "_resolve_tool_source": lambda body, **_kwargs: body,
        "_tool_asset_roots": unavailable_catalog,
    })
    assert resolve(request) == request


def test_native_projection_keeps_managed_asset_id_with_canonical_source(tmp_path):
    source_root = tmp_path / "source"
    output_root = tmp_path / "destination"
    uploads_root = tmp_path / "uploads"
    source_root.mkdir()
    output_root.mkdir()
    uploads_root.mkdir()
    source_path = source_root / "poster.png"
    source_path.write_bytes(b"already inspected")
    params = {
        "source": "asset-poster",
        "source_kind": "image",
        "workspace": "destination",
        "source_path": str(source_path),
        "source_workspace": "source",
        "source_asset_id": "asset-poster",
    }

    ready = _request_ready_params(params)
    canonical = _canonical_request_source(
        params,
        {
            "_workspace_dir": lambda workspace: str(
                {"source": source_root, "destination": output_root}[workspace]
            ),
        },
    )
    ready.pop("source_path", None)
    ready["source"] = canonical

    assert canonical == "/api/v1/file/poster.png?workspace=source"
    assert ready["asset_id"] == "asset-poster"


@pytest.mark.parametrize("settings", [None, {}, {"spatial_upsampler_prompt": None}])
def test_empty_settings_cross_real_scalar_processor_validator(prepared_fixture, settings):
    from shared.wangp1272.processors import validated_settings

    native, _ = _prepare(
        prepared_fixture,
        _params(prepared_fixture, wangp_processor_settings=settings),
        processor_settings=validated_settings,
        processor_parameters=lambda _method: [],
    )
    assert native["wangp_processor_settings"] == {}
