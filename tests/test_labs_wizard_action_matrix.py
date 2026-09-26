"""L0 freeze: Labs ↔ Wizard action matrix.

No functional change. Do not treat a documented defect as the desired
behaviour. H3 prompt bytes stay in h3_prompt_fase1_expected.json.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "labs_wizard_action_matrix.json"
H3_FIXTURE = ROOT / "tests" / "fixtures" / "h3_prompt_fase1_expected.json"
MATRIX_DOC = ROOT / "docs" / "development" / "LABS_WIZARD_ACTION_MATRIX.md"

REQUIRED_FIELDS = (
    "id", "lab", "surface", "user_operation", "control", "ui_handler",
    "domain_function", "domain_module", "adapter", "api", "wizard_capability",
    "wizard_schema", "in_wizard_context", "wizard_status", "wizard_available",
    "classification", "phase", "preconditions", "persistence", "presentation",
    "test", "notes", "prompt_fixture", "blocking_defect",
)


def _matrix() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_matrix_fixture_and_doc_exist():
    data = _matrix()
    assert data["schema"] == "hocuspocus.labs_wizard_action_matrix"
    assert data["version"] == 1
    assert data["base"]["sha"] == "e465a56ebbdcc979c73578655b6965b69db9976e"
    assert data["base"]["prs"]["179"] == "merged"
    assert data["base"]["prs"]["180"] == "merged"
    assert MATRIX_DOC.is_file()
    doc = MATRIX_DOC.read_text(encoding="utf-8")
    assert "tests/fixtures/labs_wizard_action_matrix.json" in doc
    for row in data["operations"]:
        assert f"`{row['id']}`" in doc, row["id"]


def test_every_operation_is_classified_with_a_phase():
    data = _matrix()
    classes = set(data["classifications"])
    phases = set(data["phases"])
    ids = []
    for row in data["operations"]:
        missing = [key for key in REQUIRED_FIELDS if key not in row]
        assert missing == [], (row.get("id"), missing)
        assert row["classification"] in classes, row["id"]
        assert row["phase"] in phases, row["id"]
        ids.append(row["id"])
        if row["wizard_capability"]:
            assert row["domain_function"], (
                f"Wizard-promised {row['wizard_capability']} on {row['id']} "
                "has no identified function"
            )
        if row["blocking_defect"]:
            assert row["wizard_available"] is False, row["id"]
        if row["domain_module"] and row["domain_function"]:
            path = ROOT / row["domain_module"]
            assert path.is_file(), (row["id"], row["domain_module"])
            assert row["domain_function"] in path.read_text(encoding="utf-8"), (
                row["id"], row["domain_function"], row["domain_module"]
            )
        if row["test"]:
            assert (ROOT / row["test"]).is_file(), (row["id"], row["test"])
    assert len(ids) == len(set(ids))
    assert len(ids) >= 60


def test_every_audited_control_group_has_classification_and_phase():
    data = _matrix()
    classes = set(data["classifications"])
    phases = set(data["phases"])
    op_ids = {row["id"] for row in data["operations"]}
    groups = data["audited_control_groups"]
    assert len(groups) == 60
    names = []
    for group in groups:
        assert group["classification"] in classes, group["component"]
        assert group["phase"] in phases, group["component"]
        assert group["operation_ids"], group["component"]
        missing = [oid for oid in group["operation_ids"] if oid not in op_ids]
        assert missing == [], (group["component"], missing)
        names.append(group["component"])
    assert len(names) == len(set(names))
    assert "SeriesShotsPanel.tsx" in names
    assert "StoryMusicProductionLegacyDrawer.tsx" in names


def test_closed_labs_gaps_are_marked_addressed():
    data = _matrix()
    by_id = {gap["id"]: gap for gap in data["known_gaps"]}
    closed = (
        "fused_dropped_by_model_for_manifest",
        "partial_global_profile_guard",
        "approve_all_replaces_chosen_takes",
        "script_shots_dialogue_desync",
        "t2v_double_mode_and_image_requirements",
        "shot_number_is_not_attempt_id",
    )
    for gap_id in closed:
        summary = by_id[gap_id]["summary"]
        assert summary.startswith("Addressed:"), gap_id
    review = (ROOT / "ui" / "src" / "features" / "series" / "actions.ts").read_text(encoding="utf-8")
    assert "replaceFinals: action.scope === 'replace_latest' || action.scope === 'selected_latest'" in review
    assert "explicitAttemptSelection" in review
    qa = ROOT / "ui" / "tests" / "labsWizardQaAttemptId.test.mjs"
    assert qa.is_file()
    assert "attempt_id" in qa.read_text(encoding="utf-8")
    matcher = (ROOT / "ui" / "src" / "lib" / "productionProfile.ts").read_text(encoding="utf-8")
    assert "settings.flowShift === fields.videoSettings.flowShift" in matcher
    assert "settings.audioShift === fields.videoSettings.audioShift" in matcher
    guidance = (ROOT / "ui" / "src" / "features" / "stories" / "storyVisualGuidance.ts").read_text(encoding="utf-8")
    assert "return mode === 'image_guided'" in guidance


def test_known_gaps_and_unregistered_series_comic_are_frozen():
    data = _matrix()
    gap_ids = {gap["id"] for gap in data["known_gaps"]}
    assert "fused_dropped_by_model_for_manifest" in gap_ids
    assert "approve_all_replaces_chosen_takes" in gap_ids
    assert "shot_number_is_not_attempt_id" in gap_ids
    assert "script_shots_dialogue_desync" in gap_ids
    assert "stage_series_comic_unregistered" in gap_ids
    assert "blocked_always_empty" in gap_ids
    comic = next(row for row in data["operations"] if row["id"] == "series.comic.stage")
    assert comic["domain_function"] == "stageSeriesComic"
    assert comic["wizard_capability"] == "stage_series_comic"
    assert comic["classification"] == "operativa"
    assert comic["phase"] == "L6"
    assert data["wizard_context"]["availability"]["model"] == "derived"
    wizard = next(row for row in data["operations"] if row["id"] == "wizard.context.blocked")
    assert wizard["blocking_defect"] == ""
    assert wizard["wizard_available"] is True


def test_l12_mandatory_cases_have_an_executable_suite():
    path = ROOT / "ui" / "tests" / "labsWizardL12.test.mjs"
    assert path.is_file()
    source = path.read_text(encoding="utf-8")
    for needle in (
        "Qué puedes hacer en Series Lab",
        "Cómo genero un capítulo",
        "quick_video",
        "unrelated canon",
        "He descubierto ChatGPT",
        "selected_latest",
        "stage_series_comic",
        "missingAssemblyShotOrders",
        "not_a_real_action",
        "question:workflow-1:step-2",
        "song-live",
    ):
        assert needle in source, needle
    doc = MATRIX_DOC.read_text(encoding="utf-8")
    assert "## L12 verification" in doc
    assert "did **not** run a GPU generation" in doc
    e2e = ROOT / "ui" / "e2e" / "specs" / "labs-wizard-l12-shells.spec.ts"
    assert e2e.is_file()
    assert "Story Lab full-story shell" in e2e.read_text(encoding="utf-8")


def test_h3_prompt_fixtures_are_reused_not_copied():
    data = _matrix()
    expected = "tests/fixtures/h3_prompt_fase1_expected.json"
    assert data["h3_prompt_fixtures"]["before_ui"] == expected
    assert data["h3_prompt_fixtures"]["before_queue"] == expected
    assert data["h3_prompt_fixtures"]["reuse_tests"] == [
        "tests/test_h3_prompt_finalization.py",
    ]
    assert H3_FIXTURE.is_file()
    payload = json.loads(H3_FIXTURE.read_text(encoding="utf-8"))
    assert payload["provenance"]["base_sha"]
    assert payload["speech_matrix"], "frozen H3 speech prompts must remain"
    assert (ROOT / "tests" / "test_h3_prompt_finalization.py").is_file()
    prompt_ops = [row for row in data["operations"] if row["prompt_fixture"] == expected]
    assert {row["id"] for row in prompt_ops} >= {
        "h3.prompt.finalization_fixture",
        "series.shots.render",
        "h3.policy.e2e",
        "h3.audio.contradictions",
        "h3.creative.extra_line",
    }
