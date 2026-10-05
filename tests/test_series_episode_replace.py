"""A rewritten script replaces the episode: extra shots go, and takes stay only where the content did."""
from services.series_library import _merge_episode_shot_patch, same_shot_content

TAKE = {"attempts": [{"id": "att-1", "status": "completed"}], "approvedAttemptId": "att-1", "durationSeconds": 4.2}


def stored(sid, text, who="kevin"):
    return {"id": sid, "order": 1, "locationId": "garage", "framing": "two",
            "dialogueBeats": [{"id": f"{sid}_b0", "characterId": who, "text": text, "sourceDialogueIds": ["d1"]}], **TAKE}


def test_replace_drops_unnamed_shots_and_stale_takes_but_keeps_matching_ones():
    current = [stored("e1s00", "¿Oyes eso?"), stored("e1s01", "...No.", "gary"), stored("e1s02", "Adiós.")]
    incoming = [{"id": "e1s00", "order": 1, "locationId": "garage", "framing": "two",
                 "dialogueBeats": [{"id": "e1s00_b0", "characterId": "kevin", "text": "¿Oyes eso?"}]},
                {"id": "e1s01", "order": 2, "locationId": "garage", "framing": "two",
                 "dialogueBeats": [{"id": "e1s01_b0", "characterId": "gary", "text": "Sí, un camión."}]}]
    merged = _merge_episode_shot_patch(current, incoming, replace=True)
    assert [shot["id"] for shot in merged] == ["e1s00", "e1s01"], "the third shot is gone"
    assert merged[0]["approvedAttemptId"] == "att-1" and merged[0]["durationSeconds"] == 4.2, "same lines: the take still fits"
    assert merged[1]["attempts"] == [] and "approvedAttemptId" not in merged[1], "other lines: no take"
    assert "durationSeconds" not in merged[1]
    # Without replace nothing changes: a sparse patch still cannot delete or strip a shot.
    sparse = _merge_episode_shot_patch(current, incoming)
    assert [shot["id"] for shot in sparse] == ["e1s00", "e1s01", "e1s02"] and sparse[1]["approvedAttemptId"] == "att-1"


def test_content_comparison_ignores_annotations_order_and_lengths():
    before = stored("e1s00", "Hola")
    after = {"id": "e1s00", "order": 7, "sceneId": "x", "durationSeconds": 9, "locationId": "garage", "framing": "two",
             "dialogueBeats": [{"id": "e1s00_b0", "characterId": "kevin", "text": "Hola"}]}
    assert same_shot_content(before, after)
    assert not same_shot_content(before, {**after, "framing": "close"})
    assert not same_shot_content(before, {**after, "layout2d": {"props": [{"file": "key.png"}]}})
    assert not same_shot_content(before, {**after, "dialogueBeats": [{"id": "e1s00_b0", "characterId": "gary", "text": "Hola"}]})
