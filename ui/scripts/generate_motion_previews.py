#!/usr/bin/env python3
"""Generate lightweight hover previews for Scene Animator motion presets."""

from __future__ import annotations

import argparse
import math
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


WIDTH, HEIGHT, FPS = 480, 270, 24
Point = tuple[float, float, float] | tuple[float, float, float, float]
State = tuple[float, float, float, float]

PRESETS: list[tuple[str, Point, Point, float, bool, str]] = [
    ("turntable", (50, 50, .8), (50, 50, .8), 5, True, "linear"),
    ("meteor", (-10, 82, .22), (112, 18, .65), 2, True, "dramatic"),
    ("space-cruise", (8, 54, .48), (92, 43, .68), 5, True, "ease"),
    ("hover", (50, 54, .7), (50, 46, .76), 4, True, "ease"),
    ("landing", (50, -12, .2), (50, 60, .82), 4, False, "bounce"),
    ("liftoff", (50, 68, .82), (54, -15, .28), 3, False, "dramatic"),
    ("zoom-in", (50, 50, .18), (50, 50, 1.35), 3, True, "dramatic"),
    ("zoom-out", (50, 50, 1.25), (50, 50, .18), 3, True, "ease"),
    ("drift-right", (25, 50, .68), (75, 50, .68), 6, False, "linear"),
    ("drift-left", (75, 50, .68), (25, 50, .68), 6, False, "linear"),
    ("diagonal-rise", (20, 82, .38), (78, 22, .82), 4, True, "ease"),
    ("diagonal-drop", (78, 16, .82), (24, 84, .35), 3, True, "dramatic"),
    ("pop", (50, 50, .05), (50, 50, .85), 1, True, "bounce"),
    ("glide", (-8, 72, .4), (108, 70, .52), 4, False, "ease"),
    ("pass-camera", (16, 50, .18), (90, 50, 1.5), 3, True, "dramatic"),
    ("vibrate", (49, 51, .72), (51, 49, .75), 2, False, "bounce"),
    ("orbit-sweep", (18, 70, .32), (86, 30, .9), 5, True, "ease"),
    ("center-reveal", (50, 105, .35), (50, 52, .9), 3, True, "ease"),
    ("exit-frame", (50, 50, .8), (120, -10, .25), 2, True, "dramatic"),
    ("floating-logo", (50, 45, .72), (50, 55, .72), 4, True, "ease"),
    ("orbit-layer", (50, 50, .45), (50, 50, .45), 5, True, "linear"),
    ("game-spawn", (50, 55, .05, 0), (50, 50, .8, 1), 1.2, True, "bounce"),
    ("loot-drop", (50, -18, .35), (50, 72, .72), 1.4, True, "bounce"),
    ("item-pickup", (50, 68, .72, 1), (50, 20, .12, 0), .9, True, "dramatic"),
    ("projectile-launch", (-12, 58, .16), (115, 42, .5), .75, True, "dramatic"),
    ("boss-entrance", (50, -20, .18, 0), (50, 58, 1.25, 1), 2.2, False, "bounce"),
    ("dodge-dash", (30, 55, .82), (78, 50, .68), .55, False, "dramatic"),
    ("hit-knockback", (55, 48, .88), (32, 58, .62), .65, True, "bounce"),
    ("power-up-rise", (50, 78, .3, .25), (50, 42, 1.05, 1), 1.8, True, "bounce"),
    ("cinematic-push", (38, 55, .28), (54, 48, 1.18), 5.5, False, "ease"),
    ("hero-flyover", (-18, 22, .22), (118, 72, 1.15), 4.2, True, "ease"),
    ("fade-reveal", (50, 50, .78, 0), (50, 50, .92, 1), 2.5, False, "ease"),
    ("foreground-parallax", (-28, 50, 1.55), (128, 50, 1.55), 7, False, "linear"),
    ("crane-reveal", (50, 112, 1.3, .2), (50, 45, .72, 1), 4.5, False, "ease"),
    ("portal-arrival", (50, 50, .02, 0), (50, 50, 1, 1), 1.6, True, "dramatic"),
]


def easing(value: float, curve: str) -> float:
    if curve == "ease":
        return value * value * (3 - 2 * value)
    if curve == "dramatic":
        return value * value
    if curve == "bounce":
        return min(1, value + math.sin(value * math.pi * 3) * (1 - value) * .18)
    return value


def normalize_point(point: Point) -> State:
    return point[0], point[1], point[2], point[3] if len(point) > 3 else 1.0


def motion_state(preset_id: str, start: Point, end: Point, curve: str, progress: float) -> State:
    if preset_id == "orbit-layer":
        angle = progress * math.pi * 4
        depth = math.sin(angle)
        return 50 + math.cos(angle) * 18, 50 + depth * 9, .45 * (1 + depth * .12), 1
    value = easing(progress, curve)
    start_state, end_state = normalize_point(start), normalize_point(end)
    return tuple(a + (b - a) * value for a, b in zip(start_state, end_state))  # type: ignore[return-value]


def background() -> Image.Image:
    image = Image.new("RGBA", (WIDTH, HEIGHT), "#07111f")
    pixels = image.load()
    for y in range(HEIGHT):
        for x in range(WIDTH):
            glow = max(0, 1 - math.hypot(x - WIDTH / 2, y - HEIGHT / 2) / (WIDTH * .65))
            pixels[x, y] = (7 + int(glow * 7), 17 + int(glow * 13), 31 + int(glow * 21), 255)
    draw = ImageDraw.Draw(image)
    for x in range(0, WIDTH, 40):
        draw.line((x, 0, x, HEIGHT), fill=(87, 135, 180, 16))
    for y in range(0, HEIGHT, 40):
        draw.line((0, y, WIDTH, y), fill=(87, 135, 180, 16))
    return image


BASE_BACKGROUND = background()


def prepare_sprite(path: Path) -> Image.Image:
    image = Image.open(path).convert("RGBA")
    box = image.getchannel("A").getbbox()
    return image.crop(box) if box else image


def place_sprite(canvas: Image.Image, source: Image.Image, state: State, spin: bool, progress: float, depth_order: int = 0) -> None:
    x, y, scale, opacity = state
    base = 170 * scale / .8
    ratio = source.width / max(1, source.height)
    width = base if ratio >= 1 else base * ratio
    height = base / ratio if ratio >= 1 else base
    if spin:
        yaw = math.cos(progress * math.pi * 4)
        width *= max(.18, abs(yaw))
    sprite = source.resize((max(1, round(width)), max(1, round(height))), Image.Resampling.LANCZOS)
    if spin and math.cos(progress * math.pi * 4) < 0:
        sprite = sprite.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    if opacity < 1:
        sprite.putalpha(sprite.getchannel("A").point(lambda value: round(value * max(0, opacity))))
    shadow = Image.new("RGBA", sprite.size, (0, 0, 0, 0))
    shadow.putalpha(sprite.getchannel("A").filter(ImageFilter.GaussianBlur(8)))
    px, py = round(WIDTH * x / 100 - sprite.width / 2), round(HEIGHT * y / 100 - sprite.height / 2)
    canvas.alpha_composite(shadow, (px + 5, py + 7))
    canvas.alpha_composite(sprite, (px, py))


def render_frame(primary: Image.Image, secondary: Image.Image, preset: tuple[str, Point, Point, float, bool, str], progress: float, poster: bool = False) -> Image.Image:
    preset_id, start, end, _duration, spin, curve = preset
    frame = BASE_BACKGROUND.copy()
    draw = ImageDraw.Draw(frame)
    if poster:
        samples = [motion_state(preset_id, start, end, curve, index / 24) for index in range(25)]
        points = [(WIDTH * x / 100, HEIGHT * y / 100) for x, y, _scale, _opacity in samples]
        draw.line(points, fill=(70, 220, 255, 150), width=3)
        for index, point in enumerate(points[::4]):
            radius = 2 if index < 6 else 4
            draw.ellipse((point[0] - radius, point[1] - radius, point[0] + radius, point[1] + radius), fill=(116, 232, 255, 210))
    state = motion_state(preset_id, start, end, curve, progress)
    if preset_id == "orbit-layer":
        depth = math.sin(progress * math.pi * 4)
        if depth < 0:
            place_sprite(frame, primary, state, spin, progress)
        place_sprite(frame, secondary, (50, 50, .72, 1), False, progress)
        if depth >= 0:
            place_sprite(frame, primary, state, spin, progress)
    else:
        place_sprite(frame, primary, state, spin, progress)
    return frame.convert("RGB")


def encode_preview(output: Path, primary: Image.Image, secondary: Image.Image, preset: tuple[str, Point, Point, float, bool, str]) -> None:
    preset_id, _start, _end, duration, _spin, _curve = preset
    frame_count = max(1, round(duration * FPS))
    command = [
        "ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{WIDTH}x{HEIGHT}", "-r", str(FPS), "-i", "-", "-an", "-c:v", "libvpx-vp9",
        "-deadline", "good", "-cpu-used", "3", "-crf", "36", "-b:v", "0", "-pix_fmt", "yuv420p", str(output / f"{preset_id}.webm"),
    ]
    process = subprocess.Popen(command, stdin=subprocess.PIPE)
    assert process.stdin is not None
    for index in range(frame_count):
        progress = index / max(1, frame_count - 1)
        process.stdin.write(render_frame(primary, secondary, preset, progress).tobytes())
    process.stdin.close()
    if process.wait() != 0:
        raise RuntimeError(f"ffmpeg failed for {preset_id}")
    render_frame(primary, secondary, preset, .28, poster=True).save(output / f"{preset_id}.webp", "WEBP", quality=82, method=6)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--primary", required=True, type=Path)
    parser.add_argument("--secondary", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--only", nargs="*", help="Generate only these preset ids")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    primary, secondary = prepare_sprite(args.primary), prepare_sprite(args.secondary)
    presets = [preset for preset in PRESETS if not args.only or preset[0] in args.only]
    for index, preset in enumerate(presets, 1):
        print(f"[{index:02d}/{len(presets)}] {preset[0]}", flush=True)
        encode_preview(args.output, primary, secondary, preset)


if __name__ == "__main__":
    main()
