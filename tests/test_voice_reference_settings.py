"""Regression coverage for Voice Reference and beta-feature defaults."""

import json
import os
import unittest


_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LAUNCH_PATH = os.path.join(_ROOT, "app", "_launch_runtime.py")
_SERVICES_PANEL_PATH = os.path.join(
    _ROOT,
    "ui",
    "src",
    "components",
    "SettingsDrawer",
    "ServicesSettingsPanel.tsx",
)
_SETTINGS_EN_PATH = os.path.join(
    _ROOT, "ui", "src", "i18n", "locales", "en", "settings.json",
)


def _read(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


class TestVoiceReferenceSettings(unittest.TestCase):
    def test_voice_reference_defaults_on_while_beta_features_default_off(self):
        launch = _read(_LAUNCH_PATH)
        self.assertIn(
            '"voice_reference_enabled": services.get('
            '"voice_reference_enabled", True)',
            launch,
        )
        self.assertIn(
            '"show_experimental": services.get("show_experimental", False)',
            launch,
        )

    def test_voice_reference_setting_is_not_behind_beta_feature_gate(self):
        panel = _read(_SERVICES_PANEL_PATH)
        settings = json.loads(_read(_SETTINGS_EN_PATH))
        block_start = panel.index("{/* Voice Reference (ID-LoRA)")
        block_end = panel.index("</label>", block_start)
        voice_reference_block = panel[block_start:block_end]

        self.assertIn("t('services.voiceTitle')", voice_reference_block)
        self.assertEqual(settings["services"]["voiceTitle"], "Voice Reference (ID-LoRA)")
        self.assertIn("voice_reference_enabled", voice_reference_block)
        self.assertNotIn("show_experimental", voice_reference_block)
        self.assertNotIn("Experimental", voice_reference_block)

        beta_copy = panel[panel.index("t('services.betaToggle')"):]
        self.assertEqual(settings["services"]["betaToggle"], "Show in-development features")
        self.assertNotIn("services.voiceTitle", beta_copy)


if __name__ == "__main__":
    unittest.main()
