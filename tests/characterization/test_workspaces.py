"""Workspaces: list, create, switch, delete (launch "Workspaces" section)."""
from __future__ import annotations

import json
import os
import stat
import sys

import pytest

from tests.characterization import media


def test_workspaces_lifecycle(server, golden) -> None:
    server.check(golden, "list fresh", "GET", "/api/v1/workspaces")
    server.check(golden, "create", "POST", "/api/v1/workspaces", json={"name": "golden-a"})
    server.check(golden, "create again", "POST", "/api/v1/workspaces", json={"name": "golden-a"})
    server.check(golden, "create second", "POST", "/api/v1/workspaces", json={"name": "golden_b"})
    server.check(golden, "list after create", "GET", "/api/v1/workspaces")
    server.check(golden, "set active", "PUT", "/api/v1/workspaces/active", json={"name": "golden-a"})
    server.check(golden, "list after set active", "GET", "/api/v1/workspaces")
    server.check(golden, "set active back", "PUT", "/api/v1/workspaces/active", json={"name": "default"})
    server.check(golden, "delete", "DELETE", "/api/v1/workspaces/golden_b")
    server.check(golden, "list after delete", "GET", "/api/v1/workspaces")


def test_wizard_persistence_round_trip(server, golden) -> None:
    server.check(golden, "wizard conversation empty", "GET", "/api/v1/wizard/conversations")
    server.check(golden, "wizard workflows empty", "GET", "/api/v1/wizard/workflows")
    server.check(
        golden, "wizard conversation invalid workspace", "GET", "/api/v1/wizard/conversations",
        params={"workspace": "../escape"},
    )
    server.check(
        golden, "wizard workflows invalid workspace", "GET", "/api/v1/wizard/workflows",
        params={"workspace": "../escape"},
    )
    server.check(golden, "wizard conversation save", "PUT", "/api/v1/wizard/conversations", json={
        "workspace": "default",
        "baseRevision": 0,
        "conversation": {
            "version": 1,
            "revision": 0,
            "messages": [{"id": "msg-1", "role": "user", "text": "Hola", "createdAt": 1}],
        },
    })
    server.check(golden, "wizard conversation loaded", "GET", "/api/v1/wizard/conversations")
    server.check(golden, "wizard workflows save", "PUT", "/api/v1/wizard/workflows", json={
        "workspace": "default",
        "baseRevision": 0,
        "collection": {"version": 1, "revision": 0, "workflows": []},
    })
    server.check(golden, "wizard workflows loaded", "GET", "/api/v1/wizard/workflows")


def test_storage_usage_reads_sidecars_and_workspace_sizes(server, golden) -> None:
    """Storage usage joins generation sidecars with the bytes in each workspace."""
    (server.outputs / "clip.meta.json").write_text(
        json.dumps({
            "created_at": 10,
            "params": {"model_type": "fake_t2v", "activated_loras": ["look.safetensors"]},
        }),
        encoding="utf-8",
    )
    (server.outputs / "lab").mkdir()
    (server.outputs / "lab" / "note.txt").write_text("hi", encoding="utf-8")
    server.check(golden, "storage usage", "GET", "/api/v1/storage/usage")


def test_workspace_names_are_validated(server, golden) -> None:
    server.check(golden, "create without name", "POST", "/api/v1/workspaces", json={})
    server.check(golden, "create with a path", "POST", "/api/v1/workspaces", json={"name": "../escape"})
    server.check(golden, "create with a space", "POST", "/api/v1/workspaces", json={"name": "two words"})
    server.check(golden, "set active invalid", "PUT", "/api/v1/workspaces/active", json={"name": "a/b"})
    server.check(golden, "delete default", "DELETE", "/api/v1/workspaces/default")
    server.check(golden, "delete missing", "DELETE", "/api/v1/workspaces/never-made")
    server.check(golden, "outputs of an invalid workspace", "GET", "/api/v1/outputs", params={"workspace": "..."})


def test_workspace_listing_counts_visible_files_and_skips_private_folders(server, golden) -> None:
    """``file_count`` counts the non-hidden files directly inside a folder; ``_`` and ``.`` folders are not workspaces."""
    (server.outputs / "golden-a").mkdir()
    (server.outputs / "golden-b").mkdir()
    (server.outputs / "_private").mkdir()
    (server.outputs / ".cache").mkdir()
    (server.outputs / "one.txt").write_text("1", encoding="utf-8")
    (server.outputs / ".hidden.txt").write_text("h", encoding="utf-8")
    (server.outputs / "golden-a" / "a.txt").write_text("a", encoding="utf-8")
    (server.outputs / "golden-a" / "b.txt").write_text("b", encoding="utf-8")
    (server.outputs / "golden-a" / "nested").mkdir()
    (server.outputs / "golden-a" / "nested" / "deep.txt").write_text("d", encoding="utf-8")
    (server.outputs / "_private" / "p.txt").write_text("p", encoding="utf-8")
    server.check(golden, "listing counts files", "GET", "/api/v1/workspaces")


def test_switching_the_workspace_saves_the_config_file_atomically(server, golden) -> None:
    """The switch is written to ``wgp.server_config_filename`` with owner-only permissions and no temporary file left."""
    config_file = server.root / "wgp_config.json"
    response = server.client.put("/api/v1/workspaces/active", json={"name": "golden-saved"})
    assert response.status_code == 200
    saved = json.loads(config_file.read_text(encoding="utf-8"))
    assert saved["services"]["active_workspace"] == "golden-saved"
    assert saved["save_path"] == str(server.outputs)
    if os.name == "posix":
        assert stat.S_IMODE(config_file.stat().st_mode) == 0o600
    assert [item.name for item in server.root.iterdir() if item.name.endswith(".tmp")] == []
    assert server.wgp.server_config["services"]["active_workspace"] == "golden-saved"
    assert os.path.realpath(server.wgp.save_path) == os.path.realpath(server.outputs / "golden-saved")
    assert os.path.realpath(server.wgp.image_save_path) == os.path.realpath(server.outputs / "golden-saved")
    server.check(golden, "listing after the switch", "GET", "/api/v1/workspaces")


def test_switching_the_workspace_while_a_generation_runs_defers_the_save_path(server, monkeypatch) -> None:
    """With a worker registered in the shared abort-state dictionary the config is saved and ``wgp.save_path`` waits."""
    launch = sys.modules["_launch_runtime"]
    before = server.wgp.save_path
    monkeypatch.setitem(launch._active_gen_states, "golden-busy", {"abort": False})
    response = server.client.put("/api/v1/workspaces/active", json={"name": "golden-deferred"})
    assert response.status_code == 200
    assert server.wgp.server_config["services"]["active_workspace"] == "golden-deferred"
    assert json.loads((server.root / "wgp_config.json").read_text(encoding="utf-8"))["services"]["active_workspace"] == "golden-deferred"
    assert server.wgp.save_path == before


def test_audio_adopt_resolves_media_in_the_workspace_and_in_uploads(server, golden) -> None:
    """``/api/v1/audio/adopt`` goes through the request media path policy (workspace, uploads, traversal)."""
    media.sound(server.outputs / "golden_song.wav")
    media.sound(server.outputs / "golden-w" / "golden_other.wav")
    media.sound(server.root / "uploads" / "audio" / "golden_upload.wav")
    media.sound(server.root / "golden_outside.wav")
    media.image(server.outputs / "golden_picture.png")
    adopt = "/api/v1/audio/adopt"
    server.check(golden, "adopt a workspace song", "POST", adopt, json={"audio_path": "golden_song.wav"})
    server.check(golden, "adopt from another workspace", "POST", adopt, json={"audio_path": "golden_other.wav", "workspace": "golden-w"})
    server.check(golden, "adopt an upload by url", "POST", adopt, json={"audio_path": "/api/v1/uploads/audio/golden_upload.wav"})
    server.check(golden, "adopt an upload by path", "POST", adopt, json={"audio_path": "uploads/audio/golden_upload.wav"})
    server.check(golden, "adopt a missing file", "POST", adopt, json={"audio_path": "golden_missing.wav"})
    server.check(golden, "adopt a traversal", "POST", adopt, json={"audio_path": "../golden_outside.wav"})
    server.check(golden, "adopt an absolute path outside", "POST", adopt, json={"audio_path": str(server.root / "golden_outside.wav")})
    server.check(golden, "adopt a picture as audio", "POST", adopt, json={"audio_path": "golden_picture.png"})
    server.check(golden, "adopt in an invalid workspace", "POST", adopt, json={"audio_path": "golden_song.wav", "workspace": "../x"})


def test_audio_upload_trim_mix_and_analysis_cheap_reads(server, golden) -> None:
    """Validation and cheap reads for the audio routes still living in the launch module.

    A real analysis job is not started: that worker runs in a background thread.
    Transcription is not asked for. Beat fields from a silent clip are masked
    because librosa's reading of silence is not a contract.
    """
    media.sound(server.outputs / "trim_me.wav", seconds=1.2)
    media.sound(server.outputs / "mix_a.wav")
    media.sound(server.outputs / "mix_b.wav")
    excerpt = (r"[0-9a-f]{8}-excerpt\.wav", "<ID>-excerpt.wav")
    mix_name = (r"mix_[0-9a-f]{6}\.wav", "mix_<ID>.wav")

    server.check(golden, "audio analyze status idle", "GET", "/api/v1/audio/analyze/status")
    server.check(
        golden, "upload an unsupported audio file", "POST", "/api/v1/upload-audio",
        files={"file": ("notes.txt", b"not audio", "text/plain")},
    )
    uploaded = server.check(
        golden, "upload a wav", "POST", "/api/v1/upload-audio",
        files={"file": ("clip.wav", media.sound(server.root / "clip.wav").read_bytes(), "audio/wav")},
    )
    server.check(golden, "serve a missing audio upload", "GET", "/api/v1/uploads/audio/missing.wav")
    served = server.client.get(uploaded.json()["url"])
    assert served.status_code == 200
    assert served.headers["content-type"].startswith("audio/")

    trim = "/api/v1/audio/trim"
    server.check(golden, "trim a missing file", "POST", trim, json={"audio_path": "missing.wav", "start": 0, "end": 1})
    server.check(golden, "trim bad times", "POST", trim, json={"audio_path": "trim_me.wav", "start": "later", "end": "soon"})
    server.check(golden, "trim too short", "POST", trim, json={"audio_path": "trim_me.wav", "start": 0, "end": 0.5})
    server.check(golden, "trim an invalid workspace", "POST", trim, json={"audio_path": "trim_me.wav", "workspace": "../x", "start": 0, "end": 1})
    media.need_ffmpeg()
    server.check(
        golden, "trim an excerpt", "POST", trim,
        json={"audio_path": "trim_me.wav", "start": 0, "end": 1.0},
        replace=(excerpt,),
    )

    mix = "/api/v1/audio/mix"
    base = str(server.outputs / "mix_a.wav")
    server.check(golden, "mix fewer than two tracks", "POST", mix, json={"tracks": [{"path": base}]})
    server.check(
        golden, "mix a path that is not allowed", "POST", mix,
        json={"tracks": [{"path": base}, {"path": "/etc/passwd"}]},
    )
    server.check(
        golden, "mix two workspace tracks", "POST", mix,
        json={"tracks": [
            {"path": base, "volume": 1.0},
            {"path": str(server.outputs / "mix_b.wav"), "start_time": 0, "volume": 0.5},
        ]},
        replace=(mix_name,),
    )

    analyze = "/api/v1/audio/analyze"
    unstable = ("bpm", "beats", "downbeats", "sections", "onset_envelope")
    server.check(golden, "analyze a missing file", "POST", analyze, json={"audio_path": "missing.wav", "transcribe": False})
    server.check(golden, "analyze a traversal", "POST", analyze, json={"audio_path": "../escape.wav", "transcribe": False})
    server.check(golden, "analyze an invalid workspace", "POST", analyze, json={"audio_path": "trim_me.wav", "workspace": "../x", "transcribe": False})
    server.check(
        golden, "analyze a tiny wav", "POST", analyze,
        json={"audio_path": "trim_me.wav", "transcribe": False},
        mask=unstable,
    )

    jobs = "/api/v1/audio/analyze/jobs"
    server.check(golden, "queue analysis of a missing file", "POST", jobs, json={"audio_path": "missing.wav"})
    server.check(
        golden, "queue analysis with an invalid task id", "POST", jobs,
        json={"audio_path": "trim_me.wav", "task_id": "not-a-task"},
    )
    unknown = "audio-analysis-does-not-exist"
    server.check(golden, "read an unknown analysis job", "GET", f"{jobs}/{unknown}")
    server.check(golden, "cancel an unknown analysis job", "POST", f"{jobs}/{unknown}/cancel")

    suggest = "/api/v1/audio/suggest-clips"
    plan = "/api/v1/audio/plan-structure"
    server.check(golden, "suggest clips without analysis", "POST", suggest, json={})
    server.check(golden, "plan structure without analysis", "POST", plan, json={})
    fake = {
        "duration": 10.0,
        "bpm": 120.0,
        "beats": [{"time": 0.5, "strength": 0.4}, {"time": 1.0, "strength": 0.4}],
        "downbeats": [],
        "sections": [{"start": 0.0, "end": 10.0, "label": "verse", "energy": 0.4}],
    }
    server.check(golden, "suggest clips from a stored analysis", "POST", suggest, json={"analysis": fake, "clip_duration": 5.0, "total_duration": 10.0})
    server.check(golden, "plan structure from a stored analysis", "POST", plan, json={"analysis": fake, "pacing_profile": "balanced", "total_duration": 10.0})
