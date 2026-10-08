"""Style check and duplicate warnings. The analyzer is simulated."""
import copy
import threading
import time

import numpy as np
import pytest
from PIL import Image

from services import game_qa
from services.game_generators import REGISTRY
from services.game_generators.base import AttemptResult
from services.game_inputs import asset_inputs
from services.game_library import add_attempt, approve_attempt, create_game, normalize_style, update_game, upsert_assets, warning_codes
from services.game_produce import GameProduce, ProduceDeps
from services.game_qa import file_dhash, note_style, style_check

NOW = "2026-10-06T12:00:00Z"


def test_game_warnings_are_code_and_message():
    from services.game_generators.animation import animation_warnings
    from services.game_generators.audio import loop_warnings
    from services.game_generators.three_d import budget_warning
    from services.game_library import game_warning

    batches = [
        animation_warnings(0.06, 0.21, 0.21, 2.01),
        loop_warnings(0.06, 0.0),
        budget_warning(12, 10),
        budget_warning(None, 10),
        [game_warning("style_mismatch", "The image does not match the style reference.")],
    ]
    seen = set()
    for batch in batches:
        assert batch
        for item in batch:
            assert {"code", "message"} <= set(item)
            assert isinstance(item["code"], str) and item["code"] and " " not in item["code"]
            assert isinstance(item["message"], str) and item["message"]
            seen.add(item["code"])
    assert {
        "loop_not_closed", "identity_drift", "foot_drift", "halo",
        "loop_seam", "over_budget", "triangles_unknown", "style_mismatch",
    } <= seen


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    """No pause or cached hash leaks from one test into the next."""
    monkeypatch.setitem(game_qa._PAUSED, "until", 0.0)
    game_qa._cached_dhash.cache_clear()
    yield
    game_qa._cached_dhash.cache_clear()


class _Caller:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def loopback(self, tool, arguments):
        self.calls.append((tool, arguments))
        if self.error:
            raise self.error
        return self.result


def _picture(path, flip=False):
    image = Image.new("L", (32, 32), 0)
    pixels = image.load()
    for y in range(32):
        for x in range(32):
            bright = x > 16
            pixels[x, y] = 0 if bright == flip else 255
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def _stripes(path):
    """Vertical stripes: far from both ``_picture`` halves."""
    columns = np.tile((np.arange(32) // 4 % 2 * 255).astype(np.uint8), (32, 1))
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(columns).save(path)


def _approved(asset_id, kind, main, attempt_id="r1"):
    return {"id": asset_id, "kind": kind, "status": "approved", "approvedAttemptId": attempt_id,
            "attempts": [{"id": attempt_id, "status": "ok", "files": {"main": main}}]}


def _game(*assets, vision=True, refs=("ref",)):
    return {
        "id": "bosque",
        "style": {"qa": {"vision": vision}, "references": [{"assetId": ref, "attemptId": "r1"} for ref in refs]},
        "assets": list(assets),
    }


def _workspace(tmp_path):
    """``ref.png`` (an approved reference) and ``hero.png`` (the candidate) differ."""
    _picture(tmp_path / "ref.png", flip=True)
    _picture(tmp_path / "hero.png")
    return _approved("ref", "character", "ref.png")


HERO = {"id": "heroe", "kind": "character", "status": "generating"}


def test_style_json_ignores_the_text_around_it():
    caller = _Caller({"text": 'Sure {"score": 4, "reason": "same ink"} thanks {"score": 1}'})
    checked = style_check(caller, "/api/v1/file/hero.png", ["a", "b", "c", "d"], "game-x-style")
    assert checked == {"score": 4, "reason": "same ink"}
    tool, arguments = caller.calls[0]
    assert tool == "analyze"
    assert arguments["request_id"] == "game-x-style"
    assert [item["source"] for item in arguments["params"]["media"]] == ["a", "b", "c", "/api/v1/file/hero.png"]


@pytest.mark.parametrize("reply", [
    {"score": 5.5}, {"score": 0}, {"score": -3}, {"score": "4"}, {"score": True}, {"score": None},
    {"text": '{"score": NaN}'}, {"text": '{"score": Infinity}'}, {"text": "4 out of 5"}, {"text": "{oops}"},
    {"error": "no vision model", "score": 4}, ["score", 4], "4",
])
def test_garbage_or_out_of_range_scores_are_no_score(reply):
    checked = style_check(_Caller(reply), "/api/v1/file/hero.png", ["a"])
    assert checked == {"score": None, "reason": "style_check_unavailable"}


def test_a_fractional_score_rounds_half_up():
    assert style_check(_Caller({"score": 4.5}), "c", ["a"])["score"] == 5
    assert style_check(_Caller({"score": 2.4, "reason": ""}), "c", ["a"]) == {"score": 2, "reason": "ok"}


def test_analyze_gets_canonical_urls_and_a_new_request_per_candidate(tmp_path):
    ref = _workspace(tmp_path)
    _picture(tmp_path / "game" / "a 2" / "hero+.png")
    caller = _Caller({"text": '{"score": 4, "reason": "ok"}'})
    game = _game(ref)
    for attempt_id, main in (("abc-a1", "hero.png"), ("abc-a2", "game/a 2/hero+.png")):
        metrics, warnings = note_style(caller.loopback, str(tmp_path), "lab one", game, HERO, {"main": main}, {}, [], attempt_id=attempt_id)
        assert metrics == {"styleScore": 4}
        assert warnings == []
    first, second = (arguments for _tool, arguments in caller.calls)
    assert first["params"]["workspace"] == "lab one"
    assert [item["source"] for item in first["params"]["media"]] == [
        "/api/v1/file/ref.png?workspace=lab+one", "/api/v1/file/hero.png?workspace=lab+one",
    ]
    assert second["params"]["media"][-1]["source"] == "/api/v1/file/game/a%202/hero%2B.png?workspace=lab+one"
    assert first["request_id"].startswith("game-bosque-heroe-abc-a1-style-")
    assert second["request_id"].startswith("game-bosque-heroe-abc-a2-style-")
    assert len(first["request_id"]) <= 160
    assert first["params"]["json_schema"]["properties"]["score"] == {"type": "integer", "minimum": 1, "maximum": 5}
    assert first["params"]["temperature"] == 0


def test_references_skip_missing_files_and_the_candidate_itself(tmp_path):
    _picture(tmp_path / "hero.png")
    game = _game(_approved("self", "character", "hero.png"), _approved("gone", "character", "gone.png"), refs=("self", "gone"))
    caller = _Caller({"score": 5})
    metrics, warnings = note_style(caller.loopback, str(tmp_path), "lab", game, HERO, {"main": "hero.png"}, {"colors": 3}, ["halo"])
    assert caller.calls == []
    # No reference left: nothing to compare, so no score and no warning, but the duplicate check still ran.
    assert metrics == {"colors": 3}
    assert warnings[0] == "halo"
    assert warning_codes(warnings) == ["halo", "duplicate_of"]
    assert warnings[1]["ref"] == "self"
    assert warnings[1]["message"]


def test_only_stills_inside_the_workspace_are_checked(tmp_path):
    ref = _workspace(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-outside.png"
    _picture(outside)
    caller = _Caller({"score": 1})
    game = _game(ref)
    cases = [
        ({"id": "walk", "kind": "animation"}, {"main": "hero.png", "sheet": "hero.png", "atlas": "a.json"}),
        ({"id": "boom", "kind": "vfx"}, {"main": "hero.png"}),
        ({"id": "cielo", "kind": "background"}, {"layer-0.png": "hero.png"}),
        ({"id": "moneda", "kind": "item"}, {"main": "hero.png", "sheet": "hero.png", "atlas": "a.json"}),
        (HERO, {"main": str(outside)}),
        (HERO, {"main": f"../{outside.name}"}),
        (HERO, {"main": "missing.png"}),
    ]
    for asset, files in cases:
        assert note_style(caller.loopback, str(tmp_path), "lab", game, asset, files, {"k": 1}, ["w"]) == ({"k": 1}, ["w"])
    assert caller.calls == []


def test_analyze_down_does_not_break_the_batch(tmp_path, monkeypatch):
    caller = _Caller(error=OSError("down"))
    checked = style_check(caller, "/api/v1/file/hero.png", ["a"])
    assert checked["score"] is None
    assert checked["reason"] == "style_check_unavailable"
    monkeypatch.setitem(game_qa._PAUSED, "until", 0.0)
    ref = _workspace(tmp_path)

    class Generator:
        def estimate(self, _game, _asset):
            return {"image": 1}

        def run(self, ctx):
            return AttemptResult(
                files={"main": "hero.png"}, metrics={"attemptIds": [ctx.attempt_id]},
                warnings=[], provenance={"steps": []},
            )

    game = _game(ref, {"id": "heroe", "kind": "character", "status": "pending", "dependsOn": [], "spec": {}, "candidates": 1})
    saved = {}

    def write_attempt(_workspace, _game_id, asset_id, attempt, status):
        saved["attempt"] = attempt
        saved["status"] = status
        game["assets"][1]["status"] = status

    def stamp_attempt(_workspace, _game_id, _asset_id, attempt_id, metrics, warnings):
        saved["stamped"] = (attempt_id, metrics, warnings)

    monkeypatch.setitem(REGISTRY, "character", Generator())
    service = GameProduce(ProduceDeps(
        call=lambda _tool, _args: {},
        loopback=caller.loopback,
        workspace_dir=lambda _name: str(tmp_path),
        read_game=lambda _workspace, _game_id: copy.deepcopy(game),
        write_attempt=write_attempt,
        inline=True,
        stamp_attempt=stamp_attempt,
    ))
    job = service.start("lab", "bosque", asset_ids=["heroe"])
    assert job["status"] == "completed"
    assert job["steps"][0]["status"] == "done"
    assert saved["status"] == "review"
    assert saved["attempt"]["warnings"] == []  # saved before the vision check
    attempt_id, metrics, warnings = saved["stamped"]
    assert attempt_id == saved["attempt"]["id"]
    assert "style_check_unavailable" in warning_codes(warnings)
    assert "styleScore" not in metrics


def test_each_candidate_is_scored_from_its_own_picture(tmp_path, monkeypatch):
    ref = _workspace(tmp_path)
    _stripes(tmp_path / "a2.png")
    scores = {"hero.png": 5, "a2.png": 1}

    def loopback(_tool, arguments):
        source = arguments["params"]["media"][-1]["source"]
        return {"text": '{"score": %d, "reason": "r"}' % scores[source.split("/")[-1].split("?")[0]]}

    class Generator:
        def estimate(self, _game, _asset):
            return {"image": 2}

        def run(self, ctx):
            listed = [
                {"id": f"{ctx.attempt_id}-a1", "files": {"main": "hero.png"}, "metrics": {}, "warnings": []},
                {"id": f"{ctx.attempt_id}-a2", "files": {"main": "a2.png"}, "metrics": {}, "warnings": []},
            ]
            return AttemptResult(files={"main": "hero.png"}, metrics={"candidates": listed}, warnings=[], provenance={"steps": []})

    game = _game(ref, {"id": "heroe", "kind": "character", "status": "pending", "dependsOn": [], "spec": {}, "candidates": 2})
    stamped = []
    monkeypatch.setitem(REGISTRY, "character", Generator())
    service = GameProduce(ProduceDeps(
        call=lambda _tool, _args: {}, loopback=loopback, workspace_dir=lambda _name: str(tmp_path),
        read_game=lambda _workspace, _game_id: copy.deepcopy(game),
        write_attempt=lambda _w, _g, _a, _attempt, _status: None, inline=True,
        stamp_attempt=lambda _w, _g, _a, attempt_id, metrics, warnings: stamped.append((attempt_id, metrics, warnings)),
    ))
    service.start("lab", "bosque", asset_ids=["heroe"])
    assert [(attempt_id[-2:], metrics.get("styleScore"), warning_codes(warnings)) for attempt_id, metrics, warnings in stamped] == [
        ("a1", 5, []), ("a2", 1, ["style_mismatch"]),
    ]


def test_a_hung_analyzer_costs_one_wait_then_pauses(tmp_path, monkeypatch):
    monkeypatch.setattr(game_qa, "_TIMEOUT_S", 0.2)
    monkeypatch.setattr(game_qa, "_POLL_S", 0.05)
    release = threading.Event()
    calls = []

    def hung(_tool, _arguments):
        calls.append(1)
        release.wait(5)
        return {"score": 5}

    ref = _workspace(tmp_path)
    try:
        started = time.monotonic()
        for _ in range(3):
            metrics, warnings = note_style(hung, str(tmp_path), "lab", _game(ref), HERO, {"main": "hero.png"}, {}, [])
            assert metrics == {}
            assert warning_codes(warnings) == ["style_check_unavailable"]
            assert warnings[0]["message"]
        assert time.monotonic() - started < 2
        assert len(calls) == 1
    finally:
        release.set()


def test_a_cancel_stops_the_wait_without_pausing_vision(tmp_path, monkeypatch):
    monkeypatch.setattr(game_qa, "_POLL_S", 0.05)
    release = threading.Event()
    stop = threading.Event()

    def slow(_tool, _arguments):
        stop.set()
        release.wait(5)
        return {"score": 5}

    ref = _workspace(tmp_path)
    try:
        started = time.monotonic()
        _metrics, warnings = note_style(slow, str(tmp_path), "lab", _game(ref), HERO, {"main": "hero.png"}, {}, [], cancelled=stop.is_set)
        assert warning_codes(warnings) == ["style_check_unavailable"]
        assert warnings[0]["message"]
        assert time.monotonic() - started < 2
        assert not game_qa._paused()
        caller = _Caller(error=AssertionError("cancelled jobs do not ask"))
        note_style(caller.loopback, str(tmp_path), "lab", _game(ref), HERO, {"main": "hero.png"}, {}, [], cancelled=lambda: True)
        assert caller.calls == []
    finally:
        release.set()


def test_duplicate_of_an_approved_sibling(tmp_path):
    _picture(tmp_path / "left.png")
    _picture(tmp_path / "right.png")
    _picture(tmp_path / "other.png", flip=True)
    assert file_dhash(tmp_path / "left.png") == file_dhash(tmp_path / "right.png")
    assert file_dhash(tmp_path / "left.png") != file_dhash(tmp_path / "other.png")
    assets = [
        _approved("kept", "character", "left.png", "a1"),
        _approved("fresh", "item", "left.png", "b1"),
        {**_approved("waiting", "character", "left.png", "c1"), "status": "review"},
        _approved("ref", "character", "other.png"),
    ]
    caller = _Caller({"text": '{"score": 2, "reason": "photo"}'})
    asset = {"id": "nuevo", "kind": "character", "status": "generating"}
    metrics, warnings = note_style(caller.loopback, str(tmp_path), "lab", _game(*assets), asset, {"main": "right.png"}, {}, [])
    assert metrics["styleScore"] == 2
    assert warning_codes(warnings) == ["style_mismatch", "duplicate_of"]
    assert warnings[1]["ref"] == "kept"
    assert "kept" in warnings[1]["message"]

    quiet = _Caller(error=AssertionError("vision is off"))
    metrics, warnings = note_style(
        quiet.loopback, str(tmp_path), "lab", _game(*assets, vision=False), asset, {"main": "right.png"}, {"colors": 3}, ["kept"],
    )
    # Vision off skips only the call; the duplicate check is local and still runs.
    assert metrics == {"colors": 3}
    assert warnings[0] == "kept"
    assert warning_codes(warnings) == ["kept", "duplicate_of"]
    assert warnings[1]["ref"] == "kept"
    assert quiet.calls == []


def test_duplicates_skip_the_asset_itself_and_flat_images(tmp_path):
    _picture(tmp_path / "hero.png")
    Image.new("L", (32, 32), 40).save(tmp_path / "flat-a.png")
    Image.new("L", (32, 32), 200).save(tmp_path / "flat-b.png")
    own = {**_approved("heroe", "character", "hero.png"), "status": "approved"}
    _metrics, warnings = note_style(None, str(tmp_path), "lab", _game(own, vision=False), own, {"main": "hero.png"}, {}, [])
    assert warnings == []
    flat = _approved("lago", "tile", "flat-a.png")
    tile = {"id": "arena", "kind": "tile"}
    caller = _Caller({"score": 4})
    metrics, warnings = note_style(caller.loopback, str(tmp_path), "lab", _game(flat, refs=()), tile, {"main": "flat-b.png"}, {}, [])
    # Two plain tiles of different colours are not duplicates. ``lago`` is still the same-kind reference.
    assert warnings == []
    assert metrics == {"styleScore": 4}
    assert len(caller.calls) == 1


def test_duplicates_hash_the_picture_over_black(tmp_path):
    """Hidden RGB under transparent pixels must not tell two identical sprites apart."""
    shown = np.zeros((32, 32, 4), dtype=np.uint8)
    shown[:, :8, 3] = 255
    shown[:, 8:16] = (255, 255, 255, 255)
    hidden = shown.copy()
    hidden[:, 16:, :3] = (np.arange(16) // 4 % 2 * 255).astype(np.uint8)[None, :, None]  # stripes, fully transparent
    Image.fromarray(shown).save(tmp_path / "shown.png")
    Image.fromarray(hidden).save(tmp_path / "hidden.png")
    game = _game(_approved("kept", "sprite", "shown.png"), vision=False)
    _metrics, warnings = note_style(None, str(tmp_path), "lab", game, {"id": "pose", "kind": "sprite"}, {"main": "hidden.png"}, {}, [])
    assert warning_codes(warnings) == ["duplicate_of"]
    assert warnings[0]["ref"] == "kept"


def test_each_approved_picture_is_decoded_once(tmp_path):
    peers = []
    for index in range(4):
        _picture(tmp_path / f"peer-{index}.png", flip=bool(index % 2))
        peers.append(_approved(f"peer-{index}", "character", f"peer-{index}.png"))
    _picture(tmp_path / "hero.png")
    game = _game(*peers, vision=False)
    for _ in range(5):
        note_style(None, str(tmp_path), "lab", game, HERO, {"main": "hero.png"}, {}, [])
    assert game_qa._cached_dhash.cache_info().misses == 5


def test_style_qa_defaults_on_and_can_be_disabled():
    assert normalize_style({})["qa"] == {"vision": True}
    assert normalize_style({"qa": {"vision": False}})["qa"]["vision"] is False
    assert normalize_style({"qa": {"vision": "no"}})["qa"]["vision"] is True


def test_turning_vision_off_keeps_the_style_approval_and_the_fingerprints():
    library, game = create_game({}, {"id": "bosque", "title": "Bosque"}, now=NOW)
    library, game = upsert_assets(library, "bosque", [{"id": "heroe", "kind": "character"}], False, now=NOW)
    digest = asset_inputs(game, game["assets"][0])
    library, _asset = add_attempt(library, "bosque", "heroe", {"id": "a1", "status": "ok", "inputs": digest, "createdAt": NOW}, now=NOW)
    library, _asset = approve_attempt(library, "bosque", "heroe", "a1", now=NOW)
    before = next(item for item in library["games"] if item["id"] == "bosque")
    _library, after = update_game(library, "bosque", {"style": {"qa": {"vision": False}}}, before["revision"], now=NOW)
    assert after["style"]["qa"] == {"vision": False}
    assert after["style"]["revision"] == before["style"]["revision"]
    assert after["style"]["approval"] == before["style"]["approval"]
    assert after["assets"][0]["status"] == "approved"
    assert asset_inputs(after, after["assets"][0]) == digest



def test_stamp_attempt_keeps_files_decision_and_asset_status():
    from services.game_library import add_attempt, approve_attempt, create_game, stamp_attempt, upsert_assets

    now = "2026-10-07T00:00:00Z"
    library, _game = create_game({}, {"id": "bosque", "title": "Bosque"}, now=now)
    library, _game = upsert_assets(library, "bosque", [{"id": "heroe", "kind": "character"}], False, now=now)
    library, _asset = add_attempt(library, "bosque", "heroe", {"id": "a1", "status": "ok", "createdAt": now, "files": {"main": "game/x.png"}}, now=now)
    library, _asset = approve_attempt(library, "bosque", "heroe", "a1", now=now)
    library, asset = stamp_attempt(library, "bosque", "heroe", "a1", metrics={"styleScore": 4}, warnings=["style_mismatch"], now=now)
    attempt = asset["attempts"][0]
    assert (attempt["files"], attempt["decision"], asset["status"]) == ({"main": "game/x.png"}, "approved", "approved")
    assert (attempt["metrics"], attempt["warnings"]) == ({"styleScore": 4}, ["style_mismatch"])
