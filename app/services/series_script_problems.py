"""Group a script check's repeated lines so an agent can read them.

``detail.problems`` stays the original list. The exception message lists one
line per ``(code, subject)`` and stops after 30 groups.
"""
from __future__ import annotations

import re

_PREFIX = re.compile(
    r"^(?P<prefix>shot \d+ \((?P<shot>e\d+s\d+)\)[^:]*|scene (?P<scene>\S+)):\s*(?P<body>.*)$"
)
_RULES = (
    ("unknown_character", re.compile(r"^unknown character (.+)$"), "unknown character"),
    ("no_character_kit", re.compile(r"^(.+) has no Character Kit$"), "no Character Kit"),
    ("no_pose", re.compile(r"^(.+) has no pose (\S+)"), "no pose"),
    ("unknown_location", re.compile(r"^unknown location (.+)$"), "unknown location"),
    ("no_variant", re.compile(r"^location (.+) has no variant"), "no variant"),
    ("missing_file", re.compile(r"^file (.+) is not in the workspace$"), "file is not in the workspace"),
    ("unknown_scene", re.compile(r"^unknown scene (.+)$"), "unknown scene"),
    ("unknown_speaker", re.compile(r"^line \d+ has an unknown speaker (.+)$"), "unknown speaker"),
    ("no_voice", re.compile(r"^(.+) has no \w+ voice"), "no voice"),
    ("bad_framing", re.compile(r"^framing must be"), "framing is not allowed"),
    ("bad_kind", re.compile(r"^kind must be"), "kind is not allowed"),
    ("bad_voice_room", re.compile(r"^voiceRoom must be|^line \d+ voiceRoom must be"), "voiceRoom is not allowed"),
    ("no_shots", re.compile(r"^the script has no shots$"), "the script has no shots"),
)
_GROUP_LIMIT = 30
_SHOTS_LISTED = 2


def group_problems(problems: list[str]) -> list[dict]:
    """One group per code and subject, in the order the first line appeared."""
    order: list[tuple[str, str]] = []
    buckets: dict[tuple[str, str], dict] = {}
    for raw in problems:
        parsed = _parse(str(raw))
        key = (parsed["code"], parsed["subject"])
        bucket = buckets.get(key)
        if bucket is None:
            bucket = {**parsed, "shots": [], "raws": []}
            buckets[key] = bucket
            order.append(key)
        bucket["raws"].append(str(raw))
        shot = parsed["shot"]
        if shot and shot not in bucket["shots"]:
            bucket["shots"].append(shot)
    return [_group(buckets[key]) for key in order]


def format_groups(groups: list[dict]) -> str:
    """The message an agent reads. Groups past 30 are counted, not dropped from ``problems``."""
    shown = [str(group.get("message") or "") for group in groups[:_GROUP_LIMIT]]
    extra = len(groups) - _GROUP_LIMIT
    if extra > 0:
        shown.append(f"(+{extra} more groups)")
    return "; ".join(item for item in shown if item)


def _parse(raw: str) -> dict:
    match = _PREFIX.match(raw)
    body = match.group("body") if match else raw
    shot = match.group("shot") if match else ""
    code, subject, phrase = _classify(body)
    return {"code": code, "subject": subject, "phrase": phrase, "shot": shot or "", "body": body}


def _classify(body: str) -> tuple[str, str, str]:
    for code, pattern, phrase in _RULES:
        found = pattern.match(body)
        if found is None:
            continue
        subject = found.group(1) if found.groups() else ""
        return code, subject, phrase
    return "problem", "", body


def _group(bucket: dict) -> dict:
    shots = list(bucket["shots"])
    raws = bucket["raws"]
    message = raws[0] if len(raws) == 1 else _many(bucket["subject"], bucket["phrase"], shots)
    return {"code": bucket["code"], "subject": bucket["subject"], "shots": shots, "message": message}


def _many(subject: str, phrase: str, shots: list[str]) -> str:
    who = f"{subject}: " if subject else ""
    if not shots:
        return f"{who}{phrase}"
    if len(shots) <= 6:
        listed = ", ".join(shots)
    else:
        listed = f"{', '.join(shots[:_SHOTS_LISTED])} … {len(shots)} shots"
    return f"{who}{phrase} (shots {listed})"
