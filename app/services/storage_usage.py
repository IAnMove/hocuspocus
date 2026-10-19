"""Storage usage analytics moved verbatim from the full server.

The report walks WanGP weight files, so only the full server calls
``configure``. The core server does not mount this route.
"""
from __future__ import annotations

import json
import os


def configure(
    *,
    engine,
    list_workspaces,
    model_weight_groups,
    variant_group_filenames,
    resolve_lora_root,
    linked_lora_roots,
) -> None:
    """Bind the full server's weight helpers. Names match the moved function."""
    global wgp, _list_workspaces, _model_weight_groups, _variant_group_filenames
    global _resolve_lora_root, _linked_lora_roots
    wgp = engine
    _list_workspaces = list_workspaces
    _model_weight_groups = model_weight_groups
    _variant_group_filenames = variant_group_filenames
    _resolve_lora_root = resolve_lora_root
    _linked_lora_roots = linked_lora_roots


def storage_usage():
    """Usage analytics backfilled from generation sidecars: every job ever
    run left a .meta.json with model_type, activated_loras, and created_at.
    Joined with on-disk sizes so 'largest, least used' is one sort away."""
    base = wgp.server_config.get("save_path", "outputs")
    scan_dirs = [w["path"] for w in _list_workspaces()]
    model_usage: dict = {}
    lora_usage: dict = {}
    sidecars = 0
    for d in scan_dirs:
        try:
            entries = os.listdir(d)
        except OSError:
            continue
        for n in entries:
            if not n.endswith(".meta.json"):
                continue
            try:
                with open(os.path.join(d, n), "r", encoding="utf-8") as f:
                    meta = json.load(f)
            except Exception:
                continue
            sidecars += 1
            params = meta.get("params") or {}
            created = meta.get("created_at") or 0
            mt = params.get("model_type")
            if mt:
                agg = model_usage.setdefault(mt, {"count": 0, "last_used": 0})
                agg["count"] += 1
                agg["last_used"] = max(agg["last_used"], created)
            for lora in params.get("activated_loras") or []:
                if isinstance(lora, str) and lora:
                    agg = lora_usage.setdefault(lora, {"count": 0, "last_used": 0})
                    agg["count"] += 1
                    agg["last_used"] = max(agg["last_used"], created)

    models = []
    # Shared weights (pointer-resolved base transformers, common text
    # encoders) appear in MANY models' groups — per-model sizes overlap by
    # design, so the dashboard's total comes from this global dedupe, not
    # from summing rows.
    global_seen = set()
    models_total_bytes = 0
    for mt in wgp.displayed_model_types:
        md = wgp.get_model_def(mt)
        if md is None:
            continue
        total = 0
        primary_bytes = 0
        seen_paths = set()
        try:
            for group in _model_weight_groups(mt):
                for fname in _variant_group_filenames(group):
                    p = wgp.fl.locate_file(fname, error_if_none=False)
                    if not p:
                        continue
                    key = os.path.normcase(os.path.abspath(p))
                    if key in seen_paths:
                        continue
                    seen_paths.add(key)
                    try:
                        size = os.path.getsize(p)
                    except OSError:
                        continue
                    total += size
                    if key not in global_seen:
                        global_seen.add(key)
                        models_total_bytes += size
            # What the row's Delete actually frees: DELETE /models/{mt}
            # removes owned files only (a finetune's alias never deletes
            # the shared base) — mirror that here or the button lies.
            for group in _model_weight_groups(mt, owned_only=True):
                for fname in _variant_group_filenames(group):
                    p = wgp.fl.locate_file(fname, error_if_none=False)
                    if p and not wgp.fl.is_protected_path(p):
                        try:
                            primary_bytes += os.path.getsize(p)
                        except OSError:
                            pass
        except Exception:
            pass
        usage = model_usage.get(mt, {})
        # Rows without deletable bytes need to say WHY: a finetune whose
        # def aliases another model's weights frees nothing when deleted
        # (delete the base row instead), and weights living only in
        # linked installs are read-only here.
        _raw_urls = md.get("URLs")
        _alias_of = None
        if isinstance(_raw_urls, str):
            _alias_md = wgp.get_model_def(_raw_urls)
            _alias_of = (_alias_md or {}).get("name", _raw_urls)
        models.append({
            "model_type": mt, "name": md.get("name", mt),
            "size_bytes": total, "primary_bytes": primary_bytes,
            "alias_of": _alias_of,
            "use_count": usage.get("count", 0),
            "last_used": usage.get("last_used") or None,
        })

    loras = []
    lora_root = _resolve_lora_root()
    walk_roots = ([(lora_root, False)] if lora_root else []) + [(r, True) for r in _linked_lora_roots()]
    seen_keys = set()
    for root, linked in walk_roots:
        for dirpath, _dn, fns in os.walk(root):
            for f in fns:
                if not f.endswith((".safetensors", ".sft")):
                    continue
                rel_dir = os.path.relpath(dirpath, root)
                key = os.path.normcase(os.path.normpath(os.path.join(rel_dir, f)))
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                try:
                    size = os.path.getsize(os.path.join(dirpath, f))
                except OSError:
                    size = 0
                usage = lora_usage.get(f, {})
                loras.append({
                    "filename": f, "directory": rel_dir, "linked": linked, "size_bytes": size,
                    "use_count": usage.get("count", 0),
                    "last_used": usage.get("last_used") or None,
                })

    workspaces = []
    for w in _list_workspaces():
        ws_bytes = 0
        try:
            with os.scandir(w["path"]) as it:
                for e in it:
                    if e.is_file() and not e.name.startswith("."):
                        try:
                            ws_bytes += e.stat().st_size
                        except OSError:
                            pass
        except OSError:
            pass
        workspaces.append({"name": w["name"], "file_count": w.get("file_count", 0), "size_bytes": ws_bytes})

    return {
        "models": sorted(models, key=lambda m: -m["size_bytes"]),
        "models_total_bytes": models_total_bytes,
        "loras": sorted(loras, key=lambda l: -l["size_bytes"]),
        "workspaces": workspaces,
        "scanned_sidecars": sidecars,
    }
