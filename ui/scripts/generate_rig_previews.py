#!/usr/bin/env python3
"""Generate honest, asset-free previews for Maestro rig profiles and clips.

The drawings intentionally show Maestro's procedural joint chain instead of a
humanoid character: current clips bend a generic chain and should not imply
semantic arms/legs. Motion amplitudes mirror procedural_rig.py closely enough
for selection cards while remaining lightweight and redistributable.
"""

from __future__ import annotations

import argparse
import math
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


WIDTH, HEIGHT, FPS = 320, 180, 24

PROFILES: dict[str, tuple[int, str, float]] = {
    "prop": (3, "vertical", 3.5),
    "vehicle": (3, "horizontal", 5.5),
    "humanoid": (7, "vertical", 2.4),
    "quadruped": (7, "horizontal", 2.0),
    "flying": (5, "horizontal", 2.8),
    "serpentine": (9, "serpentine", 1.6),
}

CLIPS: dict[str, float] = {
    "idle": 3.0,
    "breathe": 2.5,
    "hover": 3.0,
    "alert": 2.4,
    "walk": 1.0,
    "run": .64,
    "strafe": 1.2,
    "jump": 1.25,
    "attack": .8,
    "hit": .7,
    "roll": 1.0,
    "charge": 1.6,
    "victory": 2.0,
    "bounce": 1.0,
    "spin": 4.0,
    "wobble": 2.0,
}


def background() -> Image.Image:
    image = Image.new("RGBA", (WIDTH, HEIGHT), "#07111f")
    pixels = image.load()
    for y in range(HEIGHT):
        for x in range(WIDTH):
            glow = max(0.0, 1.0 - math.hypot(x - WIDTH / 2, y - HEIGHT / 2) / (WIDTH * .55))
            pixels[x, y] = (7 + int(glow * 7), 17 + int(glow * 15), 31 + int(glow * 25), 255)
    draw = ImageDraw.Draw(image)
    for x in range(0, WIDTH, 32):
        draw.line((x, 0, x, HEIGHT), fill=(87, 135, 180, 18))
    for y in range(0, HEIGHT, 30):
        draw.line((0, y, WIDTH, y), fill=(87, 135, 180, 18))
    draw.line((20, 145, WIDTH - 20, 145), fill=(96, 165, 250, 42), width=1)
    return image


BASE_BACKGROUND = background()


def clip_state(clip_id: str, progress: float) -> dict[str, float]:
    phase = 2 * math.pi * progress
    state = {"x": 0.0, "y": 0.0, "rotation": 0.0, "sx": 1.0, "sy": 1.0, "sway": 0.0, "turn": 1.0, "glow": 0.0}
    if clip_id == "idle":
        state["sway"] = 10 * math.sin(phase)
    elif clip_id == "breathe":
        wave = .03 * math.sin(phase)
        state.update(sx=1 + wave, sy=1 - .66 * wave)
    elif clip_id == "hover":
        state.update(y=8 * math.sin(phase), rotation=3 * math.sin(phase + math.pi / 2), sway=6 * math.sin(phase))
    elif clip_id == "alert":
        state.update(rotation=3 * (1 - math.cos(phase)) * .5, sway=8 * math.sin(phase), turn=max(.55, abs(math.cos(math.radians(12) * math.sin(phase)))))
    elif clip_id == "walk":
        state.update(y=5 * (.5 - .5 * math.cos(phase * 2)), sway=14 * math.sin(phase))
    elif clip_id == "run":
        lift = abs(math.sin(phase))
        state.update(y=10 * lift, sx=1.035 - .035 * lift, sy=.94 + .06 * lift, sway=20 * math.sin(phase))
    elif clip_id == "strafe":
        state.update(x=22 * math.sin(phase), y=4 * (.5 - .5 * math.cos(phase * 2)), rotation=-9 * math.sin(phase), sway=11 * math.sin(phase))
    elif clip_id == "jump":
        airborne = math.sin(math.pi * progress) ** 1.25
        state.update(y=42 * airborne, rotation=-5 * math.sin(math.pi * progress), sx=1 - .045 * airborne, sy=1 + .09 * airborne, sway=8 * math.sin(phase))
    elif clip_id == "attack":
        strike = math.sin(math.pi * progress) ** 2
        state.update(x=-12 * strike, y=5 * strike, rotation=-12 * strike, sx=1 + .16 * strike, sway=18 * math.sin(phase), glow=strike)
    elif clip_id == "hit":
        recoil = math.sin(math.pi * progress)
        state.update(x=20 * recoil, y=-5 * recoil, rotation=-17 * recoil, sway=-12 * math.sin(phase), glow=recoil)
    elif clip_id == "roll":
        state.update(y=18 * math.sin(math.pi * progress), rotation=360 * progress)
    elif clip_id == "charge":
        pulse = math.sin(phase * 3) * math.sin(math.pi * progress)
        state.update(sx=1 + .055 * pulse, sy=1 + .08 * pulse, sway=7 * pulse, glow=abs(pulse))
    elif clip_id == "victory":
        state.update(y=25 * math.sin(math.pi * progress) ** 2, sway=13 * math.sin(phase), turn=math.cos(phase), glow=.4 * math.sin(math.pi * progress))
    elif clip_id == "bounce":
        lift = abs(math.sin(phase))
        state.update(y=20 * lift, sx=1.04 - .04 * lift, sy=.92 + .08 * lift)
    elif clip_id == "spin":
        state["turn"] = math.cos(phase)
    elif clip_id == "wobble":
        state.update(y=6 * abs(math.sin(phase)), rotation=8 * math.sin(phase), sway=6 * math.sin(phase * 2))
    return state


def base_chain(count: int, orientation: str, progress: float = 0.0) -> list[tuple[float, float]]:
    if orientation == "vertical":
        return [(0.0, 47 - index * 94 / max(1, count - 1)) for index in range(count)]
    if orientation == "serpentine":
        return [(-62 + index * 124 / max(1, count - 1), math.sin(index * .8 + progress * math.pi * 2) * 17) for index in range(count)]
    return [(-62 + index * 124 / max(1, count - 1), 0.0) for index in range(count)]


def transform_points(points: list[tuple[float, float]], state: dict[str, float], progress: float, stiffness: float) -> list[tuple[float, float]]:
    angle = math.radians(state["rotation"])
    cos_angle, sin_angle = math.cos(angle), math.sin(angle)
    turn = state["turn"]
    turn_scale = max(.16, abs(turn))
    transformed: list[tuple[float, float]] = []
    for index, (x, y) in enumerate(points):
        amount = index / max(1, len(points) - 1)
        flexible = max(.18, 1.2 - stiffness / 6)
        sway = math.sin(progress * math.pi * 2 + index * .45) * state["sway"] * amount * flexible
        local_x = (x + sway) * state["sx"] * turn_scale
        local_y = y * state["sy"]
        rotated_x = local_x * cos_angle - local_y * sin_angle
        rotated_y = local_x * sin_angle + local_y * cos_angle
        transformed.append((WIDTH / 2 + state["x"] + rotated_x, 103 - state["y"] + rotated_y))
    return transformed


def draw_chain(frame: Image.Image, points: list[tuple[float, float]], state: dict[str, float], profile_id: str | None = None, ghost: bool = False) -> None:
    overlay = Image.new("RGBA", frame.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    glow = max(0.0, state.get("glow", 0.0))
    body_alpha = 35 if ghost else 72
    bone_alpha = 55 if ghost else 240
    turn_scale = max(.16, abs(state.get("turn", 1.0)))
    base_body_width = 18 if profile_id in {"vehicle", "quadruped", "flying", "serpentine"} else 24
    body_width = max(5, round(base_body_width * (.2 + .8 * turn_scale)))
    if len(points) > 1:
        draw.line(points, fill=(59, 130, 246, body_alpha), width=body_width, joint="curve")
        if profile_id == "flying":
            middle = points[len(points) // 2]
            draw.polygon((middle, (middle[0] - 52, middle[1] - 35), (middle[0] - 12, middle[1] + 4)), fill=(96, 165, 250, body_alpha // 2))
            draw.polygon((middle, (middle[0] + 52, middle[1] - 35), (middle[0] + 12, middle[1] + 4)), fill=(96, 165, 250, body_alpha // 2))
        draw.line(points, fill=(125, 230, 255, bone_alpha), width=3 if not ghost else 2, joint="curve")
        if profile_id not in {"vehicle", "quadruped", "flying", "serpentine"}:
            middle = points[len(points) // 2]
            half_width = 24 * turn_scale
            ring_height = 7 if not ghost else 4
            draw.ellipse((middle[0] - half_width, middle[1] - ring_height, middle[0] + half_width, middle[1] + ring_height), outline=(96, 165, 250, bone_alpha), width=2 if not ghost else 1)
    radius = 4 if not ghost else 2
    for index, (x, y) in enumerate(points):
        color = (52, 211, 153, bone_alpha) if index == 0 else (224, 242, 254, bone_alpha)
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color, outline=(14, 116, 144, bone_alpha))
    if not ghost:
        root_x, root_y = points[0]
        draw.ellipse((root_x - 8, root_y - 8, root_x + 8, root_y + 8), outline=(52, 211, 153, 220), width=2)
    if glow > 0:
        halo = overlay.filter(ImageFilter.GaussianBlur(8 + int(glow * 8)))
        frame.alpha_composite(halo)
    frame.alpha_composite(overlay)


def animation_frame(clip_id: str, progress: float, poster: bool = False) -> Image.Image:
    frame = BASE_BACKGROUND.copy()
    if poster:
        for sample, alpha in ((0.0, .18), (.5, .28), (1.0, .18)):
            ghost_state = clip_state(clip_id, sample)
            ghost_state["glow"] = 0
            ghost_points = transform_points(base_chain(7, "vertical"), ghost_state, sample, 2.4)
            draw_chain(frame, ghost_points, {**ghost_state, "glow": 0, "alpha": alpha}, ghost=True)
    state = clip_state(clip_id, progress)
    points = transform_points(base_chain(7, "vertical"), state, progress, 2.4)
    draw_chain(frame, points, state)
    return frame.convert("RGB")


def profile_frame(profile_id: str, progress: float, poster: bool = False) -> Image.Image:
    count, orientation, stiffness = PROFILES[profile_id]
    phase = 2 * math.pi * progress
    state = {"x": 0.0, "y": 2 * math.sin(phase), "rotation": 0.0, "sx": 1.0, "sy": 1.0, "sway": (9 - stiffness) * math.sin(phase), "turn": 1.0, "glow": 0.0}
    points = transform_points(base_chain(count, orientation, progress if orientation == "serpentine" else 0), state, progress, stiffness)
    frame = BASE_BACKGROUND.copy()
    if poster:
        draw = ImageDraw.Draw(frame)
        draw.line((32, 28, 32, 142), fill=(52, 211, 153, 90), width=2)
        for index in range(count):
            y = 36 + index * 94 / max(1, count - 1)
            draw.ellipse((28, y - 3, 34, y + 3), fill=(52, 211, 153, 160))
    draw_chain(frame, points, state, profile_id=profile_id)
    return frame.convert("RGB")


def encode(output: Path, name: str, duration: float, render) -> None:
    frame_count = max(2, round(duration * FPS))
    command = [
        "ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{WIDTH}x{HEIGHT}", "-r", str(FPS), "-i", "-", "-an", "-c:v", "libvpx-vp9",
        "-deadline", "good", "-cpu-used", "3", "-crf", "38", "-b:v", "0", "-pix_fmt", "yuv420p", str(output / f"{name}.webm"),
    ]
    process = subprocess.Popen(command, stdin=subprocess.PIPE)
    assert process.stdin is not None
    for index in range(frame_count):
        process.stdin.write(render(index / max(1, frame_count - 1)).tobytes())
    process.stdin.close()
    if process.wait() != 0:
        raise RuntimeError(f"ffmpeg failed for {name}")
    render(.28, poster=True).save(output / f"{name}.webp", "WEBP", quality=82, method=6)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--only", nargs="*", help="Generate only these profile/clip ids")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    selected = set(args.only or ())
    jobs = [(f"profile-{profile_id}", 2.4, lambda progress, poster=False, item=profile_id: profile_frame(item, progress, poster)) for profile_id in PROFILES if not selected or profile_id in selected]
    jobs += [(f"animation-{clip_id}", duration, lambda progress, poster=False, item=clip_id: animation_frame(item, progress, poster)) for clip_id, duration in CLIPS.items() if not selected or clip_id in selected]
    for index, (name, duration, render) in enumerate(jobs, 1):
        print(f"[{index:02d}/{len(jobs)}] {name}", flush=True)
        encode(args.output, name, duration, render)


if __name__ == "__main__":
    main()
