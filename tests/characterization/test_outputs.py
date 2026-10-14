"""Gallery listing, file serving and metadata over a few outputs made in the test."""
from __future__ import annotations

import base64
import json

from tests.characterization import media

IMAGE = "2026-01-02-10h00m00s_seed7_golden_image.png"
CLIP = "2026-01-02-10h05m00s_seed9_golden_clip.mp4"
SONG = "golden_song.wav"
# Encoded sizes change with the ffmpeg and Pillow versions, not with the server:
# the "size" field, and the same size in a thumbnail URL ("?v=<mtime>-<size>").
ENCODED = {"mask": ("size",), "replace": ((r"(\?v=\d+)-\d+", r"\1-<SIZE>"),)}


def _outputs(server) -> None:
    folder = server.outputs
    media.image(folder / IMAGE)
    media.sidecar(folder / IMAGE, {
        "generation_mode": "image",
        "created_at": media.BASE_MTIME + 1,
        "params": {"prompt": "a red square", "model_type": "fake_t2v", "resolution": "8x8", "seed": 7},
    })
    media.video(folder / CLIP)
    media.sidecar(folder / CLIP, {
        "generation_mode": "video",
        "params": {"prompt": "a blue field", "model_type": "fake_t2v", "resolution": "64x36", "seed": 9},
    })
    media.sound(folder / SONG)
    for offset, name in enumerate((SONG, IMAGE, CLIP)):
        media.stamp(folder / name, offset)


# Scene file names end in six random hex digits. The clock stamp is already <TIME>.
_SCENE_FILE = {"replace": ((r"_[0-9a-f]{6}", "_<ID>"),)}
_SCENE_PREVIEW = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\npreview").decode()
_PLAZA = {"version": 1, "name": "Plaza", "layers": [], "width": 64, "height": 36, "fps": 30, "duration": 1}


def test_scene_save_answer(server, golden) -> None:
    """POST /api/v1/scenes as the full server answers it, including a URL with no workspace query."""
    server.check(
        golden, "scene save", "POST", "/api/v1/scenes",
        json={"workspace": "default", "scene": _PLAZA, "preview": _SCENE_PREVIEW},
        **_SCENE_FILE,
    )
    server.check(golden, "scene save needs version 1", "POST", "/api/v1/scenes", json={"scene": {"name": "Plaza"}})
    server.check(
        golden, "scene save needs a preview", "POST", "/api/v1/scenes",
        json={"scene": _PLAZA},
    )


def test_scene_recording_answers(server, golden, tmp_path) -> None:
    """POST /api/v1/scenes/recordings. The published URL has no workspace query."""
    server.check(
        golden, "scene recording metadata must be json", "POST", "/api/v1/scenes/recordings",
        files={"file": ("clip.webm", b"webm", "video/webm")},
        data={"metadata": "{"},
    )
    server.check(
        golden, "scene recording metadata too large", "POST", "/api/v1/scenes/recordings",
        files={"file": ("clip.webm", b"webm", "video/webm")},
        data={"metadata": "x" * (8 * 1024 * 1024 + 1)},
    )
    server.check(
        golden, "scene recording workspace must be exact", "POST", "/api/v1/scenes/recordings",
        files={"file": ("clip.webm", b"webm", "video/webm")},
        data={"metadata": json.dumps({"workspace": " client-lab ", "scene": _PLAZA})},
    )
    server.check(
        golden, "scene recording needs version 1", "POST", "/api/v1/scenes/recordings",
        files={"file": ("clip.webm", b"webm", "video/webm")},
        data={"metadata": json.dumps({"scene": {"name": "Plaza"}, "prompt": ""})},
    )
    media.need_ffmpeg()
    clip = tmp_path / "capture.mp4"
    media.video(clip, seconds=1, size="64x36", fps=30)
    server.check(
        golden, "scene recording", "POST", "/api/v1/scenes/recordings",
        files={"file": ("capture.mp4", clip.read_bytes(), "video/mp4")},
        data={"metadata": json.dumps({
            "workspace": "client-lab",
            "prompt": "harbour",
            "scene": _PLAZA,
        })},
        mask=("size",),
        **_SCENE_FILE,
    )


def test_gallery_listing(server, golden) -> None:
    _outputs(server)
    server.check(golden, "list", "GET", "/api/v1/outputs", **ENCODED)
    server.check(golden, "list page", "GET", "/api/v1/outputs", **ENCODED, params={"limit": 1, "offset": 1})
    server.check(golden, "list images", "GET", "/api/v1/outputs", **ENCODED, params={"media_type": "image"})
    server.check(golden, "list search", "GET", "/api/v1/outputs", **ENCODED, params={"search": "blue"})
    server.check(golden, "list oldest first", "GET", "/api/v1/outputs", **ENCODED, params={"order": "oldest"})
    server.client.post(f"/api/v1/favorites/{CLIP}")
    server.check(golden, "list favorites", "GET", "/api/v1/outputs", **ENCODED, params={"favorites_only": "true"})
    media.image(server.root / "uploads" / "golden_upload.png")
    media.stamp(server.root / "uploads" / "golden_upload.png", 10)
    server.check(golden, "list uploads view", "GET", "/api/v1/outputs", **ENCODED, params={"workspace": "__uploads__"})


def test_gallery_origin_result_kind_edits_and_multiclip(server, golden) -> None:
    """Origin, result kind, edits and multiclip filters, recorded before the gallery move."""
    folder = server.outputs
    media.video(folder / "harbour_multiclip.mp4")
    media.sidecar(folder / "harbour_multiclip.mp4", {
        "generation_mode": "video",
        "origin": {"actor": "wizard", "tool": "wizard", "capability": "generation.video"},
        "params": {"prompt": "harbour chapter", "model_type": "fake_t2v", "resolution": "64x36"},
    })
    media.image(folder / "retake.png")
    media.sidecar(folder / "retake.png", {
        "generation_mode": "image",
        "params": {"prompt": "a retake", "edit_sub_mode": "retake", "resolution": "8x8"},
    })
    media.stamp(folder / "harbour_multiclip.mp4", 1)
    media.stamp(folder / "retake.png", 2)
    server.check(golden, "list origin wizard", "GET", "/api/v1/outputs", **ENCODED, params={"origin": "wizard"})
    server.check(golden, "list result kind chapter", "GET", "/api/v1/outputs", **ENCODED, params={"result_kind": "chapter"})
    server.check(golden, "list edits", "GET", "/api/v1/outputs", **ENCODED, params={"edits_only": "true"})
    server.check(golden, "list multiclip", "GET", "/api/v1/outputs", **ENCODED, params={"multiclip_only": "true"})


def test_output_files_and_metadata(server, golden) -> None:
    _outputs(server)
    served = server.client.get(f"/api/v1/file/{IMAGE}")
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/png"
    assert served.content == (server.outputs / IMAGE).read_bytes()
    server.check(golden, "file missing", "GET", "/api/v1/file/not-there.png")
    server.check(golden, "file outside outputs", "GET", "/api/v1/file/..%2F..%2Fsecret.txt")
    server.check(golden, "metadata", "GET", f"/api/v1/outputs/{IMAGE}/metadata")
    server.check(golden, "metadata missing", "GET", "/api/v1/outputs/not-there.png/metadata")
    media.image(server.outputs / "plain.png")
    server.check(golden, "metadata without sidecar", "GET", "/api/v1/outputs/plain.png/metadata")


def test_output_thumbnail(server, golden) -> None:
    """A still gets a preview. A missing file and a non-media file do not."""
    media.image(server.outputs / "plain.png")
    (server.outputs / "notes.txt").write_text("notes", encoding="utf-8")
    preview = server.client.get("/api/v1/outputs/thumbnail/plain.png")
    assert preview.status_code == 200
    assert preview.headers["content-type"] in {"image/jpeg", "image/webp"}
    assert preview.content
    server.check(golden, "thumbnail missing", "GET", "/api/v1/outputs/thumbnail/missing.png")
    server.check(golden, "thumbnail not media", "GET", "/api/v1/outputs/thumbnail/notes.txt")
    server.check(golden, "thumbnail unknown size", "GET", "/api/v1/outputs/thumbnail/plain.png", params={"size": "huge"})


def test_extra_info_reads(server, golden) -> None:
    """Extra info reads saved metadata. It does not call a model on GET."""
    folder = server.outputs
    name = "notes.mp4"
    media.need_ffmpeg()
    media.video(folder / name)
    media.stamp(folder / name, 4)
    media.sidecar(folder / name, {
        "generation_mode": "video",
        "created_at": media.BASE_MTIME + 4,
        "job_id": "job-notes",
        "params": {"prompt": "a blue field", "model_type": "fake_t2v", "resolution": "64x36", "seed": 9},
    })
    media.video(folder / "silent.mp4")
    media.image(folder / "plain.png")
    server.check(golden, "extra info missing", "GET", "/api/v1/outputs/missing.mp4/extra-info")
    server.check(golden, "extra info not a video", "GET", "/api/v1/outputs/plain.png/extra-info")
    server.check(golden, "extra info no metadata", "GET", "/api/v1/outputs/silent.mp4/extra-info")
    server.check(
        golden, "extra info", "GET", f"/api/v1/outputs/{name}/extra-info",
        mask=("file_size_bytes",),
    )
    server.check(
        golden, "extra info bad language", "GET", f"/api/v1/outputs/{name}/extra-info",
        params={"language": "xx"},
    )
    server.check(
        golden, "extra info generate bad language", "POST", f"/api/v1/outputs/{name}/extra-info",
        json={"language": "xx"},
    )


def test_group_clips_and_rejoin_validation(server, golden) -> None:
    """Group membership is a sidecar scan. Rejoin refuses before any concat."""
    folder = server.outputs
    for index, clip_name in ((0, "shot_a.mp4"), (1, "shot_b.mp4")):
        (folder / clip_name).write_bytes(b"clip")
        media.sidecar(folder / clip_name, {
            "params": {
                "prompt": f"shot {index}",
                "multi_clip_info": {"group_id": "grp1", "index": index, "total": 2},
            },
        })
    (folder / "solo.mp4").write_bytes(b"solo")
    media.sidecar(folder / "solo.mp4", {
        "params": {
            "prompt": "only one",
            "multi_clip_info": {"group_id": "solo", "index": 0, "total": 1},
        },
    })
    server.check(golden, "group clips", "GET", "/api/v1/outputs/group/grp1")
    server.check(golden, "group clips missing", "GET", "/api/v1/outputs/group/missing-group")
    server.check(golden, "rejoin needs group", "POST", "/api/v1/outputs/rejoin", json={})
    server.check(golden, "rejoin missing group", "POST", "/api/v1/outputs/rejoin", json={"group_id": "nope"})
    server.check(golden, "rejoin needs two clips", "POST", "/api/v1/outputs/rejoin", json={"group_id": "solo"})


def test_move_and_delete_outputs(server, golden) -> None:
    """Move and delete stay inside the listed workspace."""
    folder = server.outputs
    (folder / "keep.png").write_bytes(b"png")
    (folder / "gone.png").write_bytes(b"bye")
    film = folder / "film"
    film.mkdir()
    (film / "hero.png").write_bytes(b"film-hero")
    (film / "hero.meta.json").write_text("{}", encoding="utf-8")
    (film / "hero.preview.png").write_bytes(b"preview")
    (film / "only-film.png").write_bytes(b"only-film")
    outside = folder.parent / "outside.png"
    outside.write_bytes(b"outside")

    server.check(golden, "move needs workspace", "POST", "/api/v1/outputs/keep.png/move", json={})
    server.check(
        golden, "move invalid workspace", "POST", "/api/v1/outputs/keep.png/move",
        json={"workspace": "../x"},
    )
    server.check(
        golden, "move already there", "POST", "/api/v1/outputs/keep.png/move",
        json={"workspace": "default"},
    )
    server.check(
        golden, "move missing", "POST", "/api/v1/outputs/missing.png/move",
        json={"workspace": "archive"},
    )
    server.check(
        golden, "move traversal", "POST", "/api/v1/outputs/../outside.png/move",
        json={"workspace": "archive"},
    )
    server.check(
        golden, "move traversal encoded", "POST",
        "/api/v1/outputs/nested%2F..%2F..%2Foutside.png/move",
        json={"workspace": "archive"},
    )
    assert outside.read_bytes() == b"outside"
    server.check(
        golden, "move cross workspace", "POST", "/api/v1/outputs/hero.png/move",
        json={"workspace": "archive", "source_workspace": "film"},
    )
    assert (folder / "archive" / "hero.png").read_bytes() == b"film-hero"
    assert (folder / "archive" / "hero.meta.json").read_text(encoding="utf-8") == "{}"
    assert (folder / "archive" / "hero.preview.png").read_bytes() == b"preview"
    assert not (film / "hero.png").exists()
    assert (folder / "keep.png").is_file()

    server.check(golden, "delete output", "DELETE", "/api/v1/outputs/gone.png")
    assert not (folder / "gone.png").exists()
    server.check(golden, "delete missing", "DELETE", "/api/v1/outputs/not-there.png")
    server.check(golden, "delete traversal", "DELETE", "/api/v1/outputs/..%2Foutside.png")
    assert outside.read_bytes() == b"outside"
    server.check(
        golden, "delete listed workspace", "DELETE", "/api/v1/outputs/only-film.png",
        params={"workspace": "film"},
    )
    assert not (film / "only-film.png").exists()
    assert (folder / "keep.png").is_file()


def test_alternative_song_validation(server, golden) -> None:
    """List, attach and delete refuse before any remount."""
    folder = server.outputs
    (folder / "empty.mp4").write_bytes(b"")
    media.image(folder / "still.png")
    server.check(golden, "alternative songs missing", "GET", "/api/v1/outputs/missing.mp4/alternative-songs")
    server.check(golden, "alternative songs not a video", "GET", "/api/v1/outputs/still.png/alternative-songs")
    server.check(golden, "alternative songs no shots", "GET", "/api/v1/outputs/empty.mp4/alternative-songs")
    server.check(
        golden, "attach song needs audio", "POST", "/api/v1/outputs/empty.mp4/alternative-songs",
        json={},
    )
    server.check(
        golden, "delete song missing video", "DELETE",
        "/api/v1/outputs/missing.mp4/alternative-songs/song-1",
    )
    server.check(
        golden, "delete song not attached", "DELETE",
        "/api/v1/outputs/empty.mp4/alternative-songs/song-1",
    )
    media.need_ffmpeg()
    media.video(folder / "mix.mp4")
    server.check(
        golden, "alternative songs list", "GET", "/api/v1/outputs/mix.mp4/alternative-songs",
        mask=("duration_seconds",),
    )
    server.check(
        golden, "attach song missing audio", "POST", "/api/v1/outputs/mix.mp4/alternative-songs",
        json={"audio_name": "nope.wav"},
    )
    server.check(
        golden, "mount song missing", "POST",
        "/api/v1/outputs/mix.mp4/alternative-songs/song-missing/mount",
        json={},
    )
