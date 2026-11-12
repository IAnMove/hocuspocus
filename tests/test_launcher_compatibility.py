"""Pinokio launcher regressions that do not require the application runtime."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
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
        # The optional installers are generated from the catalog, not listed by hand.
        self.assertIn("components.menuItems(info, 'nvidia')", launcher)
        catalog = (_ROOT / "app" / "runtime" / "install_catalog.json").read_text(encoding="utf-8")
        self.assertIn("sam_install.js", catalog)

    def test_fresh_install_still_uses_pinokios_documented_gpu_variable(self):
        installer = (_ROOT / "install.js").read_text(encoding="utf-8")

        self.assertIn("...runtime.preflight()", installer)
        from services.runtime_profiles import select_profiles
        amd = select_profiles("win32", "x64", "amd")
        self.assertTrue(amd["supported"])
        self.assertTrue(amd["engines"]["core"]["supported"])
        self.assertFalse(amd["engines"]["wangp"]["supported"])
        self.assertIn("NVIDIA", amd["engines"]["wangp"]["reason"])
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


class TestUnfinishedFirstInstall(unittest.TestCase):
    """A first install that stopped leaves app/env behind: the menu offers Install, not Start."""

    def _node(self, script: str, present: tuple[str, ...] = ()):
        done = subprocess.run(["node", "-e", script], cwd=_ROOT, check=True, capture_output=True, text=True,
                              env={**os.environ, "PRESENT": ",".join(present)})
        return json.loads(done.stdout.strip().splitlines()[-1])

    def _menu_texts(self, present: tuple[str, ...]) -> list[str]:
        return self._node(
            "const launcher = require('./pinokio.js');"
            "const have = new Set((process.env.PRESENT || '').split(',').filter(Boolean));"
            "const info = {exists: p => have.has(p), running: () => false, local: () => ({})};"
            "launcher.menu({platform: 'linux', arch: 'x64', gpu: 'nvidia'}, info)"
            ".then(items => console.log(JSON.stringify(items.map(item => item.text))));",
            present)

    def test_the_menu_offers_install_until_a_first_install_finishes(self):
        self.assertEqual(self._menu_texts(()), ["Install"])
        self.assertEqual(self._menu_texts(("app/env", "app/.install.incomplete")), ["Install"])
        installed = self._menu_texts(("app/env",))
        self.assertEqual(installed[:2], ["Start", "Update"])
        self.assertNotIn("Install", installed)

    def test_install_marks_only_a_first_install_and_clears_it_after_the_setup(self):
        steps = self._node("console.log(JSON.stringify(require('./install.js').run.map("
                           "s => [s.method, s.when || '', (s.params && (s.params.path || s.params.uri)) || ''])))")
        marker = "app/.install.incomplete"
        write = steps.index(["fs.write", "{{!exists('app/env')}}", marker])
        setup = steps.index(["script.start", "", "runtime_setup.js"])
        clear = steps.index(["fs.rm", "{{exists('app/.install.incomplete')}}", marker])
        self.assertLess(write, setup)
        self.assertLess(setup, clear)
        # runtime.call stops the script when the setup did not succeed, before the marker is cleared.
        self.assertEqual(steps[setup + 1][0], "notify")
        self.assertEqual(clear, setup + 2)


if __name__ == "__main__":
    unittest.main()
