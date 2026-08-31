import os
import random
import sys
import tempfile
import unittest
from pathlib import Path

_APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app"))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from services.alternative_songs import (  # noqa: E402
    attach_song,
    find_song,
    load_sidecar,
    plan_timeline,
    public_song,
    remove_song,
    save_sidecar,
    source_clip_names,
    unique_mounted_name,
)
from services.output_result_kind import classify_output_result_kind  # noqa: E402


def _clip(name: str, duration: float) -> dict:
    return {"name": name, "path": f"/tmp/{name}", "duration": duration}


class AlternativeSongPlannerTests(unittest.TestCase):
    def test_shorter_song_keeps_original_order_and_stops(self):
        planned = plan_timeline(
            [_clip("a.mp4", 5), _clip("b.mp4", 5), _clip("c.mp4", 5)],
            7.5,
            rng=random.Random(1),
        )
        self.assertEqual([item["name"] for item in planned], ["a.mp4", "b.mp4"])
        self.assertTrue(all(item["extra"] is False for item in planned))
        self.assertAlmostEqual(sum(item["used"] for item in planned), 7.5)

    def test_longer_song_appends_random_pool_shots(self):
        planned = plan_timeline(
            [_clip("a.mp4", 2), _clip("b.mp4", 2)],
            7,
            rng=random.Random(3),
        )
        self.assertGreaterEqual(len(planned), 4)
        self.assertEqual([item["name"] for item in planned[:2]], ["a.mp4", "b.mp4"])
        self.assertTrue(any(item["extra"] for item in planned))
        extras = [item for item in planned if item["extra"]]
        self.assertGreaterEqual(len(extras), 1)
        consecutive_same = 0
        for left, right in zip(planned, planned[1:]):
            if left["name"] == right["name"]:
                consecutive_same += 1
        self.assertEqual(consecutive_same, 0)

    def test_single_source_loops_the_assembled_video(self):
        planned = plan_timeline([_clip("mix.mp4", 3)], 8, rng=random.Random(0))
        self.assertGreaterEqual(len(planned), 3)
        self.assertTrue(all(item["name"] == "mix.mp4" for item in planned))
        self.assertTrue(planned[0]["extra"] is False)
        self.assertTrue(any(item["extra"] for item in planned[1:]))

    def test_source_clip_names_prefer_director_then_editor_then_self(self):
        sidecar = {
            "params": {
                "source_clips": ["shot_a.mp4", "shot_b.mp4", "shot_a.mp4"],
                "video_editor": {"clips": [{"source": "/outputs/shot_c.mp4"}]},
            }
        }
        self.assertEqual(
            source_clip_names(sidecar, "final_mv.mp4"),
            ["shot_a.mp4", "shot_b.mp4", "shot_c.mp4"],
        )
        self.assertEqual(source_clip_names({"params": {}}, "final_mv.mp4"), ["final_mv.mp4"])

    def test_attach_is_idempotent_per_audio_name(self):
        sidecar = {"params": {}}
        first = attach_song(sidecar, audio_name="en.mp3", duration_seconds=12.5)
        second = attach_song(sidecar, audio_name="en.mp3", duration_seconds=13)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(sidecar["params"]["alternative_songs"]), 1)
        self.assertEqual(second["duration_seconds"], 13)
        other = attach_song(sidecar, audio_name="pt.mp3", duration_seconds=11)
        self.assertNotEqual(first["id"], other["id"])
        removed = remove_song(sidecar, other["id"])
        self.assertEqual(removed["audio_name"], "pt.mp3")
        self.assertIsNone(find_song(sidecar, song_id=other["id"]))

    def test_mounted_filename_lands_in_videoclips_tab(self):
        with tempfile.TemporaryDirectory() as tmp:
            name = unique_mounted_name(tmp, "sysadmin_unique.mp4", "Sysadmin Midnight EN.mp3")
            self.assertTrue(name.endswith("_mv.mp4"))
            self.assertIn("sysadmin_midnight_en", name)
            Path(os.path.join(tmp, name)).write_bytes(b"x")
            again = unique_mounted_name(tmp, "sysadmin_unique.mp4", "Sysadmin Midnight EN.mp3")
            self.assertNotEqual(again, name)
        self.assertEqual(
            classify_output_result_kind(
                "sysadmin_unique_sysadmin_midnight_en_mv.mp4",
                {"result_kind": "music_video", "parent_output": "sysadmin_unique.mp4"},
            ),
            "music_video",
        )

    def test_sidecar_roundtrip_keeps_songs(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = os.path.join(tmp, "clip.mp4")
            Path(video).write_bytes(b"not-a-real-mp4")
            sidecar = load_sidecar(video)
            attach_song(sidecar, audio_name="en.mp3", duration_seconds=9)
            save_sidecar(video, sidecar)
            reloaded = load_sidecar(video)
            songs = [public_song(item) for item in reloaded["params"]["alternative_songs"]]
            self.assertEqual(songs[0]["audio_name"], "en.mp3")
            self.assertTrue(songs[0]["id"].startswith("song-"))


if __name__ == "__main__":
    unittest.main()
