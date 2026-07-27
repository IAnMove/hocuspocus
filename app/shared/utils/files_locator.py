from __future__ import annotations
import os

default_checkpoints_paths = ["ckpts", "."]
READ_ONLY_CHECKPOINTS_ENV = "MAESTRO_READ_ONLY_CHECKPOINTS"

_writable_checkpoints_paths = list(default_checkpoints_paths)
_read_only_checkpoints_paths = []
_checkpoints_paths = list(default_checkpoints_paths)


def _path_key(path):
    return os.path.normcase(os.path.realpath(os.path.abspath(os.path.expanduser(path))))


def _configured_read_only_paths():
    raw = os.environ.get(READ_ONLY_CHECKPOINTS_ENV, "")
    paths = []
    seen = set()
    for item in raw.split(os.pathsep):
        item = item.strip()
        if not item:
            continue
        expanded = os.path.abspath(os.path.expanduser(item))
        key = _path_key(expanded)
        if key in seen or not os.path.isdir(expanded):
            continue
        seen.add(key)
        paths.append(expanded)
    return paths


def set_checkpoints_paths(checkpoints_paths):
    """Configure writable roots plus optional lookup-only model libraries.

    WanGP historically treats every configured checkpoint root as writable:
    ``get_smart_download_root`` selects whichever root already contains a
    requested model family. Maestro Next also needs to reuse the stable
    installation's large checkpoint library without letting downloads,
    cleanup migrations, or resets modify it. Paths supplied through
    ``MAESTRO_READ_ONLY_CHECKPOINTS`` therefore participate in lookup only.
    """

    global _checkpoints_paths
    global _writable_checkpoints_paths
    global _read_only_checkpoints_paths

    configured = [
        os.fspath(path).strip()
        for path in (checkpoints_paths or [])
        if os.fspath(path).strip()
    ]
    if not configured:
        configured = list(default_checkpoints_paths)

    writable_keys = {_path_key(path) for path in configured}
    read_only = [
        path
        for path in _configured_read_only_paths()
        if _path_key(path) not in writable_keys
    ]

    _writable_checkpoints_paths = configured
    _read_only_checkpoints_paths = read_only
    _checkpoints_paths = configured + read_only


def get_read_only_checkpoints_paths():
    return list(_read_only_checkpoints_paths)


def is_read_only_path(path):
    if path is None:
        return False
    candidate = _path_key(os.fspath(path))
    for root in _read_only_checkpoints_paths:
        root_key = _path_key(root)
        try:
            if os.path.commonpath([candidate, root_key]) == root_key:
                return True
        except ValueError:
            # Different Windows drives cannot share a common path.
            continue
    return False


def assert_writable_path(path, operation="modify"):
    """Reject destructive operations against a lookup-only checkpoint root."""

    if is_read_only_path(path):
        raise PermissionError(
            f"Refusing to {operation} read-only checkpoint path: {path}"
        )
    return os.fspath(path)


def _redirect_read_only_destination(path):
    """Map an absolute destination inside a read-only root to the local root."""

    if path is None or not os.path.isabs(path) or not is_read_only_path(path):
        return path
    candidate = _path_key(path)
    for root in _read_only_checkpoints_paths:
        root_key = _path_key(root)
        try:
            relative = os.path.relpath(candidate, root_key)
        except ValueError:
            continue
        if relative == os.pardir or relative.startswith(os.pardir + os.sep):
            continue
        if relative == ".":
            return _writable_checkpoints_paths[0]
        return os.path.join(_writable_checkpoints_paths[0], relative)
    return path

def _normalize_force_path(force_path):
    if force_path is not None and isinstance(force_path, list) and len(force_path):
        force_path = force_path[0]
    if force_path is None:
        return None
    force_path = os.fspath(force_path).strip()
    if len(force_path) == 0:
        return None
    normalized = os.path.normpath(force_path)
    return None if normalized in ("", ".") else normalized

def get_download_location(file_name = None, force_path= None):
    if file_name is not None and os.path.isabs(file_name):
        return _redirect_read_only_destination(file_name)
    if force_path is not None and isinstance(force_path, list) and len(force_path): force_path = force_path[0]
    if file_name is not None:
        if force_path is None:
            return os.path.join(_writable_checkpoints_paths[0], file_name)
        else:
            return os.path.join(_writable_checkpoints_paths[0], force_path, file_name)
    else:
        if force_path is None:
            return _writable_checkpoints_paths[0]
        else:
            return os.path.join(_writable_checkpoints_paths[0])

def get_smart_download_root(force_path = None):
    force_path = _normalize_force_path(force_path)
    if force_path is None:
        return _writable_checkpoints_paths[0]
    if os.path.isabs(force_path):
        return _redirect_read_only_destination(force_path)
    for folder in _writable_checkpoints_paths:
        candidate = os.path.join(folder, force_path)
        if os.path.isdir(candidate):
            return folder
    return _writable_checkpoints_paths[0]

def get_smart_download_location(file_name = None, force_path = None):
    if file_name is not None and os.path.isabs(file_name):
        return _redirect_read_only_destination(file_name)
    force_path = _normalize_force_path(force_path)
    if force_path is None:
        return get_download_location(file_name)
    if os.path.isabs(force_path):
        force_path = _redirect_read_only_destination(force_path)
        return force_path if file_name is None else os.path.join(force_path, file_name)
    root = get_smart_download_root(force_path)
    base_path = os.path.join(root, force_path)
    return base_path if file_name is None else os.path.join(base_path, file_name)

def locate_folder(folder_name, error_if_none = True):
    searched_locations = []
    if os.path.isabs(folder_name):
        if os.path.isdir(folder_name): return folder_name
        searched_locations.append(folder_name)
    else:
        for folder in _checkpoints_paths:
            path = os.path.join(folder, folder_name)
            if os.path.isdir(path):
                return path
            searched_locations.append(os.path.abspath(path))
    if error_if_none: raise Exception(f"Unable to locate folder '{folder_name}', tried {searched_locations}")    
    return None


def locate_file(file_name, create_path_if_none = False, error_if_none = True, extra_paths = None):
    if file_name.startswith("http"):
        file_name = os.path.basename(file_name)
    searched_locations = []
    if os.path.isabs(file_name):
        if os.path.isfile(file_name): return file_name
        searched_locations.append(file_name)
    else:
        for folder in _checkpoints_paths + ([] if extra_paths is None else extra_paths):
            path = os.path.join(folder, file_name)
            if os.path.isfile(path):
                return path
            searched_locations.append(os.path.abspath(path))
    
    if create_path_if_none:
        return get_download_location(file_name)
    if error_if_none: raise Exception(f"Unable to locate file '{file_name}', tried {searched_locations}")
    return None
