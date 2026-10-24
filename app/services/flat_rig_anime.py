"""Eyes and mouth from the optional anime landmarks, called by the flat rig.

The white-eye search and the mouth wipe stay in ``flat_rig``. This module
only decides when the 28 points replace them. A hint still wins.
"""
from __future__ import annotations

from typing import Any

import numpy as np
from PIL import Image

from services import anime_face_landmarks
from services.flat_rig_base import FlatRigError
from services.flat_rig_eyes import _outlined_eyes, find_eyes


def read_anime(image: Image.Image, crop, size, anime):
    """Anime geometry in figure pixels, and whether the installed detector failed."""
    if anime is False:
        return None, False
    raw = anime_face_landmarks.prepare(image, anime)
    if not raw:
        return None, False
    if raw.get("error"):
        return None, True
    return anime_face_landmarks.into_crop(raw, crop, size), False


def _guided_eyes(rgb: np.ndarray, alpha: np.ndarray, near, guide: dict[str, Any]):
    """The eyes at a hint as before; else at the landmarks' eyes, then by the search, then from their outlines."""
    if near is not None or "eyes" not in guide:
        return find_eyes(rgb, alpha, near=near)
    for attempt in (lambda: find_eyes(rgb, alpha, near=guide["eyes"]), lambda: find_eyes(rgb, alpha)):
        try:
            return attempt()
        except FlatRigError as error:
            if error.code != "eyes_not_found":
                raise
    return _outlined_eyes(rgb, alpha, guide["eye_outlines"])


def _white_eyes(rgb: np.ndarray, alpha: np.ndarray, guide: dict[str, Any]):
    """The white-blob eyes only (no outline fallback). None when that search finds nothing."""
    for near in ((guide["eyes"],) if "eyes" in guide else ()) + (None,):
        try:
            return find_eyes(rgb, alpha, near=near)
        except FlatRigError as error:
            if error.code != "eyes_not_found":
                raise
    return None


def anime_eyes(rgb, alpha, hinted, guide, geom):
    """A hint, else whites, else anime outlines when whites fail or disagree beyond the documented tolerance."""
    if hinted is not None or not geom or not geom.get("eye_outlines"):
        box, mask = _guided_eyes(rgb, alpha, hinted, guide)
        return box, mask, "hint" if hinted is not None else "whites", [], None
    found = _white_eyes(rgb, alpha, guide)
    outlines = geom["eye_outlines"]
    if found is None or anime_face_landmarks.eyes_disagree(found[0], geom):
        box, mask = _outlined_eyes(rgb, alpha, outlines)
        warnings = ["eyes_disagree"] if found is not None else []
        return box, mask, "landmarks", warnings, outlines
    return found[0], found[1], "whites", [], None


def _probe_mouth(find_mouth, rgb, alpha, face_eyes, screen, realistic, near):
    try:
        return find_mouth(rgb, alpha, face_eyes, screen, realistic=realistic, near=near)
    except FlatRigError as error:
        if error.code != "mouth_not_found":
            raise
        return None


def _landmark_mouth(figure, rgb, alpha, eyes_box, geom, guide):
    """The mouth on the landmark line. Nothing is wiped: the painted mark disagreed or was absent."""
    ex0, ey0, ex1, ey1 = eyes_box
    mx, my = geom["mouth"]["center"]
    band = alpha[ey1:min(alpha.shape[0], ey1 + (ey1 - ey0)), ex0:ex1] > 200
    colour = rgb[ey1:min(alpha.shape[0], ey1 + (ey1 - ey0)), ex0:ex1]
    background = np.median(colour[band], axis=0) if band.any() else np.array([200, 160, 130])
    updated = dict(guide)
    updated["mouth_width"] = float(geom["mouth"]["width"])
    updated["mouth_points"] = anime_face_landmarks.lip_contour(geom)
    updated["mouth_score"] = float(geom["score"])
    return (figure, False, False, None, None, float(mx), float(my), background), updated


def _whites_mouth(figure, rgb, alpha, eyes_box, face_eyes, style, ink, near, realistic, rig_mouth, warnings):
    pack = rig_mouth(figure, rgb, alpha, eyes_box, face_eyes, style, ink, near, realistic)
    return pack, "whites", warnings, None


def anime_mouth(figure, rgb, alpha, eyes_box, face_eyes, style, ink, hinted, guide, geom, realistic, rig_mouth, find_mouth):
    """Whites when they agree, or when the landmark mouth is not plausible.

    The landmark line is used only when the white search fails or disagrees and
    ``mouth_plausible`` is true. A hint still wins. An implausible landmark mouth
    leaves a found white mouth in place and warns ``mouth_landmarks_implausible``.
    """
    if hinted is not None or not geom or not geom.get("mouth"):
        near = hinted if hinted is not None else guide.get("mouth")
        pack = rig_mouth(figure, rgb, alpha, eyes_box, face_eyes, style, ink, near, realistic)
        return pack, "hint" if hinted is not None else "whites", [], guide
    screen = style["screen"]
    probe = _probe_mouth(find_mouth, rgb, alpha, face_eyes, screen, realistic, None)
    plausible = anime_face_landmarks.mouth_plausible(geom)
    if probe is not None and (not plausible or not anime_face_landmarks.mouth_disagree(probe[0], geom)):
        warnings = ["mouth_landmarks_implausible"] if not plausible else []
        pack, source, warnings, _guide = _whites_mouth(
            figure, rgb, alpha, eyes_box, face_eyes, style, ink, None, realistic, rig_mouth, warnings)
        return pack, source, warnings, guide
    if not plausible:
        # No painted mouth, and the landmark mouth is too small, too high or too unsure to invent one.
        pack, source, warnings, _guide = _whites_mouth(
            figure, rgb, alpha, eyes_box, face_eyes, style, ink, None, realistic, rig_mouth, [])
        return pack, source, warnings, guide
    centre = geom["mouth"]["center"]
    close = _probe_mouth(find_mouth, rgb, alpha, face_eyes, screen, realistic, centre)
    if close is not None and not anime_face_landmarks.mouth_disagree(close[0], geom):
        pack, source, warnings, _guide = _whites_mouth(
            figure, rgb, alpha, eyes_box, face_eyes, style, ink, centre, realistic, rig_mouth, [])
        return pack, source, warnings, guide
    pack, guide = _landmark_mouth(figure, rgb, alpha, eyes_box, geom, guide)
    warnings = ["mouth_disagree"] if probe is not None or close is not None else []
    return pack, "landmarks", warnings, guide


def pose_warnings(height, ey0, found, guide, wiped, rigged, alpha, face_eyes, mouth_box,
                  eye_warnings, mouth_warnings, anime_failed, stray_marks) -> list[str]:
    """The pose's warnings, including a landmark disagreement and a failed detector."""
    warnings = ["eyes_low"] if ey0 / height > 0.4 else []
    warnings.extend(eye_warnings)
    warnings.extend(mouth_warnings)
    if anime_failed:
        warnings.append("anime_landmarks_failed")
    if not found:
        warnings.append("mouth_not_found")
    if (guide.get("hint_ignored") or {}).get("far"):
        warnings.append("mouth_hint_ignored")
    elif wiped and stray_marks(np.array(rigged)[..., :3], alpha, face_eyes, mouth_box):
        warnings.append("stray_mark")
    return warnings
