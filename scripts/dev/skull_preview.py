#!/usr/bin/env python3
"""Preview the skull of each head kind without a server: front, three-quarter and side, flat-shaded, in one picture.

    app/env/bin/python scripts/dev/skull_preview.py out.png [fem boy man]

To change a kind, edit its table in ``blob_loft`` (SKULL, SKULL_BOY, SKULL_MAN: crown v=1 to chin v=0, half width, front and back
depth) and run this; compare with silhouettes measured from a Qwen-drawn bald head sheet (see docs/agents/CHARACTER_STYLES.md)."""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app"))
from PIL import Image, ImageDraw  # noqa: E402

from services.blob_loft import HEAD_KINDS, skull_point  # noqa: E402

HEIGHT = 1.8
DIMS = {"fem": (0.12, 0.146, 0.128), "boy": (0.108, 0.152, 0.136), "man": (0.105, 0.152, 0.138)}
LIGHT = (-0.45, 0.6, 0.65)


def render(kind: str, yaw: float, size: int = 360) -> Image.Image:
    width, height, depth = (v * HEIGHT for v in DIMS[kind])
    layout = {"sx": width, "sy": height, "sz": depth, "head_y": 0.0, "h": HEIGHT, "head_kind": kind}
    c, s = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    grid = [[skull_point(layout, 360.0 * j / 48, -90 + 180 * k / 36) for j in range(48)] for k in range(37)]
    rotated = [[(x * c + z * s, y, -x * s + z * c) for x, y, z in ring] for ring in grid]
    scale = size * 0.42 / (height / 2 * 1.1)
    image = Image.new("RGB", (size, size), (236, 232, 226))
    draw = ImageDraw.Draw(image)
    triangles = []
    for i in range(len(rotated) - 1):
        for j in range(48):
            a, b, d, e = rotated[i][j], rotated[i][(j + 1) % 48], rotated[i + 1][(j + 1) % 48], rotated[i + 1][j]
            for tri in ((a, b, d), (a, d, e)):
                u = [tri[1][k] - tri[0][k] for k in range(3)]
                v = [tri[2][k] - tri[0][k] for k in range(3)]
                n = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]]
                length = math.sqrt(sum(q * q for q in n)) or 1.0
                centre = [sum(p[k] for p in tri) / 3 for k in range(3)]
                n = [q / length for q in n]
                if sum(n[k] * centre[k] for k in range(3)) < 0:
                    n = [-q for q in n]
                triangles.append((centre[2], tri, n))
    triangles.sort(key=lambda t: t[0])
    for _depth, tri, n in triangles:
        shade = 0.55 + 0.45 * max(0.0, sum(n[k] * LIGHT[k] for k in range(3)) / math.sqrt(sum(q * q for q in LIGHT)))
        colour = tuple(int(v * shade) for v in (244, 206, 178))
        draw.polygon([(size / 2 + p[0] * scale, size * 0.52 - p[1] * scale) for p in tri], fill=colour)
    draw.text((8, 6), f"{kind} yaw {yaw:g}", fill=(30, 30, 30))
    return image


def main() -> None:
    out = sys.argv[1] if len(sys.argv) > 1 else "skulls.png"
    kinds = sys.argv[2:] or list(HEAD_KINDS)
    sheet = Image.new("RGB", (360 * 3, 360 * len(kinds)))
    for row, kind in enumerate(kinds):
        for col, yaw in enumerate((0, 40, 90)):
            sheet.paste(render(kind, yaw), (360 * col, 360 * row))
    sheet.save(out)
    print(out)


if __name__ == "__main__":
    main()
