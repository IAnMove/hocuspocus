"""The music-video runbook matches the production.run contract.

``production.review`` is named for the agent. This branch does not import it.
The combined branch will register it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = ROOT / "docs" / "agents" / "VIDEO_PRODUCTION_RUNBOOK.md"
# ``<id>.production.json`` is the saved state file, not an MCP tool.
TOOL_RE = re.compile(
    r"\b((?:production|scenes|montages|jobs)\.(?!json\b)[a-z0-9_]+(?:\.[a-z0-9_]+)*|audio\.analyze|generation\.[a-z0-9_]+(?:\.[a-z0-9_]+)*)\b"
)
# Not registered here. The combined branch will register it.
PENDING = "production.review"
SPEC_KEYS = frozenset({"title", "song", "style", "shots"})


def _text() -> str:
    return RUNBOOK.read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    marker = f"## {heading}\n"
    start = text.index(marker) + len(marker)
    end = text.find("\n## ", start)
    if end < 0:
        return text[start:]
    return text[start:end]


def _json_blocks(text: str) -> list[str]:
    return re.findall(r"```json\n(.*?)\n```", text, flags=re.DOTALL)


def _operation_names(group) -> set[str]:
    items = [group] if isinstance(group, dict) else group
    names = set()
    for item in items:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            names.add(item["name"])
    return names


def _catalog_groups() -> list:
    from routers.image_generation_commands import image_command_catalog
    from routers.studio_music_commands import music_command_catalog
    from services.montage_commands import command_catalog as montages
    from services.music_production import command_catalog as production
    from services.scene2d_export import command_catalog as scene_export
    from services.song_analysis import command_catalog as audio
    from services.video2d_edit import command_catalog as scene_edit

    groups = [
        production(),
        audio(),
        montages(),
        scene_edit(),
        scene_export(),
        image_command_catalog(),
        [music_command_catalog()],
    ]
    try:
        from services.jobs_wait import command_catalog as jobs_wait
    except ImportError:
        return groups
    groups.append(jobs_wait())
    return groups


def _known_commands() -> set[str]:
    known: set[str] = set()
    for group in _catalog_groups():
        known.update(_operation_names(group))
    return known


def test_fenced_json_examples_parse():
    blocks = _json_blocks(_text())
    assert blocks
    for block in blocks:
        json.loads(block)


def test_spec_example_keeps_title_song_style_shots():
    examples = [json.loads(block) for block in _json_blocks(_text())]
    specs = [item for item in examples if isinstance(item, dict) and SPEC_KEYS <= set(item)]
    assert specs


def test_runbook_names_review_and_production_plan():
    text = _text()
    assert PENDING in text
    assert "production.plan" in text
    assert "production.plan" in _known_commands()


def test_named_commands_exist_except_pending_review():
    named = set(TOOL_RE.findall(_text()))
    assert PENDING in named
    # production.review is not imported on this branch. The combined branch will register it.
    known = _known_commands()
    missing = sorted(name for name in named if name != PENDING and name not in known)
    assert missing == []


def test_agent_call_order_is_run_status_review_retake():
    order = _section(_text(), "Call order")
    expect = ("production.run", "production.status", "production.review", "production.run")
    cursor = 0
    for name in TOOL_RE.findall(order):
        if cursor < len(expect) and name == expect[cursor]:
            cursor += 1
    assert cursor == len(expect)
    assert "jobs.wait" in order
    assert "jobs.wait" in _known_commands()
    assert "Do not also call `montages.export`" in _text()


def test_review_contract_names_the_code_checks():
    section = _section(_text(), "production.review")
    for token in ("black_bars", "frozen_shot", "title_cut_off", "text_covers_face", "duplicate_people", "appearance_changed", "retake_keys"):
        assert token in section
    assert "not a language model looking at the contact sheet" in section
    assert "must not invent yes or no" in section
