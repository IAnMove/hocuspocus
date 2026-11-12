"""Versioned collection operations shared by HTTP/Wizard and external agents.

The registry owns atomic effects and receipts. This module only defines and
validates the wire contract; it does not schedule work or keep another journal.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError


Identity = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=240, pattern=r"^\S+$")]
IntentId = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=160)]
Name = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=160, pattern=r"\S")]
References = Annotated[list[Identity], Field(max_length=500, json_schema_extra={"uniqueItems": True})]


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class CollectionFields(StrictInput):
    name: Name
    description: Annotated[str, Field(max_length=2000)] = ""
    project_ids: References = Field(default_factory=list)
    asset_ids: References = Field(default_factory=list)
    production_ids: References = Field(default_factory=list)


class CollectionUpdate(StrictInput):
    workspace_id: Identity
    expected_revision: Annotated[int, Field(ge=1)]
    # Omitted fields preserve existing values. Explicit null is rejected below.
    name: Name | None = None
    description: Annotated[str, Field(max_length=2000)] | None = None
    project_ids: References | None = None
    asset_ids: References | None = None
    production_ids: References | None = None


class CollectionGet(StrictInput):
    workspace_id: Identity


class ReceiptGet(StrictInput):
    intent_id: IntentId


class Invocation(StrictInput):
    version: Literal[1]
    operation: str
    intent_id: IntentId | None = None
    input: dict[str, Any]


# Published entries are all executed by WorkspaceRegistry.execute_command.
OPERATIONS = {
    "collections.create": (CollectionFields, True, "Create a collection of exact references without moving source files."),
    "collections.update": (CollectionUpdate, True, "Update an exact collection and expected revision. Omitted fields are preserved."),
    "collections.get": (CollectionGet, False, "Read a collection by immutable ID, including revision and membership."),
    "collections.list": (StrictInput, False, "List logical collections; these are independent of physical output folders."),
    "commands.receipt": (ReceiptGet, False, "Recover a committed collection command by its exact intention ID, including after restart."),
}
MUTATIONS = frozenset(name for name, (_, mutation, _) in OPERATIONS.items() if mutation)


def catalog() -> dict[str, Any]:
    operations = []
    for name, (model, mutation, description) in OPERATIONS.items():
        schema = model.model_json_schema()
        # Updates have omission semantics, never nullable fields. Keep published
        # JSON Schema aligned with validation instead of advertising null.
        if name == "collections.update":
            for value in schema["properties"].values():
                if "anyOf" in value:
                    branches = [branch for branch in value.pop("anyOf") if branch.get("type") != "null"]
                    value.update(branches[0])
                    value.pop("default", None)
        properties = {"version": {"type": "integer", "const": 1},
                      "operation": {"type": "string", "const": name}, "input": schema}
        required = ["version", "operation", "input"]
        if mutation:
            properties["intent_id"] = {"type": "string", "minLength": 1, "maxLength": 160}
            required.append("intent_id")
        operations.append({"name": name, "description": description, "mutation": mutation,
                           "inputSchema": {"type": "object", "additionalProperties": False,
                                           "properties": properties, "required": required}})
    return {"version": 1, "scope": "installation", "operations": operations}


def installation_catalog() -> dict[str, Any]:
    """``catalog()`` plus the workspace folder tools (``workspace_folder_commands``): what an installation publishes."""
    from services.workspace_folder_commands import command_catalog

    published = catalog()
    return {**published, "operations": [*published["operations"], *command_catalog()]}


def _validate_collection_fields(data: dict[str, Any]) -> None:
    if any(item is None for item in data.values()):
        raise ValueError("Collection fields cannot be null; omit a field to preserve it")
    if "name" in data and not data["name"].strip():
        raise ValueError("Collection name cannot be blank")
    for field in ("project_ids", "asset_ids", "production_ids"):
        if field in data and len(set(data[field])) != len(data[field]):
            raise ValueError(f"{field} must contain unique canonical IDs")


def validate_command(value: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return original request and effective spec. Transport identity is not a digest."""
    try:
        if not isinstance(value, dict) or type(value.get("version")) is not int:
            raise ValueError("Command version must be the integer 1")
        request = Invocation.model_validate(value)
        if request.operation not in OPERATIONS:
            raise ValueError("Unknown command operation")
        model, mutation, _ = OPERATIONS[request.operation]
        if mutation and not request.intent_id:
            raise ValueError("Mutating commands require intent_id; keep it for transport retries")
        if not mutation and request.intent_id is not None:
            raise ValueError("Read commands do not accept an execution intent_id")
        parsed = model.model_validate(request.input)
        data = parsed.model_dump(exclude_unset=request.operation == "collections.update")
        _validate_collection_fields(data)
        effective = {"version": 1, "operation": request.operation, "input": data}
        return deepcopy(value), {**effective, "intent_id": request.intent_id}
    except ValidationError as exc:
        # Paths/types are useful feedback; never echo arbitrary submitted data.
        errors = [f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}" for item in exc.errors(include_input=False)]
        raise ValueError("; ".join(errors)) from exc


def resolve_catalog_reference(api, kind: str, identity: str):
    """Reuse the exact-ID read handlers mounted by the application."""
    from services.wangp_agent_adapters import _mounted_routes
    paths = {"asset_ids": "/api/v1/assets/{asset_id}", "project_ids": "/api/v1/projects/{project_id}",
             "production_ids": "/api/v1/productions/{production_id}"}
    route = next((route for route in _mounted_routes(api)
                  if getattr(route, "path", None) == paths[kind] and "GET" in getattr(route, "methods", set())), None)
    if route is None:
        raise ValueError(f"Reference resolver is unavailable for {kind}")
    return route.endpoint(identity)
