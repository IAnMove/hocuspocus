#!/usr/bin/env python3
"""Build a 9×6 face pack from stills named rest/A/happy/… (cube-front planes)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from assemble_face_packs import EXPRESSIONS, TILE, VISEMES, match_skin, paste_mouth, write_png  # noqa: E402

ALIASES = {'I': 'E', 'U': 'O', 'F': 'M', 'L': 'A'}
STEMS = {name.lower(): name for name in (*VISEMES, *EXPRESSIONS, 'rest', 'neutral', 'plane', 'canonical')}


def index_dir(folder: Path) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for path in folder.iterdir():
        if not path.is_file() or path.suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp'}:
            continue
        stem = path.stem.lower()
        for prefix in ('viseme-', 'viseme_', 'mouth-', 'mouth_', 'expr-', 'expr_', 'expression-', 'expression_'):
            if stem.startswith(prefix):
                stem = stem[len(prefix):]
                break
        key = STEMS.get(stem)
        if key == 'neutral' or key == 'plane' or key == 'canonical':
            key = 'rest'
        if key:
            found[key] = path
    return found


def load_named(path: Path) -> bytes:
    # Reuse ffmpeg decode via a fake numeric loader: decode here
    import subprocess
    proc = subprocess.run(
        ['ffmpeg', '-v', 'error', '-i', str(path), '-vf', f'scale={TILE}:{TILE}', '-f', 'rawvideo', '-pix_fmt', 'rgb24', 'pipe:1'],
        check=True, stdout=subprocess.PIPE,
    )
    if len(proc.stdout) != TILE * TILE * 3:
        raise RuntimeError(f'{path} decoded to {len(proc.stdout)} bytes')
    return proc.stdout


def resolve(found: dict[str, Path]) -> tuple[dict[str, bytes], dict[str, bytes]]:
    if 'rest' not in found:
        raise SystemExit('need rest.png (the cube-front plane)')
    rest = load_named(found['rest'])
    visemes: dict[str, bytes] = {'rest': rest}
    for viseme in VISEMES:
        if viseme == 'rest':
            continue
        src = found.get(viseme) or found.get(ALIASES.get(viseme, viseme))
        visemes[viseme] = load_named(src) if src else rest
    expressions: dict[str, bytes] = {'neutral': rest}
    for expression in EXPRESSIONS:
        if expression == 'neutral':
            continue
        src = found.get(expression)
        expressions[expression] = load_named(src) if src else rest
    return visemes, expressions


def write_pack(visemes: dict[str, bytes], expressions: dict[str, bytes], dest: Path, mouth=(64.0, 92.0, 30.0, 18.0)) -> None:
    rest = visemes['rest']
    visemes = {key: match_skin(tile, rest) for key, tile in visemes.items()}
    expressions = {key: match_skin(tile, rest) for key, tile in expressions.items()}
    width, height = TILE * 9, TILE * 6
    canvas = bytearray(width * height * 3)
    cx, cy, rx, ry = mouth
    for row, expression in enumerate(EXPRESSIONS):
        base = expressions[expression]
        for col, viseme in enumerate(VISEMES):
            tile = base if viseme == 'rest' else paste_mouth(base, visemes[viseme], cx, cy, rx, ry)
            for y in range(TILE):
                dst = ((row * TILE + y) * width + col * TILE) * 3
                src = y * TILE * 3
                canvas[dst:dst + TILE * 3] = tile[src:src + TILE * 3]
    dest.parent.mkdir(parents=True, exist_ok=True)
    write_png(dest, width, height, bytes(canvas))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    parser.add_argument('-o', '--out', type=Path, help='PNG path (default: folder/pack.png)')
    args = parser.parse_args()
    found = index_dir(args.folder)
    visemes, expressions = resolve(found)
    dest = args.out or (args.folder / 'pack.png')
    write_pack(visemes, expressions, dest)
    print(dest, dest.stat().st_size)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
