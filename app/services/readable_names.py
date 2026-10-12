"""Readable, file-safe names for what the server saves on someone's behalf.

An export or a published scene is found by its name in the gallery and the
Open dialogs. Names used to be cut to their first 40 characters, so a Series
shot export (``<series> · <episode> · e1s163``) lost the shot id that tells
the shots apart, and accented letters became dashes (``M-s-all``). These
helpers fold accents to ASCII and shorten the leading parts first.
"""
from __future__ import annotations

import re
import unicodedata

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
# " · ", " — ", " | ", " / " separate the parts of a composed name (series, episode, shot).
_PARTS = re.compile(r"\s+[·—|/]\s+|\s*·\s*")


def ascii_slug(text: object, limit: int = 80) -> str:
    """``Más allá del Plan`` -> ``Mas-alla-del-Plan``; '' when nothing is left."""
    folded = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode("ascii")
    return _UNSAFE.sub("-", folded).strip("-._")[:limit].strip("-._")


def keep_last_label(name: object, limit: int = 64) -> str:
    """A file label of a composed name that keeps its last part whole (a shot id) and shortens the others.

    ``Plus Ultra: Más allá del Plan · La confesión · e1s163`` ->
    ``Plus-Ultra-Mas-alla-del-Plan-La-confesion-e1s163``; when that is longer than ``limit``, each earlier part gets
    an equal share of the room the last one leaves."""
    parts = [slug for slug in (ascii_slug(part, limit) for part in _PARTS.split(str(name or ""))) if slug]
    if not parts:
        return ""
    last, head = parts[-1][:limit], parts[:-1]
    room = limit - len(last) - len(head)
    if not head or room <= 0:
        return last
    whole = "-".join(head)
    if len(whole) <= room:
        return f"{whole}-{last}"
    shares, left = [], room
    for index, part in enumerate(head):
        share = max(1, left // (len(head) - index))
        shares.append(part[:share].strip("-._") or part[:1])
        left -= len(shares[-1])
    return "-".join([*shares, last])


__all__ = ["ascii_slug", "keep_last_label"]
