from __future__ import annotations

import base64
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import core_runtime
from core_runtime import api
from services.platform_capabilities import FEATURE_UNAVAILABLE
from services.scene_commands import SceneCommands
from services import core_canonical_tasks, core_remote_image
from services.core_remote_image import catalog_entry


# The key core's assembly router registered its controller under when core_runtime was imported
# (the folder of the default workspace, relative to the directory the tests start in).
CORE_ASSEMBLY_KEY = os.path.realpath(os.path.abspath(core_runtime.core.workspace_dir("default")))


class ImmediateThread:
    def __init__(self, target=None, args=(), kwargs=None, daemon=None, name=None):
        self._target = target
        self._args = args

    def start(self):
        self._target(*self._args)


def _bind_core_video_editor_runtime():
    """Bind the editor router's module runtime to core's wiring again (the same arguments core_runtime passes).

    ``routers.video_editor._runtime`` is one module global that every ``create_video_editor_router`` call rebinds.
    A test file that builds its own editor router earlier in the same process (tests/test_video_editor_router.py)
    would otherwise leave core's export routes resolving clips through that test's folders.
    """
    from routers import video_editor
    from services import core_workspace as core

    video_editor._bind_video_editor_runtime(
        workspace_dir=core.workspace_dir_or_400,
        get_active_workspace=core.active_workspace,
        resolve_input_path=core_runtime._resolve_editor_input,
        publish_legacy_task=core_canonical_tasks.publish_video_editor_activity,
        thumbnail_cache_dir=os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(core_runtime.__file__))), "cache", "media-thumbnails",
        ),
    )


class CoreRuntimeTests(unittest.TestCase):
    def setUp(self):
        _bind_core_video_editor_runtime()
        self.client = TestClient(api)
        self.patches = [
            patch("services.platform_capabilities.host_platform", return_value="darwin"),
            patch("services.platform_capabilities.host_machine", return_value="arm64"),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in self.patches:
            item.stop()
        # Some tests start a job whose worker thread is stubbed out. Left in the registries it would
        # stay "queued" for the rest of the process.
        from services import core_remote_3d

        core_remote_3d._JOBS.clear()
        core_remote_image._JOBS.clear()

    def _in_temp_workspace(self):
        folder = tempfile.TemporaryDirectory()
        previous = os.getcwd()
        os.chdir(folder.name)
        return folder, previous

    def _leave_temp_workspace(self, folder, previous):
        os.chdir(previous)
        folder.cleanup()

    def test_saved_scene_url_keeps_its_workspace_after_active_folder_changes(self):
        from services import core_workspace as core

        for requested in ("scene-lab", "default", None):
            with self.subTest(workspace=requested):
                folder, previous = self._in_temp_workspace()
                try:
                    core.save_config({"services": {"active_workspace": "active-lab"}})
                    scene = {"version": 1, "name": "Workspace round trip"}
                    payload = {"scene": scene}
                    if requested is not None:
                        payload["workspace"] = requested
                    saved = self.client.post("/api/v1/scenes", json=payload)
                    self.assertEqual(saved.status_code, 200, saved.text)
                    result = saved.json()
                    workspace = requested if requested is not None else "active-lab"
                    self.assertEqual(
                        result["url"], f"/api/v1/file/{result['name']}?workspace={workspace}",
                    )
                    core.save_config({"services": {"active_workspace": "other-lab"}})
                    fetched = self.client.get(result["url"])
                    self.assertEqual(fetched.status_code, 200, fetched.text)
                    self.assertEqual(fetched.json(), scene)
                    self.assertEqual(
                        self.client.get(f"/api/v1/file/{result['name']}").status_code, 404,
                    )
                finally:
                    self._leave_temp_workspace(folder, previous)

    def test_boot_surface_and_local_engines_are_blocked(self):
        listed = self.client.get("/api/v1/system/capabilities")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["profile"], "macos-arm64-core-remote")
        self.assertFalse(listed.json()["ui"]["show_cuda_controls"])
        model = self.client.get("/api/v1/models").json()["models"][0]
        self.assertEqual(model["model_type"], "minimax:image-01")
        self.assertFalse(model["is_t2v"])
        self.assertEqual(model["family"], "minimax")
        self.assertFalse(catalog_entry()["is_t2v"])
        self.assertIn("workspaces", self.client.get("/api/v1/workspaces").json())
        self.assertEqual(self.client.get("/api/v1/system-config").status_code, 200)
        self.assertEqual(self.client.get("/api/v1/services-config").status_code, 200)
        self.assertEqual(self.client.get("/api/v1/jobs").status_code, 200)
        self.assertEqual(self.client.get("/api/v1/outputs").status_code, 200)
        self.assertEqual(self.client.get("/api/v1/recipes").status_code, 200)
        denied = self.client.post("/api/v1/generate")
        self.assertEqual(denied.status_code, 409)
        self.assertEqual(denied.json()["detail"]["code"], FEATURE_UNAVAILABLE)
        self.assertEqual(self.client.post("/api/v1/model3d/generate", json={"provider": "local"}).status_code, 409)
        self.assertEqual(self.client.post("/api/v1/director/pipeline/start").status_code, 409)
        self.assertEqual(self.client.post("/api/v1/rig/generate", json={"engine": "unirig"}).status_code, 409)
        mcp = self.client.post("/api/v1/wangp/mcp", json={"params": {"name": "generate"}})
        self.assertEqual(mcp.status_code, 503)
        self.assertEqual(self.client.post("/api/v1/tools/remove-background").status_code, 409)
        missing = self.client.post("/api/v1/video-editor/probe", json={"source": "missing.mp4"})
        self.assertEqual(missing.status_code, 400)

    def test_procedural_rig_runs_without_the_3d_engine(self):
        import shutil
        import time
        capabilities = self.client.get("/api/v1/rig/capabilities").json()
        self.assertEqual([engine["id"] for engine in capabilities["engines"]], ["procedural", "humanoid"])
        self.assertTrue(capabilities["engines"][0]["installed"], capabilities["engines"][0]["install_hint"])
        self.assertTrue(capabilities["animations"])
        folder, previous = self._in_temp_workspace()
        try:
            fixture = Path(__file__).resolve().parents[1] / "ui" / "tests" / "fixtures" / "tv-head-humanoid.glb"
            shutil.copy(fixture, core_runtime.core.outputs_root() / "prop.glb")
            started = self.client.post("/api/v1/rig/generate", json={"source": "prop.glb", "animations": ["idle"]})
            self.assertEqual(started.status_code, 200, started.text)
            job = started.json()
            deadline = time.monotonic() + 60
            while job["status"] not in {"completed", "failed", "cancelled"} and time.monotonic() < deadline:
                time.sleep(0.2)
                job = self.client.get(f"/api/v1/rig/status/{job['job_id']}").json()
            self.assertEqual(job["status"], "completed", job.get("error"))
            self.assertTrue(list(core_runtime.core.outputs_root().glob("*_rigged_prop_*.glb")))
        finally:
            self._leave_temp_workspace(folder, previous)

    def _copy_rig_fixture(self, destination: Path) -> None:
        import shutil
        fixture = Path(__file__).resolve().parents[1] / "ui" / "tests" / "fixtures" / "tv-head-humanoid.glb"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(fixture, destination)

    def test_rig_keeps_the_submission_provenance(self):
        folder, previous = self._in_temp_workspace()
        try:
            self._copy_rig_fixture(core_runtime.core.outputs_root() / "prop.glb")
            started = self.client.post("/api/v1/rig/generate", json={
                "source": "prop.glb",
                "animations": ["idle"],
                "provenance": {"actor": "wizard", "capability": "rig"},
            })
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(started.status_code, 200, started.text)
        self.assertEqual(started.json().get("provenance", {}).get("actor"), "wizard")

    def test_rig_accepts_an_uploaded_glb(self):
        folder, previous = self._in_temp_workspace()
        try:
            self._copy_rig_fixture(Path("uploads") / "prop.glb")
            started = self.client.post("/api/v1/rig/generate", json={
                "source": "/api/v1/uploads/prop.glb",
                "animations": ["idle"],
            })
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(started.status_code, 200, started.text)

    def test_rig_publishes_an_activity_task(self):
        folder, previous = self._in_temp_workspace()
        try:
            self._copy_rig_fixture(core_runtime.core.outputs_root() / "prop.glb")
            started = self.client.post("/api/v1/rig/generate", json={
                "source": "prop.glb", "animations": ["idle"],
            })
            self.assertEqual(started.status_code, 200, started.text)
            tasks = self.client.get("/api/v1/tasks", params={"status": "all", "workspace": "default"})
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(tasks.status_code, 200, tasks.text)
        workflows = [item.get("workflow") for item in tasks.json()["tasks"]]
        self.assertIn("rig", workflows)

    def test_meshy_completion_writes_an_asset_manifest(self):
        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()

            def fake_generate(**kwargs):
                name = "meshy-manifest.glb"
                path = Path(kwargs["output_dir"]) / name
                path.write_bytes(b"glb")
                return {"filename": name, "path": str(path), "provider": "meshy"}

            with patch("services.meshy_3d_service.generate_model", side_effect=fake_generate), patch(
                "services.execution_mode.validate_remote_provider",
            ), patch("services.core_remote_3d.threading.Thread", ImmediateThread):
                response = self.client.post("/api/v1/model3d/generate", json={
                    "provider": "meshy", "prompt": "a clay robot", "workspace": "default",
                })
            sidecar = core_runtime.core.outputs_root() / "meshy-manifest.meta.json"
            published = sidecar.is_file() and json.loads(sidecar.read_text(encoding="utf-8"))["technical"]["published_on_generate"]
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(published)

    def test_finished_remote_3d_job_reports_a_url_that_names_its_workspace(self):
        """A bare /api/v1/file/<name> is served from the ACTIVE workspace only; the job says where it ran."""
        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()
            with patch("services.meshy_3d_service.generate_model", return_value={"filename": "meshy-where.glb"}), patch(
                "services.execution_mode.validate_remote_provider",
            ), patch("services.core_remote_3d.threading.Thread", ImmediateThread):
                started = self.client.post("/api/v1/model3d/generate", json={
                    "provider": "meshy", "prompt": "a clay robot", "workspace": "default",
                })
            status = self.client.get(f"/api/v1/model3d/status/{started.json()['job_id']}")
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(status.json()["status"], "completed", status.text)
        self.assertEqual(status.json()["url"], "/api/v1/file/meshy-where.glb?workspace=default")

    def test_model3d_job_publishes_an_activity_task(self):
        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()
            with patch("services.meshy_3d_service.generate_model", return_value={"filename": "meshy-test.glb"}), patch(
                "services.execution_mode.validate_remote_provider",
            ):
                response = self.client.post("/api/v1/model3d/generate", json={
                    "provider": "meshy", "prompt": "a clay robot", "workspace": "default",
                })
            tasks = self.client.get("/api/v1/tasks", params={"status": "all", "workspace": "default"})
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(response.status_code, 200, response.text)
        workflows = [item.get("workflow") for item in tasks.json()["tasks"]]
        self.assertIn("model3d", workflows)

    def _meshy_job_request(self, images):
        """POST a Meshy job with the worker thread stubbed; return the response and the job's stored request."""
        from services import core_remote_3d

        with patch("services.core_remote_3d.threading.Thread"), patch("services.execution_mode.validate_remote_provider"):
            response = self.client.post("/api/v1/model3d/generate", json={
                "provider": "meshy", "images": images, "workspace": "default",
            })
        job = core_remote_3d._JOBS.get(response.json().get("job_id")) if response.status_code == 200 else {}
        return response, (job or {}).get("_request", {})

    def test_core_model3d_refuses_retexture_instead_of_generating(self):
        """The shared router accepts operation=retexture; Meshy must not silently generate a new mesh."""
        from PIL import Image

        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()
            Path("outputs", "hero.glb").write_bytes(b"glb")
            Image.new("RGB", (4, 4), (1, 2, 3)).save(Path("outputs", "tex.png"))
            with patch("services.meshy_3d_service.generate_model") as generate, patch(
                "services.execution_mode.validate_remote_provider",
            ), patch("services.core_remote_3d.threading.Thread") as worker:
                response = self.client.post("/api/v1/model3d/generate", json={
                    "provider": "meshy",
                    "operation": "retexture",
                    "source_model": "hero.glb",
                    "images": {"front": "tex.png"},
                    "workspace": "default",
                })
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("Retexture a GLB", str(response.json().get("detail") or ""))
        generate.assert_not_called()
        worker.assert_not_called()

    def test_core_model3d_keeps_a_nested_reference_the_router_accepted(self):
        from PIL import Image

        folder, previous = self._in_temp_workspace()
        try:
            nested = Path("outputs", "refs", "deep", "front.png")
            nested.parent.mkdir(parents=True)
            Image.new("RGB", (4, 4), (1, 2, 3)).save(nested)
            response, request = self._meshy_job_request({"front": "refs/deep/front.png"})
            expected = os.path.realpath(nested)
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(os.path.realpath(request["image_path"]), expected)

    def test_core_model3d_uses_the_upload_the_router_picked_over_a_workspace_file_of_the_same_name(self):
        from PIL import Image

        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()
            Path("uploads").mkdir()
            Image.new("RGB", (4, 4), (200, 0, 0)).save(Path("outputs", "front.png"))
            Image.new("RGB", (4, 4), (0, 0, 200)).save(Path("uploads", "front.png"))
            response, request = self._meshy_job_request({"front": "/api/v1/uploads/front.png"})
            expected = os.path.realpath(Path("uploads", "front.png"))
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(os.path.realpath(request["image_path"]), expected)

    def test_meshy_job_stays_completed_when_the_asset_manifest_cannot_be_written(self):
        """The GLB exists and the provider call was paid for: a manifest failure must not turn the job into a failure."""
        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()

            def fake_generate(**kwargs):
                name = "meshy-paid.glb"
                Path(kwargs["output_dir"], name).write_bytes(b"glb")
                return {"filename": name}

            with patch("services.meshy_3d_service.generate_model", side_effect=fake_generate), patch(
                "services.execution_mode.validate_remote_provider",
            ), patch("services.core_remote_3d.threading.Thread", ImmediateThread), patch(
                "services.asset_manifest.publish_generation_job_sidecar", side_effect=OSError("disk full"),
            ):
                started = self.client.post("/api/v1/model3d/generate", json={
                    "provider": "meshy", "prompt": "a clay robot", "workspace": "default",
                })
            job = self.client.get(f"/api/v1/model3d/status/{started.json()['job_id']}").json()
            produced = Path("outputs", "meshy-paid.glb").is_file()
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(started.status_code, 200, started.text)
        self.assertEqual(job["status"], "completed", job)
        self.assertEqual(job["filename"], "meshy-paid.glb")
        self.assertTrue(produced)

    def test_core_model3d_unload_cancels_the_queued_remote_jobs(self):
        """The shared Model3D router brings ``POST /api/v1/model3d/unload`` to core: it cancels the Meshy and Hi3D jobs."""
        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()
            with patch("services.core_remote_3d.threading.Thread"), patch(
                "services.execution_mode.validate_remote_provider",
            ):
                started = self.client.post("/api/v1/model3d/generate", json={
                    "provider": "meshy", "prompt": "a clay robot", "workspace": "default",
                })
            unloaded = self.client.post("/api/v1/model3d/unload")
            after = self.client.get(f"/api/v1/model3d/status/{started.json()['job_id']}")
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(started.status_code, 200, started.text)
        self.assertEqual(started.json()["status"], "queued")
        self.assertEqual(unloaded.status_code, 200, unloaded.text)
        self.assertGreaterEqual(unloaded.json()["cancelled_jobs"], 1)
        self.assertIs(unloaded.json()["model_loaded"], False)
        self.assertEqual(after.json()["status"], "cancelled")

    def test_hi3d_text_prompt_uses_a_minimax_still(self):
        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()
            core_runtime.core.save_config({"services": {
                "active_workspace": "default",
                "minimax_image_api_key": "test-key",
                "hi3d_api_key": "hi-key",
            }})
            seen = {}

            def fake_still(**kwargs):
                path = Path(kwargs["output_dir"]) / "still.png"
                path.write_bytes(b"png")
                return {"path": str(path)}

            def fake_hi3d(**kwargs):
                seen["image"] = kwargs.get("image_path")
                name = "hi3d-out.glb"
                Path(kwargs["output_dir"], name).write_bytes(b"glb")
                return {"filename": name}

            with patch("services.minimax_image_service.generate_image", side_effect=fake_still), patch(
                "services.hi3d_service.generate_model", side_effect=fake_hi3d,
            ), patch("services.execution_mode.validate_remote_provider"), patch(
                "services.core_remote_3d.threading.Thread", ImmediateThread,
            ):
                response = self.client.post("/api/v1/model3d/generate", json={
                    "provider": "hi3d", "prompt": "a clay robot", "workspace": "default",
                })
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(str(seen.get("image") or "").endswith("still.png"))

    def test_model3d_execution_mode_refusal_is_409(self):
        from services.execution_mode import ExecutionModeError
        with patch(
            "services.execution_mode.validate_generation",
            side_effect=ExecutionModeError("plan mode stops before queue submission"),
        ):
            response = self.client.post("/api/v1/model3d/generate", json={
                "provider": "meshy", "prompt": "a clay robot", "workspace": "default",
            })
        self.assertEqual(response.status_code, 409, response.text)

    def test_diagnostics_snapshot_and_report_on_the_core_profile(self):
        snapshot = self.client.get("/api/v1/diagnostics")
        self.assertEqual(snapshot.status_code, 200, snapshot.text)
        body = snapshot.json()
        self.assertEqual(body["schema"], "hocuspocus.user-diagnostics-report")
        self.assertIn("platform", body)
        self.assertIn("capabilities", body)
        report = self.client.post("/api/v1/diagnostics/report", json={
            "error": {"message": "MiniMax key missing", "code": "provider_unconfigured"},
        })
        self.assertEqual(report.status_code, 200, report.text)
        packed = report.json()
        self.assertEqual(packed["schema"], "hocuspocus.user-diagnostics-report")
        self.assertEqual(packed["error"]["code"], "provider_unconfigured")
        blob = json.dumps(packed)
        self.assertNotIn("sk-", blob)

    def test_series_reference_import_and_refresh_are_persisted_in_core(self):
        folder, previous = self._in_temp_workspace()
        try:
            series = self.client.post('/api/v1/series', json={'workspace':'default', 'title':'Reference test'}).json()
            series['canon']['worldSummary'] = 'A persistent world'
            series['characters'] = [{'id':'char_a', 'name':'Ada', 'referenceAssetIds':[]}]
            series['locations'] = [{'id':'loc_a', 'name':'Lab', 'referenceAssetIds':[]}]
            series['allowedProductionMethods'] = ['animation_2d', 'imported_video']
            path = f"/api/v1/series/{series['id']}"
            saved = self.client.put(path, json={'workspace':'default', 'series':series, 'baseRevision':series['revision']})
            self.assertEqual(saved.status_code, 200, saved.text)
            series = saved.json()
            series = self.client.post(path + '/canon/approve', json={'workspace':'default', 'baseRevision':series['canon']['revision']}).json()
            episode_response = self.client.post(path + '/episodes', json={'workspace':'default'})
            self.assertEqual(episode_response.status_code, 200, episode_response.text)
            episode = episode_response.json()
            Path('uploads').mkdir(exist_ok=True)
            portrait = Path('uploads/portrait.png')
            portrait.write_bytes(b'reference fixture')
            imported = self.client.post(path + '/assets/import', json={'workspace':'default', 'uploadPath':str(portrait.resolve()),
                'ownerType':'character', 'ownerId':'char_a', 'kind':'character', 'referenceRole':'primary_portrait',
                'metadata':{'prompt':'Ada in a paper cutout style', 'jobId':'image-job'}})
            self.assertEqual(imported.status_code, 200, imported.text)
            result = imported.json()
            self.assertEqual(result['series']['characters'][0]['referenceAssetIds'], [result['asset']['id']])
            self.assertEqual(result['asset']['metadata']['jobId'], 'image-job')
            self.assertEqual(result['series']['canon']['approval'], 'draft')
            retry = self.client.post(path + '/assets/import', json={'workspace':'default', 'uploadPath':str(portrait.resolve()),
                'ownerType':'character', 'ownerId':'char_a', 'kind':'character', 'metadata':{'jobId':'image-job'}})
            self.assertEqual(retry.status_code, 200, retry.text)
            self.assertEqual(retry.json()['asset']['id'], result['asset']['id'])
            self.assertEqual(retry.json()['series']['revision'], result['series']['revision'])
            approved = self.client.post(path + '/canon/approve', json={'workspace':'default', 'baseRevision':result['series']['canon']['revision']}).json()
            refreshed = self.client.post(path + f"/episodes/{episode['id']}/references/refresh", json={'workspace':'default', 'baseRevision':approved['revision']})
            self.assertEqual(refreshed.status_code, 200, refreshed.text)
            snapshot = refreshed.json()['episodesById'][episode['id']]['canonSnapshot']
            self.assertEqual(snapshot['characters'][0]['primaryReferenceAssetId'], result['asset']['id'])
            self.assertEqual(refreshed.json()['allowedProductionMethods'], ['animation_2d', 'imported_video'])
        finally:
            self._leave_temp_workspace(folder, previous)

    def test_a_location_plate_import_is_scanned_once_and_always_answers_its_warnings(self):
        folder, previous = self._in_temp_workspace()
        try:
            series = self.client.post('/api/v1/series', json={'workspace':'default', 'title':'Plate test'}).json()
            series['locations'] = [{'id':'loc_a', 'name':'Lab', 'referenceAssetIds':[]}]
            path = f"/api/v1/series/{series['id']}"
            saved = self.client.put(path, json={'workspace':'default', 'series':series, 'baseRevision':series['revision']})
            self.assertEqual(saved.status_code, 200, saved.text)
            Path('uploads').mkdir(exist_ok=True)
            plate = Path('uploads/plate.png')
            plate.write_bytes(b'plate fixture')
            scans = []
            with patch('services.series_plate_checks.detect_people', side_effect=lambda found: scans.append(found) or []):
                clean = self.client.post(path + '/assets/import', json={'workspace':'default', 'uploadPath':str(plate.resolve()),
                    'ownerType':'location', 'ownerId':'loc_a', 'kind':'image', 'referenceRole':'environment'})
                self.assertEqual(clean.status_code, 200, clean.text)
                self.assertEqual(clean.json()['warnings'], [])
                other = self.client.post(path + '/assets/import', json={'workspace':'default', 'uploadPath':str(plate.resolve()),
                    'ownerType':'location', 'ownerId':'loc_a', 'kind':'image', 'referenceRole':'reference'})
                self.assertEqual(other.status_code, 200, other.text)
                self.assertNotIn('warnings', other.json())
            self.assertEqual(len(scans), 1)
        finally:
            self._leave_temp_workspace(folder, previous)

    def test_mcp_settings_status_on_the_core_profile(self):
        listed = self.client.get("/api/v1/settings/mcp")
        self.assertEqual(listed.status_code, 200, listed.text)
        body = listed.json()
        self.assertEqual(body["endpoint"], "/api/v1/mcp")
        self.assertEqual(body["authentication"], "Bearer")
        self.assertNotIn("token", body)
        blocked = self.client.put("/api/v1/settings/mcp", json={"enabled": True})
        self.assertEqual(blocked.status_code, 403)
        closed = self.client.post("/api/v1/wangp/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
        self.assertEqual(closed.status_code, 503)

    def test_core_gallery_serves_the_thumbnails_its_rows_point_at(self):
        """Every row's thumbnail_url (and the sized route the gallery tiles ask for) answered 404 on core."""
        from PIL import Image
        from services import output_ops

        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()
            Path("uploads").mkdir()
            Image.new("RGB", (64, 48), (200, 30, 30)).save(Path("outputs") / "still.png")
            Image.new("RGB", (32, 32), (30, 30, 200)).save(Path("uploads") / "reference.png")
            Image.new("RGB", (8, 8), (0, 0, 0)).save("outside.png")
            Path("outputs", "notes.wav").write_bytes(b"RIFF")
            with patch.object(output_ops, "_MEDIA_THUMBNAIL_CACHE_DIR", str(Path(folder.name) / "thumbnails")):
                listings = {
                    workspace: self.client.get("/api/v1/outputs", params={"workspace": workspace})
                    for workspace in ("default", "__uploads__")
                }
                rows = [
                    row for response in listings.values() for row in response.json()["outputs"]
                    if row["type"] == "image"
                ]
                row_answers = {row["name"]: self.client.get(row["thumbnail_url"]).status_code for row in rows}
                sized = {
                    workspace: self.client.get(
                        f"/api/v1/outputs/thumbnail/{name}", params={"size": "sm", "workspace": workspace},
                    )
                    for workspace, name in (("default", "still.png"), ("__uploads__", "reference.png"))
                }
                escaped = self.client.get(
                    "/api/v1/outputs/thumbnail/..%2Foutside.png", params={"workspace": "__uploads__"},
                )
                missing = self.client.get("/api/v1/outputs/thumbnail/nothing.png", params={"workspace": "default"})
                audio = self.client.get("/api/v1/outputs/thumbnail/notes.wav", params={"workspace": "default"})
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(sorted(row_answers), ["reference.png", "still.png"])
        self.assertEqual(set(row_answers.values()), {200}, row_answers)
        for workspace, response in sized.items():
            self.assertEqual(response.status_code, 200, f"{workspace}: {response.text}")
            self.assertEqual(response.headers["content-type"], "image/webp")
        self.assertEqual(escaped.status_code, 404, escaped.text)
        self.assertEqual(missing.status_code, 404, missing.text)
        self.assertEqual(audio.status_code, 400, audio.text)

    def test_core_gallery_answers_400_for_a_bad_workspace_name_on_every_route(self):
        """The thumbnail route has no ValueError mapping of its own (the full server's lookup raises a 400 itself)."""
        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()
            answers = {
                (route, workspace): self.client.get(route, params={"workspace": workspace})
                for route in ("/api/v1/outputs/thumbnail/still.png", "/api/v1/file/still.png", "/api/v1/outputs")
                for workspace in ("../outside", "bad name", "")
                if (route, workspace) != ("/api/v1/outputs", "")  # an empty name lists the active workspace
            }
        finally:
            self._leave_temp_workspace(folder, previous)
        for (route, workspace), response in answers.items():
            self.assertEqual(response.status_code, 400, f"{route} workspace={workspace!r}: {response.text}")
            self.assertEqual(response.json(), {"detail": "Invalid workspace name"})

    def test_core_thumbnail_binding_leaves_the_other_output_ops_slots_alone(self):
        """Both servers can be imported in one process; core binds only safe_join, never the full server's slots."""
        from services import output_ops

        sentinel = object()
        with patch.object(output_ops, "_load_favorites", sentinel), patch.object(output_ops, "_safe_join", None):
            output_ops.configure_thumbnails(safe_join="join")
            self.assertEqual(output_ops._safe_join, "join")
            self.assertIs(output_ops._load_favorites, sentinel)

    def test_core_refuses_browser_mutations_from_another_origin(self):
        """A foreign page can send a simple POST (text/plain) to a loopback port; core must refuse it like the full server."""
        evil = {"Origin": "http://evil.example"}
        folder, previous = self._in_temp_workspace()
        try:
            kept = self.client.post("/api/v1/workspaces", json={"name": "keep-me"})
            simple_post = self.client.post(
                "/api/v1/workspaces", content='{"name": "csrf-made"}', headers={**evil, "Content-Type": "text/plain"},
            )
            switched = self.client.put("/api/v1/workspaces/active", json={"name": "keep-me"}, headers=evil)
            deleted = self.client.delete("/api/v1/workspaces/keep-me", headers=evil)
            read = self.client.get("/api/v1/workspaces", headers=evil)
            same_origin = self.client.post(
                "/api/v1/workspaces", json={"name": "made-here"}, headers={"Origin": "http://testserver"},
            )
            pinokio_proxy = self.client.post(
                "/api/v1/workspaces", json={"name": "made-by-proxy"}, headers={"Origin": "https://42003.localhost"},
            )
            outputs = Path("outputs")
            created = sorted(item.name for item in outputs.iterdir())
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(kept.status_code, 200, kept.text)
        for label, response in (("simple POST", simple_post), ("PUT", switched), ("DELETE", deleted)):
            self.assertEqual(response.status_code, 403, f"{label}: {response.text}")
            self.assertEqual(response.json(), {"detail": "Cross-origin API mutations are not allowed"})
        self.assertEqual(read.status_code, 200, read.text)
        self.assertEqual(same_origin.status_code, 200, same_origin.text)
        self.assertEqual(pinokio_proxy.status_code, 200, pinokio_proxy.text)
        self.assertEqual(created, ["keep-me", "made-by-proxy", "made-here"])

    def test_core_stacks_the_browser_guards_like_the_full_server(self):
        """Outermost first: the cross-origin check wraps CORS, which wraps the Host check."""
        names = [getattr(item.kwargs.get("dispatch"), "__name__", item.cls.__name__) for item in api.user_middleware]
        guards = ("protect_cross_origin_mutations", "CORSMiddleware", "guard_host")
        self.assertEqual([name for name in names if name in guards], list(guards))

    def test_core_answers_the_full_servers_origin_matrix(self):
        """The characterization test drives the same cases through the full server; the two must stay equal."""
        from tests.support.origin_cases import ORIGIN_CASES, REFUSED, answer, refused_by_origin

        client = TestClient(api, raise_server_exceptions=False)
        self.assertEqual(refused_by_origin(client), list(ORIGIN_CASES))
        evil = {"origin": "http://evil.example", "host": "127.0.0.1:42003"}
        form = 'name=x'
        multipart = '--b\r\nContent-Disposition: form-data; name="file"; filename="a.png"\r\n\r\nx\r\n--b--\r\n'
        for label, headers, body in (
            ("urlencoded form", {**evil, "content-type": "application/x-www-form-urlencoded"}, form),
            ("multipart upload", {**evil, "content-type": "multipart/form-data; boundary=b"}, multipart),
            ("agent token with a page origin", {**evil, "authorization": "Bearer agent"}, None),
        ):
            self.assertEqual(answer(client.post("/api/v1/upload", headers=headers, content=body)), REFUSED, label)
        referer_only = client.post("/api/v1/__guard_probe__", headers={"referer": "http://evil.example/"})
        self.assertEqual(referer_only.status_code, 404)  # no Origin: a script or MCP client, as on the full server
        rebound = client.post("/api/v1/__guard_probe__", headers={"origin": "http://evil.example:42003",
                                                                  "host": "evil.example:42003"})
        self.assertEqual(rebound.status_code, 421)  # DNS rebinding passes the origin check; the Host guard stops it

    def test_settings_token_gates_core_mcp_and_closes_when_disabled(self):
        folder = tempfile.TemporaryDirectory()
        original_path = core_runtime._mcp_access.path
        client = TestClient(api, base_url="http://127.0.0.1:8080")
        origin = {"Origin": "http://127.0.0.1:8080"}
        ping = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
        try:
            core_runtime._mcp_access.path = Path(folder.name) / "mcp-access.json"
            self.assertEqual(client.post("/api/v1/wangp/mcp", json=ping).status_code, 503)
            created = client.put("/api/v1/settings/mcp", json={"enabled": True}, headers=origin)
            self.assertEqual(created.status_code, 200, created.text)
            token = created.json()["token"]
            self.assertGreaterEqual(len(token), 40)
            authorized = {"Authorization": f"Bearer {token}"}
            opened = client.post("/api/v1/wangp/mcp", headers=authorized, json=ping)
            self.assertEqual(opened.status_code, 200, opened.text)
            leaked = client.post("/api/v1/wangp/mcp", json=ping)
            self.assertEqual(leaked.status_code, 401)
            client.put("/api/v1/settings/mcp", json={"enabled": False}, headers=origin)
            self.assertEqual(client.post("/api/v1/wangp/mcp", headers=authorized, json=ping).status_code, 503)
        finally:
            core_runtime._mcp_access.path = original_path
            folder.cleanup()

    def test_remote_llm_load_is_not_blocked_as_local_engine(self):
        with patch("services.llm_service.load_model"), patch(
            "services.llm_service.get_status", return_value={"loaded": False, "provider": "minimax"},
        ):
            response = self.client.post("/api/v1/llm/load", json={"provider": "minimax", "model_id": "MiniMax-M3"})
        self.assertEqual(response.status_code, 200)

    def test_llm_prompt_tools_use_remote_llm_and_hide_h3_planner(self):
        missing = self.client.post("/api/v1/llm/enhance-prompt", json={})
        self.assertEqual(missing.status_code, 400, missing.text)
        self.assertEqual(missing.json()["detail"], "prompt is required")
        with patch("services.llm_service.is_loaded", return_value=False), patch(
            "services.llm_service.load_model",
        ), patch("services.llm_service.enhance_prompt", return_value="a talking cat") as enhance:
            enhanced = self.client.post("/api/v1/llm/enhance-prompt", json={"prompt": "a cat", "mode": "image"})
        self.assertEqual(enhanced.status_code, 200, enhanced.text)
        self.assertEqual(enhanced.json(), {"original": "a cat", "enhanced": "a talking cat"})
        enhance.assert_called_once()
        with patch("services.llm_service.is_loaded", return_value=False), patch(
            "services.llm_service.load_model",
        ), patch("services.llm_service.describe_image", return_value="a red cube") as describe:
            described = self.client.post("/api/v1/llm/describe-image", json={"image_path": "/tmp/cube.png"})
        self.assertEqual(described.status_code, 200, described.text)
        self.assertEqual(described.json(), {"description": "a red cube"})
        describe.assert_called_once()
        planned = self.client.post(
            "/api/v1/llm/plan-h3-windows",
            json={"prompt": "Clark turns toward the truck", "model_type": "minimax_h3"},
        )
        self.assertEqual(planned.status_code, 409, planned.text)
        self.assertEqual(planned.json()["detail"]["code"], FEATURE_UNAVAILABLE)

    def test_video3d_world3d_save_persists_the_document(self):
        document = SceneCommands(None).execute({
            "version": 1,
            "operation": "scenes.effects.showcase",
            "input": {"dimension": "3d", "collection": "anime"},
        })["result"]["document"]
        preview = "data:image/png;base64," + base64.b64encode(
            b"\x89PNG\r\n\x1a\npreview"
        ).decode()
        folder, previous = self._in_temp_workspace()
        try:
            missing = self.client.post("/api/v1/scenes/world3d", json=[])
            saved = self.client.post("/api/v1/scenes/world3d", json={
                "workspace": "default",
                "document": document,
                "name": "../My shot / v2",
                "preview": preview,
            })
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(missing.status_code, 422)
        self.assertEqual(saved.status_code, 200, saved.text)
        body = saved.json()
        self.assertTrue(body["name"].endswith(".world3d.scene.json"))
        self.assertIn("workspace=default", body["url"])
        self.assertNotIn("..", body["name"])

    def test_world3d_export_admits_on_the_core_profile(self):
        document = {
            "version": 1, "units": "meters", "up": "y", "width": 64, "height": 64,
            "fps": 30, "duration": 2 / 30, "templateId": "two-shot",
            "camera": {"family": "establishment", "eye": [0, 1.6, 4.2], "look": [0, 1, 0], "fov": 50},
            "light": {"kind": "directional", "direction": [-0.35, -1, -0.25], "intensity": 1.15, "color": "#fff4e5"},
            "slots": [{
                "id": "subject_1", "slot": "subject_1", "position": [0, 0, 0], "rotationY": 0,
                "scale": 1, "sourceUrl": "", "media": "model3d", "clip": None,
            }],
        }
        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()
            catalog = self.client.get("/api/v1/scenes/world3d/export/commands")
            with patch("services.world3d_export.threading.Thread", ImmediateThread):
                admitted = self.client.post("/api/v1/scenes/world3d/export", json={
                    "version": 1,
                    "operation": "scenes.world3d.export",
                    "intent_id": "mac-world3d-export",
                    "input": {"workspace": "default", "document": document, "refs": []},
                })
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(catalog.status_code, 200, catalog.text)
        names = {item.get("name") for item in catalog.json().get("operations") or []}
        self.assertIn("scenes.world3d.export", names)
        self.assertEqual(admitted.status_code, 200, admitted.text)
        body = admitted.json()
        self.assertFalse(body["replayed"])
        self.assertEqual(body["receipt"]["operation"], "scenes.world3d.export")
        self.assertTrue(body["receipt"]["taskIds"])

    def test_scene_packages_export_and_import_on_the_core_profile(self):
        from services.scene_packages import PACKAGE_KIND

        document = {
            "version": 1, "units": "meters", "up": "y", "width": 64, "height": 64,
            "fps": 30, "duration": 1, "templateId": "two-shot",
            "camera": {"family": "establishment", "eye": [0, 1.6, 4.2], "look": [0, 1, 0], "fov": 50},
            "light": {"kind": "directional", "direction": [-0.35, -1, -0.25], "intensity": 1.15, "color": "#fff4e5"},
            "slots": [{
                "id": "subject_1", "slot": "subject_1", "position": [0, 0, 0], "rotationY": 0,
                "scale": 1,
                "sourceUrl": "/api/v1/file/hero.glb?workspace=default",
                "sourceRef": {
                    "workspaceId": "default",
                    "filename": "hero.glb",
                    "url": "/api/v1/file/hero.glb?workspace=default",
                    "assetId": "asset_hero",
                },
                "media": "model3d",
                "clip": None,
            }],
        }
        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()
            Path("outputs", "lab").mkdir()
            Path("outputs", "hero.glb").write_bytes(b"glb-core-package")
            catalog = self.client.get("/api/v1/scene-packages/format")
            missing = self.client.post("/api/v1/scene-packages/export", json={})
            exported = self.client.post("/api/v1/scene-packages/export", json={
                "workspace": "default",
                "title": "Harbour",
                "documents": [document],
            })
            imported = self.client.post(
                "/api/v1/scene-packages/import",
                params={"workspace": "lab"},
                content=exported.content,
                headers={"Content-Type": "application/zip"},
            )
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(catalog.status_code, 200, catalog.text)
        self.assertEqual(catalog.json()["kind"], PACKAGE_KIND)
        self.assertEqual(missing.status_code, 422, missing.text)
        self.assertEqual(exported.status_code, 200, exported.text)
        self.assertTrue(exported.headers.get("content-type", "").startswith("application/zip"))
        self.assertIn("harbour.scene-package.zip", exported.headers.get("content-disposition", "").lower())
        self.assertEqual(imported.status_code, 200, imported.text)
        body = imported.json()
        self.assertTrue(body["ok"])
        self.assertEqual(len(body["scenes"]), 1)
        self.assertGreaterEqual(body["assets_created"], 1)

    def test_wizard_conversation_put_round_trips_instead_of_emptying(self):
        conversation = {
            "version": 1,
            "revision": 0,
            "messages": [{
                "id": "msg-1",
                "role": "user",
                "text": "Exporta el plano",
                "createdAt": 1,
            }],
            "executions": [],
        }
        folder, previous = self._in_temp_workspace()
        try:
            empty = self.client.get("/api/v1/wizard/conversations")
            saved = self.client.put("/api/v1/wizard/conversations", json={
                "workspace": "default",
                "baseRevision": 0,
                "conversation": conversation,
            })
            loaded = self.client.get("/api/v1/wizard/conversations")
            conflict = self.client.put("/api/v1/wizard/conversations", json={
                "workspace": "default",
                "baseRevision": 0,
                "conversation": conversation,
            })
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(empty.status_code, 200)
        self.assertEqual(empty.json()["messages"], [])
        self.assertEqual(empty.json()["revision"], 0)
        self.assertNotIn("conversations", empty.json())
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["revision"], 1)
        self.assertEqual(saved.json()["messages"][0]["text"], "Exporta el plano")
        self.assertEqual(loaded.json()["messages"][0]["id"], "msg-1")
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json()["detail"]["code"], "wizard_conversation_revision_conflict")

    def test_wizard_get_rejects_an_invalid_workspace_name(self):
        conversation = self.client.get("/api/v1/wizard/conversations", params={"workspace": "../escape"})
        workflows = self.client.get("/api/v1/wizard/workflows", params={"workspace": "../escape"})
        self.assertEqual(conversation.status_code, 400, conversation.text)
        self.assertEqual(workflows.status_code, 400, workflows.text)
        self.assertNotIn("Could not read", conversation.text)
        self.assertNotIn("Could not read", workflows.text)
        # A workspace folder that cannot be created is a 500 with the Wizard message, as before the router was shared.
        with patch("services.core_workspace.workspace_dir", side_effect=OSError("disk full")):
            unreadable = self.client.get("/api/v1/wizard/conversations")
            unsaved = self.client.put("/api/v1/wizard/workflows", json={"workspace": "default", "collection": {}})
        self.assertEqual(unreadable.status_code, 500, unreadable.text)
        self.assertIn("Could not read the Wizard conversation: disk full", unreadable.json()["detail"])
        self.assertEqual(unsaved.status_code, 500, unsaved.text)
        self.assertIn("Could not save Wizard workflows: disk full", unsaved.json()["detail"])

    def test_wizard_put_rejects_a_json_array(self):
        conversation = self.client.put("/api/v1/wizard/conversations", json=["not", "an", "object"])
        workflows = self.client.put("/api/v1/wizard/workflows", json=["not", "an", "object"])
        self.assertEqual(conversation.status_code, 422, conversation.text)
        self.assertEqual(workflows.status_code, 422, workflows.text)

    def test_video_editor_export_name_cannot_escape_the_workspace(self):
        from services import core_workspace as core

        def fake_render(_clips, destination, **_kwargs):
            Path(destination).write_bytes(b"export")
            return {"duration": 1}

        folder, previous = self._in_temp_workspace()
        try:
            workspace = core.workspace_dir("default")
            Path(workspace, "clip.mp4").write_bytes(b"x")
            with patch("routers.video_editor.render_project", side_effect=fake_render), patch(
                "routers.video_editor.threading.Thread", ImmediateThread,
            ):
                started = self.client.post("/api/v1/video-editor/export", json={
                    "clips": [{"source": "clip.mp4"}],
                    "name": "../etc/passwd / cut",
                    "workspace": "default",
                })
                job = self.client.get(
                    f"/api/v1/video-editor/export/{started.json()['job_id']}",
                ).json()
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(started.status_code, 202, started.text)
        self.assertEqual(job["status"], "completed", job)
        self.assertNotIn("..", job["filename"])
        self.assertNotIn("/", job["filename"])
        self.assertTrue(job["filename"].endswith("_etc_passwd_cut.mp4"))

    def test_video_editor_screenshot_keeps_each_character_sheet_frame(self):
        from services import core_workspace as core

        def fake_extract(source, dest, time_seconds):
            Path(dest).write_bytes(f"frame-{time_seconds}".encode())
            return {"time": time_seconds, "width": 8, "height": 8}

        folder, previous = self._in_temp_workspace()
        try:
            workspace = core.workspace_dir("default")
            Path(workspace, "orbit.mp4").write_bytes(b"clip")
            with patch("routers.video_editor.time.strftime", return_value="2026-09-11-13h55m00s"), patch(
                "routers.video_editor.extract_frame", side_effect=fake_extract,
            ):
                first = self.client.post("/api/v1/video-editor/screenshot", json={
                    "source": "orbit.mp4",
                    "time": 0.1,
                    "name": "character_front",
                    "workspace": "default",
                })
                second = self.client.post("/api/v1/video-editor/screenshot", json={
                    "source": "orbit.mp4",
                    "time": 0.8,
                    "name": "character_front",
                    "workspace": "default",
                })
                first_name = first.json()["filename"]
                second_name = second.json()["filename"]
                first_bytes = Path(workspace, first_name).read_bytes()
                second_bytes = Path(workspace, second_name).read_bytes()
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(first_name, "2026-09-11-13h55m00s_character_front_frame.png")
        self.assertEqual(second_name, "2026-09-11-13h55m00s_character_front_frame_2.png")
        self.assertEqual(first_bytes, b"frame-0.1")
        self.assertEqual(second_bytes, b"frame-0.8")

    def test_video_editor_export_keeps_a_second_same_second_cut(self):
        from services import core_workspace as core

        def fake_render(clips, destination, **_kwargs):
            Path(destination).write_bytes(f"export-{len(clips)}".encode())
            return {"duration": 1}

        folder, previous = self._in_temp_workspace()
        try:
            workspace = core.workspace_dir("default")
            Path(workspace, "clip.mp4").write_bytes(b"clip")
            with patch("routers.video_editor.time.strftime", return_value="2026-09-11-13h55m00s"), patch(
                "routers.video_editor.threading.Thread", ImmediateThread,
            ), patch("routers.video_editor.render_project", side_effect=fake_render):
                first_response = self.client.post("/api/v1/video-editor/export", json={
                    "clips": [{"source": "clip.mp4"}],
                    "name": "Harbour cut",
                    "workspace": "default",
                })
                second_response = self.client.post("/api/v1/video-editor/export", json={
                    "clips": [{"source": "clip.mp4"}, {"source": "clip.mp4"}],
                    "name": "Harbour cut",
                    "workspace": "default",
                })
                first = self.client.get(
                    f"/api/v1/video-editor/export/{first_response.json()['job_id']}",
                ).json()
                second = self.client.get(
                    f"/api/v1/video-editor/export/{second_response.json()['job_id']}",
                ).json()
                first_bytes = Path(workspace, first["filename"]).read_bytes()
                second_bytes = Path(workspace, second["filename"]).read_bytes()
                sidecar = Path(workspace, first["filename"]).with_suffix(".meta.json").read_text(encoding="utf-8")
                listed = self.client.get("/api/v1/tasks", params={"workspace": "default", "status": "all"})
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(first_response.status_code, 202, first_response.text)
        self.assertEqual(second_response.status_code, 202, second_response.text)
        self.assertEqual(first["filename"], "2026-09-11-13h55m00s_Harbour_cut.mp4")
        self.assertEqual(second["filename"], "2026-09-11-13h55m00s_Harbour_cut_2.mp4")
        self.assertEqual(first_bytes, b"export-1")
        self.assertEqual(second_bytes, b"export-2")
        self.assertIn("video_editor", sidecar)
        workflows = {item.get("workflow") for item in listed.json().get("tasks") or []}
        self.assertIn("video-editor", workflows)

    def test_video_editor_rejects_an_invalid_trim_and_has_a_cancel_route(self):
        """The shared editor rejects a backwards trim before it looks up media,
        and a missing export has a cancel route."""
        folder, previous = self._in_temp_workspace()
        try:
            rejected = self.client.post("/api/v1/video-editor/export", json={
                "clips": [{"source": "clip.mp4"}],
                "soundtrack": {"source": "song.mp3", "trim_start": 5, "trim_end": 2},
                "workspace": "default",
            })
            layered = self.client.post("/api/v1/video-editor/export", json={
                "clips": [{"source": "clip.mp4"}],
                "audio_cues": [{
                    "source": "sting.mp3",
                    "start": 0,
                    "trim_start": 4,
                    "trim_end": 1,
                }],
                "workspace": "default",
            })
            huge = self.client.post("/api/v1/video-editor/export", json={
                "clips": [{"source": "clip.mp4"}],
                "width": 8000,
                "height": 8000,
                "workspace": "default",
            })
            missing = self.client.post("/api/v1/video-editor/export/does-not-exist/cancel")
            foreign = self.client.post("/api/v1/video-editor/export", json={
                "clips": [{"source": "clip.mp4"}],
                "workspace": "../outside",
            })
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(rejected.status_code, 400, rejected.text)
        self.assertIn("trim", str(rejected.json()["detail"]).lower())
        self.assertEqual(layered.status_code, 400, layered.text)
        self.assertIn("trim", str(layered.json()["detail"]).lower())
        self.assertEqual(huge.status_code, 400, huge.text)
        self.assertIn("resolution", str(huge.json()["detail"]).lower())
        self.assertEqual(missing.status_code, 404, missing.text)
        self.assertIn("Video editor export job not found", str(missing.json()["detail"]))
        self.assertEqual(foreign.status_code, 400, foreign.text)
        self.assertIn("Invalid workspace name", str(foreign.json()["detail"]))

    def test_activity_cancel_stops_a_queued_video_editor_export(self):
        """Core Activity now lists editor exports; Cancel must stop FFmpeg, not MiniMax."""
        from services import core_workspace as core

        class FrozenThread:
            def __init__(self, target=None, args=(), kwargs=None, daemon=None, name=None):
                pass

            def start(self):
                return None

        folder, previous = self._in_temp_workspace()
        try:
            workspace = core.workspace_dir("default")
            Path(workspace, "clip.mp4").write_bytes(b"clip")
            with patch("routers.video_editor.threading.Thread", FrozenThread):
                started = self.client.post("/api/v1/video-editor/export", json={
                    "clips": [{"source": "clip.mp4"}],
                    "name": "Harbour cut",
                    "workspace": "default",
                })
                job_id = started.json()["job_id"]
                listed = self.client.get("/api/v1/tasks", params={"workspace": "default", "status": "all"})
                editor = next(
                    task for task in listed.json().get("tasks") or []
                    if task.get("backend_job_id") == job_id
                )
                cancelled = self.client.post(
                    f"/api/v1/tasks/{editor['id']}/cancel",
                    params={"workspace": "default"},
                )
                status = self.client.get(f"/api/v1/video-editor/export/{job_id}")
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(started.status_code, 202, started.text)
        self.assertTrue(editor.get("cancelable"), editor)
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        self.assertEqual(status.status_code, 200, status.text)
        self.assertEqual(status.json()["status"], "cancelled", status.json())
        self.assertEqual(cancelled.json()["task"]["status"], "cancelled")

    def _activity_row(self, adapter, job_id, **fields):
        """The Activity row a router publishes for one backend job, so Cancel/Resume have something to act on."""
        return core_canonical_tasks.upsert_task(
            "default", f"task-{adapter}-{job_id}", kind=adapter, workflow=adapter, title=adapter, status="queued",
            backend_job_id=job_id, cancelable=True, metadata={"adapter": adapter}, **fields,
        )

    def _activity_control(self, row, action="cancel"):
        return self.client.post(f"/api/v1/tasks/{row['id']}/{action}", params={"workspace": "default"})

    def test_activity_cancel_reaches_the_jobs_of_the_routers_core_mounts(self):
        """Before the controls table, every adapter but MiniMax image answered 404 "Task not found"."""
        from services import core_remote_3d, rig_service, story_music_jobs

        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()
            rig_service._jobs["rig-act"] = {"job_id": "rig-act", "status": "queued", "workspace": "default"}
            core_remote_3d._JOBS["m3d-act"] = {"job_id": "m3d-act", "status": "queued", "workspace": "default"}
            with story_music_jobs._minimax_music_jobs_lock:
                story_music_jobs._minimax_music_jobs["minimax-music-aaaaaaaaaaaa"] = {
                    "jobId": "minimax-music-aaaaaaaaaaaa", "workspace": "default", "status": "queued", "children": [],
                }
            rows = {
                "rig": self._activity_row("rig", "rig-act"),
                "model3d": self._activity_row("model3d", "m3d-act"),
                "minimax-music": self._activity_row("minimax-music", "minimax-music-aaaaaaaaaaaa"),
            }
            answers = {name: self._activity_control(row) for name, row in rows.items()}
            states = {
                "rig": rig_service._jobs["rig-act"]["status"],
                "model3d": core_remote_3d._JOBS["m3d-act"]["status"],
                "minimax-music": story_music_jobs._minimax_music_jobs["minimax-music-aaaaaaaaaaaa"]["status"],
            }
        finally:
            rig_service._jobs.pop("rig-act", None)
            with story_music_jobs._minimax_music_jobs_lock:
                story_music_jobs._minimax_music_jobs.clear()
            self._leave_temp_workspace(folder, previous)
        for name, answer in answers.items():
            self.assertEqual(answer.status_code, 200, f"{name}: {answer.text}")
            self.assertEqual(states[name], "cancelled", name)

    def test_activity_cancel_of_a_music_candidate_row_cancels_its_job(self):
        from services import story_music_jobs

        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()
            job_id = "minimax-music-bbbbbbbbbbbb"
            with story_music_jobs._minimax_music_jobs_lock:
                story_music_jobs._minimax_music_jobs[job_id] = {
                    "jobId": job_id, "workspace": "default", "status": "queued", "children": [],
                }
            row = self._activity_row(
                "minimax-music-candidate", f"{job_id}-1", root_id=f"task-minimax-music-{job_id}",
            )
            answer = self._activity_control(row)
            state = story_music_jobs._minimax_music_jobs[job_id]["status"]
        finally:
            with story_music_jobs._minimax_music_jobs_lock:
                story_music_jobs._minimax_music_jobs.clear()
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(answer.status_code, 200, answer.text)
        self.assertEqual(state, "cancelled")

    def test_activity_cancel_and_discard_reach_a_queued_series_assembly(self):
        class FrozenThread:
            def __init__(self, target=None, args=(), kwargs=None, daemon=None, name=None):
                pass

            def start(self):
                return None

        from routers import series_assembly
        from services import core_workspace as core

        folder, previous = self._in_temp_workspace()
        try:
            series = self._ready_to_assemble()
            # Assembly controllers are keyed by workspace folder when the router is built. Core's folders are
            # relative to the working directory, which this test moved, so register the temp one the same way.
            controller = series_assembly._ASSEMBLY_CONTROLLERS[CORE_ASSEMBLY_KEY]
            controllers = patch.dict(series_assembly._ASSEMBLY_CONTROLLERS, {
                os.path.realpath(core.workspace_dir("default")): controller,
            })
            controllers.start()
            self.addCleanup(controllers.stop)
            with patch("routers.series_assembly.threading.Thread", FrozenThread):
                started = self.client.post(
                    f"/api/v1/series/{series['id']}/episodes/episode-1/assembly/start", json={"workspace": "default"},
                )
            job_id = started.json()["jobId"]
            listed = self.client.get("/api/v1/tasks", params={"workspace": "default", "status": "all"})
            row = next(task for task in listed.json()["tasks"] if task.get("backend_job_id") == job_id)
            cancelled = self._activity_control(row)
            status = self.client.get(f"/api/v1/series/assembly/jobs/{job_id}", params={"workspace": "default"})
            discarded = self.client.delete(f"/api/v1/tasks/{row['id']}", params={"workspace": "default"})
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(started.status_code, 200, started.text)
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        # The worker is frozen, so the job waits for its cancellation boundary instead of settling.
        self.assertEqual(status.json()["status"], "cancelling", status.json())
        self.assertEqual(discarded.status_code, 409, discarded.text)
        self.assertIn("Cancel the active assembly", discarded.text, "the discard reached the assembly controller")

    def test_activity_control_of_an_adapter_without_a_handler_keeps_the_old_answers(self):
        """Core does not mount the audio router: its rows still answer as before (404 / 409), not with a guess."""
        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()
            row = self._activity_row("audio-analysis", "audio-analysis-aaaaaaaaaaaa")
            cancelled = self._activity_control(row)
            resumed = self._activity_control(row, "resume")
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(cancelled.status_code, 404, cancelled.text)
        self.assertEqual(resumed.status_code, 409, resumed.text)

    def test_task_controls_treat_retry_as_resume_and_the_last_registration_wins(self):
        from services import task_controls

        task_controls.register("unit-adapter", "resume", lambda task: "first")
        task_controls.register("unit-adapter", "resume", lambda task: "second")
        try:
            self.assertEqual(task_controls.handler_for("unit-adapter", "retry")({}), "second")
            self.assertEqual(task_controls.handler_for("unit-adapter", "RESUME")({}), "second")
            self.assertIsNone(task_controls.handler_for("unit-adapter", "cancel"))
            self.assertIsNone(task_controls.handler_for("", "cancel"))
            with self.assertRaises(ValueError):
                task_controls.register("unit-adapter", "cancel", None)
            self.assertEqual(task_controls.job_id({"backend_job_id": 7}), "7")
        finally:
            task_controls._handlers.pop(("unit-adapter", "resume"), None)

    def test_production_profile_defaults_to_remote_providers(self):
        listed = self.client.get("/api/v1/production-profile")
        self.assertEqual(listed.status_code, 200)
        profile = listed.json()["profile"]
        self.assertEqual(profile["text"]["provider"], "minimax")
        self.assertEqual(profile["image"]["provider"], "minimax")
        # Music is local first: the paid MiniMax API is never a default.
        self.assertEqual(profile["music"], {"provider": "local", "model": "ace_step_v1_5_xl_sft_lm_4b"})
        self.assertEqual(profile["model3d"]["provider"], "meshy")

    def test_mcp_lists_read_tools_and_omits_local_generate(self):
        headers = {"Authorization": "Bearer core-mcp-token"}
        with patch.object(core_runtime._mcp_access, "token", return_value="core-mcp-token"):
            denied = self.client.post("/api/v1/wangp/mcp", json={
                "jsonrpc": "2.0", "id": 1, "method": "tools/list",
            })
            self.assertEqual(denied.status_code, 401)
            response = self.client.post("/api/v1/wangp/mcp", headers=headers, json={
                "jsonrpc": "2.0", "id": 1, "method": "tools/list",
            })
            generate = self.client.post(
                "/api/v1/wangp/mcp", headers=headers, json={"params": {"name": "generate"}},
            )
        self.assertEqual(response.status_code, 200)
        names = {tool["name"] for tool in response.json()["result"]["tools"]}
        self.assertIn("assets", names)
        self.assertNotIn("generate", names)
        self.assertEqual(generate.status_code, 409)
        self.assertEqual(generate.json()["detail"]["code"], FEATURE_UNAVAILABLE)

    def test_story_and_series_libraries_persist(self):
        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()
            library = self.client.put("/api/v1/stories/library", json={
                "workspace": "default",
                "baseRevision": 0,
                "library": {"version": 2, "revision": 0, "activeId": "", "projects": {}},
            })
            created = self.client.post("/api/v1/series", json={"workspace": "default", "title": "Mac series"})
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(library.status_code, 200)
        self.assertEqual(created.status_code, 200)
        self.assertTrue(str(created.json()["id"]).startswith("series_"))

    def _ready_to_assemble(self):
        """Two approved clips of one episode, written to the temp workspace's library; returns the series."""
        from services.series_library import (
            create_series_project,
            empty_series_library,
            write_series_library,
        )

        Path("outputs").mkdir()
        Path("outputs", "one.mp4").write_bytes(b"one")
        Path("outputs", "two.mp4").write_bytes(b"two")
        series = create_series_project("default", title="Harbour")
        season_id = series["seasons"][0]["id"]
        series["assets"] = {
            "asset-1": {"id": "asset-1", "kind": "video", "uri": "outputs/one.mp4",
                        "ownerType": "episode", "ownerId": "episode-1"},
            "asset-2": {"id": "asset-2", "kind": "video", "uri": "outputs/two.mp4",
                        "ownerType": "episode", "ownerId": "episode-1"},
        }
        series["episodesById"] = {
            "episode-1": {
                "id": "episode-1",
                "seasonId": season_id,
                "script": [{"id": "scene_1", "beats": [], "dialogue": []}],
                "shots": [{
                    "id": "shot-2", "order": 2, "sceneId": "scene_1",
                    "approvedAttemptId": "attempt-2",
                    "attempts": [{"id": "attempt-2", "status": "completed",
                                  "outputAssetIds": ["asset-2"]}],
                }, {
                    "id": "shot-1", "order": 1, "sceneId": "scene_1",
                    "approvedAttemptId": "attempt-1",
                    "attempts": [{"id": "attempt-1", "status": "completed",
                                  "outputAssetIds": ["asset-1"]}],
                }],
            },
        }
        series["seasons"][0]["episodeOrder"] = ["episode-1"]
        library = empty_series_library("default")
        library["seriesById"][series["id"]] = series
        library["seriesOrder"] = [series["id"]]
        write_series_library(str(Path("outputs")), library, "default")
        return series

    def test_series_assembly_joins_approved_clips_on_the_core_profile(self):
        def concatenate(paths, output_path, **_kwargs):
            Path(output_path).write_bytes(b"".join(Path(path).read_bytes() for path in paths))
            return True

        folder, previous = self._in_temp_workspace()
        try:
            series = self._ready_to_assemble()
            with patch("services.core_series_assembly.concatenate_clips", side_effect=concatenate), patch(
                "routers.series_assembly.threading.Thread", ImmediateThread,
            ):
                missing = self.client.post(
                    "/api/v1/series/missing/episodes/episode-1/assembly/start",
                    json={"workspace": "default"},
                )
                started = self.client.post(
                    f"/api/v1/series/{series['id']}/episodes/episode-1/assembly/start",
                    json={"workspace": "default"},
                )
                job = started.json() if started.status_code == 200 else {}
                status = self.client.get(
                    f"/api/v1/series/assembly/jobs/{job.get('jobId')}",
                    params={"workspace": "default"},
                )
                listed = self.client.get("/api/v1/series/assembly/recovery", params={"workspace": "default"})
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(missing.status_code, 404, missing.text)
        self.assertEqual(started.status_code, 200, started.text)
        self.assertEqual(status.status_code, 200, status.text)
        body = status.json()
        self.assertEqual(body["status"], "completed", status.text)
        self.assertTrue(body["assetId"])
        self.assertTrue(str(body["filename"]).endswith(".mp4"))
        self.assertEqual(listed.status_code, 200, listed.text)

    def test_series_import_copies_story_uploads_into_the_workspace(self):
        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()
            Path("uploads").mkdir()
            Path("uploads", "hero.png").write_bytes(b"png-bytes")
            saved = self.client.put("/api/v1/stories/library", json={
                "workspace": "default",
                "baseRevision": 0,
                "library": {
                    "version": 2,
                    "revision": 0,
                    "activeId": "story_mac",
                    "projects": {
                        "story_mac": {
                            "id": "story_mac",
                            "title": "Harbour",
                            "premise": "A lantern wakes the harbour.",
                            "assets": {
                                "asset_hero": {
                                    "id": "asset_hero",
                                    "name": "Hero",
                                    "source": "/api/v1/uploads/hero.png",
                                }
                            },
                            "characters": [{
                                "id": "char_keeper",
                                "name": "Keeper",
                                "referenceAssetIds": ["asset_hero"],
                                "primaryReferenceAssetId": "asset_hero",
                            }],
                        }
                    },
                },
            })
            imported = self.client.post("/api/v1/series/import-story", json={
                "workspace": "default",
                "storyId": "story_mac",
            })
            series = imported.json() if imported.status_code == 200 else {}
            copied_bytes = b""
            copied_count = 0
            if series.get("id"):
                assets_dir = Path("outputs") / "assets" / series["id"]
                copied = list(assets_dir.glob("*")) if assets_dir.is_dir() else []
                copied_count = len(copied)
                copied_bytes = copied[0].read_bytes() if copied else b""
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(imported.status_code, 200, imported.text)
        assets = series.get("assets") or {}
        self.assertIn("asset_hero", assets)
        self.assertTrue(str(assets["asset_hero"]["uri"]).startswith(f"assets/{series['id']}/"))
        self.assertTrue(str(assets["asset_hero"]["uri"]).endswith(".png"))
        self.assertEqual(series["characters"][0]["referenceAssetIds"], ["asset_hero"])
        self.assertEqual(series["characters"][0]["primaryReferenceAssetId"], "asset_hero")
        self.assertEqual(copied_count, 1)
        self.assertEqual(copied_bytes, b"png-bytes")

    def test_series_import_rejects_a_missing_story_upload(self):
        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()
            Path("uploads").mkdir()
            denied = self.client.post("/api/v1/series/import-story", json={
                "workspace": "default",
                "story": {
                    "id": "story_missing",
                    "title": "Missing hero",
                    "assets": {
                        "asset_hero": {
                            "id": "asset_hero",
                            "name": "Hero",
                            "source": "/api/v1/uploads/missing.png",
                        }
                    },
                },
            })
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(denied.status_code, 400, denied.text)
        self.assertIn("no longer available", denied.json()["detail"])

    def test_meshy_generate_starts_a_remote_job(self):
        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()
            fake = {"filename": "meshy-test.glb", "path": "meshy-test.glb", "provider": "meshy"}
            with patch("services.meshy_3d_service.generate_model", return_value=fake), patch(
                "services.execution_mode.validate_remote_provider",
            ):
                response = self.client.post("/api/v1/model3d/generate", json={
                    "provider": "meshy", "prompt": "a clay robot", "workspace": "default",
                })
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["provider"], "meshy")

    def test_minimax_music_rejects_local_models(self):
        denied = self.client.post("/api/v1/stories/music-candidates/jobs", json={
            "model": "ace_step_v1_5_xl_sft_lm_4b",
            "prompt": "synthwave",
            "lyrics": "hello",
            "workspace": "default",
        })
        self.assertEqual(denied.status_code, 409)
        self.assertEqual(denied.json()["detail"]["code"], FEATURE_UNAVAILABLE)

    def _clear_music_jobs(self):
        from services import story_music_jobs

        with story_music_jobs._minimax_music_jobs_lock:
            story_music_jobs._minimax_music_jobs.clear()

    def test_minimax_music_reloads_an_interrupted_checkpoint(self):
        job_id = "minimax-music-abc123def456"
        folder, previous = self._in_temp_workspace()
        try:
            checkpoint = Path("outputs") / ".minimax-music-jobs"
            checkpoint.mkdir(parents=True)
            payload = {
                "jobId": job_id,
                "taskId": f"task-{job_id}",
                "workspace": "default",
                "status": "running",
                "phase": "requesting",
                "message": "in progress",
                "children": [{
                    "taskId": f"task-{job_id}-candidate-1",
                    "status": "running",
                    "phase": "requesting",
                }],
            }
            (checkpoint / f"{job_id}.json").write_text(json.dumps(payload), encoding="utf-8")
            loaded = self.client.get(f"/api/v1/stories/music-candidates/jobs/{job_id}")
        finally:
            self._clear_music_jobs()
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(loaded.status_code, 200, loaded.text)
        body = loaded.json()
        self.assertEqual(body["status"], "interrupted")
        self.assertIn("restarted", body["message"])
        self.assertEqual(body["children"][0]["status"], "interrupted")

    def test_minimax_music_reload_skips_a_folder_that_is_not_a_workspace_name(self):
        """An outputs folder with an invalid workspace name must not stop the checkpoint scan."""
        job_id = "minimax-music-0123456789ab"
        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs", "bad name").mkdir(parents=True)
            checkpoint = Path("outputs", "lab", ".minimax-music-jobs")
            checkpoint.mkdir(parents=True)
            payload = {
                "jobId": job_id,
                "taskId": f"task-{job_id}",
                "workspace": "lab",
                "status": "running",
                "phase": "requesting",
                "message": "in progress",
                "children": [],
            }
            (checkpoint / f"{job_id}.json").write_text(json.dumps(payload), encoding="utf-8")
            loaded = self.client.get(f"/api/v1/stories/music-candidates/jobs/{job_id}")
        finally:
            self._clear_music_jobs()
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(loaded.status_code, 200, loaded.text)
        self.assertEqual(loaded.json()["status"], "interrupted")
        self.assertEqual(loaded.json()["workspace"], "lab")

    def test_minimax_music_replay_does_not_start_a_second_worker(self):
        from routers import story_music

        started = []

        class RecordingThread:
            def __init__(self, target=None, args=(), kwargs=None, daemon=None, name=None):
                self.args = args

            def start(self):
                started.append(self.args)

        payload = {
            "model": "music-3.0",
            "prompt": "cinematic dream pop",
            "lyrics": "[Verse]\nAcross the night",
            "count": 1,
            "workspace": "default",
            "paid_music_confirmed": True,
            "idempotencyKey": "same-song-key",
        }
        folder, previous = self._in_temp_workspace()
        try:
            with patch("services.execution_mode.validate_remote_provider"), patch.object(
                story_music.threading, "Thread", RecordingThread,
            ):
                first = self.client.post("/api/v1/stories/music-candidates/jobs", json=payload)
                second = self.client.post("/api/v1/stories/music-candidates/jobs", json=payload)
        finally:
            self._clear_music_jobs()
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(first.status_code, 202, first.text)
        self.assertEqual(second.status_code, 202, second.text)
        self.assertTrue(second.json().get("replay"))
        self.assertEqual(second.json()["jobId"], first.json()["jobId"])
        self.assertEqual(len(started), 1)

    def test_minimax_music_start_publishes_activity(self):
        from routers import story_music

        class QuietThread:
            def __init__(self, target=None, args=(), kwargs=None, daemon=None, name=None):
                return None

            def start(self):
                return None

        payload = {
            "model": "music-3.0",
            "prompt": "cinematic dream pop",
            "lyrics": "[Verse]\nAcross the night",
            "count": 1,
            "workspace": "default",
            "paid_music_confirmed": True,
            "idempotencyKey": "activity-song-key",
        }
        folder, previous = self._in_temp_workspace()
        try:
            with patch("services.execution_mode.validate_remote_provider"), patch.object(
                story_music.threading, "Thread", QuietThread,
            ):
                started = self.client.post("/api/v1/stories/music-candidates/jobs", json=payload)
                listed = self.client.get("/api/v1/tasks", params={"workspace": "default", "status": "all"})
        finally:
            self._clear_music_jobs()
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(started.status_code, 202, started.text)
        self.assertEqual(listed.status_code, 200, listed.text)
        body = started.json()
        tasks = {task["id"]: task for task in listed.json()["tasks"]}
        parent = tasks[body["taskId"]]
        self.assertEqual(parent["provider"], "minimax")
        self.assertEqual(parent["metadata"]["adapter"], "minimax-music")
        child_id = body["children"][0]["taskId"]
        self.assertEqual(tasks[child_id]["metadata"]["adapter"], "minimax-music-candidate")

    def test_minimax_music_null_or_empty_workspace_means_the_active_workspace(self):
        """Core's old music route turned a null or empty workspace into the active one."""
        from routers import story_music
        from services import core_workspace as core

        class QuietThread:
            def __init__(self, target=None, args=(), kwargs=None, daemon=None, name=None):
                return None

            def start(self):
                return None

        for value in (None, ""):
            with self.subTest(workspace=value):
                folder, previous = self._in_temp_workspace()
                try:
                    Path("outputs", "lab").mkdir(parents=True)
                    core.save_config({"services": {"active_workspace": "lab"}})
                    payload = {
                        "model": "music-3.0",
                        "prompt": "cinematic dream pop",
                        "lyrics": "[Verse]\nAcross the night",
                        "count": 1,
                        "workspace": value,
                        "paid_music_confirmed": True,
                        "idempotencyKey": f"active-workspace-{value!r}",
                    }
                    with patch("services.execution_mode.validate_remote_provider"), patch.object(
                        story_music.threading, "Thread", QuietThread,
                    ):
                        started = self.client.post("/api/v1/stories/music-candidates/jobs", json=payload)
                    checkpoint_dir = Path("outputs", "lab", ".minimax-music-jobs")
                    checkpoints = list(checkpoint_dir.glob("*.json")) if checkpoint_dir.is_dir() else []
                finally:
                    self._clear_music_jobs()
                    self._leave_temp_workspace(folder, previous)
                self.assertEqual(started.status_code, 202, started.text)
                self.assertEqual(started.json()["workspace"], "lab")
                self.assertEqual(len(checkpoints), 1)

    def test_minimax_image_generate_starts_a_studio_job(self):
        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()
            fake = {"name": "minimax.jpg", "path": "minimax.jpg", "prompt": "a lantern", "aspect_ratio": "1:1"}
            # The job's worker runs inline, like the other MiniMax image tests: a real daemon thread reads the
            # process cwd (core_workspace.root) while this test removes its temp folder, and a directory it
            # creates in that moment makes the cleanup fail with "Directory not empty".
            with patch("services.core_remote_image.generate_image", return_value=fake), patch(
                "services.execution_mode.validate_remote_provider",
            ), patch("services.core_remote_image.threading.Thread", ImmediateThread):
                response = self.client.post("/api/v1/generate", json={
                    "model_type": "minimax:image-01",
                    "generation_mode": "image",
                    "prompt": "a lantern in the rain",
                    "workspace": "default",
                })
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("job_id", response.json())
        status = self.client.get(f"/api/v1/status/{response.json()['job_id']}")
        self.assertEqual(status.status_code, 200)

    def test_minimax_image_generate_encodes_upload_subject_reference(self):
        captured = {}

        def fake_generate(**kwargs):
            captured.update(kwargs)
            return {"name": "minimax.jpg", "path": "minimax.jpg", "prompt": "a lantern", "aspect_ratio": "1:1"}

        folder, previous = self._in_temp_workspace()
        try:
            Path("uploads").mkdir()
            Path("uploads", "hero.png").write_bytes(b"\x89PNG\r\n\x1a\n")
            Path("outputs").mkdir()
            with patch("services.core_remote_image.generate_image", side_effect=fake_generate), patch(
                "services.execution_mode.validate_remote_provider",
            ), patch("services.core_remote_image.threading.Thread", ImmediateThread):
                response = self.client.post("/api/v1/generate", json={
                    "model_type": "minimax:image-01",
                    "generation_mode": "image",
                    "prompt": "a lantern in the rain",
                    "workspace": "default",
                    "subject_reference": "/api/v1/uploads/hero.png",
                })
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(captured["subject_reference"].startswith("data:image/png;base64,"))

    def _studio_image_command(self, intent="mac-image-intent"):
        return {
            "version": 2,
            "operation": "generation.image",
            "intent_id": intent,
            "input": {
                "workspace": "default",
                "params": {
                    "model_type": "minimax:image-01",
                    "prompt": "a lantern in the rain",
                    "resolution": "1024x1024",
                    "num_inference_steps": 1,
                    "guidance_scale": 1.0,
                    "seed": 1,
                    "generation_mode": "image",
                    "image_mode": 1,
                    "video_length": 1,
                },
            },
        }

    def test_studio_image_command_admits_minimax_and_replays(self):
        from services.studio_image_spec import freeze_studio_image_spec

        command = self._studio_image_command()
        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()
            fake = {"name": "minimax.jpg", "path": "minimax.jpg", "prompt": "a lantern", "aspect_ratio": "1:1"}
            with patch("services.core_remote_image.generate_image", return_value=fake), patch(
                "services.execution_mode.validate_remote_provider",
            ), patch("services.core_remote_image.threading.Thread", ImmediateThread):
                missing = self.client.post("/api/v1/generation/commands", json=[])
                first = self.client.post("/api/v1/generation/commands", json=command)
                replay = self.client.post("/api/v1/generation/commands", json=command)
                changed = dict(command)
                changed["input"] = {**command["input"], "params": {**command["input"]["params"], "prompt": "another"}}
                conflict = self.client.post("/api/v1/generation/commands", json=changed)
                receipt = self.client.get(
                    "/api/v1/generation/commands/receipt",
                    params={"workspace": "default", "intent_id": command["intent_id"]},
                )
                local = self.client.post("/api/v1/generation/commands", json={
                    **self._studio_image_command("local-flux"),
                    "input": {
                        "workspace": "default",
                        "params": {
                            **self._studio_image_command()["input"]["params"],
                            "model_type": "pi_flux2",
                        },
                    },
                })
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(missing.status_code, 422, missing.text)
        self.assertEqual(first.status_code, 200, first.text)
        body = first.json()
        receipt_body = body["receipt"]
        self.assertFalse(body["replayed"])
        self.assertEqual(receipt_body["commandId"], command["intent_id"])
        self.assertEqual(receipt_body["operation"], "generation.image")
        self.assertEqual(receipt_body["status"], "queued")
        self.assertEqual(receipt_body["commandVersion"], 2)
        self.assertEqual(receipt_body["contentFingerprint"], freeze_studio_image_spec(command)["fingerprint"])
        self.assertTrue(receipt_body["result"]["job_id"])
        self.assertEqual(receipt_body["result"]["workspace"], "default")
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertTrue(replay.json()["replayed"])
        self.assertEqual(replay.json()["receipt"]["result"]["job_id"], receipt_body["result"]["job_id"])
        self.assertEqual(conflict.status_code, 409, conflict.text)
        self.assertEqual(conflict.json()["detail"]["code"], "intent_conflict")
        self.assertEqual(receipt.status_code, 200, receipt.text)
        self.assertEqual(receipt.json()["receipt"]["commandId"], command["intent_id"])
        status = self.client.get(f"/api/v1/status/{receipt_body['result']['job_id']}")
        self.assertEqual(status.status_code, 200, status.text)
        self.assertEqual(local.status_code, 409, local.text)
        self.assertEqual(local.json()["detail"]["code"], FEATURE_UNAVAILABLE)

    def test_canonical_tasks_list_minimax_jobs_instead_of_an_empty_stub(self):
        command = self._studio_image_command("mac-task-list")
        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()
            fake = {"name": "minimax.jpg", "path": "minimax.jpg", "prompt": "a lantern", "aspect_ratio": "1:1"}
            with patch("services.core_remote_image.generate_image", return_value=fake), patch(
                "services.execution_mode.validate_remote_provider",
            ), patch("services.core_remote_image.threading.Thread", ImmediateThread):
                admitted = self.client.post("/api/v1/generation/commands", json=command)
                listed = self.client.get("/api/v1/tasks", params={"workspace": "default", "status": "all"})
                task_ids = admitted.json()["receipt"].get("taskIds") or []
                task_id = str(task_ids[0]) if task_ids else ""
                fetched = self.client.get(f"/api/v1/tasks/{task_id}", params={"workspace": "default"})
                cancelled = self.client.post(
                    f"/api/v1/tasks/{task_id}/cancel",
                    params={"workspace": "default"},
                )
                events = self.client.get(
                    f"/api/v1/tasks/{task_id}/events",
                    params={"workspace": "default"},
                )
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(admitted.status_code, 200, admitted.text)
        self.assertTrue(task_id)
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertIn(task_id, {item.get("id") for item in listed.json().get("tasks") or []})
        self.assertNotEqual(listed.json().get("tasks"), [])
        self.assertEqual(fetched.status_code, 200, fetched.text)
        self.assertEqual(fetched.json()["task"]["id"], task_id)
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        self.assertEqual(events.status_code, 200, events.text)

    def test_task_upsert_syncs_past_an_illegal_transition_and_keeps_reservation(self):
        from services.core_generation_commands import registry_for

        folder, previous = self._in_temp_workspace()
        try:
            registry = registry_for("default")
            registry.create(
                id="task-client-core-sync",
                workspace="default",
                status="queued",
                workflow="generate_story_song",
                title="Story song",
                metadata={"generation_id": "gen-1"},
            )
            jumped = self.client.post("/api/v1/tasks/upsert", json={
                "id": "core-sync",
                "workspace": "default",
                "status": "completed",
                "title": "MiniMax Music",
                "phase": "completed",
                "message": "Ready",
            })
            stored = registry.get("task-client-core-sync")
            types = [event["type"] for event in registry.events("task-client-core-sync")]
            reopened = self.client.post("/api/v1/tasks/upsert", json={
                "id": "core-sync",
                "workspace": "default",
                "status": "queued",
                "title": "MiniMax Music",
                "phase": "queued",
                "message": "Waiting again",
            })
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(jumped.status_code, 200, jumped.text)
        self.assertEqual(jumped.json()["status"], "completed")
        self.assertEqual(stored["workflow"], "generate_story_song")
        self.assertEqual(stored["title"], "Story song")
        self.assertEqual(stored["metadata"]["generation_id"], "gen-1")
        self.assertEqual(stored["metadata"]["adapter"], "frontend")
        self.assertIn("adapter.synced", types)
        self.assertEqual(reopened.status_code, 200, reopened.text)
        self.assertEqual(reopened.json()["status"], "completed")
        self.assertEqual(reopened.json()["message"], "Ready")

    def test_system_stats_include_the_runtime_identity(self):
        response = self.client.get("/api/v1/system-stats")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["model"], {"name": None, "model_type": None, "loaded": False})
        self.assertIn("compute_percent", body["gpu"])
        self.assertIn("instance_id", body["runtime"])
        self.assertIn("ui_build_id", body["runtime"])

    def test_startup_binds_before_announcing_and_publishes_the_endpoint(self):
        import io
        import socket
        from contextlib import redirect_stdout

        from services.server_endpoint import withdraw_server_endpoint

        held = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        held.bind(("127.0.0.1", 0))
        busy = held.getsockname()[1]
        if busy in {42003, 42042, 42072} or 42080 <= busy <= 42100:
            held.close()
            self.skipTest("ephemeral port landed on a reserved server port")
        endpoint = Path(core_runtime._app_dir) / "settings" / "server-endpoint.json"
        previous = endpoint.read_text(encoding="utf-8") if endpoint.exists() else None
        seen = {}

        def fake_serve(_app, *, host, port, sockets=None):
            seen["host"] = host
            seen["port"] = port
            seen["sockets"] = list(sockets or [])

        stdout = io.StringIO()
        try:
            with patch.dict(os.environ, {"SERVER_PORT": str(busy), "SERVER_NAME": "127.0.0.1"}, clear=False):
                os.environ.pop("PINOKIO_SHARE_LOCAL", None)
                with patch("services.server_lifecycle.run_until_stopped", fake_serve), redirect_stdout(stdout):
                    core_runtime.run_server()
            self.assertNotEqual(seen.get("port"), busy)
            self.assertTrue(seen.get("sockets"))
            self.assertEqual(seen["host"], "127.0.0.1")
            text = stdout.getvalue()
            self.assertIn(f"http://127.0.0.1:{seen['port']}/", text)
            self.assertNotIn(f"http://127.0.0.1:{busy}/", text)
            record = json.loads(endpoint.read_text(encoding="utf-8"))
            self.assertEqual(record["port"], seen["port"])
            self.assertEqual(record["url"], f"http://127.0.0.1:{seen['port']}")
            # Core has no LanAuthMiddleware, so it must not announce a protected LAN session.
            sharing = {"PINOKIO_SHARE_LOCAL": "true", "LOREFRAME_LAN_TOKEN": "t" * 32}
            with patch.dict(os.environ, sharing), patch("services.server_entry.run") as entry, redirect_stdout(io.StringIO()):
                os.environ.pop("LOREFRAME_LAN_AUTH", None)
                core_runtime.run_server()
            self.assertEqual(entry.call_args.kwargs["lan_messages"], [])
        finally:
            held.close()
            for sock in seen.get("sockets") or []:
                sock.close()
            if previous is None:
                withdraw_server_endpoint(endpoint, os.getpid())
                if endpoint.exists():
                    endpoint.unlink()
            else:
                endpoint.write_text(previous, encoding="utf-8")

    def test_studio_image_command_canonicalizes_upload_references(self):
        folder, previous = self._in_temp_workspace()
        try:
            Path("uploads").mkdir()
            Path("uploads", "hero.png").write_bytes(b"\x89PNG\r\n\x1a\n")
            Path("outputs").mkdir()
            response = self.client.post("/api/v1/generation/commands/references", json={
                "references": [str(Path("uploads", "hero.png").resolve())],
            })
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["references"], ["/api/v1/uploads/hero.png"])

    def test_wizard_image_upscale_executor_starts_minimax_and_blocks_local_upscale(self):
        from services import core_generation_commands

        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()
            fake = {"name": "minimax.jpg", "path": "minimax.jpg", "prompt": "a lantern", "aspect_ratio": "1:1"}
            catalog = self.client.get("/api/v1/wizard/workflows/executor/commands")
            with patch("services.core_remote_image.generate_image", return_value=fake), patch(
                "services.execution_mode.validate_remote_provider",
            ), patch("services.core_remote_image.threading.Thread", ImmediateThread):
                started = self.client.post("/api/v1/wizard/workflows/executor", json={
                    "workspace": "default",
                    "workflowId": "wf-mac-image",
                    "userRequest": "Generate a lantern",
                    "inputSnapshot": {
                        "model_type": "minimax:image-01",
                        "prompt": "a lantern in the rain",
                        "resolution": "1024x1024",
                        "num_inference_steps": 1,
                        "seed": 1,
                        "guidance_scale": 1.0,
                    },
                })
                self.assertEqual(started.status_code, 200, started.text)
                workflow = started.json()["workflow"]
                image_task_id = workflow["steps"][0]["taskId"]
                synced = core_generation_commands.get_task("default", image_task_id)
                ticked = self.client.post(
                    "/api/v1/wizard/workflows/executor/reconcile",
                    json={"workspace": "default"},
                )
                upscale = self.client.post("/api/v1/generation/commands", json={
                    "version": 1,
                    "operation": "tools.upscale",
                    "intent_id": "mac-upscale",
                    "input": {"workspace": "default", "params": {"source": "minimax.jpg"}},
                })
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(catalog.status_code, 200, catalog.text)
        operations = {item.get("name") for item in catalog.json().get("operations") or []}
        self.assertIn("wizard.image_upscale", operations)
        self.assertEqual(workflow["workflowId"], "wf-mac-image")
        self.assertEqual(workflow["steps"][0]["kind"], "generation.image")
        self.assertEqual(workflow["steps"][0]["state"], "waiting")
        self.assertTrue(image_task_id)
        self.assertIsNotNone(synced)
        self.assertEqual(synced["status"], "completed")
        self.assertEqual(synced["result_refs"], ["minimax.jpg"])
        self.assertEqual(ticked.status_code, 200, ticked.text)
        advanced = ticked.json()["results"][0]["workflow"]
        self.assertEqual(advanced["steps"][0]["state"], "completed")
        self.assertEqual(advanced["steps"][0]["outputRefs"], ["minimax.jpg"])
        self.assertEqual(advanced["state"], "awaiting_input")
        self.assertEqual(advanced["steps"][1]["state"], "awaiting_input")
        self.assertEqual(upscale.status_code, 409, upscale.text)
        self.assertEqual(upscale.json()["detail"]["code"], FEATURE_UNAVAILABLE)

    def test_outputs_classify_studio_kinds_and_honor_media_type(self):
        from services.core_workspace import classify_output_type

        self.assertEqual(classify_output_type("2026-09-11_minimax-image-01_abcd1234.jpg"), "image")
        self.assertEqual(classify_output_type("meshy-harbour.glb"), "model3d")
        self.assertEqual(classify_output_type("minimax-music.wav"), "audio")
        self.assertEqual(classify_output_type("harbour-shot.mp4"), "video")
        self.assertEqual(classify_output_type("harbour.world3d.scene.json"), "scene")
        self.assertEqual(classify_output_type("page-01.comic.json"), "comic")
        self.assertIsNone(classify_output_type("harbour.preview.png"))
        self.assertIsNone(classify_output_type("harbour.meta.json"))

        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()
            Path("outputs", "2026-09-11_minimax-image-01_abcd1234.jpg").write_bytes(b"jpg")
            Path("outputs", "meshy-harbour.glb").write_bytes(b"glb")
            Path("outputs", "minimax-music.wav").write_bytes(b"wav")
            Path("outputs", "harbour-shot.mp4").write_bytes(b"mp4")
            Path("outputs", "harbour.world3d.scene.json").write_text("{}", encoding="utf-8")
            Path("outputs", "harbour.preview.png").write_bytes(b"preview")
            Path("outputs", "harbour.meta.json").write_text("{}", encoding="utf-8")
            listed = self.client.get("/api/v1/outputs")
            images = self.client.get("/api/v1/outputs", params={"media_type": "image"})
            models = self.client.get("/api/v1/outputs", params={"media_type": "model3d", "limit": 1})
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(listed.status_code, 200, listed.text)
        by_name = {item["name"]: item for item in listed.json()["outputs"]}
        self.assertEqual(set(by_name), {
            "2026-09-11_minimax-image-01_abcd1234.jpg",
            "meshy-harbour.glb",
            "minimax-music.wav",
            "harbour-shot.mp4",
            "harbour.world3d.scene.json",
        })
        self.assertEqual(by_name["2026-09-11_minimax-image-01_abcd1234.jpg"]["type"], "image")
        self.assertEqual(by_name["meshy-harbour.glb"]["type"], "model3d")
        self.assertEqual(by_name["minimax-music.wav"]["type"], "audio")
        self.assertEqual(by_name["harbour-shot.mp4"]["type"], "video")
        self.assertEqual(by_name["harbour.world3d.scene.json"]["type"], "scene")
        self.assertNotIn("file", {item["type"] for item in listed.json()["outputs"]})
        self.assertEqual([item["name"] for item in images.json()["outputs"]], [
            "2026-09-11_minimax-image-01_abcd1234.jpg",
        ])
        self.assertEqual(images.json()["outputs"][0]["type"], "image")
        self.assertEqual(models.json()["total"], 1)
        self.assertEqual(models.json()["outputs"][0]["type"], "model3d")

    def test_core_outputs_filter_by_search_and_oldest_order(self):
        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()
            older = Path("outputs", "older-blue.png")
            newer = Path("outputs", "newer-red.png")
            older.write_bytes(b"png")
            newer.write_bytes(b"png")
            os.utime(older, (10, 10))
            os.utime(newer, (20, 20))
            searched = self.client.get("/api/v1/outputs", params={"search": "blue"})
            ordered = self.client.get("/api/v1/outputs", params={"order": "oldest"})
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(searched.status_code, 200, searched.text)
        self.assertEqual([item["name"] for item in searched.json()["outputs"]], ["older-blue.png"])
        self.assertEqual(
            [item["name"] for item in ordered.json()["outputs"]],
            ["older-blue.png", "newer-red.png"],
        )

    def test_core_outputs_include_image_dimensions(self):
        from PIL import Image

        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()
            Image.new("RGB", (8, 6), (1, 2, 3)).save(Path("outputs", "card.png"))
            listed = self.client.get("/api/v1/outputs")
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(listed.status_code, 200, listed.text)
        row = listed.json()["outputs"][0]
        self.assertEqual((row.get("width"), row.get("height")), (8, 6))

    def test_a_new_scene_recording_is_listed_at_once_on_core(self):
        """Core lists through the shared 5-second scan cache; a recording has to drop that cache, not another dict."""
        from PIL import Image

        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()
            Image.new("RGB", (4, 4), (1, 2, 3)).save(Path("outputs", "first.png"))
            before = self.client.get("/api/v1/outputs")
            stamp = Path("outputs").stat().st_mtime_ns

            def fake_transcode(src, dest, *, fps, audio_tracks, duration, embedded_audio):
                Path(dest).write_bytes(b"mp4-bytes")

            scene = {"version": 1, "name": "Harbour Shot", "width": 64, "height": 64, "fps": 30, "duration": 2, "layers": []}
            with patch("services.scene_save.transcode_scene_recording", side_effect=fake_transcode), patch(
                "services.scene_save.publish_generation_sidecar",
            ):
                saved = self.client.post(
                    "/api/v1/scenes/recordings",
                    files={"file": ("rec.webm", b"webm", "video/webm")},
                    data={"metadata": json.dumps({"workspace": "default", "scene": scene})},
                )
            # A coarse file-system clock can leave the folder's mtime as it was.
            os.utime("outputs", ns=(stamp, stamp))
            after = self.client.get("/api/v1/outputs")
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual([row["name"] for row in before.json()["outputs"]], ["first.png"])
        self.assertIn(saved.json()["name"], [row["name"] for row in after.json()["outputs"]])

    def test_core_still_serves_the_uploads_view_files(self):
        """The gallery's Uploads view lists ``/api/v1/file/<name>?workspace=__uploads__``; core served it before the share."""
        from PIL import Image

        folder, previous = self._in_temp_workspace()
        try:
            Path("uploads").mkdir()
            Image.new("RGB", (8, 6), (1, 2, 3)).save(Path("uploads", "pick.png"))
            listed = self.client.get("/api/v1/outputs", params={"workspace": "__uploads__"})
            served = self.client.get("/api/v1/file/pick.png", params={"workspace": "__uploads__"})
            missing = self.client.get("/api/v1/file/nope.png", params={"workspace": "__uploads__"})
            expected = Path("uploads", "pick.png").read_bytes()
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(listed.json()["outputs"][0]["url"], "/api/v1/file/pick.png?workspace=__uploads__")
        self.assertEqual(served.status_code, 200, served.text)
        self.assertEqual(served.content, expected)
        self.assertEqual(served.headers["content-type"], "image/png")
        self.assertEqual(missing.status_code, 404, missing.text)

    def test_core_outputs_filter_by_origin_and_result_kind(self):
        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()
            Path("outputs", "harbour_multiclip.mp4").write_bytes(b"mp4")
            Path("outputs", "harbour_multiclip.meta.json").write_text(json.dumps({
                "origin": {"actor": "wizard", "tool": "wizard", "capability": "generation.video"},
                "params": {},
            }), encoding="utf-8")
            Path("outputs", "plain.mp4").write_bytes(b"mp4")
            origin = self.client.get("/api/v1/outputs", params={"origin": "wizard"})
            kind = self.client.get("/api/v1/outputs", params={"result_kind": "chapter"})
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(origin.status_code, 200, origin.text)
        self.assertEqual([item["name"] for item in origin.json()["outputs"]], ["harbour_multiclip.mp4"])
        self.assertEqual(origin.json()["outputs"][0]["origin"]["actor"], "wizard")
        self.assertEqual(kind.status_code, 200, kind.text)
        self.assertEqual([item["name"] for item in kind.json()["outputs"]], ["harbour_multiclip.mp4"])
        self.assertEqual(kind.json()["outputs"][0]["result_kind"], "chapter")

    def test_core_config_save_is_private_and_atomic(self):
        import stat

        folder, previous = self._in_temp_workspace()
        try:
            switched = self.client.put("/api/v1/workspaces/active", json={"name": "saved-lab"})
            settings = Path("app", "settings")
            path = settings / "core_config.json"
            mode = stat.S_IMODE(path.stat().st_mode) if path.is_file() else None
            leftovers = [item.name for item in settings.iterdir() if item.name != "core_config.json"]
            text = path.read_text(encoding="utf-8") if path.is_file() else ""
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(switched.status_code, 200, switched.text)
        self.assertEqual(mode, 0o600)
        self.assertEqual(leftovers, [])
        self.assertIn('"active_workspace": "saved-lab"', text)
        # indent=2: services is one level down, the workspace name two levels down.
        self.assertIn("\n  \"services\"", text)
        self.assertIn("\n    \"active_workspace\"", text)

    def _delete_film_while(self, seed, release):
        """DELETE ``film`` and then ``other`` on the core app while ``seed`` has a job running in ``film``."""
        from services import core_workspace as core

        folder, previous = self._in_temp_workspace()
        try:
            film, other = core.workspace_dir("film"), core.workspace_dir("other")
            Path(film, "keep.png").write_bytes(b"png")
            seed()
            refused = self.client.delete("/api/v1/workspaces/film")
            kept = Path(film, "keep.png").is_file()
            elsewhere = self.client.delete("/api/v1/workspaces/other")
            release()
            deleted = self.client.delete("/api/v1/workspaces/film")
            gone = not Path(film).is_dir()
            other_gone = not Path(other).is_dir()
        finally:
            release()
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(refused.status_code, 409, refused.text)
        self.assertIsInstance(refused.json()["detail"], str)
        self.assertEqual(refused.json()["code"], "workspace_busy")
        self.assertTrue(kept)
        self.assertEqual(elsewhere.status_code, 200, "a job in film must not block deleting another workspace")
        self.assertTrue(other_gone)
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertTrue(gone)
        return refused.json()

    def test_core_refuses_to_delete_a_workspace_while_a_video_editor_export_is_running(self):
        """DELETE is new on core. A queued export still writes into the folder; deleting it
        would wipe the clips and let workspace_dir resurrect an empty workspace."""
        from routers import video_editor

        def seed():
            with video_editor._video_editor_jobs_lock:
                video_editor._video_editor_jobs["export-film"] = {
                    "job_id": "export-film", "workspace": "film", "status": "queued",
                }

        body = self._delete_film_while(seed, video_editor.reset_video_editor_jobs)
        self.assertEqual([item["kind"] for item in body["blocking"]], ["video-editor"])

    def test_core_refuses_to_delete_a_workspace_while_a_3d_job_is_cancelling_or_waiting(self):
        """cancelling still calls the paid provider and may write a GLB; the old jobs() filter only
        treated queued/running as busy, and treated every workspace's job as one."""
        from services import core_remote_3d

        for status in ("cancelling", "waiting_resource", "queued"):
            with self.subTest(status=status):
                body = self._delete_film_while(
                    lambda status=status: core_remote_3d._JOBS.update({
                        "job-3d": {"job_id": "job-3d", "status": status, "workspace": "film"},
                    }),
                    core_remote_3d._JOBS.clear,
                )
                self.assertEqual([item["kind"] for item in body["blocking"]], ["core-3d"])
                self.assertEqual(body["blocking"][0]["status"], status)

    def test_core_refuses_to_delete_a_workspace_while_a_minimax_image_job_runs(self):
        """The old core guard covered this one, but for every workspace at once."""
        body = self._delete_film_while(
            lambda: core_remote_image._JOBS.update({
                "job-img": {
                    "id": "job-img", "status": "running", "workspace": "film", "progress": 0.1, "message": "Generating",
                },
            }),
            core_remote_image._JOBS.clear,
        )
        self.assertEqual([item["kind"] for item in body["blocking"]], ["core-image"])

    def test_core_delete_ignores_jobs_of_other_workspaces_and_finished_jobs(self):
        """A 3D job left queued in ``default`` (what the nested-reference test leaves behind) and finished
        jobs of ``film`` must not keep ``film`` from being deleted."""
        from services import core_remote_3d
        from services import core_workspace as core

        folder, previous = self._in_temp_workspace()
        try:
            core.workspace_dir("film")
            core_remote_3d._JOBS.update({
                "elsewhere": {"job_id": "elsewhere", "status": "queued", "workspace": "default"},
                "done": {"job_id": "done", "status": "completed", "workspace": "film"},
                "failed": {"job_id": "failed", "status": "failed", "workspace": "film"},
            })
            core_remote_image._JOBS["img-done"] = {"id": "img-done", "status": "cancelled", "workspace": "film"}
            deleted = self.client.delete("/api/v1/workspaces/film")
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(deleted.status_code, 200, deleted.text)

    def test_wizard_image_executor_fails_when_minimax_job_fails(self):
        from services import core_generation_commands

        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()
            with patch("services.core_remote_image.generate_image", side_effect=RuntimeError("minimax down")), patch(
                "services.execution_mode.validate_remote_provider",
            ), patch("services.core_remote_image.threading.Thread", ImmediateThread):
                started = self.client.post("/api/v1/wizard/workflows/executor", json={
                    "workspace": "default",
                    "workflowId": "wf-mac-fail",
                    "userRequest": "Generate a lantern",
                    "inputSnapshot": {
                        "model_type": "minimax:image-01",
                        "prompt": "a lantern in the rain",
                        "resolution": "1024x1024",
                        "num_inference_steps": 1,
                        "seed": 1,
                        "guidance_scale": 1.0,
                    },
                })
                self.assertEqual(started.status_code, 200, started.text)
                image_task_id = started.json()["workflow"]["steps"][0]["taskId"]
                synced = core_generation_commands.get_task("default", image_task_id)
                ticked = self.client.post(
                    "/api/v1/wizard/workflows/executor/reconcile",
                    json={"workspace": "default"},
                )
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertIsNotNone(synced)
        self.assertEqual(synced["status"], "failed")
        self.assertEqual(ticked.status_code, 200, ticked.text)
        failed = ticked.json()["results"][0]["workflow"]
        self.assertEqual(failed["state"], "failed")
        self.assertEqual(failed["steps"][0]["state"], "failed")
        self.assertEqual(failed["workflowId"], "wf-mac-fail")

    def test_studio_image_command_encodes_upload_refs_for_minimax(self):
        command = self._studio_image_command("mac-image-ref")
        command["input"]["params"]["image_refs"] = ["/api/v1/uploads/hero.png"]
        captured = {}

        def fake_generate(**kwargs):
            captured.update(kwargs)
            return {"name": "minimax.jpg", "path": "minimax.jpg", "prompt": "a lantern", "aspect_ratio": "1:1"}

        folder, previous = self._in_temp_workspace()
        try:
            Path("uploads").mkdir()
            Path("uploads", "hero.png").write_bytes(b"\x89PNG\r\n\x1a\n")
            Path("outputs").mkdir()
            with patch("services.core_remote_image.generate_image", side_effect=fake_generate), patch(
                "services.execution_mode.validate_remote_provider",
            ), patch("services.core_remote_image.threading.Thread", ImmediateThread):
                response = self.client.post("/api/v1/generation/commands", json=command)
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(captured["subject_reference"].startswith("data:image/png;base64,"))

    def test_studio_image_command_rejects_oversized_prompt_before_admit(self):
        command = self._studio_image_command("mac-image-long")
        command["input"]["params"]["prompt"] = "x" * 10001
        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()
            with patch("services.execution_mode.validate_remote_provider"):
                rejected = self.client.post("/api/v1/generation/commands", json=command)
                command["input"]["params"]["prompt"] = "a lantern in the rain"
                fake = {"name": "minimax.jpg", "path": "minimax.jpg", "prompt": "a lantern", "aspect_ratio": "1:1"}
                with patch("services.core_remote_image.generate_image", return_value=fake), patch(
                    "services.core_remote_image.threading.Thread", ImmediateThread,
                ):
                    accepted = self.client.post("/api/v1/generation/commands", json=command)
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(rejected.status_code, 400, rejected.text)
        self.assertEqual(rejected.json()["detail"]["code"], "invalid_command")
        self.assertEqual(accepted.status_code, 200, accepted.text)
        self.assertFalse(accepted.json()["replayed"])

    def test_studio_image_command_replay_restarts_a_missing_job(self):
        from services import core_remote_image
        command = self._studio_image_command("mac-image-replay")
        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()
            fake = {"name": "minimax.jpg", "path": "minimax.jpg", "prompt": "a lantern", "aspect_ratio": "1:1"}
            with patch("services.core_remote_image.generate_image", return_value=fake), patch(
                "services.execution_mode.validate_remote_provider",
            ), patch("services.core_remote_image.threading.Thread", ImmediateThread):
                first = self.client.post("/api/v1/generation/commands", json=command)
                job_id = first.json()["receipt"]["result"]["job_id"]
                core_remote_image._JOBS.pop(job_id, None)
                replay = self.client.post("/api/v1/generation/commands", json=command)
                status = self.client.get(f"/api/v1/status/{job_id}")
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertTrue(replay.json()["replayed"])
        self.assertEqual(replay.json()["receipt"]["result"]["job_id"], job_id)
        self.assertEqual(status.status_code, 200, status.text)
        self.assertEqual(status.json()["job_id"], job_id)

    def _plan_patches(self, *, generate=None, writing=None, patch_generator=True):
        """Patch the Series plan owner this process actually runs.

        Before the shared router, that owner is ``services.core_series_plan``.
        After it, the same calls land on ``services.series_plan_jobs`` and
        ``routers.series_plan``. One helper covers both so a gain test can
        fail on the old server and pass after the move.
        """
        import importlib
        from contextlib import ExitStack

        stack = ExitStack()
        if writing is None:
            def writing(_request):
                return None
        if patch_generator and generate is None:
            def generate(**_kwargs):
                return {"outline": {"beats": ["The lantern wakes."]}}
        if importlib.util.find_spec("services.core_series_plan") is not None:
            import services.core_series_plan as old

            if patch_generator and hasattr(old, "_generate_json"):
                stack.enter_context(patch.object(old, "_generate_json", side_effect=generate))
            stack.enter_context(patch.object(old, "_writing_override", side_effect=writing))
            stack.enter_context(patch.object(old.threading, "Thread", ImmediateThread))
        if importlib.util.find_spec("services.series_plan_jobs") is not None:
            import services.series_plan_jobs as jobs

            if patch_generator:
                stack.enter_context(patch.object(jobs, "_generate_comic_director_json", side_effect=generate))
            stack.enter_context(patch.object(jobs, "_comic_writing_llm", side_effect=writing))
            stack.enter_context(patch.object(jobs, "_ensure_llm_loaded", return_value=None))
        if importlib.util.find_spec("routers.series_plan") is not None:
            import routers.series_plan as routes

            stack.enter_context(patch.object(routes.threading, "Thread", ImmediateThread))
            stack.enter_context(patch.object(routes, "_comic_writing_llm", side_effect=writing))
        stack.enter_context(patch("services.core_production.ensure_llm_loaded", return_value=None))
        return stack

    def _series_ready_to_plan(self, premises=("A lantern wakes the harbour.",), *, setup=True):
        from services import core_workspace as core
        from services.series_library import create_series_episode, read_series_library, write_series_library

        created = self.client.post("/api/v1/series", json={"workspace": "default", "title": "Harbour Lights"})
        self.assertEqual(created.status_code, 200, created.text)
        project = created.json()
        series_id = project["id"]
        if setup:
            saved = self.client.put(f"/api/v1/series/{series_id}", json={
                "workspace": "default",
                "baseRevision": project["revision"],
                "series": {
                    "premise": "A lantern wakes the harbour every dusk.",
                    "visualStyle": "Wet cobbles, amber lamps",
                },
            })
            self.assertEqual(saved.status_code, 200, saved.text)
        root = core.workspace_dir("default")
        library = read_series_library(root, "default")
        series = library["seriesById"][series_id]
        series["characters"] = [{"id": "character-1", "name": "Mara", "role": "keeper"}]
        series["locations"] = [{"id": "location-1", "name": "Harbour"}]
        episodes = []
        for index, premise in enumerate(premises, start=1):
            episode = create_series_episode(
                series, premise=premise, title=f"Episode {index}",
                logline=f"Logline {index}", outline={"beats": [f"Beat {index}"]},
            )
            series["episodesById"][episode["id"]] = episode
            series["seasons"][0]["episodeOrder"].append(episode["id"])
            episodes.append(episode["id"])
        stored = write_series_library(root, library, "default")
        saved_episodes = [
            stored["seriesById"][series_id]["episodesById"][episode_id] for episode_id in episodes
        ]
        return series_id, saved_episodes

    def _editable_plan_proposal(self, episode_id):
        return {
            "id": episode_id,
            "outline": {"beats": ["Original beat"]},
            "script": [{
                "id": "scene-1", "order": 1, "locationId": "location-1", "time": "day",
                "participatingCharacterIds": ["character-1"], "purpose": "Original purpose",
                "entryState": "Before", "exitState": "After",
                "beats": [{"id": "scene-beat-1", "kind": "action", "summary": "Original action"}],
                "dialogue": [{
                    "id": "dialogue-1", "characterId": "character-1", "text": "Original line",
                    "emotion": "neutral", "delivery": "plain",
                }],
            }],
            "shots": [{
                "id": "shot-1", "sceneId": "scene-1", "order": 1, "durationSeconds": 10,
                "framing": "medium", "camera": "static", "action": "Original shot",
                "dialogueBeats": [{
                    "id": "shot-dialogue-1", "characterId": "character-1", "text": "Original line",
                    "emotion": "neutral", "delivery": "plain",
                }],
                "visibleCharacterIds": ["character-1"], "speakingCharacterIds": ["character-1"],
                "primarySpeakerId": "character-1", "locationId": "location-1",
                "continuityFromShotId": "", "prompt": "Original prompt", "negativePrompt": "",
            }],
            "continuityIssues": [],
            "proposedCanonDelta": {
                "baseRevision": 1, "sourceEpisodeId": episode_id,
                "add": [{
                    "id": "fact-1", "description": "Original fact", "status": "proposed",
                    "decision": "pending",
                }],
                "change": [], "retire": [],
            },
        }

    def _seed_plan_job(self, job):
        from services import core_workspace as core
        from services.series_jobs import SeriesJobStore

        SeriesJobStore(core.workspace_dir(str(job["workspace"])), "planning").save(job)
        try:
            from services.core_series_plan import _JOBS
            _JOBS[job["jobId"]] = job
        except ImportError:
            pass
        try:
            from services.series_plan_jobs import _series_plan_jobs
            _series_plan_jobs[job["jobId"]] = job
        except ImportError:
            pass

    def _stored_plan_job(self, job_id):
        from services import core_workspace as core
        from services.series_jobs import SeriesJobStore

        return SeriesJobStore(core.workspace_dir("default"), "planning").load(job_id)

    def test_series_plan_start_uses_the_remote_llm(self):
        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()
            series_id, episodes = self._series_ready_to_plan()
            with self._plan_patches():
                started = self.client.post(
                    f"/api/v1/series/{series_id}/episodes/{episodes[0]['id']}/plan/start",
                    json={"workspace": "default", "scope": "outline"},
                )
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(started.status_code, 200, started.text)
        self.assertTrue(str(started.json()["jobId"]).startswith("series-plan-"))

    def test_series_known_series_bootstrap_auto_applies(self):
        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()
            created = self.client.post("/api/v1/series", json={"workspace": "default", "title": "Untitled series"})
            self.assertEqual(created.status_code, 200, created.text)
            series_id = created.json()["id"]
            raw = {
                "setup": {
                    "title": "Harbour Lights",
                    "premise": "A lantern wakes the harbour every dusk.",
                    "visualStyle": "Wet cobbles, amber lamps",
                    "format": "episodic",
                    "defaultEpisodeDurationSeconds": 75,
                },
                "canon": {
                    "worldSummary": "A coastal town that bargains with the tide.",
                    "immutableRules": [{"id": "rule_tide", "description": "The lantern must be lit at dusk."}],
                    "currentFacts": [],
                    "forbiddenChanges": [],
                    "themes": ["duty"],
                    "longArcs": [],
                    "timeline": [],
                },
                "characters": [{"id": "mara", "name": "Mara", "role": "keeper"}],
                "locations": [{"id": "harbour", "name": "Harbour"}],
                "relationships": [],
                "props": [],
            }

            def generate(**_kwargs):
                return raw

            with self._plan_patches(generate=generate):
                started = self.client.post(
                    f"/api/v1/series/{series_id}/canon/prepare/start",
                    json={
                        "workspace": "default",
                        "instruction": "Continue Harbour Lights",
                        "bootstrapKnownSeries": True,
                        "autoApply": True,
                    },
                )
            self.assertEqual(started.status_code, 200, started.text)
            job_id = started.json()["jobId"]
            job = self.client.get(f"/api/v1/series/plan/jobs/{job_id}")
            self.assertEqual(job.status_code, 200, job.text)
            body = job.json()
            self.assertEqual(body["status"], "completed")
            self.assertTrue(body["autoApplied"])
            self.assertEqual(body["seriesResult"]["title"], "Harbour Lights")
            self.assertEqual(body["seriesResult"]["canon"]["immutableRules"][0]["description"], "The lantern must be lit at dusk.")
            stored = self.client.get(f"/api/v1/series/{series_id}", params={"workspace": "default"})
            self.assertEqual(stored.status_code, 200, stored.text)
            project = stored.json()
            self.assertEqual(project["title"], "Harbour Lights")
            self.assertEqual(project["characters"][0]["name"], "Mara")
            self.assertEqual(project["characters"][0]["approval"], "draft")
        finally:
            self._leave_temp_workspace(folder, previous)

    def test_a_series_put_with_a_few_fields_keeps_the_rest_of_the_project(self):
        """An agent sent only allowedProductionMethods and the PUT emptied the series' episodes, characters and assets."""
        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()
            created = self.client.post("/api/v1/series", json={"workspace": "default", "title": "Harbour Lights"}).json()
            full = dict(created, characters=[{"id": "mara", "name": "Mara", "role": "keeper"}], locations=[{"id": "harbour", "name": "Harbour"}])
            saved = self.client.put(f"/api/v1/series/{created['id']}", json={"workspace": "default", "series": full,
                                                                              "baseRevision": created["revision"]})
            self.assertEqual(saved.status_code, 200, saved.text)
            current = self.client.get(f"/api/v1/series/{created['id']}", params={"workspace": "default"}).json()
            self.assertEqual(len(current["characters"]), 1)
            partial = self.client.put(f"/api/v1/series/{created['id']}", json={
                "workspace": "default", "series": {"allowedProductionMethods": ["animation_2d", "imported_video"]},
                "baseRevision": current["revision"]})
            self.assertEqual(partial.status_code, 200, partial.text)
            stored = partial.json()
            self.assertEqual(stored["allowedProductionMethods"], ["animation_2d", "imported_video"])
            self.assertEqual([item["id"] for item in stored["characters"]], ["mara"])
            self.assertEqual([item["id"] for item in stored["locations"]], ["harbour"])
            self.assertEqual(stored["episodesById"], current["episodesById"])
            self.assertEqual(stored["title"], "Harbour Lights")
            cleared = self.client.put(f"/api/v1/series/{created['id']}", json={
                "workspace": "default", "series": {"locations": []}, "baseRevision": stored["revision"]}).json()
            self.assertEqual(cleared["locations"], [], "an explicit empty list still clears")
        finally:
            self._leave_temp_workspace(folder, previous)

    def test_series_canon_prepare_normalizes_before_review(self):
        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()
            series_id, _episodes = self._series_ready_to_plan(premises=())
            raw = {
                "canon": {
                    "worldSummary": "A coastal town that bargains with the tide.",
                    "immutableRules": [{"id": "rule_tide", "description": "The lantern must be lit at dusk."}],
                    "forbiddenChanges": ["No daylight lantern"],
                    "themes": ["duty"],
                    "longArcs": [],
                },
                "characters": [{"id": "mara", "name": "Mara"}],
                "locations": [{"id": "harbour", "name": "Harbour"}],
                "relationships": [],
            }

            def generate(**_kwargs):
                return raw

            with self._plan_patches(generate=generate):
                started = self.client.post(
                    f"/api/v1/series/{series_id}/canon/prepare/start",
                    json={"workspace": "default", "instruction": "Tighten the bible"},
                )
            self.assertEqual(started.status_code, 200, started.text)
            job = self.client.get(f"/api/v1/series/plan/jobs/{started.json()['jobId']}")
            self.assertEqual(job.status_code, 200, job.text)
            proposal = job.json()["seriesResult"]
            self.assertEqual(job.json()["status"], "completed")
            self.assertFalse(job.json().get("autoApplied"))
            self.assertEqual(proposal["characters"][0]["approval"], "draft")
            self.assertEqual(proposal["canon"]["immutableRules"][0]["status"], "draft")
            applied = self.client.post(f"/api/v1/series/plan/jobs/{started.json()['jobId']}/apply-canon")
            self.assertEqual(applied.status_code, 200, applied.text)
            self.assertEqual(applied.json()["characters"][0]["name"], "Mara")
        finally:
            self._leave_temp_workspace(folder, previous)

    def test_core_plan_requires_series_setup_before_canon_preparation(self):
        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()
            created = self.client.post("/api/v1/series", json={"workspace": "default", "title": "Harbour Lights"})
            self.assertEqual(created.status_code, 200, created.text)
            with self._plan_patches():
                started = self.client.post(
                    f"/api/v1/series/{created.json()['id']}/canon/prepare/start",
                    json={"workspace": "default", "instruction": "Tighten the bible"},
                )
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(started.status_code, 400, started.text)
        self.assertIn("Complete Series setup before preparing canon", started.text)

    def test_core_plan_repairs_a_stage_that_breaks_a_production_rule(self):
        answers = [
            {"outline": {"beats": []}},
            {"outline": {"beats": ["The lantern wakes."]}},
        ]

        def generate(**_kwargs):
            return answers.pop(0)

        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()
            series_id, episodes = self._series_ready_to_plan()
            with self._plan_patches(generate=generate):
                started = self.client.post(
                    f"/api/v1/series/{series_id}/episodes/{episodes[0]['id']}/plan/start",
                    json={"workspace": "default", "scope": "outline"},
                )
            self.assertEqual(started.status_code, 200, started.text)
            job = self.client.get(f"/api/v1/series/plan/jobs/{started.json()['jobId']}")
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(job.status_code, 200, job.text)
        self.assertEqual(job.json()["status"], "completed", job.text)
        self.assertEqual(job.json()["episodeResult"]["outline"]["beats"], ["The lantern wakes."])
        self.assertEqual(answers, [])

    def test_core_plan_repairs_malformed_json(self):
        def writing(_request):
            return {"model": "deepseek-v4-flash", "base_url": "https://api.deepseek.com", "api_key": "key"}

        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()
            series_id, episodes = self._series_ready_to_plan()
            with self._plan_patches(writing=writing, patch_generator=False), patch(
                "services.llm_service.generate_openai_compatible",
                return_value='{"outline": {"beats": ["The lantern wakes.",]}}',
            ):
                started = self.client.post(
                    f"/api/v1/series/{series_id}/episodes/{episodes[0]['id']}/plan/start",
                    json={"workspace": "default", "scope": "outline"},
                )
            self.assertEqual(started.status_code, 200, started.text)
            job = self.client.get(f"/api/v1/series/plan/jobs/{started.json()['jobId']}")
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(job.json()["status"], "completed", job.text)
        self.assertEqual(job.json()["episodeResult"]["outline"]["beats"], ["The lantern wakes."])

    def test_core_keeps_one_task_registry_per_workspace_folder(self):
        """A second TaskRegistry for the same database re-ran interrupt_unfinished() and flipped the running tasks."""
        from services import core_workspace as core, task_manager
        from services.core_generation_commands import registry_for

        folder, previous = self._in_temp_workspace()
        try:
            registry = registry_for("default")
            registry.create(
                id="running-task", root_id="running-task", workspace="default", kind="series-plan",
                workflow="series", title="Plan", status="running", phase="running",
            )
            shared = task_manager.get_task_registry(core.workspace_dir("default"))
            status = registry.get("running-task")["status"]
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(status, "running")
        self.assertIs(registry, shared)

    def test_core_interrupts_a_dead_process_tasks_once_and_never_its_own(self):
        """Startup recovery stays: the rows a previous process left active are interrupted once, by the first registry
        of the folder. Every later accessor (Activity, Series plan/LLM, music reservation, 3D, remote image, a workspace
        switch) returns that same registry and leaves this process's own tasks alone."""
        from services import core_generation_commands, core_workspace as core, task_manager
        from services.music_submission import submit_music_generation

        orphans = ("orphan-running", "orphan-queued")
        folder, previous = self._in_temp_workspace()
        try:
            workspace_dir = core.workspace_dir("default")
            left_on_disk = task_manager.TaskRegistry(workspace_dir, interrupt_stale=False)  # the dead process's rows
            for task_id, state in zip(orphans, ("running", "queued")):
                left_on_disk.create(id=task_id, root_id=task_id, workspace="default", kind="series-plan",
                                    workflow="series", title=task_id, status=state, phase=state)
            registry = core_generation_commands.registry_for("default")
            recovered = {task_id: registry.get(task_id)["status"] for task_id in orphans}
            registry.create(id="live-plan", root_id="live-plan", workspace="default", kind="series-plan",
                            workflow="series", title="Plan", status="running", phase="running")
            song = submit_music_generation(workspace_dir=workspace_dir, request={
                "prompt": "dream pop", "lyrics": "[Verse]\nLa", "model": "music-3.0", "count": 1,
                "output_folder": "default", "idempotency_key": "recovery-once",
            })
            model = core_canonical_tasks.publish_studio_activity(
                {"task_id": "live-3d", "status": "running", "workspace": "default"}, "model3d",
            )
            touched = [
                self.client.get("/api/v1/tasks", params={"workspace": "default"}).status_code,
                self.client.put("/api/v1/workspaces/active", json={"name": "default"}).status_code,
            ]
            accessors = {
                id(task_manager.get_task_registry(workspace_dir)),  # Series plan LLM calls, assembly, quick video
                id(core_generation_commands._registry("default")),  # remote and MiniMax image commands
                id(core_generation_commands.registry_for("default")),  # Activity, uploads, 3D, music publish
            }
            live = {task_id: registry.get(task_id)["status"] for task_id in ("live-plan", song["task_id"], model["id"])}
            interrupted_events = {
                task_id: [event["type"] for event in registry.events(task_id)].count("task.interrupted")
                for task_id in orphans
            }
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(recovered, {"orphan-running": "interrupted", "orphan-queued": "interrupted"})
        self.assertEqual(interrupted_events, {"orphan-running": 1, "orphan-queued": 1})
        self.assertEqual(live, {"live-plan": "running", song["task_id"]: "queued", "live-3d": "running"})
        self.assertEqual(accessors, {id(registry)})
        self.assertEqual(touched, [200, 200])

    def test_core_plan_reports_the_provider_error_not_a_cancelled_task(self):
        """The first plan job of a workspace used to be cancelled at birth by the registry the LLM call opened."""
        import requests

        def writing(_request):
            return {"model": "local-model", "base_url": "http://127.0.0.1:9", "api_key": ""}

        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()
            series_id, episodes = self._series_ready_to_plan()
            with self._plan_patches(writing=writing, patch_generator=False), patch(
                "services.llm_service._post_with_backoff",
                side_effect=requests.exceptions.ConnectionError("provider down"),
            ):
                started = self.client.post(
                    f"/api/v1/series/{series_id}/episodes/{episodes[0]['id']}/plan/start",
                    json={"workspace": "default", "scope": "outline"},
                )
            self.assertEqual(started.status_code, 200, started.text)
            job = self.client.get(f"/api/v1/series/plan/jobs/{started.json()['jobId']}")
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(job.json()["status"], "failed", job.text)
        self.assertIn("OpenAI-compatible request failed", job.json()["error"])
        self.assertNotIn("cancelled", job.json()["error"])

    def test_recreated_workspace_gets_a_working_task_registry(self):
        """Delete, then create the same name again: the tasks routes must not answer 500 (A5b on core)."""
        folder, previous = self._in_temp_workspace()
        try:
            created = self.client.post("/api/v1/workspaces", json={"name": "again"})
            first_list = self.client.get("/api/v1/tasks", params={"workspace": "again"})
            first_upsert = self.client.post("/api/v1/tasks/upsert", json={
                "id": "a5b-one", "workspace": "again", "status": "queued", "title": "t",
            })
            deleted = self.client.delete("/api/v1/workspaces/again")
            recreated = self.client.post("/api/v1/workspaces", json={"name": "again"})
            second_list = self.client.get("/api/v1/tasks", params={"workspace": "again"})
            second_upsert = self.client.post("/api/v1/tasks/upsert", json={
                "id": "a5b-two", "workspace": "again", "status": "queued", "title": "t",
            })
        finally:
            self._leave_temp_workspace(folder, previous)
        for label, response in (
            ("create", created), ("list", first_list), ("upsert", first_upsert), ("delete", deleted),
            ("recreate", recreated), ("list again", second_list), ("upsert again", second_upsert),
        ):
            self.assertEqual(response.status_code, 200, f"{label}: {response.text}")
        self.assertEqual(second_list.json()["tasks"], [])

    def test_core_plan_streams_the_writing_model(self):
        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()
            series_id, episodes = self._series_ready_to_plan()
            with self._plan_patches(patch_generator=False), patch(
                "services.llm_service.generate", side_effect=AssertionError("blocking generate"),
            ) as blocking, patch(
                "services.llm_service.generate_streaming",
                return_value='{"outline": {"beats": ["The lantern wakes."]}}',
            ) as streaming:
                started = self.client.post(
                    f"/api/v1/series/{series_id}/episodes/{episodes[0]['id']}/plan/start",
                    json={"workspace": "default", "scope": "outline"},
                )
            self.assertEqual(started.status_code, 200, started.text)
            job = self.client.get(f"/api/v1/series/plan/jobs/{started.json()['jobId']}")
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(job.json()["status"], "completed", job.text)
        self.assertEqual(streaming.call_count, 1)
        self.assertEqual(blocking.call_count, 0)

    def test_core_plan_renormalises_a_completed_stage_on_resume(self):
        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()
            series_id, episodes = self._series_ready_to_plan()
            episode = episodes[0]
            job_id = "series-plan-renorm"
            self._seed_plan_job({
                "jobId": job_id, "kind": "planning", "workspace": "default",
                "seriesId": series_id, "episodeId": episode["id"],
                "status": "failed", "stage": "outline", "current": 0, "total": 1,
                "message": "stopped",
                "request": {
                    "scope": "outline", "instruction": "",
                    "writingProvider": "maestro", "writingModel": "", "writingBaseUrl": "",
                    "seriesSnapshot": {"id": series_id, "characters": [], "locations": [], "episodesById": {}},
                    "episodeSnapshot": {"id": episode["id"], "number": episode["number"], "outline": {"beats": []}},
                },
                "sourceSeriesRevision": 1,
                "sourceEpisodeUpdatedAt": episode["updatedAt"],
                "completedStages": {"outline": {"outline": {"beats": ["  The lantern  ", ""]}}},
                "episodeResult": None, "result": None, "error": "stopped",
                "createdAt": 1, "updatedAt": 1,
            })

            def generate(**_kwargs):
                raise AssertionError("a completed stage must be re-normalised, not generated again")

            with self._plan_patches(generate=generate):
                resumed = self.client.post(f"/api/v1/series/plan/jobs/{job_id}/resume", json={})
            self.assertEqual(resumed.status_code, 200, resumed.text)
            job = self.client.get(f"/api/v1/series/plan/jobs/{job_id}")
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(job.status_code, 200, job.text)
        self.assertEqual(job.json()["status"], "completed", job.text)
        self.assertEqual(job.json()["episodeResult"]["outline"]["beats"], ["The lantern"])

    def test_core_plan_sends_prior_episode_summaries(self):
        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()
            series_id, episodes = self._series_ready_to_plan(("The harbour sleeps.", "The lantern wakes."))
            with self._plan_patches():
                started = self.client.post(
                    f"/api/v1/series/{series_id}/episodes/{episodes[1]['id']}/plan/start",
                    json={"workspace": "default", "scope": "outline"},
                )
            self.assertEqual(started.status_code, 200, started.text)
            stored = self._stored_plan_job(started.json()["jobId"])
        finally:
            self._leave_temp_workspace(folder, previous)
        snapshot = (stored.get("request") or {}).get("seriesSnapshot") or {}
        summaries = snapshot.get("priorEpisodeSummaries")
        self.assertEqual([item["id"] for item in summaries], [episodes[0]["id"]])
        self.assertEqual(summaries[0]["outlineBeats"], ["Beat 1"])

    def test_core_plan_cancel_is_not_overwritten_by_a_running_update(self):
        def generate(**_kwargs):
            registries = []
            try:
                from services.core_series_plan import _JOBS
                registries.append(_JOBS)
            except ImportError:
                pass
            try:
                from services.series_plan_jobs import _series_plan_jobs
                registries.append(_series_plan_jobs)
            except ImportError:
                pass
            for jobs in registries:
                for job in jobs.values():
                    if job.get("status") == "running":
                        job["status"] = "cancelling"
            return {"outline": {"beats": ["The lantern wakes."]}}

        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()
            series_id, episodes = self._series_ready_to_plan()
            with self._plan_patches(generate=generate):
                started = self.client.post(
                    f"/api/v1/series/{series_id}/episodes/{episodes[0]['id']}/plan/start",
                    json={"workspace": "default", "scope": "outline"},
                )
            self.assertEqual(started.status_code, 200, started.text)
            job = self.client.get(f"/api/v1/series/plan/jobs/{started.json()['jobId']}")
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(job.json()["status"], "cancelled", job.text)

    def test_core_plan_refuses_a_second_worker(self):
        folder, previous = self._in_temp_workspace()
        calls = []
        try:
            Path("outputs").mkdir()
            series_id, episodes = self._series_ready_to_plan()
            episode = episodes[0]
            job_id = "series-plan-second-worker"
            job = {
                "jobId": job_id, "kind": "planning", "workspace": "default",
                "seriesId": series_id, "episodeId": episode["id"],
                "status": "running", "stage": "outline", "current": 0, "total": 1,
                "message": "Generating Series Lab outline…",
                "request": {
                    "scope": "outline", "instruction": "",
                    "seriesSnapshot": {"characters": [], "locations": []},
                    "episodeSnapshot": {"id": episode["id"], "outline": {"beats": []}},
                },
                "completedStages": {}, "episodeResult": None,
                "createdAt": 1, "updatedAt": 1,
            }
            self._seed_plan_job(job)

            def generate(**_kwargs):
                calls.append("generate")
                return {"outline": {"beats": ["The lantern wakes."]}}

            with self._plan_patches(generate=generate):
                try:
                    from services.core_series_plan import _ACTIVE, _run_episode
                    _ACTIVE.add(job_id)
                    _run_episode(job_id)
                except ImportError:
                    from services import series_plan_jobs
                    series_plan_jobs._series_plan_active_jobs.add(job_id)
                    series_plan_jobs._run_series_plan_job(job_id)
                finally:
                    try:
                        from services.core_series_plan import _ACTIVE
                        _ACTIVE.discard(job_id)
                    except ImportError:
                        from services import series_plan_jobs
                        series_plan_jobs._series_plan_active_jobs.discard(job_id)
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(calls, [])

    def test_core_plan_rejects_an_edited_proposal_that_replaces_ids(self):
        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()
            series_id, episodes = self._series_ready_to_plan()
            episode = episodes[0]
            proposal = self._editable_plan_proposal(episode["id"])
            job_id = "series-plan-edited"
            self._seed_plan_job({
                "jobId": job_id, "kind": "planning", "workspace": "default",
                "seriesId": series_id, "episodeId": episode["id"],
                "status": "completed", "stage": "completed",
                "episodeResult": proposal,
                "sourceEpisodeUpdatedAt": episode["updatedAt"],
                "createdAt": 1, "updatedAt": 1, "message": "ready",
            })
            edited = json.loads(json.dumps(proposal))
            edited["shots"][0]["id"] = "replacement-shot"
            applied = self.client.post(
                f"/api/v1/series/plan/jobs/{job_id}/apply",
                json={"episodeResult": edited},
            )
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(applied.status_code, 400, applied.text)
        self.assertIn("internal IDs", applied.text)

    def test_core_plan_apply_keeps_the_canon_snapshot_and_routes_references(self):
        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()
            series_id, episodes = self._series_ready_to_plan()
            episode = episodes[0]
            proposal = self._editable_plan_proposal(episode["id"])
            proposal["shots"][0].pop("referenceManifest", None)
            job_id = "series-plan-snapshot"
            self._seed_plan_job({
                "jobId": job_id, "kind": "planning", "workspace": "default",
                "seriesId": series_id, "episodeId": episode["id"],
                "status": "completed", "stage": "completed",
                "episodeResult": proposal,
                "sourceEpisodeUpdatedAt": episode["updatedAt"],
                "createdAt": 1, "updatedAt": 1, "message": "ready",
            })
            applied = self.client.post(f"/api/v1/series/plan/jobs/{job_id}/apply", json={})
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(applied.status_code, 200, applied.text)
        saved = applied.json()
        self.assertEqual(saved["canonSnapshot"], episode["canonSnapshot"])
        self.assertEqual(saved["canonRevisionAtCreation"], episode["canonRevisionAtCreation"])
        self.assertIn("referenceManifest", saved["shots"][0])
        self.assertIsInstance(saved["shots"][0]["referenceManifest"], dict)

    def test_core_plan_start_rechecks_the_series_under_the_library_lock(self):
        import copy
        import services.series_library as library_mod

        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()
            series_id, episodes = self._series_ready_to_plan()
            calls = {"n": 0}
            real = library_mod.read_series_library

            def flaky(workspace_dir, workspace_id="default"):
                calls["n"] += 1
                library = real(workspace_dir, workspace_id)
                if calls["n"] >= 2:
                    library = copy.deepcopy(library)
                    library.get("seriesById", {}).pop(series_id, None)
                return library

            targets = ["routers.core_labs.read_series_library"]
            if __import__("importlib").util.find_spec("services.core_series_plan") is not None:
                targets.append("services.core_series_plan.read_series_library")
            with self._plan_patches():
                started = self.client.post(
                    f"/api/v1/series/{series_id}/episodes/{episodes[0]['id']}/plan/start",
                    json={"workspace": "default", "scope": "outline"},
                )
                # The patches above are only the model. Re-issue under the flaky read.
            with self._plan_patches(), patch(targets[0], flaky):
                extra = [patch(target, flaky) for target in targets[1:]]
                for item in extra:
                    item.start()
                try:
                    started = self.client.post(
                        f"/api/v1/series/{series_id}/episodes/{episodes[0]['id']}/plan/start",
                        json={"workspace": "default", "scope": "outline"},
                    )
                finally:
                    for item in extra:
                        item.stop()
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(started.status_code, 404, started.text)
        self.assertGreaterEqual(calls["n"], 2)

    def test_core_plan_publishes_an_activity_task(self):
        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()
            series_id, _episodes = self._series_ready_to_plan(premises=())
            with self._plan_patches():
                started = self.client.post(
                    f"/api/v1/series/{series_id}/canon/prepare/start",
                    json={"workspace": "default", "instruction": "Tighten the bible"},
                )
            self.assertEqual(started.status_code, 200, started.text)
            listed = self.client.get("/api/v1/tasks", params={"workspace": "default", "status": "all"})
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(listed.status_code, 200, listed.text)
        workflows = [item.get("workflow") for item in listed.json()["tasks"]]
        self.assertIn("series-plan", workflows)

    def test_activity_cancel_and_resume_a_queued_series_plan(self):
        """Core Activity lists Series plans; Cancel/Resume must hit the plan job, not MiniMax."""

        class FrozenThread:
            def __init__(self, target=None, args=(), kwargs=None, daemon=None, name=None):
                pass

            def start(self):
                return None

        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()
            series_id, episodes = self._series_ready_to_plan()
            with self._plan_patches(), patch("routers.series_plan.threading.Thread", FrozenThread):
                started = self.client.post(
                    f"/api/v1/series/{series_id}/episodes/{episodes[0]['id']}/plan/start",
                    json={"workspace": "default", "scope": "outline"},
                )
                self.assertEqual(started.status_code, 200, started.text)
                job_id = started.json()["jobId"]
                listed = self.client.get("/api/v1/tasks", params={"workspace": "default", "status": "all"})
                plan = next(
                    task for task in listed.json().get("tasks") or []
                    if task.get("backend_job_id") == job_id
                )
                cancelled = self.client.post(
                    f"/api/v1/tasks/{plan['id']}/cancel",
                    params={"workspace": "default"},
                )
                status = self.client.get(f"/api/v1/series/plan/jobs/{job_id}")
                resumed = self.client.post(
                    f"/api/v1/tasks/{plan['id']}/resume",
                    params={"workspace": "default"},
                )
                after_resume = self.client.get(f"/api/v1/series/plan/jobs/{job_id}")
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertTrue(plan.get("cancelable"), plan)
        self.assertTrue(plan.get("resumable"), plan)
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        self.assertEqual(status.status_code, 200, status.text)
        self.assertEqual(status.json()["status"], "cancelled", status.json())
        self.assertEqual(cancelled.json()["task"]["status"], "cancelled")
        self.assertEqual(resumed.status_code, 200, resumed.text)
        self.assertEqual(after_resume.status_code, 200, after_resume.text)
        self.assertEqual(after_resume.json()["status"], "queued", after_resume.json())

    def test_core_plan_recovery_and_discard_routes(self):
        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()
            job_id = "series-plan-discard-me"
            self._seed_plan_job({
                "jobId": job_id, "kind": "planning", "workspace": "default",
                "seriesId": "series_missing", "episodeId": "",
                "status": "failed", "stage": "failed", "current": 0, "total": 1,
                "message": "stopped", "error": "stopped",
                "createdAt": 1, "updatedAt": 2,
            })
            listed = self.client.get("/api/v1/series/plan/recovery", params={"workspace": "default"})
            self.assertEqual(listed.status_code, 200, listed.text)
            self.assertIn(job_id, [item["jobId"] for item in listed.json()["jobs"]])
            deleted = self.client.delete(f"/api/v1/series/plan/jobs/{job_id}")
            self.assertEqual(deleted.status_code, 200, deleted.text)
            self.assertEqual(deleted.json()["discarded"], True)
            self.assertIsNone(self._stored_plan_job(job_id))
        finally:
            self._leave_temp_workspace(folder, previous)

    def test_core_plan_apply_uses_the_series_library_lock(self):
        import threading
        import time

        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()
            series_id, episodes = self._series_ready_to_plan()
            episode = episodes[0]
            job_id = "series-plan-lock"
            self._seed_plan_job({
                "jobId": job_id, "kind": "planning", "workspace": "default",
                "seriesId": series_id, "episodeId": episode["id"],
                "status": "completed", "stage": "completed",
                "episodeResult": {"id": episode["id"], "title": "Planned while locked", "shots": []},
                "sourceEpisodeUpdatedAt": episode["updatedAt"],
                "createdAt": 1, "updatedAt": 1, "message": "ready",
            })
            from routers import core_labs

            held = threading.Event()
            write_now = threading.Event()
            entered = threading.Event()
            finished = threading.Event()
            result = {}

            def holder():
                with core_labs._LOCK:
                    held.set()
                    if not write_now.wait(5):
                        return
                    library = core_labs._read_series("default")
                    series = library["seriesById"][series_id]
                    series["title"] = "Updated while locked"
                    series["revision"] = int(series.get("revision") or 1) + 1
                    core_labs._write_series("default", library)

            def apply():
                entered.set()
                try:
                    try:
                        from services.core_series_plan import apply_episode
                        result["value"] = apply_episode(job_id, None)
                    except ImportError:
                        from routers.series_plan import apply_series_episode_plan
                        result["value"] = apply_series_episode_plan(job_id, None)
                    result["error"] = None
                except Exception as exc:
                    result["error"] = exc
                finally:
                    finished.set()

            owner = threading.Thread(target=holder)
            applier = threading.Thread(target=apply)
            owner.start()
            self.assertTrue(held.wait(2))
            applier.start()
            self.assertTrue(entered.wait(2))
            time.sleep(0.4)
            blocked = not finished.is_set()
            write_now.set()
            self.assertTrue(finished.wait(5))
            owner.join(5)
            stored = self.client.get(f"/api/v1/series/{series_id}", params={"workspace": "default"})
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertTrue(blocked, "plan apply finished while the other thread still held the library lock")
        self.assertIsNone(result.get("error"), result.get("error"))
        self.assertEqual(stored.status_code, 200, stored.text)
        project = stored.json()
        self.assertEqual(project["title"], "Updated while locked")
        self.assertEqual(project["episodesById"][episode["id"]]["title"], "Planned while locked")
        try:
            from services import series_plan_jobs
            from routers import series_plan
            self.assertIs(series_plan_jobs._series_library_lock, core_labs._LOCK)
            self.assertIs(series_plan._series_library_lock, core_labs._LOCK)
        except ImportError:
            pass


    def test_local_llm_load_is_blocked(self):
        with patch("services.llm_service.load_model") as load:
            blocked = self.client.post("/api/v1/llm/load", json={"provider": "local"})
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(blocked.json()["detail"]["code"], FEATURE_UNAVAILABLE)
        load.assert_not_called()

    @staticmethod
    def _served_core_routes():
        from tests.support.full_server import served_route_table

        return [row for row in served_route_table(api) if row["method"] not in {"MOUNT", "?"}]

    def test_core_defines_each_method_and_path_once(self):
        from collections import Counter

        served = Counter((row["method"], re.sub(r"\{[^}]*\}", "{}", row["path"])) for row in self._served_core_routes())
        self.assertEqual({key: count for key, count in served.items() if count > 1}, {})

    def test_core_series_get_comes_from_the_shared_library_router(self):
        owners = [
            row["source"] for row in self._served_core_routes()
            if row["method"] == "GET" and row["path"] == "/api/v1/series/{series_id}"
        ]
        self.assertEqual(owners, ["app/routers/series_library.py"])

    def test_core_scene_routes_come_from_the_shared_router(self):
        owners = {
            (row["method"], row["path"]): row["source"]
            for row in self._served_core_routes()
            if row["path"] in {"/api/v1/scenes", "/api/v1/scenes/recordings"}
        }
        self.assertEqual(owners, {
            ("POST", "/api/v1/scenes"): "app/routers/scenes_favorites.py",
            ("POST", "/api/v1/scenes/recordings"): "app/routers/scenes_favorites.py",
        })

    def test_core_scene_save_takes_a_json_object_sent_as_json_like_the_full_server(self):
        # The shared route takes ``body: dict`` on both servers. Core used to read
        # the raw body itself, whatever the content type: a list answered 400, a
        # broken body crashed, and JSON sent as text/plain or with no content type
        # was saved. Now all of those are validation errors (422), as on the full
        # server; the UI always sends the JSON content type.
        scene = {"scene": {"version": 1, "name": "Plaza"}}
        folder, previous = self._in_temp_workspace()
        try:
            listed = self.client.post("/api/v1/scenes", json=[1, 2])
            broken = self.client.post(
                "/api/v1/scenes", content=b"{nope", headers={"content-type": "application/json"},
            )
            as_text = self.client.post(
                "/api/v1/scenes", content=json.dumps(scene).encode(), headers={"content-type": "text/plain"},
            )
            untyped = self.client.post("/api/v1/scenes", content=json.dumps(scene).encode())
            saved = self.client.post("/api/v1/scenes", json=scene)
            stored = sorted(path.name for path in Path("outputs").rglob("*.scene.json"))
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(listed.status_code, 422, listed.text)
        self.assertEqual(listed.json()["detail"][0]["loc"], ["body"])
        self.assertEqual(broken.status_code, 422, broken.text)
        self.assertEqual(as_text.status_code, 422, as_text.text)
        self.assertEqual(untyped.status_code, 422, untyped.text)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(stored, [saved.json()["name"]])

    def test_core_scene_recording_without_a_file_is_a_validation_error_like_the_full_server(self):
        folder, previous = self._in_temp_workspace()
        try:
            missing = self.client.post("/api/v1/scenes/recordings", data={"metadata": "{}"})
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(missing.status_code, 422, missing.text)
        self.assertEqual(missing.json()["detail"][0]["loc"], ["body", "file"])

    def test_core_scene_recording_route_keeps_the_workspace_query_and_the_voice_mix(self):
        # Through the shared route, core still adds ?workspace= to both URLs
        # (the full server does not) and still mixes the separate voice track.
        folder, previous = self._in_temp_workspace()
        try:
            seen = []

            def fake_transcode(src, dest, *, fps, audio_tracks, duration, embedded_audio):
                Path(dest).write_bytes(b"mp4-bytes")
                seen.append([dict(item) for item in audio_tracks])

            metadata = json.dumps({
                "workspace": "client-lab",
                "embeddedAudio": False,
                "prompt": "harbour",
                "scene": {"version": 1, "name": "Harbour Shot", "width": 64, "height": 64,
                          "fps": 30, "duration": 2, "layers": []},
            })
            with patch("services.scene_save.transcode_scene_recording", side_effect=fake_transcode), patch(
                "services.scene_save.publish_generation_sidecar",
            ) as sidecar:
                response = self.client.post(
                    "/api/v1/scenes/recordings",
                    files={"file": ("capture.webm", b"silent-webm", "video/webm"),
                           "audio": ("voice.wav", b"voice-wav", "audio/wav")},
                    data={"metadata": metadata},
                )
            mix_path = seen[0][0]["path"] if seen else ""
            mix_left_behind = os.path.isfile(mix_path)
            published = sorted(path.name for path in Path("outputs", "client-lab").glob("*.mp4"))
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(response.status_code, 200, response.text)
        saved = response.json()
        self.assertEqual(saved["url"], f"/api/v1/file/{saved['name']}?workspace=client-lab")
        self.assertTrue(saved["thumbnail_url"].endswith("?workspace=client-lab"), saved["thumbnail_url"])
        self.assertEqual(published, [saved["name"]])
        self.assertEqual(len(seen[0]), 1)
        self.assertIn("scene-audio", mix_path)
        self.assertFalse(mix_left_behind)
        self.assertEqual(sidecar.call_args.kwargs["workspace_id"], "client-lab")

    def test_core_llm_load_uses_the_stored_provider_key_and_routing(self):
        from services import core_workspace as core

        folder, previous = self._in_temp_workspace()
        try:
            core.save_config({"services": {"active_workspace": "default", "openai_api_key": "sk-stored-key"}})
            with patch("services.llm_service.load_model") as load, patch(
                "services.llm_service.get_status", return_value={"loaded": True, "provider": "openai"},
            ):
                response = self.client.post(
                    "/api/v1/llm/load", json={"provider": "openai", "model_id": "gpt-test"},
                )
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(response.status_code, 200, response.text)
        load.assert_called_once()
        self.assertEqual(load.call_args.kwargs["api_key"], "sk-stored-key")
        self.assertEqual(load.call_args.kwargs["provider"], "openai")
        self.assertEqual(load.call_args.kwargs["model_id"], "gpt-test")
        self.assertEqual(load.call_args.kwargs["device"], "cpu")

    def test_plan_h3_windows_is_blocked_whatever_the_body(self):
        with_body = self.client.post(
            "/api/v1/llm/plan-h3-windows", json={"prompt": "Clark turns toward the truck", "model_type": "minimax_h3"},
        )
        without_body = self.client.post("/api/v1/llm/plan-h3-windows")
        self.assertEqual(with_body.status_code, 409, with_body.text)
        self.assertEqual(with_body.json()["detail"]["code"], FEATURE_UNAVAILABLE)
        self.assertEqual((without_body.status_code, without_body.json()), (409, with_body.json()))

    def test_jobs_recovery_does_not_offer_active_jobs_as_crash_leftovers(self):
        active = [{"job_id": "image-live", "status": "running"}]
        with patch("services.core_remote_image.list_active", return_value=active):
            listed = self.client.get("/api/v1/jobs")
            recovery = self.client.get("/api/v1/jobs/recovery")
        self.assertEqual(listed.json()["jobs"], active)
        self.assertEqual(recovery.status_code, 200, recovery.text)
        self.assertEqual(recovery.json(), {"jobs": []})

    def test_scene_recording_muxes_sidecar_audio_and_keeps_unique_names(self):
        from services import scene_save as core_scene_recording

        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()
            Path("outputs", "client-a").mkdir(parents=True)
            source = Path("outputs", "client-a", "capture.webm")
            voice = Path("outputs", "client-a", "mix.wav")
            source.write_bytes(b"webm")
            voice.write_bytes(b"wav")
            seen = []

            def fake_transcode(src, dest, *, fps, audio_tracks, duration, embedded_audio):
                Path(dest).write_bytes(b"mp4-bytes")
                seen.append({
                    "src": src,
                    "dest": dest,
                    "fps": fps,
                    "audio_tracks": list(audio_tracks),
                    "duration": duration,
                    "embedded_audio": embedded_audio,
                })

            scene = {
                "version": 1,
                "name": "Harbour Shot",
                "width": 64,
                "height": 64,
                "fps": 30,
                "duration": 2,
                "layers": [],
            }
            with patch("services.scene_save.transcode_scene_recording", side_effect=fake_transcode), patch(
                "services.scene_save.publish_generation_sidecar",
            ):
                first = core_scene_recording.finalize_scene_recording(
                    source_path=str(source),
                    output_dir=str(Path("outputs", "client-a")),
                    scene=scene,
                    recipe={"engine": "world3d"},
                    prompt="",
                    embedded_audio=False,
                    extra_audio_path=str(voice),
                    workspace="client-a",
                )
                second = core_scene_recording.finalize_scene_recording(
                    source_path=str(source),
                    output_dir=str(Path("outputs", "client-a")),
                    scene=scene,
                    recipe={"engine": "world3d"},
                    prompt="",
                    embedded_audio=False,
                    extra_audio_path=str(voice),
                    workspace="client-a",
                )
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(len(seen), 2)
        self.assertEqual(seen[0]["audio_tracks"][0]["path"], str(voice))
        self.assertFalse(seen[0]["embedded_audio"])
        self.assertNotEqual(first["name"], second["name"])
        self.assertTrue(first["name"].endswith(".mp4"))
        self.assertIn("Harbour-Shot", first["name"])
        self.assertIn("workspace=client-a", first["url"])
        self.assertNotEqual(first["name"], "Harbour Shot.webm")

    def test_scene_recording_keeps_authored_24fps(self):
        from services import scene_save as core_scene_recording

        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()
            source = Path("outputs", "capture.webm")
            source.write_bytes(b"webm")
            seen = []

            def fake_transcode(src, dest, *, fps, audio_tracks, duration, embedded_audio):
                Path(dest).write_bytes(b"mp4-bytes")
                seen.append({"fps": fps, "duration": duration})

            scene = {
                "version": 1,
                "name": "Film Cadence",
                "width": 720,
                "height": 1280,
                "fps": 24,
                "duration": 5,
                "layers": [],
            }
            with patch("services.scene_save.transcode_scene_recording", side_effect=fake_transcode), patch(
                "services.scene_save.publish_generation_sidecar",
            ):
                saved = core_scene_recording.finalize_scene_recording(
                    source_path=str(source),
                    output_dir=str(Path("outputs")),
                    scene=scene,
                    recipe={"engine": "world3d"},
                    prompt="",
                    embedded_audio=True,
                    extra_audio_path=None,
                    workspace="default",
                )
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(seen[0]["fps"], 24)
        self.assertEqual(seen[0]["duration"], 5)
        self.assertTrue(saved["name"].endswith(".mp4"))

    def test_scene_recording_reads_workspace_from_metadata_not_a_form_field(self):
        from services import scene_save as core_scene_recording

        details = core_scene_recording.parse_recording_metadata(json.dumps({
            "workspace": "client-a",
            "embeddedAudio": False,
            "prompt": "",
            "recipe": {"engine": "world3d"},
            "scene": {
                "version": 1,
                "name": "clip-01-world3d-scene",
                "width": 64,
                "height": 64,
                "fps": 30,
                "duration": 1,
                "layers": [],
            },
        }))
        self.assertEqual(details["workspace"], "client-a")
        self.assertEqual(details["scene"]["name"], "clip-01-world3d-scene")
        with self.assertRaises(ValueError):
            core_scene_recording.parse_recording_metadata("{}")

    def test_scene_recording_form_keeps_the_separate_voice_mix(self):
        import asyncio

        from services import scene_save as core_scene_recording

        class ChunkUpload:
            def __init__(self, payload):
                self._payload = payload

            async def read(self, size=-1):
                data, self._payload = self._payload, b""
                return data

            async def close(self):
                return None

        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()
            seen = []

            def fake_transcode(src, dest, *, fps, audio_tracks, duration, embedded_audio):
                Path(dest).write_bytes(b"mp4-bytes")
                seen.append({"audio_tracks": [dict(item) for item in audio_tracks]})

            form = {
                "file": ChunkUpload(b"silent-webm"),
                "audio": ChunkUpload(b"voice-wav"),
                "metadata": json.dumps({
                    "workspace": "default",
                    "embeddedAudio": False,
                    "prompt": "",
                    "recipe": {"engine": "world3d"},
                    "scene": {
                        "version": 1,
                        "name": "Harbour Shot",
                        "width": 64,
                        "height": 64,
                        "fps": 30,
                        "duration": 2,
                        "layers": [],
                    },
                }),
            }
            with patch("services.scene_save.transcode_scene_recording", side_effect=fake_transcode), patch(
                "services.scene_save.publish_generation_sidecar",
            ):
                saved = asyncio.run(core_scene_recording.publish_from_form(form))
            mix_path = seen[0]["audio_tracks"][0]["path"]
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertTrue(saved["name"].endswith(".mp4"))
        self.assertEqual(len(seen[0]["audio_tracks"]), 1)
        self.assertIn("scene-audio", mix_path)
        self.assertFalse(os.path.isfile(mix_path))

    def _recording_form(self, payload=b"silent-webm", *, workspace="default"):
        class ChunkUpload:
            def __init__(self, body):
                self._payload = body
                self.size = len(body)

            async def read(self, size=-1):
                data, self._payload = self._payload, b""
                return data

            async def close(self):
                return None

        return {
            "file": ChunkUpload(payload),
            "metadata": json.dumps({
                "workspace": workspace,
                "embeddedAudio": False,
                "prompt": "",
                "scene": {
                    "version": 1,
                    "name": "Harbour Shot",
                    "width": 64,
                    "height": 64,
                    "fps": 30,
                    "duration": 2,
                    "layers": [],
                },
            }),
        }

    def test_scene_recording_rejects_a_declared_size_before_reading(self):
        import asyncio

        from services.upload_stream import UploadTooLargeError
        from services import scene_save

        class Huge:
            size = 500 * 1024 * 1024 + 1

            def __init__(self):
                self.reads = 0
                self.closed = False

            async def read(self, size=-1):
                self.reads += 1
                return b""

            async def close(self):
                self.closed = True

        upload = Huge()
        form = self._recording_form()
        form["file"] = upload
        with self.assertRaises(UploadTooLargeError):
            asyncio.run(scene_save.publish_from_form(form))
        self.assertEqual(upload.reads, 0)
        self.assertTrue(upload.closed)

    def test_scene_recording_transcode_leaves_the_event_loop_and_uses_two_slots(self):
        import asyncio
        import threading

        from services import scene_save

        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()
            release = threading.Event()
            state = {"current": 0, "peak": 0, "idents": set(), "loop": None}
            lock = threading.Lock()

            def fake_transcode(src, dest, *, fps, audio_tracks, duration, embedded_audio):
                ident = threading.get_ident()
                if ident == state["loop"]:
                    raise AssertionError("transcode ran on the event loop")
                with lock:
                    state["current"] += 1
                    state["peak"] = max(state["peak"], state["current"])
                    state["idents"].add(ident)
                if not release.wait(2):
                    raise AssertionError("transcode was not released")
                with lock:
                    state["current"] -= 1
                Path(dest).write_bytes(b"mp4-bytes")

            async def main():
                state["loop"] = threading.get_ident()
                tasks = [
                    asyncio.create_task(scene_save.publish_from_form(self._recording_form()))
                    for _ in range(3)
                ]
                for _ in range(50):
                    if state["peak"] >= 2:
                        break
                    await asyncio.sleep(0.01)
                self.assertEqual(state["peak"], 2)
                self.assertLessEqual(state["current"], 2)
                release.set()
                await asyncio.gather(*tasks)

            with patch("services.scene_save.transcode_scene_recording", side_effect=fake_transcode), patch(
                "services.scene_save.publish_generation_sidecar",
            ):
                asyncio.run(main())
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(state["peak"], 2)
        self.assertTrue(state["idents"])
        self.assertNotIn(state["loop"], state["idents"])

    def test_scene_recording_drops_its_folder_from_the_scan_cache(self):
        import asyncio

        from services import core_workspace as core
        from services import scene_save

        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()
            out_dir = core.workspace_dir("default")
            scene_save.output_scan_cache[out_dir] = {"stale": True}
            scene_save.output_scan_cache["other"] = {"keep": True}

            def fake_transcode(src, dest, *, fps, audio_tracks, duration, embedded_audio):
                Path(dest).write_bytes(b"mp4-bytes")

            with patch("services.scene_save.transcode_scene_recording", side_effect=fake_transcode), patch(
                "services.scene_save.publish_generation_sidecar",
            ):
                asyncio.run(scene_save.publish_from_form(self._recording_form()))
            self.assertNotIn(out_dir, scene_save.output_scan_cache)
            self.assertEqual(scene_save.output_scan_cache["other"], {"keep": True})
        finally:
            self._leave_temp_workspace(folder, previous)

    def test_recording_url_workspace_query_is_optional(self):
        from services import scene_save

        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()
            source = Path("outputs", "capture.webm")
            source.write_bytes(b"webm")
            scene = {"version": 1, "name": "Harbour Shot", "fps": 30, "duration": 1, "layers": []}

            def fake_transcode(src, dest, *, fps, audio_tracks, duration, embedded_audio):
                Path(dest).write_bytes(b"mp4-bytes")

            with patch("services.scene_save.transcode_scene_recording", side_effect=fake_transcode), patch(
                "services.scene_save.publish_generation_sidecar",
            ):
                hidden = scene_save.finalize_scene_recording(
                    source_path=str(source),
                    output_dir=str(Path("outputs")),
                    scene=scene,
                    recipe=None,
                    prompt="",
                    embedded_audio=False,
                    extra_audio_path=None,
                    workspace="client-a",
                    include_workspace_query=False,
                )
                shown = scene_save.finalize_scene_recording(
                    source_path=str(source),
                    output_dir=str(Path("outputs")),
                    scene=scene,
                    recipe=None,
                    prompt="",
                    embedded_audio=False,
                    extra_audio_path=None,
                    workspace="client-a",
                    include_workspace_query=True,
                )
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertNotIn("workspace=", hidden["url"])
        self.assertNotIn("workspace=", hidden["thumbnail_url"])
        self.assertIn("workspace=client-a", shown["url"])
        self.assertIn("workspace=client-a", shown["thumbnail_url"])

    def _multipart_upload(self, filename: str, payload: bytes, content_type: str = "image/png"):
        boundary = "----CoreUploadBoundary"
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n"
            f"\r\n"
        ).encode("utf-8") + payload + f"\r\n--{boundary}--\r\n".encode("utf-8")
        return self.client.post(
            "/api/v1/upload",
            content=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )

    def test_multipart_upload_keeps_file_bytes_and_unique_names(self):
        png = b"\x89PNG\r\n\x1a\nfirst-clip"
        jpeg = b"\xff\xd8\xffsecond-clip"
        folder, previous = self._in_temp_workspace()
        try:
            first = self._multipart_upload("../shot / take.png", png)
            second = self._multipart_upload("take.jpg", jpeg)
            self.assertEqual(first.status_code, 200, first.text)
            self.assertEqual(second.status_code, 200, second.text)
            first_body = first.json()
            second_body = second.json()
            served = self.client.get(first_body["url"])
            first_bytes = Path(first_body["path"]).read_bytes()
            second_bytes = Path(second_body["path"]).read_bytes()
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertTrue(first_body["filename"].endswith(".png"))
        self.assertTrue(second_body["filename"].endswith(".jpg"))
        self.assertNotEqual(first_body["filename"], second_body["filename"])
        self.assertNotIn("..", first_body["filename"])
        self.assertNotIn("/", first_body["filename"])
        self.assertTrue(first_body["url"].startswith("/api/v1/uploads/"))
        self.assertEqual(first_bytes, png)
        self.assertEqual(second_bytes, jpeg)
        self.assertNotIn(b"Content-Disposition", first_bytes)
        self.assertEqual(served.status_code, 200)
        self.assertEqual(served.content, png)

    def _upload(self, name: str, payload: bytes, content_type: str = "application/octet-stream"):
        return self.client.post("/api/v1/upload", files={"file": (name, payload, content_type)})

    def test_page_and_script_uploads_are_stored_as_bin_and_never_run_as_a_page(self):
        page = b"<script>alert(document.domain)</script>"
        folder, previous = self._in_temp_workspace()
        try:
            for name, content_type in (
                ("evil.html", "text/html"), ("evil.svg", "image/svg+xml"), ("evil.js", "application/javascript"),
            ):
                with self.subTest(name=name):
                    uploaded = self._upload(name, page, content_type)
                    self.assertEqual(uploaded.status_code, 200, uploaded.text)
                    self.assertTrue(uploaded.json()["filename"].endswith(".bin"), uploaded.json())
                    served = self.client.get(uploaded.json()["url"])
                    self.assertEqual(served.status_code, 200)
                    self.assertEqual(served.content, page)
                    self.assertEqual(served.headers["content-type"], "application/octet-stream")
                    self.assertEqual(served.headers["x-content-type-options"], "nosniff")
        finally:
            self._leave_temp_workspace(folder, previous)

    def test_png_upload_is_served_back_with_nosniff(self):
        png = b"\x89PNG\r\n\x1a\nfirst-clip"
        folder, previous = self._in_temp_workspace()
        try:
            uploaded = self._upload("take.PNG", png, "image/png")
            served = self.client.get(uploaded.json()["url"])
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertTrue(uploaded.json()["filename"].endswith(".png"))
        self.assertEqual((served.status_code, served.content), (200, png))
        self.assertEqual(served.headers["content-type"], "image/png")
        self.assertEqual(served.headers["x-content-type-options"], "nosniff")

    def test_upload_over_the_cap_is_refused_and_leaves_nothing(self):
        folder, previous = self._in_temp_workspace()
        try:
            with patch("routers.uploads.MAX_IMAGE_UPLOAD_BYTES", 8):
                refused = self._upload("big.png", b"123456789", "image/png")
                allowed = self._upload("small.png", b"12345678", "image/png")
            left = sorted(os.listdir("uploads"))
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual((refused.status_code, refused.json()["detail"]), (413, "File too large (max 500 MB)"))
        self.assertEqual(allowed.status_code, 200, allowed.text)
        self.assertEqual(left, [allowed.json()["filename"]])

    def test_a_name_outside_uploads_falls_back_to_outputs_and_never_leaves_the_folders(self):
        from services import core_workspace as core

        folder, previous = self._in_temp_workspace()
        try:
            Path(core.workspace_dir("default"), "keyframe.png").write_bytes(b"keyframe pixels")
            Path("secret.txt").write_text("outside the uploads folder", encoding="utf-8")
            fallback = self.client.get("/api/v1/uploads/keyframe.png")
            missing = self.client.get("/api/v1/uploads/never-uploaded.png")
            attempts = [
                self.client.get(f"/api/v1/uploads/{name}")
                for name in ("%2e%2e", "%2e%2e%2fsecret.txt", "..%5C..%5Csecret.txt")
            ]
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual((fallback.status_code, fallback.content), (200, b"keyframe pixels"))
        self.assertEqual(fallback.headers["x-content-type-options"], "nosniff")
        self.assertEqual(missing.status_code, 404)
        for attempt in attempts:
            self.assertEqual(attempt.status_code, 404)
            self.assertNotIn("outside the uploads folder", attempt.text)

    def test_a_multipart_without_a_file_part_is_refused(self):
        folder, previous = self._in_temp_workspace()
        try:
            refused = self.client.post("/api/v1/upload", files={"note": (None, "no file here")})
            nothing_stored = not os.path.isdir("uploads") or os.listdir("uploads") == []
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(refused.status_code, 422)
        self.assertTrue(nothing_stored)

    def test_video_upload_reports_its_frame_rate_duration_and_audio(self):
        from tests.characterization import media

        folder, previous = self._in_temp_workspace()
        try:
            clip = media.video(Path("source") / "clip.mp4")
            with clip.open("rb") as handle:
                uploaded = self._upload("clip.mp4", handle.read(), "video/mp4")
        finally:
            self._leave_temp_workspace(folder, previous)
        body = uploaded.json()
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        self.assertEqual(
            {key: body.get(key) for key in ("fps", "frame_count", "duration_seconds", "has_audio")},
            {"fps": 8.0, "frame_count": 8, "duration_seconds": 1.0, "has_audio": False},
        )

    def test_compressed_audio_upload_is_transcoded_to_wav(self):
        from tests.characterization import media

        folder, previous = self._in_temp_workspace()
        try:
            tone = media.compressed_sound(Path("source") / "tone.aac")
            # The core install has the ffmpeg program but not the ffmpeg-python package.
            with patch.dict("sys.modules", {"ffmpeg": None}):
                uploaded = self._upload("tone.aac", tone.read_bytes(), "audio/aac")
                left = sorted(os.listdir("uploads"))
                served = self.client.get(uploaded.json()["url"])
                broken = self._upload("broken.mp3", b"this is not audio", "audio/mpeg")
                left_after_broken = sorted(os.listdir("uploads"))
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        self.assertTrue(uploaded.json()["filename"].endswith(".wav"))
        self.assertEqual(left, [uploaded.json()["filename"]])
        self.assertEqual(served.content[:4], b"RIFF")
        self.assertEqual(broken.status_code, 400)
        self.assertTrue(broken.json()["detail"].startswith("Failed to decode .mp3 audio:"))
        self.assertEqual(left_after_broken, left)

    def test_both_upload_routes_come_from_the_shared_uploads_router(self):
        owners = {
            (row["method"], row["path"]): row["source"] for row in self._served_core_routes()
            if row["path"] in {"/api/v1/upload", "/api/v1/uploads/{filename}"}
        }
        self.assertEqual(owners, {
            ("POST", "/api/v1/upload"): "app/routers/uploads.py",
            ("GET", "/api/v1/uploads/{filename}"): "app/routers/uploads.py",
        })

    def test_director_plan_prompts_keep_the_validation_answers(self):
        missing_clips = self.client.post("/api/v1/director/plan-prompts", json={})
        self.assertEqual(missing_clips.status_code, 400)
        self.assertEqual(missing_clips.json()["detail"], "clips is required")
        missing_style = self.client.post("/api/v1/director/plan-prompts", json={"clips": [{}]})
        self.assertEqual(missing_style.status_code, 400)
        self.assertEqual(missing_style.json()["detail"], "style_prompt is required")
        missing_angle = self.client.post("/api/v1/director/plan-angle-prompts", json={})
        self.assertEqual(missing_angle.status_code, 400)
        self.assertEqual(missing_angle.json()["detail"], "style_prompt is required")

    def test_director_pipeline_list_marks_a_stale_run_and_keeps_summary_fields(self):
        folder, previous = self._in_temp_workspace()
        try:
            out = Path("outputs")
            out.mkdir()
            payload = {
                "pipeline_id": "pipe-stale",
                "status": "running",
                "phase": "video",
                "comic_id": "issue-1",
                "clips": [],
                "output_files": [],
                "scene_description": "A stale run",
                "resource_schedule": {"lane": "video"},
            }
            (out / "_director_pipeline_pipe-stale.json").write_text(
                json.dumps(payload), encoding="utf-8",
            )
            listed = self.client.get("/api/v1/director/pipelines")
            self.assertEqual(listed.status_code, 200, listed.text)
            rows = listed.json()["pipelines"]
            self.assertEqual(len(rows), 1, listed.text)
            row = rows[0]
            self.assertEqual(row["status"], "crashed")
            self.assertEqual(row["comic_id"], "issue-1")
            self.assertIn("repair_status", row)
            self.assertEqual(row["resource_schedule"], {"lane": "video"})
            self.assertIn("preview_fingerprint", row)
            saved = json.loads((out / "_director_pipeline_pipe-stale.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["status"], "crashed")
        finally:
            self._leave_temp_workspace(folder, previous)

    def test_director_active_pipelines_lists_the_in_memory_run(self):
        from services import director_pipeline

        pipeline_id = "pipe-live"
        with director_pipeline._pipeline_lock:
            previous_pipeline = director_pipeline._pipelines.get(pipeline_id)
            director_pipeline._pipelines[pipeline_id] = {
                "id": pipeline_id,
                "status": "running",
                "phase": "video",
                "workspace": "default",
                "created_at": 10,
                "pipeline_type": "comic",
                "params": {"pipeline_type": "comic"},
                "clip_plans": [],
            }
        folder, previous = self._in_temp_workspace()
        try:
            listed = self.client.get("/api/v1/director/pipelines/active")
            self.assertEqual(listed.status_code, 200, listed.text)
            rows = listed.json()["pipelines"]
            self.assertEqual([row["id"] for row in rows], [pipeline_id])
            self.assertEqual(rows[0]["status"], "running")
            self.assertNotIn("params", rows[0])
        finally:
            with director_pipeline._pipeline_lock:
                if previous_pipeline is None:
                    director_pipeline._pipelines.pop(pipeline_id, None)
                else:
                    director_pipeline._pipelines[pipeline_id] = previous_pipeline
            self._leave_temp_workspace(folder, previous)

    def test_director_saved_pipeline_hydrates_the_queue(self):
        folder, previous = self._in_temp_workspace()
        try:
            out = Path("outputs")
            out.mkdir()
            payload = {
                "pipeline_id": "pipe-queue",
                "status": "completed",
                "clip_plans": [{"image_prompt": "a cat", "video_prompt": "walk"}],
                "planned_clips": [{"shot_id": "shot-1", "duration_sec": 4}],
            }
            (out / "_director_pipeline_pipe-queue.json").write_text(
                json.dumps(payload), encoding="utf-8",
            )
            saved = self.client.get("/api/v1/director/pipelines/pipe-queue")
            self.assertEqual(saved.status_code, 200, saved.text)
            body = saved.json()
            self.assertEqual(body["queue_source"], "clip_plans")
            self.assertEqual(body["clips"][0]["image_prompt"], "a cat")
            self.assertEqual(body["clips"][0]["shot_id"], "shot-1")
        finally:
            self._leave_temp_workspace(folder, previous)

    def test_director_saved_pipeline_missing_uses_the_launch_404(self):
        missing = self.client.get("/api/v1/director/pipelines/missing-pipeline")
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json(), {"error": "Pipeline not found"})

    def test_director_pipeline_status_reports_a_saved_run_with_preview_fields(self):
        folder, previous = self._in_temp_workspace()
        try:
            out = Path("outputs")
            out.mkdir()
            payload = {
                "pipeline_id": "pipe-done",
                "status": "completed",
                "auto_mode": True,
                "clips": [{
                    "image_prompt": "a cat",
                    "video_prompt": "walk",
                    "video_filename": "cat.mp4",
                }],
                "output_files": ["cat.mp4"],
                "params": {"secret": "no"},
            }
            (out / "_director_pipeline_pipe-done.json").write_text(
                json.dumps(payload), encoding="utf-8",
            )
            status = self.client.get("/api/v1/director/pipeline/pipe-done")
            self.assertEqual(status.status_code, 200, status.text)
            body = status.json()
            self.assertTrue(body["recovered_from_disk"])
            self.assertEqual(body["status"], "completed")
            self.assertIn("preview_fingerprint", body)
            self.assertFalse(body["preview_approved"])
            self.assertEqual(body["quality_gate"]["status"], "pending")
            self.assertNotIn("params", body)
            self.assertNotIn("secret", json.dumps(body))
        finally:
            self._leave_temp_workspace(folder, previous)

    def test_director_pipeline_reads_come_from_the_shared_router(self):
        shared = "app/routers/director_pipeline_reads.py"
        paths = {
            "/api/v1/director/plan-prompts",
            "/api/v1/director/plan-angle-prompts",
            "/api/v1/director/pipelines",
            "/api/v1/director/pipelines/active",
            "/api/v1/director/pipelines/{pid}",
            "/api/v1/director/pipeline/{pid}",
        }
        owners = {
            (row["method"], row["path"]): row["source"]
            for row in self._served_core_routes()
            if row["path"] in paths
        }
        self.assertEqual(set(owners), {
            ("POST", "/api/v1/director/plan-prompts"),
            ("POST", "/api/v1/director/plan-angle-prompts"),
            ("GET", "/api/v1/director/pipelines"),
            ("GET", "/api/v1/director/pipelines/active"),
            ("GET", "/api/v1/director/pipelines/{pid}"),
            ("GET", "/api/v1/director/pipeline/{pid}"),
        })
        self.assertEqual(set(owners.values()), {shared})

    def test_core_refuses_series_delete_while_a_job_is_active(self):
        from services.core_workspace import workspace_dir
        from services.series_jobs import SeriesJobStore

        folder, previous = self._in_temp_workspace()
        try:
            series = self.client.post("/api/v1/series", json={"workspace": "default", "title": "Guarded"}).json()
            SeriesJobStore(workspace_dir("default"), "planning").save({
                "jobId": "plan-active",
                "workspace": "default",
                "seriesId": series["id"],
                "episodeId": "",
                "status": "running",
            })
            deleted = self.client.delete(f"/api/v1/series/{series['id']}", params={"workspace": "default"})
            fetched = self.client.get(f"/api/v1/series/{series['id']}", params={"workspace": "default"})
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(deleted.status_code, 409, deleted.text)
        self.assertEqual(deleted.json()["detail"]["code"], "series_jobs_active")
        self.assertEqual(fetched.status_code, 200, fetched.text)

    def test_core_refuses_episode_delete_while_a_job_is_active(self):
        from services.core_workspace import workspace_dir
        from services.series_jobs import SeriesJobStore

        folder, previous = self._in_temp_workspace()
        try:
            series = self.client.post("/api/v1/series", json={"workspace": "default", "title": "Guarded episode"}).json()
            series["canon"]["worldSummary"] = "A world"
            series["characters"] = [{"id": "char_a", "name": "Ada"}]
            series["locations"] = [{"id": "loc_a", "name": "Lab"}]
            path = f"/api/v1/series/{series['id']}"
            saved = self.client.put(path, json={"workspace": "default", "series": series, "baseRevision": series["revision"]})
            series = saved.json()
            approved = self.client.post(path + "/canon/approve", json={"workspace": "default", "baseRevision": series["canon"]["revision"]})
            episode = self.client.post(path + "/episodes", json={"workspace": "default"})
            episode_id = episode.json().get("id")
            SeriesJobStore(workspace_dir("default"), "render").save({
                "jobId": "render-active",
                "workspace": "default",
                "seriesId": series["id"],
                "episodeId": episode_id,
                "status": "queued",
            })
            deleted = self.client.delete(f"{path}/episodes/{episode_id}", params={"workspace": "default"})
            fetched = self.client.get(f"{path}/episodes/{episode_id}", params={"workspace": "default"})
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertEqual(episode.status_code, 200, episode.text)
        self.assertEqual(deleted.status_code, 409, deleted.text)
        self.assertEqual(deleted.json()["detail"]["code"], "series_jobs_active")
        self.assertEqual(fetched.status_code, 200, fetched.text)

    def test_core_lists_an_episode_that_no_season_references(self):
        folder, previous = self._in_temp_workspace()
        try:
            series = self.client.post("/api/v1/series", json={"workspace": "default", "title": "Loose episode"}).json()
            library = self.client.get("/api/v1/series/library", params={"workspace": "default"}).json()
            loose = dict(series)
            loose["episodesById"] = {"ep_orphan": {"id": "ep_orphan", "title": "Loose"}}
            library["seriesById"][series["id"]] = loose
            with patch("services.series_library.normalize_series_library", side_effect=lambda value, workspace_id="default": value):
                saved = self.client.put("/api/v1/series/library", json={"workspace": "default", "library": library})
                listed = self.client.get(f"/api/v1/series/{series['id']}/episodes", params={"workspace": "default"})
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertIn("ep_orphan", [item["id"] for item in listed.json()["episodes"]])

    def test_core_canon_approval_uses_the_launch_guards(self):
        folder, previous = self._in_temp_workspace()
        try:
            series = self.client.post("/api/v1/series", json={"workspace": "default", "title": "Canon guards"}).json()
            path = f"/api/v1/series/{series['id']}/canon/approve"
            stale = self.client.post(path, json={"workspace": "default", "baseRevision": 99})
            missing_world = self.client.post(path, json={"workspace": "default", "baseRevision": series["canon"]["revision"]})
            series["canon"]["worldSummary"] = "A persistent world"
            saved = self.client.put(f"/api/v1/series/{series['id']}", json={"workspace": "default", "series": series, "baseRevision": series["revision"]})
            series = saved.json()
            missing_cast = self.client.post(path, json={"workspace": "default", "baseRevision": series["canon"]["revision"]})
            series["characters"] = [{"id": "char_a", "name": "Ada"}]
            saved = self.client.put(f"/api/v1/series/{series['id']}", json={"workspace": "default", "series": series, "baseRevision": series["revision"]})
            series = saved.json()
            missing_place = self.client.post(path, json={"workspace": "default", "baseRevision": series["canon"]["revision"]})
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(stale.status_code, 409, stale.text)
        self.assertEqual(stale.json()["detail"], "Canon revision changed to 1; reload before approval")
        self.assertEqual(missing_world.status_code, 400, missing_world.text)
        self.assertEqual(missing_world.json()["detail"], "Complete the World summary before approving canon")
        self.assertEqual(missing_cast.status_code, 400, missing_cast.text)
        self.assertEqual(missing_cast.json()["detail"], "Add at least one principal character before approving canon")
        self.assertEqual(missing_place.status_code, 400, missing_place.text)
        self.assertEqual(missing_place.json()["detail"], "Add at least one canonical location before approving canon")

    def test_core_asset_import_uses_the_launch_checks(self):
        folder, previous = self._in_temp_workspace()
        try:
            series = self.client.post("/api/v1/series", json={"workspace": "default", "title": "Import checks"}).json()
            path = f"/api/v1/series/{series['id']}/assets/import"
            Path("uploads").mkdir(exist_ok=True)
            source = Path("uploads/ref.png")
            source.write_bytes(b"png")
            absolute = str(source.resolve())
            long_key = "k" * 120
            imported = self.client.post(path, json={
                "workspace": "default", "uploadPath": absolute, "ownerType": "series", "kind": "nope",
                "referenceRole": "reference",
                "metadata": {"referenceRole": "hijack", "importedAt": "ancient", long_key: "kept", "name": "from-metadata"},
            })
            relative = self.client.post(path, json={
                "workspace": "default", "uploadPath": "ref.png", "ownerType": "series", "kind": "image",
            })
            missing_owner = self.client.post(path, json={
                "workspace": "default", "uploadPath": absolute, "ownerType": "character", "ownerId": "missing",
                "kind": "image",
            })
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(imported.status_code, 200, imported.text)
        asset = imported.json()["asset"]
        self.assertEqual(asset["kind"], "other")
        self.assertEqual(asset["metadata"]["referenceRole"], "reference")
        self.assertNotEqual(asset["metadata"]["importedAt"], "ancient")
        self.assertNotIn(long_key, asset["metadata"])
        self.assertEqual(asset["metadata"]["k" * 100], "kept")
        self.assertEqual(asset["metadata"]["name"], "from-metadata")
        self.assertEqual(relative.status_code, 400, relative.text)
        self.assertIn("HocusPocus Lab uploads", relative.json()["detail"])
        self.assertEqual(missing_owner.status_code, 404, missing_owner.text)
        self.assertEqual(missing_owner.json()["detail"], "Series character not found")

    def test_core_serves_the_cpu_series_routes_the_ui_calls(self):
        folder, previous = self._in_temp_workspace()
        try:
            missing = "/api/v1/series/missing-series"
            commit = self.client.post(missing + "/episodes/ep/canon/commit", json={"workspace": "default"})
            route = self.client.post(missing + "/episodes/ep/references/route", json={"workspace": "default"})
            preview = self.client.post(missing + "/shots/duration/preview", json={"workspace": "default"})
            approve = self.client.post(
                missing + "/episodes/ep/shots/sh/attempts/at/approve", json={"workspace": "default"},
            )
            bulk = self.client.post(missing + "/episodes/ep/attempts/approve-bulk", json={"workspace": "default"})
            reject = self.client.post(
                missing + "/episodes/ep/shots/sh/attempts/at/reject", json={"workspace": "default"},
            )
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(commit.status_code, 400, commit.text)
        self.assertEqual(commit.json()["detail"], "baseRevision is required")
        for response in (route, approve, bulk, reject):
            self.assertEqual(response.status_code, 404, response.text)
            self.assertEqual(response.json()["detail"], "Series Lab project not found")
        self.assertEqual(preview.status_code, 400, preview.text)
        self.assertEqual(preview.json()["detail"], "Series shot is required")


def test_safe_join_copies_use_the_launch_containment_check():
    """A child of ``/`` stays inside ``/``. The prefix copy rejected it."""
    import tempfile

    from services.core_workspace import safe_join as core_safe_join
    from services.kernel.paths import safe_join
    from services.win_safe_files import safe_join_under

    expected = os.path.realpath("/tmp")
    assert safe_join("/", "tmp") == expected
    assert safe_join_under("/", "tmp") == expected
    assert core_safe_join("/", "tmp") == expected
    assert safe_join_under is safe_join
    assert core_safe_join is safe_join
    with tempfile.TemporaryDirectory() as base:
        assert safe_join(base, "..", "secret.txt") is None
        assert safe_join(base, "clip.mp4") == os.path.realpath(os.path.join(base, "clip.mp4"))


if __name__ == "__main__":
    unittest.main()
