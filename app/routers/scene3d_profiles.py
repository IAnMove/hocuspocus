"""Workspace-scoped, content-addressed face calibration. No audio or model bytes."""
from __future__ import annotations
import hashlib
import json
import os
import re
import threading
import uuid
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from services.character_speech_definition import face_settings

_lock = threading.Lock()
MAX_MODEL_BYTES = 64 * 1024 * 1024
_WORKSPACE = re.compile(r"^[A-Za-z0-9_. -]{1,120}$")
_DIGEST = re.compile(r"^[a-f0-9]{64}$")

class ProfileWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_. -]+$")
    revision: int = Field(ge=0)
    settings: dict

    @field_validator("workspace")
    @classmethod
    def workspace_name(cls, value):
        if value in {".", ".."}:
            raise ValueError("Invalid workspace.")
        return value

    @field_validator("settings")
    @classmethod
    def face_only(cls, value):
        return face_settings(value)

def _contained(path: str, root: str) -> bool:
    try:
        return os.path.normcase(os.path.commonpath((path, root))) == os.path.normcase(root)
    except (TypeError, ValueError, OSError):
        return False


def stored_glb_digest(workspace_dir, workspace: str, filename: str) -> tuple[str, int]:
    if not _WORKSPACE.fullmatch(workspace) or workspace in {".", ".."}:
        raise HTTPException(400, "Invalid profile scope.")
    if not isinstance(filename, str) or not filename or filename != os.path.basename(filename) or "/" in filename or "\\" in filename:
        raise HTTPException(400, "Invalid model filename.")
    if not filename.lower().endswith(".glb"):
        raise HTTPException(400, "Only GLB models have a face calibration identity.")
    root = os.path.realpath(os.path.abspath(workspace_dir(workspace)))
    path = os.path.realpath(os.path.abspath(os.path.join(root, filename)))
    if path == root or not _contained(path, root):
        raise HTTPException(400, "Invalid model filename.")
    if not os.path.isfile(path):
        raise HTTPException(404, "Model file was not found in this workspace.")
    size = os.path.getsize(path)
    if size > MAX_MODEL_BYTES:
        raise HTTPException(413, "Model exceeds 64 MB.")
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest(), size


def create_scene3d_profiles_router(workspace_dir):
    router = APIRouter()

    def target(workspace: str, digest: str):
        if not _DIGEST.fullmatch(digest) or not _WORKSPACE.fullmatch(workspace) or workspace in {".", ".."}:
            raise HTTPException(400, "Invalid profile scope.")
        return Path(workspace_dir(workspace)).resolve() / ".speech3d-profiles" / (digest + ".json")

    def read(path):
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

    @router.get("/speech/digest")
    def digest_model(workspace: str, filename: str):
        digest, size = stored_glb_digest(workspace_dir, workspace, filename)
        return {"digest": digest, "bytes": size}

    @router.get("/speech/profiles/{digest}")
    def get_profile(digest: str, workspace: str):
        with _lock:
            profile = read(target(workspace, digest))
        if profile is None:
            raise HTTPException(404, "No saved calibration for this model.")
        return profile

    @router.put("/speech/profiles/{digest}")
    def put_profile(digest: str, payload: ProfileWrite):
        path = target(payload.workspace, digest)
        with _lock:
            current = read(path)
            revision = current["revision"] if current else 0
            if revision != payload.revision:
                raise HTTPException(409, "Calibration changed elsewhere; reload before saving.")
            result = {"version": 1, "digest": digest, "revision": revision + 1, "settings": payload.settings}
            path.parent.mkdir(parents=True, exist_ok=True)
            # Preserve earlier revisions; never delete a user calibration.
            if current:
                history = path.with_name(digest + ".v" + str(revision) + ".json")
                if not history.exists():
                    history.write_text(json.dumps(current, allow_nan=False), encoding="utf-8")
            temp = path.with_name(digest + "." + uuid.uuid4().hex + ".tmp")
            temp.write_text(json.dumps(result, allow_nan=False), encoding="utf-8")
            os.replace(temp, path)
        return result
    return router
