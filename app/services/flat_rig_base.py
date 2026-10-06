"""What the flat rig's modules share: the mouth states, the sprite size, the default ink, anchors and the error."""
from __future__ import annotations

from PIL import Image, ImageDraw

STATES = ("closed", "small", "wide", "round", "pressed", "medium", "pucker", "bite", "tongue")
SPRITE = (512, 320)
INK = (34, 22, 20, 255)


class FlatRigError(ValueError):
    def __init__(self, code: str, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.code, self.status = code, status


def _paste_inside(image, outline, fill, box_or_ellipse, kind) -> None:
    mask = Image.new("L", image.size, 0)
    ImageDraw.Draw(mask).polygon(outline, fill=255)
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    getattr(ImageDraw.Draw(layer), kind)(box_or_ellipse, fill=fill)
    clip = Image.composite(layer, Image.new("RGBA", image.size, (0, 0, 0, 0)), mask)
    image.paste(layer, (0, 0), clip.split()[3])


def _anchor(cx: float, cy: float, size: float, width: int, height: int) -> dict[str, float]:
    """A pose-local anchor: the centre in % of the pose's longer edge from its middle, and the height ``size`` as a share
    of that edge."""
    edge = max(width, height)
    return {"offsetX": round((cx - width / 2) / edge * 100, 3), "offsetY": round((cy - height / 2) / edge * 100, 3),
            "scale": round(size / edge, 5), "rotation": 0.0}
