"""Installed LoRA library. Function bodies are unchanged."""
from __future__ import annotations

import glob
import json
import os
import time

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from services import model3d_service

# A relative loras_root still resolves under app/, the directory of the launch module.
_SERVICE_FILE = os.path.abspath(__file__)
__file__ = os.path.join(os.path.dirname(os.path.dirname(_SERVICE_FILE)), "_launch_runtime.py")

wgp = _safe_join = _is_legacy_h3_model = _minimax_h3_turbo_option = None
_civitai_fetch_model = _build_manifest_entry = _get_linked_model_folders = None


def configure(*, engine, safe_join, is_legacy_h3_model, minimax_h3_turbo_option,
              civitai_fetch_model, build_manifest_entry, get_linked_model_folders) -> None:
    global wgp, _safe_join, _is_legacy_h3_model, _minimax_h3_turbo_option
    global _civitai_fetch_model, _build_manifest_entry, _get_linked_model_folders
    wgp = engine
    _safe_join = safe_join
    _is_legacy_h3_model = is_legacy_h3_model
    _minimax_h3_turbo_option = minimax_h3_turbo_option
    _civitai_fetch_model = civitai_fetch_model
    _build_manifest_entry = build_manifest_entry
    _get_linked_model_folders = get_linked_model_folders


def list_lora_directories():
    """Return all available LoRA directories for target selection during download."""
    lora_root = wgp.server_config.get("loras_root", "loras") if hasattr(wgp, 'server_config') else "loras"
    candidates = [lora_root]
    if not os.path.isabs(lora_root):
        candidates.append(os.path.join(os.path.dirname(__file__), lora_root))
        candidates.append(os.path.join(os.getcwd(), lora_root))
    resolved = None
    for c in candidates:
        if os.path.isdir(c):
            resolved = c
            break
    if not resolved:
        return {"directories": []}
    dirs = sorted([
        d for d in os.listdir(resolved)
        if os.path.isdir(os.path.join(resolved, d)) and not d.startswith(".")
    ])
    return {"directories": dirs}


def serve_lora_preview(filename: str):
    """Serve a locally downloaded LoRA preview file (video or image)."""
    # Reject any traversal markers up front; only basenames are valid here.
    if filename != os.path.basename(filename) or filename.startswith("."):
        raise HTTPException(status_code=400, detail="Invalid filename")
    lora_root = wgp.server_config.get("loras_root", "loras") if hasattr(wgp, 'server_config') else "loras"
    app_dir = os.path.dirname(os.path.abspath(__file__))
    base = os.path.join(app_dir, lora_root)
    # Search all subdirectories for the preview file
    for dirpath, _, files in os.walk(base):
        if filename in files:
            filepath = _safe_join(base, os.path.relpath(dirpath, base), filename)
            if filepath is None:
                continue
            media_type = "video/mp4" if filename.endswith(".mp4") else "image/png"
            from services.win_safe_files import share_delete_file_response
            return share_delete_file_response(filepath, media_type=media_type)
    return JSONResponse({"error": "Preview not found"}, status_code=404)

# ── Stable LoRA identifier ───────────────────────────────────────────
# A `lora_id` is a stable identifier that survives version updates.
# Anything keyed off a LoRA in persisted state (activations, weights,
# NSFW stash, etc.) should use this instead of the filename so that
# updating from v1.2 → v1.5 carries those settings forward automatically.
#
#   civitai:{modelId}   - LoRA from CivitAI (any version of the same model)
#   local:{filename}    - locally-trained / hand-installed (no sidecar)
#
# The version is tracked separately in the update manifest, NOT here.
def _compute_lora_id(filename: str, sidecar_meta: dict | None) -> str:
    """Return the stable lora_id for a LoRA file.

    Always prefer `civitai:{modelId}` when the sidecar exposes one so
    that swapping a v1.2 file for v1.5 (different filename, same model)
    keeps the same identifier. Falls back to `local:{filename}` otherwise,
    which is the right behavior for hand-trained or hand-installed LoRAs.
    """
    if isinstance(sidecar_meta, dict):
        model_id = sidecar_meta.get("modelId")
        if model_id is not None:
            try:
                return f"civitai:{int(model_id)}"
            except (TypeError, ValueError):
                # Some sidecars store modelId as a string; pass through.
                return f"civitai:{model_id}"
    return f"local:{filename}"


# ── NSFW LoRA classification ─────────────────────────────────────────
# Used by /api/v1/loras/installed and /api/v1/loras/{model_type}/details.
# Always called as a fallback after checking the CivitAI sidecar's `nsfw`
# boolean — sidecar-true wins; this only fires when the sidecar didn't
# flag it (or the LoRA has no sidecar at all, which is the case for
# anything downloaded outside our CivitAI integration).
#
# Two design choices to limit false positives:
#
#   1. Word-boundary matching, not substring. So "anal" matches "anal"
#      but not "ANALysis"; "oral" matches "oral" but not "mORAL"; "sex"
#      matches "sex" but not "susSEX". Substring matching previously
#      caused real-world FPs (e.g. an LTX-2.3 enhancement LoRA whose
#      guide mentioned "explicit text overlays" was flagged because
#      "explicit" appeared anywhere in the text).
#
#   2. Curated keyword list. Words too ambiguous for context-free
#      matching (e.g. "explicit", "adult", "mature") are deliberately
#      EXCLUDED — they show up too often in SFW contexts. Words that
#      are unambiguous in any reasonable context stay.
#
# Filenames and tags often use `_` or `-` as separators; Python's `\b`
# treats `_` as a word char, so we normalize those to spaces before
# matching. This lets `\bboob\b` correctly match "Big_Boobs_LoRA" when
# the filename is normalized to "Big Boobs LoRA".
import re as _re_nsfw
from functools import lru_cache as _lru_cache_nsfw

# NSFW LoRA-classification keyword fallback — flags a LoRA as mature when a
# keyword appears as a whole word in its name / tags / description, used only
# when the CivitAI sidecar doesn't already flag it. Category-level terms only
# (the two most explicit terms from the original list are dropped to
# keep tracked source clean). `\b` word boundaries prevent false hits like
# "oral"->"moral", "breast"->"breastfeeding", "sex"->"Sussex" (filenames are
# normalized `_`/`-` -> space before matching; see _NSFW_NORMALIZE_RE).
_NSFW_LORA_KEYWORDS = [
    "nsfw", "nude", "naked", "sex", "breast", "oral",
    "doggy", "xxx", "porn", "hentai", "uncensored", "unchained",
]


@_lru_cache_nsfw(maxsize=1)
def _get_nsfw_regex() -> "_re_nsfw.Pattern[str]":
    """Compiled word-boundary regex over the NSFW LoRA keyword fallback."""
    return _re_nsfw.compile(
        r"\b(?:" + "|".join(_re_nsfw.escape(k) for k in _NSFW_LORA_KEYWORDS) + r")\b",
        _re_nsfw.IGNORECASE,
    )


# Normalize filename separators to spaces so word boundaries work
# inside underscore/dash-joined identifiers.
_NSFW_NORMALIZE_RE = _re_nsfw.compile(r"[_\-]")

def _classify_lora_nsfw(
    filename: str,
    display_name: str | None = None,
    sidecar_meta: dict | None = None,
    guide_text: str | None = None,
) -> bool:
    """Return True if any NSFW keyword appears as a whole word anywhere
    across the LoRA's text metadata. Checks:
      - filename (with `_`/`-` normalized to spaces so word boundaries
        catch tokens inside identifiers like `Big_Boobs_LoRA`)
      - display name (CivitAI sidecar's `name`)
      - sidecar tags
      - sidecar description + versionDescription
      - generated `.guide.md` content
    """
    blobs: list[str] = []
    blobs.append(filename or "")
    if display_name:
        blobs.append(str(display_name))
    if isinstance(sidecar_meta, dict):
        tags = sidecar_meta.get("tags") or []
        if isinstance(tags, list):
            blobs.append(" ".join(str(t) for t in tags))
        for key in ("description", "versionDescription"):
            val = sidecar_meta.get(key)
            if isinstance(val, str):
                blobs.append(val)
    if guide_text:
        blobs.append(str(guide_text))
    haystack = _NSFW_NORMALIZE_RE.sub(" ", " ".join(blobs))
    return _get_nsfw_regex().search(haystack) is not None


# ── System-managed LoRA detection ────────────────────────────────────
# Some LoRAs in the user's loras folder are auto-downloaded by the
# launcher itself (model-loading code, blend mode, edit anything, etc.)
# rather than manually installed. They:
#   - are tied to specific model versions (the model loader expects them)
#   - shouldn't be "updated" through the LoRA browser — that's the model
#     update flow's job, and a mismatch can break inference outright
#   - happen to be uploaded to CivitAI by various people, so a naive
#     versionId comparison flags them as "available" even though there's
#     nothing the user should do about it
#
# Filename patterns are the most reliable discriminator since the
# launcher always uses deterministic filenames sourced from HuggingFace.
import re as _re_sys_lora
_SYSTEM_MANAGED_LORA_PATTERNS = (
    # LTX-2 / LTX-2.3 distilled LoRAs (e.g. ltx-2-19b-distilled-lora-384,
    # ltx-2.3-22b-distilled-lora-384, ltx-2.3-22b-distilled-lora-384-1.1).
    # See app/defaults/ltx2_*.json for the canonical download URLs.
    _re_sys_lora.compile(r"distilled[-_]lora", _re_sys_lora.IGNORECASE),
    # Edit Anything LoRA (Alissonerdx, auto-downloaded by /api/v1/edit-anything).
    _re_sys_lora.compile(r"edit[-_]anything", _re_sys_lora.IGNORECASE),
    # Official SCAIL-2 Relighting LoRA, downloaded and converted on first
    # Recast use. It is pinned to the upstream checkpoint hash below.
    _re_sys_lora.compile(r"scail2[-_]relighting[-_]lora", _re_sys_lora.IGNORECASE),
    # MiniMax H3 Turbo accelerator, exposed as a managed experimental preset
    # for Full H3 checkpoints and downloaded on first use.
    _re_sys_lora.compile(r"minimax[-_]h3[-_]turbo", _re_sys_lora.IGNORECASE),
    # LTX-2.3 Transition LoRA (auto-downloaded by ensureTransitionLoraForBlend).
    _re_sys_lora.compile(r"transition", _re_sys_lora.IGNORECASE),
)


def _is_system_managed_lora(filename: str) -> bool:
    """Return True if `filename` matches a known system-managed LoRA pattern."""
    if not filename:
        return False
    base = os.path.splitext(filename)[0]
    return any(p.search(base) for p in _SYSTEM_MANAGED_LORA_PATTERNS)

def _resolve_per_file_update_status(
    lora_id: str,
    file_version_id: int | None,
    lora_max_version: dict[str, int],
    manifest_entry: dict | None,
    filename: str | None = None,
) -> dict:
    """Compute a per-file update status from the manifest + sidecar version.

    The manifest's collective `status` is informative but not authoritative
    for a single file: when a CivitAI LoRA has been updated and the user
    keeps the old file alongside the new one (common when authors change
    naming conventions between releases), both files share a `lora_id` but
    have different `versionId`s. We need to:

      - flag the file that's actually old as `available` so the user sees
        a download prompt for the latest;
      - leave the file that already matches CivitAI's latest as `current`;
      - mark previous-version files as `current` (superseded by another
        file on disk — there's nothing more to download), so we don't keep
        nagging about the same update after the user installs it.

    The result dict mirrors the manifest entry shape so callers can spread
    it directly into their info row.
    """
    out: dict = {
        "update_status": "unknown",
        "latest_version_id": None,
        "current_version_id": file_version_id,
        "latest_published_at": None,
        "latest_changelog": None,
    }
    # System-managed LoRAs (auto-downloaded by the launcher's model code)
    # always report 'current' — there's no user-facing update flow for them
    # and they're tied to specific model versions that the launcher manages.
    if filename and _is_system_managed_lora(filename):
        out["update_status"] = "current"
        return out
    if not isinstance(manifest_entry, dict):
        # No manifest entry yet — local-only LoRAs report 'local',
        # CivitAI-sourced LoRAs that haven't been checked report 'unknown'.
        out["update_status"] = "local" if lora_id.startswith("local:") else "unknown"
        return out
    out["latest_version_id"] = manifest_entry.get("latest_version_id")
    out["latest_published_at"] = manifest_entry.get("latest_published_at")
    out["latest_changelog"] = manifest_entry.get("latest_changelog")
    if manifest_entry.get("status") == "removed":
        out["update_status"] = "removed"
        return out
    # Suppress the badge when CivitAI says the modelId is for a Checkpoint
    # (or any non-LoRA type). Files that land in the LoRA folder but reference
    # a checkpoint-typed model on CivitAI are typically distilled LoRAs that
    # ship bundled with the main model download — there's no per-LoRA update
    # to apply, the user would update the whole checkpoint via a different
    # flow. The file still shows up in listings, just without the "available"
    # status.
    civitai_type = manifest_entry.get("civitai_model_type")
    if isinstance(civitai_type, str) and civitai_type and civitai_type.upper() != "LORA":
        out["update_status"] = "current"
        return out
    latest = out["latest_version_id"]
    if file_version_id is None or latest is None:
        out["update_status"] = "unknown"
        return out
    # File matches or exceeds CivitAI's latest: nothing newer to fetch.
    if file_version_id >= latest:
        out["update_status"] = "current"
        return out
    # File is older than latest, but another file on disk for this same
    # lora_id is the actual newest local copy → this one is superseded
    # (a newer version is already installed). Don't badge.
    if lora_max_version.get(lora_id, 0) > file_version_id:
        out["update_status"] = "current"
        return out
    # Genuinely the only / newest local copy and CivitAI has a newer one.
    out["update_status"] = "available"
    return out


def _build_lora_max_version_map(root: str) -> dict[str, int]:
    """Walk a LoRA directory tree and return `{lora_id: max(versionId)}`
    so the listing endpoints can identify superseded files.

    Only includes LoRAs with a `civitai:`-style lora_id since `local:`
    files don't have versions to compare anyway.
    """
    result: dict[str, int] = {}
    if not root or not os.path.isdir(root):
        return result
    for dirpath, _dirnames, filenames in os.walk(root):
        for f in filenames:
            if not f.endswith((".safetensors", ".sft")):
                continue
            sidecar = os.path.splitext(os.path.join(dirpath, f))[0] + ".civitai.json"
            if not os.path.isfile(sidecar):
                continue
            try:
                with open(sidecar, "r", encoding="utf-8") as sf:
                    meta = json.load(sf)
            except Exception:
                continue
            mid = meta.get("modelId")
            vid = meta.get("versionId")
            if mid is None or vid is None:
                continue
            try:
                lora_id = f"civitai:{int(mid)}"
                vid_i = int(vid)
            except (TypeError, ValueError):
                continue
            if vid_i > result.get(lora_id, 0):
                result[lora_id] = vid_i
    return result

def list_all_installed_loras():
    """List ALL installed LoRAs across all directories with CivitAI metadata.

    Walks the primary loras root PLUS each linked install's loras root
    (issue #16: linked LoRAs never appeared in "My LoRAs" even though the
    guide scan processed them). Same enumeration and mirror convention as
    the scan: linked files are deduped against primary by relative key,
    and their sidecars/guides are read from the PRIMARY MIRROR path first
    (where the scan writes them, since linked installs stay read-only),
    then from beside the file itself.
    """
    lora_root = wgp.server_config.get("loras_root", "loras") if hasattr(wgp, 'server_config') else "loras"
    candidates = [lora_root]
    if not os.path.isabs(lora_root):
        candidates.append(os.path.join(os.path.dirname(__file__), lora_root))
        candidates.append(os.path.join(os.getcwd(), lora_root))
    resolved = None
    for c in candidates:
        if os.path.isdir(c):
            resolved = c
            break
    lora_root = resolved
    if not lora_root:
        return {"loras": []}

    walk_roots = [(lora_root, False)] + [(root, True) for root in _linked_lora_roots()]

    # Read the cached update manifest once per request so each row can
    # surface its update_status without an extra round trip.
    _manifest = _load_lora_manifest()
    _manifest_entries = _manifest.get("entries", {}) if isinstance(_manifest, dict) else {}
    # Pre-compute the highest local versionId per lora_id so per-file
    # status can correctly suppress 'available' on superseded files
    # (older files left over after a newer version was downloaded).
    _lora_max_version = _build_lora_max_version_map(lora_root)

    loras = []
    _seen_keys = set()
    for walk_root, is_linked in walk_roots:
      for dirpath, _dirnames, filenames in os.walk(walk_root):
        for f in filenames:
            if not f.endswith((".safetensors", ".sft")):
                continue
            rel_dir = os.path.relpath(dirpath, walk_root)
            # Dedupe primary vs linked by relative key — primary walks
            # first, so its copy wins (same rule as the scan and the
            # per-model listing endpoints).
            _key = os.path.normcase(os.path.normpath(os.path.join(rel_dir, f)))
            if _key in _seen_keys:
                continue
            _seen_keys.add(_key)
            full_path = os.path.join(dirpath, f)
            own_base = os.path.splitext(full_path)[0]
            # Sidecars/guides for linked files live at the primary-mirror
            # base (scan write target); check it first, then beside the file.
            if is_linked:
                _mirror_base = os.path.normpath(os.path.join(lora_root, rel_dir, os.path.splitext(f)[0]))
                _bases = [_mirror_base, own_base]
            else:
                _bases = [own_base]
            try:
                _size_bytes = os.path.getsize(full_path)
            except OSError:
                _size_bytes = None
            info = {
                "filename": f,
                "directory": rel_dir,
                "linked": is_linked,
                "size_bytes": _size_bytes,
                "trained_words": [],
                "preview_url": None,
                "civitai_model_id": None,
                "has_guide": any(os.path.isfile(b + ".guide.md") for b in _bases),
                "name": None,
                "base_model": None,
                "nsfw": False,
                "downloaded_at": None,
                "released_at": None,
                "lora_id": f"local:{f}",  # overwritten below if sidecar has modelId
            }
            sidecar = next((b + ".civitai.json" for b in _bases if os.path.isfile(b + ".civitai.json")), _bases[0] + ".civitai.json")
            meta = None
            if os.path.isfile(sidecar):
                try:
                    with open(sidecar, "r", encoding="utf-8") as sf:
                        meta = json.load(sf)
                    info["trained_words"] = meta.get("trainedWords", [])
                    info["civitai_model_id"] = meta.get("modelId")
                    info["hf_repo_id"] = meta.get("repoId")
                    info["name"] = meta.get("name")
                    info["base_model"] = meta.get("baseModel")
                    # CivitAI sidecars have carried downloadedAt since the
                    # download path first shipped; publishedAt (the version
                    # release date) is newer — captured at download time and
                    # backfilled for existing files by check-updates.
                    info["downloaded_at"] = meta.get("downloadedAt")
                    info["released_at"] = meta.get("publishedAt")
                    # Manual override (set via /api/v1/loras/nsfw-override)
                    # takes precedence over CivitAI's `nsfw` boolean, which
                    # is sometimes overly conservative (it's "worst content
                    # across the entire model" — set true if any version or
                    # example image is NSFW, even when the LoRA itself is
                    # SFW). Override = bool → use it; Override absent → fall
                    # back to CivitAI's flag.
                    if isinstance(meta.get("nsfw_override"), bool):
                        info["nsfw"] = meta["nsfw_override"]
                        info["nsfw_overridden"] = True
                    else:
                        info["nsfw"] = meta.get("nsfw", False)
                        info["nsfw_overridden"] = False
                    # CivitAI images
                    images = meta.get("images", [])
                    if images and isinstance(images, list) and images[0].get("url"):
                        info["preview_url"] = images[0]["url"]
                    # HuggingFace example media
                    if not info["preview_url"]:
                        example_media = meta.get("exampleMedia", [])
                        if example_media and isinstance(example_media, list):
                            info["preview_url"] = example_media[0]
                except Exception:
                    pass
            # Downloaded-date fallback for HF/hand-installed files without a
            # CivitAI sidecar: the weight file's mtime.
            if not info.get("downloaded_at"):
                try:
                    info["downloaded_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(os.path.getmtime(full_path)))
                except OSError:
                    info["downloaded_at"] = None
            # Check for local preview files (downloaded from HF)
            if not info.get("preview_url"):
                for _b in _bases:
                    for ext in (".mp4", ".png", ".jpg", ".webp"):
                        preview_file = _b + f"_preview1{ext}"
                        if os.path.isfile(preview_file):
                            info["preview_url"] = f"/api/v1/loras/preview/{os.path.basename(preview_file)}"
                            info["preview_type"] = "video" if ext == ".mp4" else "image"
                            break
                    if info.get("preview_url"):
                        break
            # Infer NSFW from filename + sidecar tags/description + guide
            # text — but only when no authoritative signal exists. Manual
            # override always wins; CivitAI's flag wins over the heuristic;
            # the keyword fallback is only for hand-installed LoRAs without
            # sidecars at all.
            has_override = isinstance(meta, dict) and isinstance(meta.get("nsfw_override"), bool)
            sidecar_has_nsfw_field = isinstance(meta, dict) and "nsfw" in meta
            if not info["nsfw"] and not has_override and not sidecar_has_nsfw_field:
                _meta = meta if os.path.isfile(sidecar) else None
                guide_path = next((b + ".guide.md" for b in _bases if os.path.isfile(b + ".guide.md")), None)
                guide_text = None
                if guide_path:
                    try:
                        with open(guide_path, "r", encoding="utf-8") as gf:
                            guide_text = gf.read()
                    except Exception:
                        guide_text = None
                if _classify_lora_nsfw(filename=f, display_name=info.get("name"),
                                       sidecar_meta=_meta, guide_text=guide_text):
                    info["nsfw"] = True
            # Stable identifier: civitai:{modelId} when available, else local:{filename}.
            # Survives version updates so persisted state (weights, activations,
            # NSFW stash) carries forward automatically.
            info["lora_id"] = _compute_lora_id(f, meta)
            # Per-file update status — uses the cached manifest entry plus
            # this file's own sidecar versionId, so superseded files (older
            # version sitting next to a newer one) don't get falsely flagged
            # as "update available."
            file_vid = None
            if isinstance(meta, dict):
                _v = meta.get("versionId")
                if _v is not None:
                    try:
                        file_vid = int(_v)
                    except (TypeError, ValueError):
                        file_vid = None
            _entry = _manifest_entries.get(info["lora_id"]) if isinstance(_manifest_entries, dict) else None
            info.update(_resolve_per_file_update_status(
                lora_id=info["lora_id"],
                file_version_id=file_vid,
                lora_max_version=_lora_max_version,
                manifest_entry=_entry,
                filename=f,
            ))
            loras.append(info)
    return {"loras": loras, "manifest_last_check_at": _manifest.get("last_full_check_at") if isinstance(_manifest, dict) else None}


def _linked_lora_roots() -> list[str]:
    """Loras folders of every linked install, derived from their ckpts
    roots (the convention get_lora_search_dirs and the guide scan use)."""
    roots = []
    for _linked_ckpts in _get_linked_model_folders():
        _linked_loras = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(_linked_ckpts)), "loras"))
        if os.path.isdir(_linked_loras):
            roots.append(_linked_loras)
    return roots


def _is_def_bundled_lora(filename: str) -> bool:
    """True when any model definition bundles this LoRA (accelerator
    distills like SCAIL-2 Fast's lightx2v). Deleting one of these only
    triggers a re-download on that model's next generation — the model
    loads it unconditionally. The try is PER model type: one malformed
    def (e.g. a finetune whose "loras" points at a removed base) must
    not abort the scan and fail the guard open for everything after it."""
    base = os.path.normcase(filename)
    for mt in wgp.displayed_model_types:
        try:
            for url in wgp.get_model_recursive_prop(mt, "loras", return_list=True) or []:
                if isinstance(url, str) and os.path.normcase(url.split("/")[-1]) == base:
                    return True
        except Exception:
            continue
    return False


def delete_lora_file(directory: str, filename: str):
    """Delete an installed LoRA plus its sidecar, guide, and preview files.

    Takes the {directory, filename} pair exactly as /loras/installed
    reports it (directory is relative, "." for the root). Only files in
    the primary loras root are deletable — linked installs are read-only,
    same rule as checkpoint deletes.
    """
    if not filename.endswith((".safetensors", ".sft")) or os.path.basename(filename) != filename:
        raise HTTPException(status_code=400, detail="Not a LoRA file.")
    lora_root = _resolve_lora_root()
    if not lora_root:
        raise HTTPException(status_code=500, detail="LoRA folder not found.")
    rel_dir = "" if directory in ("", ".") else directory
    # _safe_join resolves symlinks before the containment check.
    target = _safe_join(os.path.abspath(lora_root), rel_dir, filename) if rel_dir else _safe_join(os.path.abspath(lora_root), filename)
    if target is None:
        raise HTTPException(status_code=400, detail="Invalid path.")
    if not os.path.isfile(target):
        # The same relative key existing only under a linked root means the
        # user clicked delete on a read-only linked copy.
        for _linked_loras in _linked_lora_roots():
            if os.path.isfile(os.path.join(_linked_loras, rel_dir, filename)):
                raise HTTPException(status_code=403, detail="This LoRA lives in a linked model folder, which is read-only. Delete it from that install instead.")
        raise HTTPException(status_code=404, detail=f"LoRA not found: {filename}")
    # Def-bundled only — the fuzzy _is_system_managed_lora patterns
    # over-match user LoRAs whose names merely contain words like
    # "transition" and would make them permanently undeletable.
    if _is_def_bundled_lora(filename):
        raise HTTPException(status_code=409, detail="This LoRA is bundled with a model (a distill/accelerator) and would just re-download on next use. Delete the model instead.")

    from services.win_safe_files import safe_delete
    result = safe_delete(target)
    if not result.get("deleted"):
        raise HTTPException(status_code=423, detail="The file is locked by another process. Try again in a moment.")
    base = os.path.splitext(target)[0]
    extras_removed = []
    extras = [base + ".civitai.json", base + ".guide.md"]
    extras += [base + f"_preview1{ext}" for ext in (".mp4", ".png", ".jpg", ".webp")]
    for extra in extras:
        try:
            if os.path.isfile(extra):
                os.remove(extra)
                extras_removed.append(os.path.basename(extra))
        except OSError:
            pass
    print(f"[LoRA] Deleted {os.path.join(rel_dir, filename) if rel_dir else filename} (+{len(extras_removed)} sidecar files)")
    return {"status": "ok", "deleted": filename, "deferred": bool(result.get("deferred")), "extras_removed": extras_removed}

def _lora_is_compatible_with_model(model_def: dict, path: str) -> bool:
    from services.h3_runtime_policy import lora_compatible
    return lora_compatible(model_def, path)

def list_loras(model_type: str):
    """List available LoRA files for a model type."""
    if _is_legacy_h3_model(model_type):
        return {"loras": [], "guidance_max_phases": 1}
    if model_type in model3d_service.MODEL_BY_ID:
        return {"loras": [], "guidance_max_phases": 1}
    md = wgp.get_model_def(model_type)
    if md is None:
        raise HTTPException(status_code=404, detail=f"Unknown model: {model_type}")

    try:
        lora_dir = wgp.get_lora_dir(model_type)
    except Exception:
        return {"loras": [], "guidance_max_phases": md.get("guidance_max_phases", 1)}

    turbo_option = _minimax_h3_turbo_option(md)
    if lora_dir is None:
        return {"loras": [], "guidance_max_phases": md.get("guidance_max_phases", 1)}

    # Merge the primary dir with linked read-only dirs (Linked Model
    # Folders' sibling loras/), deduped by filename — so LoRAs from an
    # existing Wan2GP install show up in the Studio selector without
    # copying them.
    names = set()
    if os.path.isdir(lora_dir):
        for search_dir in wgp.get_lora_search_dirs(model_type):
            for f in glob.glob(os.path.join(search_dir, "*.safetensors")) + glob.glob(os.path.join(search_dir, "*.sft")):
                if not _lora_is_compatible_with_model(md, f):
                    continue
                names.add(os.path.basename(f))
    # Managed choices are virtual until first use. Keeping the pinned Turbo
    # filename in the catalog makes it discoverable on a fresh install; the
    # generation preflight below performs the verified one-time download.
    if turbo_option:
        names.update(item["filename"] for item in turbo_option["presets"])
    loras = sorted(names)

    return {
        "loras": loras,
        "guidance_max_phases": md.get("guidance_max_phases", 1),
    }


def list_loras_details(model_type: str):
    """List LoRAs with metadata from .civitai.json sidecars."""
    if _is_legacy_h3_model(model_type):
        return {"loras": [], "guidance_max_phases": 1}
    if model_type in model3d_service.MODEL_BY_ID:
        return {"loras": [], "guidance_max_phases": 1}
    md = wgp.get_model_def(model_type)
    if md is None:
        raise HTTPException(status_code=404, detail=f"Unknown model: {model_type}")
    try:
        lora_dir = wgp.get_lora_dir(model_type)
    except Exception:
        return {"loras": [], "guidance_max_phases": md.get("guidance_max_phases", 1)}
    turbo_option = _minimax_h3_turbo_option(md)
    if lora_dir is None:
        return {"loras": [], "guidance_max_phases": md.get("guidance_max_phases", 1)}

    # Merge across the primary dir and linked read-only dirs (same set as
    # the plain listing endpoint), primary copy wins per filename.
    _seen_names = set()
    files = []
    if os.path.isdir(lora_dir):
        for _search_dir in wgp.get_lora_search_dirs(model_type):
            for f in sorted(
                glob.glob(os.path.join(_search_dir, "*.safetensors"))
                + glob.glob(os.path.join(_search_dir, "*.sft"))
            ):
                if not _lora_is_compatible_with_model(md, f):
                    continue
                _b = os.path.basename(f)
                if _b in _seen_names:
                    continue
                _seen_names.add(_b)
                files.append(f)
    files.sort(key=lambda p: os.path.basename(p))

    # Read the cached update manifest once per request so each row can
    # surface its update_status without an extra round trip.
    _manifest = _load_lora_manifest()
    _manifest_entries = _manifest.get("entries", {}) if isinstance(_manifest, dict) else {}
    # Per-file status needs to know the highest local versionId for each
    # lora_id so we can suppress 'available' on superseded files. Walking
    # just this model-type's lora_dir is enough since multiple versions
    # of the same model live in the same dir.
    _lora_max_version = _build_lora_max_version_map(lora_dir)

    loras = []
    for f in files:
        basename = os.path.basename(f)
        info = {
            "filename": basename,
            "trained_words": [],
            "preview_url": None,
            "civitai_model_id": None,
            "recommended_weights": None,
            "has_guide": False,
            "nsfw": False,
            "downloaded_at": None,
            "released_at": None,
            "lora_id": f"local:{basename}",  # overwritten below if sidecar has modelId
        }
        # Guides and sidecars for LINKED loras are stored in Maestro's own
        # lora dir keyed by the same basename — check there first, then
        # fall back to a sidecar sitting next to the file itself (read-only,
        # e.g. when the linked install is another Maestro/Wan2GP).
        _primary_base = os.path.join(lora_dir, os.path.splitext(basename)[0])
        _own_base = os.path.splitext(f)[0]
        guide_file = next(
            (p for p in (_primary_base + ".guide.md", _own_base + ".guide.md") if os.path.isfile(p)),
            None,
        )
        if guide_file:
            info["has_guide"] = True
            try:
                with open(guide_file, "r", encoding="utf-8") as gf:
                    info["guide"] = gf.read().strip()
            except Exception:
                info["guide"] = None
        # Check for .civitai.json sidecar
        sidecar = next(
            (p for p in (_primary_base + ".civitai.json", _own_base + ".civitai.json") if os.path.isfile(p)),
            _primary_base + ".civitai.json",
        )
        meta = None
        if os.path.isfile(sidecar):
            try:
                with open(sidecar, "r", encoding="utf-8") as sf:
                    meta = json.load(sf)
                info["trained_words"] = meta.get("trainedWords", [])
                info["civitai_model_id"] = meta.get("modelId")
                info["recommended_weights"] = meta.get("recommendedWeights")
                # Same date semantics as /api/v1/loras/installed: downloadedAt
                # is stamped by the download path, publishedAt (version release
                # date) is captured at download and backfilled by check-updates.
                info["downloaded_at"] = meta.get("downloadedAt")
                info["released_at"] = meta.get("publishedAt")
                # Manual override > CivitAI flag > keyword fallback. See
                # /api/v1/loras/installed for full rationale.
                if isinstance(meta.get("nsfw_override"), bool):
                    info["nsfw"] = meta["nsfw_override"]
                    info["nsfw_overridden"] = True
                else:
                    info["nsfw"] = bool(meta.get("nsfw", False))
                    info["nsfw_overridden"] = False
                images = meta.get("images", [])
                if images and isinstance(images, list) and images[0].get("url"):
                    info["preview_url"] = images[0]["url"]
            except Exception:
                meta = None
        # Downloaded-date fallback for HF/hand-installed files without a
        # CivitAI sidecar: the weight file's mtime.
        if not info.get("downloaded_at"):
            try:
                info["downloaded_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(os.path.getmtime(f)))
            except OSError:
                info["downloaded_at"] = None
        # Fallback: infer NSFW from filename + tags + description + guide
        # only when no authoritative signal exists.
        has_override = isinstance(meta, dict) and isinstance(meta.get("nsfw_override"), bool)
        sidecar_has_nsfw_field = isinstance(meta, dict) and "nsfw" in meta
        if not info["nsfw"] and not has_override and not sidecar_has_nsfw_field:
            if _classify_lora_nsfw(
                filename=basename,
                display_name=(meta.get("name") if isinstance(meta, dict) else None),
                sidecar_meta=meta,
                guide_text=info.get("guide"),
            ):
                info["nsfw"] = True
        # Stable identifier: civitai:{modelId} when available, else local:{filename}.
        info["lora_id"] = _compute_lora_id(basename, meta)
        # Per-file update status (see /api/v1/loras/installed for the
        # equivalent logic). Computes against this file's own sidecar
        # versionId rather than blindly inheriting the manifest's
        # collective status, so superseded files don't keep nagging
        # after the user has already downloaded the new version.
        file_vid = None
        if isinstance(meta, dict):
            _v = meta.get("versionId")
            if _v is not None:
                try:
                    file_vid = int(_v)
                except (TypeError, ValueError):
                    file_vid = None
        _entry = _manifest_entries.get(info["lora_id"]) if isinstance(_manifest_entries, dict) else None
        info.update(_resolve_per_file_update_status(
            lora_id=info["lora_id"],
            file_version_id=file_vid,
            lora_max_version=_lora_max_version,
            manifest_entry=_entry,
            filename=basename,
        ))
        loras.append(info)

    for preset in (turbo_option or {}).get("presets", []):
        filename = preset["filename"]
        info = next((item for item in loras if item["filename"] == filename), None)
        if info is None:
            info = {
                "filename": filename,
                "trained_words": [],
                "preview_url": None,
                "civitai_model_id": None,
                "recommended_weights": None,
                "has_guide": False,
                "nsfw": False,
                "downloaded_at": None,
                "released_at": None,
                "lora_id": f"managed:{filename}",
            }
            loras.append(info)
        info.update({
            "managed": True,
            "recommended_weights": {
                "source": "default",
                "default": preset["weight"],
                "min": preset["weight_min"],
                "max": preset["weight_max"],
            },
            "has_guide": True,
            "guide": preset["description"],
            "update_status": "current",
        })
        loras.sort(key=lambda item: item["filename"])
    return {
        "loras": loras,
        "guidance_max_phases": md.get("guidance_max_phases", 1),
        "manifest_last_check_at": _manifest.get("last_full_check_at") if isinstance(_manifest, dict) else None,
    }


async def set_lora_nsfw_override(request: Request):
    """Manually flag a LoRA as SFW or NSFW, overriding CivitAI's nsfw value.

    CivitAI's model-level `nsfw` boolean is "worst content across the model"
    and gets set true if any version or example image is NSFW — even when
    the LoRA itself is SFW. Their browser uses a granular `nsfwLevel` int
    that we don't currently capture, so users with misclassified LoRAs need
    a way to correct the local sidecar.

    Body: `{"filename": "<basename>", "nsfw": true|false|null}`
      - `true` / `false`: write `nsfw_override` to sidecar
      - `null`: clear the override, fall back to CivitAI's flag

    Returns: `{filename, nsfw, nsfw_overridden}` — the new effective state.
    """
    body = await request.json()
    filename = body.get("filename")
    nsfw_value = body.get("nsfw")
    if not isinstance(filename, str) or not filename:
        raise HTTPException(status_code=400, detail="filename is required")
    if nsfw_value is not None and not isinstance(nsfw_value, bool):
        raise HTTPException(status_code=400, detail="nsfw must be true, false, or null")
    # Reject path-traversal — only accept a basename.
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="filename must be a basename, not a path")

    lora_root = _resolve_lora_root()
    if not lora_root:
        raise HTTPException(status_code=500, detail="LoRA root not found")

    # Locate the sidecar by walking the tree — LoRAs live in subdirectories
    # by architecture, and the caller doesn't necessarily know which.
    target_safetensors: str | None = None
    for dirpath, _dirnames, filenames in os.walk(lora_root):
        if filename in filenames:
            target_safetensors = os.path.join(dirpath, filename)
            break
    if not target_safetensors:
        raise HTTPException(status_code=404, detail=f"LoRA not found: {filename}")

    sidecar_path = os.path.splitext(target_safetensors)[0] + ".civitai.json"
    if os.path.isfile(sidecar_path):
        try:
            with open(sidecar_path, "r", encoding="utf-8") as sf:
                sidecar = json.load(sf)
            if not isinstance(sidecar, dict):
                sidecar = {}
        except Exception:
            sidecar = {}
    else:
        # Create a minimal sidecar so the override has somewhere to live.
        sidecar = {}

    if nsfw_value is None:
        sidecar.pop("nsfw_override", None)
    else:
        sidecar["nsfw_override"] = bool(nsfw_value)

    try:
        with open(sidecar_path, "w", encoding="utf-8") as sf:
            json.dump(sidecar, sf, indent=2)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write sidecar: {e}")

    # Compute the new effective nsfw value (override wins over flag).
    if isinstance(sidecar.get("nsfw_override"), bool):
        effective_nsfw = sidecar["nsfw_override"]
        overridden = True
    else:
        effective_nsfw = bool(sidecar.get("nsfw", False))
        overridden = False
    return {
        "filename": filename,
        "nsfw": effective_nsfw,
        "nsfw_overridden": overridden,
    }


def check_lora_updates(force: bool = False):
    """Walk all installed LoRAs, query CivitAI for the latest version of
    each one that has a sidecar `modelId`, and update the manifest with
    the results. Returns a summary the UI can display in a toast.

    Honors a 24h staleness window unless `force=true` is passed: a manifest
    less than 24h old is returned as-is so we don't hammer CivitAI on every
    app start. Uses a small thread pool for parallelism — typical libraries
    of <100 LoRAs finish in a few seconds.
    """
    from datetime import datetime, timezone, timedelta
    from concurrent.futures import ThreadPoolExecutor, as_completed

    lora_root = _resolve_lora_root()
    if not lora_root:
        return {"checked": 0, "updates_available": 0, "errors": ["LoRA root not found"], "skipped": True}

    manifest = _load_lora_manifest()
    now = datetime.now(timezone.utc)
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    if not force and manifest.get("last_full_check_at"):
        try:
            last = datetime.strptime(manifest["last_full_check_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            if now - last < timedelta(hours=LORA_MANIFEST_STALE_HOURS):
                avail = sum(1 for e in manifest.get("entries", {}).values() if e.get("status") == "available")
                return {
                    "checked": len(manifest.get("entries", {})),
                    "updates_available": avail,
                    "errors": [],
                    "skipped": True,
                    "reason": "fresh",
                    "last_full_check_at": manifest["last_full_check_at"],
                }
        except Exception:
            pass

    # Walk all LoRA files and collect (lora_id, model_id, current_version_id).
    targets: list[tuple[str, int, int | None]] = []
    # Every sidecar per model, including superseded-version duplicates the
    # targets list dedupes away — used to backfill publishedAt below.
    sidecars_by_model: dict[int, list[str]] = {}
    for dirpath, _dirnames, filenames in os.walk(lora_root):
        for f in filenames:
            if not f.endswith((".safetensors", ".sft")):
                continue
            # Skip system-managed LoRAs — there's no useful update flow for
            # them and we don't want to waste CivitAI requests on entries
            # that will always render as 'current' anyway.
            if _is_system_managed_lora(f):
                continue
            sidecar = os.path.splitext(os.path.join(dirpath, f))[0] + ".civitai.json"
            if not os.path.isfile(sidecar):
                continue
            try:
                with open(sidecar, "r", encoding="utf-8") as sf:
                    meta = json.load(sf)
            except Exception:
                continue
            model_id = meta.get("modelId")
            if model_id is None:
                continue
            try:
                model_id_int = int(model_id)
            except (TypeError, ValueError):
                continue
            current_v = meta.get("versionId")
            try:
                current_v_int = int(current_v) if current_v is not None else None
            except (TypeError, ValueError):
                current_v_int = None
            sidecars_by_model.setdefault(model_id_int, []).append(sidecar)
            lora_id = f"civitai:{model_id_int}"
            # If multiple files share a modelId (user kept v1 + v2 side by
            # side), we keep the highest current_version_id since that's
            # the one whose update status is most informative.
            existing = next((t for t in targets if t[0] == lora_id), None)
            if existing:
                if (current_v_int or 0) > (existing[2] or 0):
                    targets = [t for t in targets if t[0] != lora_id]
                    targets.append((lora_id, model_id_int, current_v_int))
                continue
            targets.append((lora_id, model_id_int, current_v_int))

    errors: list[str] = []
    new_entries: dict[str, dict] = dict(manifest.get("entries", {}))

    def _backfill_published_at(sidecar_paths: list[str], model_data: dict):
        """Write each version's publishedAt into local sidecars that predate
        publishedAt capture, matched by the sidecar's versionId."""
        versions = {}
        for v in model_data.get("modelVersions", []) or []:
            if isinstance(v, dict) and v.get("id") is not None:
                try:
                    versions[int(v["id"])] = v.get("publishedAt")
                except (TypeError, ValueError):
                    continue
        for path in sidecar_paths:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                if meta.get("publishedAt"):
                    continue
                vid = meta.get("versionId")
                published = versions.get(int(vid)) if vid is not None else None
                if not published:
                    continue
                meta["publishedAt"] = published
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(meta, f, indent=2)
            except Exception:
                continue

    def _fetch_one(target):
        lora_id, model_id, current_v = target
        data, status = _civitai_fetch_model(model_id)
        return lora_id, model_id, current_v, data, status

    if targets:
        # Politeness: keep concurrency low so the CivitAI search/detail
        # endpoints stay responsive for the user's other browsing while
        # this runs in the background. Earlier versions used 8 workers
        # which triggered IP-level rate limits and made parallel /search
        # requests time out at 504. With max_workers=2 a 100-LoRA library
        # finishes in ~50 seconds and the public API stays responsive.
        #
        # Early abort: if the first handful of requests all fail (network
        # outage, CivitAI down, our IP rate-limited), stop hammering and
        # let the user retry later via the manual "Check" button.
        consecutive_failures = 0
        FAILURE_THRESHOLD = 5
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(_fetch_one, t) for t in targets]
            for fut in as_completed(futures):
                try:
                    lora_id, model_id, current_v, data, status = fut.result()
                except Exception as e:
                    errors.append(str(e))
                    consecutive_failures += 1
                    if consecutive_failures >= FAILURE_THRESHOLD:
                        # Cancel pending futures so the endpoint returns
                        # quickly instead of waiting on doomed retries.
                        for f in futures:
                            f.cancel()
                        errors.append(f"Aborted after {consecutive_failures} consecutive failures")
                        break
                    continue
                if data is None and status not in (404,):
                    # Network error / rate limit. Preserve the previous entry
                    # rather than overwriting it with an `unknown` stub —
                    # the user's existing badge state stays accurate.
                    consecutive_failures += 1
                    if consecutive_failures >= FAILURE_THRESHOLD:
                        for f in futures:
                            f.cancel()
                        errors.append(f"Aborted after {consecutive_failures} consecutive CivitAI failures")
                        break
                    if lora_id in new_entries:
                        continue
                else:
                    consecutive_failures = 0  # reset on any success or 404
                entry = _build_manifest_entry(model_id, current_v, data, status, now_iso)
                new_entries[lora_id] = entry
                # Backfill release dates into sidecars that predate
                # publishedAt capture — the fetched model JSON carries
                # every version's publishedAt, so this is free here.
                if data is not None:
                    _backfill_published_at(sidecars_by_model.get(model_id, []), data)

    # Drop entries for LoRAs that no longer exist on disk (deleted by user).
    live_ids = {t[0] for t in targets}
    new_entries = {k: v for k, v in new_entries.items() if k in live_ids}

    manifest["entries"] = new_entries
    manifest["last_full_check_at"] = now_iso
    manifest["_version"] = LORA_MANIFEST_VERSION
    _save_lora_manifest(manifest)

    updates_available = sum(1 for e in new_entries.values() if e.get("status") == "available")
    return {
        "checked": len(targets),
        "updates_available": updates_available,
        "errors": errors,
        "skipped": False,
        "last_full_check_at": now_iso,
    }


def get_lora_update_manifest():
    """Return the cached manifest without hitting CivitAI. The frontend
    reads this on app start to populate badges immediately, and triggers
    /check-updates separately if the cache is stale."""
    return _load_lora_manifest()

# ── LoRA update manifest ─────────────────────────────────────────────
# Tracks the latest CivitAI version per LoRA so the UI can surface an
# "update available" badge in the LoRA browser. The manifest is a
# JSON file co-located with the LoRA root so it travels with the data
# it describes. It's written by /api/v1/loras/check-updates and read
# back into /api/v1/loras/installed and /api/v1/loras/{model_type}/details
# to populate per-row update status.
#
# Schema (v1):
#   {
#     "_version": 1,
#     "last_full_check_at": "2026-04-29T12:00:00Z" | null,
#     "entries": {
#       "civitai:12345": {
#         "model_id": 12345,
#         "current_version_id": 6789,        // from local sidecar
#         "latest_version_id": 7000,          // from CivitAI
#         "latest_published_at": "2026-04-20T10:30:00Z",
#         "latest_changelog": "Fixed XYZ ...",
#         "status": "current" | "available" | "removed",
#         "last_checked_at": "2026-04-29T12:00:00Z"
#       }
#     }
#   }
LORA_MANIFEST_VERSION = 1
LORA_MANIFEST_FILENAME = ".lora_update_manifest.json"
LORA_MANIFEST_STALE_HOURS = 24

def _resolve_lora_root() -> str | None:
    """Resolve the LoRA root directory the same way list_all_installed_loras does."""
    lora_root = wgp.server_config.get("loras_root", "loras") if hasattr(wgp, "server_config") else "loras"
    candidates = [lora_root]
    if not os.path.isabs(lora_root):
        candidates.append(os.path.join(os.path.dirname(__file__), lora_root))
        candidates.append(os.path.join(os.getcwd(), lora_root))
    for c in candidates:
        if os.path.isdir(c):
            return c
    return None


def _lora_manifest_path() -> str | None:
    root = _resolve_lora_root()
    if not root:
        return None
    return os.path.join(root, LORA_MANIFEST_FILENAME)


def _load_lora_manifest() -> dict:
    """Load the manifest, returning a fresh empty one if missing or malformed."""
    fp = _lora_manifest_path()
    empty = {"_version": LORA_MANIFEST_VERSION, "last_full_check_at": None, "entries": {}}
    if not fp or not os.path.isfile(fp):
        return empty
    try:
        with open(fp, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return empty
        # Future-proof: drop unknown versions rather than corrupt the schema.
        if data.get("_version") != LORA_MANIFEST_VERSION:
            return empty
        data.setdefault("entries", {})
        data.setdefault("last_full_check_at", None)
        return data
    except Exception:
        return empty


def _save_lora_manifest(manifest: dict) -> None:
    fp = _lora_manifest_path()
    if not fp:
        return
    try:
        with open(fp, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
    except Exception as e:
        print(f"[LoraUpdates] Failed to save manifest: {e}")
