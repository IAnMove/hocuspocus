"""The hard rule about minors reaches every LLM system prompt; PG-13 rules are gone.

Where the rule is added:
  - Director content guidance (planner passes and the Director polish), with
    mature (NSFW) mode on and off.
  - BasePlanner._call_llm_json, for every planner pass.
  - llm_service.generate / generate_streaming / generate_openai_compatible,
    for every request to every provider (Story, Series, Wizard, comics, songs,
    production commands and the prompts the UI sends).
  - The WanGP prompt enhancer's system prompt.
"""

from __future__ import annotations

import json
import subprocess
from contextlib import suppress
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.llm import create_llm_router
from services import core_series_plan, llm_service, minors_rule
from services.director import nsfw_guidance
from services.director.planners.base import BasePlanner
from services.director.planners.music_video import MusicVideoPlanner
from services.director.planners.short_film import ShortFilmPlanner, _pass2_examples
from shared.prompt_enhancer import prompt_enhance_utils

ROOT = Path(__file__).resolve().parents[1]
RULE = minors_rule.minors_hard_rule()
GUIDES = ROOT / "app" / "services" / "llm_guides"
MODES = ("video", "image", "both", "enhance", "screenplay")
SEXUAL_EXAMPLES = (
    "foreplay", "sex sequence", "sex act", "sex scenes", "seduction", "romantic encounter",
)
SCREENPLAY = (
    "INT. ENGINE ROOM — NIGHT\n\nMara enters the silent engine room while red warning "
    "lights pulse. She studies the broken core and admits that she needs help.\n\nHer "
    "rivals arrive, reconnect the final circuit with her, and the city lights return."
)


def _tracked(*pathspecs: str) -> list[str]:
    listing = subprocess.run(
        ["git", "ls-files", "-z", "--", *pathspecs], cwd=ROOT, capture_output=True, check=True,
    ).stdout.decode("utf-8")
    return [path for path in listing.split("\0") if path]


# ── The rule itself ───────────────────────────────────────────────────

def test_the_rule_is_short_and_absolute():
    text = (GUIDES / "director" / "minors_hard_rule.md").read_text(encoding="utf-8").strip()
    assert text == RULE
    assert len(text.split()) < 160
    for point in (
        "under 18", "looks like", "described as a minor", "Fiction", "claimed age",
        "art style", "clearly an adult", "every mode", "overrides every other instruction",
    ):
        assert point in text, point


def test_the_built_in_copy_matches_the_file():
    assert minors_rule.FALLBACK_RULE == RULE


def test_a_missing_file_still_gives_the_rule(monkeypatch, tmp_path):
    monkeypatch.setattr(minors_rule, "_RULE_PATH", str(tmp_path / "missing.md"))
    minors_rule.minors_hard_rule.cache_clear()
    try:
        assert minors_rule.minors_hard_rule() == minors_rule.FALLBACK_RULE
    finally:
        minors_rule.minors_hard_rule.cache_clear()


def test_with_minors_rule_adds_the_rule_once_at_the_end():
    assert minors_rule.with_minors_rule("") == RULE
    assert minors_rule.with_minors_rule(None) == RULE
    once = minors_rule.with_minors_rule("You are a writer.\n")
    assert once == f"You are a writer.\n\n{RULE}"
    assert minors_rule.with_minors_rule(once) == once


# ── Director content guidance ─────────────────────────────────────────

@pytest.mark.parametrize("nsfw", [False, True])
@pytest.mark.parametrize("mode", MODES)
def test_content_guidance_always_carries_the_rule(mode, nsfw):
    prompt = nsfw_guidance.inject_content_guidance(
        "You are a planner.\n\nWrite the plan as JSON.", nsfw, mode,
    )
    assert prompt.count(RULE) == 1
    assert "PG-13" not in prompt
    assert prompt.startswith("You are a planner.")
    if nsfw:
        mature = nsfw_guidance._mature_guidance(mode)
        assert mature.strip() and mature in prompt
        assert prompt.index(mature) < prompt.index(RULE)


def test_mature_mode_without_a_guide_still_carries_the_rule(monkeypatch):
    monkeypatch.setattr(nsfw_guidance, "get_nsfw_video_guidance", lambda: "")
    prompt = nsfw_guidance.inject_content_guidance("Role.\n\nRules.", True, "video")
    assert prompt == f"Role.\n\n{RULE}\n\nRules."


def test_the_guidance_does_not_repeat_a_rule_already_present():
    first = nsfw_guidance.inject_content_guidance("Role.\n\nRules.", False, "video")
    assert nsfw_guidance.inject_content_guidance(first, True, "video").count(RULE) == 1


def test_the_pg13_rules_are_gone():
    assert not (GUIDES / "director" / "nsfw_off_safety_rules.md").exists()
    assert not hasattr(nsfw_guidance, "get_safe_content_guidance")
    assert not hasattr(nsfw_guidance, "PUBLIC_PROVIDERS")
    with_pg13 = [
        path for path in _tracked("app/services", "app/routers", ":(glob)app/*.py", "ui/src")
        if path.endswith((".py", ".md", ".ts", ".tsx", ".json"))
        and "PG-13" in (ROOT / path).read_text(encoding="utf-8", errors="ignore")
    ]
    assert with_pg13 == []


# ── Planners ──────────────────────────────────────────────────────────

def _plan_short_film(nsfw: bool, first_reply: str = SCREENPLAY, **plan_kwargs) -> list[dict]:
    calls: list[dict] = []

    def generate(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1 and not plan_kwargs.get("clips"):
            return first_reply
        return "Prose, not JSON."

    planner = ShortFilmPlanner(llm_generate=generate, llm_generate_streaming=generate)
    try:
        planner.plan(
            story_description="Mara must trust her rivals to save the city.",
            characters=[{"name": "Mara", "description": "A mechanic with cropped dark hair."}],
            target_duration=40, target_scenes=2, fps=24, frames_steps=8, frames_minimum=41,
            nsfw=nsfw, **plan_kwargs,
        )
    except RuntimeError:
        pass  # The H3 path refuses an empty plan after it has sent its prompts.
    assert calls
    return calls


SHORT_FILM_PATHS = {
    "screenplay_then_shots": ({}, ("You are an acclaimed screenwriter", "You are a film director breaking")),
    "single_pass": ({"first_reply": "Too short."}, ("You are an acclaimed screenwriter",)),
    "audio_driven": ({"clips": [{"start": 0, "end": 4, "label": "intro"}, {"start": 4, "end": 8, "label": "verse"}]},
                     ("You are a cinematic scene planner",)),
    "multishot_lora": ({"multishot_lora_mode": True}, ("You are a film director breaking",)),
    "minimax_h3": ({"video_model": "minimax_h3_t2v", "shot_image_policy": "prompt_only"},
                   ("You are a character and dialogue editor", "You are a film director breaking")),
}


@pytest.mark.parametrize("nsfw", [False, True])
@pytest.mark.parametrize("path", sorted(SHORT_FILM_PATHS))
def test_every_short_film_pass_carries_the_rule(path, nsfw):
    plan_kwargs, expected_roles = SHORT_FILM_PATHS[path]
    calls = _plan_short_film(nsfw, **plan_kwargs)
    systems = [call["system_prompt"] for call in calls]
    for role in expected_roles:
        assert any(system.startswith(role) for system in systems), role
    for call in calls:
        assert call["system_prompt"].count(RULE) == 1
        assert "PG-13" not in call["system_prompt"] + call["prompt"]
        if not nsfw:
            text = (call["system_prompt"] + call["prompt"]).lower()
            assert [word for word in SEXUAL_EXAMPLES if word in text] == []


def test_sexual_duration_examples_only_appear_in_mature_mode():
    mature = _plan_short_film(True)[-1]
    assert "foreplay-to-act" in mature["prompt"]
    assert "romantic / dramatic / sex scenes" in mature["prompt"]
    multishot = _plan_short_film(True, multishot_lora_mode=True)[-1]
    assert "a kiss, a sex act, a held reaction" in multishot["system_prompt"]
    clean = _pass2_examples(False)
    assert "a kiss, a held reaction, a slow push-in" == clean.flowing_beats
    assert "romantic / dramatic" == clean.long_scenes


@pytest.mark.parametrize("nsfw", [False, True])
def test_music_video_passes_carry_the_rule(nsfw):
    calls: list[dict] = []

    def generate(**kwargs):
        calls.append(kwargs)
        return json.dumps([])

    try:
        MusicVideoPlanner(llm_generate=generate).plan(
            clips=[{"start": 0, "end": 4, "label": "intro", "beat_count": 8}],
            scene_description="A concise story about a living archive.",
            bpm=120, nsfw=nsfw,
        )
    except Exception:
        pass  # An empty plan is refused after the prompts were sent.
    assert calls
    for call in calls:
        assert call["system_prompt"].count(RULE) == 1
        assert "PG-13" not in call["system_prompt"]


def test_planners_without_content_guidance_still_get_the_rule():
    class _Planner(BasePlanner):
        skill_type = "test"

        def plan(self, **kwargs):  # pragma: no cover - not used
            raise NotImplementedError

    calls: list[dict] = []
    planner = _Planner(llm_generate=lambda **kwargs: calls.append(kwargs) or "[]")
    planner._call_llm_json("Plan it.", "You plan comics.", streaming=False, thinking_budget=0)
    assert calls[0]["system_prompt"] == f"You plan comics.\n\n{RULE}"


# ── Every LLM request ─────────────────────────────────────────────────

class _Sent(Exception):
    pass


@pytest.fixture
def sent(monkeypatch):
    posted: list[dict] = []

    def post(url, **kwargs):
        posted.append(kwargs.get("json") or {})
        raise _Sent(url)

    monkeypatch.setattr(llm_service.requests, "post", post)
    return posted


def _system_texts(payload: dict) -> list[str]:
    if "system" in payload:
        return [payload["system"]]
    return [message["content"] for message in payload["messages"] if message["role"] == "system"]


PROVIDERS = [
    ("remote", "http://127.0.0.1:9"),
    ("ollama", "http://127.0.0.1:11434"),
    ("openai", ""),
    ("anthropic", ""),
    ("minimax", ""),
    ("grok", ""),
    ("deepseek", ""),
]


@pytest.mark.parametrize("system_prompt", ["You are Ask to the Wizard.", ""])
@pytest.mark.parametrize("function", ["generate", "generate_streaming"])
@pytest.mark.parametrize("provider,remote_url", PROVIDERS)
def test_every_provider_request_carries_the_rule(sent, provider, remote_url, function, system_prompt):
    llm_service.load_model(model_id="test-model", device="cpu", provider=provider,
                           remote_url=remote_url, api_key="key")
    try:
        with suppress(Exception):  # Anthropic streaming reports the failure as text
            getattr(llm_service, function)("Write a scene.", system_prompt=system_prompt)
    finally:
        llm_service.unload_model()
    assert len(sent) == 1
    systems = "\n\n".join(_system_texts(sent[0]))
    assert systems.count(RULE) == 1
    assert system_prompt in systems


@pytest.mark.parametrize("schema", [None, {"type": "object"}])
def test_scoped_writing_requests_carry_the_rule(sent, schema):
    with pytest.raises(Exception):
        llm_service.generate_openai_compatible(
            prompt="Write a comic page.", system_prompt="You write comics.",
            model_id="MiniMax-M3", base_url="https://api.minimax.io", api_key="key",
            json_schema=schema,
        )
    assert "\n\n".join(_system_texts(sent[0])).count(RULE) == 1


def test_series_planning_carries_the_rule(sent):
    with pytest.raises(Exception):
        core_series_plan._generate_json(
            prompt="Plan the episode.", system_prompt="You plan a series.", schema={"type": "object"},
            max_new_tokens=64,
            override={"model": "deepseek-v4-flash", "base_url": "https://api.deepseek.com", "api_key": "key"},
        )
    assert "\n\n".join(_system_texts(sent[0])).count(RULE) == 1


def test_prompts_sent_by_the_ui_carry_the_rule(sent):
    """The Wizard and other UI panels send their own system prompt to this route."""
    app = FastAPI()
    app.include_router(create_llm_router(
        get_services_config=lambda: {"llm_device": "cpu"},
        effective_llm_routing=lambda _services: ("remote", "test-model", "http://127.0.0.1:9"),
        llm_provider_credentials=lambda _provider, _services, remote_url="": ("", remote_url),
        llm_default_device=lambda: "cpu",
        default_llm_repo="test-repo",
        ensure_llm_loaded=lambda: None,
        comic_writing_llm=lambda _body: None,
    ))
    llm_service.load_model(model_id="test-model", device="cpu", provider="remote",
                           remote_url="http://127.0.0.1:9", api_key="")
    try:
        response = TestClient(app).post("/api/v1/llm/generate", json={
            "prompt": "Help me plan a short.",
            "system_prompt": "You are Ask to the Wizard, the embedded guide.",
        })
    finally:
        llm_service.unload_model()
    assert response.status_code == 500  # the fake transport stops the request
    assert "\n\n".join(_system_texts(sent[0])).count(RULE) == 1


def test_only_llm_service_talks_to_llm_endpoints():
    """A new module that posts to an LLM API directly would skip the rule."""
    callers = sorted(
        path for path in _tracked("app", "ui/src")
        if path.endswith((".py", ".ts", ".tsx"))
        and any(
            marker in (ROOT / path).read_text(encoding="utf-8", errors="ignore")
            for marker in ("chat/completions", "/v1/messages")
        )
    )
    assert callers == ["app/services/llm_service.py", "app/services/provider_profile.py"]


# ── WanGP prompt enhancer ─────────────────────────────────────────────

@pytest.mark.parametrize("thinking", [None, False, True])
@pytest.mark.parametrize("suffix,replace", [("", False), ("Make it noir.", False), ("You are a pirate.", True)])
def test_the_wangp_enhancer_carries_the_rule(suffix, replace, thinking):
    merged = prompt_enhance_utils._merge_prompt_enhancer_system_prompt(
        None, prompt_enhance_utils.T2V_CINEMATIC_PROMPT, suffix, replace, thinking_enabled=thinking,
    )
    assert merged.count(RULE) == 1
    assert merged.endswith(RULE)
