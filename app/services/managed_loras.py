"""Managed auto-download LoRAs, moved verbatim from the full server.

``bind`` is called once from the full server after ``wgp``, the download
registry and ``_MANAGED_LORAS`` exist, and stores those objects. ``__file__``
points at the full server so a relative ``loras_root`` still resolves under
``app/``, which is what this body did when it lived in the full server.
"""
from __future__ import annotations

import os
import time
import uuid

import requests

# A relative loras_root still resolves under app/, the directory of the launch module.
_SERVICE_FILE = os.path.abspath(__file__)
__file__ = os.path.join(os.path.dirname(os.path.dirname(_SERVICE_FILE)), "_launch_runtime.py")

wgp = None
_civitai_download_lock = None
_civitai_downloads = None
_MANAGED_LORAS = None


def bind(**names):
    """Store the full server's engine, download registry and managed-LoRA table."""
    global wgp, _civitai_download_lock, _civitai_downloads, _MANAGED_LORAS
    wgp = names["wgp"]
    _civitai_download_lock = names["_civitai_download_lock"]
    _civitai_downloads = names["_civitai_downloads"]
    _MANAGED_LORAS = names["_MANAGED_LORAS"]


def _ensure_managed_loras_present(activated_loras, model_type, progress=None):
    """Download any managed auto-download LoRA in `activated_loras` that is
    missing from disk, blocking until each finishes.

    The file is written into the exact directory wgp loads LoRAs from for
    this model (`wgp.get_lora_dir`), so the pipeline finds it immediately
    after we return. Downloads to a .part file and atomically renames on
    success so a crashed/partial download can't masquerade as a valid LoRA.

    `progress(msg)` — optional callback used to surface a status string
    while a download is in flight (we point it at the job's `message` so the
    polling UI shows "Downloading … model").

    Returns the list of filenames downloaded this call (empty if everything
    was already present). Raises RuntimeError on download failure.
    """
    if not activated_loras:
        return []

    try:
        target_dir = wgp.get_lora_dir(model_type)
    except Exception:
        # Fall back to the configured loras_root if the model dir can't be
        # resolved (shouldn't happen for the ltx2 models these LoRAs target).
        lora_root = wgp.server_config.get("loras_root", "loras") if hasattr(wgp, "server_config") else "loras"
        if not os.path.isabs(lora_root):
            lora_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), lora_root)
        target_dir = os.path.join(lora_root, "ltx2")

    def _find_download_record(name):
        """Snapshot of the active-downloads entry for `name`, preferring an
        in-flight ("downloading") record over a finished one. Used to detect
        the frontend's proactive fetch so we wait on it instead of racing."""
        with _civitai_download_lock:
            match = None
            for rec in _civitai_downloads.values():
                if os.path.basename(str(rec.get("filename", ""))) == name:
                    if rec.get("status") == "downloading":
                        return dict(rec)
                    match = dict(rec)
            return match

    downloaded = []
    for fname in activated_loras:
        base = os.path.basename(str(fname))
        spec = _MANAGED_LORAS.get(base)
        if not spec:
            continue
        save_path = os.path.join(target_dir, base)
        label = spec.get("label", base)

        # A linked installation's verified converted file is a valid runtime
        # source too; don't reclaim another 1.2 GB in the primary install.
        try:
            resolved_path = wgp.resolve_lora_path(model_type, base)
        except Exception:
            resolved_path = save_path
        if os.path.isfile(resolved_path):
            continue

        # If another part of the app is already fetching this exact file (the
        # frontend pre-downloads it when the panel mounts), wait for that to
        # finish rather than starting a second concurrent download — on
        # Windows a parallel write / atomic rename onto the open file would
        # fail or corrupt it.
        rec = _find_download_record(base)
        if rec is not None and rec.get("status") == "downloading":
            print(f"[ManagedLoRA] {label} already downloading elsewhere — waiting for it")
            waited = 0.0
            while waited < 600:
                rec = _find_download_record(base)
                if rec is None or rec.get("status") != "downloading":
                    break
                if progress:
                    pct = int(rec.get("progress") or 0)
                    progress(f"Downloading {label} model (one-time setup)… {pct}%")
                time.sleep(2)
                waited += 2
            # A legacy or externally-created failed record may still point at
            # an in-place partial. Drop it so the presence check below can
            # re-fetch a clean copy.
            if rec is not None and rec.get("status") == "failed":
                try:
                    if os.path.isfile(save_path):
                        os.remove(save_path)
                except Exception:
                    pass

        if os.path.isfile(save_path):
            continue

        os.makedirs(target_dir, exist_ok=True)
        remote_path = spec.get("remote_path", base)
        revision = spec.get("revision", "main")
        url = f"https://huggingface.co/{spec['repo_id']}/resolve/{revision}/{remote_path}"
        # Unique temp + atomic rename: a partial/failed download can never be
        # mistaken for a valid LoRA, and we don't clobber another writer.
        tmp_path = save_path + f".{uuid.uuid4().hex[:8]}.part"
        source_tmp_path = (
            save_path + f".{uuid.uuid4().hex[:8]}.source.part"
            if spec.get("converter") else tmp_path
        )
        print(f"[ManagedLoRA] {label} not found — downloading {url} -> {save_path}")
        if progress:
            progress(f"Downloading {label} model (one-time setup)…")
        try:
            import hashlib

            resp = requests.get(url, stream=True, timeout=30)
            resp.raise_for_status()
            total = int(resp.headers.get("content-length", 0))
            done = 0
            last_pct = -1
            digest = hashlib.sha256()
            with open(source_tmp_path, "wb") as out:
                for chunk in resp.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    out.write(chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    if progress and total > 0:
                        pct = int(done * 100 / total)
                        if pct >= last_pct + 5:
                            last_pct = pct
                            progress(f"Downloading {label} model (one-time setup)… {pct}%")

            expected_size = spec.get("size")
            if expected_size is not None and done != int(expected_size):
                raise RuntimeError(
                    f"download size mismatch (expected {int(expected_size)} bytes, got {done})"
                )
            expected_sha256 = spec.get("sha256")
            actual_sha256 = digest.hexdigest()
            if expected_sha256 and actual_sha256.lower() != str(expected_sha256).lower():
                raise RuntimeError("download SHA-256 mismatch; the checkpoint was not published")

            if spec.get("converter") == "scail2_sat_lora":
                if progress:
                    progress(f"Converting {label} model (one-time setup)…")
                print(f"[ManagedLoRA] Converting official SAT LoRA -> {tmp_path}")
                from services.scail2_lora import convert_scail2_sat_lora
                tensor_count = convert_scail2_sat_lora(
                    source_tmp_path,
                    tmp_path,
                    expected_sha256=str(expected_sha256),
                )
                print(f"[ManagedLoRA] Converted {tensor_count} SCAIL-2 Relighting tensors")
                os.remove(source_tmp_path)
            elif source_tmp_path != tmp_path:
                os.replace(source_tmp_path, tmp_path)
            os.replace(tmp_path, save_path)
            downloaded.append(base)
            print(f"[ManagedLoRA] {label} downloaded -> {save_path}")
        except Exception as e:
            for partial_path in {tmp_path, source_tmp_path}:
                try:
                    if os.path.isfile(partial_path):
                        os.remove(partial_path)
                except Exception:
                    pass
            support_url = spec.get("support_url", f"https://huggingface.co/{spec['repo_id']}")
            if spec.get("converter"):
                recovery_hint = (
                    f"Retry the automatic setup, or download the official source from "
                    f"{support_url} and convert it with SCAIL-2's convert_lora.py."
                )
            else:
                recovery_hint = f"Try again, or import it manually from {support_url}."
            raise RuntimeError(
                f"Could not download the {label} model automatically: {e}. "
                f"Check your internet connection. {recovery_hint}"
            ) from e

    return downloaded
