from __future__ import annotations

import base64
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import core_runtime
from core_runtime import api
from services import core_upload
from services.platform_capabilities import FEATURE_UNAVAILABLE
from services.scene_commands import SceneCommands
from services import core_remote_image
from services.core_remote_image import catalog_entry


class ImmediateThread:
    def __init__(self, target=None, args=(), kwargs=None, daemon=None, name=None):
        self._target = target
        self._args = args

    def start(self):
        self._target(*self._args)


class CoreRuntimeTests(unittest.TestCase):
    def setUp(self):
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

    def _in_temp_workspace(self):
        folder = tempfile.TemporaryDirectory()
        previous = os.getcwd()
        os.chdir(folder.name)
        return folder, previous

    def _leave_temp_workspace(self, folder, previous):
        os.chdir(previous)
        folder.cleanup()

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
        self.assertEqual(self.client.post("/api/v1/rig/generate").status_code, 409)
        mcp = self.client.post("/api/v1/wangp/mcp", json={"params": {"name": "generate"}})
        self.assertEqual(mcp.status_code, 503)
        self.assertEqual(self.client.post("/api/v1/tools/remove-background").status_code, 409)
        missing = self.client.post("/api/v1/video-editor/probe", json={"source": "missing.mp4"})
        self.assertEqual(missing.status_code, 400)

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
            Path('uploads/portrait.png').write_bytes(b'reference fixture')
            imported = self.client.post(path + '/assets/import', json={'workspace':'default', 'uploadPath':'portrait.png',
                'ownerType':'character', 'ownerId':'char_a', 'kind':'character', 'referenceRole':'primary_portrait',
                'metadata':{'prompt':'Ada in a paper cutout style', 'jobId':'image-job'}})
            self.assertEqual(imported.status_code, 200, imported.text)
            result = imported.json()
            self.assertEqual(result['series']['characters'][0]['referenceAssetIds'], [result['asset']['id']])
            self.assertEqual(result['asset']['metadata']['jobId'], 'image-job')
            self.assertEqual(result['series']['canon']['approval'], 'draft')
            retry = self.client.post(path + '/assets/import', json={'workspace':'default', 'uploadPath':'portrait.png',
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

    def test_video_editor_export_name_cannot_escape_the_workspace(self):
        from services import core_editor, core_workspace as core

        folder, previous = self._in_temp_workspace()
        try:
            workspace = core.workspace_dir("default")
            with patch.object(core_editor, "resolve_media", return_value=os.path.join(workspace, "clip.mp4")), \
                 patch.object(core_editor, "render_project", return_value={"duration": 1}):
                Path(workspace, "clip.mp4").write_bytes(b"x")
                job = core_editor.start_export({
                    "clips": [{"source": "clip.mp4"}],
                    "name": "../etc/passwd / cut",
                    "workspace": "default",
                })
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertNotIn("..", job["filename"])
        self.assertNotIn("/", job["filename"])
        self.assertTrue(job["filename"].endswith("_etc_passwd_cut.mp4"))

    def test_video_editor_screenshot_keeps_each_character_sheet_frame(self):
        from services import core_editor, core_workspace as core

        def fake_extract(source, dest, time_seconds):
            Path(dest).write_bytes(f"frame-{time_seconds}".encode())
            return {"time": time_seconds, "width": 8, "height": 8}

        folder, previous = self._in_temp_workspace()
        try:
            workspace = core.workspace_dir("default")
            Path(workspace, "orbit.mp4").write_bytes(b"clip")
            with patch.object(core_editor, "time") as frozen, patch.object(
                core_editor, "extract_frame", side_effect=fake_extract,
            ):
                frozen.strftime.return_value = "2026-09-11-13h55m00s"
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
        from services import core_editor, core_workspace as core

        def fake_render(clips, destination, **_kwargs):
            Path(destination).write_bytes(f"export-{len(clips)}".encode())
            return {"duration": 1}

        folder, previous = self._in_temp_workspace()
        try:
            workspace = core.workspace_dir("default")
            Path(workspace, "clip.mp4").write_bytes(b"clip")
            with patch.object(core_editor, "time") as frozen, patch(
                "services.core_editor.threading.Thread", ImmediateThread,
            ), patch.object(core_editor, "render_project", side_effect=fake_render):
                frozen.strftime.return_value = "2026-09-11-13h55m00s"
                first = core_editor.start_export({
                    "clips": [{"source": "clip.mp4"}],
                    "name": "Harbour cut",
                    "workspace": "default",
                })
                second = core_editor.start_export({
                    "clips": [{"source": "clip.mp4"}, {"source": "clip.mp4"}],
                    "name": "Harbour cut",
                    "workspace": "default",
                })
                first_bytes = Path(workspace, first["filename"]).read_bytes()
                second_bytes = Path(workspace, second["filename"]).read_bytes()
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertEqual(first["filename"], "2026-09-11-13h55m00s_Harbour_cut.mp4")
        self.assertEqual(second["filename"], "2026-09-11-13h55m00s_Harbour_cut_2.mp4")
        self.assertEqual(first_bytes, b"export-1")
        self.assertEqual(second_bytes, b"export-2")

    def test_production_profile_defaults_to_remote_providers(self):
        listed = self.client.get("/api/v1/production-profile")
        self.assertEqual(listed.status_code, 200)
        profile = listed.json()["profile"]
        self.assertEqual(profile["text"]["provider"], "minimax")
        self.assertEqual(profile["image"]["provider"], "minimax")
        self.assertEqual(profile["music"]["provider"], "minimax")
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

    def test_series_assembly_joins_approved_clips_on_the_core_profile(self):
        from services.series_library import (
            create_series_project,
            empty_series_library,
            write_series_library,
        )

        def concatenate(paths, output_path, **_kwargs):
            Path(output_path).write_bytes(b"".join(Path(path).read_bytes() for path in paths))
            return True

        folder, previous = self._in_temp_workspace()
        try:
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

    def test_minimax_image_generate_starts_a_studio_job(self):
        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()
            fake = {"name": "minimax.jpg", "path": "minimax.jpg", "prompt": "a lantern", "aspect_ratio": "1:1"}
            with patch("services.core_remote_image.generate_image", return_value=fake), patch(
                "services.execution_mode.validate_remote_provider",
            ):
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

    def test_series_plan_start_uses_the_remote_llm(self):
        series = {
            "id": "series_mac", "revision": 1, "provider": {},
            "episodesById": {"ep1": {"id": "ep1", "premise": "A lantern wakes the harbour.", "updatedAt": "t"}},
        }
        library = {"seriesById": {"series_mac": series}}

        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()
            with patch("services.core_series_plan._series_or_404", return_value=(series, library)), patch(
                "services.core_series_plan._generate_json", return_value={"outline": {"beats": ["The lantern wakes."]}},
            ), patch("services.core_series_plan._writing_override", return_value=None), patch(
                "services.core_series_plan.threading.Thread", ImmediateThread,
            ):
                started = self.client.post(
                    "/api/v1/series/series_mac/episodes/ep1/plan/start",
                    json={"workspace": "default", "scope": "outline"},
                )
        finally:
            os.chdir(previous)
            folder.cleanup()
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
            with patch("services.core_series_plan._generate_json", return_value=raw), patch(
                "services.core_series_plan._writing_override", return_value=None,
            ), patch("services.core_series_plan.threading.Thread", ImmediateThread):
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

    def test_series_canon_prepare_normalizes_before_review(self):
        folder, previous = self._in_temp_workspace()
        try:
            Path("outputs").mkdir()
            created = self.client.post("/api/v1/series", json={
                "workspace": "default",
                "title": "Harbour Lights",
            })
            self.assertEqual(created.status_code, 200, created.text)
            series_id = created.json()["id"]
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
            with patch("services.core_series_plan._generate_json", return_value=raw), patch(
                "services.core_series_plan._writing_override", return_value=None,
            ), patch("services.core_series_plan.threading.Thread", ImmediateThread):
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

    def test_local_llm_load_is_blocked(self):
        blocked = self.client.post("/api/v1/llm/load", json={"provider": "local"})
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(blocked.json()["detail"]["code"], FEATURE_UNAVAILABLE)

    def test_scene_recording_muxes_sidecar_audio_and_keeps_unique_names(self):
        from services import core_scene_recording

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
            with patch("services.core_scene_recording.transcode_scene_recording", side_effect=fake_transcode), patch(
                "services.core_scene_recording.publish_generation_sidecar",
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

    def test_scene_recording_reads_workspace_from_metadata_not_a_form_field(self):
        from services import core_scene_recording

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

        from services import core_scene_recording

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
            with patch("services.core_scene_recording.transcode_scene_recording", side_effect=fake_transcode), patch(
                "services.core_scene_recording.publish_generation_sidecar",
            ):
                saved = asyncio.run(core_scene_recording.publish_from_form(form))
            mix_path = seen[0]["audio_tracks"][0]["path"]
        finally:
            self._leave_temp_workspace(folder, previous)
        self.assertTrue(saved["name"].endswith(".mp4"))
        self.assertEqual(len(seen[0]["audio_tracks"]), 1)
        self.assertIn("scene-audio", mix_path)
        self.assertFalse(os.path.isfile(mix_path))

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

    def test_extract_upload_prefers_file_part_and_rejects_empty_multipart(self):
        extra = (
            b"------Part\r\n"
            b'Content-Disposition: form-data; name="note"\r\n\r\n'
            b"ignore\r\n"
            b"------Part\r\n"
            b'Content-Disposition: form-data; name="file"; filename="hero.png"\r\n'
            b"Content-Type: image/png\r\n\r\n"
            b"PIXELS\r\n"
            b"------Part--\r\n"
        )
        data, name = core_upload.extract_upload(extra, "multipart/form-data; boundary=----Part")
        self.assertEqual(name, "hero.png")
        self.assertEqual(data, b"PIXELS")
        with self.assertRaises(ValueError):
            core_upload.extract_upload(
                b"------Part\r\nContent-Disposition: form-data; name=\"note\"\r\n\r\nx\r\n------Part--\r\n",
                "multipart/form-data; boundary=----Part",
            )


if __name__ == "__main__":
    unittest.main()
