"""The music-video coverage cycle and chorus sets, as editable treatment fields.

Clip i gets coverage line i % 6 and every chorus returns to the first
recurring set (PR #5). Both stay the default; the treatment can change the
cycle (``coverage``; ``[]`` means no coverage hint) and the chorus set
(``chorus_set``: ``first``, ``rotate`` through the sets, or ``free`` for the
planner to choose). The rule sentences that describe the defaults follow the
treatment so the plan never carries two rules that pull in opposite
directions.
"""

from __future__ import annotations

from typing import Any

# ui/src/features/director/treatmentDefaults.ts shows the same six lines.
COVERAGE_SEQUENCE = (
    "hero wide performance",
    "direct-to-camera medium performance",
    "beauty close-up",
    "moving profile coverage",
    "low-angle performance",
    "detail insert",
)
CHORUS_SET_MODES = ("first", "rotate", "free")
MAX_COVERAGE_LINES = 12


def treatment_coverage(raw: dict) -> list[str]:
    """The coverage cycle: missing → the default six; an empty list → no hint."""
    value = raw.get("coverage")
    if value is None:
        return list(COVERAGE_SEQUENCE)
    lines = value if isinstance(value, list) else str(value).split("\n")
    cleaned = [" ".join(str(line).split())[:160] for line in lines]
    return [line for line in cleaned if line][:MAX_COVERAGE_LINES]


def treatment_chorus_set(raw: dict) -> str:
    mode = str(raw.get("chorus_set") or "first").strip().lower()
    return mode if mode in CHORUS_SET_MODES else "first"


def treatment_coverage_fields(raw: dict) -> dict[str, Any]:
    """The ``coverage`` and ``chorus_set`` a normalized treatment carries.

    Only values that differ from the defaults are kept. A default treatment
    then stays byte-identical to the one before these fields existed: the
    planner prints the treatment as JSON in its system prompt, and a plan
    and a saved run store it. Readers use ``treatment_coverage`` and
    ``treatment_chorus_set``, which fill the defaults back in.
    """
    fields: dict[str, Any] = {}
    coverage = treatment_coverage(raw)
    if coverage != list(COVERAGE_SEQUENCE):
        fields["coverage"] = coverage
    chorus_set = treatment_chorus_set(raw)
    if chorus_set != "first":
        fields["chorus_set"] = chorus_set
    return fields


def recurring_set_for(section: str, index: int, sets: list[str], chorus_mode: str, nth_chorus: int) -> str:
    """The recurring set of one clip. Choruses: the first set, the sets in turn, or none."""
    if section == "chorus":
        if chorus_mode == "rotate":
            return sets[nth_chorus % len(sets)]
        return "" if chorus_mode == "free" else sets[0]
    if section == "bridge":
        return sets[-1]
    if len(sets) > 1:
        return sets[min(1 + (index % max(1, len(sets) - 1)), len(sets) - 1)]
    return sets[0]


def coverage_hint(coverage: dict) -> str:
    """The clip's planned role, set, coverage and section direction for the LLM.

    A chorus with ``chorus_set: "free"`` has no set and an empty coverage
    cycle gives no coverage; both are then left out.
    """
    parts = [f"Planned role: {coverage.get('scene_type', 'narrative')}"]
    recurring_set = coverage.get("recurring_set", "main set")
    if recurring_set:
        parts.append(f"recurring set: {recurring_set}")
    framing = coverage.get("coverage", "medium shot")
    if framing:
        parts.append(f"coverage: {framing}")
    parts.append(f"section direction: {coverage.get('section_rule', '')}")
    return " " + "; ".join(parts) + "."


# Sentences of music_video_treatment_rules.md that describe the default chorus
# set and coverage cycle, and what replaces them when the treatment changes.
CHORUS_RULE_SWAPS = {
    "rotate": (
        ("signature chorus set and one or two secondary sets", "recurring sets"),
        ("Choruses return to the signature setup at peak scale.",
         "Choruses rotate through the recurring sets at peak scale."),
    ),
    "free": (
        ("signature chorus set and one or two secondary sets", "recurring sets"),
        ("Choruses return to the signature setup at peak scale.",
         "Choruses peak in scale; choose each chorus setting freely."),
    ),
}
COVERAGE_RULE = (
    "and select one useful piece of coverage: hero wide, medium direct-to-camera,\n"
    "  beauty close-up, moving profile, low angle or detail insert."
)
CHORUS_RECURRENCE_LINE = {
    "first": "- Use controlled recurrence. Revisit the same chorus set, wardrobe and visual motif.",
    "rotate": "- Use controlled recurrence. Choruses rotate through the recurring sets; keep the wardrobe and visual motif.",
    "free": "- Use controlled recurrence of wardrobe and visual motif. Each chorus may use any setting.",
}
CHORUS_CONTINUITY_NOTE = {
    "first": "Controlled recurrence is intentional: choruses return to the signature setup",
    "rotate": "Controlled recurrence is intentional: choruses rotate through the recurring sets",
    "free": "Choruses choose their own settings; wardrobe and motif recur",
}


def treatment_rules_for(guide: str, treatment: dict[str, Any]) -> str:
    """The music-video treatment rules, matching the treatment's chorus set and coverage."""
    for old, new in CHORUS_RULE_SWAPS.get(treatment.get("chorus_set", "first"), ()):
        guide = guide.replace(old, new)
    cycle = list(treatment.get("coverage", COVERAGE_SEQUENCE))
    if cycle != list(COVERAGE_SEQUENCE):
        guide = guide.replace(
            COVERAGE_RULE,
            "and follow the clip's planned coverage." if cycle
            else "and select one useful piece of coverage.",
        )
    return guide
