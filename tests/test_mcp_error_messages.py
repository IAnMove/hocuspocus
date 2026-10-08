"""Field errors name what was sent, and a script check groups repeated problems."""
from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from services.job_leftovers import command_catalog as leftovers_catalog
from services.job_leftovers import command_handlers
from services.durable_generation_queue import DurableGenerationQueue
from services.job_leftovers import JobLeftovers
from services.series_commands import _field_error, command_handlers as series_handlers
from services.series_script import ScriptError, apply_script
from services.series_script_problems import format_groups, group_problems
from services.world3d_template_catalog import World3DTemplateError, builtin_cards, page_templates, search_templates
from services.world3d_template_commands import execute_command


def _series_handlers():
    seen = []

    def opener(request, timeout=120):
        seen.append(request.full_url)

        class _Body:
            def read(self):
                return b'{"templates": []}'

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        return _Body()

    handlers = series_handlers(lambda: "http://127.0.0.1:9", lambda _workspace: "/tmp", lambda: "/tmp", opener=opener)
    return handlers, seen


def test_an_unexpected_series_field_names_the_allowed_ones():
    handlers, _seen = _series_handlers()
    with pytest.raises(HTTPException) as caught:
        asyncio.run(handlers["series.templates"]({"version": 1, "input": {"language": "es", "nope": 1}}))
    detail = caught.value.detail
    assert detail["message"] == "Unexpected field(s): nope. Allowed: language, workspace"
    assert detail["unexpected"] == ["nope"]
    assert detail["allowed"] == ["language", "workspace"]


def test_a_tool_with_no_fields_says_so():
    detail = _field_error(["workspace"], [])
    assert detail["message"] == "This tool takes no input fields"
    assert detail["unexpected"] == ["workspace"]
    assert detail["allowed"] == []


def test_series_templates_ignores_workspace():
    handlers, seen = _series_handlers()
    asyncio.run(handlers["series.templates"]({"version": 1, "input": {"workspace": "lab", "language": "es"}}))
    assert seen and "language=es" in seen[0]
    assert "workspace" not in seen[0]


def test_a_missing_required_field_still_names_the_required_list():
    handlers, _seen = _series_handlers()
    with pytest.raises(HTTPException) as caught:
        asyncio.run(handlers["series.list"]({"version": 1, "input": {}}))
    assert caught.value.detail["message"] == "Use version 1 with input fields: workspace"


def test_leftovers_accepts_workspace_and_names_an_unexpected_field(tmp_path):
    service = JobLeftovers(queue=DurableGenerationQueue(str(tmp_path / "queue.json")), jobs={})
    handlers = command_handlers(service)
    listed = handlers["jobs.leftovers"]({"version": 1, "input": {"workspace": "lab"}})
    assert listed["result"]["jobs"] == []
    description = next(item["description"] for item in leftovers_catalog() if item["name"] == "jobs.leftovers")
    assert "process-wide" in description
    with pytest.raises(HTTPException) as caught:
        handlers["jobs.leftovers"]({"version": 1, "input": {"job": 1}})
    detail = caught.value.detail
    assert detail["message"] == "Unexpected field(s): job. Allowed: workspace"
    assert detail["unexpected"] == ["job"]
    assert detail["allowed"] == ["workspace"]


def test_repeated_script_problems_become_a_few_groups():
    problems = [
        f"shot {index} (e1s{index:02d}): {name} has no Character Kit"
        for name in ("ana", "boa", "cio", "dina")
        for index in range(30)
    ]
    groups = group_problems(problems)
    assert len(problems) == 120
    assert len(groups) == 4
    assert [group["subject"] for group in groups] == ["ana", "boa", "cio", "dina"]
    assert groups[0]["code"] == "no_character_kit"
    assert len(groups[0]["shots"]) == 30
    message = format_groups(groups)
    assert "ana: no Character Kit (shots e1s00, e1s01 … 30 shots)" in message
    assert "(+" not in message
    error = ScriptError(problems)
    assert error.problems == problems
    assert str(error) == message


def test_groups_past_thirty_are_counted_and_the_problem_list_stays_whole():
    problems = [f"shot 0 (e1s00): unknown character person-{index}" for index in range(31)]
    message = format_groups(group_problems(problems))
    assert message.endswith("(+1 more groups)")
    assert "person-30" not in message
    assert ScriptError(problems).problems == problems


def test_a_script_with_no_kits_groups_one_character_across_shots():
    series = {
        "id": "lab", "revision": 1, "spokenLanguage": "es",
        "characters": [{"id": "pedro", "name": "Pedro", "voiceProfile": {}}],
        "locations": [{"id": "street", "variants": []}],
        "episodesById": {},
    }
    script = {
        "scenes": [{"id": "a", "location": "street"}],
        "shots": [{"scene": "a", "cast": [["pedro", "base"]], "lines": [{"who": "pedro", "es": "Hola."}]} for _ in range(14)],
    }
    with pytest.raises(ScriptError) as caught:
        apply_script(lambda *_args: {}, lambda: series, {}, set(), "lab", script, check_only=True)
    assert len(caught.value.problems) == 14
    assert caught.value.groups[0]["shots"][0] == "e1s00"
    assert str(caught.value) == "pedro: no Character Kit (shots e1s00, e1s01 … 14 shots)"


def test_template_list_pages_by_id_and_keeps_a_query_ranked():
    page = page_templates("")
    assert page["total"] == len(builtin_cards())
    assert len(page["templates"]) == 50
    assert [card["id"] for card in page["templates"]] == sorted(card["id"] for card in page["templates"])
    second = page_templates("", offset=50, limit=50)
    assert second["total"] == page["total"]
    assert set(card["id"] for card in page["templates"]).isdisjoint(card["id"] for card in second["templates"])
    queried = page_templates("dolly zoom", limit=3)
    assert [card["id"] for card in queried["templates"]] == [card["id"] for card in search_templates("dolly zoom", limit=3)]
    with pytest.raises(World3DTemplateError) as limited:
        page_templates("zoom", limit=201)
    assert limited.value.code == "invalid_limit"
    with pytest.raises(HTTPException) as empty:
        execute_command("world3d.templates.list", {"version": 1, "input": {}}, lambda _workspace: "/tmp")
    assert empty.value.detail["code"] == "invalid_workspace"
