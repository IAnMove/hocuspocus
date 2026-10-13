"""Gallery listing, file serving and metadata over a few outputs made in the test."""
from __future__ import annotations

from tests.characterization import media

IMAGE = "2026-01-02-10h00m00s_seed7_golden_image.png"
CLIP = "2026-01-02-10h05m00s_seed9_golden_clip.mp4"
SONG = "golden_song.wav"
# Encoded sizes change with the ffmpeg and Pillow versions, not with the server.
SIZES = ("size",)


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


def test_gallery_listing(server, golden) -> None:
    _outputs(server)
    server.check(golden, "list", "GET", "/api/v1/outputs", mask=SIZES)
    server.check(golden, "list page", "GET", "/api/v1/outputs", mask=SIZES, params={"limit": 1, "offset": 1})
    server.check(golden, "list images", "GET", "/api/v1/outputs", mask=SIZES, params={"media_type": "image"})
    server.check(golden, "list search", "GET", "/api/v1/outputs", mask=SIZES, params={"search": "blue"})
    server.check(golden, "list oldest first", "GET", "/api/v1/outputs", mask=SIZES, params={"order": "oldest"})
    server.client.post(f"/api/v1/favorites/{CLIP}")
    server.check(golden, "list favorites", "GET", "/api/v1/outputs", mask=SIZES, params={"favorites_only": "true"})
    media.image(server.root / "uploads" / "golden_upload.png")
    media.stamp(server.root / "uploads" / "golden_upload.png", 10)
    server.check(golden, "list uploads view", "GET", "/api/v1/outputs", mask=SIZES, params={"workspace": "__uploads__"})


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
