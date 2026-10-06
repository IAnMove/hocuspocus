"""The last open items of docs/development/MCP_RECOVERABILITY.md: machine translations, kept scripts, publications, origin."""
import asyncio
import copy
import json
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.music_productions import create_music_productions_router
from routers.series_language_versions import create_series_language_versions_router
from routers.series_produce import create_series_produce_router
from services import series_commands
from services.agent_activity import ActorHeaderMiddleware, caller_scope
from services.mcp_profiles import SERIES_TOOLS
from services.output_origin import filter_by_origin, output_origin
from services.production_publication import latest_publication, publication_handlers, record_publication
from services.series_language_versions import clear_checked, normalize_language_versions, version_from_translation
from services.series_produce import ProduceDeps, SeriesProduce
from services.series_script_history import MAX_REVISIONS, list_scripts, read_script, record_script
from tests.test_output_completion_time import list_test_outputs
from tests.test_series_language_versions import episode, series

AGENT = {"surface": "mcp", "tool": "external_agent"}
TRANSLATION = {"title": "Pilot", "lines": [{"id": "b1", "text": "Okay, Gary."}, {"id": "b2", "text": "Hi!"}],
               "cards": [{"shotId": "s0", "title": "VALLEY", "body": "Episode 1"}]}


# 1. Machine translations -------------------------------------------------------------------------------------------

def test_a_translation_marks_every_line_card_and_title_it_wrote():
    version = version_from_translation(TRANSLATION, episode(), requested_by="agent", now="2026-10-06T10:00:00Z")
    assert version["machineTranslated"] == {"dialogue": ["b1", "b2"], "cards": ["s0"], "title": True,
                                            "translatedAt": "2026-10-06T10:00:00Z", "requestedBy": "agent"}
    partial = version_from_translation({"lines": [{"id": "b2", "text": "Hey!"}]}, episode(),
                                       {"title": "Pilot", "dialogue": {"b1": "Okay."}, "cards": {}}, requested_by="someone")
    assert partial["machineTranslated"]["dialogue"] == ["b2"] and "title" not in partial["machineTranslated"]
    assert partial["machineTranslated"]["requestedBy"] == "user"
    assert "machineTranslated" not in version_from_translation({"lines": []}, episode())


def test_the_library_keeps_marks_only_for_lines_and_cards_the_version_has():
    marks = {"dialogue": ["b1", "b2", "ghost"], "cards": ["s0", "s9"], "title": True, "requestedBy": "wizard"}
    raw = {"english": {"title": "", "dialogue": {"b1": "Okay."}, "cards": {}, "machineTranslated": marks}}
    kept = normalize_language_versions(raw, episode()["shots"], "spanish")["english"]
    assert kept["machineTranslated"] == {"dialogue": ["b1"], "cards": [], "requestedBy": "wizard"}
    gone = normalize_language_versions({"english": {"dialogue": {}, "machineTranslated": marks}}, episode()["shots"], "spanish")
    assert "machineTranslated" not in gone["english"]


def test_a_persons_edit_clears_the_mark_of_what_they_wrote():
    version = version_from_translation(TRANSLATION, episode(), requested_by="agent")
    checked = clear_checked(version, {"dialogue": {"b1": "Okay, Gary!"}, "cards": {"s0": {"title": "VALLEY", "body": ""}}})
    assert checked["machineTranslated"]["dialogue"] == ["b2"] and checked["machineTranslated"]["cards"] == []
    assert checked["machineTranslated"]["title"] is True
    done = clear_checked(checked, {"dialogue": {"b2": "Hi!"}, "title": "Pilot"})
    assert "machineTranslated" not in done and done["dialogue"] == version["dialogue"]


def test_the_router_marks_translations_and_only_a_person_clears_them():
    store = {"series": series()}

    def change(workspace, series_id, episode_id, apply):
        current = store["series"]
        apply(current, current["episodesById"][episode_id])
        episode_record = current["episodesById"][episode_id]
        episode_record["languageVersions"] = normalize_language_versions(episode_record["languageVersions"], episode_record["shots"], "spanish")
        return copy.deepcopy(current)

    app = FastAPI()
    app.add_middleware(ActorHeaderMiddleware)
    app.include_router(create_series_language_versions_router(
        change_episode=change, read_episode=lambda _w, _s, _e: (store["series"], store["series"]["episodesById"]["ep1"]),
        translate=lambda *_args: TRANSLATION))
    client = TestClient(app)
    path = "/api/v1/series/uv/episodes/ep1/language-versions/english"
    translated = client.post(f"{path}/translate", json={"workspace": "cast"}, headers={"X-Hocus-Actor": "agent"}).json()
    assert translated["version"]["machineTranslated"]["dialogue"] == ["b1", "b2"]
    assert translated["version"]["machineTranslated"]["requestedBy"] == "agent"
    by_agent = client.put(path, json={"workspace": "cast", "version": {"dialogue": {"b1": "Okay, pal."}}},
                          headers={"X-Hocus-Actor": "agent"}).json()
    assert by_agent["version"]["machineTranslated"]["dialogue"] == ["b1", "b2"], "an agent's rewrite is still unchecked"
    by_wizard = client.put(path, json={"workspace": "cast", "version": {"dialogue": {"b2": "Hello!"}}},
                           headers={"X-Hocus-UI-Surface": "wizard"}).json()
    assert by_wizard["version"]["machineTranslated"]["dialogue"] == ["b1", "b2"]
    by_person = client.put(path, json={"workspace": "cast", "version": {"dialogue": {"b1": "Okay, pal."}}}).json()
    assert by_person["version"]["machineTranslated"]["dialogue"] == ["b2"]
    assert by_person["version"]["machineTranslated"]["cards"] == ["s0"] and by_person["version"]["dialogue"]["b1"] == "Okay, pal."


# 2. The scripts of from_script -------------------------------------------------------------------------------------

def test_scripts_are_kept_per_episode_newest_first_and_the_same_script_counts_again(tmp_path):
    first = record_script(tmp_path, "uv", "ep2", {"shots": [1]}, by="agent", created=True, shots=1, languages=["spanish"],
                          now="2026-10-06T10:00:00Z")
    assert first["revision"] == 1 and first["by"] == "agent" and first["created"] is True and "script" not in first
    again = record_script(tmp_path, "uv", "ep2", {"shots": [1]}, by="user", created=False, shots=1, languages=["spanish"])
    assert again["revision"] == 1 and again["applied"] == 2 and again["lastBy"] == "user"
    second = record_script(tmp_path, "uv", "ep2", {"shots": [1, 2]}, by="wizard", created=False, shots=2, languages=["spanish"])
    restored = record_script(tmp_path, "uv", "ep2", {"shots": [1]}, by="user", created=False, shots=1, languages=["spanish"],
                             restored_from=1)
    assert (second["revision"], restored["revision"], restored["restoredFrom"]) == (2, 3, 1)
    assert [item["revision"] for item in list_scripts(tmp_path, "uv", "ep2")] == [3, 2, 1]
    assert read_script(tmp_path, "uv", "ep2")["script"] == {"shots": [1]}
    assert read_script(tmp_path, "uv", "ep2", 2)["script"] == {"shots": [1, 2]}
    assert list_scripts(tmp_path, "uv", "other") == []
    stored = list((tmp_path / ".series-scripts-v1").rglob("*.json"))
    assert [path.name for path in stored] == ["ep2.json"], "kept in a hidden folder, out of the gallery"


def test_only_the_newest_revisions_are_kept_and_odd_ids_stay_inside_the_folder(tmp_path):
    for index in range(MAX_REVISIONS + 3):
        record_script(tmp_path, "../uv", "ep/1", {"n": index}, by="agent", created=False, shots=0, languages=[])
    kept = list_scripts(tmp_path, "../uv", "ep/1")
    assert len(kept) == MAX_REVISIONS and kept[0]["revision"] == MAX_REVISIONS + 3
    assert all(tmp_path / ".series-scripts-v1" in path.parents for path in tmp_path.rglob("*.json"))


class ScriptTools:
    """The series tools from_script calls through LocalMcp, over one in-memory project."""

    def __init__(self):
        character = {"id": "kevin", "voiceProfile": {"characterKitRef": {"id": "kit-kevin"}}}
        self.series = {"id": "uv", "revision": 1, "spokenLanguage": "Español", "characters": [character],
                       "locations": [{"id": "garage", "variants": []}], "episodesById": {}}

    def __call__(self, tool, arguments):
        data = arguments["input"]
        if tool == "series.episode.create":
            number = len(self.series["episodesById"]) + 1
            self.series["episodesById"][f"ep{number}"] = {"id": f"ep{number}", "number": number, "shots": []}
            return {"result": {"episode": {"id": f"ep{number}"}}}
        if tool == "series.episode.update":
            self.series["episodesById"][data["episode_id"]]["shots"] = data["episode"]["shots"]
            self.series["revision"] += 1
        return {"result": {"missingLines": []}}


def script(text="Hola."):
    return {"title": {"es": "Piloto"}, "scenes": [{"id": "open", "location": "garage"}],
            "shots": [{"scene": "open", "lines": [{"who": "kevin", "es": text}]}]}


def _script_client(tmp_path):
    tools = ScriptTools()
    workspace_dir = lambda _name: str(tmp_path)
    service = SeriesProduce(ProduceDeps(call=tools, workspace_dir=workspace_dir, read_library=lambda _w: {}))
    app = FastAPI()
    app.add_middleware(ActorHeaderMiddleware)
    app.include_router(create_series_produce_router(
        service, call=tools, bind_loop=lambda _loop: None, read_library=lambda _w: {"seriesById": {"uv": tools.series}},
        read_kits=lambda _w: {"kit-kevin": {"poses": {}}}, workspace_dir=workspace_dir))
    return TestClient(app)


def test_from_script_keeps_what_was_written_and_rewrites_from_it(tmp_path):
    client = _script_client(tmp_path)
    checked = client.post("/api/v1/series/uv/episodes/from-script", json={"workspace": "cast", "script": script(), "check": True})
    assert checked.status_code == 200 and "scriptRevision" not in checked.json()
    assert client.get("/api/v1/series/uv/episodes/ep1/scripts", params={"workspace": "cast"}).json() == {"revisions": [], "total": 0}
    written = client.post("/api/v1/series/uv/episodes/from-script", json={"workspace": "cast", "script": script()},
                          headers={"X-Hocus-Actor": "agent"}).json()
    assert written["episodeId"] == "ep1" and written["scriptRevision"] == 1
    client.post("/api/v1/series/uv/episodes/from-script", json={"workspace": "cast", "script": script("Adiós."), "episodeId": "ep1"},
                headers={"X-Hocus-Actor": "agent"})
    listed = client.get("/api/v1/series/uv/episodes/ep1/scripts", params={"workspace": "cast"}).json()
    assert [(item["revision"], item["by"], item["created"]) for item in listed["revisions"]] == [(2, "agent", False), (1, "agent", True)]
    assert listed["revisions"][0]["shots"] == 1 and listed["revisions"][0]["languages"] == ["spanish"]
    assert "script" not in listed["revisions"][0]
    first = client.get("/api/v1/series/uv/episodes/ep1/scripts/1", params={"workspace": "cast"}).json()
    assert first["script"] == script() and first["tool"] == "series.episode.from_script"
    latest = client.get("/api/v1/series/uv/episodes/ep1/scripts/latest", params={"workspace": "cast"}).json()
    assert latest["revision"] == 2
    download = client.get("/api/v1/series/uv/episodes/ep1/scripts/1", params={"workspace": "cast", "download": True})
    assert download.json() == script() and 'filename="uv-ep1-script-r1.json"' in download.headers["content-disposition"]
    dry = client.post("/api/v1/series/uv/episodes/ep1/scripts/1/rewrite", json={"workspace": "cast", "check": True})
    assert dry.json()["checked"] is True
    rewritten = client.post("/api/v1/series/uv/episodes/ep1/scripts/1/rewrite", json={"workspace": "cast"}).json()
    assert rewritten["episodeId"] == "ep1" and rewritten["scriptRevision"] == 3
    newest = client.get("/api/v1/series/uv/episodes/ep1/scripts", params={"workspace": "cast"}).json()["revisions"][0]
    assert (newest["by"], newest["restoredFrom"], newest["created"]) == ("user", 1, False)
    assert client.get("/api/v1/series/uv/episodes/ep1/scripts/9", params={"workspace": "cast"}).status_code == 404
    assert client.get("/api/v1/series/uv/episodes/ep1/scripts/x", params={"workspace": "cast"}).status_code == 400
    assert client.post("/api/v1/series/uv/episodes/ep9/scripts/1/rewrite", json={"workspace": "cast"}).json()["detail"]["code"] == "no_script"


def test_the_mcp_tool_reads_the_kept_scripts(tmp_path):
    calls = []

    def request(method, path, *, query=None, body=None):
        calls.append((method, path))
        if path.endswith("/scripts"):
            return {"revisions": [{"revision": 2}, {"revision": 1}]}
        return {"revision": int(path.rsplit("/", 1)[1]) if path[-1].isdigit() else 2, "script": {"shots": []}}

    runner = series_commands._RUNNERS["series.episode.script.get"]
    data = {"workspace": "cast", "series_id": "uv", "episode_id": "ep1"}
    assert runner(data, request)["script"]["revision"] == 2 and calls[-1][1].endswith("/scripts/latest")
    assert runner({**data, "revision": 1}, request)["script"]["revision"] == 1
    assert runner(data, lambda *_a, **_k: {"revisions": []}) == {"revisions": [], "script": None}
    catalog = {item["name"]: item for item in series_commands.command_catalog()}
    assert catalog["series.episode.script.get"]["mutation"] is False and "series.episode.script.get" in SERIES_TOOLS
    assert "scriptRevision" in catalog["series.episode.from_script"]["description"]


# 3. Publications -----------------------------------------------------------------------------------------------------

def test_a_publication_is_remembered_and_the_card_links_its_page(tmp_path, monkeypatch):
    root = tmp_path / "film"
    root.mkdir()
    public = tmp_path / "public"
    for name in ("final.mp4", "sheet.jpg"):
        (root / name).write_bytes(name.encode())
    (root / "show.production.json").write_text(json.dumps({"status": "completed", "final": "final.mp4", "contact_sheet": "sheet.jpg",
                                                            "spec": {"title": "Night bus"}}))
    monkeypatch.setenv("HOCUS_PUBLICATION_ROOT", str(public))
    monkeypatch.setenv("HOCUS_PUBLICATION_BASE_URL", "http://127.0.0.1:8844")
    monkeypatch.delenv("HOCUS_PUBLICATION_SERVE", raising=False)
    handler = publication_handlers(lambda _ws: str(root))["production.publish"]
    arguments = {"version": 1, "input": {"workspace": "film", "production_id": "show", "mode": "preview"}}
    with caller_scope(AGENT):
        published = asyncio.run(handler(arguments))["result"]
    latest = latest_publication(root, "show")
    assert latest["page"] == published["page"] and latest["mode"] == "preview" and latest["published_by"] == "agent"
    assert latest["count"] == 1
    asyncio.run(handler(arguments))
    rows = json.loads((root / "show.publications.json").read_text())["publications"]
    assert len(rows) == 1 and rows[0]["first_published_at"] and rows[0]["published_by"] == "user"
    app = FastAPI()
    app.include_router(create_music_productions_router(workspace_dir=lambda _name: str(root)))
    client = TestClient(app)
    card = client.get("/api/v1/music-productions", params={"workspace": "film"}).json()["productions"][0]
    assert card["publication"]["page"] == published["page"] and card["publication"]["mode"] == "preview"
    assert client.get("/api/v1/music-productions/show", params={"workspace": "film"}).json()["production"]["publication"]["count"] == 1


def test_a_production_never_published_or_with_a_bad_link_has_no_publication(tmp_path):
    assert latest_publication(tmp_path, "show") is None
    record_publication(tmp_path, "show", {"publication_id": "x", "page": "javascript:alert(1)", "video": "", "mode": "release"})
    assert latest_publication(tmp_path, "show") is None


# 4. Origin in the gallery listing --------------------------------------------------------------------------------------

def test_the_origin_is_read_from_the_sidecar_like_the_details_panel():
    assert output_origin({"origin": {"tool": "external_agent", "capability": "generation.image"}}) == {
        "actor": "agent", "capability": "generation.image"}
    assert output_origin({"requested_by": {"tool": "external_agent", "capability": "studio.key"}, "origin": {"tool": "studio"}}) == {
        "actor": "agent", "capability": "studio.key"}
    assert output_origin({"origin": {"actor": "wizard", "tool": "wangp"}}) == {"actor": "wizard"}
    assert output_origin({"origin": {"actor": "agent", "capability": "None"}}) == {"actor": "agent"}
    assert output_origin({"origin": {"actor": "user", "tool": "wangp"}}) is None
    assert output_origin(None) is None and output_origin({"origin": "agent"}) is None
    rows = [{"name": "a", "origin": {"actor": "agent"}}, {"name": "w", "origin": {"actor": "wizard"}}, {"name": "u", "origin": None}]
    assert [row["name"] for row in filter_by_origin(rows, "agent")] == ["a", "w"]
    assert [row["name"] for row in filter_by_origin(rows, "mcp")] == ["a"]
    assert [row["name"] for row in filter_by_origin(rows, "wizard")] == ["w"]
    assert filter_by_origin(rows, "") == rows and filter_by_origin(rows, "robots") == []


def test_the_gallery_listing_carries_the_origin_and_filters_by_it(tmp_path):
    for index, (name, meta) in enumerate([
        ("agent.png", {"origin": {"tool": "external_agent", "capability": "generation.image"}}),
        ("wizard.mp4", {"origin": {"actor": "wizard"}}),
        ("mine.png", {"origin": {"actor": "user"}}),
        ("bare.wav", None),
    ]):
        media = tmp_path / name
        media.write_bytes(b"x")
        os.utime(media, (100.0 + index, 100.0 + index))
        if meta is not None:
            (tmp_path / f"{Path(name).stem}.meta.json").write_text(json.dumps(meta), encoding="utf-8")
    every = {item["name"]: item.get("origin") for item in list_test_outputs(tmp_path)}
    assert every == {"agent.png": {"actor": "agent", "capability": "generation.image"}, "wizard.mp4": {"actor": "wizard"},
                     "mine.png": None, "bare.wav": None}
    agents = list_test_outputs(tmp_path, origin="agent", limit=1)
    assert [item["name"] for item in agents] == ["wizard.mp4"], "filtered before paging, newest first"
    assert [item["name"] for item in list_test_outputs(tmp_path, origin="mcp")] == ["agent.png"]
    assert [item["name"] for item in list_test_outputs(tmp_path, origin="agent", media_type="image")] == ["agent.png"]
