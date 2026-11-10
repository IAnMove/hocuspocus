"""The anime mould (``blob_loft``): what must not move, and how the arms follow their bones.

The first half pins what the realistic (PS2) style and the vertical cards depend on: the lofted bytes of a ``style: real``
body and the face anchor of the reference characters. They were taken from the mould before the arm and face work, so an
edit that leaks into the real style or moves a head fails here.
"""
import hashlib

import pytest

from services.anime_make import resolve_traits
from services.blob_builder import blob_pieces
from services.blob_loft import loft_glb

# sha256 of ``loft_glb`` for the real-style body of each gender, from the mould as approved with the PS2 heads
REAL_MOULD = {
    ("man", None, None): "b243b96a898a4907d47f81497104c7ddb3514bec87b38c62eadd16fa586fe1d5",
    ("woman", None, None): "b175b6759c3bb1f75e02b0ae16ac060200a3936a57cd9aa68a70813d2a0cdb90",
    ("boy", None, None): "c676375984108c40916112723f329ecd20db4494a8f4f5fe5efe04ecb974101d",
    ("girl", None, None): "f06a0a714974922036f46a35ba6bf22b131efc64733336bea9b36f132ea1c012",
    ("woman", "bob", 1.7): "df342e29e26a9caccd662c6dda5b66ebe071e312a793301243569f661910f662",
}


def _real(gender, hair, height):
    raw = {"style": "real", "gender": gender, **({"hair_style": hair} if hair else {}), **({"height": height} if height else {})}
    built = blob_pieces(resolve_traits(raw)["body"])
    return hashlib.sha256(loft_glb(built["traits"], built["layout"], "blob")).hexdigest()


@pytest.mark.parametrize("key", list(REAL_MOULD), ids=lambda key: "-".join(str(part) for part in key if part))
def test_real_style_mould_is_byte_identical(key):
    assert _real(*key) == REAL_MOULD[key], "a change to the anime mould reached the realistic style"


# The reference characters of the vertical cards: (height, head kind, outfit, skirt) -> the head centre their framing depends on.
REFERENCE_HEAD = {
    "Ana": ({"height": 1.62, "head": {"width": 0.12, "height": 0.146, "depth": 0.128, "shape": "anime", "kind": "fem"}}, [0.0, 1.50174, 0.0], [0.0972, 0.11826, 0.10368]),
    "Eva": ({"height": 1.66, "head": {"width": 0.12, "height": 0.146, "depth": 0.128, "shape": "anime", "kind": "fem"}}, [0.0, 1.53882, 0.0], [0.0996, 0.12118, 0.10624]),
    "Teo": ({"height": 1.9008, "head": {"width": 0.108, "height": 0.152, "depth": 0.136, "shape": "anime", "kind": "boy"}}, [0.0, 1.7563392, 0.0], [0.1026432, 0.1444608, 0.12925440000000002]),
}


@pytest.mark.parametrize("name", list(REFERENCE_HEAD))
def test_face_anchor_does_not_move(name):
    traits, center, radii = REFERENCE_HEAD[name]
    body = {"family": "anime", "mesh": "loft", "build": "slim", "hands": "mitten", "feet": "shoe", "outfit": "school",
            "hair": {"style": "short", "color": "#2A211C"}, **traits}
    anchor = blob_pieces(body)["faceAnchor"]
    assert anchor["center"] == pytest.approx(center, abs=1e-9)
    assert anchor["radii"] == pytest.approx(radii, abs=1e-9)
