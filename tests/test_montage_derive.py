"""Derived aspect copies of a montage leave the original file alone."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.montages import create_montages_router
from services.montage_commands import MontageCommands
from services.montage_documents import MontageError, MontageStore
from services.montage_derive import derived_document


def _montage():
    return {
        "version": 1, "name": "The Bird Is Freed", "width": 1920, "height": 1080, "fps": 24,
        "clips": [{"id": "c1", "source": "wide.mp4", "fit": "fit", "focusX": 30, "focusY": 70}],
        "soundtrack": {"source": "song.wav", "volume": 0.8},
        "overlays": [
            {"id": "top", "source": "cap/top.png", "start": 0.2, "end": 2, "x": 50, "y": 0, "width": 100},
            {"id": "mid", "source": "cap/mid.png", "start": 1, "end": 3, "x": 40, "y": 95, "width": 40},
        ],
        "audioCues": [{"id": "vo1", "source": "vo.wav", "start": 0.4, "volume": 1}],
        "duck": 0.3,
    }


def _store(tmp_path: Path) -> MontageStore:
    def workspace_dir(name: str) -> str:
        path = tmp_path / name
        path.mkdir(parents=True, exist_ok=True)
        return str(path)
    return MontageStore(workspace_dir)


def _commands(store: MontageStore) -> MontageCommands:
    return MontageCommands(store, start_export=lambda body: {"job_id": "unused"}, get_export=lambda job: {"job_id": job})


def test_derived_document_places_overlays_and_keeps_focus():
    document = derived_document(_montage(), aspect="9:16", fit="blur", file="The-Bird-Is-Freed.montage.json", revision=2)
    assert document["width"] == 1080 and document["height"] == 1920
    assert document["name"] == "The Bird Is Freed (9:16)"
    assert document["clips"][0]["fit"] == "blur"
    assert document["clips"][0]["focusX"] == 30 and document["clips"][0]["focusY"] == 70
    assert document["soundtrack"]["source"] == "song.wav"
    assert document["audioCues"][0]["source"] == "vo.wav"
    assert document["derivedFrom"] == {"file": "The-Bird-Is-Freed.montage.json", "revision": 2}
    top, mid = document["overlays"]
    assert top["width"] == 90 and top["y"] == 12 and top["x"] == 50
    assert mid["width"] == 40 and mid["y"] == 80
    square = derived_document(_montage(), aspect="1:1", fit="fill", file="a.montage.json", revision=1)
    assert (square["width"], square["height"]) == (1080, 1080)
    portrait = derived_document(_montage(), aspect="4:5", fit="fill", file="a.montage.json", revision=1)
    assert (portrait["width"], portrait["height"]) == (1080, 1350)


def test_derive_writes_a_new_file_and_conflicts_until_regenerated(tmp_path: Path):
    store = _store(tmp_path)
    commands = _commands(store)
    saved = store.save("x-song", _montage())
    original = store.get("x-song", saved["file"])["montage"]
    created = commands.execute("montages.derive", {"version": 1, "input": {
        "workspace": "x-song", "file": saved["file"], "format": "9:16", "fit": "blur",
    }})["result"]
    assert created["file"] == "The-Bird-Is-Freed-9-16.montage.json"
    assert created["revision"] == 1
    again = store.get("x-song", saved["file"])["montage"]
    assert again["revision"] == original["revision"]
    assert again["width"] == 1920 and again["clips"][0]["fit"] == "fit"
    assert "derivedFrom" not in again
    try:
        commands.execute("montages.derive", {"version": 1, "input": {
            "workspace": "x-song", "file": saved["file"], "format": "9:16", "fit": "blur",
        }})
    except MontageError as error:
        assert error.status == 409 and error.code == "exists"
    else:
        raise AssertionError("second derive should conflict")
    regenerated = commands.execute("montages.derive", {"version": 1, "input": {
        "workspace": "x-song", "file": saved["file"], "format": "9:16", "fit": "fill",
        "output_file": created["file"], "expected_revision": 1,
    }})["result"]
    assert regenerated["revision"] == 2
    copy = store.get("x-song", created["file"])["montage"]
    assert copy["clips"][0]["fit"] == "fill"
    assert copy["derivedFrom"]["file"] == saved["file"]
    assert store.get("x-song", saved["file"])["montage"]["clips"][0]["fit"] == "fit"


def test_derive_http_route(tmp_path: Path):
    store = _store(tmp_path)
    saved = store.save("x-song", _montage())
    app = FastAPI()
    app.include_router(create_montages_router(_commands(store)))
    client = TestClient(app)
    response = client.post(
        f"/api/v1/montages/{saved['file']}/derive",
        json={"workspace": "x-song", "format": "4:5", "fit": "blur"},
    )
    assert response.status_code == 200
    assert response.json()["file"].endswith("-4-5.montage.json")
    conflict = client.post(
        f"/api/v1/montages/{saved['file']}/derive",
        json={"workspace": "x-song", "format": "4:5", "fit": "blur"},
    )
    assert conflict.status_code == 409 and conflict.json()["detail"]["code"] == "exists"
