"""Comic view of a montage: printed frames cached in the workspace, not a new comic."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi import FastAPI, Response
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFilter

from routers.montages import create_montages_router
from services.asset_catalog import scan_asset_catalog
from services.kernel.paths import safe_join
from services.montage_commands import MontageCommands, command_catalog
from services.montage_comic import comic_panels, laplacian_variance, sample_times
from services.montage_documents import MontageError, MontageStore, export_body, normalize_montage

WS = "comicdemo"
FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")


def _montage(**clip):
    body = {"id": "c1", "source": "shot.mp4", "trimStart": 0, "trimEnd": 10}
    body.update(clip)
    return {"version": 1, "name": "Bird", "width": 1080, "height": 1920, "fps": 24, "clips": [body], "soundtrack": None}


def _store(tmp_path: Path) -> MontageStore:
    def workspace_dir(name: str) -> str:
        path = tmp_path / name
        path.mkdir(parents=True, exist_ok=True)
        return str(path)
    return MontageStore(workspace_dir)


def _png(path: Path, sharp: bool) -> None:
    image = Image.new("RGB", (32, 48), "white")
    if sharp:
        draw = ImageDraw.Draw(image)
        for x in range(0, 32, 3):
            draw.line((x, 0, x, 48), fill="black")
    else:
        image = image.filter(ImageFilter.GaussianBlur(2))
    image.save(path)


def _commands(tmp_path: Path) -> MontageCommands:
    return MontageCommands(_store(tmp_path), start_export=lambda _body: {}, get_export=lambda job: {"job_id": job})


def test_samples_cover_the_middle_of_the_trim():
    assert sample_times(0, 10) == [2.0, 3.5, 5.0, 6.5, 8.0]
    assert sample_times(1, 1) == [1.0]


def test_laplacian_prefers_a_sharp_picture(tmp_path: Path):
    sharp, blur = tmp_path / "sharp.png", tmp_path / "blur.png"
    _png(sharp, True)
    _png(blur, False)
    assert laplacian_variance(sharp) > laplacian_variance(blur)


def test_comic_is_optional_and_export_ignores_it(tmp_path: Path):
    raw = _montage()
    once = normalize_montage(raw)
    assert "comic" not in json.dumps(once)
    again = normalize_montage(json.loads(json.dumps(once)))
    assert again == once
    store = _store(tmp_path)
    saved = store.save(WS, once)
    path = tmp_path / WS / saved["file"]
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["clips"] == once["clips"]
    updated = store.save(WS, {key: value for key, value in stored.items() if key not in {"revision", "updatedAt"}},
                         file=saved["file"], expected_revision=1)
    reloaded = json.loads(path.read_text(encoding="utf-8"))
    assert updated["revision"] == 2
    assert reloaded["clips"] == stored["clips"]
    with_comic = normalize_montage(_montage(comic={"frame": 1.25, "text": "bubble"}, lyric="hola"))
    assert with_comic["clips"][0]["comic"] == {"frame": 1.25, "text": "bubble"}
    assert "comic" not in export_body(with_comic, WS)["clips"][0]
    assert "lyric" not in export_body(with_comic, WS)["clips"][0]
    with pytest.raises(MontageError):
        normalize_montage(_montage(comic={"text": "shout"}))
    assert normalize_montage(_montage(comic={}))["clips"][0].get("comic") is None


def _run(tmp_path: Path, **kwargs):
    root = tmp_path / WS
    root.mkdir(parents=True, exist_ok=True)
    (root / "shot.mp4").write_bytes(b"video")
    Image.new("RGB", (2, 2), "red").save(root / "loose.png")
    store = _store(tmp_path)
    store.save(WS, _montage(**kwargs.pop("clip", {})))
    calls: list[float] = []
    prints: list[tuple] = []

    def extract(_source, dest, at):
        calls.append(round(float(at), 3))
        color = (0, 0, 0) if round(float(at), 3) == 3.5 else (255, 255, 255)
        Image.new("RGB", (32, 48), color).save(dest)

    def printer(source, dest, _seed, box=None):
        prints.append(box)
        Image.open(source).save(dest)

    def score(path: Path) -> float:
        with Image.open(path) as opened:
            return 10.0 if opened.getpixel((0, 0)) == (0, 0, 0) else 1.0

    result = comic_panels(store, WS, "Bird.montage.json", extract=extract, score=score, printer=printer,
                          duration_of=lambda _path: 10.0, **kwargs)
    return result, calls, prints, root, store


def test_default_frame_is_the_sharpest_sample_and_the_second_call_hits_the_cache(tmp_path: Path):
    result, calls, prints, root, store = _run(tmp_path)
    assert calls == [2.0, 3.5, 5.0, 6.5, 8.0]
    assert result["panels"][0]["at"] == 3.5
    assert result["panels"][0]["clip_id"] == "c1"
    assert prints == [(0, 0, 32, 48, 32, 48)]
    assert result["panels"][0]["width"] == 32 and result["panels"][0]["height"] == 48
    assert result["panels"][0]["frame"].startswith("/api/v1/file/.comic-panels/")
    assert result["panels"][0]["print"].startswith("/api/v1/file/.comic-panels/")
    cached = comic_panels(store, WS, "Bird.montage.json",
                          extract=lambda *_args: pytest.fail("cache miss"),
                          score=lambda _path: 0.0,
                          printer=lambda *_args: pytest.fail("print miss"),
                          duration_of=lambda _path: 10.0)
    assert cached["panels"][0]["at"] == 3.5
    assert cached["panels"][0]["frame"] == result["panels"][0]["frame"]
    _assert_hidden(tmp_path, root)


def test_frame_override_and_saved_comic_frame(tmp_path: Path):
    result, calls, _prints, _root, _store = _run(tmp_path, frames={"c1": 1.5}, clip={"comic": {"frame": 4, "text": "caption"}})
    assert calls == [1.5]
    assert result["panels"][0]["at"] == 1.5


def test_saved_comic_frame_is_used_when_the_request_has_none(tmp_path: Path):
    saved, calls, _prints, _root, _store = _run(tmp_path, clip={"comic": {"frame": 4, "text": "none"}})
    assert calls == [4.0]
    assert saved["panels"][0]["at"] == 4.0


def test_commands_http_and_mcp_share_the_operation(tmp_path: Path):
    launch = Path(__file__).resolve().parents[1].joinpath("app", "_launch_runtime.py").read_text(encoding="utf-8")
    assert "montage_command_catalog()" in launch and "_montage_commands.handlers()" in launch
    names = [item["name"] for item in command_catalog()]
    assert "montages.comic.panels" in names and "montages.shots.get" in names
    root = tmp_path / WS
    root.mkdir(parents=True)
    (root / "shot.mp4").write_bytes(b"video")
    commands = _commands(tmp_path)
    commands.store.save(WS, _montage())

    def extract(_source, dest, _at):
        _png(Path(dest), True)

    from services import montage_comic
    original = montage_comic.comic_panels

    def wrapped(store, workspace, file, **kwargs):
        kwargs.setdefault("extract", extract)
        kwargs.setdefault("score", lambda _path: 1.0)
        kwargs.setdefault("printer", lambda source, dest, _seed, box=None: Image.open(source).save(dest))
        kwargs.setdefault("duration_of", lambda _path: 10.0)
        return original(store, workspace, file, **kwargs)

    montage_comic.comic_panels = wrapped
    try:
        assert "montages.comic.panels" in commands.handlers()
        app = FastAPI()
        app.include_router(create_montages_router(commands))
        client = TestClient(app)
        response = client.post(f"/api/v1/montages/Bird.montage.json/comic/panels", json={"workspace": WS, "clip_ids": ["c1"]})
        assert response.status_code == 200
        assert response.json()["panels"][0]["clip_id"] == "c1"
        via_mcp = client.get("/api/v1/montages/commands").json()
        assert "montages.comic.panels" in {item["name"] for item in via_mcp["operations"]}
        refused = client.post(f"/api/v1/montages/Bird.montage.json/comic/panels", json={"workspace": WS, "clip_ids": ["missing"]})
        assert refused.status_code == 422
    finally:
        montage_comic.comic_panels = original


def _assert_hidden(tmp_path: Path, root: Path) -> None:
    from services import output_listing
    previous = (output_listing._workspace_dir, output_listing._load_favorites, output_listing._safe_join, output_listing.wgp)
    try:
        output_listing._output_scan_cache.clear()
        output_listing.configure(workspace_dir=lambda name: str(tmp_path / name), load_favorites=lambda: set(),
                                 safe_join=safe_join, engine=type("Engine", (), {"server_config": {"save_path": str(tmp_path)}})())
        listed = output_listing.list_outputs(Response(), workspace=WS)
    finally:
        output_listing._workspace_dir, output_listing._load_favorites, output_listing._safe_join, output_listing.wgp = previous
        output_listing._output_scan_cache.clear()
    names = {item["name"] for item in listed["outputs"]}
    hidden = {path.name for path in (root / ".comic-panels").iterdir()}
    assert "loose.png" in names and "shot.mp4" in names
    assert names.isdisjoint(hidden)
    assert not any(name.startswith(".") for name in names)
    catalog = scan_asset_catalog([{"workspace_id": WS, "path": str(root)}])
    filenames = {item["filename"] for item in catalog["assets"]}
    assert "loose.png" in filenames and filenames.isdisjoint(hidden)
    assert any(path.suffix == ".png" for path in (root / ".comic-panels").iterdir())


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg is required")
def test_real_frame_is_printed_and_cached(tmp_path: Path):
    root = tmp_path / WS
    root.mkdir(parents=True)
    video = root / "shot.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=64x64:rate=8:duration=2",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)], check=True)
    store = _store(tmp_path)
    store.save(WS, _montage(trimEnd=2, comic={"text": "caption"}))
    first = comic_panels(store, WS, "Bird.montage.json", clip_ids=["c1"])
    panel = first["panels"][0]
    assert panel["width"] == 64 and panel["height"] == 64
    printed = root / ".comic-panels" / Path(panel["print"].split("?", 1)[0]).name
    assert printed.is_file() and printed.stat().st_size > 0
    before = sorted((path.name, path.stat().st_mtime_ns) for path in (root / ".comic-panels").glob("*.png"))
    second = comic_panels(store, WS, "Bird.montage.json", clip_ids=["c1"])
    after = sorted((path.name, path.stat().st_mtime_ns) for path in (root / ".comic-panels").glob("*.png"))
    assert second["panels"][0]["at"] == panel["at"]
    assert before == after
