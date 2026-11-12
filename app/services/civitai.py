"""CivitAI browser client. Function bodies are unchanged."""
from __future__ import annotations

import json
import os
import threading
import time

import requests
from fastapi import HTTPException

from services.lora_library import _resolve_lora_root

wgp = None
_list_checkpoint_architectures = None
_guess_arch_for_base = None


def configure(*, engine, list_checkpoint_architectures, guess_arch_for_base) -> None:
    global wgp, _list_checkpoint_architectures, _guess_arch_for_base
    wgp = engine
    _list_checkpoint_architectures = list_checkpoint_architectures
    _guess_arch_for_base = guess_arch_for_base


# ── CivitAI Browser ───────────────────────────────────────────────────

CIVITAI_BASE_URL = "https://civitai.com/api/v1"
CIVITAI_IMAGE_CDN = "https://imagecache.civitai.com/xG1nkqKTMzGDvpLrqFT7WA"
CIVITAI_USER_AGENT = "Maestro/1.0 (CivitAI LoRA Browser)"


def _fix_civitai_image_url(url: str, width: int = 450, is_video: bool = False) -> str:
    """Convert CivitAI image UUID to full CDN URL if needed."""
    if not url:
        return ""
    if url.startswith("http"):
        return url
    # UUID — construct CDN URL
    filename = "preview.mp4" if is_video else "preview.jpg"
    return f"{CIVITAI_IMAGE_CDN}/{url}/width={width}/{filename}"


def _fix_civitai_images(data: dict):
    """Recursively fix image URLs in CivitAI API response data."""
    # Fix images in model versions
    for version in data.get("modelVersions", []):
        for img in version.get("images", []):
            url = img.get("url", "")
            is_vid = img.get("type") == "video" or url.endswith(".mp4") or url.endswith(".webm")
            img["url"] = _fix_civitai_image_url(url, 450, is_vid)
    # Fix top-level images (search results)
    for item in data.get("items", []):
        for version in item.get("modelVersions", []):
            for img in version.get("images", []):
                url = img.get("url", "")
                is_vid = img.get("type") == "video" or url.endswith(".mp4") or url.endswith(".webm")
                img["url"] = _fix_civitai_image_url(url, 450, is_vid)

# CivitAI base model name → local architecture for lora directory resolution
# Note: CivitAI uses "LTXV" for all LTX models (LTX, LTX-2, LTX-2.3)
#
# CivitAI's full baseModel taxonomy is exposed via their filter dropdowns
# and accepted as `?baseModels=<exact string>` on the search API. Keep
# this map in sync with what creators actually pick — entries missing
# here become invisible to our browser even though they show up in
# CivitAI's UI and 3rd-party clients (civarchive et al).
# MiniMax H3 LoRA metadata is not fully standardized yet. CivitAI currently
# uses "MiniMax H3", while Hugging Face cards variously use the official repo,
# Comfy's repack, or only a ``minimax-h3`` tag. Match the unambiguous combined
# model name, but never a generic "H3" token on its own.
def _is_minimax_h3_identity(*values) -> bool:
    identity = " ".join(str(value) for value in values if value).casefold()
    compact = "".join(char for char in identity if char.isalnum())
    return "minimaxh3" in compact


CIVIT_TO_LOCAL_ARCH = {
    # Wan Video
    "Wan Video 14B t2v": "t2v",
    "Wan Video 1.3B t2v": "t2v_1.3B",
    "Wan Video 14B i2v 480p": "i2v",
    "Wan Video 14B i2v 720p": "i2v",
    "Wan Video 2.2 T2V-A14B": "t2v",
    "Wan Video 2.2 I2V-A14B": "t2v",
    "Wan Video 2.2 TI2V-5B": "ti2v_2_2",
    "Wan Video 2.5 T2V": "t2v",
    "Wan Video 2.5 I2V": "i2v",
    # Hunyuan
    "Hunyuan Video": "hunyuan_1_5_t2v",
    "Hunyuan 1": "hunyuan",
    # Flux
    "Flux.1 D": "flux",
    "Flux.1 S": "flux_schnell",
    "Flux.1 Krea": "flux",
    "Flux.1 Kontext": "flux_dev_kontext",
    "Flux.2 D": "flux2_dev",
    # Flux 2 Klein — CivitAI splits each variant into distilled
    # ("Flux.2 Klein 9B") and base ("Flux.2 Klein 9B-base"). Both share
    # the same hidden_dim (3072 for 9B, 4096 for 4B), so LoRAs trained
    # against either checkpoint are arch-compatible and route to the
    # same local directory.
    "Flux.2 Klein 9B": "flux2_klein_9b",
    "Flux.2 Klein 9B-base": "flux2_klein_9b",
    "Flux.2 Klein 4B": "flux2_klein_4b",
    "Flux.2 Klein 4B-base": "flux2_klein_4b",
    # LTX — CivitAI splits LTX 1 (LTXV), LTX-2 (LTXV2), and LTX-2.3
    # (LTXV 2.3) into distinct baseModel values. LTX-2 and LTX-2.3
    # share the ltx2 architecture on disk; LTX 1 has its own ltxv dir.
    "LTXV": "ltxv",
    "LTXV2": "ltx2",
    "LTXV 2.3": "ltx2",
    # MiniMax H3 (shared by First/Last, Omni, pruned, and full models)
    "MiniMax H3": "minimax_h3",
    # Qwen Image
    "Qwen": "qwen_image_20B",
    # Krea 2
    "Krea 2": "krea2",
    # Other
    "ZImageTurbo": "z_image",
    "Mochi": "mocha",
    "CogVideoX": "cogvideox",
}


def _civitai_lora_arch(base_model: str) -> str:
    """Return the canonical local LoRA directory key for a CivitAI base."""
    mapped = CIVIT_TO_LOCAL_ARCH.get(base_model, "")
    if mapped:
        return mapped
    # Keep pasted URLs working if CivitAI changes punctuation or casing while
    # retaining the recognizable MiniMax H3 model identity.
    if _is_minimax_h3_identity(base_model):
        return "minimax_h3"
    return ""

# Smart base model filters for the browser.
# Each entry has: label (shown in UI), civitai_base (CivitAI API filter),
# optional search_query (injected into search), and default_dir (target lora directory).
# Virtual entries (search_query set) let us create sub-filters CivitAI doesn't have.
CIVITAI_MODEL_FILTERS = [
    # --- Video ---
    {"label": "MiniMax H3", "civitai_base": "MiniMax H3", "default_dir": "minimax_h3"},
    # LTX — CivitAI now exposes three distinct baseModel values:
    # LTXV (LTX 1), LTXV2 (LTX-2), LTXV 2.3 (LTX-2.3). The previous
    # search_query workarounds bucketed everything under "LTXV" and
    # missed every LoRA tagged with the version-specific values.
    {"label": "LTX (All)", "civitai_base": "LTXV,LTXV2,LTXV 2.3", "default_dir": "ltx2"},
    {"label": "LTX-2.3", "civitai_base": "LTXV 2.3", "default_dir": "ltx2"},
    {"label": "LTX-2", "civitai_base": "LTXV2", "default_dir": "ltx2"},
    {"label": "Wan 14B t2v", "civitai_base": "Wan Video 14B t2v", "default_dir": "wan"},
    {"label": "Wan 14B i2v 480p", "civitai_base": "Wan Video 14B i2v 480p", "default_dir": "wan_i2v"},
    {"label": "Wan 14B i2v 720p", "civitai_base": "Wan Video 14B i2v 720p", "default_dir": "wan_i2v"},
    {"label": "Wan 1.3B t2v", "civitai_base": "Wan Video 1.3B t2v", "default_dir": "wan_1.3B"},
    {"label": "Wan 2.2 T2V", "civitai_base": "Wan Video 2.2 T2V-A14B", "default_dir": "wan"},
    {"label": "Wan 2.2 I2V", "civitai_base": "Wan Video 2.2 I2V-A14B", "default_dir": "wan"},
    {"label": "Wan 2.2 TI2V 5B", "civitai_base": "Wan Video 2.2 TI2V-5B", "default_dir": "wan_5B"},
    {"label": "Wan 2.5 T2V", "civitai_base": "Wan Video 2.5 T2V", "default_dir": "wan"},
    {"label": "Wan 2.5 I2V", "civitai_base": "Wan Video 2.5 I2V", "default_dir": "wan_i2v"},
    {"label": "Hunyuan Video", "civitai_base": "Hunyuan Video", "default_dir": "hunyuan_1_5"},
    {"label": "CogVideoX", "civitai_base": "CogVideoX", "default_dir": "cogvideox"},
    {"label": "Mochi", "civitai_base": "Mochi", "default_dir": "mocha"},
    # --- Image ---
    {"label": "Flux.1 Dev", "civitai_base": "Flux.1 D", "default_dir": "flux"},
    {"label": "Flux.1 Schnell", "civitai_base": "Flux.1 S", "default_dir": "flux"},
    {"label": "Flux.1 Kontext", "civitai_base": "Flux.1 Kontext", "default_dir": "flux_dev_kontext"},
    # CivitAI separates Flux 2 variants into distinct baseModel values.
    # Use them directly (matching what civarchive et al do) instead of
    # the older approach of bucketing everything under "Flux.2 D" and
    # narrowing with a search query — that missed every LoRA tagged with
    # the variant-specific values. CivitAI accepts comma-separated
    # baseModels, so we pass distilled + base variants together to give
    # one combined list per architecture.
    {"label": "Flux.2 Dev", "civitai_base": "Flux.2 D", "default_dir": "flux2"},
    {"label": "Flux.2 Klein 9B", "civitai_base": "Flux.2 Klein 9B,Flux.2 Klein 9B-base", "default_dir": "flux2_klein_9b"},
    {"label": "Flux.2 Klein 4B", "civitai_base": "Flux.2 Klein 4B,Flux.2 Klein 4B-base", "default_dir": "flux2_klein_4b"},
    {"label": "Qwen", "civitai_base": "Qwen", "default_dir": "qwen"},
    {"label": "Krea 2", "civitai_base": "Krea 2", "default_dir": "krea2"},
    {"label": "ZImageTurbo", "civitai_base": "ZImageTurbo", "default_dir": "z_image"},
]

# Best-guess default for the architecture picker, keyed by CivitAI baseModel.
# Only needed where CIVIT_TO_LOCAL_ARCH's lora-DIR value isn't itself a real
# model architecture (e.g. "LTXV 2.3" → lora dir "ltx2", but the model arch
# is "ltx2_22B"). The UI picker lets the user override this guess.
_CIVIT_BASE_TO_ARCH_HINT = {
    "LTXV 2.3": "ltx2_22B",
    "LTXV2": "ltx2_22B",
    "Flux.2 Klein 9B": "flux2_klein_9b",
    "Flux.2 Klein 9B-base": "flux2_klein_9b",
    "Flux.2 Klein 4B": "flux2_klein_4b",
    "Flux.2 Klein 4B-base": "flux2_klein_4b",
    "Flux.2 D": "flux2_dev",
    "Flux.1 D": "flux",
    "Flux.1 Krea": "flux",
    "Qwen": "qwen_image_20B",
}

def _civitai_headers() -> dict:
    headers = {"User-Agent": CIVITAI_USER_AGENT, "Content-Type": "application/json"}
    api_key = wgp.server_config.get("services", {}).get("civitai_api_key", "")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


LORA_CHANGELOG_MAX_LEN = 800




def _civitai_fetch_model(model_id: int, timeout: float = 15.0) -> tuple[dict | None, int | None]:
    """Fetch a CivitAI model. Returns (json_or_None, http_status_or_None).
    A 404 status maps to (None, 404) so callers can mark the LoRA as `removed`.
    Network failures map to (None, None) so callers can preserve the previous
    manifest entry instead of clobbering it.
    """
    try:
        resp = requests.get(
            f"{CIVITAI_BASE_URL}/models/{int(model_id)}",
            headers=_civitai_headers(), timeout=timeout,
        )
        if resp.status_code == 404:
            return None, 404
        resp.raise_for_status()
        return resp.json(), resp.status_code
    except requests.HTTPError as e:
        return None, getattr(e.response, "status_code", None)
    except Exception:
        return None, None


def _build_manifest_entry(
    model_id: int,
    current_version_id: int | None,
    civitai_data: dict | None,
    http_status: int | None,
    now_iso: str,
) -> dict:
    """Build a single manifest entry from CivitAI data + local sidecar info."""
    entry: dict = {
        "model_id": int(model_id),
        "current_version_id": int(current_version_id) if current_version_id is not None else None,
        "latest_version_id": None,
        "latest_published_at": None,
        "latest_changelog": None,
        "civitai_model_type": None,
        "status": "unknown",
        "last_checked_at": now_iso,
    }
    if http_status == 404:
        entry["status"] = "removed"
        return entry
    if not isinstance(civitai_data, dict):
        # Network error or malformed response — caller decides whether to
        # preserve the previous entry instead of using this stub.
        entry["status"] = "unknown"
        return entry
    # Capture CivitAI's model type so per-file status can suppress badges
    # when the modelId points to a non-LoRA (typically a Checkpoint that
    # *bundles* one or more LoRA files — e.g. LTX-2 distilled LoRAs that
    # ship with the main checkpoint download). Updating those happens at
    # the model-checkpoint level, not the LoRA level, so flagging them as
    # "update available" would be misleading.
    entry["civitai_model_type"] = civitai_data.get("type")
    versions = civitai_data.get("modelVersions") or []
    if not isinstance(versions, list) or not versions:
        entry["status"] = "unknown"
        return entry
    latest = versions[0] if isinstance(versions[0], dict) else None
    if not latest:
        entry["status"] = "unknown"
        return entry
    latest_id = latest.get("id")
    entry["latest_version_id"] = int(latest_id) if isinstance(latest_id, (int, float)) else None
    entry["latest_published_at"] = latest.get("publishedAt") or latest.get("createdAt")
    changelog = latest.get("description") or ""
    if isinstance(changelog, str) and changelog:
        # Strip HTML-ish tags lightly (CivitAI ships HTML in description).
        # Full sanitization happens at render time in the UI.
        import re as _re_html
        changelog = _re_html.sub(r"<[^>]+>", "", changelog).strip()
        if len(changelog) > LORA_CHANGELOG_MAX_LEN:
            changelog = changelog[:LORA_CHANGELOG_MAX_LEN].rstrip() + "…"
        entry["latest_changelog"] = changelog
    if entry["latest_version_id"] is None or entry["current_version_id"] is None:
        entry["status"] = "unknown"
    elif entry["latest_version_id"] != entry["current_version_id"]:
        entry["status"] = "available"
    else:
        entry["status"] = "current"
    return entry

def civitai_base_models():
    """Return supported model filters for the browser."""
    return {"filters": CIVITAI_MODEL_FILTERS}


def civitai_checkpoint_architectures(base_model: str = ""):
    """List architectures a checkpoint can be imported as (video/image models
    we already support), plus a best-guess default for the given CivitAI
    baseModel so the UI picker can pre-select it."""
    architectures = _list_checkpoint_architectures()
    guess = _guess_arch_for_base(base_model, {a["architecture"]: True for a in architectures})
    return {"architectures": architectures, "suggested_architecture": guess}

# ── CivitAI response cache ──────────────────────────────────────────
# Search and model-detail responses change rarely, the UI re-fetches
# them constantly (results are wiped every time the browser opens, and
# each filter keystroke re-searches), and CivitAI rate-limits by IP
# aggressively enough that check-updates had to drop to 2 workers.
# Successful responses are cached for a short TTL; errors and
# maintenance pages are never cached.
_CIVITAI_CACHE: dict = {}
_CIVITAI_CACHE_LOCK = threading.Lock()
_CIVITAI_CACHE_TTL = 15 * 60
_CIVITAI_CACHE_MAX = 200


def _civitai_cache_get(key):
    with _CIVITAI_CACHE_LOCK:
        entry = _CIVITAI_CACHE.get(key)
        if entry and entry[0] > time.time():
            return entry[1]
        if entry:
            _CIVITAI_CACHE.pop(key, None)
    return None


def _civitai_cache_put(key, payload):
    with _CIVITAI_CACHE_LOCK:
        if len(_CIVITAI_CACHE) >= _CIVITAI_CACHE_MAX:
            # Evict the quarter closest to expiry.
            for old_key, _ in sorted(_CIVITAI_CACHE.items(), key=lambda kv: kv[1][0])[: _CIVITAI_CACHE_MAX // 4]:
                _CIVITAI_CACHE.pop(old_key, None)
        _CIVITAI_CACHE[key] = (time.time() + _CIVITAI_CACHE_TTL, payload)


def civitai_search(
    query: str = "", sort: str = "Highest Rated", period: str = "AllTime",
    nsfw: bool = False, types: str = "LORA", baseModels: str = "",
    limit: int = 20, cursor: str = "",
):
    """Proxy CivitAI model search (TTL-cached)."""
    # nsfw MUST be part of the key — mature-mode gating changes results.
    cache_key = ("search", query, sort, period, nsfw, types, baseModels, limit, cursor)
    cached = _civitai_cache_get(cache_key)
    if cached is not None:
        return cached
    params = {"limit": limit, "sort": sort, "period": period, "nsfw": str(nsfw).lower(), "types": types}
    if query:
        params["query"] = query
    if baseModels:
        # CivitAI's baseModels filter is an array. When a single filter
        # entry covers multiple variant tags (e.g. Klein 9B distilled
        # AND its base checkpoint), our CIVITAI_MODEL_FILTERS encodes
        # them as a comma-separated string. Split into a list here so
        # `requests` emits ?baseModels=A&baseModels=B repeated params,
        # which is what CivitAI's API actually accepts.
        base_list = [b.strip() for b in baseModels.split(",") if b.strip()]
        if len(base_list) > 1:
            params["baseModels"] = base_list
        elif base_list:
            params["baseModels"] = base_list[0]
    if cursor:
        params["cursor"] = cursor

    try:
        resp = requests.get(f"{CIVITAI_BASE_URL}/models", params=params, headers=_civitai_headers(), timeout=15)
        # Detect CivitAI's scheduled-maintenance page before raise_for_status
        # collapses everything into a generic exception. Their maintenance
        # response is 503 + an HTML page with the title "We'll be right
        # back | Civitai" — we forward a 503 with a clear message so the
        # UI can render "CivitAI is undergoing maintenance" instead of a
        # cryptic "request failed".
        if resp.status_code == 503:
            body_preview = (resp.text or "")[:200]
            is_maintenance = (
                "we'll be right back" in body_preview.lower()
                or "civitai" in body_preview.lower() and "<html" in body_preview.lower()
            )
            if is_maintenance:
                print(f"[CivitAI] Service in maintenance (503 with maintenance page)")
                raise HTTPException(
                    status_code=503,
                    detail="CivitAI is currently in scheduled maintenance. "
                           "Try again in a few minutes.",
                )
        resp.raise_for_status()
        data = resp.json()
        _fix_civitai_images(data)
        _civitai_cache_put(cache_key, data)
        return data
    except HTTPException:
        raise
    except requests.Timeout:
        raise HTTPException(status_code=504, detail="CivitAI request timed out")
    except requests.RequestException as e:
        # Log the response body preview when available — invaluable for
        # diagnosing 5xx vs WAF block vs rate-limit vs bad-request.
        body_preview = ""
        status_code = None
        if hasattr(e, "response") and e.response is not None:
            try:
                body_preview = (e.response.text or "")[:300]
                status_code = e.response.status_code
            except Exception:
                pass
        print(
            f"[CivitAI] Search failed (status={status_code}): {e}"
            + (f"\n  Body preview: {body_preview!r}" if body_preview else "")
        )
        raise HTTPException(status_code=502, detail=f"CivitAI request failed: {e}")


def civitai_model_detail(model_id: int):
    """Fetch CivitAI model details with local architecture mapping (TTL-cached)."""
    cache_key = ("model", model_id)
    cached = _civitai_cache_get(cache_key)
    if cached is not None:
        return cached
    try:
        resp = requests.get(f"{CIVITAI_BASE_URL}/models/{model_id}", headers=_civitai_headers(), timeout=15)
        # Same maintenance-page detection as /search — surface a 503 with
        # a clear message instead of a generic 502 so the UI can render
        # appropriate "try again later" messaging.
        if resp.status_code == 503:
            body_preview = (resp.text or "")[:200]
            if "we'll be right back" in body_preview.lower() or (
                "civitai" in body_preview.lower() and "<html" in body_preview.lower()
            ):
                raise HTTPException(
                    status_code=503,
                    detail="CivitAI is currently in scheduled maintenance. "
                           "Try again in a few minutes.",
                )
        resp.raise_for_status()
        data = resp.json()
    except HTTPException:
        raise
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"CivitAI request failed: {e}")

    # Enrich versions with local arch mapping and fix image URLs
    for version in data.get("modelVersions", []):
        base = version.get("baseModel", "")
        arch = _civitai_lora_arch(base)
        version["localArch"] = arch
        for img in version.get("images", []):
            url = img.get("url", "")
            is_vid = img.get("type") == "video" or url.endswith(".mp4") or url.endswith(".webm")
            img["url"] = _fix_civitai_image_url(url, 450, is_vid)

    # Cache post-enrichment — the mapping is deterministic, so cached
    # hits skip both the network call and the enrichment pass.
    _civitai_cache_put(cache_key, data)
    return data


_CIVITAI_ALLOWED_HOSTS = {"civitai.com", "www.civitai.com", "civitai-delivery-worker-prod.5ac0637cfd0766c97916cefa3764fbdf.r2.cloudflarestorage.com"}


def _is_safe_civitai_url(url: str) -> bool:
    """Only allow downloads from civitai.com and its known CDN hosts.
    Prevents SSRF via the `download_url` body field (attacker could
    otherwise point us at internal services)."""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        host = (parsed.hostname or "").lower()
        if host in _CIVITAI_ALLOWED_HOSTS:
            return True
        # Allow any *.civitai.com subdomain (their CDN routes shift)
        return host.endswith(".civitai.com")
    except Exception:
        return False

def _strip_html_lite(s: str) -> str:
    """Lightweight HTML-tag strip (CivitAI/HF ship HTML in descriptions)."""
    if not isinstance(s, str) or not s:
        return ""
    import re as _re
    return _re.sub(r"<[^>]+>", " ", s)


def _extract_civitai_model_ids(text: str, exclude_id=None) -> list:
    """Find civitai.com/models/<id> references in free text. Returns a deduped,
    order-preserving list of ints, excluding `exclude_id` (typically the
    checkpoint's own modelId). Capped to keep remote fetches bounded."""
    if not isinstance(text, str) or not text:
        return []
    import re as _re
    try:
        ex = int(exclude_id) if exclude_id is not None else None
    except Exception:
        ex = None
    out: list = []
    for m in _re.finditer(r"civitai\.com/models/(\d+)", text, _re.IGNORECASE):
        mid = int(m.group(1))
        if mid != ex and mid not in out:
            out.append(mid)
        if len(out) >= 3:
            break
    return out


def _find_installed_lora_by_model_id(model_id) -> dict | None:
    """Scan the local LoRA tree for a .civitai.json sidecar whose modelId matches.
    Returns {"name", "guide", "trainedWords"} for the first match, else None.

    A merged-LoRA checkpoint prompts like its source LoRA, so that LoRA's
    already-generated .guide.md (if the user has it installed) is the strongest
    signal we have — we surface it verbatim as context (and as a no-LLM reuse
    fallback)."""
    try:
        root = _resolve_lora_root()
    except Exception:
        root = None
    if not root or not os.path.isdir(root):
        return None
    try:
        want = int(model_id)
    except Exception:
        return None
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            if not fn.endswith(".civitai.json"):
                continue
            sc_path = os.path.join(dirpath, fn)
            try:
                with open(sc_path, "r", encoding="utf-8") as f:
                    sc = json.load(f)
            except Exception:
                continue
            if sc.get("modelId") != want:
                continue
            base = sc_path[: -len(".civitai.json")]
            guide = ""
            gp = base + ".guide.md"
            if os.path.isfile(gp):
                try:
                    with open(gp, "r", encoding="utf-8") as f:
                        guide = f.read().strip()
                except Exception:
                    guide = ""
            return {
                "name": sc.get("name", "") or "",
                "guide": guide,
                "trainedWords": sc.get("trainedWords", []) or [],
            }
    return None


def _civitai_model_json_to_meta(data: dict) -> dict:
    """Map a CivitAI model API response to the sidecar-style meta dict that
    _build_lora_context consumes (name/description/trainedWords/examplePrompts/…),
    mining per-sample-image embedded prompt metadata for example prompts."""
    versions = data.get("modelVersions") or []
    latest = versions[0] if (versions and isinstance(versions[0], dict)) else {}
    example_prompts: list = []
    for img in (latest.get("images") or []):
        if isinstance(img, dict):
            meta = img.get("meta")
            if isinstance(meta, dict):
                p = meta.get("prompt")
                if isinstance(p, str) and p.strip():
                    example_prompts.append(p.strip())
        if len(example_prompts) >= 5:
            break
    return {
        "name": data.get("name", "") or "",
        "description": _strip_html_lite(data.get("description", "") or "").strip(),
        "versionDescription": _strip_html_lite(latest.get("description", "") or "").strip(),
        "trainedWords": latest.get("trainedWords", []) or [],
        "examplePrompts": example_prompts,
        "baseModel": latest.get("baseModel", "") or "",
        "tags": data.get("tags", []) or [],
    }
