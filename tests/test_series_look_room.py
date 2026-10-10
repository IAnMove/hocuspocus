"""Look room: from_script stands each 2D cast member with the open frame in front of their gaze; shot edits only warn."""
import asyncio
import copy

import pytest
from PIL import Image

from routers.series_shot_edit import ShotEdit, create_series_shot_edit_router
from services import pose_facing, series_look_room
from services.series_guide import build_bible
from services.series_library import normalize_series_library
from services.series_script import apply_script


def project():
    character = lambda cid: {"id": cid, "name": cid.title(), "voiceProfile": {"characterKitRef": {"id": f"kit-{cid}"}}}
    return {"id": "pu", "revision": 3, "spokenLanguage": "Español",
            "characters": [character(cid) for cid in ("ines", "rayo", "blas", "telmo")],
            "locations": [{"id": "deck", "variants": [], "layout2d": {"homes": {"telmo": 30}}}], "episodesById": {}}


def pose(facing=None, file=None):
    found = {"source": f"/api/v1/file/{file}?workspace=pu"} if file else {}
    return {**found, **({"facing": facing} if facing else {})}


KITS = {"kit-ines": {"base": pose(), "poses": {"ordena": pose("left"), "busto": pose("front")}},
        "kit-rayo": {"base": pose("right"), "poses": {"dispara": pose("right")}},
        "kit-blas": {"base": pose("right"), "poses": {}},
        "kit-telmo": {"base": pose("left"), "poses": {"rosario": pose()}}}


class Tools:
    """The series tools from_script calls, over an in-memory project; keeps the shots it writes."""

    def __init__(self):
        self.series, self.shots = project(), None

    def read(self):
        return self.series

    def __call__(self, tool, arguments):
        data = arguments["input"]
        if tool == "series.episode.create":
            self.series["episodesById"]["ep1"] = {"id": "ep1", "number": 1, "shots": []}
            return {"result": {"episode": {"id": "ep1"}}}
        if tool == "series.episode.update":
            self.shots = data["episode"]["shots"]
        return {"result": {}}


def script(*shots):
    return {"title": "El galeón", "scenes": [{"id": "deck", "location": "deck"}],
            "shots": [{"scene": "deck", "framing": "medium", **shot} for shot in shots]}


def run(*shots, kits=KITS, root=None, check=False):
    tools = Tools()
    result = apply_script(tools, tools.read, kits, set(), "pu", script(*shots), check_only=check, root=root)
    return result, [[(entry["characterId"], entry.get("x")) for entry in shot["layout2d"].get("cast") or []]
                    for shot in tools.shots or []]


def test_one_person_stands_on_the_side_away_from_their_gaze():
    result, cast = run({"cast": [["ines", "ordena", 30]]}, {"cast": [["rayo", "dispara", 72]]}, {"cast": [["ines", "busto", 30]]},
                       {"cast": [["ines", "ordena", 48]]}, {"cast": [["ines", "ordena", 80]]}, {"cast": [["ines", "base", 30]]},
                       {"framing": "wide", "cast": [["telmo"]]}, {"cast": [["rayo", "dispara", 31.5]]})
    assert cast == [[("ines", 70)], [("rayo", 28)], [("ines", 30)], [("ines", 48)], [("ines", 80)], [("ines", 30)],
                    [("telmo", 70)], [("rayo", 31.5)]]
    assert result["lookRoom"] == [
        {"shot": "e1s00", "character": "ines", "pose": "ordena", "facing": "left", "from": 30, "to": 70},
        {"shot": "e1s01", "character": "rayo", "pose": "dispara", "facing": "right", "from": 72, "to": 28},
        {"shot": "e1s06", "character": "telmo", "pose": "base", "facing": "left", "from": 30, "to": 70}]
    assert "lookRoomKept" not in result, "front, unknown and the centre band stay where they are"


def test_two_people_who_look_away_from_each_other_swap_places():
    result, cast = run({"framing": "two", "cast": [["ines", "ordena", 30], ["rayo", "base", 70]]},
                       {"framing": "two", "cast": [["rayo", "base", 32], ["ines", "ordena", 68]]},
                       {"framing": "two", "cast": [["ines", "ordena"], ["rayo", "base"]]},
                       {"framing": "two", "cast": [["blas", "base", 30], ["rayo", "base", 70]]})
    assert cast[0] == [("ines", 70), ("rayo", 30)] and cast[1] == [("rayo", 32), ("ines", 68)]
    assert cast[2] == [("ines", 66), ("rayo", 34)], "a cast without x is placed where the planner put it, then swapped"
    assert cast[3] == [("blas", 30), ("rayo", 70)]
    assert [(move["shot"], move["character"], move["from"], move["to"]) for move in result["lookRoom"]] == [
        ("e1s00", "ines", 30, 70), ("e1s00", "rayo", 70, 30), ("e1s02", "ines", 34, 66), ("e1s02", "rayo", 66, 34)]
    kept, = result["lookRoomKept"]
    assert kept["shot"] == "e1s03" and kept["character"] == "rayo" and "swapping does not help" in kept["reason"]


def test_three_or_more_are_reported_not_moved():
    result, cast = run({"framing": "wide", "cast": [["ines", "ordena", 20], ["rayo", "base", 50], ["blas", "base", 80]]})
    assert cast == [[("ines", 20), ("rayo", 50), ("blas", 80)]] and "lookRoom" not in result
    assert [(item["character"], item["x"]) for item in result["lookRoomKept"]] == [("ines", 20), ("blas", 80)]
    assert all("three or more" in item["reason"] for item in result["lookRoomKept"])


def test_lookroom_false_an_entrance_or_another_kind_of_shot_keeps_x():
    result, cast = run({"cast": [["ines", "ordena", 30, {"lookRoom": False}]]},
                       {"lookRoom": False, "cast": [["ines", "ordena", 30]]},
                       {"framing": "wide", "cast": [["ines", "ordena", 30, {"enterFrom": "left"}]]},
                       {"framing": "two", "cast": [["ines", "ordena", 30, {"enterFrom": "left"}], ["rayo", "base", 70]]},
                       {"cast": [{"characterId": "ines", "poseId": "ordena", "x": 30, "transform": {"x": 30, "y": 50, "scale": 1}}]})
    assert cast == [[("ines", 30)], [("ines", 30)], [("ines", 30)], [("ines", 30), ("rayo", 70)], [("ines", 30)]]
    assert "lookRoom" not in result and "lookRoomKept" not in result
    tools = Tools()
    apply_script(tools, tools.read, KITS, set(), "pu", script({"lookRoom": False, "cast": [["ines", "ordena", 30, {"lookRoom": False}]]}))
    stored = normalize_series_library({"seriesById": {"pu": {**tools.series, "episodesById": {"ep1": {
        "id": "ep1", "number": 1, "script": [{"id": "e1_deck", "locationId": "deck"}], "shots": tools.shots}}}}},
        "pu")["seriesById"]["pu"]["episodesById"]["ep1"]["shots"][0]
    assert stored["layout2d"]["lookRoom"] is False and stored["layout2d"]["cast"][0]["lookRoom"] is False, "the opt-out is kept"


def test_check_reports_the_moves_as_notes_and_writes_nothing():
    tools = Tools()
    checked = apply_script(tools, tools.read, KITS, set(), "pu", script({"cast": [["ines", "ordena", 30]]}), check_only=True)
    assert checked["checked"] is True and checked["lookRoom"][0]["to"] == 70 and tools.shots is None


def _cut_on_the_left(path):
    """A bust whose shoulder runs off its image's left border (edge snap holds it on the frame's left)."""
    image = Image.new("RGBA", (200, 300), (0, 0, 0, 0))
    image.paste((120, 80, 40, 255), (0, 120, 160, 300))
    image.save(path)


def test_poses_are_read_on_their_images_and_a_cut_pose_stays_on_its_cut_side(tmp_path, monkeypatch):
    pose_facing._CACHE.clear()
    _cut_on_the_left(tmp_path / "telmo-busto.png")
    Image.new("RGBA", (200, 300), (0, 0, 0, 0)).save(tmp_path / "rayo-free.png")
    looks = {(200, 300): {"facing": "left", "confidence": 0.8, "source": "face"}}
    monkeypatch.setattr(pose_facing, "detect", lambda image: looks.get(image.size))
    kits = {**KITS, "kit-telmo": {"base": pose(file="telmo-busto.png"), "poses": {"rosario": pose(file="rayo-free.png")}}}
    result, cast = run({"cast": [["telmo", "base", 35]]}, {"cast": [["telmo", "rosario", 35]]},
                       {"cast": [["telmo", "base", 35, {"edgeSnap": False}]]}, kits=kits, root=str(tmp_path))
    assert cast == [[("telmo", 35)], [("telmo", 65)], [("telmo", 65)]]
    kept, = result["lookRoomKept"]
    assert kept["shot"] == "e1s00" and "cut on its left side" in kept["reason"]


def test_the_bible_lists_which_way_each_pose_looks(tmp_path, monkeypatch):
    pose_facing._CACHE.clear()
    Image.new("RGBA", (10, 10)).save(tmp_path / "t.png")
    monkeypatch.setattr(pose_facing, "detect", lambda image: {"facing": "right", "confidence": 0.9, "source": "face"})
    kits = {**KITS, "kit-telmo": {"base": pose("left"), "poses": {"rosario": pose(file="t.png")}}}
    bible = build_bible(project(), kits, [], str(tmp_path))
    facing = {item["id"]: item.get("facing") for item in bible["characters"]}
    assert facing["ines"] == {"ordena": "left", "busto": "front"} and facing["telmo"] == {"base": "left", "rosario": "right"}
    assert build_bible(project(), kits, [])["characters"][3]["facing"] == {"base": "left"}, "without the workspace: the kit's own"


def test_a_shot_edit_that_leaves_someone_looking_out_is_kept_and_warned(tmp_path):
    tools = Tools()
    apply_script(tools, tools.read, KITS, set(), "pu", script({"cast": [["ines", "ordena", 70]]}, {"cast": [["rayo", "base", 30]]}))
    stored = {"seriesById": {"pu": {**tools.series, "episodesById": {"ep1": {
        "id": "ep1", "number": 1, "script": [{"id": "e1_deck", "locationId": "deck"}], "shots": tools.shots}}}}}

    class Store:
        series = normalize_series_library(stored, "pu")["seriesById"]["pu"]

        def read(self, _workspace):
            return {"seriesById": {"pu": copy.deepcopy(self.series)}}

        def change(self, _workspace, series_id, change):
            working = copy.deepcopy(self.series)
            change(working)
            self.series = normalize_series_library({"seriesById": {series_id: working}}, "pu")["seriesById"][series_id]
            return copy.deepcopy(self.series)

    store = Store()
    router = create_series_shot_edit_router(change_series=store.change, read_library=store.read, read_kits=lambda _ws: KITS,
                                            workspace_dir=lambda _ws: str(tmp_path), call=lambda *_: {}, bind_loop=lambda _loop: None)
    post = next(route.endpoint for route in router.routes if route.path.endswith("/shots/edit"))
    moved = [{"characterId": "ines", "poseId": "ordena", "x": 25}]
    checked = asyncio.run(post("pu", "ep1", ShotEdit(workspace="pu", shot=1, changes={"cast": moved}, check=True)))
    assert "x 75 gives look room" in checked["warnings"][0]
    reply = asyncio.run(post("pu", "ep1", ShotEdit(workspace="pu", shot=1, changes={"cast": moved})))
    assert reply["shot"]["script"]["cast"][0]["x"] == 25, "the user's edit wins"
    assert "ines (ordena) faces left at x 25" in reply["warnings"][0]
    quiet = asyncio.run(post("pu", "ep1", ShotEdit(workspace="pu", shot=2, changes={"camera": "push"})))
    assert "warnings" not in quiet, "an edit that leaves the cast alone says nothing"
    opted = asyncio.run(post("pu", "ep1", ShotEdit(workspace="pu", shot=1, changes={"cast": [{**moved[0], "lookRoom": False}]})))
    assert "warnings" not in opted


def test_warnings_read_a_stored_shot_without_moving_it():
    shot = {"id": "e1s04", "productionMethod": "animation_2d", "layout2d": {"framing": "two", "cast": [
        {"characterId": "ines", "poseId": "ordena", "x": 30}, {"characterId": "rayo", "poseId": "base", "x": 70}]}}
    before = copy.deepcopy(shot)
    found = series_look_room.warnings(project(), KITS, shot, None)
    assert len(found) == 2 and "x 70 gives look room" in found[0] and shot == before
    assert series_look_room.warnings(project(), KITS, {**shot, "productionMethod": "animation_3d"}, None) == []


@pytest.mark.parametrize("x, expected", [(44.9, 55.1), (45, 45), (10, 90)])
def test_the_centre_band_is_45_to_55(x, expected):
    _result, cast = run({"cast": [["ines", "ordena", x]]})
    assert cast == [[("ines", expected)]]
