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


def test_a_rewrite_keeps_the_files_of_the_shots_and_takes_it_drops_owned_by_the_episode():
    """The bug: a rewrite dropping a shot (or a changed shot's take) left the take's video owned by an attempt that no
    longer existed, and the whole project then failed validation, so the script could not be written at all."""
    from services.series_library import update_series_episode
    shots = [{**stored("e1s00", "¿Oyes eso?"), "attempts": [{"id": "att-0", "status": "completed"}], "approvedAttemptId": "att-0"},
             {**stored("e1s01", "...No.", "gary"), "attempts": [{"id": "att-1", "status": "completed"}], "approvedAttemptId": "att-1"},
             {**stored("e1s02", "Adiós."), "attempts": [{"id": "att-2", "status": "completed"}], "approvedAttemptId": "att-2"}]
    video = lambda owner_type, owner: {"kind": "video", "uri": f"{owner}.mp4", "ownerType": owner_type, "ownerId": owner}
    series = {"id": "show", "revision": 3, "episodesById": {"e1": {"id": "e1", "shots": shots}},
              "assets": {"a0": video("attempt", "att-0"), "a1": video("attempt", "att-1"), "a2": video("attempt", "att-2"),
                         "a3": video("shot", "e1s02"), "a4": video("series", "show")}}
    incoming = [{"id": "e1s00", "order": 1, "locationId": "garage", "framing": "two",
                 "dialogueBeats": [{"id": "e1s00_b0", "characterId": "kevin", "text": "¿Oyes eso?"}]},
                {"id": "e1s01", "order": 2, "locationId": "garage", "framing": "two",
                 "dialogueBeats": [{"id": "e1s01_b0", "characterId": "gary", "text": "Sí, un camión."}]}]
    updated = update_series_episode(series, "e1", {"shots": incoming, "replaceShots": True}, base_series_revision=3)
    owners = {asset_id: (asset["ownerType"], asset["ownerId"]) for asset_id, asset in updated["assets"].items()}
    assert owners["a0"] == ("attempt", "att-0"), "the take that still fits keeps its file"
    assert owners["a1"] == ("episode", "e1") and owners["a2"] == ("episode", "e1"), "dropped takes' files stay, on the episode"
    assert owners["a3"] == ("episode", "e1") and owners["a4"] == ("series", "show")
    assert series["assets"]["a1"]["ownerType"] == "attempt", "the stored project is not changed in place"


def test_a_video_take_survives_a_rewrite_that_only_changes_its_sound():
    """Generated and imported takes get sfx, music and clip audio at the cut: changing them keeps the take."""
    video = {"id": "e1s03", "order": 4, "locationId": "garage", "productionMethod": "imported_video",
             "layout2d": {"framing": "wide", "camera": "static", "sfx": [{"file": "boom.wav", "at": 1.0}]}, **TAKE}
    louder = {**{key: value for key, value in video.items() if key not in TAKE},
              "layout2d": {"framing": "wide", "camera": "static", "sfx": [{"file": "boom.wav", "at": 2.0, "in": 0.5}],
                           "music": {"file": "theme.wav"}, "clipAudio": "drop"}}
    assert same_shot_content(video, louder)
    merged = _merge_episode_shot_patch([video], [louder], replace=True)
    assert merged[0]["approvedAttemptId"] == "att-1" and merged[0]["layout2d"]["clipAudio"] == "drop"
    assert not same_shot_content(video, {**louder, "productionMethod": "animation_2d"}), "a 2D shot renders its sound"
    assert not same_shot_content({**video, "productionMethod": "animation_2d"},
                                 {**louder, "productionMethod": "animation_2d"})


def test_a_transition_is_not_shot_content_and_a_cut_is_dropped():
    from services.series_library import _normalize_shot

    before = stored("e1s00", "Hola")
    body = {key: value for key, value in before.items() if key not in TAKE}
    after = {**body, "transitionIn": {"kind": "dissolve", "seconds": 0.5}}
    assert same_shot_content(before, after)
    merged = _merge_episode_shot_patch([before], [after], replace=True)
    assert merged[0]["approvedAttemptId"] == "att-1" and merged[0]["transitionIn"]["kind"] == "dissolve"
    cleared = _merge_episode_shot_patch(merged, [{**body, "transitionIn": None}], replace=True)
    assert cleared[0].get("transitionIn") is None and cleared[0]["approvedAttemptId"] == "att-1"
    base = {**stored("e1s00", "Hola"), "productionMethod": "animation_2d"}
    assert "transitionIn" not in _normalize_shot({**base, "transitionIn": {"kind": "cut", "seconds": 0.4}}, 0)
    kept = _normalize_shot({**base, "transitionIn": {"kind": "dip_white", "seconds": 1}}, 0)
    assert kept["transitionIn"] == {"kind": "dip_white", "seconds": 1.0}
