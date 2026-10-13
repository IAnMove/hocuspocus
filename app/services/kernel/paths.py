"""Path containment shared by both servers and by services."""
from __future__ import annotations

import os


def safe_join(base: str, *parts: str) -> str | None:
    """Join `parts` under `base` and return the absolute path only if it
    stays inside `base`. Returns None on traversal attempts (`..`, absolute
    paths, symlinks escaping the base, etc.). Use for any endpoint that
    accepts a user-supplied filename."""
    try:
        base_real = os.path.realpath(base)
        joined = os.path.realpath(os.path.join(base_real, *parts))
        # commonpath compares path components rather than string prefixes.
        # normcase preserves correct behaviour on case-insensitive Windows
        # filesystems and ValueError handles paths on different drives.
        base_cmp = os.path.normcase(base_real)
        joined_cmp = os.path.normcase(joined)
        if os.path.commonpath((base_cmp, joined_cmp)) != base_cmp:
            return None
        return joined
    except (ValueError, OSError):
        return None
