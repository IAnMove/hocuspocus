"""Workspaces: list, create, switch, delete (launch "Workspaces" section)."""
from __future__ import annotations

import importlib.util
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


def test_the_full_server_registers_the_busy_probes_of_every_family_it_runs(server) -> None:
    """Booting the server wires the "full" profile (workspace router) and the probes the Series and game routers push."""
    from services import workspace_busy

    assert set(workspace_busy.registered()) == {
        "video-editor", "minimax-music", "minimax-image", "rig", "series-plan", "music-production",
        "model3d", "story-plan", "comic-plan", "director-plan", "series-render",
        "game-produce", "series-produce", "series-native", "series-voice", "series-assembly", "quick-video-batch",
    }


def test_deleting_a_workspace_with_a_running_export_is_refused_and_leaves_other_workspaces_alone(server) -> None:
    """A real DELETE on the full server: the refusal is readable text with a code, the folder survives, a free workspace goes."""
    from routers.video_editor import _register_video_editor_job, reset_video_editor_jobs

    (server.outputs / "golden-busy").mkdir()
    (server.outputs / "golden-busy" / "clip.mp4").write_bytes(b"clip")
    (server.outputs / "golden-free").mkdir()
    reset_video_editor_jobs()
    try:
        _register_video_editor_job({"job_id": "golden-export", "workspace": "golden-busy", "status": "running"})
        refused = server.client.delete("/api/v1/workspaces/golden-busy")
        free = server.client.delete("/api/v1/workspaces/golden-free")
    finally:
        reset_video_editor_jobs()
    deleted = server.client.delete("/api/v1/workspaces/golden-busy")

    assert refused.status_code == 409
    body = refused.json()
    assert isinstance(body["detail"], str) and "video-editor golden-export (running)" in body["detail"]
    assert body["code"] == "workspace_busy" and [item["kind"] for item in body["blocking"]] == ["video-editor"]
    assert free.status_code == 200 and not (server.outputs / "golden-free").exists()
    assert deleted.status_code == 200 and not (server.outputs / "golden-busy").exists()


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


def test_storage_duplicates_scan_reclaim_and_linked_removal(server, golden, tmp_path, monkeypatch) -> None:
    """Duplicate scan, reclaim and linked-removal guards. No weights are downloaded.

    The scan reads whatever ``wgp.fl`` and the LoRA root say. Both are pointed
    at empty-or-fixture folders under this test, so the answer does not depend
    on the machine's model folders.
    """
    primary = tmp_path / "install-a" / "app" / "ckpts"
    linked = tmp_path / "install-b" / "app" / "ckpts"
    loras = tmp_path / "loras"
    primary.mkdir(parents=True)
    linked.mkdir(parents=True)
    loras.mkdir()
    payload = b"w" * (10 * 1024 * 1024)
    (primary / "same.safetensors").write_bytes(payload)
    (linked / "same.safetensors").write_bytes(payload)
    (primary / "clash.safetensors").write_bytes(b"aaa")
    (linked / "clash.safetensors").write_bytes(b"bbbb")
    linked_app = str(linked.parent)

    class _Files:
        def get_checkpoints_paths(self):
            return [str(primary), str(linked)]

        def is_external_root(self, root):
            return os.path.abspath(root) == str(linked)

        def is_protected_path(self, path):
            if not path:
                return False
            candidate = os.path.abspath(path)
            try:
                return os.path.commonpath([candidate, linked_app]) == linked_app
            except ValueError:
                return False

    monkeypatch.setattr(server.wgp, "fl", _Files(), raising=False)
    monkeypatch.setitem(server.wgp.server_config, "loras_root", str(loras))

    same_primary = str(primary / "same.safetensors")
    same_linked = str(linked / "same.safetensors")
    server.check(golden, "storage duplicates", "GET", "/api/v1/storage/duplicates")
    server.check(
        golden, "reclaim missing path", "POST", "/api/v1/storage/duplicates/reclaim", json={"path": ""},
    )
    server.check(
        golden, "reclaim absent file", "POST", "/api/v1/storage/duplicates/reclaim",
        json={"path": str(primary / "nope.safetensors")},
    )
    server.check(
        golden, "reclaim a linked file", "POST", "/api/v1/storage/duplicates/reclaim",
        json={"path": same_linked},
    )
    server.check(
        golden, "remove linked while disabled", "POST", "/api/v1/storage/duplicates/remove-linked",
        json={"path": same_linked},
    )
    services = server.wgp.server_config["services"]
    monkeypatch.setitem(services, "storage_allow_linked_removal", True)
    server.check(
        golden, "remove linked duplicate", "POST", "/api/v1/storage/duplicates/remove-linked",
        json={"path": same_linked},
    )
    assert (linked / "same.safetensors").is_file()
    server.check(
        golden, "reclaim primary duplicate", "POST", "/api/v1/storage/duplicates/reclaim",
        json={"path": same_primary},
    )
    assert not (primary / "same.safetensors").is_file()
    assert (linked / "same.safetensors").is_file()


def test_storage_duplicates_never_count_or_delete_one_physical_file_twice(server, tmp_path, monkeypatch) -> None:
    """The safety checks of the duplicate tools, on links and look-alike files. No golden: plain assertions.

    A hard link, a symlink, or a linked root that is the primary root through a link is one physical file:
    it is "shared", never a duplicate, and neither reclaim nor remove-linked deletes it. Same-size files that
    differ in a sampled chunk are conflicts, and so is a longer linked file that starts like the primary one.
    Pairs under 10 MB are not listed. The "." search root is not a linked install. A primary file present in
    two linked installs is listed once. Remove-linked refuses a primary file. Recorded on the server before the
    C9c move (the code under test did not change).
    """
    from services import win_safe_files

    size = 10 * 1024 * 1024
    primary = tmp_path / "install-a" / "app" / "ckpts"
    linked = tmp_path / "install-b" / "app" / "ckpts"
    second = tmp_path / "install-c" / "app" / "ckpts"
    joined = tmp_path / "install-j" / "app" / "ckpts"  # a linked root that is the primary root, through a link
    for folder in (primary, linked, second, joined.parent):
        folder.mkdir(parents=True)
    os.symlink(primary, joined)
    loras = tmp_path / "loras"
    loras.mkdir()

    def write(path, seed, flip=None):
        data = bytearray(bytes([seed]) * size)
        if flip is not None:
            data[flip] ^= 0xFF
        path.write_bytes(bytes(data))

    write(primary / "hard.safetensors", 1)
    os.link(primary / "hard.safetensors", linked / "hard.safetensors")
    write(primary / "sym.safetensors", 2)
    os.symlink(primary / "sym.safetensors", linked / "sym.safetensors")
    write(primary / "tail.safetensors", 3)
    write(linked / "tail.safetensors", 3, flip=size - 5)
    write(primary / "middle.safetensors", 4)
    write(linked / "middle.safetensors", 4, flip=size // 2 + 7)
    write(primary / "same.safetensors", 5)
    write(linked / "same.safetensors", 5)
    write(second / "same.safetensors", 5)
    write(primary / "longer.safetensors", 7)
    (linked / "longer.safetensors").write_bytes(bytes([7]) * size + b"more")
    (primary / "small.safetensors").write_bytes(b"s" * 1024)
    (linked / "small.safetensors").write_bytes(b"s" * 1024)
    write(tmp_path / "dot.safetensors", 6)  # the "." root is the working directory (tmp_path)
    write(primary / "dot.safetensors", 6)
    linked_roots = {str(linked), str(second), str(joined)}
    linked_apps = [str(linked.parent), str(second.parent), str(joined.parent)]

    class _Files:
        def get_checkpoints_paths(self):
            return [str(primary), str(linked), str(second), str(joined), "."]

        def is_external_root(self, root):
            return os.path.abspath(root) in linked_roots

        def is_protected_path(self, path):
            candidate = os.path.abspath(path)
            return any(os.path.commonpath([candidate, app]) == app for app in linked_apps)

    monkeypatch.setattr(server.wgp, "fl", _Files(), raising=False)
    monkeypatch.setitem(server.wgp.server_config, "loras_root", str(loras))

    scan = server.client.get("/api/v1/storage/duplicates").json()
    assert [(row["rel_path"], row["linked_install"]) for row in scan["duplicates"]] == [
        ("same.safetensors", "install-b"),
    ]
    assert sorted((row["rel_path"], row["linked_install"]) for row in scan["conflicts"]) == [
        ("longer.safetensors", "install-b"), ("middle.safetensors", "install-b"), ("tail.safetensors", "install-b"),
    ]
    # hard + sym through install-b; every primary name (the small one too) through the joined root.
    assert scan["shared_via_link"] == 2 + 8
    assert scan["total_reclaimable_bytes"] == size

    refused = (409, {"detail": "No identical linked copy exists (anymore) — refusing to delete the only copy."})
    for name in ("hard.safetensors", "sym.safetensors", "tail.safetensors", "middle.safetensors", "longer.safetensors"):
        response = server.client.post("/api/v1/storage/duplicates/reclaim", json={"path": str(primary / name)})
        assert (response.status_code, response.json()) == refused, name
        assert (primary / name).is_file() and (linked / name).exists(), name

    monkeypatch.setitem(server.wgp.server_config["services"], "storage_allow_linked_removal", True)
    recycled = []
    monkeypatch.setattr(win_safe_files, "recycle_file", lambda target: recycled.append(target) or True)
    for name in ("hard.safetensors", "sym.safetensors", "middle.safetensors", "longer.safetensors"):
        response = server.client.post("/api/v1/storage/duplicates/remove-linked", json={"path": str(linked / name)})
        assert response.status_code == 409, name
    response = server.client.post(
        "/api/v1/storage/duplicates/remove-linked", json={"path": str(primary / "same.safetensors")},
    )
    assert (response.status_code, response.json()) == (400, {
        "detail": "That file is not in a linked install — use Reclaim for HocusPocus Lab's own copies.",
    })
    response = server.client.post(
        "/api/v1/storage/duplicates/remove-linked", json={"path": str(linked / "same.safetensors")},
    )
    assert response.status_code == 200
    assert response.json()["surviving_copy"] == str(primary / "same.safetensors")
    assert recycled == [str(linked / "same.safetensors")]
    assert (primary / "hard.safetensors").read_bytes()[:1] == b"\x01"


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
    if importlib.util.find_spec("librosa") is not None:  # the analysis needs librosa; the CI core install has none and answers 501
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
