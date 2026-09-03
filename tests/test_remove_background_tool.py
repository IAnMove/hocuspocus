from contextlib import contextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient as FastApiTestClient
from PIL import Image

from routers.tools import create_tools_router
from services.background_removal import remove_background_file
from services.background_removal_job import BackgroundRemovalJobHooks, run_remove_background_job
from services.asset_manifest import read_asset_manifest


def _image(path: Path, size=(24, 18)):
    Image.new("RGBA", size, (120, 80, 30, 255)).save(path)


def _fake_matte(image: Image.Image) -> Image.Image:
    result = image.convert("RGBA")
    pixels = result.load()
    for x in range(result.width):
        pixels[x, 0] = (0, 0, 0, 0)
        pixels[x, result.height - 1] = (0, 0, 0, 0)
    for y in range(result.height):
        pixels[0, y] = (0, 0, 0, 0)
        pixels[result.width - 1, y] = (0, 0, 0, 0)
    return result


def test_remove_background_file_reuses_injected_matte_and_keeps_source(tmp_path):
    uploads = tmp_path / "uploads"
    workspace = tmp_path / "outputs"
    uploads.mkdir()
    workspace.mkdir()
    source = workspace / "portrait.png"
    _image(source)

    result = remove_background_file(
        "portrait.png",
        uploads_root=str(uploads),
        workspace_root=str(workspace),
        output_dir=str(workspace),
        remove_background=_fake_matte,
    )

    output = Path(result["path"])
    assert source.is_file()
    assert output.is_file()
    assert output != source
    assert output.name.startswith("portrait.no-background-")
    assert result["method"] == "rembg-u2net"
    assert result["alpha"]["status"] == "transparent"
    with Image.open(output) as rendered:
        assert rendered.mode == "RGBA"
        assert rendered.size == (24, 18)


def test_remove_background_file_can_derive_cross_workspace_source(tmp_path):
    uploads = tmp_path / "uploads"
    source_workspace = tmp_path / "source-workspace"
    destination_workspace = tmp_path / "destination-workspace"
    uploads.mkdir()
    source_workspace.mkdir()
    destination_workspace.mkdir()
    source = source_workspace / "portrait.png"
    _image(source)

    result = remove_background_file(
        str(source),
        uploads_root=str(uploads),
        workspace_root=str(source_workspace),
        output_dir=str(destination_workspace),
        destination_workspace_root=str(destination_workspace),
        remove_background=_fake_matte,
    )

    assert Path(result["path"]).parent == destination_workspace
    assert source.is_file()


def test_tools_route_resolves_exact_asset_id_and_enqueues_one_job(tmp_path):
    uploads = tmp_path / "uploads"
    workspace = tmp_path / "outputs"
    uploads.mkdir()
    workspace.mkdir()
    source = workspace / "source.png"
    _image(source)
    jobs = []
    started = []
    asset = {
        "id": "asset_source",
        "kind": "image",
        "filename": "source.png",
        "locations": [{
            "workspace_id": "default",
            "output_folder": "default",
            "filename": "source.png",
        }],
    }
    app = FastAPI()
    app.include_router(create_tools_router(
        get_active_workspace=lambda: "default",
        list_workspaces=lambda: [{"name": "default"}],
        workspace_dir=lambda _name: str(workspace),
        uploads_dir=lambda: str(uploads),
        asset_finder=lambda asset_id: asset if asset_id == "asset_source" else None,
        register_job=lambda job: jobs.append(job) or job,
        start_remove_background=lambda job: started.append(job),
    ))

    response = FastApiTestClient(app).post("/api/v1/tools/remove-background", json={
        "asset_id": "asset_source",
        "source": "source.png",
        "workspace": "default",
        "instruction": "keep the original silhouette",
        "provenance": {"actor": "wizard", "command": {"command_id": "cmd-1"}},
    })

    assert response.status_code == 200
    payload = response.json()
    assert payload["job_id"] == jobs[0]["id"]
    assert payload["generation_details"]["source_asset_id"] == "asset_source"
    assert jobs[0]["params"]["source"] == "source.png"
    assert jobs[0]["params"]["source_asset_id"] == "asset_source"
    assert jobs[0]["params"]["generation_mode"] == "image"
    assert jobs[0]["params"]["_non_durable_tool"] == "remove_background"
    assert jobs[0]["provenance"]["actor"] == "wizard"
    assert jobs[0]["provenance"]["capability"] == "remove_background"
    assert started == jobs


def test_tools_route_rejects_non_image_asset_and_traversal(tmp_path):
    uploads = tmp_path / "uploads"
    workspace = tmp_path / "outputs"
    uploads.mkdir()
    workspace.mkdir()
    jobs = []
    video_asset = {
        "id": "asset_video",
        "kind": "video",
        "locations": [{"workspace_id": "default", "filename": "clip.mp4"}],
    }
    app = FastAPI()
    app.include_router(create_tools_router(
        get_active_workspace=lambda: "default",
        list_workspaces=lambda: [{"name": "default"}],
        workspace_dir=lambda _name: str(workspace),
        uploads_dir=lambda: str(uploads),
        asset_finder=lambda asset_id: video_asset if asset_id == "asset_video" else None,
        register_job=lambda job: jobs.append(job) or job,
        start_remove_background=lambda _job: None,
    ))
    client = FastApiTestClient(app)

    assert client.post("/api/v1/tools/remove-background", json={"asset_id": "asset_video"}).status_code == 400
    assert client.post("/api/v1/tools/remove-background", json={"source": "../source.png"}).status_code == 400
    assert client.post("/api/v1/tools/remove-background", json={"source": "/api/v1/uploads/../source.png"}).status_code == 400
    assert not jobs


def test_tools_route_preserves_exact_absolute_upload_source(tmp_path):
    uploads = tmp_path / "uploads"
    workspace = tmp_path / "outputs"
    uploads.mkdir()
    workspace.mkdir()
    source = uploads / "same-name.png"
    _image(source)
    jobs = []
    app = FastAPI()
    app.include_router(create_tools_router(
        get_active_workspace=lambda: "default",
        list_workspaces=lambda: [{"name": "default"}],
        workspace_dir=lambda _name: str(workspace),
        uploads_dir=lambda: str(uploads),
        register_job=lambda job: jobs.append(job) or job,
        start_remove_background=lambda _job: None,
    ))

    response = FastApiTestClient(app).post("/api/v1/tools/remove-background", json={
        "source": str(source),
        "workspace": "default",
    })

    assert response.status_code == 200
    assert jobs[0]["params"]["_source_path"] == str(source.resolve())
    assert jobs[0]["params"]["source_workspace"] == "__uploads__"

    api_response = FastApiTestClient(app).post("/api/v1/tools/remove-background", json={
        "source": "/api/v1/uploads/same-name.png",
        "workspace": "default",
    })
    assert api_response.status_code == 200
    assert jobs[1]["params"]["_source_path"] == str(source.resolve())
    assert jobs[1]["params"]["source_workspace"] == "__uploads__"


def test_tools_route_preserves_workspace_from_canonical_file_url(tmp_path):
    uploads = tmp_path / "uploads"
    default_workspace = tmp_path / "default"
    film_workspace = tmp_path / "film"
    uploads.mkdir()
    default_workspace.mkdir()
    film_workspace.mkdir()
    source = film_workspace / "portrait.png"
    _image(source)
    jobs = []
    app = FastAPI()
    app.include_router(create_tools_router(
        get_active_workspace=lambda: "default",
        list_workspaces=lambda: [{"name": "default"}, {"name": "film"}],
        workspace_dir=lambda name: str({"default": default_workspace, "film": film_workspace}[name]),
        uploads_dir=lambda: str(uploads),
        register_job=lambda job: jobs.append(job) or job,
        start_remove_background=lambda _job: None,
    ))

    response = FastApiTestClient(app).post("/api/v1/tools/remove-background", json={
        "source": "/api/v1/file/portrait.png?workspace=film",
        "workspace": "default",
    })

    assert response.status_code == 200
    assert jobs[0]["params"]["_source_path"] == str(source.resolve())
    assert jobs[0]["params"]["source_workspace"] == "film"

    encoded = film_workspace / "my portrait.png"
    _image(encoded)
    encoded_response = FastApiTestClient(app).post("/api/v1/tools/remove-background", json={
        "source": "/api/v1/file/my%20portrait.png?workspace=film",
        "workspace": "default",
    })
    assert encoded_response.status_code == 200
    assert jobs[1]["params"]["_source_path"] == str(encoded.resolve())
    assert jobs[1]["params"]["source_workspace"] == "film"

    mismatch = FastApiTestClient(app).post("/api/v1/tools/remove-background", json={
        "source": "/api/v1/uploads/portrait.png",
        "source_workspace": "film",
        "workspace": "default",
    })
    assert mismatch.status_code == 409
    assert len(jobs) == 2


def test_background_removal_worker_publishes_lineage_and_finishes(tmp_path):
    uploads = tmp_path / "uploads"
    workspace = tmp_path / "outputs"
    uploads.mkdir()
    workspace.mkdir()
    source = workspace / "source.png"
    _image(source)
    job = {
        "id": "job-bg-1",
        "status": "queued",
        "created_at": 100.0,
        "started_at": None,
        "finished_at": None,
        "params": {
            "source": "source.png",
            "source_asset_id": "asset_source",
            "source_filename": "source.png",
            "_source_path": str(source),
            "_uploads_root": str(uploads),
            "_workspace_root": str(workspace),
            "model": "u2net",
            "model_type": "rembg-u2net",
            "generation_mode": "image",
            "capability": "remove_background",
            "instruction": "transparent cutout",
            "_execution_mode": "real",
        },
        "workspace": "default",
        "out_dir": str(workspace),
        "output_files": [],
        "provenance": {"actor": "wizard", "capability": "remove_background"},
    }
    active_states = {}
    sidecars = []

    @contextmanager
    def slot(_job):
        yield True

    def try_start(current, **updates):
        current.update(updates)
        current["status"] = "running"
        current["started_at"] = 101.0
        return True

    def update_job(current, **updates):
        current.update(updates)
        return True

    def finish_job(current, status, **updates):
        current.update(updates)
        current["status"] = status
        current["finished_at"] = 102.0
        return True

    def register(_job, job_id, states, state):
        states[job_id] = state
        return True

    def unregister(job_id, states, _state):
        states.pop(job_id, None)

    hooks = BackgroundRemovalJobHooks(
        generation_slot=slot,
        try_start=try_start,
        update_job=update_job,
        finish_job=finish_job,
        is_cancel_requested=lambda current: bool(current.get("cancel_requested")),
        record_job_outputs=lambda current, files: current.update(output_files=files),
        register_abort_state=register,
        unregister_abort_state=unregister,
        acknowledge_cancel=lambda current: current.update(status="cancelled") or True,
        active_states=active_states,
        publish_sidecar=lambda current, path, sidecar: sidecars.append((current, path, sidecar)),
    )
    # Avoid loading a real rembg model in the contract test while exercising
    # the worker's actual job/sidecar path.
    import services.background_removal_job as worker_module
    original = worker_module.remove_background_file
    worker_module.remove_background_file = lambda *args, **kwargs: remove_background_file(
        *args, **kwargs, remove_background=_fake_matte,
    )
    try:
        assert run_remove_background_job(job, hooks=hooks) is True
    finally:
        worker_module.remove_background_file = original

    assert job["status"] == "completed"
    assert len(job["output_files"]) == 1
    assert len(sidecars) == 1
    _, output_path, sidecar = sidecars[0]
    assert Path(output_path).is_file()
    assert sidecar["inputs"][0]["id"] == "asset_source"
    assert sidecar["parents"][0]["id"] == "asset_source"
    assert sidecar["transformations"][0]["method"] == "rembg-u2net"
    assert sidecar["execution_mode"] == "real"
    assert sidecar["simulated"] is False
    assert "_source_path" not in sidecar["params"]
    assert "_non_durable_tool" not in sidecar["params"]

    # Run the same publisher contract used by launch.py and inspect the
    # canonical read model rather than relying on legacy top-level keys.
    from services.asset_manifest import publish_generation_sidecar
    publish_generation_sidecar(
        output_path,
        sidecar,
        output_folder="default",
        tool="remove_background",
        actor="wizard",
        capability="remove_background",
    )
    manifest = read_asset_manifest(output_path)
    assert manifest is not None
    assert manifest["origin"]["tool"] == "remove_background"
    assert manifest["origin"]["actor"] == "wizard"
    assert manifest["generation"]["prompts"]["instruction"] == "transparent cutout"
    assert manifest["lineage"]["parents"][0]["id"] == "asset_source"
    assert manifest["technical"]["output"] == "transparent_png"


def test_background_removal_worker_acknowledges_registration_cancel_race(tmp_path):
    job = {
        "id": "job-bg-race",
        "status": "queued",
        "params": {"_execution_mode": "real"},
        "workspace": "default",
        "out_dir": str(tmp_path),
    }
    acknowledgements = []
    active_states = {}

    @contextmanager
    def slot(_job):
        yield True

    def try_start(current, **updates):
        current.update(updates)
        current["status"] = "running"
        return True

    def register(current, _job_id, _states, _state):
        # Model the cancellation landing after try_start but before the
        # worker can publish its abort state.
        current["cancel_requested"] = True
        current["status"] = "cancelling"
        return False

    hooks = BackgroundRemovalJobHooks(
        generation_slot=slot,
        try_start=try_start,
        update_job=lambda *_args, **_kwargs: True,
        finish_job=lambda *_args, **_kwargs: False,
        is_cancel_requested=lambda current: bool(current.get("cancel_requested")),
        record_job_outputs=lambda *_args, **_kwargs: None,
        register_abort_state=register,
        unregister_abort_state=lambda *_args, **_kwargs: None,
        acknowledge_cancel=lambda current: acknowledgements.append(current["id"]) or True,
        active_states=active_states,
        publish_sidecar=lambda *_args, **_kwargs: None,
    )

    assert run_remove_background_job(job, hooks=hooks) is False
    assert acknowledgements == ["job-bg-race"]


def test_background_removal_worker_settles_cancel_after_registration(tmp_path):
    job = {
        "id": "job-bg-cancelled",
        "status": "queued",
        "params": {"_execution_mode": "real"},
        "workspace": "default",
        "out_dir": str(tmp_path),
    }
    acknowledgements = []

    @contextmanager
    def slot(_job):
        yield True

    def try_start(current, **updates):
        current.update(updates)
        current["status"] = "running"
        current["cancel_requested"] = True
        return True

    hooks = BackgroundRemovalJobHooks(
        generation_slot=slot,
        try_start=try_start,
        update_job=lambda *_args, **_kwargs: True,
        finish_job=lambda *_args, **_kwargs: False,
        is_cancel_requested=lambda current: bool(current.get("cancel_requested")),
        record_job_outputs=lambda *_args, **_kwargs: None,
        register_abort_state=lambda *_args, **_kwargs: True,
        unregister_abort_state=lambda *_args, **_kwargs: None,
        acknowledge_cancel=lambda current: acknowledgements.append(current["id"]) or True,
        active_states={},
        publish_sidecar=lambda *_args, **_kwargs: None,
    )

    assert run_remove_background_job(job, hooks=hooks) is False
    assert acknowledgements == ["job-bg-cancelled"]


def test_background_removal_worker_settles_interrupted_simulation(tmp_path):
    source = tmp_path / "source.png"
    _image(source)
    job = {
        "id": "job-bg-sim-cancelled",
        "status": "queued",
        "params": {
            "_execution_mode": "simulate",
            "_source_path": str(source),
            "source": source.name,
        },
        "workspace": "default",
        "out_dir": str(tmp_path),
    }
    acknowledgements = []

    @contextmanager
    def slot(_job):
        yield True

    def try_start(current, **updates):
        current.update(updates)
        current["status"] = "running"
        return True

    def interrupted_artifact(*_args, **_kwargs):
        raise InterruptedError("cancelled")

    hooks = BackgroundRemovalJobHooks(
        generation_slot=slot,
        try_start=try_start,
        update_job=lambda *_args, **_kwargs: True,
        finish_job=lambda *_args, **_kwargs: False,
        is_cancel_requested=lambda current: bool(current.get("cancel_requested")),
        record_job_outputs=lambda *_args, **_kwargs: None,
        register_abort_state=lambda *_args, **_kwargs: True,
        unregister_abort_state=lambda *_args, **_kwargs: None,
        acknowledge_cancel=lambda current: acknowledgements.append(current["id"]) or True,
        active_states={},
        publish_sidecar=lambda *_args, **_kwargs: None,
        simulated_artifact=interrupted_artifact,
    )

    assert run_remove_background_job(job, hooks=hooks) is False
    assert acknowledgements == ["job-bg-sim-cancelled"]
