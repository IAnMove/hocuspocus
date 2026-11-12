"""Which files a model pre-download fetches, without importing WanGP.

``resolve_model_files`` is the file-resolution mirror of the block at the top
of ``wgp.load_models`` (the vendored engine). ``download_model_files`` is
launch's pre-download, moved here: it resolves that list and then fetches.
``app/wgp.py`` is vendored from upstream WanGP and is not edited. The two
blocks have drifted; the test table records where a reading of ``load_models``
and this mirror still request the same files.
"""
from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ResolvedModelFiles:
    """The downloads ``load_models`` would start for one model type.

    ``files`` is ``(filename, source_type, submodel_no)`` in resolution order.
    An empty ``files`` tuple means the handler's own list is the whole
    download (``download_models("", model_type, 0, -1)``). ``text_encoder``
    is ``(filename, folder)`` when a text encoder is part of the plan.
    """

    files: tuple[tuple[str, int, int], ...]
    text_encoder: tuple[str, str | None] | None


def resolve_model_files(
    model_type: str,
    *,
    get_model_def: Callable[..., Any],
    transformer_quantization: str,
    transformer_dtype_policy: Any,
    get_transformer_dtype: Callable[..., Any],
    get_model_filename: Callable[..., str],
    get_model_recursive_prop: Callable[..., Any],
    text_encoder_quantization: str,
) -> ResolvedModelFiles:
    """Return the file list the pre-download mirror would fetch. No I/O.

    The body is the file-resolution block of launch's ``_download_model_files``,
    which mirrors ``wgp.load_models``. Names the block reads on the engine are
    arguments. It does not download and it does not check that a file landed.
    """
    model_def = get_model_def(model_type)
    quantization = transformer_quantization
    dtype_policy = transformer_dtype_policy
    transformer_dtype = get_transformer_dtype(model_type, dtype_policy)

    model_file_list = [get_model_filename(model_type=model_type, quantization=quantization, dtype_policy=dtype_policy)]
    source_type_list = [0]
    submodel_no_list = [1]
    if "URLs2" in model_def:
        model_file_list.append(get_model_filename(model_type=model_type, quantization=quantization, dtype_policy=dtype_policy, submodel_no=2))
        source_type_list.append(0)
        submodel_no_list.append(2)
    modules = get_model_recursive_prop(model_type, "modules", return_list=True)
    modules = [get_model_recursive_prop(module, "modules", sub_prop_name="_list", return_list=True) if isinstance(module, str) else module for module in modules]
    for module_type in modules:
        if isinstance(module_type, dict):
            for urls_key, submodel_no in (("URLs", 1), ("URLs2", 2)):
                urls = module_type.get(urls_key, None)
                if urls is None:
                    raise Exception(f"No {urls_key} defined for Module {module_type}")
                model_file_list.append(get_model_filename(model_type, quantization, transformer_dtype, URLs=urls))
                source_type_list.append(1)
                submodel_no_list.append(submodel_no)
        else:
            model_file_list.append(get_model_filename(model_type, quantization, transformer_dtype, module_type=module_type))
            source_type_list.append(1)
            submodel_no_list.append(0)

    files: list[tuple[str, int, int]] = []
    for filename, source_type, submodel_no in zip(model_file_list, source_type_list, submodel_no_list):
        if len(filename) == 0:
            continue
        files.append((filename, source_type, submodel_no))

    text_encoder: tuple[str, str | None] | None = None
    text_encoder_URLs = get_model_recursive_prop(model_type, "text_encoder_URLs", return_list=True)
    if text_encoder_URLs is not None:
        te_quant = (model_def.get("text_encoder_quantization", None) if model_def else None) or text_encoder_quantization
        text_encoder_filename = get_model_filename(model_type=model_type, quantization=te_quant, dtype_policy=dtype_policy, URLs=text_encoder_URLs)
        if text_encoder_filename is not None and len(text_encoder_filename):
            text_encoder_folder = model_def.get("text_encoder_folder", None)
            text_encoder = (text_encoder_filename, text_encoder_folder)
    return ResolvedModelFiles(files=tuple(files), text_encoder=text_encoder)


def download_model_files(
    model_type: str,
    *,
    is_legacy_h3_model: Callable[[str], bool],
    ensure_quality_assets: Callable[..., Any],
    is_h3_downloaded: Callable[[], bool],
    get_model_def: Callable[..., Any],
    transformer_quantization: str,
    transformer_dtype_policy: Any,
    get_transformer_dtype: Callable[..., Any],
    get_model_filename: Callable[..., str],
    get_model_recursive_prop: Callable[..., Any],
    download_models: Callable[..., Any],
    get_local_model_filename: Callable[..., Any],
    text_encoder_quantization: str,
    check_model_downloaded: Callable[[str], bool],
) -> None:
    """Resolve and fetch every file the pre-download mirror would download.

    The legacy MiniMax H3 branch and the "located after download" checks stay
    here. The file list itself comes from ``resolve_model_files``.
    """
    if is_legacy_h3_model(model_type):
        ensure_quality_assets(
            lambda message: print(f"[H3 Legacy] {message}")
        )
        if not is_h3_downloaded():
            raise RuntimeError(
                "Legacy download finished but the exact ConvRot files are still missing."
            )
        return

    plan = resolve_model_files(
        model_type,
        get_model_def=get_model_def,
        transformer_quantization=transformer_quantization,
        transformer_dtype_policy=transformer_dtype_policy,
        get_transformer_dtype=get_transformer_dtype,
        get_model_filename=get_model_filename,
        get_model_recursive_prop=get_model_recursive_prop,
        text_encoder_quantization=text_encoder_quantization,
    )
    fetched = False
    for filename, source_type, submodel_no in plan.files:
        download_models(filename, model_type, source_type, submodel_no)
        fetched = True
    if not fetched:
        # No main file: the handler's own file list is the whole download (load_models does the same).
        download_models("", model_type, 0, -1)

    if plan.text_encoder is not None:
        text_encoder_filename, text_encoder_folder = plan.text_encoder
        download_models(text_encoder_filename, model_type, 2, -1, force_path=text_encoder_folder)
        if get_local_model_filename(text_encoder_filename, extra_paths=text_encoder_folder) is None:
            raise Exception(f"Text encoder '{os.path.basename(text_encoder_filename)}' could not be located after download.")

    if not check_model_downloaded(model_type):
        raise Exception("Download finished but the checkpoint could not be located — check disk space and earlier terminal output.")
