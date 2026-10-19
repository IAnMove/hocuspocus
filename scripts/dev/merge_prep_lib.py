"""Pure resolvers for the merge chores that recur in every PR.

Text and JSON in, text and JSON out. No git and no pytest.
"""

from __future__ import annotations

import copy
import re


class BalanceError(ValueError):
    """The shard file-count gap or the weight ratio is over the CI limit."""


def _paragraphs(text: str) -> list[str]:
    stripped = text.strip()
    if not stripped:
        return []
    parts = re.split(r"\n[ \t]*\n", stripped)
    return [part.strip() for part in parts if part.strip()]


def _join(parts: list[str]) -> str:
    if not parts:
        return ""
    return "\n\n".join(parts) + "\n"


def resolve_changelog(ours: str, theirs: str) -> str:
    """Keep the branch paragraphs first, then the ref paragraphs that are new.

    A paragraph that already appears on the branch is not repeated. New ref
    paragraphs are inserted after the branch paragraphs that share the same
    preceding paragraph, before the next paragraph both sides already have.
    """
    own = _paragraphs(ours)
    other = _paragraphs(theirs)
    if not own:
        return _join(other)
    if not other:
        return _join(own)
    own_index: dict[str, int] = {}
    for index, paragraph in enumerate(own):
        own_index.setdefault(paragraph, index)
    other_keys = set(other)
    insertions: dict[int, list[str]] = {}
    seen = set(own)
    last_shared = -1
    for paragraph in other:
        if paragraph in own_index:
            last_shared = own_index[paragraph]
            continue
        if paragraph in seen:
            continue
        seen.add(paragraph)
        insert_after = last_shared
        cursor = last_shared + 1
        while cursor < len(own) and own[cursor] not in other_keys:
            insert_after = cursor
            cursor += 1
        insertions.setdefault(insert_after, []).append(paragraph)
    merged: list[str] = []
    merged.extend(insertions.get(-1, []))
    for index, paragraph in enumerate(own):
        merged.append(paragraph)
        merged.extend(insertions.get(index, []))
    return _join(merged)


def _group_map(manifest: dict) -> dict[str, dict]:
    return {group["id"]: group for group in manifest["groups"]}


def _added_paths(base: dict, ours: dict) -> list[tuple[str, str]]:
    """Paths the branch added, in the branch's group order."""
    present = {path for group in base["groups"] for path in group["paths"]}
    added: list[tuple[str, str]] = []
    for group in ours["groups"]:
        for path in group["paths"]:
            if path not in present:
                added.append((path, group["id"]))
    return added


def _smaller_group(groups: dict[str, dict]) -> str:
    return min(groups, key=lambda group_id: (len(groups[group_id]["paths"]), group_id))


def resolve_test_groups(base: dict, ours: dict, theirs: dict, new_test_files: list[str]) -> dict:
    """Take the ref manifest and append the test files this branch added.

    Existing ref entries stay in their order. A new test file the branch did
    not assign goes to the group with fewer paths. Path rules whose prefix the
    ref does not have are appended in the branch's order.
    """
    result = copy.deepcopy(theirs)
    groups = _group_map(result)
    present = {path for group in result["groups"] for path in group["paths"]}
    queued = _added_paths(base, ours)
    known = {path for path, _group in queued}
    ours_groups = _group_map(ours)
    ours_path_group = {
        path: group["id"]
        for group in ours["groups"]
        for path in group["paths"]
    }
    for path in new_test_files:
        if path in known:
            continue
        group_id = ours_path_group.get(path) or _smaller_group(groups)
        queued.append((path, group_id))
        known.add(path)
    for path, group_id in queued:
        if path in present:
            continue
        if group_id not in groups:
            raise ValueError(f"group {group_id} is not in the ref manifest; cannot re-add {path}")
        groups[group_id]["paths"].append(path)
        present.add(path)
    have = {rule.get("prefix") for rule in result.get("path_rules") or []}
    for rule in ours.get("path_rules") or []:
        prefix = rule.get("prefix")
        if prefix in have:
            continue
        result.setdefault("path_rules", []).append(copy.deepcopy(rule))
        have.add(prefix)
    # ours_groups is read so a typo in the branch manifest fails here, not later.
    if not ours_groups:
        raise ValueError("branch manifest has no groups")
    return result


def apply_weights(manifest: dict, weights: dict[str, int], sentence: str) -> dict:
    """Set both group weights, append the note once, and enforce the CI limits.

    The file-count gap may not exceed 5. The weight ratio may not exceed 1.25.
    ``weights`` is supplied by the caller (pytest --collect-only, or a stub).
    """
    result = copy.deepcopy(manifest)
    counts: list[int] = []
    values: list[int] = []
    for group in result["groups"]:
        group_id = group["id"]
        if group_id not in weights:
            raise BalanceError(f"missing weight for {group_id}")
        weight = int(weights[group_id])
        if weight <= 0:
            raise BalanceError(f"non-positive weight for {group_id}: {weight}")
        group["weight"] = weight
        counts.append(len(group["paths"]))
        values.append(weight)
    if len(counts) != 2:
        raise BalanceError(f"expected two groups, found {len(counts)}")
    gap = abs(counts[0] - counts[1])
    if gap > 5:
        raise BalanceError(
            f"file-count gap {gap} exceeds 5 ({counts[0]} vs {counts[1]})"
        )
    ratio = max(values) / min(values)
    if ratio > 1.25:
        raise BalanceError(
            f"weight ratio {ratio:.3f} exceeds 1.25 ({values[0]} vs {values[1]})"
        )
    note = str(result.get("weight_note") or "").rstrip()
    extra = sentence.strip()
    if extra and extra not in note:
        result["weight_note"] = (note + " " + extra).strip()
    return result


def format_merge_summary(rows: list[str]) -> str:
    """At most 15 non-empty lines."""
    kept = [row.strip() for row in rows if row and row.strip()][:15]
    if not kept:
        return ""
    return "\n".join(kept) + "\n"
