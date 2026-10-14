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
