"""Pinokio launcher regressions that do not require the application runtime."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest


_ROOT = Path(__file__).resolve().parents[1]


class TestPinokioGpuCompatibility(unittest.TestCase):
    def test_installed_app_menu_is_not_hidden_by_early_gpu_detection(self):
        launcher = (_ROOT / "pinokio.js").read_text(encoding="utf-8")

        self.assertNotIn("if (kernel.gpu", launcher)
        self.assertIn('text: "Start"', launcher)
        self.assertIn('href: "start.js"', launcher)
        self.assertNotIn("Start (Classic UI)", launcher)
        self.assertNotIn("Open Classic UI", launcher)
        self.assertNotIn("Classic Compiled", launcher)
        self.assertNotIn("start_classic.js", launcher)
        self.assertIn('=== "darwin"', launcher)
        self.assertIn("sam_install.js", launcher)

    def test_fresh_install_still_uses_pinokios_documented_gpu_variable(self):
        installer = (_ROOT / "install.js").read_text(encoding="utf-8")

        self.assertIn("...runtime.preflight()", installer)
        from services.runtime_profiles import select_profiles
        rejected = select_profiles("win32", "x64", "amd")
        self.assertFalse(rejected["supported"])
        self.assertIn("NVIDIA", rejected["engines"]["wangp"]["reason"])
        apple = select_profiles("darwin", "arm64", "apple")
        self.assertTrue(apple["supported"])
        self.assertTrue(apple["engines"]["core"]["supported"])
        self.assertFalse(apple["engines"]["wangp"]["supported"])

    def test_start_url_uses_the_required_capture_object(self):
        start = (_ROOT / "start.js").read_text(encoding="utf-8")

        self.assertIn('"event": "/(http:\\/\\/[0-9.:]+)/"', start)
        self.assertIn('url: "{{input.event[1]}}"', start)


class TestInstallWindowsAndUltralyticsPins(unittest.TestCase):
    def test_ultralytics_thop_satisfies_yolo_8_4_142(self):
        requirements = (_ROOT / "app" / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("ultralytics==8.4.142", requirements)
        self.assertIn("ultralytics-thop==2.1.6", requirements)
        self.assertNotIn("ultralytics-thop==2.0.18", requirements)

    def test_install_and_update_share_hunyuan_native_windows_paths(self):
        native = (_ROOT / "hunyuan_native.js").read_text(encoding="utf-8")
        installer = (_ROOT / "install.js").read_text(encoding="utf-8")
        updater = (_ROOT / "update.js").read_text(encoding="utf-8")
        self.assertIn("runtime_setup.js", installer)
        self.assertIn("runtime_setup.js", updater)
        import subprocess
        subprocess.run(["node", "scripts/check_runtime_profiles.cjs"], cwd=_ROOT, check=True)
        self.assertIn("targets/x86_64-linux", native)
        self.assertIn("CUDA_PATH", native)
        self.assertIn("{{platform === 'win32'}}", native)
        self.assertIn("build_mesh_painter.py", native)
        self.assertIn("compile_mesh_painter.sh", native)
        self.assertNotIn("targets/x86_64-linux", installer)
        self.assertNotIn("targets/x86_64-linux", updater)

    def test_mesh_painter_windows_flags_are_msvc_not_unix(self):
        sys.path.insert(0, str(_ROOT / "app" / "services" / "hunyuan3d"))
        from build_mesh_painter import extra_args

        compile_args, _link_args = extra_args("Windows", "win32")
        self.assertIn("/O2", compile_args)
        self.assertNotIn("-fPIC", compile_args)
        linux_compile, _linux_link = extra_args("Linux", "linux")
        self.assertIn("-fPIC", linux_compile)


if __name__ == "__main__":
    unittest.main()
