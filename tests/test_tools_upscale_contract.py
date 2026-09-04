"""Contracts for the shared Tools upscale image/video boundary.

The real worker is intentionally not imported here: importing the launch
runtime initializes WanGP and model services. Source resolution is exercised
with real temporary files, while the worker implementation is checked from
the standalone service module.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from fastapi import HTTPException

from shared.tools.background_removal_request import (
    RemoveBackgroundRequest,
    UPSCALE_IMAGE_EXTENSIONS,
    UPSCALE_VIDEO_EXTENSIONS,
    resolve_source,
)


ROOT = Path(__file__).resolve().parents[1]


def _workspace_functions(workspace: Path, uploads: Path):
    return {
        "workspace_dir": lambda _workspace: str(workspace),
        "uploads_dir": lambda: str(uploads),
    }


def _resolve(payload: RemoveBackgroundRequest, *, workspace: Path, uploads: Path, kind: str):
    functions = _workspace_functions(workspace, uploads)
    return resolve_source(
        payload,
        destination_workspace="default",
        workspace_dir=functions["workspace_dir"],
        uploads_dir=functions["uploads_dir"],
        asset_finder=lambda _asset_id: None,
        expected_kind=kind,
        allowed_extensions=(
            UPSCALE_IMAGE_EXTENSIONS if kind == "image" else UPSCALE_VIDEO_EXTENSIONS
        ),
        source_label=kind,
    )


def test_upscale_source_boundary_accepts_still_and_video_without_crossing_kinds(tmp_path):
    workspace = tmp_path / "workspace"
    uploads = tmp_path / "uploads"
    workspace.mkdir()
    uploads.mkdir()
    still = workspace / "poster.tiff"
    clip = workspace / "shot.webm"
    still.write_bytes(b"image fixture")
    clip.write_bytes(b"video fixture")

    image_result = _resolve(
        RemoveBackgroundRequest(source=still.name, workspace="default"),
        workspace=workspace,
        uploads=uploads,
        kind="image",
    )
    video_result = _resolve(
        RemoveBackgroundRequest(source=clip.name, workspace="default"),
        workspace=workspace,
        uploads=uploads,
        kind="video",
    )

    assert image_result[:2] == (str(still.resolve()), still.name)
    assert video_result[:2] == (str(clip.resolve()), clip.name)
    with pytest.raises(HTTPException) as mismatch:
        _resolve(
            RemoveBackgroundRequest(source=still.name, workspace="default"),
            workspace=workspace,
            uploads=uploads,
            kind="video",
        )
    assert mismatch.value.status_code == 404


def test_upscale_asset_boundary_rejects_an_image_asset_for_video_processing(tmp_path):
    workspace = tmp_path / "workspace"
    uploads = tmp_path / "uploads"
    workspace.mkdir()
    uploads.mkdir()
    source = workspace / "poster.png"
    source.write_bytes(b"image fixture")
    asset = {
        "id": "asset-poster",
        "kind": "image",
        "locations": [{"workspace_id": "default", "filename": source.name}],
    }

    with pytest.raises(HTTPException) as mismatch:
        resolve_source(
            RemoveBackgroundRequest(asset_id="asset-poster"),
            destination_workspace="default",
            workspace_dir=lambda _workspace: str(workspace),
            uploads_dir=lambda: str(uploads),
            asset_finder=lambda _asset_id: asset,
            expected_kind="video",
            allowed_extensions=UPSCALE_VIDEO_EXTENSIONS,
            source_label="video",
        )
    assert mismatch.value.status_code == 400
    assert "video" in str(mismatch.value.detail)


def _function(tree: ast.AST, name: str) -> ast.AST:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"Function {name!r} not found")


def _called_names(node: ast.AST) -> set[str]:
    names = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        if isinstance(child.func, ast.Name):
            names.add(child.func.id)
        elif isinstance(child.func, ast.Attribute):
            names.add(child.func.attr)
    return names


@pytest.fixture(scope="module")
def launch_tree():
    return ast.parse(
        (ROOT / "app" / "_launch_runtime.py").read_text(encoding="utf-8"),
        filename="app/_launch_runtime.py",
    )


@pytest.fixture(scope="module")
def service_tree():
    return ast.parse(
        (ROOT / "app" / "services" / "tools_upscale.py").read_text(encoding="utf-8"),
        filename="app/services/tools_upscale.py",
    )


def test_image_worker_branch_never_calls_video_decoder_or_writer(service_tree):
    worker = _function(service_tree, "run_tool_upscale")
    image_branch = next(
        node for node in ast.walk(worker)
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Compare)
        and isinstance(node.test.left, ast.Name)
        and node.test.left.id == "source_kind"
        and any(
            isinstance(op, ast.Eq) for op in node.test.ops
        )
        and any(
            isinstance(value, ast.Constant) and value.value == "image"
            for value in node.test.comparators
        )
    )
    image_calls = _called_names(ast.Module(body=image_branch.body, type_ignores=[]))
    video_calls = _called_names(ast.Module(body=image_branch.orelse, type_ignores=[]))

    assert "upscale_image" in image_calls
    assert not image_calls.intersection({
        "get_video_info", "extract_audio_tracks", "get_resampled_video", "save_video",
    })
    assert {"get_video_info", "extract_audio_tracks", "get_resampled_video", "save_video"} <= video_calls


def test_still_adapter_uses_the_existing_upscale_pipeline_in_still_mode(service_tree):
    helper = _function(service_tree, "upscale_image")
    spatial_calls = [
        node for node in ast.walk(helper)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "perform_spatial_upsampling"
    ]
    assert len(spatial_calls) == 1
    still_keyword = next(
        keyword.value for keyword in spatial_calls[0].keywords
        if keyword.arg == "still_image"
    )
    assert isinstance(still_keyword, ast.Constant) and still_keyword.value is True


def test_launch_worker_is_a_thin_facade_over_the_tools_service(launch_tree):
    worker = _function(launch_tree, "_run_tool_upscale")
    calls = _called_names(worker)
    assert "run_tool_upscale" in calls
    assert "_coordinated_generation_slot" not in calls


def test_upscale_service_does_not_import_the_launch_runtime():
    source = (ROOT / "app" / "services" / "tools_upscale.py").read_text(encoding="utf-8")
    assert "_launch_runtime" not in source
    assert "from fastapi" not in source


def test_shared_upscale_route_accepts_both_source_kinds_and_uses_one_worker(launch_tree):
    route = _function(launch_tree, "tools_upscale")
    resolver = next(
        node for node in ast.walk(route)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_resolve_tool_source"
    )
    expected_kinds = next(
        keyword.value for keyword in resolver.keywords if keyword.arg == "expected_kinds"
    )
    assert isinstance(expected_kinds, ast.Tuple)
    assert [value.value for value in expected_kinds.elts] == ["image", "video"]
    # The route selects the real or simulated worker once, then passes that
    # callable to the shared thread launcher.  The worker names therefore
    # appear in the assignment rather than as direct calls in the route body.
    worker_assignment = next(
        node for node in ast.walk(route)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "worker" for target in node.targets)
    )
    assert {
        node.id for node in ast.walk(worker_assignment.value)
        if isinstance(node, ast.Name)
    } >= {"_run_tool_upscale", "_run_generation"}
