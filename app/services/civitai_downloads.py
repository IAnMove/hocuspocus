"""CivitAI download worker and the shared download registry. Function bodies are unchanged."""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import PureWindowsPath

import requests
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from services.checkpoints import (
    _checkpoint_download_dir,
    _generate_and_save_checkpoint_guide,
    _register_checkpoint_finetune,
    _scan_defaults_by_arch,
)
from services.civitai import (
    CIVITAI_BASE_URL,
    _civitai_headers,
    _civitai_lora_arch,
    _is_safe_civitai_url,
)
from services.lora_guides import _generate_and_save_lora_guide

# A relative path still resolves under app/, the directory of the launch module.
_SERVICE_FILE = os.path.abspath(__file__)
__file__ = os.path.join(os.path.dirname(os.path.dirname(_SERVICE_FILE)), "_launch_runtime.py")

wgp = _safe_join = _ensure_llm_loaded = None


def configure(*, engine, safe_join, ensure_llm_loaded) -> None:
    global wgp, _safe_join, _ensure_llm_loaded
    wgp = engine
    _safe_join = safe_join
    _ensure_llm_loaded = ensure_llm_loaded


_civitai_downloads: dict = {}
_civitai_download_lock = threading.Lock()
_download_target_reservations: dict[str, str] = {}


def _is_safe_path_component(value) -> bool:
    """Return whether a user-controlled filename/directory is one component."""
    if not isinstance(value, str) or not value:
        return False
    if value in (".", "..") or value.rstrip(" .") != value:
        return False
    if any(ord(char) < 32 or char in '<>:"|?*' for char in value):
        return False
    if "/" in value or "\\" in value or os.path.isabs(value):
        return False
    drive, _tail = os.path.splitdrive(value)
    if drive:
        return False
    if PureWindowsPath(value).is_reserved():
        return False
    device_stem = value.split(".", 1)[0].upper()
    if device_stem in {"CON", "PRN", "AUX", "NUL"}:
        return False
    if (
        len(device_stem) == 4
        and device_stem[:3] in {"COM", "LPT"}
        and device_stem[3] in "123456789"
    ):
        return False
    return True


def _response_content_length(headers) -> int:
    """Return a trustworthy wire length, or zero for decoded responses."""
    try:
        encoding = str(
            headers.get("content-encoding")
            or headers.get("Content-Encoding")
            or ""
        ).strip().lower()
        if encoding not in ("", "identity"):
            return 0
        length = headers.get("content-length") or headers.get("Content-Length") or 0
        return max(0, int(length))
    except (AttributeError, TypeError, ValueError, OverflowError):
        return 0


def _download_progress_percent(bytes_downloaded, bytes_total) -> int:
    """Return byte progress in the public download API's 0..100 scale."""
    try:
        downloaded = max(0, int(bytes_downloaded or 0))
        total = max(0, int(bytes_total or 0))
    except (TypeError, ValueError, OverflowError):
        return 0
    if total <= 0:
        return 0
    return min(100, int(downloaded * 100 / total))


def _require_complete_download(bytes_downloaded, bytes_total):
    """Reject a cleanly-ended HTTP stream when Content-Length is short."""
    if bytes_total > 0 and bytes_downloaded != bytes_total:
        raise IOError(
            f"Incomplete download: received {bytes_downloaded} of "
            f"{bytes_total} bytes"
        )


def _new_download_record(download_id: str, filename: str, **internal) -> dict:
    """Build the common record shared by CivitAI and HuggingFace imports."""
    record = {
        "id": str(download_id),
        "filename": str(filename or ""),
        "status": "downloading",
        "progress": 0,
        "bytes_downloaded": 0,
        "bytes_total": 0,
        "error": None,
        "started_at": time.time(),
        "completed_at": None,
    }
    record.update(internal)
    return record


def _safe_download_number(value, *, integer: bool = False):
    """Coerce an internal value without letting status serialization fail."""
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0 if integer else None
    if number != number or number in (float("inf"), float("-inf")):
        return 0 if integer else None
    if integer:
        return max(0, int(number))
    return number


def _serialize_download_record(record, fallback_id: str = "") -> dict:
    """Return the stable, JSON-safe public shape for any registry entry."""
    if not isinstance(record, dict):
        record = {}
    progress = _safe_download_number(record.get("progress"), integer=True)
    error = record.get("error")
    model_type = record.get("model_type")
    warnings = record.get("warnings")
    if not isinstance(warnings, (list, tuple)):
        warnings = []
    return {
        "id": str(record.get("id") or fallback_id),
        "filename": str(record.get("filename") or ""),
        "status": str(record.get("status") or "downloading"),
        "progress": min(100, progress),
        "bytes_downloaded": _safe_download_number(
            record.get("bytes_downloaded"), integer=True,
        ),
        "bytes_total": _safe_download_number(
            record.get("bytes_total"), integer=True,
        ),
        "error": None if error is None else str(error),
        "started_at": _safe_download_number(record.get("started_at")),
        "completed_at": _safe_download_number(record.get("completed_at")),
        # Present after a checkpoint has been registered successfully. The UI
        # uses this as a filename-independent signal to refresh model lists.
        "model_type": None if not model_type else str(model_type),
        "warnings": [str(warning) for warning in warnings],
    }


def _update_download_record(download_id: str, **changes):
    """Mutate a download record under the registry lock."""
    with _civitai_download_lock:
        record = _civitai_downloads.get(download_id)
        if record is not None:
            record.update(changes)
        return record


def _complete_download_record(download_id: str):
    _update_download_record(
        download_id,
        status="completed",
        progress=100,
        error=None,
        completed_at=time.time(),
    )


def _fail_download_record(download_id: str, error):
    _update_download_record(
        download_id,
        status="failed",
        error=str(error),
        completed_at=time.time(),
    )


def _normalize_download_target(target_path: str) -> str:
    return os.path.normcase(os.path.realpath(os.path.abspath(target_path)))


def _reserve_download_target(download_id: str, target_path: str):
    """Reserve one normalized final path; return its key or None if busy."""
    normalized = _normalize_download_target(target_path)
    owner = str(download_id)
    with _civitai_download_lock:
        current_owner = _download_target_reservations.get(normalized)
        if current_owner is not None and current_owner != owner:
            return None
        _download_target_reservations[normalized] = owner
    return normalized


def _release_download_target(download_id: str, target_path: str):
    """Release a reservation only when it still belongs to this attempt."""
    normalized = _normalize_download_target(target_path)
    with _civitai_download_lock:
        if _download_target_reservations.get(normalized) == str(download_id):
            _download_target_reservations.pop(normalized, None)


def _validate_safetensors_payload(path: str):
    """Apply Maestro's minimum-size and header checks to a safetensors file."""
    file_size = os.path.getsize(path)
    if file_size < 100 * 1024:
        raise ValueError(
            f"file is only {file_size} bytes — too small to be a real LoRA"
        )
    with open(path, "rb") as handle:
        raw_len = handle.read(8)
        if len(raw_len) != 8:
            raise ValueError("file is shorter than the 8-byte safetensors header prefix")
        import struct as _struct
        header_len = _struct.unpack("<Q", raw_len)[0]
    if header_len <= 0 or header_len > 256 * 1024 * 1024:
        raise ValueError(
            f"safetensors header length {header_len} is out of range "
            f"(file is not a valid safetensors)"
        )
    if 8 + header_len >= file_size:
        raise ValueError(
            f"safetensors header claims {header_len} bytes but file is only "
            f"{file_size} bytes total"
        )


def _zip_member_target(target_dir: str, member_name: str, *, flatten: bool) -> str:
    """Resolve one archive member without permitting unsafe components."""
    normalized_name = str(member_name or "").replace("\\", "/")
    components = normalized_name.split("/")
    if flatten:
        components = [components[-1]] if components else []
    if not components or any(not _is_safe_path_component(part) for part in components):
        raise ValueError(f"unsafe archive member path: {member_name!r}")
    target = _safe_join(target_dir, *components)
    if target is None:
        raise ValueError(f"archive member escapes target directory: {member_name!r}")
    return target


def _copy_zip_member_to_partial(zip_file, member, partial_path: str) -> int:
    copied = 0
    with zip_file.open(member) as source, open(partial_path, "wb") as output:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            output.write(chunk)
            copied += len(chunk)
    return copied


def _extract_civitai_archive(
    archive_path: str,
    target_dir: str,
    download_id: str,
    reserved_targets: set,
    partial_paths: set,
) -> list[str]:
    """Validate and atomically publish every selected member of a ZIP."""
    import zipfile

    prepared = []
    seen_targets = set()
    archive_target = _normalize_download_target(archive_path)
    with zipfile.ZipFile(archive_path, "r") as zip_file:
        members = [member for member in zip_file.infolist() if not member.is_dir()]
        safetensor_members = [
            member for member in members
            if member.filename.lower().endswith((".safetensors", ".sft"))
        ]
        selected = safetensor_members or members
        if not selected:
            raise ValueError("archive contains no extractable files")

        for member in selected:
            is_safetensors = member in safetensor_members
            final_path = _zip_member_target(
                target_dir, member.filename, flatten=is_safetensors,
            )
            normalized_target = _normalize_download_target(final_path)
            if normalized_target == archive_target:
                raise ValueError(
                    f"archive member {member.filename!r} collides with its archive path"
                )
            if normalized_target in seen_targets:
                raise ValueError(
                    f"archive contains duplicate target {os.path.basename(final_path)!r}"
                )
            seen_targets.add(normalized_target)

            reservation = _reserve_download_target(download_id, final_path)
            if reservation is None:
                raise RuntimeError(
                    f"Another download is already writing {os.path.basename(final_path)}"
                )
            reserved_targets.add(reservation)
            os.makedirs(os.path.dirname(final_path), exist_ok=True)

            partial_path = f"{final_path}.{uuid.uuid4().hex}.part"
            partial_paths.add(partial_path)
            copied = _copy_zip_member_to_partial(zip_file, member, partial_path)
            if copied != member.file_size:
                raise IOError(
                    f"Incomplete archive member {member.filename!r}: received "
                    f"{copied} of {member.file_size} bytes"
                )
            if is_safetensors:
                try:
                    _validate_safetensors_payload(partial_path)
                except Exception as exc:
                    raise RuntimeError(
                        f"Invalid safetensors archive member {member.filename!r}: {exc}"
                    ) from exc
            prepared.append((partial_path, final_path))

    extracted = []
    for partial_path, final_path in prepared:
        os.replace(partial_path, final_path)
        partial_paths.discard(partial_path)
        extracted.append(final_path)
    return extracted

async def civitai_download(request: Request):
    """Start downloading a file from CivitAI."""
    body = await request.json()
    url = body.get("download_url")
    filename = body.get("filename", "model.safetensors")
    target_arch = body.get("target_arch", "")
    model_id = body.get("model_id")
    version_id = body.get("version_id")
    trained_words = body.get("trained_words", [])
    model_name = body.get("model_name", "")
    images = body.get("images", [])
    description = body.get("description", "")
    version_description = body.get("version_description", "")
    base_model = body.get("base_model", "")
    example_prompts = body.get("example_prompts", [])
    tags = body.get("tags", [])
    model_nsfw = body.get("nsfw", False)

    target_dir_name = body.get("target_dir_name", "")  # Direct dir name override (e.g., "flux2_klein_9b")
    kind = (body.get("kind") or "lora").lower()  # "lora" (default) | "checkpoint"
    target_architecture = body.get("target_architecture", "")  # required for checkpoint imports
    auto_quantize = bool(body.get("auto_quantize", False))  # checkpoint: load-time int8

    # Trust the version's base-model identity over a stale browser mapping.
    # An explicit directory choice remains authoritative.
    if kind == "lora" and not target_dir_name:
        inferred_target_arch = _civitai_lora_arch(base_model)
        if inferred_target_arch:
            target_arch = inferred_target_arch

    if not url:
        raise HTTPException(status_code=400, detail="download_url is required")
    if not _is_safe_civitai_url(url):
        raise HTTPException(status_code=400, detail="download_url must point to civitai.com")
    if not _is_safe_path_component(filename):
        raise HTTPException(status_code=400, detail="Invalid filename")
    if target_arch and not _is_safe_path_component(target_arch):
        raise HTTPException(status_code=400, detail="Invalid target_arch")

    # target_dir_name is user-supplied — reject anything that isn't a
    # plain directory name to defeat traversal into arbitrary filesystem
    # locations when combined with lora_root below.
    if target_dir_name and not _is_safe_path_component(target_dir_name):
        raise HTTPException(status_code=400, detail="Invalid target_dir_name")

    # Resolve target directory.
    if kind == "checkpoint":
        # Checkpoints are full transformer weights — validate the requested
        # architecture against the supported set and route into ckpts/ (where
        # WGP loads model weights from), NOT the loras tree.
        arch_index = _scan_defaults_by_arch()
        if not target_architecture or target_architecture not in arch_index:
            raise HTTPException(
                status_code=400,
                detail="A supported target_architecture is required for checkpoint imports",
            )
        target_dir = _checkpoint_download_dir()
    else:
        # LoRA — user override takes priority
        lora_root = wgp.server_config.get("loras_root", "loras") if hasattr(wgp, 'server_config') else "loras"
        if not os.path.isabs(lora_root):
            lora_root = os.path.join(os.path.dirname(__file__), lora_root)
        if target_dir_name:
            candidate = _safe_join(lora_root, target_dir_name)
            if candidate is None:
                raise HTTPException(status_code=400, detail="Invalid target_dir_name")
            target_dir = candidate
        elif target_arch:
            try:
                target_dir = wgp.get_lora_dir(target_arch)
            except Exception:
                target_dir = _safe_join(lora_root, target_arch)
                if target_dir is None:
                    raise HTTPException(status_code=400, detail="Invalid target_arch")
        else:
            target_dir = lora_root
    os.makedirs(target_dir, exist_ok=True)

    download_id = uuid.uuid4().hex[:8]
    dl = _new_download_record(download_id, filename)
    dl.update({
        "target_dir": target_dir,
        # Metadata for sidecar
        "_url": url,
        "_model_id": model_id,
        "_version_id": version_id,
        "_trained_words": trained_words,
        "_model_name": model_name,
        "_images": images,
        "_description": description,
        "_version_description": version_description,
        "_base_model": base_model,
        "_example_prompts": example_prompts,
        "_tags": tags,
        "_nsfw": model_nsfw,
        # Version release date — powers "newest release" sorting in My
        # LoRAs so users can tell which of a creator's renamed variants
        # is actually current.
        "_published_at": body.get("published_at"),
        "_kind": kind,
        "_target_architecture": target_architecture,
        "_auto_quantize": auto_quantize,
    })
    with _civitai_download_lock:
        _civitai_downloads[download_id] = dl

    thread = threading.Thread(target=_run_civitai_download, args=(download_id,), daemon=True)
    thread.start()

    return {"download_id": download_id, "status": "downloading"}

def _run_civitai_download(download_id: str):
    """Background thread: download file from CivitAI with progress tracking."""
    dl = _civitai_downloads[download_id]
    url = dl["_url"]
    target_dir = dl["target_dir"]
    filename = dl["filename"]
    partial_paths = set()
    reserved_targets = set()

    try:
        # CivitAI's download endpoint sits behind Cloudflare with bot
        # protection that's stricter than the API endpoints — a custom
        # User-Agent is enough to trigger 500 responses while the same URL
        # works in any browser. Use a browser-like UA + Accept header for
        # downloads specifically, so we look like a normal client.
        # (The API helpers keep their custom UA for telemetry/etiquette;
        # only this hot path needs to masquerade.)
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/121.0.0.0 Safari/537.36"
            ),
            "Accept": "*/*",
            # Deliberately omit `br` (brotli). The `requests` library only
            # auto-decompresses brotli when the optional `brotli` package
            # is installed in the venv; without it, brotli responses get
            # written verbatim to disk and produce ~10KB of compressed
            # garbage that later crashes mmgp's safetensors reader with
            # OverflowError. CivitAI's CDN preferentially serves brotli
            # for small bodies (auth-error pages, Cloudflare challenges),
            # so this surfaced primarily as "every LoRA download produced
            # an 11KB junk file" when a request was rejected.
            #
            # gzip + deflate are auto-decompressed by `requests` always,
            # and large LoRA bodies are typically served identity-encoded
            # anyway, so dropping brotli costs nothing in practice.
            "Accept-Encoding": "gzip, deflate",
        }
        # Auth strategy:
        #   1. If URL already has a token query param: trust it, no Bearer.
        #      CivitAI API responses often include a per-user `?token=...`
        #      already; appending a second one yields HTTP 500.
        #   2. Else if we have an API key: append `?token={api_key}` so the
        #      auth survives the redirect to CivitAI's CDN (which strips
        #      Authorization headers cross-origin).
        from urllib.parse import urlparse, parse_qs
        url_has_token = bool(parse_qs(urlparse(url).query).get("token"))
        if not url_has_token:
            api_key = wgp.server_config.get("services", {}).get("civitai_api_key", "")
            if api_key:
                sep = "&" if "?" in url else "?"
                url = f"{url}{sep}token={api_key}"
                headers["Authorization"] = f"Bearer {api_key}"
        resp = requests.get(url, headers=headers, stream=True, timeout=30, allow_redirects=True)
        if resp.status_code >= 400:
            # Surface CivitAI's actual response body so we can tell whether
            # it's a Cloudflare challenge, a token issue, an unauthorized
            # error, etc. — invaluable for diagnosing 500s in the wild.
            body_preview = ""
            try:
                body_preview = resp.text[:500] if hasattr(resp, "text") else ""
            except Exception:
                pass
            print(
                f"[CivitAI] Download HTTP {resp.status_code} for {url}\n"
                f"  Response headers: {dict(resp.headers)}\n"
                f"  Body preview: {body_preview!r}"
            )
        resp.raise_for_status()

        # Get filename from content-disposition if available
        cd = resp.headers.get("content-disposition", "")
        if "filename=" in cd:
            fname = cd.split("filename=")[1].strip('"').strip(";").strip()
            if fname:
                remote_filename = os.path.basename(fname.replace("\\", "/"))
                if _is_safe_path_component(remote_filename):
                    filename = remote_filename
                    _update_download_record(download_id, filename=filename)

        total = _response_content_length(resp.headers)
        _update_download_record(download_id, bytes_total=total)

        save_path = os.path.join(target_dir, filename)
        reserved_target = _reserve_download_target(download_id, save_path)
        if reserved_target is None:
            raise RuntimeError(f"Another download is already writing {filename}")
        reserved_targets.add(reserved_target)
        partial_path = f"{save_path}.{uuid.uuid4().hex}.part"
        partial_paths.add(partial_path)
        downloaded = 0

        with open(partial_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):  # 1MB chunks
                if not chunk:
                    continue
                f.write(chunk)
                downloaded += len(chunk)
                _update_download_record(
                    download_id,
                    bytes_downloaded=downloaded,
                    progress=_download_progress_percent(downloaded, total),
                )

        _require_complete_download(downloaded, total)

        # ── Bogus-payload check ─────────────────────────────────────
        # Detect the case where CivitAI returned an auth-error page,
        # rate-limit response, or Cloudflare challenge body INSTEAD of
        # the LoRA. Symptoms: file is tiny (a real LoRA is at minimum
        # several MB) and/or the safetensors header doesn't parse.
        # Without this check, a 10KB error-page body lands as a
        # `.safetensors` file and later crashes mmgp's loader with
        # `OverflowError: cannot fit 'int' into an index-sized integer`
        # — much harder to diagnose than failing here at download time.
        if filename.lower().endswith((".safetensors", ".sft")):
            try:
                _validate_safetensors_payload(partial_path)
            except Exception as _validate_exc:
                raise RuntimeError(
                    f"CivitAI returned an invalid LoRA payload: {_validate_exc}. "
                    f"This is usually a missing/expired CivitAI API key, a rate-limit, "
                    f"or a model that requires special access. Check Settings → Services → "
                    f"CivitAI API Key."
                )

        # Publish only a fully-received (and, for safetensors, validated)
        # payload. A failed stream leaves no truncated model at save_path.
        os.replace(partial_path, save_path)
        partial_paths.discard(partial_path)

        # Check if downloaded file is a ZIP archive (some CivitAI LoRAs are zipped)
        extracted_files = []
        import zipfile
        if zipfile.is_zipfile(save_path):
            print(f"[CivitAI] Downloaded file is a ZIP archive — extracting...")
            extracted_files = _extract_civitai_archive(
                save_path,
                target_dir,
                download_id,
                reserved_targets,
                partial_paths,
            )
            # Delete the archive only after every selected member has passed
            # path, size, payload, reservation, and atomic-publish checks.
            os.remove(save_path)
            save_path = extracted_files[0]
            filename = os.path.basename(save_path)
            _update_download_record(download_id, filename=filename)
            print(f"[CivitAI] Extracted {len(extracted_files)} file(s)")

        # NOTE: A previous version did dim-based architecture verification
        # here (peeking the safetensors header and warning if the file's
        # attention tensors didn't match the target directory's expected
        # hidden dim). It was removed because the dim assumptions were
        # wrong — Klein 9B uses the same 4096 hidden / 12288 QKV dims as
        # Flux 2 Pro/Dev, so the check false-positived on legitimate
        # Klein-trained LoRAs. The file-integrity gate above (size > 100KB
        # AND parseable safetensors header) is the actual safety net.

        sidecar_data = {
            "modelId": dl["_model_id"],
            "versionId": dl["_version_id"],
            "name": dl["_model_name"],
            "baseModel": dl.get("_base_model", ""),
            "trainedWords": dl["_trained_words"],
            "description": dl.get("_description", ""),
            "versionDescription": dl.get("_version_description", ""),
            "examplePrompts": dl.get("_example_prompts", []),
            "tags": dl.get("_tags", []),
            "nsfw": dl.get("_nsfw", False),
            "images": dl["_images"][:4] if dl["_images"] else [],
            "downloadedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        if dl.get("_published_at"):
            sidecar_data["publishedAt"] = dl["_published_at"]
        if dl.get("_kind") == "checkpoint":
            sidecar_data["modelType"] = "Checkpoint"

        # Write sidecar and generate guide for each extracted file (or the single download)
        files_to_process = extracted_files if extracted_files else [save_path]
        for file_path in files_to_process:
            if not os.path.isfile(file_path):
                continue
            fname = os.path.basename(file_path)
            sidecar_path = os.path.splitext(file_path)[0] + ".civitai.json"
            try:
                with open(sidecar_path, "w", encoding="utf-8") as f:
                    json.dump(sidecar_data, f, indent=2)
            except Exception as e:
                print(f"[CivitAI] Failed to write sidecar for {fname}: {e}")

        # Post-download registration differs by kind:
        #   - checkpoint: write a finetune JSON so WGP lists it as a selectable
        #                 model variant of an existing architecture.
        #   - lora:       auto-generate a usage guide + weight recommendations.
        if dl.get("_kind") == "checkpoint":
            try:
                dl["message"] = "Registering checkpoint..."
                model_type, finetune_path = _register_checkpoint_finetune(
                    save_path, sidecar_data, dl.get("_target_architecture", ""),
                    auto_quantize=dl.get("_auto_quantize", False),
                )
                dl["model_type"] = model_type
                dl["message"] = f"Registered as model '{model_type}'"
                # Auto-generate a per-checkpoint prompt-enhancer guide from the
                # CivitAI metadata, stored inline in the (gitignored) finetune
                # JSON. Isolated from registration: a guide failure (or the LLM
                # not being loaded) must not mark the successful registration as
                # failed. Mirrors the LoRA guide auto-generation path above.
                try:
                    dl["message"] = "Generating prompt guide..."
                    _ensure_llm_loaded()
                    _generate_and_save_checkpoint_guide(finetune_path, sidecar_data)
                except Exception as ge:
                    print(f"[CivitAI] Checkpoint guide auto-generation failed (non-fatal): {ge}")
                finally:
                    dl["message"] = f"Registered as model '{model_type}'"
            except Exception as e:
                # The weight file is already on disk; surface a warning instead
                # of failing the whole download so the user can retry/repair the
                # registration without re-downloading gigabytes.
                msg = f"Checkpoint downloaded but registration failed: {e}"
                dl.setdefault("warnings", []).append(msg)
                print(f"[CivitAI] {msg}")
        else:
            # Auto-generate guide + weight recommendations from metadata
            for file_path in files_to_process:
                if not os.path.isfile(file_path):
                    continue
                fname = os.path.basename(file_path)
                try:
                    dl["message"] = f"Generating guide for {fname}..."
                    _ensure_llm_loaded()
                    _generate_and_save_lora_guide(file_path, sidecar_data, fname)
                except Exception as e:
                    print(f"[CivitAI] Guide auto-generation failed for {fname} (non-fatal): {e}")

        _complete_download_record(download_id)
        print(f"[CivitAI] Download complete: {filename} ({downloaded / 1024 / 1024:.1f}MB)"
              f"{f' — extracted {len(extracted_files)} file(s)' if extracted_files else ''}")

    except Exception as e:
        _fail_download_record(download_id, e)
        print(f"[CivitAI] Download failed: {e}")
    finally:
        for cleanup_path in tuple(partial_paths):
            try:
                if os.path.isfile(cleanup_path):
                    os.remove(cleanup_path)
            except OSError:
                pass
        for reserved_target in tuple(reserved_targets):
            _release_download_target(download_id, reserved_target)

def civitai_downloads_status():
    """List active and recent downloads."""
    with _civitai_download_lock:
        downloads = [
            _serialize_download_record(dl, fallback_id=download_id)
            for download_id, dl in _civitai_downloads.items()
        ]
    return {"downloads": downloads}

# ── HuggingFace / CivitAI LoRA Import ────────────────────────────────────────

def _import_civitai_lora_by_url(url: str, target_dir_override: str = "") -> JSONResponse:
    """Resolve a CivitAI URL to a download record and start the download.

    Mirrors the surface area of the existing /api/v1/civitai/download POST
    flow but takes a single URL instead of structured fields. Useful for
    users who paste any of these into the "Import URL" field:
      - https://civitai.com/models/<modelId>
      - https://civitai.com/models/<modelId>/<slug>
      - https://civitai.com/models/<modelId>?modelVersionId=<versionId>
      - https://civitai.com/models/<modelId>/<slug>?modelVersionId=<versionId>
      - https://civitai.com/api/download/models/<versionId>

    Returns the same JSON shape as the HF import path so the LoRA browser's
    handleImport doesn't need to branch on result type. The download itself
    runs in a background thread (same `_run_civitai_download` used by the
    normal browser-driven flow).
    """
    import re as _re

    url = url.strip()

    # Form 1: /api/download/models/<versionId>  — versionId is the URL path segment
    version_id: int | None = None
    model_id: int | None = None
    m = _re.search(r"civitai\.com/api/download/models/(\d+)", url)
    if m:
        version_id = int(m.group(1))
    else:
        # Form 2: /models/<modelId>[/slug][?modelVersionId=<vid>]
        m = _re.search(r"civitai\.com/models/(\d+)", url)
        if not m:
            return JSONResponse(
                {"error": "Unrecognized CivitAI URL. Expected /models/<id> or /api/download/models/<versionId>."},
                status_code=400,
            )
        model_id = int(m.group(1))
        vm = _re.search(r"[?&]modelVersionId=(\d+)", url)
        if vm:
            version_id = int(vm.group(1))

    # Resolve model_id + version_id by querying CivitAI's API.
    try:
        if version_id is not None and model_id is None:
            # Form 1 (direct version URL): fetch the version to recover model_id.
            resp = requests.get(
                f"{CIVITAI_BASE_URL}/model-versions/{version_id}",
                headers=_civitai_headers(),
                timeout=15,
            )
            resp.raise_for_status()
            version_data = resp.json()
            if "error" in version_data:
                return JSONResponse({"error": f"CivitAI: {version_data['error']}"}, status_code=404)
            model_id = version_data.get("modelId")
            if not model_id:
                return JSONResponse({"error": "CivitAI version response missing modelId"}, status_code=502)

        # Fetch the model — needed for tags, sidecar metadata, and to find
        # the right version when modelVersionId wasn't in the URL.
        resp = requests.get(
            f"{CIVITAI_BASE_URL}/models/{model_id}",
            headers=_civitai_headers(),
            timeout=15,
        )
        if resp.status_code == 404:
            return JSONResponse({"error": f"CivitAI model {model_id} not found"}, status_code=404)
        resp.raise_for_status()
        model_data = resp.json()

        if model_data.get("type", "").upper() != "LORA":
            return JSONResponse(
                {"error": f"CivitAI model {model_id} is type '{model_data.get('type')}', not LORA"},
                status_code=400,
            )

        versions = model_data.get("modelVersions", []) or []
        if not versions:
            return JSONResponse({"error": "CivitAI model has no published versions"}, status_code=400)

        # Pick the right version: user-specified, or latest published.
        chosen = None
        if version_id is not None:
            for v in versions:
                if v.get("id") == version_id:
                    chosen = v
                    break
            if chosen is None:
                return JSONResponse(
                    {"error": f"Version {version_id} not found on model {model_id}. Try removing the modelVersionId from the URL to use the latest."},
                    status_code=404,
                )
        else:
            # Latest = first in the modelVersions array (CivitAI returns newest-first).
            chosen = versions[0]
            version_id = chosen.get("id")

        # Pick the primary file. CivitAI marks one file as "primary" — that's
        # what their UI downloads when you click the big download button.
        files = chosen.get("files", []) or []
        if not files:
            return JSONResponse({"error": "CivitAI version has no files (may be a draft or missing upload)"}, status_code=400)
        primary_file = next((f for f in files if f.get("primary")), files[0])
        download_url = primary_file.get("downloadUrl")
        remote_filename = str(primary_file.get("name") or "model.safetensors")
        filename = os.path.basename(remote_filename.replace("\\", "/"))
        if not _is_safe_path_component(filename):
            return JSONResponse({"error": "CivitAI returned an invalid filename"}, status_code=502)
        if not download_url:
            return JSONResponse({"error": "CivitAI file has no downloadUrl"}, status_code=502)

        # Resolve target directory:
        #  1. explicit override (caller passed target_dir)
        #  2. CIVIT_TO_LOCAL_ARCH lookup by version's baseModel
        #  3. fallback to lora_root (no arch subdir)
        base_model = chosen.get("baseModel", "") or ""
        target_arch = _civitai_lora_arch(base_model)

        lora_root = wgp.server_config.get("loras_root", "loras") if hasattr(wgp, "server_config") else "loras"
        if not os.path.isabs(lora_root):
            lora_root = os.path.join(os.path.dirname(__file__), lora_root)

        if target_dir_override:
            # Reject traversal — same guard as /api/v1/civitai/download.
            if not _is_safe_path_component(target_dir_override):
                return JSONResponse({"error": "Invalid target_dir"}, status_code=400)
            target_dir = _safe_join(lora_root, target_dir_override)
            if target_dir is None:
                return JSONResponse({"error": "Invalid target_dir"}, status_code=400)
        elif target_arch:
            try:
                target_dir = wgp.get_lora_dir(target_arch)
            except Exception:
                target_dir = os.path.join(lora_root, target_arch)
        else:
            target_dir = lora_root
        os.makedirs(target_dir, exist_ok=True)

        # Build the download record using the same shape /civitai/download
        # creates, then dispatch to the same background-download function.
        download_id = uuid.uuid4().hex[:8]
        dl = _new_download_record(download_id, filename)
        dl.update({
            "target_dir": target_dir,
            "_url": download_url,
            "_model_id": model_id,
            "_version_id": version_id,
            "_trained_words": chosen.get("trainedWords", []) or [],
            "_model_name": model_data.get("name", ""),
            "_images": chosen.get("images", []) or [],
            "_description": model_data.get("description", "") or "",
            "_version_description": chosen.get("description", "") or "",
            "_base_model": base_model,
            "_example_prompts": [],
            "_tags": model_data.get("tags", []) or [],
            "_nsfw": bool(model_data.get("nsfw", False)),
        })
        with _civitai_download_lock:
            _civitai_downloads[download_id] = dl

        thread = threading.Thread(target=_run_civitai_download, args=(download_id,), daemon=True)
        thread.start()

        return JSONResponse({
            "download_id": download_id,
            "status": "downloading",
            "filename": filename,
            "target_dir": os.path.relpath(target_dir, os.path.dirname(__file__)),
            "base_model": base_model,
            "model_id": model_id,
            "version_id": version_id,
        })

    except requests.Timeout:
        return JSONResponse({"error": "CivitAI request timed out"}, status_code=504)
    except requests.RequestException as e:
        return JSONResponse({"error": f"CivitAI request failed: {e}"}, status_code=502)
