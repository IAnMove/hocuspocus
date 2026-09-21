#!/usr/bin/env python3
"""Assemble 9×6 viseme/expression face packs and a synthetic vowel WAV."""
from __future__ import annotations

import math
import struct
import subprocess
import sys
import wave
import zlib
from pathlib import Path

TILE = 128
COLS, ROWS = 9, 6
VISEMES = ('rest', 'M', 'A', 'E', 'I', 'O', 'U', 'F', 'L')
EXPRESSIONS = ('neutral', 'happy', 'angry', 'worried', 'surprised', 'sleepy')
SRC = Path.home() / '.grok/sessions/%2Fhome%2Fina%2Fpinokio%2Fapi%2FMaestro-next.git/01a08b0b-218e-70c3-8a34-9524f3f316f3/images'
OUT = Path(__file__).resolve().parents[1] / 'public/examples/face-pack'
FFMPEG = 'ffmpeg'

TV_VISEMES = {'rest': 1, 'M': 11, 'A': 7, 'E': 6, 'I': 13, 'O': 9, 'U': 16, 'F': 15, 'L': 19}
TV_EXPR = {'neutral': 1, 'happy': 18, 'angry': 23, 'worried': 22, 'surprised': 24, 'sleepy': 25}
SK_VISEMES = {'rest': 2, 'M': 3, 'A': 5, 'E': 8, 'I': 12, 'O': 10, 'U': 17, 'F': 14, 'L': 21}
SK_EXPR = {'neutral': 2, 'happy': 28, 'angry': 26, 'worried': 29, 'surprised': 27, 'sleepy': 30}
VOXEL_VISEMES = {'rest': 32, 'M': 32, 'A': 39, 'E': 43, 'I': 43, 'O': 41, 'U': 41, 'F': 32, 'L': 39}
VOXEL_EXPR = {'neutral': 32, 'happy': 49, 'angry': 48, 'worried': 58, 'surprised': 53, 'sleepy': 55}
ANIME_VISEMES = {'rest': 33, 'M': 35, 'A': 36, 'E': 44, 'I': 44, 'O': 45, 'U': 45, 'F': 35, 'L': 36}
ANIME_EXPR = {'neutral': 33, 'happy': 51, 'angry': 50, 'worried': 59, 'surprised': 56, 'sleepy': 52}
CUBE_VISEMES = {'rest': 31, 'M': 37, 'A': 38, 'E': 40, 'I': 40, 'O': 42, 'U': 42, 'F': 37, 'L': 38}
CUBE_EXPR = {'neutral': 31, 'happy': 46, 'angry': 47, 'worried': 60, 'surprised': 57, 'sleepy': 54}
FELT_VISEMES = {'rest': 111, 'M': 134, 'A': 133, 'E': 132, 'I': 132, 'O': 131, 'U': 137, 'F': 134, 'L': 133}
FELT_EXPR = {'neutral': 111, 'happy': 135, 'angry': 139, 'worried': 136, 'surprised': 138, 'sleepy': 140}
PLANE_KITS = {
    'clay': ({'rest': 115, 'M': 115, 'A': 142, 'E': 142, 'I': 142, 'O': 152, 'U': 152, 'F': 115, 'L': 142}, {'neutral': 115, 'happy': 167, 'angry': 185, 'worried': 115, 'surprised': 200, 'sleepy': 115}),
    'pixel': ({'rest': 116, 'M': 116, 'A': 143, 'E': 143, 'I': 143, 'O': 170, 'U': 170, 'F': 116, 'L': 143}, {'neutral': 116, 'happy': 209, 'angry': 197, 'worried': 116, 'surprised': 183, 'sleepy': 116}),
    'porcelain': ({'rest': 118, 'M': 118, 'A': 144, 'E': 144, 'I': 144, 'O': 172, 'U': 172, 'F': 118, 'L': 144}, {'neutral': 118, 'happy': 181, 'angry': 196, 'worried': 118, 'surprised': 157, 'sleepy': 118}),
    'cat': ({'rest': 119, 'M': 119, 'A': 141, 'E': 141, 'I': 141, 'O': 160, 'U': 160, 'F': 119, 'L': 141}, {'neutral': 119, 'happy': 171, 'angry': 188, 'worried': 119, 'surprised': 119, 'sleepy': 119}),
    'oni': ({'rest': 120, 'M': 120, 'A': 147, 'E': 147, 'I': 147, 'O': 201, 'U': 201, 'F': 120, 'L': 147}, {'neutral': 120, 'happy': 182, 'angry': 186, 'worried': 120, 'surprised': 174, 'sleepy': 120}),
    'stencil': ({'rest': 121, 'M': 121, 'A': 150, 'E': 150, 'I': 150, 'O': 175, 'U': 175, 'F': 121, 'L': 150}, {'neutral': 121, 'happy': 189, 'angry': 161, 'worried': 121, 'surprised': 203, 'sleepy': 121}),
    'alien': ({'rest': 122, 'M': 122, 'A': 146, 'E': 146, 'I': 146, 'O': 163, 'U': 163, 'F': 122, 'L': 146}, {'neutral': 122, 'happy': 177, 'angry': 202, 'worried': 122, 'surprised': 187, 'sleepy': 122}),
    'pumpkin': ({'rest': 123, 'M': 123, 'A': 199, 'E': 199, 'I': 199, 'O': 159, 'U': 159, 'F': 123, 'L': 199}, {'neutral': 123, 'happy': 173, 'angry': 190, 'worried': 123, 'surprised': 145, 'sleepy': 123}),
    'ice': ({'rest': 124, 'M': 124, 'A': 148, 'E': 148, 'I': 148, 'O': 205, 'U': 205, 'F': 124, 'L': 148}, {'neutral': 124, 'happy': 178, 'angry': 193, 'worried': 124, 'surprised': 162, 'sleepy': 124}),
    'mushroom': ({'rest': 126, 'M': 126, 'A': 149, 'E': 149, 'I': 149, 'O': 192, 'U': 192, 'F': 126, 'L': 149}, {'neutral': 126, 'happy': 176, 'angry': 165, 'worried': 126, 'surprised': 126, 'sleepy': 126}),
    'vector': ({'rest': 127, 'M': 127, 'A': 151, 'E': 151, 'I': 151, 'O': 164, 'U': 164, 'F': 127, 'L': 151}, {'neutral': 127, 'happy': 191, 'angry': 179, 'worried': 127, 'surprised': 127, 'sleepy': 127}),
    'halftone': ({'rest': 128, 'M': 128, 'A': 153, 'E': 153, 'I': 153, 'O': 180, 'U': 180, 'F': 128, 'L': 153}, {'neutral': 128, 'happy': 204, 'angry': 210, 'worried': 128, 'surprised': 194, 'sleepy': 128}),
    'steampunk': ({'rest': 129, 'M': 129, 'A': 154, 'E': 154, 'I': 154, 'O': 169, 'U': 169, 'F': 129, 'L': 154}, {'neutral': 129, 'happy': 184, 'angry': 206, 'worried': 129, 'surprised': 195, 'sleepy': 129}),
    'gummy': ({'rest': 130, 'M': 130, 'A': 207, 'E': 207, 'I': 207, 'O': 198, 'U': 198, 'F': 130, 'L': 207}, {'neutral': 130, 'happy': 168, 'angry': 155, 'worried': 130, 'surprised': 130, 'sleepy': 130}),
}


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def load_tile(index: int, crop: str) -> bytes:
    src = SRC / f'{index}.jpg'
    vf = f'{crop},scale=128:128' if crop else 'scale=128:128'
    proc = subprocess.run(
        [FFMPEG, '-v', 'error', '-i', str(src), '-vf', vf, '-f', 'rawvideo', '-pix_fmt', 'rgb24', 'pipe:1'],
        check=True, stdout=subprocess.PIPE,
    )
    if len(proc.stdout) != TILE * TILE * 3:
        raise RuntimeError(f'{src} decoded to {len(proc.stdout)} bytes')
    return proc.stdout


def _luma(r: int, g: int, b: int) -> float:
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _border_mean(rgb: bytes) -> tuple[float, float, float]:
    sr = sg = sb = n = 0
    for y in range(TILE):
        for x in range(TILE):
            if 10 <= x < TILE - 10 and 10 <= y < TILE - 10:
                continue
            i = (y * TILE + x) * 3
            r, g, b = rgb[i], rgb[i + 1], rgb[i + 2]
            if _luma(r, g, b) < 28:
                continue
            sr += r
            sg += g
            sb += b
            n += 1
    if n < 16:
        return (1.0, 1.0, 1.0)
    return (sr / n, sg / n, sb / n)


def match_skin(tile: bytes, ref: bytes) -> bytes:
    tr, tg, tb = _border_mean(tile)
    rr, rg, rb = _border_mean(ref)
    if tr < 1 or tg < 1 or tb < 1:
        return tile
    kr, kg, kb = rr / tr, rg / tg, rb / tb
    out = bytearray(tile)
    for i in range(0, len(out), 3):
        r, g, b = out[i], out[i + 1], out[i + 2]
        if _luma(r, g, b) < 28:
            continue
        out[i] = max(0, min(255, int(r * kr)))
        out[i + 1] = max(0, min(255, int(g * kg)))
        out[i + 2] = max(0, min(255, int(b * kb)))
    return bytes(out)


def paste_mouth(base: bytes, viseme: bytes, cx: float, cy: float, rx: float, ry: float) -> bytes:
    out = bytearray(base)
    for y in range(TILE):
        ny = (y + 0.5 - cy) / ry
        for x in range(TILE):
            nx = (x + 0.5 - cx) / rx
            d = nx * nx + ny * ny
            if d > 1.2:
                continue
            a = 1.0 if d <= 0.92 else max(0.0, 1.0 - (d - 0.92) / 0.28)
            i = (y * TILE + x) * 3
            for c in range(3):
                out[i + c] = int(out[i + c] * (1 - a) + viseme[i + c] * a)
    return bytes(out)


def write_png(path: Path, width: int, height: int, rgb: bytes) -> None:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', zlib.crc32(tag + data) & 0xFFFFFFFF)

    raw = b''.join(b'\x00' + rgb[y * width * 3:(y + 1) * width * 3] for y in range(height))
    path.write_bytes(
        b'\x89PNG\r\n\x1a\n'
        + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
        + chunk(b'IDAT', zlib.compress(raw, 9))
        + chunk(b'IEND', b'')
    )


def assemble(name: str, visemes: dict[str, int], expressions: dict[str, int], crop: str, mouth: tuple[float, float, float, float]) -> None:
    vis_tiles = {key: load_tile(index, crop) for key, index in visemes.items()}
    expr_tiles = {key: load_tile(index, crop) for key, index in expressions.items()}
    rest = vis_tiles['rest']
    vis_tiles = {key: match_skin(tile, rest) for key, tile in vis_tiles.items()}
    expr_tiles = {key: match_skin(tile, rest) for key, tile in expr_tiles.items()}
    width, height = TILE * COLS, TILE * ROWS
    canvas = bytearray(width * height * 3)
    cx, cy, rx, ry = mouth
    for row, expression in enumerate(EXPRESSIONS):
        base = expr_tiles[expression]
        for col, viseme in enumerate(VISEMES):
            tile = base if viseme == 'rest' else paste_mouth(base, vis_tiles[viseme], cx, cy, rx, ry)
            for y in range(TILE):
                dst = ((row * TILE + y) * width + col * TILE) * 3
                src = y * TILE * 3
                canvas[dst:dst + TILE * 3] = tile[src:src + TILE * 3]
    write_png(OUT / f'{name}-pack.png', width, height, bytes(canvas))
    rest_row = bytearray(TILE * COLS * TILE * 3)
    for col, viseme in enumerate(VISEMES):
        tile = rest if viseme == 'rest' else paste_mouth(rest, vis_tiles[viseme], cx, cy, rx, ry)
        for y in range(TILE):
            dst = (y * TILE * COLS + col * TILE) * 3
            src = y * TILE * 3
            rest_row[dst:dst + TILE * 3] = tile[src:src + TILE * 3]
    write_png(OUT / f'{name}-visemes.png', TILE * COLS, TILE, bytes(rest_row))


def synth_vowels(path: Path) -> None:
    sr = 22050
    samples: list[float] = [0.0] * int(sr * 8)

    def osc(freq: float, i: int) -> float:
        return math.sin(2 * math.pi * freq * i / sr)

    def put(start: float, dur: float, f1: float, f2: float, amp: float = 0.2) -> None:
        n0 = int(start * sr)
        n = int(dur * sr)
        for i in range(n):
            t = i / sr
            env = min(1.0, t * 40) * min(1.0, (dur - t) * 18)
            s = 0.55 * osc(f1, i) + 0.32 * osc(f2, i) + 0.13 * osc(f1 * 2, i)
            samples[n0 + i] += amp * env * s

    # Two identical vowel passes: CRT 0–4 s, skull 4–8 s.
    for base in (0.0, 4.0):
        put(base + 0.35, 0.5, 700, 1200, 0.22)   # A
        put(base + 1.05, 0.5, 530, 1840, 0.2)    # E
        put(base + 1.75, 0.5, 270, 2290, 0.18)   # I
        put(base + 2.45, 0.5, 570, 840, 0.22)    # O
        put(base + 3.15, 0.5, 300, 870, 0.2)     # U

    with wave.open(str(path), 'w') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sr)
        frames = b''.join(struct.pack('<h', max(-32767, min(32767, int(s * 32767)))) for s in samples)
        wav.writeframes(frames)


def main() -> int:
    if not (SRC / '1.jpg').is_file():
        print('missing Imagine sources', file=sys.stderr)
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    assemble('tv', TV_VISEMES, TV_EXPR, crop='crop=520:600:252:210', mouth=(64, 84, 36, 22))
    assemble('skull', SK_VISEMES, SK_EXPR, crop='crop=iw*0.72:ih*0.72:(iw-iw*0.72)/2:(ih-ih*0.72)/2', mouth=(64, 90, 44, 32))
    assemble('voxel', VOXEL_VISEMES, VOXEL_EXPR, crop='crop=iw*0.78:ih*0.78:(iw-iw*0.78)/2:(ih-ih*0.78)/2', mouth=(72, 88, 34, 22))
    assemble('anime', ANIME_VISEMES, ANIME_EXPR, crop='crop=iw*0.86:ih*0.86:(iw-iw*0.86)/2:(ih-ih*0.86)/2', mouth=(64, 92, 34, 18))
    assemble('cubeskull', CUBE_VISEMES, CUBE_EXPR, crop='crop=iw*0.72:ih*0.72:(iw-iw*0.72)/2:(ih-ih*0.72)/2', mouth=(64, 92, 42, 30))
    assemble('felt', FELT_VISEMES, FELT_EXPR, crop='', mouth=(64, 92, 30, 18))
    if not (OUT / 'neutral-vowels.wav').is_file():
        synth_vowels(OUT / 'neutral-vowels.wav')
    for name in (
        'tv-pack.png', 'skull-pack.png', 'voxel-pack.png', 'anime-pack.png', 'cubeskull-pack.png',
        'tv-visemes.png', 'skull-visemes.png', 'voxel-visemes.png', 'anime-visemes.png', 'cubeskull-visemes.png',
        'neutral-vowels.wav',
    ):
        path = OUT / name
        if path.is_file():
            print(name, path.stat().st_size)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
