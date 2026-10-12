"""CPU media and Wizard attribution work on the same core runtime served by the launcher."""
import json
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image


def test_core_cpu_media_preserves_wizard_identity_intent_and_activity(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import core_runtime

    client = TestClient(core_runtime.api)
    catalog = client.get("/api/v1/media/commands")
    assert catalog.status_code == 200
    assert set(catalog.json()["operations"]) == {
        "media.frame", "media.compose", "audio.trim", "assets.import_from_workspace", "studio.key",
    }
    folder = Path(core_runtime.core.workspace_dir("show"))
    Image.new("RGBA", (16, 16), "red").save(folder / "source.png")
    command = {"version": 1, "operation": "media.compose", "intent_id": "wizard-still",
               "input": {"workspace": "show", "layers": [{"file": "source.png"}], "size": [16, 16], "output_name": "still"}}
    made = client.post("/api/v1/media/commands", json=command, headers={"X-Hocus-UI-Surface": "wizard"})
    assert made.status_code == 200, made.text
    result = made.json()["result"]
    metadata = json.loads((folder / result["file"]).with_suffix(".meta.json").read_text())
    assert metadata["origin"]["actor"] == "wizard"
    assert metadata["command_id"] == "wizard-still"
    replayed = client.post("/api/v1/media/commands", json=command, headers={"X-Hocus-UI-Surface": "wizard"})
    assert replayed.json()["result"]["replayed"] is True
    assert len(list(folder.glob("still*.png"))) == 1
    changed = client.post("/api/v1/tasks/wizard-changes", json={
        "workspace": "show", "capability": "media_tool", "commandId": "wizard-still",
        "targets": [{"kind": "file", "id": result["file"], "file": result["file"]}],
    })
    assert changed.status_code == 200, changed.text
    assert changed.json()["recorded"] is True
    task = changed.json()["task"]
    assert task["metadata"]["actor"] == "wizard"
    assert task["metadata"]["command_id"] == "wizard-still"
    assert task["result_refs"] == [result["file"]]
