"""Regression tests for the non-generative comic storyboard preview."""

import unittest

from app.services.video_editor import _comic_preview_video_filter


class TestComicStoryboardPreview(unittest.TestCase):
    def test_static_preview_preserves_the_complete_panel(self):
        video_filter = _comic_preview_video_filter(
            duration=3,
            width=1920,
            height=1080,
            fps=30,
            motion="none",
        )

        self.assertIn("force_original_aspect_ratio=decrease", video_filter)
        self.assertIn("pad=1920:1080", video_filter)
        self.assertNotIn("force_original_aspect_ratio=increase", video_filter)
        self.assertNotIn("crop=", video_filter)
        self.assertIn("zoompan=z='1':x='0':y='0'", video_filter)

    def test_optional_preview_push_is_restrained(self):
        video_filter = _comic_preview_video_filter(
            duration=5,
            width=1280,
            height=720,
            fps=25,
            motion="push-in",
        )

        self.assertIn("1+0.04*", video_filter)
        self.assertNotIn("1+0.10*", video_filter)


if __name__ == "__main__":
    unittest.main()
