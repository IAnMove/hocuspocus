"""Slice generated 3×3 atlases into aligned PNG assets; never redraw the artwork.

Input JSON: {specs: [[id, label, art brief], ...], paths: {id: atlas.png}}.
All nine cells share one scale and use centered pivots on 512px alpha canvases.
"""
import hashlib
import json
from pathlib import Path
import shutil
import sys

from PIL import Image

STATES = ("closed", "small", "wide", "round", "pressed", "medium", "pucker", "bite", "tongue")
ROOT = Path(__file__).resolve().parents[1]


def slices(path):
    with Image.open(path) as image:
        image = image.convert("RGBA")
        cells = []
        for i in range(9):
            x, y = i % 3, i // 3
            cell = image.crop((round(x * image.width / 3), round(y * image.height / 3),
                               round((x + 1) * image.width / 3), round((y + 1) * image.height / 3)))
            # Ignore imperceptible alpha specks when finding the sprite frame.
            bounds = cell.getchannel("A").point(lambda alpha: 255 if alpha >= 8 else 0).getbbox()
            if bounds is None:
                raise ValueError(f"Empty mouth cell {i} in {path}")
            cells.append(cell.crop(bounds))
        return cells


def pack_images(path, destination):
    cells = slices(path)
    ratio = 448 / max(max(cell.size) for cell in cells)
    destination.mkdir(parents=True, exist_ok=True)
    for state, cell in zip(STATES, cells):
        size = tuple(max(1, round(value * ratio)) for value in cell.size)
        scaled = cell.resize(size, Image.Resampling.LANCZOS)
        sprite = Image.new("RGBA", (512, 512))
        sprite.alpha_composite(scaled, ((512 - size[0]) // 2, (512 - size[1]) // 2))
        sprite.save(destination / f"{state}.png", optimize=True)


def build(specification):
    root = ROOT / "ui/public/character-kit-presets/mouths"
    manifest = json.loads((root / "manifest.json").read_text())
    new_ids = {row[0] for row in specification["specs"]}
    packs = [item for item in manifest["packs"] if item["id"] not in new_ids]
    for identifier, label, brief in specification["specs"]:
        source = Path(specification["paths"][identifier])
        pack_images(source, root / identifier)
        packs.append({"id": identifier, "label": label, "style": "cutout", "collection": "studio-20",
                      "notes": brief + ". Nine phonetic positions, transparent PNG, shared 512px frame and pivot.",
                      "provenance": {"tool": "OpenAI imagegen", "atlasSha256": hashlib.sha256(source.read_bytes()).hexdigest()},
                      "states": {state: {"file": f"{identifier}/{state}.png", "width": 512, "height": 512} for state in STATES}})
    manifest.update(states=list(STATES), packs=packs)
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    mirror = ROOT / "app/character_kit_presets/mouths"
    for identifier in new_ids:
        shutil.copytree(root / identifier, mirror / identifier, dirs_exist_ok=True)
    shutil.copy2(root / "manifest.json", mirror / "manifest.json")
    print(f"Prepared {len(new_ids)} packs, {len(new_ids) * len(STATES)} aligned sprites.")


if __name__ == "__main__":
    build(json.loads(Path(sys.argv[1]).read_text()))
