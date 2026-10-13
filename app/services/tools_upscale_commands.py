"""Bind the typed Tools upscale contract to the shared native adapter.

This module is deliberately an adapter only.  Queue ownership, durable
receipts and worker dispatch remain in ``ImageGenerationCommands`` and the
existing launch runtime.  In particular, this file does not define a second
registry or start a thread.
"""

from __future__ import annotations

from copy import deepcopy
import os
from typing import Any

from services.image_generation_commands import command_error
from services.native_generation_operation import NativeGenerationOperation
from services.tools_upscale_preparation import prepare_tools_upscale
from services.tools_upscale_spec import (
    _asset_id_from_reference,
    freeze_tools_upscale_spec,
    tools_upscale_schema,
)


def _execution_policy(runtime):
    execution_mode = runtime.get("execution_mode")
    validate = getattr(execution_mode, "validate_generation", None)
    if not callable(validate):
        return lambda _workspace: None

    def check(workspace):
        try:
            validate(workspace)
        except Exception as error:
            error_type = getattr(execution_mode, "ExecutionModeError", ValueError)
            if isinstance(error, error_type):
                raise command_error(409, "execution_policy", str(error)) from error
            raise

    return check


def _resource_adapter(runtime):
    from services.studio_image_resources import StudioImageResources

    workspace_dir = runtime.get("_workspace_dir")
    list_workspaces = runtime.get("_list_workspaces")
    if not callable(workspace_dir) or not callable(list_workspaces):
        raise ValueError("Tools upscale resources are not configured")
    uploads_dir = runtime.get("_uploads_dir")
    if not callable(uploads_dir):
        uploads_dir = lambda: os.path.join(os.getcwd(), "uploads")
    wgp = runtime.get("wgp")
    lora_search_dirs = getattr(wgp, "get_lora_search_dirs", None)
    if not callable(lora_search_dirs):
        lora_search_dirs = lambda _model_type: []
    lora_compatible = runtime.get("_lora_is_compatible_with_model")
    if not callable(lora_compatible):
        lora_compatible = lambda _definition, _path: True
    return StudioImageResources(
        workspace_dir=workspace_dir,
        uploads_dir=uploads_dir,
        list_workspaces=list_workspaces,
        lora_search_dirs=lora_search_dirs,
        lora_compatible=lora_compatible,
    )


def _asset_locations(runtime, asset_id):
    roots_factory = runtime.get("_tool_asset_roots")
    if not callable(roots_factory):
        return None
    from services.asset_catalog import find_asset

    asset = find_asset(roots_factory(), asset_id)
    if asset is None:
        return None
    locations = asset.get("locations")
    if not isinstance(locations, list):
        raise command_error(409, "source_location_unavailable", "The source asset has no valid locations")
    return locations


def _check_asset_scope(runtime, asset_id, source_workspace):
    locations = _asset_locations(runtime, asset_id)
    if locations is None:
        return
    if any(not isinstance(location, dict) for location in locations):
        raise command_error(409, "source_location_unavailable", "The source asset has invalid locations")
    matches = [item for item in locations if item.get("workspace_id") == source_workspace]
    if source_workspace is not None and len(matches) != 1:
        code = "ambiguous_source" if len(matches) > 1 else "source_workspace_mismatch"
        raise command_error(409, code, "The source_workspace does not identify one exact asset location")
    if source_workspace is None and len(locations) != 1:
        code = "source_location_unavailable" if not locations else "ambiguous_source"
        raise command_error(409, code, "Choose a source_workspace for this asset")


def _resolve_source(runtime):
    resolver = runtime.get("_resolve_tool_source") or runtime.get("resolve_tool_source")
    if not callable(resolver):
        return None

    def resolve(params, **kwargs):
        # Preparation already adapts bare/API asset references to the native
        # ``asset_id`` field.  Accept that prepared body as-is while also
        # supporting direct adapter callers that still provide ``source``.
        body = deepcopy(params)
        source = body.get("source")
        asset_id = body.get("asset_id")
        if asset_id is None and isinstance(source, str):
            asset_id = _asset_id_from_reference(source)
        if asset_id:
            body["asset_id"] = asset_id
            body.pop("source", None)
            _check_asset_scope(runtime, asset_id, body.get("source_workspace"))
        expected_kinds = kwargs.get("expected_kinds") or (body.get("source_kind"),)
        try:
            return resolver(body, expected_kinds=expected_kinds)
        except TypeError as first_error:
            try:
                return resolver(body)
            except TypeError:
                raise first_error

    return resolve


def _request_ready_params(params: dict[str, Any]) -> dict[str, Any]:
    """Project inspected source identity into the legacy endpoint body.

    The endpoint accepts one source field. The typed adapter has already
    inspected the canonical URL/asset, so it sends the exact resolved path
    through the existing confined resolver until a canonical API URL can be
    projected. A submitted managed asset ID is retained alongside that URL;
    the native resolver checks that both identify the same basename/location.
    """
    result = deepcopy(params)
    source = result.pop("source", None)
    asset_id = _asset_id_from_reference(source) if isinstance(source, str) else None
    if asset_id:
        result["asset_id"] = asset_id
    path_key = "source_path" if result.get("source_kind") == "image" else "video_path"
    result[path_key] = result.get(path_key)
    return result


def _canonical_request_source(params: dict[str, Any], runtime: dict[str, Any]) -> str | None:
    path_key = "source_path" if params.get("source_kind") == "image" else "video_path"
    path = params.get(path_key)
    workspace_dir = runtime.get("_workspace_dir")
    if not path or not callable(workspace_dir):
        return None
    uploads_dir = runtime.get("_uploads_dir")
    if not callable(uploads_dir):
        uploads_dir = lambda: os.path.join(os.getcwd(), "uploads")
    source_workspace = params.get("source_workspace")
    if not isinstance(source_workspace, str) or not source_workspace:
        return None
    try:
        from services.wangp_submission import wangp_media_url

        workspace_for_url = params.get("workspace") if source_workspace == "__uploads__" else source_workspace
        return wangp_media_url(
            path,
            workspace_for_url,
            uploads_dir=uploads_dir(),
            workspace_dir=workspace_dir(
                source_workspace if source_workspace != "__uploads__" else params.get("workspace")
            ),
        )
    except (OSError, TypeError, ValueError):
        return None


def _worker(runtime):
    policy = runtime["execution_mode"].policy()
    return runtime["_run_generation"] if policy.simulated else runtime["_run_tool_upscale"]


def tools_upscale_command_catalog() -> dict:
    """Return the exact operation entry consumed by HTTP/MCP discovery."""
    schema = tools_upscale_schema()
    input_schema = dict(schema["input"])
    definitions = input_schema.pop("$defs", {})
    return {
        "name": "tools.upscale",
        "version": 2,
        "supportedVersions": [2],
        "domain": "tools",
        "mutation": True,
        "description": (
            "Upscale one exact image or video source in an explicit output "
            "workspace with an installed local processor. Preserve the "
            "source workspace, processor settings and intent_id; the shared "
            "receipt proves admission and its canonical task reports completion."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "$defs": definitions,
            "properties": {
                "version": {"type": "integer", "const": 2},
                "operation": {"const": "tools.upscale"},
                "intent_id": deepcopy(schema["intent_id"]),
                "input": input_schema,
            },
            "required": ["version", "operation", "intent_id", "input"],
        },
    }


# Short aliases used by catalog exporters in adjacent command slices.
tools_upscale_catalog = tools_upscale_command_catalog
upscale_command_catalog = tools_upscale_command_catalog


def create_tools_upscale_operation(runtime: dict[str, Any]) -> NativeGenerationOperation:
    """Create the registered ``tools.upscale`` adapter for one runtime."""
    source_resolver = _resolve_source(runtime)

    def freeze(command):
        frozen = freeze_tools_upscale_spec(command)
        effective = frozen["effective"]["input"]
        return frozen, {
            **deepcopy(effective["params"]),
            "workspace": effective["workspace"],
        }

    def prepare(params):
        prepared, resources = prepare_tools_upscale(
            params,
            resources=_resource_adapter(runtime),
            resolve_source=source_resolver,
            execution_policy=_execution_policy(runtime),
            processor_capabilities=runtime.get("_tools_processor_capabilities"),
            validate_processors=runtime.get("_validate_tools_processors"),
            processor_settings=runtime.get("_validated_tools_processor_settings"),
            processor_parameters=runtime.get("_tools_processor_parameters"),
            probe_video=runtime.get("_probe_tool_video"),
        )
        ready = _request_ready_params(prepared)
        canonical_source = _canonical_request_source(prepared, runtime)
        if canonical_source:
            path_key = "source_path" if prepared.get("source_kind") == "image" else "video_path"
            ready.pop(path_key, None)
            ready["source"] = canonical_source
        return ready, resources

    return NativeGenerationOperation(
        freeze=freeze,
        prepare=prepare,
        catalog=tools_upscale_command_catalog(),
        prepare_request=runtime["tools_upscale"],
        worker=_worker(runtime),
        use_generation_defaults=False,
    )


# Alias kept for discovery code that calls adapters by their operation name.
create_tools_upscale_adapter = create_tools_upscale_operation


__all__ = [
    "create_tools_upscale_adapter",
    "create_tools_upscale_operation",
    "tools_upscale_catalog",
    "tools_upscale_command_catalog",
    "upscale_command_catalog",
]
