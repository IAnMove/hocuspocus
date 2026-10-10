"""Activity entries for what an external agent changed through MCP.

The MCP dispatcher calls :meth:`AgentActivity.record` after a mutating tool
succeeds. A tool that already runs as a canonical task (a generation, an
export) gets the agent attribution merged into that task. Any other change
(a saved scene, a personal Video 3D template, a kit, a series edit) becomes
one completed ``agent`` task per changed artifact, so the Activity panel can
list what the agent made and open each result in its editor.

Server jobs call the same tools in process (``LocalMcp``) without entering
an external caller scope, so they are not reported as agent work.
"""
from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any
from urllib.parse import unquote, urlparse

_LOGGER = logging.getLogger("loreframe.operations.agent_activity")

AGENT_TOOL = "external_agent"
WIZARD_TOOL = "wizard"
# Who a loopback HTTP call (an MCP tool that runs through the app's own routes) is made for.
ACTOR_HEADER = "x-hocus-actor"
ACTORS = ("user", "agent", "wizard", "server")
_CALLER: ContextVar[dict | None] = ContextVar("hocus_mcp_caller", default=None)

# Task controls and analysis runs change job state, not a user artifact.
_SKIPPED = frozenset({
    "jobs.resume", "jobs.discard", "audio.analyze", "audio.phonemes.setup", "wizard.workflow_answer",
    "production.cancel", "commands.receipt",
})
_SKIPPED_SUFFIXES = (".cancel", ".resume")
_FILE_SUFFIXES = (
    ".world3d.scene.json", ".scene.json", ".montage.json", ".comic.json", ".production.json", ".glb", ".gltf",
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".webm", ".mov", ".wav", ".mp3", ".flac", ".ogg", ".srt", ".vtt",
)
_FILE_KEYS = frozenset({"file", "name", "filename", "output", "output_name", "output_file", "glb", "path", "url", "audio", "image", "video"})
_TARGET_ORDER = ("world3d_template", "world3d_scene", "scene_file", "character_kit", "series_episode", "series",
                 "story", "montage", "template", "workspace_collection", "file")
_TASK_KEYS = ("task_id", "root_task_id")
_MAX_WALK_DEPTH = 5
_MAX_TARGETS = 24
_WORKSPACE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


@contextmanager
def caller_scope(caller: dict | None) -> Iterator[None]:
    """Mark the current request as coming from an MCP client (or from the server itself)."""
    token = _CALLER.set(dict(caller) if caller else None)
    try:
        yield
    finally:
        _CALLER.reset(token)


def current_caller() -> dict | None:
    caller = _CALLER.get()
    return dict(caller) if caller else None


def is_external_agent() -> bool:
    """True inside an MCP request from an outside client, False for server jobs and plain HTTP."""
    caller = _CALLER.get()
    return bool(caller) and not caller.get("internal")


def actor_label() -> str:
    """Who is changing a record right now: ``agent`` (MCP client), ``wizard`` (Ask to the Wizard) or ``user``."""
    caller = _CALLER.get() or {}
    if is_external_agent():
        return "agent"
    if caller.get("actor") in ("agent", "wizard"):
        return caller["actor"]
    return "wizard" if caller.get("surface") == "wizard" else "user"


def current_actor() -> str:
    """Like :func:`actor_label`, and ``server`` for the server's own jobs (a Series render approving its takes)."""
    caller = _CALLER.get() or {}
    if not is_external_agent() and (caller.get("actor") == "server" or caller.get("internal") == "server"):
        return "server"
    return actor_label()


@contextmanager
def loopback_agent_scope() -> Iterator[None]:
    """In a route an MCP tool reached through a loopback (``X-Hocus-Actor: agent``), act as that agent while the
    provenance of the files it makes is written (``requested_by``, ``external_agent``); elsewhere it does nothing.

    Activity is not involved: the MCP dispatcher already recorded the call."""
    caller = _CALLER.get() or {}
    if caller.get("actor") != "agent" or is_external_agent():
        yield
        return
    with caller_scope({"surface": "mcp", "tool": AGENT_TOOL}):
        yield


def loopback_actor() -> str | None:
    """The actor a loopback HTTP call carries in ``X-Hocus-Actor``: ``agent`` for an MCP client, ``wizard`` for Ask to
    the Wizard and ``server`` for the server's own jobs (a Series render approving its takes); None for anyone else."""
    caller = _CALLER.get()
    if not caller:
        return None
    if is_external_agent():
        return "agent"
    if caller.get("actor") in ("agent", "wizard", "server"):
        return caller["actor"]  # a route reached through a loopback passes its actor on
    if caller.get("surface") == "wizard":
        return "wizard"
    return "server" if caller.get("internal") == "server" else None


def _declared_actor(headers: list[tuple[bytes, bytes]]) -> str | None:
    values = {key.lower(): value for key, value in headers}
    declared = values.get(ACTOR_HEADER.encode(), b"").decode("latin-1").strip().lower()
    if declared in ACTORS and declared != "user":
        return declared
    surface = values.get(b"x-hocus-ui-surface", b"").decode("latin-1").strip().lower()
    return "wizard" if surface == "wizard" else None


class ActorHeaderMiddleware:
    """Carry the actor a request declares (``X-Hocus-Actor`` from a loopback, ``X-Hocus-UI-Surface: wizard`` from the
    Wizard) into the caller scope, so :func:`actor_label` and :func:`current_actor` name it in the route.

    Attribution only, never a permission. It never makes a request an external agent's: the MCP dispatcher records
    those itself (``is_external_agent`` stays False here)."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        actor = _declared_actor(scope.get("headers") or []) if scope.get("type") == "http" else None
        if actor is None:
            await self.app(scope, receive, send)
            return
        with caller_scope({"surface": "loopback", "internal": "loopback", "actor": actor}):
            await self.app(scope, receive, send)


def external_caller(profile: str | None = None) -> dict:
    """HTTP MCP clients are external; only server code can enter SERVER_CALLER."""
    caller = {"surface": "mcp", "tool": AGENT_TOOL}
    if profile:
        caller["profile"] = profile
    return caller


SERVER_CALLER = {"surface": "server", "internal": "server"}


def trusted_tool(*, default_external: bool = False) -> str | None:
    """The provenance tool for work submitted by the current caller.

    ``default_external`` keeps the historical label of the MCP-only generation
    handlers when no scope was set (a direct call); server jobs always enter
    :data:`SERVER_CALLER` first, so they are never reported as an agent.
    """
    if is_external_agent() or (default_external and _CALLER.get() is None):
        return AGENT_TOOL
    return None


def agent_attribution(capability: str, command_id: str | None = None) -> dict:
    """Task metadata naming the agent call that admitted a job, or {} for anyone else."""
    if not is_external_agent():
        return {}
    caller = current_caller() or {}
    attribution = {"tool": AGENT_TOOL, "capability": capability, "command_id": command_id, "mcp_profile": caller.get("profile")}
    return {key: value for key, value in attribution.items() if value}


def requested_by(metadata: Any) -> dict:
    """Sidecar fields for an output whose task an agent requested, so the file itself says so."""
    if not isinstance(metadata, dict) or metadata.get("tool") != AGENT_TOOL:
        return {}
    request = {key: metadata[key] for key in ("tool", "capability", "command_id", "mcp_profile") if metadata.get(key)}
    fields: dict[str, Any] = {"requested_by": request}
    if metadata.get("command_id"):
        fields["command_id"] = metadata["command_id"]
    return fields


def recorded(name: str) -> bool:
    return name not in _SKIPPED and not name.endswith(_SKIPPED_SUFFIXES)


def _input(arguments: Any) -> dict:
    if not isinstance(arguments, dict):
        return {}
    for key in ("input", "params"):
        if isinstance(arguments.get(key), dict):
            return arguments[key]
    return arguments


def _intent(arguments: Any) -> str:
    if not isinstance(arguments, dict):
        return ""
    for key in ("intent_id", "request_id"):
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:160]
    return ""


def _file_name(value: Any) -> str:
    """A workspace file named by a value, or '' (only workspace-relative names and /api/v1/file URLs)."""
    if not isinstance(value, str) or not value or len(value) > 600:
        return ""
    text = value
    if text.startswith("/api/v1/file/"):
        text = unquote(urlparse(text).path[len("/api/v1/file/"):])
    elif "://" in text or text.startswith("/"):
        return ""
    if not text.lower().endswith(_FILE_SUFFIXES) or ".." in text.split("/"):
        return ""
    return text


def _target(kind: str, identity: Any, **extra: Any) -> dict | None:
    if not isinstance(identity, str) or not identity.strip():
        return None
    target = {"kind": kind, "id": identity.strip()[:300]}
    for key, value in extra.items():
        if isinstance(value, str) and value.strip():
            target[key] = value.strip()[:300]
    return target


def _scene_target(value: dict) -> dict | None:
    scene_id = value.get("sceneId")
    if isinstance(scene_id, str) and scene_id.startswith("w3d-"):
        return _target("world3d_scene", scene_id, title=value.get("templateId"))
    return None


def _document_target(value: dict) -> dict | None:
    file_name = _file_name(value.get("file")) or _file_name(value.get("name"))
    if file_name.endswith(".scene.json") and isinstance(value.get("editor"), str):
        return _target("scene_file", file_name, file=file_name, editor=value["editor"])
    return None


def _montage_target(value: dict) -> dict | None:
    """A saved montage (``<name>.montage.json``) opens in the Video Editor; its document's name is the title."""
    file_name = _file_name(value.get("file"))
    if not file_name.endswith(".montage.json"):
        return None
    montage = value.get("montage") if isinstance(value.get("montage"), dict) else {}
    return _target("montage", file_name, file=file_name, title=montage.get("name"))


def _template_target(value: dict, _data: dict) -> dict | None:
    if str(value.get("id") or "").startswith("user-") and value.get("source") == "workspace":
        return _target("world3d_template", value.get("id"), title=value.get("title"))
    return _target("template", value.get("id"), title=value.get("title"))


def _episode_target(value: dict, data: dict) -> dict | None:
    if not data.get("series_id"):
        return None
    return _target("series_episode", value.get("id"), series=data.get("series_id"), title=value.get("title"))


# Result keys that name one artifact, and how to read it.
_KEYED_TARGETS = {
    "template": _template_target,
    "character": lambda value, _data: _target("character_kit", value.get("id"), title=value.get("name")),
    "series": lambda value, _data: _target("series", value.get("id"), title=value.get("title")),
    "episode": _episode_target,
}


def _dict_targets(key: str, value: dict, data: dict) -> list[dict | None]:
    keyed = _KEYED_TARGETS.get(key)
    return [_scene_target(value), _document_target(value), _montage_target(value), keyed(value, data) if keyed else None]


def _entity_targets(entities: Any) -> list[dict | None]:
    kinds = {"workspace_collection": "workspace_collection", "series": "series", "character_kit": "character_kit"}
    return [_target(kinds[item["kind"]], item.get("id")) for item in entities or []
            if isinstance(item, dict) and item.get("kind") in kinds]


def _walk(value: Any, data: dict, found: list, depth: int = 0, key: str = "") -> None:
    if depth > _MAX_WALK_DEPTH or len(found) > _MAX_TARGETS * 2:
        return
    if isinstance(value, dict):
        found.extend(_dict_targets(key, value, data))
        if key == "" or "entities" in value:
            found.extend(_entity_targets(value.get("entities")))
        for child_key, child in value.items():
            if child_key in ("document", "images", "frames", "objects", "traits", "pending"):
                continue
            if child_key in _FILE_KEYS and (name := _file_name(child)):
                found.append(_target("file", name, file=name))
            _walk(child, data, found, depth + 1, child_key)
    elif isinstance(value, list):
        for item in value[:64]:
            _walk(item, data, found, depth + 1, key)


def _input_targets(data: dict) -> list[dict | None]:
    found: list[dict | None] = []
    series_id, episode_id = data.get("series_id"), data.get("episode_id")
    if isinstance(series_id, str) and isinstance(episode_id, str):
        found.append(_target("series_episode", episode_id, series=series_id))
    elif isinstance(series_id, str):
        found.append(_target("series", series_id))
    for key in ("kit_id", "character_id"):
        found.append(_target("character_kit", data.get(key)))
    scene_id = data.get("scene_id")
    if isinstance(scene_id, str) and scene_id.startswith("w3d-"):
        found.append(_target("world3d_scene", scene_id))
    return found


def artifact_targets(arguments: Any, result: Any) -> list[dict]:
    """Every artifact a tool result names, most specific first, without duplicates."""
    data = _input(arguments)
    found: list[dict | None] = []
    _walk(result, data, found)
    found.extend(_input_targets(data))
    return _merge_targets([], [target for target in found if target])


def _merge_targets(previous: list, current: list[dict]) -> list[dict]:
    """Earlier calls' targets plus this call's; a later call never erases a title an earlier one gave."""
    merged: dict[tuple[str, str], dict] = {}
    for item in [*previous, *current]:
        if isinstance(item, dict) and item.get("kind") in _TARGET_ORDER and item.get("id"):
            key = (item["kind"], item["id"])
            merged[key] = {**merged.get(key, {}), **item}
    # A file another target already opens (a scene document, a montage) is not listed a second time as a plain file.
    opened = {item["file"] for item in merged.values() if item["kind"] != "file" and item.get("file")}
    kept = [item for item in merged.values() if not (item["kind"] == "file" and item.get("file") in opened)]
    return sorted(kept, key=lambda item: _TARGET_ORDER.index(item["kind"]))[:_MAX_TARGETS]


def linked_task_ids(result: Any, depth: int = 0) -> list[str]:
    """Canonical task ids a tool result already reports (generation and export receipts)."""
    ids: list[str] = []
    if depth > _MAX_WALK_DEPTH:
        return ids
    if isinstance(result, dict):
        ids.extend(_task_ids_here(result))
        for child in result.values():
            ids.extend(linked_task_ids(child, depth + 1))
    elif isinstance(result, list):
        for item in result[:32]:
            ids.extend(linked_task_ids(item, depth + 1))
    return list(dict.fromkeys(ids))


def _task_ids_here(result: dict) -> list[str]:
    ids = [result[key] for key in _TASK_KEYS if isinstance(result.get(key), str) and result[key]]
    if isinstance(result.get("job_id"), str) and result["job_id"]:
        # Legacy generate/recast/upscale answers with the queue job id only.
        ids.append(f"task-generation-{result['job_id']}")
    ids.extend(item for item in result.get("taskIds") or [] if isinstance(item, str) and item)
    return ids


def _workspace(data: dict, default_workspace: Callable[[], str]) -> str:
    workspace = data.get("workspace")
    if isinstance(workspace, str) and _WORKSPACE_RE.fullmatch(workspace):
        return workspace
    return default_workspace()


def _failed(result: Any) -> bool:
    if not isinstance(result, dict):
        return False
    status = result.get("status")
    return bool(result.get("error")) or result.get("_is_error") is True or (isinstance(status, str) and status.lower() == "failed")


def _replayed(result: Any) -> bool:
    """A transport retry answered from the intent journal: the change was already recorded once."""
    if not isinstance(result, dict):
        return False
    inner = result.get("result")
    return result.get("replayed") is True or (isinstance(inner, dict) and inner.get("replayed") is True)


class AgentActivity:
    """Publish agent mutations into the workspace task registry the Activity panel reads."""

    def __init__(self, registry_for: Callable[[str], Any], default_workspace: Callable[[], str]) -> None:
        self._registry_for = registry_for
        self._default_workspace = default_workspace

    def record(self, name: str, arguments: Any, result: Any) -> None:
        """Never raises: attribution must not turn a successful tool call into an error."""
        if not is_external_agent() or not recorded(name) or _failed(result) or _replayed(result):
            return
        try:
            self._record(name, arguments, result)
        except Exception as error:  # noqa: BLE001 - attribution is best effort
            _LOGGER.warning("Could not record agent activity for %s: %s", name, error)

    def _record(self, name: str, arguments: Any, result: Any) -> None:
        data = _input(arguments)
        workspace = _workspace(data, self._default_workspace)
        registry = self._registry_for(workspace)
        caller = current_caller() or {}
        intent = _intent(arguments)
        attribution = {"tool": AGENT_TOOL, "capability": name, "command_id": intent or None,
                       "mcp_profile": caller.get("profile")}
        linked = [task_id for task_id in linked_task_ids(result) if registry.get(task_id) is not None]
        for task_id in linked:
            self._attribute(registry, task_id, attribution)
        if linked:
            return
        self._publish(registry, workspace, name, intent, attribution, artifact_targets(arguments, result))

    @staticmethod
    def _attribute(registry, task_id: str, attribution: dict) -> None:
        task = registry.get(task_id) or {}
        metadata = dict(task.get("metadata") or {})
        if metadata.get("tool") == AGENT_TOOL and metadata.get("capability"):
            return
        metadata.update({key: value for key, value in attribution.items() if value is not None})
        registry.update(task_id, metadata=metadata, event_type="agent.attributed", force=True)

    def record_wizard(self, workspace: str, capability: str, targets: Any, command_id: str | None = None) -> dict | None:
        """The trail row of an Ask to the Wizard change that started no job (a kit, a series, a story).

        The browser runs the Wizard, so it reports the change with what it changed (``targets``); the row works like
        an agent's: one per artifact, later changes of the same artifact update it, and its buttons open each result.
        Returns the task, or None when no target can be opened."""
        clean = _merge_targets([], [target for target in (_client_target(item) for item in targets or [])
                                    if target][:_MAX_TARGETS])
        name = str(capability or "").strip()[:120]
        if not clean or not name:
            return None
        if not _WORKSPACE_RE.fullmatch(workspace or ""):
            raise ValueError("Use a valid workspace")
        intent = str(command_id or "").strip()[:160]
        attribution = {"tool": WIZARD_TOOL, "capability": name, "command_id": intent or None}
        return self._publish(self._registry_for(workspace), workspace, name, intent, attribution, clean, actor="wizard")

    @staticmethod
    def _publish(registry, workspace: str, name: str, intent: str, attribution: dict, targets: list[dict],
                 actor: str = "agent") -> dict:
        """One completed ``agent`` task per artifact and actor; later calls on the same artifact update it."""
        key = f"{targets[0]['kind']}:{targets[0]['id']}" if targets else f"intent:{intent or name}"
        # An agent's rows keep their historical ids; the Wizard's are its own rows for the same artifact.
        identity = key if actor == "agent" else f"{actor}:{key}"
        task_id = f"task-{actor}-" + hashlib.sha1(identity.encode("utf-8")).hexdigest()[:20]
        existing = registry.get(task_id)
        fields = _change_fields(name, key, attribution, targets, (existing or {}).get("metadata") or {}, actor)
        if existing is None:
            return registry.create(id=task_id, workspace=workspace, **fields)
        return registry.update(task_id, event_type="agent.changed", force=True, **fields)


def _client_target(value: Any) -> dict | None:
    """A target the browser reports for a Wizard change, checked like the ones read from a tool result."""
    if not isinstance(value, dict) or value.get("kind") not in _TARGET_ORDER:
        return None
    file_name = _file_name(value.get("file")) if value.get("file") is not None else ""
    if value.get("file") is not None and not file_name:
        return None
    extra = {key: value.get(key) for key in ("title", "editor", "series")}
    return _target(value["kind"], value.get("id"), **extra, **({"file": file_name} if file_name else {}))


_ACTOR_TITLES = {"agent": "Agent", "wizard": "Wizard"}


def _change_fields(name: str, key: str, attribution: dict, targets: list[dict], previous: dict, actor: str = "agent") -> dict:
    """The task fields of one agent change, merged with what earlier calls on the same artifact recorded."""
    operations = dict(previous.get("operations") or {})
    operations[name] = int(operations.get(name) or 0) + 1
    all_targets = _merge_targets(previous.get("targets") or [], targets)
    refs = list(dict.fromkeys(item["file"] for item in all_targets if item.get("file")))[:_MAX_TARGETS]
    primary = next((item for item in all_targets if f"{item['kind']}:{item['id']}" == key), {})
    metadata = {"adapter": "agent", "actor": actor, **{field: value for field, value in attribution.items() if value is not None},
                "operations": operations, "targets": all_targets, "expects_artifact": bool(refs)}
    message = " · ".join(f"{operation} ×{count}" if count > 1 else operation for operation, count in operations.items())
    label = _ACTOR_TITLES.get(actor, "Agent")
    return {"kind": "agent", "workflow": name, "title": f"{label} · {primary.get('title') or primary.get('id') or name}"[:500],
            "status": "completed", "phase": "completed", "message": message[:2000], "progress": 1.0,
            "result_refs": refs, "metadata": metadata}
