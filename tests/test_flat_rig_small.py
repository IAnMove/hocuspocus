"""Small faces: the landmarks' head pass, the warp worked on the face enlarged and put back, readable openings."""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")
from PIL import Image, ImageDraw

from services import face_enlarge, face_landmarks, flat_rig_preview, flat_rig_warp
from services.character_kit_library import patch_character_kit
from services.flat_rig import _outlined_eyes, rig_character
from services.flat_rig_base import STATES

SKIN, LINE, BEARD, STRAND = (205, 140, 70, 255), (25, 15, 10, 255), (70, 45, 28, 255), (150, 118, 84, 255)
MOUTH_Y, MOUTH_X = 131, (138, 162)


def _figure() -> Image.Image:
    """A full figure with a small graphic-novel head (84 px): white eyes, a nose, a pen-line mouth 24 px wide and a
    short beard of dark hair with light strands, on a coat."""
    image = Image.new("RGBA", (300, 700), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((80, 170, 220, 690), fill=(40, 50, 90, 255))
    draw.ellipse((108, 58, 192, 170), fill=SKIN)
    for x0 in (124, 156):
        draw.ellipse((x0, 92, x0 + 20, 104), fill=(255, 255, 255, 255), outline=LINE, width=2)
        draw.ellipse((x0 + 7, 94, x0 + 13, 102), fill=LINE)
    draw.polygon([(148, 106), (154, 120), (145, 121)], fill=LINE)
    draw.rectangle((132, 142, 168, 168), fill=BEARD)
    for x in range(134, 168, 4):
        draw.line((x, 145, x, 166), fill=STRAND, width=1)
    draw.line((MOUTH_X[0], MOUTH_Y, MOUTH_X[1], MOUTH_Y), fill=LINE, width=2)
    return image


def _lips(low=0.0):
    x0, x1 = MOUTH_X
    upper = [[x0 + (x1 - x0) * i / 6, MOUTH_Y - 3 * np.sin(np.pi * i / 6) + low] for i in range(1, 6)]
    lower = [[x1 - (x1 - x0) * i / 6, MOUTH_Y + 4 * np.sin(np.pi * i / 6) + low] for i in range(1, 6)]
    return [[x0, MOUTH_Y + low], *upper, [x1, MOUTH_Y + low], *lower]


def _pixels(image):
    return np.array(image.convert("RGBA"))


def _composite(base: np.ndarray, patch: Image.Image, box) -> np.ndarray:
    out = Image.fromarray(base)
    out.alpha_composite(patch, box[:2])
    return np.array(out)


# Mapping ----------------------------------------------------------------------

def test_points_map_into_the_enlarged_view_and_back():
    points = np.array([[3.0, 4.0], [10.25, 7.5], [-1.0, 0.0]])
    for k in (1, 2, 5):
        view = face_enlarge.to_view(points, (2, 3), k)
        assert np.allclose(face_enlarge.to_image(view, (2, 3), k), points)
        scale, dx, dy = face_enlarge.view_affine((2, 3), k)
        assert np.allclose(view, points * scale + [dx, dy])
    # A pose pixel's centre is the centre of its k×k pixels in the view.
    pixels = np.zeros((20, 20, 3), np.uint8)
    pixels[4:7, 5:8] = 255
    big = face_enlarge.enlarge(pixels, 2, 2, 12, 12, 4)
    ys, xs = np.nonzero(big[..., 0] > 127)
    assert np.allclose([xs.mean(), ys.mean()], face_enlarge.to_view([6, 5], (2, 2), 4))


def test_an_enlarged_cutout_keeps_its_outline_colour():
    rgba = np.zeros((10, 10, 4), np.uint8)
    rgba[:, :5] = (220, 30, 20, 255)
    rgba[:, 5:] = (0, 255, 0, 0)        # keyed-out green behind the outline
    big = face_enlarge.enlarge(rgba, 0, 0, 10, 10, 4)
    seen = big[..., 3] > 16
    assert seen.any() and big[..., 1][seen].max() < 40, "the screen colour never bleeds into the figure's edge"


def test_a_mouth_line_survives_the_round_trip_through_the_view():
    line = flat_rig_warp.MouthLine(np.array([0.004, -1.1, 190.0]), 130.0, 170.0, True, "landmarks")
    big = line.affine(*face_enlarge.view_affine((120, 110), 5))
    back = big.affine(*face_enlarge.image_affine((120, 110), 5))
    xs = np.linspace(125, 175, 11)
    assert np.allclose(back.y(xs), line.y(xs)) and np.isclose(back.x0, line.x0) and np.isclose(back.width, line.width)
    view = face_enlarge.to_view(np.stack([xs, line.y(xs)], 1), (120, 110), 5)
    assert np.allclose(big.y(view[:, 0]), view[:, 1]), "the same points in the view's pixels"


def test_put_back_keeps_unmoved_pixels_and_copies_whole_pixel_moves():
    rng = np.random.default_rng(3)
    rgba = rng.integers(0, 255, (40, 40, 4)).astype(np.uint8)
    rgba[..., 3] = 255
    box, k = (8, 6, 16), 3
    side = box[2] * k
    big = face_enlarge.enlarge(rgba, box[0], box[1], box[2], box[2], k)
    rgb, alpha = big[..., :3].astype(np.float32), big[..., 3].astype(np.float32)
    dy = np.zeros((side, side), np.float32)
    dy[24:, :] = 2 * k                      # pose rows 8 and down move two pixels, whole
    dy[24:27, :] = 0.5                       # but pose row 8 only half a pixel
    changed = dy != 0
    rgb[changed] = 0                         # the enlarged state is black where it moved
    patch = face_enlarge.put_back(rgba, box, k, rgb, alpha, changed, dy, np.ones_like(changed), np.ones((16, 16)))
    x0, y0, size = box
    crop = rgba[y0:y0 + size, x0:x0 + size]
    assert (patch[:8] == crop[:8]).all(), "nothing moved: the drawing's own pixels"
    assert (patch[9:, :, :3] == rgba[y0 + 9 - 2:y0 + size - 2, x0:x0 + size, :3]).all(), "moved whole: copied, not resampled"
    assert (patch[8, :, :3] == 0).all(), "a part-pixel move: the enlarged state, averaged"


# The head pass ----------------------------------------------------------------

def _head_points(cx, cy, head):
    """68 face points of a head ``head`` px across centred at (cx, cy): jaw, brows, nose, eyes and lips."""
    points = np.zeros((68, 2))
    angles = np.linspace(np.pi, 0, 17)
    points[0:17] = np.stack([cx + head / 2 * np.cos(angles), cy + head / 2 * np.sin(angles) * 0.9 + head * 0.05], 1)
    points[17:27] = np.stack([np.linspace(cx - head * 0.35, cx + head * 0.35, 10), np.full(10, cy - head * 0.45)], 1)
    points[27:68] = (cx, cy)
    return points


class _Fake:
    """The DWPose model as the head pass sees it: the whole pass finds a head, the boxed pass finds a red dot."""

    def __init__(self, head, whole_score=0.95, head_score=0.8):
        self.head, self.whole_score, self.head_score, self.views = head, whole_score, head_score, []

    def whole(self, model, bgr):
        return _head_points(150.0, 220.0, self.head), np.full(68, self.whole_score)

    def pose(self, model, box, view):
        self.views.append((view.shape, box))
        ys, xs = np.nonzero((view[..., 2] > 200) & (view[..., 1] < 60))
        return np.tile([[xs.mean(), ys.mean()]], (133, 1)), np.full(133, self.head_score)


def _dot_image():
    image = Image.new("RGBA", (420, 900), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle((150, 240, 152, 242), fill=(255, 0, 0, 255))
    return image


@pytest.mark.parametrize("head, enlarged", [(80.0, 1), (40.0, 2)])
def test_a_small_head_is_read_alone_and_its_points_land_back_on_the_pose(monkeypatch, head, enlarged):
    fake = _Fake(head)
    monkeypatch.setattr(face_landmarks, "_wholebody", lambda: object())
    monkeypatch.setattr(face_landmarks, "_whole_pass", fake.whole)
    monkeypatch.setattr(face_landmarks, "_pose", fake.pose)
    found = face_landmarks.detect(_dot_image())
    assert found["face"] == {"size": "small", "head": head, "pass": "head"}
    assert np.allclose(np.asarray(found["mouth"]), [151.0, 241.0], atol=0.05), "the dot, in pose pixels"
    (shape, box), = fake.views
    box_side = (box[2] - box[0]) / enlarged
    assert abs(box_side - head * face_landmarks.HEAD_VIEW) < 0.01 and shape[1] >= face_landmarks.MODEL_WIDTH
    assert abs(shape[1] / enlarged - head * face_landmarks.HEAD_VIEW * face_landmarks.PADDING) < 6, \
        "the model sees the padded box, enlarged when it is smaller than its input"


def test_a_large_head_keeps_the_whole_pass_unless_it_was_unsure(monkeypatch):
    monkeypatch.setattr(face_landmarks, "_wholebody", lambda: object())
    sure = _Fake(240.0)
    monkeypatch.setattr(face_landmarks, "_whole_pass", sure.whole)
    monkeypatch.setattr(face_landmarks, "_pose", sure.pose)
    assert face_landmarks.detect(_dot_image())["face"] == {"size": "normal", "head": 240.0, "pass": "whole"}
    assert not sure.views, "a bust the whole pass is sure of is not read again"
    unsure = _Fake(240.0, whole_score=0.4)
    monkeypatch.setattr(face_landmarks, "_whole_pass", unsure.whole)
    monkeypatch.setattr(face_landmarks, "_pose", unsure.pose)
    assert face_landmarks.detect(_dot_image())["face"]["pass"] == "head", "surer alone: a bust's beard taken for its mouth"
    guessed = _Fake(80.0, head_score=0.2)
    monkeypatch.setattr(face_landmarks, "_whole_pass", guessed.whole)
    monkeypatch.setattr(face_landmarks, "_pose", guessed.pose)
    assert face_landmarks.detect(_dot_image())["face"]["pass"] == "whole", "a head pass that only guessed is not kept"


# Size and readable openings -----------------------------------------------------

def test_the_small_face_threshold_and_how_much_it_is_enlarged():
    assert face_enlarge.SMALL_HEAD == 160
    assert face_enlarge.factor(159.9) >= 2 and face_enlarge.factor(160) == 1 and face_enlarge.factor(None) == 1
    assert face_enlarge.factor(84) == 5 and face_enlarge.factor(40) == face_enlarge.MOST
    assert face_enlarge.size_class(84) == "small" and face_enlarge.size_class(260) == "normal"
    k, face = flat_rig_warp.face_scale({"lips": _lips(), "face": {"head": 84.0, "pass": "head"}}, None)
    assert k == 5 and face == {"size": "small", "head": 84, "pass": "head", "upscale": 5}
    # Without landmarks the head is guessed from the mouth: 24 px wide, a 72 px head.
    k, face = flat_rig_warp.face_scale({"point": (150, 131), "width": 24.0}, None)
    assert face["size"] == "small" and face["head"] == 72 and face["pass"] is None and k == face["upscale"] > 1
    assert flat_rig_warp.face_scale({"point": (150, 131), "width": 80.0}, None)[0] == 1
    # A mouth hint dragged across the whole image never enlarges a view past MAX_VIEW pixels.
    k, _face = flat_rig_warp.face_scale({"point": (150, 131), "width": 890.0, "face": {"head": 84.0}}, None)
    assert k == 1 and face_enlarge.factor(84, 1000) == 4


def test_small_mouths_open_far_enough_to_read_and_busts_are_untouched():
    for state, (drop, share, _pinch, _teeth) in flat_rig_warp.WARP_STATES.items():
        for width in (56, 70, 90, 140):
            assert flat_rig_warp.drop_pixels(state, width) == round(drop * width), (state, width)
        if drop <= 0 or not share:
            continue
        for width in (12, 18, 24, 30):
            pixels = flat_rig_warp.drop_pixels(state, width)
            assert pixels >= round(drop * width), "never less than its own drop"
            assert pixels <= round(drop * width * flat_rig_warp.OVERDRAW), "a tiny face does not shout"
    assert flat_rig_warp.drop_pixels("wide", 24) == flat_rig_warp.READABLE
    assert flat_rig_warp.drop_pixels("small", 24) >= 2 and flat_rig_warp.drop_pixels("bite", 24) >= 2


# The enlarged warp ---------------------------------------------------------------

def test_the_line_is_snapped_on_the_enlarged_face_and_mapped_back():
    pixels = _pixels(_figure())
    seeds = {"lips": np.asarray(_lips(low=2.5))}
    plain = flat_rig_warp.rig_line(pixels, seeds, None)
    enlarged = flat_rig_warp.rig_line(pixels, seeds, None, k=5)
    for line in (plain, enlarged):
        assert line.found and line.source == "landmarks"
        assert abs(line.width - (MOUTH_X[1] - MOUTH_X[0])) < 0.5 and abs(line.centre[0] - sum(MOUTH_X) / 2) < 0.5
    # The 2 px pen line covers rows 131 and 132: its middle is 131.5. Snapped on the enlarged face the line lands
    # between the rows; on the pose's own pixels only on one of them.
    middle = MOUTH_Y + 0.5
    assert abs(enlarged.centre[1] - middle) <= 0.2 < abs(plain.centre[1] - middle) <= 0.51


def test_enlarged_patches_lie_on_the_same_square_and_closed_is_the_drawing():
    pixels = _pixels(_figure())
    line = flat_rig_warp.rig_line(pixels, {"lips": np.asarray(_lips())}, None, k=4)
    box, plain = flat_rig_warp.pose_patches(pixels, line, k=1)
    same_box, enlarged = flat_rig_warp.pose_patches(pixels, line, k=4)
    assert same_box == box, "the anchor does not move with the enlargement"
    x0, y0, side = box
    crop = pixels[y0:y0 + side, x0:x0 + side]
    assert (_composite(pixels, enlarged["closed"], box) == pixels).all(), "closed is the drawing unchanged"
    edge = np.zeros((side, side), bool)
    edge[:1], edge[-1:], edge[:, :1], edge[:, -1:] = True, True, True, True
    lum = lambda a: a[..., :3].astype(float) @ [0.299, 0.587, 0.114]
    for state in STATES:
        patch = np.array(enlarged[state])
        assert patch.shape == (side, side, 4) and (patch[..., 3][edge] <= 10).all(), state
        ring = np.zeros((side, side), bool)
        ring[:int(side * 0.06)] = ring[-int(side * 0.06):] = True
        shown = ring & (patch[..., 3] > 0)
        assert (patch[..., :3][shown] == crop[..., :3][shown]).all(), f"{state}: unmoved where it fades"
        if state in ("closed", "pressed"):
            continue
        # The opening is where the plain warp opens it, its edges smoother.
        big, small = (_composite(pixels, patches[state], box) for patches in (enlarged, plain))
        opened = [(lum(image) < 60) & (lum(pixels) > 100) for image in (big, small)]
        overlap = (opened[0] & opened[1]).sum() / max(1, (opened[0] | opened[1]).sum())
        assert opened[0].sum() > 20 and overlap > 0.6, (state, overlap)
    wide = _composite(pixels, enlarged["wide"], box)
    opened = (lum(wide) < 60) & (lum(pixels) > 100)
    opened[142:] = False                     # lower down the beard moving down darkens its light strands
    ys, xs = np.nonzero(opened)
    assert xs.min() >= MOUTH_X[0] - 1 and xs.max() <= MOUTH_X[1] + 1, "between the corners"
    assert ys.max() - MOUTH_Y >= flat_rig_warp.READABLE - 2, "deep enough to read when the figure is drawn small"


def test_the_square_holds_the_deeper_drop_down_to_where_the_jaw_is_still():
    line = flat_rig_warp.MouthLine(np.array([0.0, 131.0]), 138.0, 162.0)
    x0, y0, side = flat_rig_warp.patch_box(line)
    field = flat_rig_warp._field(line, (x0, y0, side), "wide")
    fade = int(side * flat_rig_warp.FEATHER) + 1
    assert np.abs(field.dy[-fade:]).max() < 0.05, "nothing moves where the patch fades out"


def test_a_highlight_beside_a_landmark_eye_is_closed_with_it():
    rgb = np.zeros((60, 80, 3), np.uint8)
    rgb[:] = (20, 20, 20)                     # an eye in a flat black shadow
    rgb[21:23, 40:42] = 250                   # its highlight, two pixels over the outline the points give
    alpha = np.full((60, 80), 255, np.uint8)
    outline = np.array([[35, 25], [39, 24], [43, 24], [47, 25], [43, 27], [39, 27]], float)
    _box, mask = _outlined_eyes(rgb, alpha, [outline])
    assert mask[21:23, 40:42].all() and mask[25, 41], "covered with the outline"
    assert not mask[:18].any(), "light farther off is not the eye's"


def test_a_rig_reports_each_poses_face_size_and_enlargement(tmp_path, monkeypatch):
    folder = tmp_path / "cast"
    folder.mkdir()
    _figure().save(folder / "hero.png")
    asset = {"id": "hero-base", "name": "hero", "source": "/api/v1/file/hero.png?workspace=cast", "kind": "image",
             "alphaStatus": "transparent", "reviewState": "approved"}
    patch_character_kit(str(folder), "hero", {"id": "hero", "name": "Hero", "style": "cutout", "base": asset, "poses": {},
                                              "mouth": {}, "eyes": {}, "anchors": {}}, base_revision=0)
    eyes = [[[126 + i * 3, 98] for i in range(6)], [[158 + i * 3, 98] for i in range(6)]]
    monkeypatch.setattr(face_landmarks, "detect", lambda image: {
        "eyes": eyes, "mouth": _lips(), "scores": {"eyes": 0.9, "mouth": 0.9},
        "face": {"size": "small", "head": 84.0, "pass": "head"}})
    rigged = rig_character(str(folder), "cast", "hero", base_revision=1, style={"mouthStyle": "warp"})
    pose = rigged["poses"]["base"]
    assert pose["faceSize"] == {"size": "small", "head": 84, "pass": "head", "upscale": 5}
    assert pose["mouthLine"]["faceSize"] == pose["faceSize"] and pose["mouthLine"]["found"]
    assert rigged["character"]["provenance"][-1]["mouthLines"]["base"]["faceSize"]["upscale"] == 5
    kit = rigged["character"]
    image = _pixels(Image.open(folder / kit["base"]["source"].split("/api/v1/file/")[1].split("?")[0]))
    anchor = kit["anchors"]["base"]["mouth"]
    patch = Image.open(folder / kit["anchors"]["base"]["mouthSources"]["closed"].split("/api/v1/file/")[1].split("?")[0])
    edge = max(image.shape[:2])
    x0 = image.shape[1] / 2 + anchor["offsetX"] * edge / 100 - patch.width / 2
    y0 = image.shape[0] / 2 + anchor["offsetY"] * edge / 100 - patch.width / 2
    assert (_composite(image, patch, (round(x0), round(y0))) == image).all(), "closed lies exactly on its pose"
    assert (folder / rigged["review"].split("/api/v1/file/")[1].split("?")[0]).is_file()
    # The Face Rig preview warps the pose as the rig did: enlarged, at the same line.
    flat_rig_preview._CACHE.clear()
    preview = flat_rig_preview.preview_mouth(str(folder), "cast", "hero", "base", states=["closed", "wide"])
    assert preview["faceSize"] == pose["faceSize"] and preview["mouth"] == pose["mouthLine"]["mouth"]
