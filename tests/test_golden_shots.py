"""scripts/golden_shots.py: a local change fails, live servers are refused, references are kept, new takes are compared."""
from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

_SPEC = importlib.util.spec_from_file_location("golden_shots", Path(__file__).resolve().parents[1] / "scripts/golden_shots.py")
assert _SPEC and _SPEC.loader
golden = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(golden)


def _frame(path: Path, seed: int = 7) -> Path:
    """A 1080p frame with texture, like a painted background."""
    rows, cols = np.mgrid[0:1080, 0:1920]
    base = 120 + 60 * np.sin(cols / 37.0) * np.cos(rows / 23.0)
    noise = np.random.default_rng(seed).normal(0, 12, (1080, 1920))
    Image.fromarray(np.clip(base + noise, 0, 255).astype(np.uint8)).convert("RGB").save(path)
    return path


def test_a_mouth_sized_change_on_a_1080p_frame_fails(tmp_path):
    before = _frame(tmp_path / "before.png")
    image = np.array(Image.open(before))
    image[520:560, 920:1000] = 0
    after = tmp_path / "after.png"
    Image.fromarray(image).save(after)
    assert golden.ssim_score(before, before) == 1.0
    assert golden.ssim_score(before, after) < golden.DEFAULT_SSIM
    assert golden.ssim_score(before, tmp_path / "before.png", window=4096) == 1.0
    Image.fromarray(image[:1000]).save(after)
    assert golden.ssim_score(before, after) == 0.0


@pytest.mark.parametrize("url", [None, "", "http://127.0.0.1:42003", "http://localhost:42042/", "ftp://127.0.0.1:42021"])
def test_render_refuses_a_missing_url_and_the_live_instances(url):
    with pytest.raises(SystemExit):
        golden.test_server(url)


def test_render_needs_an_explicit_test_server(tmp_path):
    assert golden.test_server("http://127.0.0.1:42021/") == "http://127.0.0.1:42021"
    (tmp_path / "manifest.json").write_text(json.dumps({"shots": []}), encoding="utf-8")
    (tmp_path / "token").write_text("secret", encoding="utf-8")
    with pytest.raises(SystemExit, match="--base-url"):
        golden.main(["render", "--golden-dir", str(tmp_path), "--token-file", str(tmp_path / "token")])


def test_record_keeps_existing_references_unless_forced(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"shots": [{"id": "rig", "kind": "rig"}]}), encoding="utf-8")
    assert golden.command_record(tmp_path) == 0
    metrics = tmp_path / "refs" / "rig" / "metrics.json"
    metrics.write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit, match="--force"):
        golden.command_record(tmp_path)
    assert metrics.read_text(encoding="utf-8") == "{}"
    assert golden.main(["record", "--force", "--golden-dir", str(tmp_path)]) == 0
    assert json.loads(metrics.read_text(encoding="utf-8"))["keyframes"] == ["f0.png"]


def test_check_compares_the_takes_fetched_after_a_render(tmp_path, monkeypatch):
    media = tmp_path / "media"
    media.mkdir()
    _frame(media / "e1s01.png")
    row = {"id": "pu-e1s01", "media": "media/e1s01.png", "workspace": "cast", "series_id": "uv",
           "episode_id": "ep1", "shot_id": "e1s01"}
    (tmp_path / "manifest.json").write_text(json.dumps({"shots": [row]}), encoding="utf-8")
    (tmp_path / "token").write_text("secret", encoding="utf-8")
    golden.command_record(tmp_path)
    assert golden.command_check(tmp_path) == 0, "before a render, the recorded copy is compared"

    calls = []
    def post(url, token, payload):
        calls.append((url, payload["params"]["name"], payload["params"]["arguments"]["input"]))
        if payload["params"]["name"] == "series.episode.render_native":
            return {"result": {"structuredContent": {"result": {"job": {"jobId": "native-1"}}}}}
        return {"result": {"structuredContent": {"result": {"job": {"jobId": "native-1", "items": [
            {"shotId": "e1s01", "status": "done", "video": "export e1s01.png"}, {"shotId": "e1s02", "status": "running"}]}}}}}
    changed = _frame(tmp_path / "changed.png", seed=8)
    downloads = []
    def download(url, token, target):
        downloads.append(url)
        shutil.copyfile(changed, target)
    monkeypatch.setattr(golden, "_post_json", post)
    monkeypatch.setattr(golden, "_download", download)

    golden.render_native(tmp_path, "http://127.0.0.1:42021", tmp_path / "token")
    assert calls[0] == ("http://127.0.0.1:42021/api/v1/mcp", "series.episode.render_native",
                        {"workspace": "cast", "series_id": "uv", "episode_id": "ep1", "shot_ids": ["e1s01"]})
    assert golden.command_check(tmp_path) == 1, "a render without its fetched take is not green"
    assert golden.fetch_takes(tmp_path, "http://127.0.0.1:42021", tmp_path / "token") == 0
    assert calls[-1][1:] == ("series.episode.render_native.status", {"workspace": "cast", "job_id": "native-1"})
    assert downloads == ["http://127.0.0.1:42021/api/v1/file/export%20e1s01.png?workspace=cast"]
    assert (tmp_path / "current" / "pu-e1s01.png").is_file()
    assert golden.command_check(tmp_path) == 1, "the new take differs from the reference"
    shutil.copyfile(media / "e1s01.png", tmp_path / "current" / "pu-e1s01.png")
    assert golden.command_check(tmp_path) == 0
    golden.render_native(tmp_path, "http://127.0.0.1:42021", tmp_path / "token")
    assert not (tmp_path / "current").exists(), "a new render drops the takes an earlier fetch brought"
