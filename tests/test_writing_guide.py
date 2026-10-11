"""Writing coach contracts use fake providers. No model or media generation."""
import copy
import json
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.writing_guide import create_writing_guide_router
from services.writing_guide import (
    accepted_guidance, catalog, episode_guidance, parse_result, prepare_request, prompts, response_schema,
)
from services.series_library import (
    create_series_project, create_series_episode, import_story_project, normalize_series_project,
    series_canon_inputs_changed,
)
from services.story_library import write_story_library, read_story_library
from services.series_planning import planning_prompt, canon_preparation_prompt


def body(**changes):
    return {"scope": "character", "action": "develop", "language": "Español",
            "values": {"desire": "Recuperar su nave", "need": "Confiar", "flaw": "Controla a todos"},
            "context": {"project": {"premise": "Una capitana pierde su nave"}}, **changes}


def reply(**changes):
    return {"suggestions": [], "examples": [], "review": [], **changes}


def guide(sections):
    return {"version": 1, "sections": {key: {"notes": notes} for key, notes in sections.items()}}


@pytest.mark.parametrize("scope", catalog()["scopes"])
def test_every_scope_has_bilingual_questions_and_a_valid_response_schema(scope):
    request = prepare_request(body(scope=scope, values={}))
    schema = response_schema(request)
    assert set(schema["properties"]) == {"suggestions", "examples", "review"}
    for field in catalog()["scopes"][scope]:
        question = catalog()["questions"][field["id"]]
        assert all(question[k]["es"] and question[k]["en"] for k in ("question", "hint", "example"))


@pytest.mark.parametrize("change", [
    {"scope": "missing"}, {"scope": []}, {"action": "execute"}, {"values": {"assets": "x"}},
    {"values": {"desire": ["not text"]}}, {"values": {"desire": "x" * 6001}},
    {"context": {"huge": "x" * 24001}}, {"action": "examples", "questionId": "unknown"},
])
def test_invalid_requests_fail_before_provider_calls(change):
    with pytest.raises(ValueError):
        prepare_request(body(**change))


def test_fill_deterministically_protects_existing_answers_even_when_provider_ignores_prompt():
    request = prepare_request(body(action="fill"))
    result = parse_result(json.dumps(reply(suggestions=[
        {"field": "desire", "value": "Forget the ship", "reason": "wrong"},
        {"field": "arc", "value": "Aprende a delegar", "reason": "Resuelve su defecto"},
    ])), request)
    assert [row["field"] for row in result["suggestions"]] == ["arc"]
    prompt, system = prompts(request)
    assert "Recuperar su nave" in prompt and "Español" in prompt
    assert "creative decisions" in system


@pytest.mark.parametrize("result", [
    reply(suggestions=[{"field": "assets", "value": "write file", "reason": ""}]),
    reply(suggestions=[{"field": "arc", "value": 12, "reason": ""}]),
    reply(suggestions=[{"field": "arc", "value": "x", "reason": ""}] * 2),
    reply(examples=["x" * 6001]), reply(review=[{"field": "arc", "value": "wrong", "reason": ""}]),
])
def test_invalid_provider_results_are_never_applied(result):
    with pytest.raises(ValueError):
        parse_result(json.dumps(result), prepare_request(body()))


def test_examples_and_review_never_become_automatic_field_updates():
    request = prepare_request(body(action="examples", questionId="need"))
    result = parse_result(json.dumps(reply(examples=["Confiar", "Escuchar"],
        suggestions=[{"field": "need", "value": "new", "reason": ""}])), request)
    assert result["suggestions"] == [] and len(result["examples"]) == 2


def test_saved_answers_survive_story_round_trip_and_series_import(tmp_path):
    story = {"id": "s", "title": "Puerto", "writingGuide": guide({"story:root": {"goal": "Salvar la nave", "stakes": "La confianza"}}),
             "characters": [{"id": "captain", "conflict": "Su oficial quiere vender"}], "world": {"society": "Gobiernan acreedores"}}
    story["writingGuide"]["sections"]["story:root"]["pending"] = {"privateDraft": "No es canon"}
    write_story_library(str(tmp_path), {"projects": {"s": story}}, base_revision=0)
    saved = read_story_library(str(tmp_path))["projects"]["s"]
    assert saved["writingGuide"] == story["writingGuide"]
    imported = import_story_project(saved)
    assert imported["writingGuide"]["sections"]["series:root"]["notes"]["goal"] == "Salvar la nave"
    assert imported["writingGuide"]["sections"]["seriesCharacter:captain"]["notes"]["conflict"] == "Su oficial quiere vender"
    assert "privateDraft" not in json.dumps(accepted_guidance(saved))
    assert "privateDraft" not in json.dumps(imported)
    assert normalize_series_project(imported, imported["id"], "default")["writingGuide"] == imported["writingGuide"]


def test_episode_uses_frozen_decisions_and_only_its_own_live_notes():
    series = create_series_project("default")
    series["writingGuide"] = guide({"series:root": {"engine": "Rescatar y pagar deudas"}})
    episode = create_series_episode(series)
    series["writingGuide"]["sections"]["series:root"]["notes"]["engine"] = "Cambió después"
    series["writingGuide"]["sections"][f"episode:{episode['id']}"] = {"notes": {"goal": "Salvar el puerto"}}
    series["writingGuide"]["sections"]["episode:other"] = {"notes": {"goal": "NO FILTRAR"}}
    decisions = episode_guidance(series, episode)
    assert decisions["series:root"]["engine"] == "Rescatar y pagar deudas"
    assert decisions[f"episode:{episode['id']}"]["goal"] == "Salvar el puerto"
    prompt, _ = planning_prompt("outline", series, episode)
    assert "Salvar el puerto" in prompt and "NO FILTRAR" not in prompt
    assert "Rescatar y pagar deudas" in prompt
    assert "Cambió después" in canon_preparation_prompt(series)[0]
    legacy = {**episode, "canonSnapshot": {}}
    assert "series:root" not in episode_guidance(series, legacy)


def test_only_accepted_global_decisions_invalidate_series_canon():
    original = create_series_project("default")
    updated = copy.deepcopy(original)
    updated["writingGuide"] = guide({"series:root": {}})
    updated["writingGuide"]["sections"]["series:root"]["pending"] = {"examples": ["una idea"]}
    assert not series_canon_inputs_changed(original, updated)
    updated["writingGuide"]["sections"]["series:root"]["notes"]["engine"] = "Otro encargo"
    assert series_canon_inputs_changed(original, updated)


def test_router_uses_project_override_and_returns_unknown_usage_honestly():
    app = FastAPI()
    app.include_router(create_writing_guide_router(
        ensure_llm_loaded=lambda: pytest.fail("Must not load or change the global LLM"),
        writing_override=lambda _: {"model": "test-model", "base_url": "https://provider.invalid", "api_key": "test-only"},
    ))
    with patch("services.llm_service.generate_openai_compatible", return_value=json.dumps(reply())) as generate:
        response = TestClient(app).post("/api/v1/writing-guide/propose", json=body(writingProvider="openai-compatible"))
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["usage"] is None and result["model"] == "test-model"
    assert "test-only" not in response.text
    assert generate.call_count == 1
    assert generate.call_args.kwargs["cancellation_token"] is not None


def test_router_rejects_malformed_json_without_spending_a_repair_call():
    app = FastAPI()
    app.include_router(create_writing_guide_router(ensure_llm_loaded=lambda: None, writing_override=lambda _: None))
    with patch("services.llm_service.generate", return_value="not json") as generate:
        response = TestClient(app).post("/api/v1/writing-guide/propose", json=body())
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "invalidProposal"
    assert generate.call_count == 1


def test_router_returns_localizable_error_codes_without_exposing_provider_details():
    app = FastAPI()
    app.include_router(create_writing_guide_router(ensure_llm_loaded=lambda: None, writing_override=lambda _: None))
    client = TestClient(app)
    with patch("services.llm_service.generate", side_effect=RuntimeError("PRIVATE PROVIDER DETAIL")) as generate:
        invalid = client.post("/api/v1/writing-guide/propose", json=body(scope="unknown"))
        assert invalid.status_code == 400 and invalid.json()["detail"]["code"] == "invalidRequest"
        generate.assert_not_called()
        failed = client.post("/api/v1/writing-guide/propose", json=body())
    assert failed.status_code == 502 and failed.json()["detail"]["code"] == "providerFailed"
    assert "PRIVATE PROVIDER DETAIL" not in failed.text


def test_router_reports_provider_usage_without_estimating_from_text():
    from services import llm_service
    def simulated_provider(**_kwargs):
        llm_service._record_activity_usage({"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20})
        return json.dumps(reply())
    app = FastAPI()
    app.include_router(create_writing_guide_router(ensure_llm_loaded=lambda: None, writing_override=lambda _: None))
    with patch("services.llm_service.generate", side_effect=simulated_provider), patch("services.llm_service.get_status", return_value={"model_id": "fixture"}):
        response = TestClient(app).post("/api/v1/writing-guide/propose", json=body())
    assert response.status_code == 200
    assert response.json()["usage"] == {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20, "calls": 1}
