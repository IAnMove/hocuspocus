"""An inpainted picture keeps the transparency of its source (``studio_image_alpha_restore``).

Sol, 2026-10-15: a PNG with a transparent background inpainted through ``generation.image`` came back with that background as opaque
grey. The app flattens the guide onto grey before the engine, the engine returns plain RGB; the source's alpha is put back afterwards.
Every picture here is a few pixels made with Pillow: nothing reads a model.
"""
import hashlib
import io
import struct
import zlib
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from services.studio_image_alpha import FLATTENED_DIR, alpha_plane_path, flattened
from services.studio_image_alpha_restore import restore_inpaint_alpha

WIDTH, HEIGHT = 24, 16
RED, BLUE = (200, 40, 40), (0, 0, 255)


def _alpha() -> np.ndarray:
    """The left third is transparent, the column next to it half transparent, the rest opaque."""
    alpha = np.full((HEIGHT, WIDTH), 255, np.uint8)
    alpha[:, :8], alpha[:, 8] = 0, 100
    return alpha


def _mask_array() -> np.ndarray:
    """White where the edit is: a block that starts in the transparent area and runs into the opaque one."""
    mask = np.zeros((HEIGHT, WIDTH), np.uint8)
    mask[4:10, 4:14] = 255
    return mask


def _folder(tmp_path: Path, name: str) -> Path:
    folder = tmp_path / name
    folder.mkdir()
    return folder


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Case:
    """A source with transparency, its flattened guide, a mask, and the engine's output: the flattened guide with the mask painted blue."""

    def __init__(self, tmp_path: Path, *, alpha=None, mask=None, output="out.png", output_size=None, mask_with_alpha=False):
        self.folder, self.out_dir = tmp_path, tmp_path / "outputs"
        self.out_dir.mkdir()
        self.alpha = _alpha() if alpha is None else alpha
        rgba = np.dstack([np.full((*self.alpha.shape, 3), RED, np.uint8), self.alpha])
        source = tmp_path / "source.png"
        Image.fromarray(rgba).save(source)
        self.guide = flattened(str(source), "image_guide", _digest(source), str(tmp_path))
        self.mask_array = _mask_array() if mask is None else mask
        mask_path = tmp_path / "mask.png"
        if mask_with_alpha:
            Image.fromarray(np.dstack([np.full((*self.mask_array.shape, 3), 255, np.uint8), self.mask_array])).save(mask_path)
            self.mask = flattened(str(mask_path), "image_mask", _digest(mask_path), str(tmp_path))
        else:
            Image.fromarray(self.mask_array).save(mask_path)
            self.mask = str(mask_path)
        engine = np.asarray(Image.open(self.guide).convert("RGB")).copy()
        engine[self.mask_array > 0] = BLUE
        self.engine = engine
        picture = Image.fromarray(engine)
        if output_size:
            picture = picture.resize(output_size, Image.Resampling.NEAREST)
        self.name = output
        self.path = self.out_dir / output
        picture.save(self.path)
        self.job = {"params": {"image_guide": self.guide, "image_mask": self.mask, "video_prompt_type": "VAG", "image_mode": 1}}

    def restore(self):
        return restore_inpaint_alpha(self.job, str(self.out_dir), self.name)

    def result(self) -> np.ndarray:
        with Image.open(self.path) as picture:
            assert picture.mode == "RGBA"
            return np.asarray(picture)


def test_outside_the_mask_the_source_alpha_is_kept_exactly_and_the_edited_region_is_opaque(tmp_path):
    case = Case(tmp_path)
    note = case.restore()
    assert note == {"status": "restored", "from": "image_guide", "mask": "image_mask"}
    alpha = case.result()[..., 3]
    inside = case.mask_array > 0
    assert (alpha[~inside] == _alpha()[~inside]).all(), "the transparent area and the soft edge outside the mask are the source's, exactly"
    assert (alpha[inside] == 255).all(), "what the edit painted over the transparent area is opaque"
    assert alpha[0, 0] == 0 and alpha[0, 8] == 100 and alpha[12, 20] == 255


def test_the_grey_the_flattening_mixed_into_a_soft_edge_is_taken_out_again_and_the_edit_keeps_its_colour(tmp_path):
    case = Case(tmp_path)
    case.restore()
    picture = case.result()
    assert np.abs(picture[0:4, 8, :3].astype(int) - RED).max() <= 3, "the half transparent column is the source's red again, not grey-mixed"
    assert (picture[4:10, 4:14, :3] == BLUE).all(), "the engine's own colour inside the mask is kept"
    assert (picture[12:, 16:, :3] == RED).all(), "an opaque pixel outside the mask is untouched"


def test_a_soft_mask_blends_the_alpha_between_the_sources_and_opaque(tmp_path):
    mask = _mask_array()
    mask[4:10, 4:6] = 128
    case = Case(tmp_path, mask=mask)
    case.restore()
    alpha = case.result()[..., 3]
    assert alpha[5, 4] == 0 + round(255 * 128 / 255), "half the mask: half way between a transparent source pixel and opaque"
    assert alpha[5, 8] == 255


def test_a_mask_with_alpha_flattened_onto_black_is_read_from_its_copy(tmp_path):
    case = Case(tmp_path, mask_with_alpha=True)
    assert Path(case.mask).parent.name == FLATTENED_DIR
    case.restore()
    assert (case.result()[..., 3][case.mask_array > 0] == 255).all()


@pytest.mark.parametrize("size", [(48, 32), (12, 8)])
def test_an_output_of_the_sources_shape_but_another_size_gets_the_alpha_at_its_own_size(tmp_path, size):
    case = Case(tmp_path, output_size=size)
    case.restore()
    alpha = case.result()[..., 3]
    assert alpha.shape == (size[1], size[0])
    assert alpha[0, 0] == 0 and alpha[-1, -1] == 255, "transparent left third and opaque right side, at the output's size"


def test_an_output_of_another_shape_is_left_as_the_engine_wrote_it(tmp_path):
    case = Case(tmp_path, output_size=(24, 24))
    before = _digest(case.path)
    assert case.restore() == {"status": "skipped", "reason": "size_mismatch"}
    assert _digest(case.path) == before


def test_a_jpeg_output_cannot_carry_alpha_and_is_left_alone_with_the_reason_in_the_note(tmp_path):
    case = Case(tmp_path, output="out.jpg")
    before = _digest(case.path)
    assert case.restore() == {"status": "skipped", "reason": "output_format_without_alpha"}
    assert _digest(case.path) == before


def test_a_picture_that_already_has_alpha_is_not_touched(tmp_path):
    case = Case(tmp_path)
    Image.fromarray(np.dstack([case.engine, _alpha()])).save(case.path)
    before = _digest(case.path)
    assert case.restore() == {"status": "skipped", "reason": "output_already_has_alpha"}
    assert _digest(case.path) == before


def test_a_source_without_transparency_an_outpaint_or_an_edit_without_a_mask_changes_nothing(tmp_path):
    opaque = Case(_folder(tmp_path, "opaque"), alpha=np.full((HEIGHT, WIDTH), 255, np.uint8))
    before = _digest(opaque.path)
    assert opaque.restore() is None and _digest(opaque.path) == before, "the app's own compose writes an alpha channel even when opaque"
    for change in ({"video_guide_outpainting": "0 0 10 10"}, {"image_mask": ""}, {"video_prompt_type": "V"}, {"image_guide": "photo.png"},
                   {"image_mask": ["a.png", "b.png"]}):
        case = Case(_folder(tmp_path, "case" + hashlib.sha256(repr(change).encode()).hexdigest()[:6]))
        case.job["params"].update(change)
        before = _digest(case.path)
        assert case.restore() is None and _digest(case.path) == before, change


def test_the_picture_is_restored_once_the_sidecar_is_written_more_than_once_and_keeps_its_text(tmp_path):
    case = Case(tmp_path)
    first = case.restore()
    once = _digest(case.path)
    assert case.restore() == first and _digest(case.path) == once, "the second sidecar write finds the note on the job and the file as it was"
    assert case.job["_alpha_restored"] == {case.name: first}
    # a fresh job on the same file sees alpha already there and does not run the grey out of the colours a second time
    again = {"params": case.job["params"]}
    assert restore_inpaint_alpha(again, str(case.out_dir), case.name)["reason"] == "output_already_has_alpha" and _digest(case.path) == once


def test_the_pngs_text_chunks_survive(tmp_path):
    case = Case(tmp_path)
    from PIL import PngImagePlugin
    info = PngImagePlugin.PngInfo()
    info.add_text("parameters", "a red barn, seed 7")
    Image.fromarray(case.engine).save(case.path, pnginfo=info)
    case.restore()
    with Image.open(case.path) as picture:
        assert picture.text["parameters"] == "a red barn, seed 7" and picture.mode == "RGBA"


def test_a_webp_output_is_restored_losslessly(tmp_path):
    case = Case(tmp_path, output="out.webp")
    assert case.restore()["status"] == "restored"
    assert (case.result()[..., 3][:, :8][case.mask_array[:, :8] == 0] == 0).all()


def test_a_file_that_is_not_a_picture_or_not_readable_stays_and_never_fails_the_job(tmp_path):
    case = Case(tmp_path)
    case.path.write_bytes(b"not a png at all")
    note = case.restore()
    assert note["status"] == "skipped" and note["reason"].startswith("unreadable") and case.path.read_bytes() == b"not a png at all"
    video = Case(_folder(tmp_path, "video"))
    assert restore_inpaint_alpha(video.job, str(video.out_dir), "clip.mp4") is None, "only pictures"
    assert not [item for item in video.out_dir.iterdir() if item.suffix == ".tmp"]


@pytest.mark.parametrize("mode", ["P", "L", "LA", "I;16", "RGBA"])
def test_odd_engine_output_modes_degrade_gracefully(tmp_path, mode):
    case = Case(tmp_path)
    picture = Image.fromarray(case.engine)
    odd = picture.convert("L").convert(mode) if mode in ("LA", "L", "P") else (
        Image.fromarray(np.full((HEIGHT, WIDTH), 30000, np.uint16)) if mode == "I;16" else picture.convert("RGBA"))
    odd.save(case.path)
    note = case.restore()
    assert note is None or note["status"] in ("restored", "skipped")
    with Image.open(case.path) as after:
        after.load()  # always a readable picture, restored or as the engine wrote it


def _png16(width: int, height: int, colour_type: int, channels: int) -> bytes:
    """A 16 bit PNG written by hand (Pillow writes none with alpha)."""
    raw = b"".join(b"\x00" + (b"\x80\x00" * (channels - 1) + b"\x00\x00") * width for _ in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 16, colour_type, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


@pytest.mark.parametrize("name,colour_type,channels", [("rgba16", 6, 4), ("la16", 4, 2)])
def test_a_16_bit_source_with_alpha_is_flattened_and_restored_as_8_bit(tmp_path, name, colour_type, channels):
    source = tmp_path / f"{name}.png"
    source.write_bytes(_png16(WIDTH, HEIGHT, colour_type, channels))
    guide = flattened(str(source), "image_guide", _digest(source), str(tmp_path))
    plane = alpha_plane_path(guide)
    assert plane is not None and Image.open(plane).mode == "L" and Image.open(plane).getextrema() == (0, 0), "fully transparent 16 bit alpha"
    out_dir = tmp_path / "outputs"
    out_dir.mkdir()
    Image.new("RGB", (WIDTH, HEIGHT), (127, 127, 127)).save(out_dir / "out.png")
    mask = np.zeros((HEIGHT, WIDTH), np.uint8)
    mask[2:6, 2:6] = 255
    Image.fromarray(mask).save(tmp_path / "mask.png")
    job = {"params": {"image_guide": guide, "image_mask": str(tmp_path / "mask.png"), "video_prompt_type": "VAG"}}
    assert restore_inpaint_alpha(job, str(out_dir), "out.png")["status"] == "restored"
    alpha = np.asarray(Image.open(out_dir / "out.png"))[..., 3]
    assert alpha[2:6, 2:6].min() == 255 and alpha.sum() == 255 * 16


def test_a_palette_or_colour_key_source_keeps_the_transparency_it_had(tmp_path):
    palette = Image.new("P", (WIDTH, HEIGHT), 0)
    palette.putpalette([200, 40, 40, 255, 255, 255] + [0] * 762)
    palette.paste(1, (8, 0, WIDTH, HEIGHT))
    path = tmp_path / "palette.png"
    palette.save(path, transparency=0)  # index 0 is the clear one: the left of the picture ... and nothing else
    guide = flattened(str(path), "image_guide", _digest(path), str(tmp_path))
    alpha = np.asarray(Image.open(alpha_plane_path(guide)))
    assert (alpha[:, :8] == 0).all() and (alpha[:, 8:] == 255).all()
    keyed = tmp_path / "keyed.png"
    Image.new("RGB", (4, 4), (255, 255, 255)).save(keyed, transparency=(255, 255, 255))
    assert Image.open(alpha_plane_path(flattened(str(keyed), "image_guide", _digest(keyed), str(tmp_path)))).getextrema() == (0, 0)
