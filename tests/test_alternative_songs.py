import json
import os
import random
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app"))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from services.alternative_songs import (  # noqa: E402
    attach_song,
    find_song,
    load_sidecar,
    plan_timeline,
    public_song,
    recover_stale_mounts,
    remove_song,
    resolve_remount_sources,
    save_sidecar,
    sidecar_path,
    source_clip_names,
    unique_mounted_name,
    write_mounted_sidecar,
)
from services.asset_manifest import (  # noqa: E402
    SCHEMA_NAME,
    publish_generation_sidecar,
    read_asset_manifest,
)
from services.generation_provenance import provenance_from_manifest  # noqa: E402
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

    def test_missing_authored_shots_fall_back_to_assembled_video(self):
        assembled = _clip("mix.mp4", 8)
        sidecar = {"params": {"source_clips": ["deleted-a.mp4", "deleted-b.mp4"]}}
        with mock.patch(
            "services.alternative_songs.resolve_existing_files",
            side_effect=[[], [assembled]],
        ) as resolve:
            sources = resolve_remount_sources(sidecar, "mix.mp4", "/outputs")

        self.assertEqual(sources, [assembled])
        self.assertEqual(
            resolve.call_args_list,
            [
                mock.call(["deleted-a.mp4", "deleted-b.mp4"], "/outputs"),
                mock.call(["mix.mp4"], "/outputs"),
            ],
        )

    def test_stale_mount_is_released_but_live_worker_stays_mounting(self):
        sidecar = {"params": {}}
        record = attach_song(sidecar, audio_name="en.mp3", duration_seconds=12)
        record.update({"status": "mounting", "job_id": "alt-song-live"})

        self.assertFalse(recover_stale_mounts(sidecar, lambda job_id: job_id == "alt-song-live"))
        self.assertEqual(record["status"], "mounting")
        self.assertTrue(recover_stale_mounts(sidecar, lambda _job_id: False))
        self.assertEqual(record["status"], "attached")
        self.assertIsNone(record["job_id"])

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


class AlternativeSongSidecarTests(unittest.TestCase):
    def test_save_sidecar_publishes_v1_and_roundtrips_songs(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = os.path.join(tmp, "clip.mp4")
            Path(video).write_bytes(b"not-a-real-mp4")
            sidecar = load_sidecar(video)
            attach_song(sidecar, audio_name="en.mp3", duration_seconds=9)
            sidecar["params"]["api_key"] = "secret-key"
            save_sidecar(video, sidecar)
            raw = json.loads(Path(sidecar_path(video)).read_text(encoding="utf-8"))
            loaded = read_asset_manifest(video)
            text = Path(sidecar_path(video)).read_text(encoding="utf-8")
            self.assertEqual(raw["schema"], SCHEMA_NAME)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded["origin"]["actor"], "unknown")
            self.assertEqual(raw["params"]["alternative_songs"][0]["audio_name"], "en.mp3")
            self.assertTrue(raw["params"]["alternative_songs"][0]["id"].startswith("song-"))
            self.assertNotIn("secret-key", text)
            self.assertNotEqual(loaded["origin"].get("actor"), "user")

    def test_save_sidecar_keeps_existing_v1_asset_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = os.path.join(tmp, "clip.mp4")
            Path(video).write_bytes(b"not-a-real-mp4")
            sidecar = load_sidecar(video)
            attach_song(sidecar, audio_name="en.mp3", duration_seconds=9)
            save_sidecar(video, sidecar)
            first = read_asset_manifest(video)
            self.assertIsNotNone(first)
            asset_id = first["asset"]["id"]
            mutated = load_sidecar(video)
            attach_song(mutated, audio_name="pt.mp3", duration_seconds=8)
            save_sidecar(video, mutated)
            again = read_asset_manifest(video)
            raw = json.loads(Path(sidecar_path(video)).read_text(encoding="utf-8"))
            self.assertIsNotNone(again)
            self.assertEqual(again["asset"]["id"], asset_id)
            self.assertEqual(len(raw["params"]["alternative_songs"]), 2)

    def test_save_sidecar_keeps_series_assembly_origin_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = os.path.join(tmp, "episode.mp4")
            Path(video).write_bytes(b"video")
            publish_generation_sidecar(
                video,
                {
                    "generation_mode": "video",
                    "params": {"pipeline_type": "series_episode"},
                },
                workspace_id="lab",
                tool="series-assembly",
            )
            before = read_asset_manifest(video)
            self.assertIsNotNone(before)
            sidecar = load_sidecar(video)
            attach_song(sidecar, audio_name="en.mp3", duration_seconds=9)
            save_sidecar(video, sidecar)
            loaded = read_asset_manifest(video)
            raw = json.loads(Path(sidecar_path(video)).read_text(encoding="utf-8"))
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded["origin"]["tool"], "series-assembly")
            self.assertEqual(loaded["asset"]["id"], before["asset"]["id"])
            self.assertEqual(raw["params"]["alternative_songs"][0]["audio_name"], "en.mp3")
            self.assertEqual(loaded["origin"]["output_folder"], "lab")
            self.assertIn(loaded["origin"].get("workspace_id"), (None, ""))

    def test_write_mounted_sidecar_publishes_alternative_songs_origin(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = os.path.join(tmp, "clip_en_mv.mp4")
            Path(output).write_bytes(b"video")
            parent_sidecar = {
                "params": {
                    "pipeline_type": "music_video",
                    "model_type": "ffmpeg_remount",
                    "resolution": "720p",
                },
            }
            song = attach_song({"params": {}}, audio_name="en.mp3", duration_seconds=9)
            planned = [{
                "name": "shot.mp4",
                "path": os.path.join(tmp, "shot.mp4"),
                "duration": 4,
                "used": 4,
                "extra": False,
            }]
            write_mounted_sidecar(
                output_path=output,
                parent_name="clip.mp4",
                parent_sidecar=parent_sidecar,
                song=song,
                planned=planned,
                job_id="alt-song-1",
                workspace="night-shift",
            )
            raw = json.loads(Path(sidecar_path(output)).read_text(encoding="utf-8"))
            loaded = read_asset_manifest(output)
            self.assertEqual(raw["schema"], SCHEMA_NAME)
            self.assertEqual(raw["parent_output"], "clip.mp4")
            self.assertEqual(raw["params"]["parent_output"], "clip.mp4")
            self.assertEqual(song["status"], "mounted")
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded["origin"]["tool"], "alternative-songs")
            self.assertEqual(loaded["origin"]["output_folder"], "night-shift")
            self.assertIn(loaded["origin"].get("workspace_id"), (None, ""))
            self.assertEqual(loaded["origin"]["actor"], "unknown")
            self.assertEqual(loaded["execution"]["job_id"], "alt-song-1")
            self.assertEqual(loaded["generation"]["model"]["id"], "ffmpeg_remount")
            self.assertEqual(loaded["generation"]["model"]["provider"], "ffmpeg")
            proven = provenance_from_manifest(loaded)
            self.assertEqual(proven["tool"], "alternative-songs")
            self.assertEqual(proven["output_folder"], "night-shift")
            self.assertIsNone(proven["workspace_id"])
            self.assertEqual(proven["command"]["job_id"], "alt-song-1")

    def test_save_sidecar_folder_name_does_not_invent_workspace_collection(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = os.path.join(tmp, "clip.mp4")
            Path(video).write_bytes(b"video")
            sidecar = load_sidecar(video)
            attach_song(sidecar, audio_name="en.mp3", duration_seconds=9)
            sidecar["workspace"] = "night-shift"
            save_sidecar(video, sidecar)
            loaded = read_asset_manifest(video)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded["origin"]["output_folder"], "night-shift")
            self.assertIn(loaded["origin"].get("workspace_id"), (None, ""))
            self.assertEqual(loaded["origin"]["actor"], "unknown")

    def test_save_sidecar_preserves_real_workspace_collection_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = os.path.join(tmp, "clip.mp4")
            Path(video).write_bytes(b"video")
            publish_generation_sidecar(
                video,
                {
                    "generation_mode": "video",
                    "params": {
                        "pipeline_type": "music_video",
                        "director_pipeline_id": "pipe-9",
                    },
                    "pipeline_id": "pipe-9",
                },
                workspace_id="workspace_abc123",
                output_folder="night-shift",
                tool="director",
            )
            sidecar = load_sidecar(video)
            attach_song(sidecar, audio_name="en.mp3", duration_seconds=9)
            save_sidecar(video, sidecar)
            loaded = read_asset_manifest(video)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded["origin"]["tool"], "director")
            self.assertEqual(loaded["origin"]["workspace_id"], "workspace_abc123")
            self.assertEqual(loaded["origin"]["output_folder"], "night-shift")
            self.assertEqual(loaded["execution"]["pipeline_id"], "pipe-9")

    def test_write_mounted_sidecar_copies_director_pipeline_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = os.path.join(tmp, "clip_en_mv.mp4")
            Path(output).write_bytes(b"video")
            parent_sidecar = {
                "pipeline_id": "pipe-44",
                "director_pipeline_id": "pipe-44",
                "task_id": "task-director-pipe-44",
                "root_task_id": "task-director-pipe-44",
                "params": {
                    "pipeline_type": "music_video",
                    "model_type": "minimax_h3",
                    "director_pipeline_id": "pipe-44",
                    "resolution": "720p",
                },
            }
            song = attach_song({"params": {}}, audio_name="en.mp3", duration_seconds=9)
            planned = [{
                "name": "shot.mp4",
                "path": os.path.join(tmp, "shot.mp4"),
                "duration": 4,
                "used": 4,
                "extra": False,
            }]
            write_mounted_sidecar(
                output_path=output,
                parent_name="clip.mp4",
                parent_sidecar=parent_sidecar,
                song=song,
                planned=planned,
                job_id="alt-song-2",
                workspace="night-shift",
            )
            loaded = read_asset_manifest(output)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded["origin"]["tool"], "alternative-songs")
            self.assertEqual(loaded["origin"]["output_folder"], "night-shift")
            self.assertIn(loaded["origin"].get("workspace_id"), (None, ""))
            self.assertEqual(loaded["execution"]["job_id"], "alt-song-2")
            self.assertEqual(loaded["execution"]["pipeline_id"], "pipe-44")
            self.assertEqual(loaded["execution"]["task_id"], "task-director-pipe-44")
            self.assertEqual(loaded["execution"]["root_task_id"], "task-director-pipe-44")


if __name__ == "__main__":
    unittest.main()
