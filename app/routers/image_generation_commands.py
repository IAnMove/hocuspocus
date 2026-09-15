"""HTTP and MCP projections of the executable image command contract."""
from __future__ import annotations
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError, field_validator
from services.image_generation_spec import image_generation_schema
from services.studio_image_spec import studio_image_schema
from services.image_generation_commands import command_error


class ReferenceResolutionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    references: list[StrictStr] = Field(min_length=1, max_length=64)
    media_kind: Literal["image", "audio", "video", "studio_video"] = "image"


class UISubmissionContext(BaseModel):
    """Optional attribution, never a source of permissions or target IDs."""
    model_config = ConfigDict(extra="forbid", strict=True)
    workflowId: StrictStr | None = Field(default=None, min_length=1, max_length=200)
    runId: StrictStr | None = Field(default=None, min_length=1, max_length=200)

    @field_validator("workflowId", "runId")
    @classmethod
    def nonblank(cls, value):
        if value is not None and (not value.strip() or value != value.strip()):
            raise ValueError("Use an exact non-blank context ID")
        return value


def _ui_context(request):
    raw = request.headers.get("X-Hocus-UI-Context", "{}")
    if len(raw) > 2048:
        raise command_error(422, "invalid_ui_context", "Submission context is too long")
    try:
        return UISubmissionContext.model_validate_json(raw).model_dump(exclude_none=True)
    except ValidationError as error:
        raise command_error(422, "invalid_ui_context", "Use only exact workflowId and runId attribution") from error


def image_command_catalog(additional_operations=()):
    spec = image_generation_schema()
    studio = studio_image_schema()
    studio_input = dict(studio["input"])
    definitions = studio_input.pop("$defs", {})
    definitions["StudioCommandInput"] = studio_input
    envelope = {"type": "object", "additionalProperties": False,
                "properties": {"version": {"type": "integer", "enum": [1, 2]},
                               "operation": {"const": "generation.image"},
                               "intent_id": spec["intent_id"], "input": {"type": "object"}},
                "required": ["version", "operation", "intent_id", "input"],
                "$defs": definitions,
                "oneOf": [
                    {"properties": {"version": {"const": 1}, "input": spec["input"]}},
                    {"properties": {"version": {"const": 2}, "input": {"$ref": "#/$defs/StudioCommandInput"}}},
                ]}
    receipt_input = {"type": "object", "additionalProperties": False,
                     "properties": {"workspace": spec["input"]["properties"]["workspace"],
                                    "intent_id": spec["intent_id"]}, "required": ["workspace", "intent_id"]}
    return [{"name": "generation.image", "version": 2, "supportedVersions": [1, 2], "domain": "studio", "mutation": True,
             "description": "Admit an image job with an installed model and explicit output workspace. Version 1 is a single text-to-image request; version 2 accepts the complete typed Studio image parameters, canonical references, LoRAs and image processors. Preserve literal prompts and reuse intent_id only for retries. The receipt proves admission; inspect its task for completion.",
             "inputSchema": envelope},
            {"name": "generation.receipt", "version": 1, "domain": "studio", "mutation": False,
             "description": "Read an immutable generation admission and its current canonical task in the exact original output workspace.",
             "inputSchema": {"type": "object", "additionalProperties": False,
                             "properties": {"version": {"type": "integer", "const": 1},
                                            "operation": {"const": "generation.receipt"}, "input": receipt_input},
                             "required": ["version", "operation", "input"]}}, *additional_operations]


def image_command_handlers(service):
    def submission_handler(operation):
        async def submit(arguments):
            if not isinstance(arguments, dict) or set(arguments) != {"version", "intent_id", "input"}:
                raise command_error(422, "invalid_command", "Use version, intent_id and input for the generation tool")
            return await service.submit({**arguments, "operation": operation}, trusted_tool="external_agent")
        return submit

    def receipt(arguments):
        if (not isinstance(arguments, dict) or set(arguments) != {"version", "input"}
                or type(arguments.get("version")) is not int or arguments["version"] != 1
                or not isinstance(arguments["input"], dict)
                or set(arguments["input"]) != {"workspace", "intent_id"}):
            raise command_error(422, "invalid_command", "Use version 1 with workspace and intent_id")
        return service.receipt(**arguments["input"])

    operations = {"generation.image", *getattr(service, "operations", {})}
    return {**{operation: submission_handler(operation) for operation in operations}, "generation.receipt": receipt}


def create_image_generation_commands_router(service):
    router = APIRouter()

    @router.get("/api/v1/generation/commands")
    def catalog():
        return {"version": 2, "operations": image_command_catalog(
            adapter.catalog for adapter in getattr(service, "operations", {}).values())}

    @router.post("/api/v1/generation/commands")
    async def submit(request: Request):
        try:
            command = await request.json()
        except ValueError as error:
            raise command_error(422, "invalid_command", "Command must be valid JSON") from error
        surface = request.headers.get("X-Hocus-UI-Surface", "studio")
        if surface not in {"studio", "wizard"}:
            raise command_error(422, "invalid_ui_surface", "Choose a known initiating UI surface")
        # Declared UI attribution, as on the native Studio endpoint. This is
        # never used for authorization. MCP supplies its own external context.
        return await service.submit(command, trusted_tool="wizard" if surface == "wizard" else None,
                                    submission_context=_ui_context(request))

    @router.get("/api/v1/generation/commands/receipt")
    def receipt(workspace: str, intent_id: str):
        return service.receipt(workspace, intent_id)

    @router.post("/api/v1/generation/commands/references")
    def references(body: ReferenceResolutionInput):
        """Read-only migration of exact legacy UI paths into canonical URLs."""
        resolve = getattr(service, "canonicalize_reference", None)
        if not callable(resolve):
            raise command_error(503, "reference_resolution_unavailable", "Reference resolution is unavailable")
        if any(not 1 <= len(value) <= 8192 for value in body.references):
            raise command_error(422, "invalid_reference", "An exact bounded media reference is required")
        try:
            return {"references": [resolve(value) if body.media_kind == "image"
                                   else resolve(value, media_kind=body.media_kind) for value in body.references]}
        except (ValueError, OSError) as error:
            raise command_error(422, "invalid_reference", str(error)) from error

    return router
