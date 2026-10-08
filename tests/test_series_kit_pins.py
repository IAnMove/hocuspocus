"""An episode can pin Character Kit revisions, and a later save keeps the old drawing."""
import asyncio
import json

import pytest
from fastapi import HTTPException

from services.character_kit_library import (
    HISTORY_REVISIONS,
    kit_revision_path,
    patch_character_kit,
    read_character_kit_library,
    read_kit_revision,
    write_character_kit_library,
)
from services.mcp_profiles import SERIES_TOOLS
from services.series_commands import OPERATIONS, command_handlers
from services.series_kit_pins import kits_for_episode, pin_episode_kits, update_episode_kits
from services.series_library import (
    create_series_episode,
    create_series_project,
    read_series_library,
    write_series_library,
)
from services.series_native_render import NativeRenderDeps, SeriesNativeRender
from services.series_take_inputs import render_inputs

VOICE = {"provider": "local", "model": "qwen3_tts_customvoice", "voiceId": "ryan"}


def asset(asset_id, source):
    return {
        "id": asset_id, "name": asset_id, "source": source, "kind": "image",
        "alphaStatus": "transparent", "reviewState": "approved",
    }


def kit(kit_id="luma", source="luma-point.png", **extra):
    body = {
        "version": 1, "id": kit_id, "name": kit_id.title(), "style": "cutout",
        "base": asset(f"{kit_id}-base", f"{kit_id}-base.png"),
        "poses": {"point": asset(f"{kit_id}-point", source)},
        "mouth": {"closed": asset(f"{kit_id}-closed", f"{kit_id}-closed.png")},
        "anchors": {"base": {"mouth": {"offsetX": 0, "offsetY": -2, "scale": .12, "rotation": 0}}},
        "provenance": [],
    }
    body.update(extra)
    return body


def character(character_id, kit_id, name):
    return {"id": character_id, "name": name, "voiceProfile": {"characterKitRef": {"id": kit_id}}}


def shot(shot_id, character_id, order=1):
    return {
        "id": shot_id, "sceneId": "scene-1", "order": order, "productionMethod": "animation_2d",
        "durationSeconds": 2, "visibleCharacterIds": [character_id],
    }


def add_episode(series, shots, title):
    scene_id = f"scene-{title.lower()}"
    episode = create_series_episode(
        series, title=title, script=[{"id": scene_id, "purpose": "A room", "dialogue": []}],
        shots=[{**item, "sceneId": scene_id} for item in shots],
    )
    series.setdefault("episodesById", {})[episode["id"]] = episode
    return episode


def write_project(folder, series):
    return write_series_library(str(folder), {"workspaceId": "default", "seriesById": {series["id"]: series}}, "default")


def approve(folder, series_id, episode_id, shot_id, kits):
    """Store a take whose fingerprint is the shot as the library normalized it."""
    library = read_series_library(str(folder))
    series = library["seriesById"][series_id]
    episode = series["episodesById"][episode_id]
    stored = next(item for item in episode["shots"] if item["id"] == shot_id)
    digest = render_inputs(series, stored, kits, str(folder))
    asset_id = f"asset-{shot_id}"
    attempt_id = f"attempt-{shot_id}"
    stored["attempts"] = [{"id": attempt_id, "status": "completed", "outputAssetIds": [asset_id]}]
    stored["approvedAttemptId"] = attempt_id
    series.setdefault("assets", {})[asset_id] = {
        "id": asset_id, "kind": "video", "uri": f"assets/{asset_id}.mp4",
        "ownerType": "attempt", "ownerId": attempt_id, "metadata": {"renderInputs": digest},
    }
    write_series_library(str(folder), library, "default")
    library = read_series_library(str(folder))
    series = library["seriesById"][series_id]
    episode = series["episodesById"][episode_id]
    stored = next(item for item in episode["shots"] if item["id"] == shot_id)
    fresh = render_inputs(series, stored, kits, str(folder))
    if fresh != series["assets"][asset_id]["metadata"]["renderInputs"]:
        series["assets"][asset_id]["metadata"]["renderInputs"] = fresh
        write_series_library(str(folder), library, "default")
    return fresh


def renderer(folder):
    root = str(folder)
    return SeriesNativeRender(NativeRenderDeps(
        call=lambda _name, _data: {},
        workspace_dir=lambda _workspace: root,
        read_library=lambda _workspace: read_series_library(root),
        read_kits=lambda _workspace: read_character_kit_library(root).get("kits") or {},
    ))


def test_a_pose_change_keeps_the_old_drawing_and_ignores_a_client_revision(tmp_path):
    old = tmp_path / "luma-old.png"
    old.write_bytes(b"png-old")
    first = patch_character_kit(tmp_path, "luma", kit(source="luma-old.png"), base_revision=0)
    assert first["kits"]["luma"]["revision"] == 1
    assert first["revision"] == 1
    assert not list(tmp_path.glob(".character-kit-revisions/*.json"))
    second = patch_character_kit(
        tmp_path, "luma", kit(source="luma-new.png", revision=99), base_revision=first["revision"],
    )
    assert second["kits"]["luma"]["revision"] == 2
    assert second["kits"]["luma"]["poses"]["point"]["source"] == "luma-new.png"
    history = json.loads((tmp_path / ".character-kit-revisions" / "luma.v1.json").read_text())
    assert history["poses"]["point"]["source"] == "luma-old.png"
    voiced = patch_character_kit(
        tmp_path, "luma", kit(source="luma-new.png", voice=VOICE), base_revision=second["revision"],
    )
    assert voiced["kits"]["luma"]["revision"] == 3
    assert voiced["kits"]["luma"]["voice"]["voiceId"] == "ryan"
    library = voiced
    for index in range(9):
        library = patch_character_kit(
            tmp_path, "luma", kit(source=f"pose-{index}.png", voice=VOICE), base_revision=library["revision"],
        )
    per_kit = sorted((tmp_path / ".character-kit-revisions").glob("luma.v*.json"))
    snapshots = list(tmp_path.glob(".character-kit-library-v1.json.v*.json"))
    assert len(per_kit) == 11
    assert len(snapshots) == HISTORY_REVISIONS
    assert (tmp_path / ".character-kit-revisions" / "luma.v1.json").is_file()
    assert old.is_file()


def test_a_kit_saved_before_pinning_is_remembered_as_revision_zero(tmp_path):
    written = write_character_kit_library(
        tmp_path, {"version": 1, "revision": 0, "activeId": "luma", "kits": {"luma": kit(source="luma-old.png")}},
        base_revision=0,
    )
    assert "revision" not in written["kits"]["luma"]
    patched = patch_character_kit(tmp_path, "luma", kit(source="luma-new.png"), base_revision=written["revision"])
    assert patched["kits"]["luma"]["revision"] == 1
    remembered = read_kit_revision(str(tmp_path), "luma", 0)
    assert remembered["poses"]["point"]["source"] == "luma-old.png"
    assert kit_revision_path(str(tmp_path), "luma", 0)


def test_a_pinned_episode_keeps_its_take_and_the_unpinned_one_goes_stale(tmp_path):
    library = patch_character_kit(tmp_path, "luma", kit(source="luma-old.png"), base_revision=0)
    series = create_series_project("default", title="Pins")
    series["allowedProductionMethods"] = ["animation_2d"]
    series["characters"] = [character("ana", "luma", "Ana")]
    held = add_episode(series, [shot("held", "ana")], "Held")
    open_episode = add_episode(series, [shot("open", "ana")], "Open")
    write_project(tmp_path, series)
    kits = read_character_kit_library(str(tmp_path))["kits"]
    approve(tmp_path, series["id"], held["id"], "held", kits)
    approve(tmp_path, series["id"], open_episode["id"], "open", kits)
    bare = {key: value for key, value in kits["luma"].items() if key != "revision"}
    stored = read_series_library(str(tmp_path))["seriesById"][series["id"]]
    held_shot = stored["episodesById"][held["id"]]["shots"][0]
    assert render_inputs(stored, held_shot, kits) == render_inputs(stored, held_shot, {"luma": bare})
    assert kits_for_episode(kits, stored["episodesById"][open_episode["id"]], str(tmp_path)) is kits
    patch_character_kit(tmp_path, "luma", kit(source="luma-new.png"), base_revision=library["revision"])
    pin_episode_kits(str(tmp_path), series["id"], held["id"], {"luma": 1}, workspace_name="default")
    latest = read_character_kit_library(str(tmp_path))["kits"]
    pinned_episode = read_series_library(str(tmp_path))["seriesById"][series["id"]]["episodesById"][held["id"]]
    resolved = kits_for_episode(latest, pinned_episode, str(tmp_path))
    assert resolved["luma"]["poses"]["point"]["source"] == "luma-old.png"
    assert resolved is not latest
    old_hash = render_inputs(stored, held_shot, {"luma": read_kit_revision(str(tmp_path), "luma", 1)})
    new_hash = render_inputs(stored, held_shot, latest)
    assert old_hash != new_hash
    render = renderer(tmp_path)
    assert render.stale_shots("default", series["id"], held["id"]) == []
    assert render.stale_shots("default", series["id"], open_episode["id"]) == ["open"]


def test_updating_one_kit_stales_only_that_characters_shots(tmp_path):
    library = patch_character_kit(tmp_path, "ana", kit("ana", "ana-old.png"), base_revision=0)
    library = patch_character_kit(tmp_path, "bob", kit("bob", "bob-old.png"), base_revision=library["revision"])
    series = create_series_project("default", title="Pins")
    series["allowedProductionMethods"] = ["animation_2d"]
    series["characters"] = [character("ana", "ana", "Ana"), character("bob", "bob", "Bob")]
    episode = add_episode(series, [
        shot("ana-shot", "ana", 1), shot("bob-shot", "bob", 2), shot("loose", "ana", 3),
    ], "Shared")
    write_project(tmp_path, series)
    kits = read_character_kit_library(str(tmp_path))["kits"]
    approve(tmp_path, series["id"], episode["id"], "ana-shot", kits)
    approve(tmp_path, series["id"], episode["id"], "bob-shot", kits)
    pin_episode_kits(str(tmp_path), series["id"], episode["id"], workspace_name="default")
    library = patch_character_kit(tmp_path, "ana", kit("ana", "ana-new.png"), base_revision=library["revision"])
    patch_character_kit(tmp_path, "bob", kit("bob", "bob-new.png"), base_revision=library["revision"])
    updated = update_episode_kits(str(tmp_path), series["id"], episode["id"], "ana", workspace_name="default")
    assert updated["kitPins"] == {"ana": 2, "bob": 1}
    assert updated["stale"] == [{"shotId": "ana-shot", "characterId": "ana", "kitId": "ana"}]
    again = update_episode_kits(str(tmp_path), series["id"], episode["id"], "ana", workspace_name="default")
    assert again["stale"] == []
    assert again["revision"] == updated["revision"]


def test_the_pin_tools_run_in_process_and_belong_to_the_series_profile(tmp_path):
    assert "series.episode.kits.pin" in OPERATIONS and "series.episode.kits.pin" in SERIES_TOOLS
    assert "series.episode.kits.update" in OPERATIONS and "series.episode.kits.update" in SERIES_TOOLS
    patch_character_kit(tmp_path, "luma", kit(), base_revision=0)
    series = create_series_project("default", title="Pins")
    series["allowedProductionMethods"] = ["animation_2d"]
    series["characters"] = [character("ana", "luma", "Ana")]
    episode = add_episode(series, [shot("held", "ana")], "Held")
    empty = add_episode(series, [], "Empty")
    write_project(tmp_path, series)
    handlers = command_handlers(lambda: "", lambda _name: str(tmp_path), lambda: str(tmp_path))
    result = asyncio.run(handlers["series.episode.kits.pin"]({
        "version": 1, "input": {"workspace": "default", "series_id": series["id"], "episode_id": episode["id"]},
    }))
    assert result["result"]["kitPins"] == {"luma": 1}
    with pytest.raises(HTTPException) as caught:
        asyncio.run(handlers["series.episode.kits.pin"]({
            "version": 1, "input": {"workspace": "default", "series_id": series["id"], "episode_id": empty["id"]},
        }))
    assert caught.value.status_code == 422
