from __future__ import annotations

import unittest

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from routers.system_capabilities import create_system_capabilities_router, require_capability_http
from services.platform_capabilities import (
    AVAILABLE,
    FEATURE_UNAVAILABLE,
    HIDDEN,
    PROFILE_LINUX_NVIDIA,
    PROFILE_MACOS_ARM64,
    PROFILE_MACOS_INTEL,
    CapabilityDenied,
    build_capabilities,
    require_capability,
)


def _snapshot(system: str, machine: str, **kwargs):
    return build_capabilities(
        system=system,
        machine=machine,
        ffmpeg_present=True,
        rhubarb_present=False,
        **kwargs,
    )


class PlatformCapabilitiesTests(unittest.TestCase):
    def test_linux_keeps_local_nvidia_engines(self):
        snap = _snapshot("linux", "x86_64")
        self.assertEqual(snap["profile"], PROFILE_LINUX_NVIDIA)
        self.assertTrue(snap["accelerators"]["cuda"])
        self.assertTrue(snap["ui"]["show_cuda_controls"])
        self.assertEqual(snap["capabilities"]["wangp_local"]["state"], AVAILABLE)
        self.assertEqual(snap["capabilities"]["minimax_h3_local"]["state"], AVAILABLE)
        self.assertEqual(snap["capabilities"]["hunyuan3d_local"]["state"], AVAILABLE)
        self.assertEqual(snap["capabilities"]["projects"]["state"], AVAILABLE)
        require_capability("wangp_local", snap)

    def test_apple_silicon_hides_cuda_engines_and_keeps_editors(self):
        snap = _snapshot("darwin", "arm64")
        self.assertEqual(snap["profile"], PROFILE_MACOS_ARM64)
        self.assertFalse(snap["accelerators"]["cuda"])
        self.assertTrue(snap["accelerators"]["mps"])
        self.assertFalse(snap["ui"]["show_cuda_controls"])
        self.assertEqual(snap["ui"]["mode"], "macosCoreRemote")
        self.assertEqual(snap["capabilities"]["editors"]["state"], AVAILABLE)
        self.assertEqual(snap["capabilities"]["video3d"]["state"], AVAILABLE)
        self.assertEqual(snap["capabilities"]["remote_llm"]["state"], AVAILABLE)
        self.assertEqual(snap["capabilities"]["wangp_local"]["state"], HIDDEN)
        self.assertEqual(snap["capabilities"]["wangp_local"]["alternative"], "remote_image")
        self.assertEqual(snap["capabilities"]["rhubarb"]["state"], "disabled")
        with self.assertRaises(CapabilityDenied) as raised:
            require_capability("wangp_local", snap)
        detail = raised.exception.as_detail()
        self.assertEqual(detail["code"], FEATURE_UNAVAILABLE)
        self.assertEqual(detail["capability"], "wangp_local")
        self.assertEqual(detail["state"], HIDDEN)

    def test_intel_mac_is_an_explicit_unsupported_profile(self):
        snap = _snapshot("darwin", "x86_64")
        self.assertEqual(snap["profile"], PROFILE_MACOS_INTEL)
        self.assertEqual(snap["ui"]["mode"], "macosIntel")
        self.assertEqual(snap["capabilities"]["minimax_h3_local"]["state"], HIDDEN)

    def test_core_runtime_on_linux_or_windows_reports_core_remote(self):
        from unittest.mock import patch
        from services.platform_capabilities import CORE_RUNTIME_ENV, PROFILE_CORE_REMOTE, platform_capabilities
        for system in ("linux", "windows"):
            with patch("services.platform_capabilities.host_platform", return_value=system), \
                    patch.dict("os.environ", {CORE_RUNTIME_ENV: "core"}):
                snap = platform_capabilities(ffmpeg_present=True, rhubarb_present=False)
            self.assertEqual(snap["profile"], PROFILE_CORE_REMOTE)
            self.assertEqual(snap["ui"]["mode"], "coreRemote")
            self.assertFalse(snap["ui"]["show_cuda_controls"])
            self.assertEqual(snap["capabilities"]["wangp_local"]["state"], HIDDEN)
            self.assertEqual(snap["capabilities"]["wangp_local"]["reason_code"], "requires_nvidia")
            self.assertEqual(snap["capabilities"]["editors"]["state"], AVAILABLE)

    def test_launch_boots_core_only_when_install_chose_it(self):
        import tempfile
        from pathlib import Path
        import launch
        with tempfile.TemporaryDirectory() as folder:
            markers = Path(folder) / ".runtime"
            self.assertFalse(launch._core_installed(folder), "legacy installs keep the full runtime")
            markers.mkdir()
            (markers / "core.managed").write_text("x")
            self.assertTrue(launch._core_installed(folder))
            (markers / "wangp.managed").write_text("x")
            self.assertFalse(launch._core_installed(folder))

    def test_http_surface_and_409_guard(self):
        app = FastAPI()
        app.include_router(create_system_capabilities_router())

        @app.post("/probe")
        def probe():
            require_capability_http("wangp_local")
            return {"ok": True}

        client = TestClient(app)
        listed = client.get("/api/v1/system/capabilities")
        self.assertEqual(listed.status_code, 200)
        self.assertIn("capabilities", listed.json())
        self.assertIn("profile", listed.json())

        denied = HTTPException(status_code=409, detail={"code": FEATURE_UNAVAILABLE})
        try:
            require_capability_http("missing-engine")
        except HTTPException as error:
            denied = error
        self.assertEqual(denied.status_code, 409)
        self.assertEqual(denied.detail["code"], FEATURE_UNAVAILABLE)


if __name__ == "__main__":
    unittest.main()
