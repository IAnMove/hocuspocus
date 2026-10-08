"""Intermediate files are released when their job is done; results and live work are kept."""
import json
import os
import time
from pathlib import Path

from services import workspace_cleanup as cleanup
from services.character_kit_library import HISTORY_REVISIONS, read_character_kit_library, write_character_kit_library
from services.production_disk import release_uploads
from services.world3d_export import staging_token


def _staging(root: Path, name: str, frames: int = 3, age: float = 0) -> Path:
    folder = root / ".world3d-export" / name
    (folder / "frames").mkdir(parents=True)
    for index in range(frames):
        (folder / "frames" / f"frame_{index:06d}.png").write_bytes(b"p" * 1000)
    (folder / "encoded.mp4").write_bytes(b"m" * 500)
    (folder / "fx.wav").write_bytes(b"w" * 100)
    (folder / "snapshot.json").write_text("{}")
    (folder / "audio-error.txt").write_text("none")
    if age:
        stamp = time.time() - age
        os.utime(folder, (stamp, stamp))
    return folder


def test_releasing_a_staging_folder_keeps_its_text_and_drops_frames_and_media(tmp_path):
    folder = _staging(tmp_path, "done")
    assert cleanup.release_export_staging(folder) == 3 * 1000 + 500 + 100
    assert sorted(item.name for item in folder.iterdir()) == ["audio-error.txt", "snapshot.json"]
    assert cleanup.release_export_staging(folder) == 0, "idempotent"
    assert cleanup.release_export_staging(tmp_path / "missing") == 0


def test_what_a_release_cannot_delete_is_logged_and_left(tmp_path, caplog):
    """A release never fails the export that asked for it, but a file it cannot delete is no longer a silent leak."""
    folder = _staging(tmp_path, "locked")
    (folder / "frames").chmod(0o500)
    try:
        with caplog.at_level("WARNING", logger="services.workspace_cleanup"):
            cleanup.release_export_staging(folder)
    finally:
        (folder / "frames").chmod(0o700)
    assert (folder / "frames" / "frame_000000.png").is_file() and not (folder / "encoded.mp4").exists()
    assert any("could not remove" in record.getMessage() and "frame_000000.png" in record.getMessage() for record in caplog.records)
    caplog.clear()
    assert cleanup.release_export_staging(folder) == 3 * 1000
    assert not caplog.records, "a file already gone is no failure"


class Registry:
    def __init__(self, tasks):
        self.tasks = tasks

    def list(self, *, statuses, limit):
        return [task for task in self.tasks if task["status"] in statuses]

    def command_admission_for_task(self, task_id):
        return next(({"intent_id": task["intent"]} for task in self.tasks if task["id"] == task_id), None)


def test_startup_prune_releases_finished_and_orphan_exports_but_keeps_live_and_fresh_ones(tmp_path):
    old = 3600
    running = _staging(tmp_path, "running-1", age=old)
    interrupted = _staging(tmp_path, "interrupted-1", age=old)
    completed = _staging(tmp_path, "completed-1", age=old)
    failed = _staging(tmp_path, "failed-1", age=old)
    orphan = _staging(tmp_path, "nobody-knows", age=old)
    fresh = _staging(tmp_path, "fresh-1")
    other = _staging(tmp_path, "other-tool", age=old)
    registry = Registry([
        {"id": "t1", "status": "running", "workflow": "scenes.world3d.export", "intent": "running-1"},
        {"id": "t2", "status": "interrupted", "workflow": "scenes.world3d.export", "intent": "interrupted-1"},
        {"id": "t3", "status": "completed", "workflow": "scenes.world3d.export", "intent": "completed-1"},
        {"id": "t4", "status": "failed", "workflow": "scenes.world3d.export", "intent": "failed-1"},
        {"id": "t5", "status": "running", "workflow": "something.else", "intent": "other-tool"},
    ])
    summary = cleanup.prune_export_staging(str(tmp_path), registry, {"scenes.world3d.export"}, staging_token)
    assert summary == {"released": 4, "bytes": 4 * 3600}
    assert (running / "frames").is_dir() and (interrupted / "frames").is_dir(), "live and resumable exports keep their frames"
    assert (fresh / "frames").is_dir(), "a folder touched minutes ago may belong to a worker that has not registered yet"
    for folder in (completed, failed, orphan, other):
        assert not (folder / "frames").exists() and (folder / "snapshot.json").is_file()
    assert cleanup.prune_export_staging(str(tmp_path / "nowhere"), registry, set(), staging_token) == {"released": 0, "bytes": 0}


def test_a_hashed_intent_maps_to_its_staging_folder(tmp_path):
    token = staging_token("not safe / at all")
    assert token != "not safe / at all" and len(token) == 32
    _staging(tmp_path, token, age=3600)
    registry = Registry([{"id": "t1", "status": "running", "workflow": "op", "intent": "not safe / at all"}])
    assert cleanup.prune_export_staging(str(tmp_path), registry, {"op"}, staging_token)["released"] == 0


def test_raw_voice_takes_go_once_their_trimmed_recording_exists(tmp_path):
    (tmp_path / "ln-ep-b0-abc.wav").write_bytes(b"trimmed")
    (tmp_path / "ln-ep-b0-abc-raw0.wav").write_bytes(b"r" * 10)
    (tmp_path / "ln-ep-b0-abc-raw0.meta.json").write_text("{}")
    (tmp_path / "ln-ep-b0-abc-raw1.wav").write_bytes(b"r" * 10)
    (tmp_path / "ln-ep-b9-zzz-raw0.wav").write_bytes(b"r" * 10)  # its recording never finished: keep
    (tmp_path / "song-raw0.wav").write_bytes(b"user file")       # not ours
    summary = cleanup.release_voice_raws(str(tmp_path))
    assert summary["released"] == 2 and summary["bytes"] == 22
    assert sorted(path.name for path in tmp_path.iterdir()) == ["ln-ep-b0-abc.wav", "ln-ep-b9-zzz-raw0.wav", "song-raw0.wav"]


def test_old_temp_folders_of_the_speech_analysis_are_swept(tmp_path):
    old = tmp_path / "hocuspocus-speech-old"
    old.mkdir()
    (old / "voice.wav").write_bytes(b"v" * 40)
    stamp = time.time() - 2 * 86400
    os.utime(old, (stamp, stamp))
    (tmp_path / "hocuspocus-speech-new").mkdir()
    (tmp_path / "other-app").mkdir()
    assert cleanup.sweep_temp_dirs(root=str(tmp_path)) == {"released": 1, "bytes": 40}
    assert sorted(path.name for path in tmp_path.iterdir()) == ["hocuspocus-speech-new", "other-app"]


def test_startup_cleanup_covers_every_workspace_and_survives_a_broken_one(tmp_path, monkeypatch):
    monkeypatch.delenv("HOCUS_KEEP_EXPORT_STAGING", raising=False)
    good = tmp_path / "good"
    good.mkdir()
    _staging(good, "completed-1", age=3600)
    (good / "ln-ep-b0-abc.wav").write_bytes(b"t")
    (good / "ln-ep-b0-abc-raw0.wav").write_bytes(b"r" * 5)
    registry = Registry([{"id": "t3", "status": "completed", "workflow": "op", "intent": "completed-1"}])
    lines = []

    def registry_for(name):
        if name == "broken":
            raise RuntimeError("no registry")
        return registry
    temp = tmp_path / "tmp"
    temp.mkdir()
    total = cleanup.startup_cleanup(["good", "broken"], lambda name: str(tmp_path / name), registry_for, {"op"}, staging_token,
                                    log=lines.append, temp_root=str(temp))
    assert total["released"] == 2 and total["bytes"] == 3600 + 5
    assert any("broken" in line for line in lines) and any("Released" in line for line in lines)
    monkeypatch.setenv("HOCUS_KEEP_EXPORT_STAGING", "1")
    _staging(good, "completed-2", age=3600)
    kept = cleanup.startup_cleanup(["good"], lambda name: str(tmp_path / name), registry_for, {"op"}, staging_token, log=lines.append,
                                   temp_root=str(temp))
    assert kept["bytes"] == 0 and (good / ".world3d-export" / "completed-2" / "frames").is_dir()


def test_a_completed_production_releases_its_upload_copies_unless_the_state_still_uses_them(tmp_path):
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    for name in ("a.png", "b.wav", "c.mp4"):
        (uploads / name).write_bytes(b"x")
    state = {"status": "completed", "uploads": ["a.png", "b.wav", "c.mp4", "gone.png"],
             "clips": {"s1": {"url": "/api/v1/uploads/c.mp4"}}}
    assert release_uploads(uploads, state) == 2
    assert sorted(path.name for path in uploads.iterdir()) == ["c.mp4"], "the clip the package refers to stays"
    assert state["uploads"] == ["c.mp4"]
    running = {"status": "running", "uploads": ["c.mp4"]}
    assert release_uploads(uploads, running) == 0 and (uploads / "c.mp4").is_file(), "only a completed run releases"


def test_the_kit_library_keeps_only_the_last_revisions_of_its_history(tmp_path):
    workspace = str(tmp_path)
    library = read_character_kit_library(workspace)
    for revision in range(HISTORY_REVISIONS + 4):
        library = write_character_kit_library(workspace, {**library, "kits": {}}, base_revision=library["revision"])
    snapshots = sorted(path.name for path in tmp_path.iterdir() if ".v" in path.name and path.name.endswith(".json"))
    numbers = sorted(int(name.rsplit(".v", 1)[1][:-5]) for name in snapshots)
    assert len(numbers) == HISTORY_REVISIONS and numbers[-1] == library["revision"] - 1
    oldest = next(name for name in snapshots if name.endswith(f".v{numbers[0]}.json"))
    assert json.loads((tmp_path / oldest).read_text())["revision"] == numbers[0], "the kept snapshots are the real ones"
