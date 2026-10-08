"""Fixes found making Uncanny Valley 1x02 through MCP, and the agent guide."""
from __future__ import annotations

import copy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.series_guide import create_series_guide_router
from services.job_lifecycle import new_media_files
from services.series_guide import audio_files, build_bible, compact_episode, guide_text
from services.series_language_versions import (
    localized_view, normalize_language_versions, set_version_duration, set_version_take, take_length_floor,
)
from services.series_library import _merge_episode_shot_patch, series_canon_inputs_changed


def episode():
    take = {"id": "a1", "status": "completed", "settings": {"sourceDurationSeconds": 1.71}, "outputAssetIds": ["take-es"]}
    take_en = {"id": "a1en", "status": "completed", "settings": {"sourceDurationSeconds": 2.17}, "outputAssetIds": ["take-en"]}
    return {"id": "ep2", "number": 2, "title": "El vecino", "shots": [
        {"id": "e2s06", "durationSeconds": 1.71, "approvedAttemptId": "a1", "attempts": [take, take_en],
         "layout2d": {"framing": "close", "music": {"file": "mus-theme-es.wav", "volume": 0.8, "start": 0}},
         "dialogueBeats": [{"id": "e2s06_b0", "characterId": "kevin", "text": "¡¿CIEN MILLONES?!"}]}],
        "languageVersions": {"english": {"dialogue": {"e2s06_b0": "ONE HUNDRED MILLION?!"}, "cards": {}, "approvedAttemptIds": {}}}}


def series(ep=None):
    return {"id": "uv-es", "title": "Valle Inquietante", "spokenLanguage": "Español de España", "canon": {"approval": "approved"},
            "characters": [{"id": "kevin", "name": "Kevin", "voiceProfile": {"characterKitRef": {"id": "uv-kevin"}}},
                           {"id": "trump", "name": "Trump"}],
            "locations": [{"id": "street", "name": "Calle", "referenceAssetIds": ["bg"], "variants": [{"id": "day"}],
                           "layout2d": {"anchors": {"fortress": {"u": 0.09, "v": 0.63}}}}],
            "assets": {"take-es": {"metadata": {"language": "spanish", "duration": 1.71, "sceneFilename": "e2s06.scene.json"}},
                       "take-en": {"metadata": {"language": "english", "duration": 2.17, "sceneFilename": "e2s06-en.scene.json"}}},
            "episodesById": {"ep2": ep or episode()}}


def test_a_version_keeps_its_own_lengths_music_and_approvals():
    ep = episode()
    ep["languageVersions"]["english"].update(durations={"e2s06": 2.17, "ghost": 3, "e2s07": -1}, music={"e2s06": "mus-theme-en.wav", "x": "a/b.wav"})
    versions = normalize_language_versions(ep["languageVersions"], ep["shots"], "spanish")
    assert versions["english"]["durations"] == {"e2s06": 2.17} and versions["english"]["music"] == {"e2s06": "mus-theme-en.wav"}
    ep["languageVersions"] = versions
    s = series(ep)
    _, view = localized_view(s, ep, "english")
    shot = view["shots"][0]
    assert shot["durationSeconds"] == 2.17 and shot["layout2d"]["music"]["file"] == "mus-theme-en.wav"
    assert ep["shots"][0]["durationSeconds"] == 1.71 and ep["shots"][0]["layout2d"]["music"]["file"] == "mus-theme-es.wav"


def test_version_takes_set_the_version_length_and_imports_check_their_own_language():
    ep = episode()
    s = series(ep)
    assert take_length_floor(s, ep, ep["shots"][0], "spanish") == 1.71
    assert take_length_floor(s, ep, ep["shots"][0], "english") == 0, "no English length until its first take"
    set_version_take(ep, "english", "e2s06", "a1en")
    assert ep["languageVersions"]["english"]["approvedAttemptIds"] == {"e2s06": "a1en"}
    assert ep["languageVersions"]["english"]["durations"] == {"e2s06": 2.17}
    assert ep["shots"][0]["approvedAttemptId"] == "a1" and ep["shots"][0]["durationSeconds"] == 1.71, "the original is untouched"
    set_version_duration(ep, "english", "e2s06", 2.5)
    assert take_length_floor(s, ep, ep["shots"][0], "english") == 2.5
    with pytest.raises(ValueError):
        set_version_take(ep, "french", "e2s06", "a1en")
    with pytest.raises(KeyError):
        set_version_take(ep, "english", "nope", "a1en")


def test_importing_a_version_take_is_measured_against_that_version(monkeypatch):
    import services.video_editor as video_editor
    from services.series_production import attach_series_import
    ep = episode()
    ep["languageVersions"]["english"]["durations"] = {"e2s06": 2.17}
    s = series(ep)
    s["allowedProductionMethods"] = ["animation_2d"]
    ep["shots"][0]["productionMethod"] = "animation_2d"
    ep["shots"][0]["durationSeconds"] = 2.17  # the English render once wrote its length on the shot
    monkeypatch.setattr(video_editor, "probe_media", lambda path: {"duration": 1.71, "width": 1920, "height": 1080})
    spanish = {"id": "new-es", "ownerType": "shot", "ownerId": "e2s06", "kind": "video", "metadata": {"language": "spanish"}}
    with pytest.raises(ValueError, match="shorter"):
        attach_series_import(s, spanish, as_take=True, source_path="x.mp4")
    ep["shots"][0]["durationSeconds"] = 1.71
    attach_series_import(s, spanish, as_take=True, source_path="x.mp4")
    english = {"id": "new-en", "ownerType": "shot", "ownerId": "e2s06", "kind": "video", "metadata": {"language": "english"}}
    with pytest.raises(ValueError, match="shorter"):
        attach_series_import(s, english, as_take=True, source_path="x.mp4"), "1.71 s is short for the 2.17 s English shot"


def test_resending_a_shot_keeps_the_length_its_take_set():
    current = episode()["shots"]
    incoming = [{**copy.deepcopy(current[0]), "durationSeconds": 5.0, "layout2d": {"framing": "medium"}}]
    merged = _merge_episode_shot_patch(current, incoming)
    assert merged[0]["durationSeconds"] == 1.71 and merged[0]["layout2d"] == {"framing": "medium"}
    fresh = _merge_episode_shot_patch(current, [*incoming, {"id": "e2s07", "durationSeconds": 5.0}])
    assert fresh[1]["durationSeconds"] == 5.0, "a shot without an imported take keeps the editor's length"


def test_staging_a_location_or_a_3d_plate_leaves_the_canon_approved():
    from services.series_production import attach_series_import
    before = series()
    staged = copy.deepcopy(before)
    staged["locations"][0]["layout2d"] = {"anchors": {"fortress": {"u": 0.1, "v": 0.6}}, "plateAssetId": "plate", "plate3d": {"status": "done"}}
    assert not series_canon_inputs_changed(before, staged)
    renamed = copy.deepcopy(before)
    renamed["locations"][0]["description"] = "Otra calle"
    assert series_canon_inputs_changed(before, renamed)
    plate = {"id": "plate", "ownerType": "location", "ownerId": "street", "kind": "video", "metadata": {"referenceRole": "plate3d"}}
    attach_series_import(staged, plate)
    assert staged["canon"]["approval"] == "approved" and staged["locations"][0]["referenceAssetIds"] == ["bg"]
    reference = {"id": "ref2", "ownerType": "location", "ownerId": "street", "kind": "image", "metadata": {"referenceRole": "environment"}}
    attach_series_import(staged, reference)
    assert staged["canon"]["approval"] == "draft", "a new reference image is a canon change"


def test_outputs_are_media_files_only(tmp_path):
    before = {"old.wav"}
    for name in ("old.wav", "sfx2-pen.wav", ".maestro-tasks-v1.sqlite3-wal", "_tmp.wav", "sfx2-pen.meta.json", "image.png"):
        (tmp_path / name).write_bytes(b"x")
    assert new_media_files(str(tmp_path), before) == ["image.png", "sfx2-pen.wav"]


def test_document_commands_accept_the_workspace_every_tool_sends():
    from services.scene_commands import EffectsApply
    document = {"version": 1, "duration": 2, "width": 1920, "height": 1080, "fps": 24, "layers": []}
    assert EffectsApply.model_validate({"document": document, "workspace": "uncanny-valley", "cues": []}).workspace == "uncanny-valley"


def test_the_bible_lists_what_an_agent_may_use():
    kits = {"uv-kevin": {"base": {"source": "k.png"}, "poses": {"panic": {}}, "mouth": {"closed": {}},
                         "voicesByLanguage": {"english": {}, "spanish": {}}}}
    bible = build_bible(series(), kits, ["mus-theme-es.wav", "sfx2-pen.wav", "ln-x.wav", ".hidden.wav", "voice-a.wav", "bg.png"])
    kevin, trump = bible["characters"]
    assert kevin["kitId"] == "uv-kevin" and kevin["poses"] == ["base", "panic"] and kevin["voices"] == ["english", "spanish"] and kevin["rigged"]
    assert "missing" in trump, "a character without a kit is flagged before a render fails"
    street = bible["locations"][0]
    assert street["variants"] == ["day"] and street["anchors"]["fortress"]["u"] == 0.09 and street["hasImage"]
    assert bible["audio"] == {"music": ["mus-theme-es.wav"], "sfx": ["sfx2-pen.wav"], "other": []}
    assert bible["nextEpisode"] == {"number": 3, "idPrefix": "e3s", "scenePrefix": "e3_"}
    assert bible["episodes"][0]["shots"] == 1 and "languageVersions" in bible["episodes"][0]
    assert "## A shot" in guide_text() and "series.episode.render_native" in guide_text()
    assert audio_files(["mus-a.wav", "x.mp3"])["other"] == ["x.mp3"]


def test_a_compact_episode_keeps_layout_lines_and_takes():
    ep = episode()
    ep["shots"][0]["transitionIn"] = {"kind": "fade_black", "seconds": 0.8}
    compact = compact_episode(series(ep), ep)
    shot = compact["shots"][0]
    assert shot["layout2d"]["framing"] == "close" and shot["dialogueBeats"][0]["text"].startswith("¡¿CIEN")
    assert shot["transitionIn"] == {"kind": "fade_black", "seconds": 0.8}
    assert shot["takes"][0] == {"id": "a1", "status": "completed", "language": "spanish", "seconds": 1.71, "sceneFilename": "e2s06.scene.json"}
    assert "attempts" not in shot and compact["languageVersions"]["english"]["dialogue"]
    assert "transitionIn" in guide_text() and "fade_black" in guide_text() and "dip_white" in guide_text()


def test_the_guide_names_the_production_lessons():
    """Lessons that cost hours, and the real series.update merge. Growth stays within 15% of 40364 bytes."""
    guide = guide_text()
    assert len(guide.encode()) <= int(40364 * 1.15)
    for phrase in (
        "keeps every top-level field you omit",
        "ambienceByLocation",
        "base_revision",
        "JSON copy",
        "boats, waves, crowds, rain",
        "image_start",
        "image_end",
        "last 14 frames",
        "10–13 key shots",
        "shot_ids",
        "One kit per character",
        "voice-over",
        "12 frames",
        "85–155 Hz",
        "165–255 Hz",
        "pitch_range",
        "magenta",
        "output_name",
        "nvidia-smi",
        "assets included",
    ):
        assert phrase in guide, phrase


def test_the_guide_routes(tmp_path):
    (tmp_path / "mus-theme-es.wav").write_bytes(b"x")
    app = FastAPI()
    app.include_router(create_series_guide_router(read_library=lambda ws: {"seriesById": {"uv-es": series()}},
                                                  read_kits=lambda ws: {}, workspace_dir=lambda ws: str(tmp_path)))
    client = TestClient(app)
    assert client.get("/api/v1/series-agent/guide").json()["guide"].startswith("# Making an episode")
    guide = client.get("/api/v1/series/uv-es/guide", params={"workspace": "uv"}).json()
    assert guide["bible"]["audio"]["music"] == ["mus-theme-es.wav"]
    assert client.get("/api/v1/series/uv-es/episodes/ep2/compact", params={"workspace": "uv"}).json()["shots"][0]["id"] == "e2s06"
    assert client.get("/api/v1/series/nope/guide", params={"workspace": "uv"}).status_code == 404


def test_the_series_profile_names_real_series_tools():
    from services.mcp_profiles import PROFILES
    from services.series_commands import command_catalog
    names = {item["name"] for item in command_catalog()}
    series_tools = {name for name in PROFILES["series"]["tools"] if name.startswith(("series.", "characters."))}
    assert series_tools <= names, series_tools - names
    assert {"series.guide", "series.episode.get"} <= names
    readonly = {item["name"]: item["mutation"] for item in command_catalog()}
    assert readonly["series.guide"] is False and readonly["series.episode.get"] is False
