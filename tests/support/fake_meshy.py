"""A fake Meshy for tests: it stands in for ``requests.get/post/delete`` and never touches the network.

Every task it creates succeeds on its first poll unless a test scripts something else:
``fake.script[kind]`` is a list of GET payloads (the last one repeats), ``fake.errors[key]`` is a
list of responses returned before the real answer, where ``key`` is ``"POST <path>"``.
"""
from __future__ import annotations

import json
import struct
from typing import Any

BASE = "https://api.meshy.ai/openapi"
ASSETS = "https://assets.meshy.ai"


def glb(clips: tuple[tuple[str, float], ...] = (), *, extensions: tuple[str, ...] = ()) -> bytes:
    """A small valid GLB with one node and one translation clip per ``(name, seconds)``."""
    buffer = struct.pack("<2f", 0.0, 1.0) + struct.pack("<6f", 0, 0, 0, 0, 1, 0)
    document: dict[str, Any] = {
        "asset": {"version": "2.0"},
        "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"name": "Hips"}],
        "buffers": [{"byteLength": len(buffer)}],
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": 8}, {"buffer": 0, "byteOffset": 8, "byteLength": 24}],
    }
    if extensions:
        document["extensionsUsed"] = list(extensions)
        document["extensionsRequired"] = list(extensions)
    if clips:
        document["accessors"] = [
            {"bufferView": 0, "componentType": 5126, "count": 2, "type": "SCALAR", "min": [0.0], "max": [1.0]},
            {"bufferView": 1, "componentType": 5126, "count": 2, "type": "VEC3"},
        ]
        document["animations"] = [
            {"name": name, "samplers": [{"input": 0, "output": 1, "interpolation": "LINEAR"}],
             "channels": [{"sampler": 0, "target": {"node": 0, "path": "translation"}}]}
            for name, _seconds in clips
        ]
    text = json.dumps(document).encode()
    text += b" " * (-len(text) % 4)
    buffer += b" " * (-len(buffer) % 4)
    body = struct.pack("<II", len(text), 0x4E4F534A) + text + struct.pack("<II", len(buffer), 0x004E4942) + buffer
    return struct.pack("<4sII", b"glTF", 2, 12 + len(body)) + body


class Response:
    def __init__(self, payload: Any = None, *, status: int = 200, content: bytes | None = None, headers: dict | None = None):
        self.status_code = status
        self.ok = status < 400
        self._payload = payload
        self.content = content if content is not None else (json.dumps(payload).encode() if payload is not None else b"")
        self.headers = headers or {}
        self.text = self.content.decode("utf-8", "ignore") if content is None else ""

    def json(self) -> Any:
        if self._payload is None:
            raise ValueError("no json")
        return self._payload

    def raise_for_status(self) -> None:
        if not self.ok:
            raise RuntimeError(f"HTTP {self.status_code}")


def error(status: int, message: str, **headers: str) -> Response:
    return Response({"message": message}, status=status, headers=headers)


class FakeMeshy:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []
        self.created: list[tuple[str, str, dict]] = []     # (kind, task id, request body)
        self.deleted: list[str] = []
        self.script: dict[str, list[dict]] = {}
        self.errors: dict[str, list[Response]] = {}
        self.files: dict[str, bytes] = {}
        self.library: list[dict] = []
        self.delete_status = 204
        self.on_poll = None          # called with the task id on every status read
        self._counter = 0

    def install(self, monkeypatch) -> "FakeMeshy":
        import requests
        monkeypatch.setattr(requests, "get", self.get)
        monkeypatch.setattr(requests, "post", self.post)
        monkeypatch.setattr(requests, "delete", self.delete)
        return self

    # -- helpers -------------------------------------------------------------------------------
    def posts(self, kind: str | None = None) -> list[dict]:
        return [body for made, _id, body in self.created if kind in (None, made)]

    def made(self, kind: str) -> list[str]:
        return [task for made, task, _body in self.created if made == kind]

    def _kind(self, path: str, body: dict) -> str:
        if path.endswith("/v1/image-to-3d"):
            return "image"
        if path.endswith("/v2/text-to-3d"):
            return body.get("mode", "preview")
        return "rig" if path.endswith("/v1/rigging") else "anim"

    def _task(self, kind: str, task: str, index: int) -> dict:
        scripted = self.script.get(kind)
        if scripted:
            return scripted[min(index, len(scripted) - 1)]
        return self._done(kind, task)

    def _done(self, kind: str, task: str) -> dict:
        base = {"id": task, "status": "SUCCEEDED", "progress": 100, "consumed_credits": {
            "image": 30, "preview": 20, "refine": 10, "rig": 5, "anim": 6}[kind]}
        if kind in ("image", "refine", "preview"):
            urls = {"model_urls": {"glb": f"{ASSETS}/{task}.glb"}, "thumbnail_url": f"{ASSETS}/{task}.png?Expires=1"}
            self.files.setdefault(f"{ASSETS}/{task}.glb", glb())
            self.files.setdefault(f"{ASSETS}/{task}.png?Expires=1", b"\x89PNG\r\n\x1a\nthumb")
            # Meshy documents expires_at for image-to-3D, not for text-to-3D.
            return {**base, **urls, **({"expires_at": 1_900_000_000_000} if kind == "image" else {})}
        if kind == "rig":
            result = {
                "rigged_character_glb_url": f"{ASSETS}/{task}-rig.glb",
                "basic_animations": {"walking_glb_url": f"{ASSETS}/{task}-walk.glb", "running_glb_url": f"{ASSETS}/{task}-run.glb"},
            }
            self.files.setdefault(f"{ASSETS}/{task}-rig.glb", glb())
            self.files.setdefault(f"{ASSETS}/{task}-walk.glb", glb((("Walking", 1.0),)))
            self.files.setdefault(f"{ASSETS}/{task}-run.glb", glb((("Running", 1.0),)))
            return {**base, "result": result, "expires_at": 1_900_000_000_000}
        sent = next((body for made, _id, body in self.created if made == "anim"), {})
        names = [f"Action {action}" for action in sent.get("action_ids", [])]
        base["consumed_credits"] = 3 * len(names)   # 3 credits per animation
        self.files.setdefault(f"{ASSETS}/{task}-anim.glb", glb(tuple((name, 1.0) for name in names)))
        return {**base, "result": {"animation_glb_url": f"{ASSETS}/{task}-anim.glb"}, "expires_at": 1_800_000_000_000}

    # -- requests API --------------------------------------------------------------------------
    def _scripted_error(self, key: str) -> Response | None:
        queued = self.errors.get(key)
        return queued.pop(0) if queued else None

    def post(self, url: str, headers=None, json=None, timeout=None, **_kw) -> Response:
        path = url.removeprefix(BASE)
        self.calls.append(("POST", path, json))
        failed = self._scripted_error(f"POST {path}")
        if failed:
            return failed
        kind = self._kind(path, json or {})
        self._counter += 1
        task = f"{kind}-{self._counter}"
        self.created.append((kind, task, dict(json or {})))
        return Response({"result": task})

    def get(self, url: str, headers=None, timeout=None, **_kw) -> Response:
        if not url.startswith(BASE):
            self.calls.append(("DOWNLOAD", url, None))
            data = self.files.get(url)
            return Response(content=data) if data is not None else error(403, "expired")
        path = url.removeprefix(BASE)
        self.calls.append(("GET", path, None))
        failed = self._scripted_error(f"GET {path.split('?')[0]}")
        if failed:
            return failed
        if path.startswith("/v1/animations/library"):
            return Response(self.library)
        task = path.rsplit("/", 1)[-1]
        kind = next((made for made, made_id, _b in self.created if made_id == task), None)
        if kind is None:
            return error(404, "Task not found")
        seen = sum(1 for call in self.calls if call[0] == "GET" and call[1].endswith(f"/{task}"))
        if self.on_poll:
            self.on_poll(task)
        return Response(self._task(kind, task, seen - 1))

    def delete(self, url: str, headers=None, timeout=None, **_kw) -> Response:
        path = url.removeprefix(BASE)
        self.calls.append(("DELETE", path, None))
        self.deleted.append(path)
        return Response({}, status=self.delete_status)
