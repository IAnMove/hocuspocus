"""An episode's staged review: production mode, plan and preview decisions per shot, notes, and when they reset."""
import copy

import pytest

from services.series_library import normalize_series_project, series_put_payload, update_series_episode
from services.series_review import (
    ReviewError, apply_review_change, classify, content_digest, normalize_episode_review, report, shot_entry, summary,
)

NOW = "2026-10-06T10:00:00Z"


def _shot(shot_id, order, *, method="animation_2d", x=40.0, line="Hola.", attempts=(), approved=None, scene="scene_1", **extra):
    shot = {"id": shot_id, "order": order, "sceneId": scene, "productionMethod": method, "framing": "medium", "camera": "static",
            "visibleCharacterIds": ["ines"], "locationId": "deck", "durationSeconds": 3,
            "layout2d": {"framing": "medium", "cast": [{"characterId": "ines", "poseId": "busto", "x": x}]},
            "dialogueBeats": [{"id": f"{shot_id}_b0", "characterId": "ines", "text": line}],
            "attempts": [dict(item) for item in attempts], **extra}
    if approved:
        shot["approvedAttemptId"] = approved
    return shot


def _take(attempt_id, stage=None, **extra):
    return {"id": attempt_id, "status": "completed", "outputAssetIds": [f"asset_{attempt_id}"], **({"reviewStage": stage} if stage else {}),
            **extra}


def _assets(shots):
    return {f"asset_{take['id']}": {"id": f"asset_{take['id']}", "kind": "video", "uri": f"assets/mp/{take['id']}.mp4",
                                    "ownerType": "attempt", "ownerId": take["id"], "metadata": {}}
            for shot in shots for take in shot.get("attempts") or []}


def _series(*shots, review=None):
    shots = list(shots) or [_shot("s01", 1), _shot("s02", 2)]
    episode = {"id": "ep1", "title": "La confesión", "shots": shots,
               "script": [{"id": "scene_1", "order": 1, "locationId": "deck", "participatingCharacterIds": ["ines"]}]}
    if review is not None:
        episode["review"] = review
    return normalize_series_project({
        "id": "mp", "title": "Más allá", "allowedProductionMethods": ["animation_2d", "animation_3d"],
        "characters": [{"id": "ines", "name": "Inés"}], "locations": [{"id": "deck", "name": "Cubierta"}],
        "assets": _assets(shots), "episodesById": {"ep1": episode}}, "mp", "cast")


def _episode(series):
    return series["episodesById"]["ep1"]


def _apply(series, body):
    episode = _episode(series)
    note_ids = apply_review_change(episode, body, now=NOW)
    return normalize_series_project(series, "mp", "cast"), note_ids


def test_an_episode_without_review_is_direct_and_stores_nothing():
    series = _series()
    assert "review" not in _episode(series), "existing episodes keep their JSON byte for byte"
    assert shot_entry(_episode(series), "s01") == {"plan": "pending", "preview": "pending", "notes": []}
    assert summary(_episode(series))["mode"] == "direct"
    assert summary(_episode(series))["nextStep"] == {"kind": "render", "count": 2}


def test_the_stored_review_is_the_documented_json():
    series, note_ids = _apply(_series(), {"mode": "plan", "shots": [
        {"shotId": "s01", "plan": "approved"},
        {"shotId": "s02", "plan": "changes", "note": {"text": "Inés más a la izquierda", "stage": "plan"}}]})
    review = _episode(series)["review"]
    digest = content_digest(next(shot for shot in _episode(series)["shots"] if shot["id"] == "s01"))
    assert review["mode"] == "plan" and review["updatedAt"] == NOW
    assert review["shots"]["s01"] == {"plan": "approved", "planDigest": digest, "planAt": NOW, "planBy": "user", "preview": "pending",
                                      "notes": []}
    note = review["shots"]["s02"]["notes"][0]
    assert note == {"id": note_ids["s02"], "at": NOW, "stage": "plan", "text": "Inés más a la izquierda", "by": "user"}
    assert review["shots"]["s02"]["plan"] == "changes"


def test_a_content_change_resets_the_decisions_and_keeps_the_notes():
    series, _ = _apply(_series(), {"mode": "plan", "shots": [
        {"shotId": "s01", "plan": "approved", "note": {"text": "bien"}}, {"shotId": "s02", "plan": "approved"}]})
    moved = copy.deepcopy(_episode(series)["shots"][0])
    moved["layout2d"]["cast"][0]["x"] = 20.0
    updated = normalize_series_project(update_series_episode(series, "ep1", {"shots": [moved]}, base_series_revision=series["revision"]),
                                       "mp", "cast")
    first, second = (shot_entry(_episode(updated), shot_id) for shot_id in ("s01", "s02"))
    assert first["plan"] == "pending" and first["notes"][0]["text"] == "bien", "moved cast: approve the plan again"
    assert second["plan"] == "approved", "the other shot keeps its approval"
    assert _episode(updated)["review"]["mode"] == "plan"


def test_a_change_that_is_not_content_keeps_the_approval():
    series, _ = _apply(_series(), {"mode": "plan", "shots": [{"shotId": "s01", "plan": "approved"}]})
    shot = copy.deepcopy(_episode(series)["shots"][0])
    shot.update(prompt="otra luz", durationSeconds=4, action="mira al mar")
    updated = normalize_series_project(update_series_episode(series, "ep1", {"shots": [shot]}, base_series_revision=series["revision"]),
                                       "mp", "cast")
    assert shot_entry(_episode(updated), "s01")["plan"] == "approved"


def test_a_rewrite_keeps_the_mode_and_the_review_of_shots_that_keep_their_id():
    series, _ = _apply(_series(_shot("s01", 1), _shot("s02", 2), _shot("s03", 3)), {"mode": "preview", "shots": [
        {"shotId": "s01", "plan": "approved"}, {"shotId": "s02", "plan": "approved", "note": {"text": "más luz"}},
        {"shotId": "s03", "plan": "approved"}]})
    shots = [_shot("s01", 1), _shot("s02", 2, line="Otra frase."), _shot("s04", 3)]
    patch = {"shots": shots, "replaceShots": True}
    updated = normalize_series_project(update_series_episode(series, "ep1", patch, base_series_revision=series["revision"]), "mp", "cast")
    review = _episode(updated)["review"]
    assert review["mode"] == "preview"
    assert review["shots"]["s01"]["plan"] == "approved", "same content under the same id"
    assert review["shots"]["s02"]["plan"] == "pending" and review["shots"]["s02"]["notes"][0]["text"] == "más luz"
    assert set(review["shots"]) == {"s01", "s02"}, "a removed shot loses its entry; a new one starts pending"


def test_approving_a_preview_needs_a_take_binds_it_and_approves_the_plan():
    series = _series(_shot("s01", 1), _shot("s02", 2, attempts=[_take("a1", "preview")]))
    with pytest.raises(ReviewError, match="render its preview first"):
        _apply(series, {"mode": "preview", "shots": [{"shotId": "s01", "preview": "approved"}]})
    series, _ = _apply(series, {"mode": "preview", "shots": [{"shotId": "s02", "preview": "approved"}]})
    entry = shot_entry(_episode(series), "s02")
    assert entry["preview"] == "approved" and entry["previewAttemptId"] == "a1" and entry["plan"] == "approved"


def test_a_newer_take_puts_the_preview_back_to_pending_unless_it_is_its_final():
    series, _ = _apply(_series(_shot("s01", 1, method="animation_3d", attempts=[_take("a1", "preview")],
                                     scene3d={"template": "deck", "quality": "final"})),
                       {"mode": "preview", "shots": [{"shotId": "s01", "preview": "approved"}]})
    final = copy.deepcopy(series)
    _episode(final)["shots"][0]["attempts"].append(_take("a2", "final"))
    final["assets"].update(_assets([{"attempts": [_take("a2")]}]))
    _episode(final)["shots"][0]["approvedAttemptId"] = "a2"
    final = normalize_series_project(final, "mp", "cast")
    assert shot_entry(_episode(final), "s01")["preview"] == "approved", "its own final take"
    assert classify(_episode(final), _episode(final)["shots"][0]) == "ready"
    retake = copy.deepcopy(series)
    _episode(retake)["shots"][0]["attempts"].append(_take("a3"))
    retake["assets"].update(_assets([{"attempts": [_take("a3")]}]))
    retake = normalize_series_project(retake, "mp", "cast")
    assert shot_entry(_episode(retake), "s01")["preview"] == "pending", "a new take nobody looked at yet"
    assert shot_entry(_episode(retake), "s01")["plan"] == "approved"


def test_a_client_save_of_the_whole_project_cannot_overwrite_the_review():
    series, _ = _apply(_series(), {"mode": "plan", "shots": [{"shotId": "s01", "plan": "approved", "note": {"text": "ok"}}]})
    stale = copy.deepcopy(series)
    _episode(stale)["review"] = {"mode": "direct", "shots": {"s02": {"plan": "approved", "planDigest": "forged"}}}
    _episode(stale)["title"] = "Nuevo título"
    saved = normalize_series_project(series_put_payload(series, stale), "mp", "cast")
    assert _episode(saved)["title"] == "Nuevo título"
    assert _episode(saved)["review"] == _episode(series)["review"]


def test_a_refused_change_applies_nothing():
    series = _series()
    episode = _episode(series)
    before = copy.deepcopy(episode)
    cases = [({"mode": "fast"}, "mode must be"), ({"shots": [{"shotId": "s01", "plan": "ok"}]}, "plan must be"),
             ({"shots": [{"shotId": "s01", "plan": "approved"}, {"shotId": "nope", "plan": "approved"}]}, "not found"),
             ({"shots": [{"shotId": "s01", "colour": "red"}]}, "Each shot change"),
             ({"shots": [{"shotId": "s01", "note": {"text": "x" * 2001}}]}, "limited to 2000"),
             ({"shots": [{"shotId": "s01", "note": {"text": "x", "id": "../etc"}}]}, "note.id"),
             ({}, "Send a mode")]
    for body, message in cases:
        with pytest.raises(ReviewError, match=message):
            apply_review_change(episode, body, now=NOW)
        assert episode == before
    with pytest.raises(ReviewError) as missing:
        apply_review_change(episode, {"shots": [{"shotId": "nope"}]}, now=NOW)
    assert missing.value.status == 404


def test_notes_are_updated_by_id_removed_when_emptied_and_get_the_stage_of_the_mode():
    series, ids = _apply(_series(), {"mode": "preview", "shots": [{"shotId": "s01", "note": {"text": "primera"}}]})
    note_id = ids["s01"]
    assert shot_entry(_episode(series), "s01")["notes"][0]["stage"] == "plan", "the plan is not approved yet"
    series, again = _apply(series, {"shots": [{"shotId": "s01", "note": {"id": note_id, "text": "primera, corregida"}}]})
    assert again == {"s01": note_id}
    assert [note["text"] for note in shot_entry(_episode(series), "s01")["notes"]] == ["primera, corregida"]
    series, _ = _apply(series, {"shots": [{"shotId": "s01", "plan": "approved", "note": {"text": "hecho", "by": "agent"}}]})
    notes = shot_entry(_episode(series), "s01")["notes"]
    assert [(note["stage"], note["by"]) for note in notes] == [("plan", "user"), ("preview", "agent")]
    series, _ = _apply(series, {"shots": [{"shotId": "s01", "note": {"id": note_id, "text": ""}}]})
    series, _ = _apply(series, {"shots": [{"shotId": "s01", "removeNoteId": notes[1]["id"]}]})
    assert shot_entry(_episode(series), "s01")["notes"] == []


def test_classification_and_next_step_in_each_mode():
    shots = [_shot("s01", 1), _shot("s02", 2, attempts=[_take("a2")]), _shot("s03", 3, attempts=[_take("a3")], approved="a3"),
             _shot("s04", 4, method="animation_3d", scene3d={"template": "deck", "quality": "final"},
                   attempts=[_take("a4", "preview")], approved="a4")]
    series = _series(*shots)
    assert summary(_episode(series))["steps"] == [{"kind": "render", "count": 2}]
    series, _ = _apply(series, {"mode": "plan", "shots": [{"shotId": "s02", "plan": "approved"}, {"shotId": "s03", "plan": "approved"}]})
    assert [classify(_episode(series), shot) for shot in _episode(series)["shots"]] == ["approve_plan", "render", "ready", "approve_plan"]
    series, _ = _apply(series, {"mode": "preview", "shots": [{"shotId": "s01", "plan": "approved"}, {"shotId": "s03", "preview": "approved"},
                                                              {"shotId": "s04", "preview": "approved"}]})
    kinds = [classify(_episode(series), shot) for shot in _episode(series)["shots"]]
    assert kinds == ["render_previews", "approve_previews", "ready", "render_final"], "a draft 3D preview still needs its final"
    result = summary(_episode(series))
    assert result["counts"]["ready"] == 1 and result["counts"]["plan"]["approved"] == 4
    assert result["nextStep"] == {"kind": "render_previews", "count": 1}
    series, _ = _apply(series, {"shots": [{"shotId": "s02", "preview": "changes", "note": {"text": "sin eco"}}]})
    assert [step["kind"] for step in summary(_episode(series))["steps"]] == ["changes", "render_previews", "render_final"]
    shot_report = next(item for item in report(series, _episode(series))["shots"] if item["shotId"] == "s02")
    assert shot_report["step"] == "changes" and shot_report["notes"][0]["text"] == "sin eco"
    assert shot_report["previewAttemptId"] == "a2" and shot_report["latestAttemptId"] == "a2"


def test_normalization_repairs_a_hand_edited_review():
    episode = {"id": "ep1", "shots": [_shot("s01", 1)], "review": {
        "mode": "turbo", "shots": {"s01": {"plan": "approved", "planDigest": "0000", "notes": [{"text": "  "}, {"text": "ok", "stage": "x"}]},
                                   "ghost": {"plan": "approved"}}}}
    normalize_episode_review(episode)
    assert episode["review"]["mode"] == "direct"
    entry = episode["review"]["shots"]["s01"]
    assert entry["plan"] == "pending", "a digest of other content is no approval"
    assert [(note["text"], note["stage"]) for note in entry["notes"]] == [("ok", "final")]
    assert "ghost" not in episode["review"]["shots"]
    empty = {"id": "ep1", "shots": [_shot("s01", 1)], "review": {"mode": "direct", "shots": {}}}
    normalize_episode_review(empty)
    assert "review" not in empty


def test_an_approval_survives_the_browser_saving_the_project_back():
    """The UI saves the whole project: its JSON has 56 where the server wrote 56.0. That is the same shot."""
    series, _ = _apply(_series(_shot("s01", 1, x=56.0)), {"mode": "plan", "shots": [{"shotId": "s01", "plan": "approved"}]})

    def browser(value):
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, dict):
            return {key: browser(item) for key, item in value.items()}
        return [browser(item) for item in value] if isinstance(value, list) else value

    sent = browser(copy.deepcopy(series))
    _episode(sent)["shots"][0]["layout2d"]["cast"][0]["x"] = 56
    saved = normalize_series_project(series_put_payload(series, sent), "mp", "cast")
    assert shot_entry(_episode(saved), "s01")["plan"] == "approved"


def test_a_note_alone_keeps_an_approved_plan():
    """A note is not a content edit: the plan stays approved."""
    series, _ = _apply(_series(), {"mode": "plan", "shots": [{"shotId": "s01", "plan": "approved"}]})
    series, _ = _apply(series, {"shots": [{"shotId": "s01", "note": {"text": "sigue bien"}}]})
    entry = shot_entry(_episode(series), "s01")
    assert entry["plan"] == "approved" and entry["notes"][0]["text"] == "sigue bien"


def test_an_edit_names_every_approval_the_picture_change_clears():
    from services.series_shot_edit import apply_edit
    shot = _shot("s01", 1, attempts=[_take("t1")], approved="t1")
    series, _ = _apply(_series(shot), {"mode": "preview", "shots": [
        {"shotId": "s01", "plan": "approved", "preview": "approved", "attemptId": "t1"}]})
    moved = copy.deepcopy(_episode(series)["shots"][0])
    moved["layout2d"]["cast"][0]["x"] = 70
    _edited, report = apply_edit(series, "ep1", "s01", {"id": "s01", "layout2d": moved["layout2d"]}, {}, ["cast"], False)
    assert report["approvalReset"] is True and report["reset"] == ["plan", "preview", "take"]


def test_sfx_volume_keeps_the_plan_and_the_take():
    """Volume is a mix level. A different file still clears plan and take."""
    from services.series_shot_edit import apply_edit
    shot = _shot("s01", 1, attempts=[_take("t1")], approved="t1")
    shot["layout2d"]["sfx"] = [{"file": "pen.wav", "at": 1.0, "volume": 0.8}]
    series, _ = _apply(_series(shot), {"mode": "plan", "shots": [{"shotId": "s01", "plan": "approved"}]})
    layout = copy.deepcopy(_episode(series)["shots"][0]["layout2d"])
    layout["sfx"][0]["volume"] = 0.2
    edited, report = apply_edit(series, "ep1", "s01", {"id": "s01", "layout2d": layout}, {}, ["sfx"], False)
    assert report["approvalReset"] is False and report["reset"] == []
    saved = normalize_series_project(edited, "mp", "cast")
    assert shot_entry(_episode(saved), "s01")["plan"] == "approved"
    kept = next(item for item in _episode(saved)["shots"] if item["id"] == "s01")
    assert kept["approvedAttemptId"] == "t1" and kept["layout2d"]["sfx"][0]["volume"] == 0.2
    layout["sfx"][0]["file"] = "other.wav"
    _changed, again = apply_edit(saved, "ep1", "s01", {"id": "s01", "layout2d": layout}, {}, ["sfx"], False)
    assert again["approvalReset"] is True and again["reset"] == ["plan", "take"]


def test_a_decision_stored_before_the_volume_exemption_stays_approved():
    """Stored digests count each sfx cue's volume. The digest must not change: 143 of 869 real plan approvals
    (plus-ultra, goya) would go back to pending. 0e91… is what the code before the exemption wrote for this shot."""
    shot = _shot("s01", 1, attempts=[_take("t1")], approved="t1")
    shot["layout2d"]["sfx"] = [{"file": "pen.wav", "at": 1.0, "volume": 0.8}]
    stored = {"plan": "approved", "planDigest": "0e91411977a564cc", "planAt": NOW, "planBy": "user",
              "preview": "approved", "previewDigest": "0e91411977a564cc", "previewAt": NOW, "previewBy": "user",
              "previewAttemptId": "t1", "notes": []}
    series = _series(shot, review={"mode": "preview", "shots": {"s01": stored}})
    assert content_digest(_episode(series)["shots"][0]) == "0e91411977a564cc"
    entry = shot_entry(_episode(series), "s01")
    assert entry["plan"] == "approved" and entry["preview"] == "approved"


def test_an_sfx_volume_edit_keeps_a_preview_and_a_different_one_still_resets():
    from services.series_shot_edit import apply_edit
    shot = _shot("s01", 1, attempts=[_take("t1")], approved="t1")
    shot["layout2d"]["sfx"] = [{"file": "pen.wav", "at": 1.0, "volume": 0.8}]
    series, _ = _apply(_series(shot), {"mode": "preview", "shots": [
        {"shotId": "s01", "plan": "approved", "preview": "approved", "attemptId": "t1"}]})
    before = content_digest(_episode(series)["shots"][0])
    layout = copy.deepcopy(_episode(series)["shots"][0]["layout2d"])
    layout["sfx"][0]["volume"] = 0.2
    edited, report = apply_edit(series, "ep1", "s01", {"id": "s01", "layout2d": layout}, {}, ["sfx"], False)
    saved = normalize_series_project(edited, "mp", "cast")
    after = content_digest(_episode(saved)["shots"][0])
    assert after != before, "the digest still counts the volume"
    assert report["reset"] == []
    entry = shot_entry(_episode(saved), "s01")
    assert entry["plan"] == "approved" and entry["preview"] == "approved"
    assert _episode(saved)["review"]["shots"]["s01"]["planDigest"] == after
    layout["sfx"][0]["at"] = 2.0
    _moved, again = apply_edit(saved, "ep1", "s01", {"id": "s01", "layout2d": layout}, {}, ["sfx"], False)
    assert again["reset"] == ["plan", "preview", "take"]


def test_an_edit_by_shot_number_resets_that_shots_review():
    """series.shot.update ("edit the second shot") writes through the editor patch, so its approvals go back to pending."""
    from services.series_shot_edit import apply_edit
    series, _ = _apply(_series(), {"mode": "plan", "shots": [{"shotId": "s01", "plan": "approved"},
                                                              {"shotId": "s02", "plan": "approved", "note": {"text": "más cerca"}}]})
    moved = copy.deepcopy(_episode(series)["shots"][1])
    moved["layout2d"]["cast"][0]["x"] = 70.0
    edited, _report = apply_edit(series, "ep1", "s02", {"id": "s02", "layout2d": moved["layout2d"]}, {}, ["cast"], False)
    saved = normalize_series_project(edited, "mp", "cast")
    assert shot_entry(_episode(saved), "s02")["plan"] == "pending" and shot_entry(_episode(saved), "s02")["notes"][0]["text"] == "más cerca"
    assert shot_entry(_episode(saved), "s01")["plan"] == "approved"
