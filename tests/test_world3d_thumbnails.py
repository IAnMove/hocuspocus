"""Our own rendered thumbnail of every Video 3D card: cached once per template version, never a broken image.

No GPU and no browser. A fake renderer paints a flat PNG where the owned browser would; one check runs the export's
real owned-browser script in Node against a fake Playwright module (skipped without Node).
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import shutil
import threading
import time
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from routers.world3d_templates import create_world3d_templates_router
from services import resource_scheduler, world3d_template_commands
from services import world3d_thumbnails as thumbs
from services.example_assets import ExampleAssets
from services.world3d_export import (
    World3DExportCancelled,
    World3DExportPending,
    export_plan,
    render_lane,
    write_png,
)
from services.world3d_scenes import World3DSceneError
from services.world3d_template_catalog import (
    builtin_card,
    builtin_cards,
    page_templates,
    search_report,
    suggest_templates,
)
from services.world3d_template_commands import command_catalog, execute_command
from services.world3d_thumbnails import (
    ThumbnailNeedsExamples,
    ThumbnailUnavailable,
    World3DThumbnails,
    paint_still,
    thumbnail_plan,
    thumbnail_recipe,
)

URL = "/api/v1/world3d/templates/{}/thumbnail"


def _document(template_id="two-shot", **overrides):
    document = {
        "version": 1, "units": "meters", "up": "y", "templateId": template_id, "width": 1920, "height": 1080,
        "fps": 30, "duration": 6, "playbackSpeed": 1,
        "camera": {"family": "establishment", "eye": [0, 1.6, 4.2], "look": [0, 1, 0], "fov": 50},
        "light": {"kind": "directional", "direction": [-0.35, -1, -0.25], "intensity": 1.15, "color": "#fff4e5"},
        "slots": [{"id": "subject_1", "slot": "subject_1", "position": [0, 0, 0], "rotationY": 0, "scale": 1,
                   "sourceUrl": "", "media": "image", "surface": "cutout", "clip": None}],
    }
    document.update(overrides)
    return document


class FakeRenderer:
    """Paints the plan's size in one colour; can wait on a gate, fail, or count how many paint at once."""

    def __init__(self, *, gate=None, fail=None):
        self.calls, self.active, self.most = [], 0, 0
        self.gate, self.fail = gate, fail
        self.started = threading.Event()
        self._guard = threading.Lock()

    def __call__(self, snapshot, staging, cancelled):
        with self._guard:
            self.calls.append(deepcopy(snapshot))
            self.active += 1
            self.most = max(self.most, self.active)
        self.started.set()
        try:
            if self.gate is not None:
                assert self.gate.wait(5)
            if self.fail is not None:
                raise self.fail
            plan = snapshot["plan"]
            path = Path(staging) / "frames" / "frame_000001.png"
            write_png(path, plan["width"], plan["height"], (40, 90, 160))
            return path
        finally:
            with self._guard:
                self.active -= 1


def _service(tmp_path, renderer=None, documents=None, **options):
    documents = {} if documents is None else documents

    def compile_document(template_id):
        return deepcopy(documents.get(template_id) or _document(template_id))

    return World3DThumbnails(outputs_dir=lambda: tmp_path / "default", renderer=renderer or FakeRenderer(),
                             compile_document=compile_document, **options)


def _client(tmp_path, service):
    app = FastAPI()
    app.include_router(create_world3d_templates_router(lambda workspace: str(tmp_path / workspace), thumbnails=service))
    return TestClient(app)


def _cache(tmp_path):
    folder = tmp_path / "default" / thumbs.FOLDER
    return sorted(path.name for path in folder.iterdir() if path.is_file()) if folder.is_dir() else []


def _staging_left(tmp_path):
    staging = tmp_path / "default" / thumbs.FOLDER / ".staging"
    return list(staging.iterdir()) if staging.is_dir() else []


def test_first_request_renders_and_caches_then_the_cache_serves(tmp_path):
    renderer = FakeRenderer()
    client = _client(tmp_path, _service(tmp_path, renderer))
    first = client.get(URL.format("two-shot"))
    assert first.status_code == 200, first.text
    assert first.headers["content-type"] == "image/webp" and first.headers["x-thumbnail-cache"] == "miss"
    with Image.open(io.BytesIO(first.content)) as image:
        assert image.format == "WEBP" and image.size == (640, 360)
    recipe = first.headers["x-thumbnail-recipe"]
    assert _cache(tmp_path) == [f"two-shot-{recipe}.webp"] and _staging_left(tmp_path) == []
    plan = renderer.calls[0]["plan"]
    assert plan["times"] == [3.0] and plan["count"] == 1 and plan["placeholders"] is True
    assert (plan["width"], plan["height"], plan["supersample"], plan["samples"]) == (640, 360, 2, 4)
    assert renderer.calls[0]["document"]["templateId"] == "two-shot"
    second = client.get(URL.format("two-shot"))
    assert second.status_code == 200 and second.headers["x-thumbnail-cache"] == "hit"
    assert second.content == first.content and len(renderer.calls) == 1


def test_stage_cards_and_portrait_cards_render_the_same_way(tmp_path):
    portrait_id = "topdown-dragon-portals"
    assert builtin_card(portrait_id)["format"] == "portrait"
    documents = {portrait_id: _document(portrait_id, width=1080, height=1920)}
    service = _service(tmp_path, FakeRenderer(), documents)
    stage = service.thumbnail("stage-bar")
    assert stage.path.name.startswith("stage-bar-") and not stage.cached
    with Image.open(service.thumbnail(portrait_id).path) as image:
        assert image.size == (360, 640)


def test_a_new_recipe_renders_again_and_drops_only_that_cards_old_picture(tmp_path, monkeypatch):
    renderer = FakeRenderer()
    documents = {"cine-dolly-zoom": _document("cine-dolly-zoom"), "cine-dolly-zoom-in": _document("cine-dolly-zoom-in")}
    service = _service(tmp_path, renderer, documents)
    old = service.thumbnail("cine-dolly-zoom")
    sibling = service.thumbnail("cine-dolly-zoom-in")
    documents["cine-dolly-zoom"] = _document("cine-dolly-zoom", duration=4)        # the template changed
    new = service.thumbnail("cine-dolly-zoom")
    assert not new.cached and new.recipe != old.recipe and len(renderer.calls) == 3
    assert _cache(tmp_path) == sorted([new.path.name, sibling.path.name])
    assert service.thumbnail("cine-dolly-zoom").cached
    monkeypatch.setattr(thumbs, "RENDER_RECIPE", thumbs.RENDER_RECIPE + 1)          # the renderer changed
    again = service.thumbnail("cine-dolly-zoom")
    assert not again.cached and again.recipe != new.recipe and len(renderer.calls) == 4


def test_the_recipe_is_the_document_and_the_renderer_recipe(monkeypatch):
    assert thumbnail_recipe(_document()) == thumbnail_recipe(_document())
    assert thumbnail_recipe(_document()) != thumbnail_recipe(_document(duration=5))
    before = thumbnail_recipe(_document())
    monkeypatch.setattr(thumbs, "RENDER_RECIPE", thumbs.RENDER_RECIPE + 1)
    assert thumbnail_recipe(_document()) != before
    plan = thumbnail_plan(_document(duration=6, playbackSpeed=2))
    assert plan["duration"] == 3 and plan["times"] == [1.5], "mid-shot in output seconds"


@pytest.mark.parametrize("template_id", ["nope", "user-mine", "bad%20id"])
def test_unknown_and_personal_ids_are_404(tmp_path, template_id):
    renderer = FakeRenderer()
    response = _client(tmp_path, _service(tmp_path, renderer)).get(URL.format(template_id))
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "unknown_template"
    assert renderer.calls == []


def test_an_id_the_template_tool_does_not_know_is_404(tmp_path):
    def compile_document(template_id):
        raise World3DSceneError("unknown_template", f"unknown_template:{template_id}", 404)

    service = World3DThumbnails(outputs_dir=lambda: tmp_path / "default", renderer=FakeRenderer(), compile_document=compile_document)
    assert _client(tmp_path, service).get(URL.format("two-shot")).status_code == 404


def _examples(tmp_path, data=b"diner"):
    """A manifest with one collection holding one picture; the cache starts empty (nothing downloaded)."""
    name = "creative/neon-diner.jpg"
    manifest = {"revision": 1, "files": {name: {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}},
                "collections": {"creative": {"files": [name], "dependencies": [], "archive": {"sha256": "x"}}}}
    return ExampleAssets(tmp_path / "examples-cache", manifest)


def _creative_document(*urls):
    document = _document("creative-neon-diner", width=720, height=1280)
    document["slots"] = [{**document["slots"][0], "id": f"slot-{index}", "sourceUrl": url} for index, url in enumerate(urls)]
    return document


def test_a_card_whose_example_media_is_not_installed_is_refused_at_once(tmp_path):
    renderer = FakeRenderer()
    documents = {"creative-neon-diner": _creative_document("/examples/creative/neon-diner.jpg?v=2", "/examples/gone.png")}
    service = _service(tmp_path, renderer, documents, examples=_examples(tmp_path))
    response = _client(tmp_path, service).get(URL.format("creative-neon-diner"))
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "examples_not_installed" and detail["retryable"] is False
    assert detail["collections"] == ["creative"] and detail["files"] == ["creative/neon-diner.jpg", "gone.png"]
    assert "creative" in detail["message"] and renderer.calls == [] and _cache(tmp_path) == []


def test_the_card_renders_once_its_collection_is_downloaded(tmp_path):
    renderer = FakeRenderer()
    assets = _examples(tmp_path)
    documents = {"creative-neon-diner": _creative_document("/examples/creative/neon-diner.jpg")}
    service = _service(tmp_path, renderer, documents, examples=assets)
    with pytest.raises(ThumbnailNeedsExamples):
        service.thumbnail("creative-neon-diner")
    entry = assets.entry("creative/neon-diner.jpg")
    assets.cache.mkdir(parents=True)
    (assets.cache / (entry["sha256"] + ".jpg")).write_bytes(b"diner")
    picture = service.thumbnail("creative-neon-diner")
    assert not picture.cached and len(renderer.calls) == 1
    assert thumbs.example_files(_creative_document("/examples/a.png?x=1", "/api/v1/uploads/b.png")) == {"a.png"}


def _unavailable(response, reason):
    assert response.status_code == 503, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "thumbnail_unavailable" and detail["reason"] == reason and detail["retryable"] is True
    assert response.headers["retry-after"] == str(thumbs.RETRY_AFTER_SECONDS)
    assert not response.headers["content-type"].startswith("image/")
    return detail


def test_a_missing_renderer_is_a_retryable_503_never_a_picture(tmp_path, monkeypatch):
    monkeypatch.setattr(thumbs, "renderer_available", lambda _url: False)
    service = World3DThumbnails(outputs_dir=lambda: tmp_path / "default", app_url=lambda: "",
                                compile_document=lambda template_id: _document(template_id))
    client = _client(tmp_path, service)
    _unavailable(client.get(URL.format("two-shot")), "renderer_unavailable")
    assert service.origin == "http://127.0.0.1:80", "the origin is the listening socket, as the export binds it"
    assert _cache(tmp_path) == []


@pytest.mark.parametrize(("failure", "reason"), [
    (World3DExportPending("real-render pending: no application URL"), "renderer_unavailable"),
    (RuntimeError("Headless world3d export failed: page crashed"), "render_failed"),
])
def test_a_failed_render_is_a_retryable_503_and_leaves_no_file(tmp_path, failure, reason):
    service = _service(tmp_path, FakeRenderer(fail=failure))
    detail = _unavailable(_client(tmp_path, service).get(URL.format("two-shot")), reason)
    assert str(failure) in detail["message"]
    assert _cache(tmp_path) == [] and _staging_left(tmp_path) == []


def test_a_frame_that_is_not_a_picture_is_never_served(tmp_path):
    def broken(snapshot, staging, cancelled):
        path = Path(staging) / "frame_000001.png"
        path.write_bytes(b"not a png")
        return path

    _unavailable(_client(tmp_path, _service(tmp_path, broken)).get(URL.format("two-shot")), "render_failed")
    assert _cache(tmp_path) == []


def test_the_lock_serialises_two_requests(tmp_path):
    gate = threading.Event()
    renderer = FakeRenderer(gate=gate)
    service = _service(tmp_path, renderer)
    results = {}

    def ask(template_id):
        results.setdefault(template_id, []).append(service.thumbnail(template_id))

    workers = [threading.Thread(target=ask, args=(name,)) for name in ("two-shot", "two-shot", "stage-bar")]
    workers[0].start()
    assert renderer.started.wait(5)
    for worker in workers[1:]:
        worker.start()
    time.sleep(0.2)
    assert renderer.active == 1, "the other requests wait for the render in progress"
    gate.set()
    for worker in workers:
        worker.join(10)
    assert renderer.most == 1
    assert sorted(snapshot["document"]["templateId"] for snapshot in renderer.calls) == ["stage-bar", "two-shot"]
    first, second = results["two-shot"]
    assert first.path == second.path and sorted([first.cached, second.cached]) == [False, True]


def test_a_request_that_cannot_wait_for_the_lock_is_told_to_come_back(tmp_path):
    gate = threading.Event()
    renderer = FakeRenderer(gate=gate)
    service = _service(tmp_path, renderer, lock_wait=0.05)
    worker = threading.Thread(target=service.thumbnail, args=("two-shot",))
    worker.start()
    try:
        assert renderer.started.wait(5)
        _unavailable(_client(tmp_path, service).get(URL.format("stage-bar")), "busy")
    finally:
        gate.set()
        worker.join(10)
    assert len(renderer.calls) == 1


def test_a_busy_render_lane_is_a_retryable_503(tmp_path, monkeypatch):
    monkeypatch.delenv("HOCUS_SCENE_RENDER_DEVICE", raising=False)
    held, release = threading.Event(), threading.Event()

    def export():
        with resource_scheduler.coordinator.acquire(render_lane(), task_id="world3d-export-running"):
            held.set()
            release.wait(10)

    holder = threading.Thread(target=export)
    holder.start()
    renderer = FakeRenderer()
    try:
        assert held.wait(5)
        service = _service(tmp_path, renderer, lane_wait=0.1)
        _unavailable(_client(tmp_path, service).get(URL.format("two-shot")), "gpu_busy")
    finally:
        release.set()
        holder.join(10)
    assert renderer.calls == [] and _staging_left(tmp_path) == []


def test_a_render_that_overruns_its_timeout_is_stopped(tmp_path):
    def stuck(snapshot, staging, cancelled):
        while not cancelled():
            time.sleep(0.01)
        raise World3DExportCancelled()

    service = _service(tmp_path, stuck, timeout=0.1)
    with pytest.raises(ThumbnailUnavailable) as stopped:
        service.thumbnail("two-shot")
    assert stopped.value.reason == "timeout"


def test_cards_point_at_our_render_and_the_json_stays_free_of_urls(tmp_path):
    assert all(card["preview"] is None for card in builtin_cards())
    cocina = search_report("cocina")["templates"][0]
    assert cocina["id"] == "stage-cocina" and cocina["preview"] == URL.format("stage-cocina")
    dolly = search_report("dolly zoom")["templates"][0]
    assert dolly["id"] == "cine-dolly-zoom" and dolly["preview"] == URL.format("cine-dolly-zoom")
    stages = page_templates(kind="stage")["templates"]
    assert stages and all(card["preview"] == URL.format(card["id"]) for card in stages)
    suggested = suggest_templates(line="persecución a pie", beat="speed")["templates"]
    assert suggested and all(card["preview"] == URL.format(card["id"]) for card in suggested)
    assert all(card["reference"] is None or card["reference"].startswith("http") for card in stages + [dolly])
    workspace = tmp_path / "studio"
    workspace.mkdir()
    (workspace / "world3d-user-templates.json").write_text(json.dumps({"templates": [
        {"id": "user-mine", "title": "Mine", "document": _document("user-mine")}]}), encoding="utf-8")
    personal = page_templates("mine", workspace_dir=lambda name: str(tmp_path / name), workspace="studio")["templates"]
    assert [card["id"] for card in personal][:1] == ["user-mine"] and personal[0]["preview"] is None


def test_templates_get_returns_the_preview_url(tmp_path, monkeypatch):
    monkeypatch.setattr(world3d_template_commands, "compile_template_document", lambda template_id: _document(template_id))
    root = lambda workspace: str(tmp_path / workspace)
    got = execute_command("world3d.templates.get", {"version": 1, "input": {"workspace": "studio", "template_id": "stage-plaza"}}, root)
    result = got["result"]
    assert result["previewUrl"] == URL.format("stage-plaza") and result["card"]["preview"] == result["previewUrl"]
    assert builtin_card("stage-plaza")["preview"] is None, "the cached catalogue card is not changed"
    (tmp_path / "studio").mkdir()
    (tmp_path / "studio" / "world3d-user-templates.json").write_text(json.dumps({"templates": [
        {"id": "user-mine", "title": "Mine", "document": _document("user-mine")}]}), encoding="utf-8")
    mine = execute_command("world3d.templates.get", {"version": 1, "input": {"workspace": "studio", "template_id": "user-mine"}}, root)
    assert mine["result"]["previewUrl"] is None and mine["result"]["card"]["preview"] is None


def test_the_tools_say_preview_is_our_render_and_reference_is_inspiration():
    tools = {tool["name"]: tool["description"] for tool in command_catalog()}
    assert "previewUrl, the URL of our own render" in tools["world3d.templates.get"]
    assert "reference is a film still" in tools["world3d.templates.get"].replace("The card's reference", "reference")
    assert "preview is the URL of our own render" in tools["world3d.templates.list"]
    assert "reference is a film still of the real technique, for inspiration only" in tools["world3d.templates.list"]


_FAKE_PLAYWRIGHT = """
import fs from 'node:fs';
const record = entry => fs.appendFileSync(process.env.FAKE_PLAYWRIGHT_LOG, JSON.stringify(entry) + '\\n');
const PNG = 'data:image/png;base64,__PNG__';
globalThis.window = { __world3dExport: {
  load(scene, size) { record({ call: 'load', size, templateId: scene.templateId }); },
  frame(seconds) { record({ call: 'frame', seconds }); return PNG; },
  checkGeometry() { record({ call: 'geometry' }); return { verdict: 'ok', samples: 0, warnings: [] }; },
  audio() { record({ call: 'audio' }); return ''; },
  dispose() { record({ call: 'dispose' }); },
} };
const page = {
  async goto(url) { record({ call: 'goto', url }); },
  async waitForFunction(fn, arg) { if (!fn(arg)) throw new Error('no bridge'); },
  async evaluate(fn, arg) { return fn(arg); },
  async close() {},
};
export const chromium = { async launch() { return { async newPage() { return page; }, async close() {} }; } };
"""


def _fake_playwright(tmp_path, monkeypatch):
    frame = tmp_path / "flat.png"
    write_png(frame, 640, 360, (200, 120, 40))
    module = tmp_path / "playwright" / "index.mjs"
    module.parent.mkdir()
    module.write_text(_FAKE_PLAYWRIGHT.replace("__PNG__", base64.b64encode(frame.read_bytes()).decode()), encoding="utf-8")
    log = tmp_path / "playwright.log"
    monkeypatch.setenv("FAKE_PLAYWRIGHT_LOG", str(log))
    monkeypatch.setenv("HOCUS_SCENE_RENDER_DEVICE", "cpu")
    return module, log


def _calls(log):
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


@pytest.mark.skipif(not shutil.which("node"), reason="needs Node to run the owned-browser script")
def test_the_owned_browser_paints_one_still_at_mid_shot_with_placeholders(tmp_path, monkeypatch):
    module, log = _fake_playwright(tmp_path, monkeypatch)
    monkeypatch.setattr(thumbs, "playwright_module", lambda: module)
    monkeypatch.setattr(thumbs, "renderer_available", lambda _url: True)
    service = World3DThumbnails(outputs_dir=lambda: tmp_path / "default", app_url=lambda: "http://127.0.0.1:9",
                                compile_document=lambda template_id: _document(template_id))
    picture = service.thumbnail("two-shot")
    with Image.open(picture.path) as image:
        assert image.format == "WEBP" and image.size == (640, 360)
    calls = _calls(log)
    assert [call["call"] for call in calls] == ["goto", "load", "frame", "dispose"], "no geometry report, no sound"
    assert calls[0]["url"] == "http://127.0.0.1:9/world3d-render.html"
    assert calls[1]["size"]["placeholders"] is True and calls[1]["templateId"] == "two-shot"
    assert calls[2]["seconds"] == 3.0


@pytest.mark.skipif(not shutil.which("node"), reason="needs Node to run the owned-browser script")
def test_an_export_plan_without_times_still_paints_every_frame_with_geometry_and_sound(tmp_path, monkeypatch):
    module, log = _fake_playwright(tmp_path, monkeypatch)
    document = _document(duration=2 / 30, width=64, height=64)
    snapshot = {"workspace": "default", "document": document, "refs": [], "plan": export_plan(document)}
    staging = tmp_path / "staging"
    staging.mkdir()
    frame = paint_still(snapshot, staging, lambda: False, app_url="http://127.0.0.1:9", module=module)
    assert frame.name == "frame_000001.png" and len(list((staging / "frames").glob("*.png"))) == 2
    calls = [call["call"] for call in _calls(log)]
    assert calls == ["goto", "load", "geometry", "frame", "frame", "audio", "dispose"]
