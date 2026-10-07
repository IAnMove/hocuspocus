"""Style check and duplicate warnings. The analyzer is simulated."""
import copy

from PIL import Image

from services.game_generators import REGISTRY
from services.game_generators.base import AttemptResult
from services.game_library import normalize_style
from services.game_produce import GameProduce, ProduceDeps
from services.game_qa import dhash, note_style, style_check


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
    image.save(path)


def test_style_json_ignores_the_text_around_it():
    caller = _Caller({"text": 'Sure {"score": 4, "reason": "same ink"} thanks'})
    checked = style_check(caller, "hero.png", ["a.png", "b.png", "c.png", "d.png"])
    assert checked == {"score": 4, "reason": "same ink"}
    media = caller.calls[0][1]["params"]["media"]
    assert [item["source"] for item in media] == ["a.png", "b.png", "c.png", "hero.png"]
    assert caller.calls[0][0] == "analyze"


def test_analyze_down_does_not_break_the_batch(tmp_path, monkeypatch):
    caller = _Caller(error=OSError("down"))
    checked = style_check(caller, "hero.png", [])
    assert checked["score"] is None
    assert checked["reason"] == "style_check_unavailable"

    class Generator:
        def estimate(self, _game, _asset):
            return {"image": 1}

        def run(self, ctx):
            return AttemptResult(
                files={"main": "hero.png"}, metrics={"attemptIds": [ctx.attempt_id]},
                warnings=[], provenance={"steps": []},
            )

    game = {"id": "bosque", "assets": [{"id": "heroe", "kind": "character", "status": "pending", "dependsOn": [], "spec": {}, "candidates": 1}]}
    saved = {}

    def write_attempt(_workspace, _game_id, asset_id, attempt, status):
        saved["attempt"] = attempt
        saved["status"] = status
        game["assets"][0]["status"] = status

    monkeypatch.setitem(REGISTRY, "character", Generator())
    service = GameProduce(ProduceDeps(
        call=lambda _tool, _args: {},
        loopback=caller.loopback,
        workspace_dir=lambda _name: str(tmp_path),
        read_game=lambda _workspace, _game_id: copy.deepcopy(game),
        write_attempt=write_attempt,
        inline=True,
    ))
    job = service.start("lab", "bosque")
    assert job["status"] == "completed"
    assert job["steps"][0]["status"] == "done"
    assert saved["status"] == "review"
    assert "style_check_unavailable" in saved["attempt"]["warnings"]
    assert "styleScore" not in saved["attempt"]["metrics"]


def test_duplicate_of_an_approved_sibling(tmp_path):
    left = tmp_path / "left.png"
    right = tmp_path / "right.png"
    other = tmp_path / "other.png"
    _picture(left, flip=False)
    _picture(right, flip=False)
    _picture(other, flip=True)
    assert dhash(str(left)) == dhash(str(right))
    assert dhash(str(left)) != dhash(str(other))
    game = {"assets": [
        {"id": "kept", "kind": "character", "status": "approved", "approvedAttemptId": "a1", "attempts": [
            {"id": "a1", "files": {"main": str(left)}},
        ]},
        {"id": "fresh", "kind": "item", "status": "approved", "approvedAttemptId": "b1", "attempts": [
            {"id": "b1", "files": {"main": str(left)}},
        ]},
    ]}
    asset = {"id": "nuevo", "kind": "character", "status": "generating"}
    caller = _Caller({"text": '{"score": 2, "reason": "photo"}'})
    metrics, warnings = note_style(
        caller.loopback, str(tmp_path), "lab", {**game, "style": {}}, asset,
        {"main": str(right)}, {}, [],
    )
    assert metrics["styleScore"] == 2
    assert "style_mismatch" in warnings
    assert "duplicate_of:kept" in warnings
    assert "duplicate_of:fresh" not in warnings

    quiet = _Caller(error=AssertionError("vision is off"))
    metrics, warnings = note_style(
        quiet.loopback, str(tmp_path), "lab",
        {"assets": game["assets"], "style": {"qa": {"vision": False}}},
        asset, {"main": str(other)}, {"colors": 3}, ["kept"],
    )
    assert metrics == {"colors": 3}
    assert warnings == ["kept"]
    assert quiet.calls == []


def test_style_qa_defaults_on_and_can_be_disabled():
    assert normalize_style({})["qa"] == {"vision": True}
    assert normalize_style({"qa": {"vision": False}})["qa"]["vision"] is False
    assert normalize_style({"qa": {"vision": "no"}})["qa"]["vision"] is True
