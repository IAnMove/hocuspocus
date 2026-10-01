"""A profile that was never saved starts on local Qwen Image 2.1 when it is installed, and only then."""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "app"))

from services import production_profile_defaults as defaults  # noqa: E402

STATIC = {"version": 1, "image": {"provider": "minimax", "model": "image-01"}, "music": {"provider": "local", "model": "ace"}}


class ProductionProfileDefaultsTests(unittest.TestCase):
    def setUp(self):
        defaults.reset_cache()

    def test_installed_qwen_becomes_the_default_image_model_without_touching_the_rest(self):
        profile = defaults.default_profile(STATIC, lambda model: model == "qwen_image_21")
        self.assertEqual(profile["image"], {"provider": "local", "model": "qwen_image_21"})
        self.assertEqual(profile["music"], STATIC["music"])
        self.assertEqual(STATIC["image"], {"provider": "minimax", "model": "image-01"})   # the static default is never mutated

    def test_without_the_weights_the_static_default_stays(self):
        self.assertEqual(defaults.default_profile(STATIC, lambda model: False), STATIC)

    def test_a_probe_that_fails_is_treated_as_not_installed(self):
        def broken(model):
            raise RuntimeError("model definitions not loaded")
        self.assertEqual(defaults.default_profile(STATIC, broken), STATIC)

    def test_the_installed_check_is_cached_for_a_short_time(self):
        calls = []
        def probe(model):
            calls.append(model)
            return True
        clock = [100.0]
        for _ in range(3):
            defaults.default_profile(STATIC, probe, now=lambda: clock[0])
        self.assertEqual(calls, ["qwen_image_21"])
        clock[0] += defaults._TTL_S + 1
        defaults.default_profile(STATIC, probe, now=lambda: clock[0])
        self.assertEqual(len(calls), 2)

    def test_the_launcher_uses_it_for_every_unsaved_profile_path(self):
        source = open(os.path.join(ROOT, "app", "_launch_runtime.py"), encoding="utf-8").read()
        self.assertEqual(source.count("copy.deepcopy(_DEFAULT_PRODUCTION_PROFILE)"), 0)
        self.assertEqual(source.count("_default_production_profile()"), 3)   # definition + the two fallbacks


if __name__ == "__main__":
    unittest.main()
