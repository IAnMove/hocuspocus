"""Storage duplicate finder, moved verbatim from the full server.

The three routes stay registered in the full server, in their original order,
through ``app/routers/storage_tools.py``. ``bind`` is called once from the full
server after ``wgp`` and the LoRA roots exist, and stores those objects.
"""
from __future__ import annotations

import os

from fastapi import HTTPException, Request

# Filled by bind(). The LoRA roots are the full server's functions.
wgp = None
_resolve_lora_root = None
_linked_lora_roots = None


def bind(**names):
    """Store the full server's engine and LoRA-root functions. Keyword arguments only."""
    global wgp, _resolve_lora_root, _linked_lora_roots
    wgp = names["wgp"]
    _resolve_lora_root = names["_resolve_lora_root"]
    _linked_lora_roots = names["_linked_lora_roots"]


_STORAGE_WEIGHT_EXTS = (".safetensors", ".sft", ".gguf", ".pth", ".ckpt", ".pt", ".bin", ".onnx")
_STORAGE_MIN_DUP_BYTES = 10 * 1024 * 1024  # skip configs/tokenizers — reclaim noise


def _walk_sized(root: str) -> dict:
    """normcased relpath -> (abs_path, size) for weight files under root."""
    out: dict = {}
    root_abs = os.path.abspath(root)
    for dirpath, _dirnames, filenames in os.walk(root_abs):
        for f in filenames:
            if not f.lower().endswith(_STORAGE_WEIGHT_EXTS):
                continue
            full = os.path.join(dirpath, f)
            try:
                size = os.path.getsize(full)
            except OSError:
                continue
            out[os.path.normcase(os.path.relpath(full, root_abs))] = (full, size)
    return out


def _same_physical_file(a: str, b: str) -> bool:
    """True when two paths reference the same on-disk data: junctions and
    symlinks resolve via realpath; NTFS hardlinks (which realpath does NOT
    resolve) via matching (st_dev, st_ino)."""
    if os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b)):
        return True
    try:
        sa, sb = os.stat(a), os.stat(b)
        return sa.st_ino != 0 and (sa.st_dev, sa.st_ino) == (sb.st_dev, sb.st_ino)
    except OSError:
        return False


def _files_probably_identical(a: str, b: str, size: int) -> bool:
    """Sampled content comparison (1MB head/middle/tail) — same-size files
    can still be divergent weights (a retrained LoRA at the same rank is
    byte-size-identical), and reading multi-GB files fully is not viable
    per scan."""
    chunk = 1024 * 1024
    offsets = [0]
    if size > chunk * 3:
        offsets += [size // 2, max(0, size - chunk)]
    elif size > chunk:
        offsets.append(max(0, size - chunk))
    try:
        with open(a, "rb") as fa, open(b, "rb") as fb:
            for off in offsets:
                fa.seek(off)
                fb.seek(off)
                if fa.read(chunk) != fb.read(chunk):
                    return False
        return True
    except OSError:
        return False


def _storage_roots() -> dict:
    """Primary + linked roots for both file kinds, resolved once."""
    ckpt_roots = wgp.fl.get_checkpoints_paths()
    # The "." search root is the whole app folder — walking it would sweep
    # the entire repo; only the real primary (index 0) is the reclaim target.
    primary_ckpts = os.path.abspath(ckpt_roots[0]) if ckpt_roots else None
    linked_ckpts = [os.path.abspath(r) for r in ckpt_roots[1:] if wgp.fl.is_external_root(r)]
    lora_primary = _resolve_lora_root()
    return {
        "checkpoint": (primary_ckpts, linked_ckpts),
        "lora": (os.path.abspath(lora_primary) if lora_primary else None, _linked_lora_roots()),
    }

def storage_duplicates():
    """Primary-root files that also exist (same relative path AND size) in
    a linked install. Deleting the PRIMARY copy is pure reclaim — the
    files locator keeps resolving the linked copy afterwards. Same-path
    different-size pairs are conflicts, not duplicates: the primary copy
    currently shadows a divergent linked file and deleting it would
    silently change behavior."""
    duplicates = []
    conflicts = []
    shared_via_link = 0
    for kind, (primary_root, linked_roots) in _storage_roots().items():
        if not primary_root or not os.path.isdir(primary_root):
            continue
        primary_files = _walk_sized(primary_root)
        for linked_root in linked_roots:
            if not os.path.isdir(linked_root):
                continue
            linked_files = _walk_sized(linked_root)
            for rel, (ppath, psize) in primary_files.items():
                hit = linked_files.get(rel)
                if not hit:
                    continue
                lpath, lsize = hit
                if psize == lsize:
                    # Same physical data (junction, symlink, or hardlink)
                    # is zero reclaimable bytes — "deleting one copy"
                    # would delete the only copy.
                    if _same_physical_file(ppath, lpath):
                        shared_via_link += 1
                        continue
                # Both roots derive from <install>/app/<ckpts|loras>, so the
                # install name is two levels up from the ROOT (deriving it
                # from the file path mislabels subfoldered loras).
                row = {
                    "kind": kind, "filename": os.path.basename(ppath), "rel_path": rel,
                    "primary_path": ppath, "size_bytes": psize,
                    "linked_path": lpath, "linked_size_bytes": lsize,
                    "linked_install": os.path.basename(os.path.dirname(os.path.dirname(linked_root))),
                }
                if psize == lsize and psize >= _STORAGE_MIN_DUP_BYTES:
                    # Same size is not same content: a retrained LoRA at the
                    # same rank is byte-size-identical. Divergent pairs are
                    # conflicts (the primary is the one actually in use).
                    if _files_probably_identical(ppath, lpath, psize):
                        duplicates.append(row)
                    else:
                        conflicts.append(row)
                elif psize != lsize:
                    conflicts.append(row)
    # One primary file can match several linked installs — count it once,
    # keyed by PHYSICAL identity so a junctioned root can't double-list.
    seen = set()
    unique = []
    for d in duplicates:
        key = os.path.normcase(os.path.realpath(d["primary_path"]))
        if key not in seen:
            seen.add(key)
            unique.append(d)
    return {
        "duplicates": sorted(unique, key=lambda d: -d["size_bytes"]),
        "conflicts": conflicts,
        "shared_via_link": shared_via_link,
        "total_reclaimable_bytes": sum(d["size_bytes"] for d in unique),
    }


async def storage_reclaim(request: Request):
    """Delete ONE primary-root duplicate. Revalidates from scratch: the
    path must live under a primary root and a same-relpath same-size
    linked copy must exist right now — a stale scan result can't delete
    anything that isn't still redundant."""
    body = await request.json()
    path = body.get("path", "")
    if not path or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="File not found.")
    target = os.path.abspath(path)
    if wgp.fl.is_protected_path(target):
        raise HTTPException(status_code=403, detail="That file is in a linked install (read-only).")
    # All comparisons happen in realpath space: a junctioned primary root
    # (e.g. ckpts linked into another install to share storage) makes
    # abspath and physical location disagree, and a "linked copy" reached
    # through the junction is the SAME file — deleting the primary would
    # delete the only copy.
    target_real = os.path.realpath(target)
    try:
        psize = os.path.getsize(target_real)
    except OSError:
        raise HTTPException(status_code=404, detail="File not found.")
    matched = False
    for kind, (primary_root, linked_roots) in _storage_roots().items():
        if not primary_root:
            continue
        proot_real = os.path.realpath(primary_root)
        if not os.path.normcase(target_real).startswith(os.path.normcase(proot_real + os.sep)):
            continue
        rel_key = os.path.relpath(target_real, proot_real)
        for linked_root in linked_roots:
            candidate = os.path.join(linked_root, rel_key)
            try:
                if not os.path.isfile(candidate) or os.path.getsize(candidate) != psize:
                    continue
                # Same physical data (junction/symlink/hardlink) is not a
                # copy, and same size is not same content — a retrained
                # LoRA at the same rank is byte-size-identical.
                if _same_physical_file(candidate, target_real):
                    continue
                if not _files_probably_identical(target_real, candidate, psize):
                    continue
                matched = candidate
                break
            except OSError:
                continue
        break
    if not matched:
        raise HTTPException(status_code=409, detail="No identical linked copy exists (anymore) — refusing to delete the only copy.")
    from services.win_safe_files import safe_delete
    result = safe_delete(target)
    if not result.get("deleted"):
        raise HTTPException(status_code=423, detail="The file is locked by another process. Try again in a moment.")
    # Audit line names the exact surviving copy — if it ever turns out to
    # be gone afterwards, this line is the forensic anchor.
    print(f"[Storage] Reclaimed duplicate: {target} ({psize} bytes; surviving copy: {matched})")
    if not os.path.isfile(matched):
        print(f"[Storage] CRITICAL: surviving copy vanished immediately after reclaim: {matched}")
    return {"status": "ok", "freed_bytes": psize, "deferred": bool(result.get("deferred")), "surviving_copy": matched}


async def storage_remove_linked(request: Request):
    """The inverse of reclaim: keep Maestro's copy, remove the LINKED
    install's duplicate — to the Recycle Bin, never a hard delete.

    Gated on the opt-in services.storage_allow_linked_removal flag:
    deleting from another install is the one sanctioned exception to the
    is_protected_path rule, and only with an identical different-physical
    copy verified in Maestro's primary root at this exact moment."""
    services = wgp.server_config.get("services", {})
    if not services.get("storage_allow_linked_removal", False):
        raise HTTPException(status_code=403, detail="Removing files from linked installs is disabled. Enable it in the Storage Manager first.")
    body = await request.json()
    path = body.get("path", "")
    if not path or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="File not found.")
    target = os.path.abspath(path)
    if not wgp.fl.is_protected_path(target):
        raise HTTPException(status_code=400, detail="That file is not in a linked install — use Reclaim for HocusPocus Lab's own copies.")
    target_real = os.path.realpath(target)
    try:
        psize = os.path.getsize(target_real)
    except OSError:
        raise HTTPException(status_code=404, detail="File not found.")
    surviving = None
    for kind, (primary_root, linked_roots) in _storage_roots().items():
        if not primary_root:
            continue
        for linked_root in linked_roots:
            lroot_real = os.path.realpath(linked_root)
            if not os.path.normcase(target_real).startswith(os.path.normcase(lroot_real + os.sep)):
                continue
            rel_key = os.path.relpath(target_real, lroot_real)
            candidate = os.path.join(primary_root, rel_key)
            try:
                if not os.path.isfile(candidate) or os.path.getsize(candidate) != psize:
                    continue
                if _same_physical_file(candidate, target_real):
                    continue
                if not _files_probably_identical(target_real, candidate, psize):
                    continue
                surviving = os.path.abspath(candidate)
                break
            except OSError:
                continue
        if surviving:
            break
    if not surviving:
        raise HTTPException(status_code=409, detail="HocusPocus Lab does not hold an identical copy of that file — refusing to remove the linked install's only version.")
    from services.win_safe_files import recycle_file
    if not recycle_file(target):
        raise HTTPException(status_code=423, detail="Could not move the file to the Recycle Bin (it may be locked, or too large for the Bin). Nothing was deleted.")
    print(f"[Storage] Removed linked duplicate to Recycle Bin: {target} ({psize} bytes; HocusPocus Lab's copy: {surviving})")
    return {"status": "ok", "freed_bytes": psize, "recycled": True, "surviving_copy": surviving}

