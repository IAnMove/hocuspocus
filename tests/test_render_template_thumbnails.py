"""The thumbnail pre-warm script asks a server for every card's picture in turn and reports times and failures.

It runs against a fake server here: no app, no browser, no GPU.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("render_template_thumbnails", ROOT / "scripts" / "render_template_thumbnails.py")
prewarm = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = prewarm
SPEC.loader.exec_module(prewarm)

PICTURE = b"RIFF\x1a\x00\x00\x00WEBPVP8L"


def _card(card_id, kind="scene", personal=False):
    return {"id": card_id, "kind": kind,
            "preview": None if personal else f"/api/v1/world3d/templates/{card_id}/thumbnail"}


CARDS = [_card("a-scene"), _card("b-cached"), _card("c-flaky"), _card("d-broken"), _card("e-examples"),
         _card("stage-bar", "stage"), _card("user-mine", personal=True)]


class FakeServer:
    """The two routes the script uses: the card list (paged) and each card's thumbnail."""

    def __init__(self):
        self.lists, self.gets = [], []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                owner.lists.append(body)
                data = body["input"]
                cards = [card for card in CARDS if not data.get("kind") or card["kind"] == data["kind"]]
                page = cards[data["offset"]:data["offset"] + data["limit"]]
                self._json(200, {"result": {"templates": page, "total": len(cards)}})

            def do_GET(self):
                card_id = self.path.split("/")[-2]
                owner.gets.append(card_id)
                if card_id == "d-broken" or (card_id == "c-flaky" and owner.gets.count("c-flaky") == 1):
                    self._json(503, {"detail": {"code": "thumbnail_unavailable", "reason": "render_failed" if card_id == "d-broken" else "busy",
                                                "message": "page crashed" if card_id == "d-broken" else "rendering", "retryable": True}})
                    return
                if card_id == "e-examples":
                    self._json(409, {"detail": {"code": "examples_not_installed", "collections": ["creative"],
                                                "message": "download creative first", "retryable": False}})
                    return
                self.send_response(200)
                self.send_header("Content-Type", "image/webp")
                self.send_header("X-Thumbnail-Cache", "hit" if card_id == "b-cached" else "miss")
                self.send_header("Content-Length", str(len(PICTURE)))
                self.end_headers()
                self.wfile.write(PICTURE)

            def _json(self, status, value):
                payload = json.dumps(value).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_exc):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setattr(prewarm, "PAGE", 2)
    with FakeServer() as fake:
        yield fake


def test_every_card_is_asked_in_turn_with_times_failures_and_a_report(server, tmp_path, capsys):
    report = tmp_path / "report.json"
    code = prewarm.main(["--url", server.url, "--pause", "0", "--report", str(report)])
    out = capsys.readouterr().out
    assert code == 1, "a card that never rendered fails the run"
    assert [body["input"]["offset"] for body in server.lists] == [0, 2, 4, 6], "the list is paged to its total"
    assert server.gets == ["a-scene", "b-cached", "c-flaky", "c-flaky", "d-broken", "d-broken", "d-broken", "e-examples",
                           "stage-bar"], "a card that needs examples is asked once, never retried"
    assert "ok    rendered a-scene" in out and "ok    cached   b-cached" in out and "ok    rendered c-flaky" in out
    assert "FAIL  d-broken  503/thumbnail_unavailable/render_failed: page crashed" in out
    assert "user-mine" not in out, "a personal template has no picture to warm"
    assert "skip  e-examples  needs examples: creative" in out
    assert "6 cards: 3 rendered, 1 cached, 1 skipped, 1 failed" in out and "failed: d-broken" in out and "slowest: " in out
    assert "skipped, example collections not installed: creative (1)" in out
    results = json.loads(report.read_text())["results"]
    assert results["c-flaky"]["attempts"] == 2 and results["d-broken"]["attempts"] == 3
    assert results["a-scene"]["bytes"] == len(PICTURE) and results["a-scene"]["type"] == "image/webp"
    assert results["e-examples"]["status"] == "skipped" and results["e-examples"]["collections"] == ["creative"]


def test_a_run_whose_only_misses_need_examples_succeeds(server, capsys):
    assert prewarm.main(["--url", server.url, "--only", "a-scene,e-examples"]) == 0
    assert "2 cards: 1 rendered, 0 cached, 1 skipped, 0 failed" in capsys.readouterr().out


def test_kind_and_only_narrow_the_run(server, capsys):
    assert prewarm.main(["--url", server.url, "--kind", "stage"]) == 0
    assert server.gets == ["stage-bar"] and all(body["input"]["kind"] == "stage" for body in server.lists)
    server.gets.clear()
    assert prewarm.main(["--url", server.url, "--only", "a-scene,nope,a-scene"]) == 1
    out = capsys.readouterr().out
    assert server.gets == ["a-scene"]
    assert "FAIL  nope  not_listed: not in the card list" in out and "2 cards: 1 rendered, 0 cached, 0 skipped, 1 failed" in out


def test_live_instances_are_refused_unless_asked(capsys):
    assert prewarm.main(["--url", "http://127.0.0.1:42042"]) == 2
    assert "live instance" in capsys.readouterr().err
    assert prewarm.check_target("http://127.0.0.1:42003/", allow_live=True) == "http://127.0.0.1:42003"
    with pytest.raises(ValueError):
        prewarm.check_target("127.0.0.1:42017", allow_live=False)


def test_an_unreachable_server_fails_before_any_card(capsys):
    with FakeServer() as fake:
        url = fake.url
    assert prewarm.main(["--url", url, "--timeout", "2"]) == 1
    assert "could not list the cards" in capsys.readouterr().err
