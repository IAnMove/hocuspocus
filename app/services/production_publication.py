"""Publish a completed production through the app, with an isolated page.

Each publication is remembered beside the production (``<id>.publications.json``: page, video, mode, when and who
published it), so the production's card links its published page (:func:`latest_publication`)."""
from __future__ import annotations

import asyncio
import hashlib
import html
import json
import logging
import os
import re
import shutil
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import quote, urlsplit

from services.publication_server import serve_publication

OPERATION = "production.publish"
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}\Z")
_WORKSPACE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,119}\Z")
_EXTENSIONS = {".mp4", ".webm", ".png", ".jpg", ".jpeg", ".wav", ".mp3", ".flac", ".m4a", ".glb", ".json"}
_lock = threading.Lock()
_LOGGER = logging.getLogger("loreframe.production.publication")


def publication_catalog() -> list[dict]:
    return [{"name": OPERATION, "version": 1, "domain": "production", "mutation": True,
             "description": "Publish a reviewed production, or use mode preview to share a clearly labelled review copy without changing human approvals. Creates its own HTML page; never edits index.html. Optional app-owned LAN serving.",
             "inputSchema": {"type": "object", "additionalProperties": False, "required": ["version", "input"],
                             "properties": {"version": {"const": 1, "type": "integer"}, "input": {
                                 "type": "object", "additionalProperties": False, "required": ["workspace", "production_id"],
                                 "properties": {"workspace": {"type": "string", "pattern": _WORKSPACE.pattern.replace("\\Z", "$")},
                                                "production_id": {"type": "string", "pattern": _ID.pattern.replace("\\Z", "$")},
                                                "slug": {"type": "string", "pattern": _ID.pattern.replace("\\Z", "$")},
                                                "mode": {"enum": ["release", "preview"], "description": "Default release requires approved shots. Preview labels the page as unapproved and leaves review decisions unchanged."},
                                                "extras": {"type": "array", "maxItems": 24, "items": {"type": "string"}}}}}}}]


def _input(arguments):
    if not isinstance(arguments, dict) or set(arguments) != {"version", "input"} or type(arguments["version"]) is not int or arguments["version"] != 1:
        raise ValueError("Use version 1 with an input object")
    data = arguments["input"]
    if not isinstance(data, dict) or set(data) - {"workspace", "production_id", "slug", "extras", "mode"}:
        raise ValueError("Unsupported publication fields")
    if "mode" in data and data["mode"] not in ("release", "preview"):
        raise ValueError("mode must be release or preview")
    for name, pattern in (("workspace", _WORKSPACE), ("production_id", _ID), ("slug", _ID)):
        value = data.get(name, data.get("production_id") if name == "slug" else None)
        if not isinstance(value, str) or not pattern.fullmatch(value):
            raise ValueError(f"Invalid {name}")
    extras = data.get("extras", [])
    if not isinstance(extras, list) or len(extras) > 24:
        raise ValueError("extras must contain at most 24 workspace filenames")
    return {**data, "slug": data.get("slug", data["production_id"]), "extras": extras}


def _source(root: Path, name, extensions=_EXTENSIONS) -> Path:
    if not isinstance(name, str) or not name or Path(name).name != name or "\\" in name or name.startswith("."):
        raise ValueError("Use a workspace artifact basename")
    path = root / name
    if path.is_symlink() or path.resolve().parent != root or not path.is_file():
        raise ValueError("Artifact must be a regular file inside this workspace")
    if path.suffix.lower() not in extensions:
        raise ValueError("Unsupported publication artifact")
    return path


def _digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def _sources(root, state, extras):
    video = _source(root, state.get("final"))
    if video.suffix != ".mp4":
        raise ValueError("The completed production must have an MP4")
    files = {"video.mp4": video}
    for name, value in (("contact", state.get("contact_sheet")), ("song", (state.get("song") or {}).get("file"))):
        if value:
            path = _source(root, value)
            files[name + path.suffix] = path
    for value in extras:
        path = _source(root, value)
        if path.name in files or path.name == "publication.json":
            raise ValueError("Extra artifact collides with a publication filename")
        files[path.name] = path
    return files


def _page(title: str, files: dict, *, preview: bool = False, language: str = "") -> str:
    """The page chrome is English; the title carries the production's own language when it is known."""
    title = html.escape(title)
    lang = f' lang="{html.escape(language)}"' if language else ""
    links = "".join(f'<li><a href="{quote(name)}" download>{html.escape(name)}</a></li>' for name in files)
    contact = next((name for name in files if name.startswith("contact.")), None)
    image = f'<img src="{quote(contact)}" alt="Video contact sheet" loading="lazy">' if contact else ""
    notice = '<p role="status"><strong>Review preview · Not approved for release</strong></p>' if preview else ""
    return f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title{lang}>{title}</title><style>body{{margin:0;background:#111d2b;color:#f5e9ce;font:18px system-ui,sans-serif}}main{{max-width:1100px;margin:auto;padding:36px 20px}}h1{{font-size:clamp(32px,6vw,64px);color:#65d4ba}}video,img{{display:block;width:100%;border-radius:14px;background:#000;margin:24px 0}}a{{color:#ffcc73}}li{{margin:10px 0;overflow-wrap:anywhere}}footer{{margin:40px 0;font-size:15px;color:#b6c4cf}}</style>
<main>{notice}<p>Original music · Original 3D models · A couch-night tribute</p><h1{lang}>{title}</h1>
<video controls playsinline preload="metadata" aria-label="{title}"><source src="video.mp4" type="video/mp4"></video>
{image}<h2>Downloads</h2><ul>{links}</ul><footer>Fan-made homage, not affiliated with Nintendo</footer></main></html>'''


def publish_production(data: dict, workspace_dir) -> dict:
    configured = os.environ.get("HOCUS_PUBLICATION_ROOT", "")
    base = os.environ.get("HOCUS_PUBLICATION_BASE_URL", "").rstrip("/")
    url = urlsplit(base)
    if not configured or url.scheme not in {"http", "https"} or not url.hostname or url.query or url.fragment:
        raise ValueError("Configure HOCUS_PUBLICATION_ROOT and HOCUS_PUBLICATION_BASE_URL on this instance")
    root = Path(workspace_dir(data["workspace"])).resolve()
    state_path = _source(root, data["production_id"] + ".production.json")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if state.get("status") != "completed":
        raise ValueError("Only a completed production can be published")
    from services.production_shot_review import assert_publishable
    preview = data.get("mode") == "preview"
    if not preview:
        assert_publishable(root, data["production_id"], state)
    files = _sources(root, state, data["extras"])
    hashes = {name: _digest(path) for name, path in files.items()}
    spec = state.get("spec") or {}
    title = str(spec.get("title") or data["production_id"])
    from services.production_song import song_language
    page_content = _page(title, files, preview=preview, language=song_language(spec.get("song")))
    page_digest = hashlib.sha256(page_content.encode()).hexdigest()
    identity = hashlib.sha256(json.dumps({"workspace": data["workspace"], "production": data["production_id"], "slug": data["slug"], "files": hashes, "page": page_digest}, sort_keys=True).encode()).hexdigest()[:16]
    destination_root = Path(configured).resolve()
    destination_root.mkdir(parents=True, exist_ok=True)
    directory = data["slug"] + "-" + identity
    destination = destination_root / directory
    page = data["slug"] + ".html"
    manifest = {"version": 1, "workspace": data["workspace"], "production_id": data["production_id"], "files": hashes, "page": page, "page_sha256": page_digest}
    if preview:
        manifest["mode"] = "preview"
    with _lock:
        if destination.is_symlink():
            raise ValueError("Publication destination is a symlink")
        if destination.exists():
            if json.loads(_source(destination, "publication.json").read_text()) != manifest:
                raise ValueError("Publication destination is owned by another publication")
            for name, digest in hashes.items():
                if _digest(_source(destination, name)) != digest:
                    raise ValueError("Published artifact changed; destination is not overwritten")
            if _digest(_source(destination, page, {".html"})) != page_digest:
                raise ValueError("Published page changed; destination is not overwritten")
        else:
            staging = Path(tempfile.mkdtemp(prefix=".publication-", dir=destination_root))
            try:
                for name, source in files.items():
                    shutil.copyfile(source, staging / name)
                    if _digest(staging / name) != hashes[name]:
                        raise ValueError("Artifact changed while publishing; retry")
                (staging / page).write_text(page_content, encoding="utf-8")
                (staging / "publication.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
                staging.rename(destination)
            finally:
                if staging.exists():
                    shutil.rmtree(staging)
    if os.environ.get("HOCUS_PUBLICATION_SERVE") == "1":
        serve_publication(destination_root, os.environ.get("HOCUS_PUBLICATION_BIND", "127.0.0.1"), url.port or 80)
    prefix = base + "/" + directory + "/"
    result = {"page": prefix + page, "video": prefix + "video.mp4", "files": {name: prefix + quote(name) for name in files},
              "publication_id": identity, "mode": "preview" if preview else "release"}
    try:
        record_publication(root, data["production_id"], result)
    except OSError as error:  # the page is published; only the card's link to it is missing
        _LOGGER.warning("Could not record the publication of %s: %s", data["production_id"], error)
    return result


def publications_path(root, production_id: str) -> Path:
    return Path(root) / f"{production_id}.publications.json"


def _publications(root, production_id: str) -> list[dict]:
    try:
        body = json.loads(publications_path(root, production_id).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return []
    rows = body.get("publications") if isinstance(body, dict) else None
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def record_publication(root, production_id: str, result: dict, *, now: float | None = None) -> dict:
    """Remember a publication beside its production; publishing the same page again updates its time."""
    from services.agent_activity import actor_label
    moment = round(now if now is not None else time.time(), 3)
    row = {"publication_id": result["publication_id"], "page": result["page"], "video": result["video"],
           "mode": result["mode"], "published_at": moment, "published_by": actor_label()}
    with _lock:
        rows, kept = _publications(root, production_id), []
        for item in rows:
            if item.get("publication_id") == row["publication_id"]:
                row["first_published_at"] = item.get("first_published_at") or item.get("published_at")
            else:
                kept.append(item)
        rows = [*kept, row][-50:]
        path = publications_path(root, production_id)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps({"version": 1, "production_id": production_id, "publications": rows}, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)
    return row


def latest_publication(root, production_id: str) -> dict | None:
    """The newest publication of a production with its page link, or None when it was never published."""
    rows = _publications(root, production_id)
    if not rows:
        return None
    latest = max(rows, key=lambda item: float(item.get("published_at") or 0))
    page = latest.get("page")
    if not isinstance(page, str) or urlsplit(page).scheme not in {"http", "https"}:
        return None
    return {"page": page, "mode": latest.get("mode") or "release", "published_at": latest.get("published_at"),
            "published_by": latest.get("published_by") or "user", "count": len(rows)}


def publication_handlers(workspace_dir) -> dict:
    from fastapi import HTTPException

    async def publish(arguments):
        try:
            result = await asyncio.to_thread(publish_production, _input(arguments), workspace_dir)
        except (ValueError, OSError, json.JSONDecodeError) as error:
            code = "review_incomplete" if str(error).startswith("review_required") else "publication_failed"
            raise HTTPException(422, {"code": code, "message": str(error), "retryable": False}) from error
        return {"version": 1, "operation": OPERATION, "status": "completed", "result": result}

    return {OPERATION: publish}
