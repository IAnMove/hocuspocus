"""Model weight groups and the MCP model list, moved verbatim from the full server.

``bind`` is called once from the full server after ``wgp`` exists. ``list_models``
and ``get_model_options`` are the shared services the list calls; they are
imported here, not copied.
"""
from __future__ import annotations

import os

from services.model_downloads import list_models
from services.model_options import get_model_options

wgp = None


def bind(**names):
    """Store the full server's engine. Keyword arguments only."""
    global wgp
    wgp = names["wgp"]


def _variant_group_filenames(urls) -> list:
    """Flatten one weight group (list of variant URLs / dict entries) to file names."""
    names = []
    for url_entry in urls:
        url_str = url_entry
        if isinstance(url_entry, dict):
            inner = url_entry.get("URLs", url_entry.get("url", []))
            url_str = inner[0] if isinstance(inner, list) and inner else (inner if isinstance(inner, str) else "")
        if not isinstance(url_str, str) or not url_str:
            continue
        names.append(url_str.rstrip("/").split("/")[-1])
    return names


def _variant_group_downloaded(urls) -> bool:
    """True when ANY variant (full bf16 vs quantized int8...) of one weight
    group exists locally. Resolves through the files locator so checkpoints
    in linked model folders (Settings -> System -> Linked Model Folders)
    light up too — a hardcoded ckpts_dir check misses every secondary root."""
    for filename in _variant_group_filenames(urls):
        if wgp.fl.locate_file(filename, error_if_none=False) is not None:
            return True
    return False


def _model_weight_groups(model_type: str, owned_only: bool = False) -> list:
    """All weight groups a model needs on disk: main URLs + weight modules.

    "URLs" may be a string pointer to another model type (finetunes such as
    z_image_control or scail2_14B_fast use "URLs": "<base_model>"). Resolve
    recursively like the engine does — iterating the raw value would walk
    the characters of the string and permanently report not-downloaded.

    owned_only=True returns only groups this entry itself declares (skips a
    string-pointer base). Used by delete: removing a finetune must not pull
    the shared base transformer out from under its sibling entries — the
    base is deleted from the base model's own row instead.

    String-named modules resolve through the engine's module registry and
    are intentionally left out (they were never counted here).
    """
    md = wgp.get_model_def(model_type) or {}
    groups = []
    raw_urls = md.get("URLs", None)
    if isinstance(raw_urls, str):
        if not owned_only:
            urls = wgp.get_model_recursive_prop(model_type, "URLs", return_list=True)
            if urls:
                groups.append(urls)
    elif raw_urls:
        groups.append(raw_urls)
    for module in md.get("modules", []):
        if isinstance(module, list):
            groups.append(module)
        elif isinstance(module, dict):
            group = module.get("URLs", [])
            if group:
                groups.append(group)
    return groups


def _missing_image_model_files(model_type: str) -> list[str]:
    """Explain readiness using the same checkpoint roots and variant groups."""
    missing = [" or ".join(_variant_group_filenames(group))
               for group in _model_weight_groups(model_type) if not _variant_group_downloaded(group)]
    definition = wgp.get_model_def(model_type) or {}
    required = list(definition.get("required_model_assets", []))
    if definition.get("vision_encoder_filename"):
        required.append(definition["vision_encoder_filename"])
    missing.extend(path for path in required if wgp.fl.locate_file(path, error_if_none=False) is None)
    for url in wgp.get_model_recursive_prop(model_type, "loras", return_list=True):
        filename = url.split("/")[-1]
        if not os.path.isfile(wgp.resolve_lora_path(model_type, filename)):
            missing.append(filename)
    return list(dict.fromkeys(name for name in missing if name))


def mcp_model_list(args):
    """models and models.list: summaries unless detail is true or one id is named."""
    if not isinstance(args, dict):
        args = {}
    model_type = args.get("model_type")
    if isinstance(model_type, str) and model_type.strip():
        return get_model_options(model_type)
    return list_models(detail=args.get("detail") is True)
