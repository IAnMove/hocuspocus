"""Hugging Face LoRA import. Function bodies are unchanged."""
from __future__ import annotations

import json
import os
import uuid

import requests
from fastapi import Request
from fastapi.responses import JSONResponse

from services.civitai import _is_minimax_h3_identity
from services.civitai_downloads import (
    _civitai_download_lock,
    _civitai_downloads,
    _complete_download_record,
    _download_progress_percent,
    _fail_download_record,
    _import_civitai_lora_by_url,
    _is_safe_path_component,
    _new_download_record,
    _release_download_target,
    _require_complete_download,
    _reserve_download_target,
    _response_content_length,
    _update_download_record,
)
from services.lora_guides import _generate_and_save_lora_guide

# A relative path still resolves under app/, the directory of the launch module.
_SERVICE_FILE = os.path.abspath(__file__)
__file__ = os.path.join(os.path.dirname(os.path.dirname(_SERVICE_FILE)), "_launch_runtime.py")

# Launch owns the token-path guard. The imported bodies do not read this name.
_hf_token_path = None


def configure(*, hf_token_path) -> None:
    global _hf_token_path
    _hf_token_path = hf_token_path


# Generic placeholder filenames that HF authors commonly use when
# uploading a single LoRA file. The on-disk name "lora_weights.safetensors"
# is meaningless — every imported LoRA would land with the same name and
# the user couldn't tell them apart. When the HF file is one of these
# generic names, we derive a descriptive disk name from the repo id
# (e.g. "AviadDahan/LTX-2.3-ID-LoRA-CelebVHQ-3K" →
# "LTX-2.3-ID-LoRA-CelebVHQ-3K.safetensors") so the user gets a
# self-identifying filename in their loras folder.
_GENERIC_HF_LORA_FILENAMES = {
    "lora_weights.safetensors",
    "pytorch_lora_weights.safetensors",
    "lora.safetensors",
    "model.safetensors",
    "diffusion_lora.safetensors",
    "unet_lora.safetensors",
    "weights.safetensors",
    "adapter_model.safetensors",
}


def _hf_disk_filename(repo_id: str, lora_filename: str, user_specified: bool) -> str:
    """Pick the on-disk filename for an HF-imported LoRA.

    Rules:
      1. If caller explicitly specified a filename, respect it as-is.
      2. If the HF repo's filename is generic (e.g. lora_weights.safetensors),
         rename to "{repo_basename}{ext}" using the last path segment of the
         repo id. Keeps user-facing names self-describing.
      3. Otherwise use the HF name verbatim.

    Repo names get a light sanitization pass to drop characters that
    would be illegal on Windows file systems while keeping dots,
    dashes, and underscores (which are common in HF repo names).
    """
    base = os.path.basename(lora_filename)
    if user_specified:
        return base
    if base.lower() not in _GENERIC_HF_LORA_FILENAMES:
        return base
    # Generic name — rename using repo id
    repo_name = repo_id.split("/")[-1]
    ext = os.path.splitext(base)[1] or ".safetensors"
    # Allow alnum, dot, dash, underscore. Replace anything else with `_`.
    safe = "".join(c if (c.isalnum() or c in "-._") else "_" for c in repo_name).strip("._")
    if not safe:
        # Repo name was entirely non-alnum (extremely unlikely) — fall
        # back to the original generic name rather than producing an
        # empty filename.
        return base
    return f"{safe}{ext}"


HF_BASE_TO_LOCAL_DIR = {
    "MiniMaxAI/MiniMax-H3": "minimax_h3",
    "Comfy-Org/MiniMax-H3": "minimax_h3",
    "Lightricks/LTX-2.3": "ltx2",
    "Lightricks/LTX-Video-2-0.9.8-distilled": "ltxv",
    "Lightricks/LTX-Video": "ltxv",
    "Wan-AI/Wan2.1-T2V-14B": "wan",
    "Wan-AI/Wan2.1-I2V-14B-480P": "wan_i2v",
    "Wan-AI/Wan2.1-I2V-14B-720P": "wan_i2v",
    "Wan-AI/Wan2.1-T2V-1.3B": "wan_1.3B",
    "black-forest-labs/FLUX.1-dev": "flux",
    "black-forest-labs/FLUX.1-schnell": "flux",
    "black-forest-labs/FLUX.2-dev": "flux2_dev",
    "Freepik/flux.2-klein-guidance-9b": "flux2_klein_9b",
    "Freepik/flux.2-klein-guidance-4b": "flux2_klein_4b",
    "tencent/HunyuanVideo": "hunyuan",
    "Qwen/Qwen-Image-Edit-2511": "qwen",
    "Alibaba/Qwen-Image-20B": "qwen",
    "krea/Krea-2-Raw": "krea2",
    "krea/Krea-2-Turbo": "krea2",
    "DeepBeepMeep/krea-2": "krea2",
}


async def hf_import_lora(request: Request):
    """Import a LoRA from a HuggingFace OR CivitAI URL.

    Endpoint name is historical (HF-only originally). Now dispatches by
    URL type:
      - huggingface.co/<user>/<repo> → parses repo metadata, downloads
        .safetensors, saves sidecar, etc.
      - civitai.com/models/<id>[?modelVersionId=<vid>] → fetches model
        details from CivitAI API, downloads the chosen version's file,
        saves the same sidecar shape (so the LoRA browser shows it
        identically regardless of source).
      - civitai.com/api/download/models/<vid> → direct version-id download.

    Both paths produce the same download-record shape so the active
    downloads UI shows them identically.
    """
    body = await request.json()
    url = body.get("url", "").strip()
    target_dir_override = body.get("target_dir", "")  # optional override
    # Optional: caller can specify a specific .safetensors filename from
    # the repo (useful when a repo hosts multiple LoRAs). If empty or not
    # found in the repo siblings, falls back to the heuristic pick below.
    desired_filename = (body.get("filename", "") or "").strip()

    import re as _re

    if target_dir_override and not _is_safe_path_component(target_dir_override):
        return JSONResponse({"error": "Invalid target_dir"}, status_code=400)

    # Detect CivitAI URL FIRST so an HF-looking URL hidden inside a
    # CivitAI redirect doesn't accidentally fall through.
    if "civitai.com" in url.lower():
        return _import_civitai_lora_by_url(url, target_dir_override)

    # Parse repo ID from URL
    # Supports: https://huggingface.co/user/repo, https://huggingface.co/user/repo/tree/main, etc.
    match = _re.search(r'huggingface\.co/([^/]+/[^/]+)', url)
    if not match:
        return JSONResponse({"error": "Unrecognized URL. Expected a HuggingFace repo (https://huggingface.co/user/repo) or a CivitAI model (https://civitai.com/models/<id>)."}, status_code=400)
    repo_id = match.group(1)

    try:
        # 1. Fetch repo metadata
        api_url = f"https://huggingface.co/api/models/{repo_id}"
        resp = requests.get(api_url, timeout=15)
        if resp.status_code == 404:
            return JSONResponse({"error": f"Repository not found: {repo_id}"}, status_code=404)
        resp.raise_for_status()
        repo = resp.json()

        # 2. Find .safetensors file(s)
        siblings = repo.get("siblings", [])
        lora_files = [s["rfilename"] for s in siblings if s["rfilename"].endswith((".safetensors", ".sft"))]
        if not lora_files:
            return JSONResponse({"error": "No .safetensors files found in this repository"}, status_code=400)

        # If caller specified a filename, use it when present in the repo;
        # otherwise fall back to the heuristic pick below.
        lora_filename = None
        if desired_filename:
            for f in lora_files:
                if f == desired_filename or os.path.basename(f) == desired_filename:
                    lora_filename = f
                    break
        if lora_filename is None:
            # Pick the main LoRA file (prefer the one without 'config' in name)
            lora_filename = lora_files[0]
            for f in lora_files:
                if "config" not in f.lower() and "text_encoder" not in f.lower():
                    lora_filename = f
                    break

        # 3. Determine target directory from base_model tag
        card_data = repo.get("cardData", {})
        base_models = card_data.get("base_model", [])
        if isinstance(base_models, str):
            base_models = [base_models]

        target_dir = target_dir_override
        hf_base_label = ""
        if not target_dir:
            # Special-case override: HF model authors often label LTX-2.3
            # LoRAs with the older "Lightricks/LTX-Video-2-0.9.8-distilled"
            # base_model tag (because LTX-2.3 doesn't have its own widely-
            # adopted HF base_model identifier yet). The repo NAME and
            # tags are a more reliable signal of the actual target version.
            #
            # If the repo identity (id, base_models, or tags) clearly
            # references LTX-2.3, force `ltx2` regardless of what
            # HF_BASE_TO_LOCAL_DIR would map. This stops AviadDahan/
            # LTX-2.3-ID-LoRA-CelebVHQ-3K and similar repos from being
            # routed into the legacy `ltxv` folder.
            _identity_blob = " ".join([
                repo_id,
                " ".join(str(b) for b in base_models),
                " ".join(str(t) for t in repo.get("tags", []) or []),
            ]).lower()
            if _is_minimax_h3_identity(_identity_blob):
                target_dir = "minimax_h3"
                hf_base_label = "MiniMax H3 (detected from repo name/tags)"
            elif "ltx-2.3" in _identity_blob or "ltx2.3" in _identity_blob or "ltx_2_3" in _identity_blob:
                target_dir = "ltx2"
                hf_base_label = "LTX-2.3 (detected from repo name/tags)"
            elif "ltx-2" in _identity_blob or "ltx2" in _identity_blob:
                # LTX-2 (any sub-version) — also goes to ltx2 folder.
                target_dir = "ltx2"
                hf_base_label = "LTX-2 (detected from repo name/tags)"
        if not target_dir:
            for bm in base_models:
                if bm in HF_BASE_TO_LOCAL_DIR:
                    target_dir = HF_BASE_TO_LOCAL_DIR[bm]
                    hf_base_label = bm
                    break
        if not target_dir:
            # Fallback: try to infer from tags
            tags = repo.get("tags", [])
            tag_str = " ".join(tags).lower()
            if "ltx-2.3" in tag_str or "ltx2.3" in tag_str:
                target_dir = "ltx2"
            elif "ltx" in tag_str:
                target_dir = "ltx2"
            elif "wan" in tag_str:
                target_dir = "wan"
            elif "flux.2" in tag_str:
                target_dir = "flux2_dev"
            elif "flux" in tag_str:
                target_dir = "flux"
            elif "hunyuan" in tag_str:
                target_dir = "hunyuan"
            elif "qwen" in tag_str:
                target_dir = "qwen"
            else:
                target_dir = "ltx2"  # safe default

        # 4. Resolve full lora directory path
        app_dir = os.path.dirname(os.path.abspath(__file__))
        lora_dir = os.path.join(app_dir, "loras", target_dir)
        os.makedirs(lora_dir, exist_ok=True)
        # Compute the on-disk filename — generic HF names like
        # "lora_weights.safetensors" get renamed using the repo basename
        # so the user gets self-identifying filenames in their loras folder.
        # `lora_filename` (the path within the HF repo) is preserved
        # separately for the download URL below.
        disk_filename = _hf_disk_filename(
            repo_id=repo_id,
            lora_filename=lora_filename,
            user_specified=bool(desired_filename),
        )
        if not _is_safe_path_component(disk_filename):
            return JSONResponse(
                {"error": "HuggingFace returned an invalid filename"},
                status_code=502,
            )
        save_path = os.path.join(lora_dir, disk_filename)
        if disk_filename != os.path.basename(lora_filename):
            print(
                f"[HF Import] Renaming generic '{os.path.basename(lora_filename)}' → "
                f"'{disk_filename}' so the LoRA is identifiable on disk"
            )

        # 5. Fetch README for description
        readme_text = ""
        try:
            readme_resp = requests.get(f"https://huggingface.co/{repo_id}/raw/main/README.md", timeout=15)
            if readme_resp.ok:
                raw = readme_resp.text
                # Strip frontmatter
                if raw.startswith("---"):
                    end = raw.find("---", 3)
                    if end > 0:
                        raw = raw[end + 3:].strip()
                readme_text = raw
        except Exception:
            pass

        # 6. Extract example prompts from widget data
        example_prompts = []
        for w in repo.get("widgetData", [])[:6]:
            txt = w.get("text", "")
            if txt:
                example_prompts.append(txt)

        # 7. Extract example media URLs
        example_media = []
        for w in repo.get("widgetData", [])[:6]:
            out = w.get("output", {})
            media_url = out.get("url", "")
            if media_url:
                example_media.append(media_url)

        # 8. Build sidecar metadata (same structure as CivitAI)
        sidecar = {
            "source": "huggingface",
            "repoId": repo_id,
            "name": repo_id.split("/")[-1],
            "baseModel": hf_base_label or (base_models[0] if base_models else ""),
            "trainedWords": [],  # HF doesn't have a standard field for this
            "description": readme_text[:5000] if readme_text else "",
            "examplePrompts": example_prompts,
            "tags": repo.get("tags", []),
            "author": repo.get("author", ""),
            "downloads": repo.get("downloads", 0),
            "likes": repo.get("likes", 0),
            "createdAt": repo.get("createdAt", ""),
            "exampleMedia": example_media,
        }

        # Extract trigger words from README if present
        if readme_text:
            # Look for common patterns: "trigger word: xxx" or "keyword: xxx"
            for pattern in [
                r'trigger\s*(?:word|phrase)[s]?\s*[:=]\s*[`"\']?([^`"\'\n]+)',
                r'keyword[s]?\s*[:=]\s*[`"\']?([^`"\'\n]+)',
                r'activation\s*(?:word|token)[s]?\s*[:=]\s*[`"\']?([^`"\'\n]+)',
            ]:
                m = _re.search(pattern, readme_text, _re.IGNORECASE)
                if m:
                    words = [w.strip() for w in m.group(1).split(",")]
                    sidecar["trainedWords"] = words
                    break

        # 9. Prepare the sidecar path. It is written by the worker while the
        # final model target is reserved against concurrent imports.
        sidecar_path = os.path.splitext(save_path)[0] + ".civitai.json"

        # 10. Download the LoRA file
        download_url = f"https://huggingface.co/{repo_id}/resolve/main/{lora_filename}"

        # Track download progress — use disk_filename so the download bar
        # shows the user-visible name we'll write to disk, not the generic
        # HF repo name.
        dl_id = f"hf_{uuid.uuid4().hex}"
        with _civitai_download_lock:
            _civitai_downloads[dl_id] = _new_download_record(
                dl_id,
                disk_filename,
                target_dir=lora_dir,
                model_name=sidecar["name"],
            )

        def _do_download():
            partial_path = None
            reserved_target = None
            try:
                reserved_target = _reserve_download_target(dl_id, save_path)
                if reserved_target is None:
                    raise RuntimeError(
                        f"Another download is already writing {disk_filename}"
                    )
                partial_path = f"{save_path}.{uuid.uuid4().hex}.part"
                dl_resp = requests.get(download_url, stream=True, timeout=30)
                dl_resp.raise_for_status()
                total = _response_content_length(dl_resp.headers)
                _update_download_record(dl_id, bytes_total=total)
                downloaded = 0
                with open(partial_path, "wb") as out:
                    for chunk in dl_resp.iter_content(chunk_size=1024 * 1024):
                        if not chunk:
                            continue
                        out.write(chunk)
                        downloaded += len(chunk)
                        _update_download_record(
                            dl_id,
                            bytes_downloaded=downloaded,
                            progress=_download_progress_percent(downloaded, total),
                        )

                _require_complete_download(downloaded, total)
                os.replace(partial_path, save_path)

                print(f"[HF Import] Downloaded {lora_filename} to {save_path}")

                with open(sidecar_path, "w", encoding="utf-8") as f:
                    f.write(json.dumps(sidecar, indent=2, ensure_ascii=False))

                # 11. Download example media files — preview filenames are
                # derived from disk_filename (not the generic HF name) so
                # they live alongside the renamed .safetensors and the
                # gallery preview lookup finds them.
                for i, media_url in enumerate(example_media[:4]):
                    try:
                        ext = ".mp4" if ".mp4" in media_url else ".png"
                        media_path = os.path.join(lora_dir, f"{os.path.splitext(disk_filename)[0]}_preview{i+1}{ext}")
                        mr = requests.get(media_url, timeout=30)
                        if mr.ok:
                            with open(media_path, "wb") as mf:
                                mf.write(mr.content)
                    except Exception:
                        pass

                # 12. Generate guide — pass disk_filename so the guide
                # references the file the user will actually see/use.
                try:
                    _generate_and_save_lora_guide(save_path, sidecar, disk_filename)
                    print(f"[HF Import] Generated guide for {disk_filename}")
                except Exception as e:
                    print(f"[HF Import] Guide generation failed: {e}")

                _complete_download_record(dl_id)

            except Exception as e:
                try:
                    if partial_path and os.path.isfile(partial_path):
                        os.remove(partial_path)
                except OSError:
                    pass
                _fail_download_record(dl_id, e)
                print(f"[HF Import] Download failed: {e}")
            finally:
                if reserved_target is not None:
                    _release_download_target(dl_id, reserved_target)

        import threading
        threading.Thread(target=_do_download, daemon=True).start()

        return {
            "status": "downloading",
            "download_id": dl_id,
            # Return the on-disk name (post-rename) so the UI status
            # message matches what the user sees in their loras folder.
            "filename": disk_filename,
            "target_dir": target_dir,
            "repo_id": repo_id,
            "base_model": sidecar["baseModel"],
        }

    except requests.RequestException as e:
        return JSONResponse({"error": f"Failed to fetch HuggingFace repo: {e}"}, status_code=502)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


def _fetch_hf_readme_context(url: str) -> str:
    """Best-effort fetch of a HuggingFace model card README for prompting hints
    (semi-auto follow-the-pointer for HF-hosted checkpoints). Returns a trimmed
    text block, or "" on any failure."""
    import re as _re
    m = _re.search(r"huggingface\.co/([\w\-.]+/[\w\-.]+)", url or "")
    if not m:
        return ""
    repo = m.group(1)
    for branch in ("main", "master"):
        try:
            r = requests.get(f"https://huggingface.co/{repo}/raw/{branch}/README.md", timeout=12)
            if r.status_code == 200 and r.text and r.text.strip():
                txt = r.text.strip()
                # Drop YAML front-matter if present.
                if txt.startswith("---"):
                    parts = txt.split("---", 2)
                    if len(parts) == 3:
                        txt = parts[2].strip()
                return txt[:1800]
        except Exception:
            continue
    return ""
