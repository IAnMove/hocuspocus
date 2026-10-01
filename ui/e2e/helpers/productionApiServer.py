"""Real ownership/review HTTP, with only the expensive generation seams simulated."""
import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "app"))

from fastapi import FastAPI
from fastapi.responses import FileResponse
import uvicorn

from routers.music_productions import create_music_productions_router
from routers.production_projects import create_production_projects_router
from services import music_production as music
from services import production_shot_commands as shots

temporary = tempfile.TemporaryDirectory(prefix="hocus-production-browser-")
root = Path(temporary.name)
app = FastAPI()
music.require_free_disk = lambda _root: None


def write(name, value):
    (root / name).write_text(json.dumps(value), encoding="utf-8")


def manifest(production):
    write("browser-clip.shots.json", {"revision": 0, "production_id": production.id, "montage": "cut.montage.json", "shots": [
        {"key": key, "clip": production.state["clips"][key]["file"],
         "takes": production.state["takes"][key], "lyric": "Night bus"}
        for key in ["s1", "s2"]
    ]})


def finish(production, spec, *_args):
    assert production.state["project"]["kind"] == "story"
    production.state.update(spec=spec, status="completed", montage_file="cut.montage.json",
                            frames={"s1": "frame.png", "s2": "frame.png"},
                            clips={"s1": {"file": "old.mp4"}, "s2": {"file": "other.mp4"}},
                            takes={"s1": [{"file": "old.mp4"}], "s2": [{"file": "other.mp4"}]})
    for name in ["old.mp4", "other.mp4"]:
        (root / name).write_bytes(b"synthetic media fixture")
    write("cut.montage.json", {"revision": 1, "clips": [{"id": "s1", "source": "old.mp4"}, {"id": "s2", "source": "other.mp4"}]})
    production.save()
    manifest(production)


def generate_clip(production, _spec, key, _action):
    assert key == "s1", "The other shot must not be regenerated"
    (root / "new.mp4").write_bytes(b"new synthetic media fixture")
    production.state["clips"][key] = {"file": "new.mp4"}
    production.state["takes"][key].append({"file": "new.mp4"})
    production.save()


def export_scene(production, _spec, _key):
    production.save()
    manifest(production)
    return {"file": "s1.scene.json"}


music.Production.run = finish
shots._shoot_clip = generate_clip
shots._export_scene = export_scene
app.include_router(create_production_projects_router(workspace_dir=lambda _workspace: str(root)))
app.include_router(create_music_productions_router(
    workspace_dir=lambda _workspace: str(root), uploads_dir=lambda: str(root),
    app_url=lambda: "http://unused", token=lambda: "test-token"))


@app.post("/test/start")
async def start():
    handlers = music.command_handlers(lambda _workspace: str(root), lambda: str(root), lambda: "http://unused", lambda: "test-token")
    spec = {"title": "Browser journey", "song": {"lyrics": "Night bus", "caption": "pop", "duration": 60, "bpm": 120},
            "style": {}, "shots": [{"key": key, "kind": "h3", "frame": "A bus", "action": "Drive"} for key in ["s1", "s2"]]}
    return await handlers[music.RUN]({"version": 1, "input": {"workspace": "default", "production_id": "browser-clip", "spec": spec}})


@app.get("/test/state")
def state():
    return {path.name: json.loads(path.read_text()) for path in root.glob("*.json")}


@app.get("/api/v1/file/{name}")
def file(name: str):
    return FileResponse(root / Path(name).name)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    uvicorn.run(app, host="127.0.0.1", port=parser.parse_args().port)
