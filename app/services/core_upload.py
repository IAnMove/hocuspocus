"""Core-profile uploads that match the UI FormData contract without File()."""
from __future__ import annotations

import os
import re
import uuid
from typing import Any
from urllib.parse import unquote

MAX_UPLOAD_BYTES = 500 * 1024 * 1024
_SAFE_EXT = re.compile(r"^\.[A-Za-z0-9]{1,10}$")
_BOUNDARY = re.compile(r"boundary=([^;]+)", re.IGNORECASE)
_FILENAME_STAR = re.compile(r"filename\*=(?:UTF-8|utf-8)''([^;\r\n]+)")
_FILENAME_QUOTED = re.compile(r'filename="([^"]*)"')
_FILENAME_BARE = re.compile(r"filename=([^;\r\n]+)")
_FIELD_NAME = re.compile(r'name="([^"]+)"')


def unique_upload_name(original: str) -> str:
    base = os.path.basename((original or "upload.bin").replace("\\", "/"))
    ext = os.path.splitext(base)[1].lower()
    if not _SAFE_EXT.fullmatch(ext):
        ext = ".bin"
    return f"{uuid.uuid4().hex}{ext}"


def _boundary(content_type: str) -> bytes | None:
    match = _BOUNDARY.search(content_type or "")
    if not match:
        return None
    value = match.group(1).strip().strip('"')
    if not value:
        return None
    return value.encode("ascii", "ignore")


def _header_filename(header: bytes) -> str:
    text = header.decode("utf-8", "replace")
    match = _FILENAME_STAR.search(text)
    if match:
        return os.path.basename(unquote(match.group(1)))
    match = _FILENAME_QUOTED.search(text)
    if match:
        return os.path.basename(match.group(1))
    match = _FILENAME_BARE.search(text)
    if match:
        return os.path.basename(match.group(1).strip().strip('"'))
    return ""


def _header_field(header: bytes) -> str:
    match = _FIELD_NAME.search(header.decode("utf-8", "replace"))
    return match.group(1) if match else ""


def extract_upload(body: bytes, content_type: str, fallback_name: str = "upload.bin") -> tuple[bytes, str]:
    if len(body) > MAX_UPLOAD_BYTES:
        raise ValueError("File too large (max 500 MB)")
    boundary = _boundary(content_type)
    if boundary is None:
        name = os.path.basename((fallback_name or "upload.bin").replace("\\", "/")) or "upload.bin"
        if not body:
            raise ValueError("A file is required")
        return body, name
    marker = b"--" + boundary
    preferred: tuple[bytes, str] | None = None
    first: tuple[bytes, str] | None = None
    start = 0
    while True:
        idx = body.find(marker, start)
        if idx < 0:
            break
        idx += len(marker)
        if body.startswith(b"--", idx):
            break
        if body.startswith(b"\r\n", idx):
            idx += 2
        elif body.startswith(b"\n", idx):
            idx += 1
        header_end = body.find(b"\r\n\r\n", idx)
        sep = 4
        if header_end < 0:
            header_end = body.find(b"\n\n", idx)
            sep = 2
        if header_end < 0:
            break
        header = body[idx:header_end]
        payload_start = header_end + sep
        next_idx = body.find(b"\r\n" + marker, payload_start)
        if next_idx < 0:
            next_idx = body.find(b"\n" + marker, payload_start)
        if next_idx < 0:
            break
        filename = _header_filename(header)
        if filename:
            payload = body[payload_start:next_idx]
            item = (payload, filename)
            if first is None:
                first = item
            if _header_field(header) == "file":
                preferred = item
                break
        start = next_idx
    chosen = preferred or first
    if chosen is None:
        raise ValueError("A file is required")
    return chosen


def save_upload(folder: str, data: bytes, original_name: str) -> dict[str, Any]:
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("File too large (max 500 MB)")
    os.makedirs(folder, exist_ok=True)
    name = unique_upload_name(original_name)
    dest = os.path.join(folder, name)
    with open(dest, "wb") as handle:
        handle.write(data)
    return {
        "filename": name,
        "path": dest,
        "url": f"/api/v1/uploads/{name}",
    }
