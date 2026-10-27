#!/usr/bin/env python3
"""Proof sheets for 3D characters: make each character from its traits, render a turntable on a running server, cut the frames
and lay them out in one picture. The review loop of docs/agents/CHARACTER_STYLES.md uses it after every change to a style.

    python scripts/dev/character_sheets.py --port 42096 --token-file <worktree>/.server.token --specs specs.json --out sheets
    specs.json: [{"name": "lucky", "traits": {"style": "real", "gender": "man", "texture": "body.png", "texture_head": "head.png"}}, ...]

Options: --look retro|toon|lit (retro: steps 4, outline 0, classic; toon: anime shade with ink), --close (head turntable),
--yaws 0,35,90,180, --exposure 1.5, --workspace blobs. It needs ffmpeg and PIL, a test server of your own (never the live one)
and a workspace where the pictures named in ``texture`` already are. Nothing here changes the app."""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

LOOKS = {"retro": {"steps": 4, "outline": 0, "ink": "#2a2030", "shade": "classic"}, "toon": {"steps": 2, "outline": 3, "ink": "#1b1530", "shade": "anime"}}
_counter = [0]


def call(port: int, token: str, tool: str, payload: dict, workspace: str | None = None, mutate: bool = True) -> dict:
    body = {"version": 1, "input": {**({"workspace": workspace} if workspace else {}), **payload}}
    if mutate:
        _counter[0] += 1
        body["intent_id"] = f"sheets-{tool}-{int(time.time())}-{_counter[0]}"
    data = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": body}}).encode()
    request = urllib.request.Request(f"http://127.0.0.1:{port}/api/v1/mcp", data=data, method="POST", headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
    raw = urllib.request.urlopen(request, timeout=900).read().decode()
    reply = json.loads(raw) if raw.lstrip().startswith("{") else json.loads([line[5:] for line in raw.splitlines() if line.startswith("data:")][-1])
    result = reply.get("result") or reply
    out = result["structuredContent"] if isinstance(result.get("structuredContent"), dict) else json.loads(result["content"][0]["text"])
    return out.get("result", out) if isinstance(out, dict) else out


def make(args, spec: dict) -> dict:
    made = call(args.port, args.token, "model3d.anime.make", {"name": spec["name"], "traits": spec.get("traits", {})}, args.workspace)
    return {"rigged": made["rigged_file"], "height": made["traits"]["height"], "name": spec["name"], "files": {k: v for k, v in made.items() if k.endswith("_file")}}


def turntable(args, characters: list[dict], yaws: list[int]) -> Path:
    """One export: every character at every yaw in a row of copies, on a plain floor."""
    scene = call(args.port, args.token, "world3d.scene.instantiate", {"template_id": args.template}, args.workspace)
    scene = scene.get("scene", scene)
    step = args.step
    bindings, beats = [], []
    slot = 0
    for who, character in enumerate(characters):
        for yaw in yaws:
            oid = "subject_1" if slot == 0 else f"copy_{slot}"
            x = round((slot - (len(characters) * len(yaws) - 1) / 2) * step, 3)
            binding = {"object_id": oid, "source_url": f"/api/v1/file/{character['rigged']}?workspace={args.workspace}", "fit": {"heightM": character["height"]},
                       "position": [x, 0, 0], "rotationY": round(math.radians(yaw), 4), "grounded": True}
            if slot:
                binding.update({"add": True, "media": "model3d"})
            bindings.append(binding)
            beats.append({"t": 0.0, "who": oid, "verb": "do", "action": "idle", "duration": 0.6})
            slot += 1
    centre = 1.62 * (characters[0]["height"] / 1.82) if args.close else 0.95
    camera = {"family": "fixed", "eye": [0, centre if args.close else 1.1, 2.6 if args.close else 3.0 + 0.55 * slot], "look": [0, centre - 0.02, 0], "fov": 30 if args.close else 34}
    patch = {"scene_id": scene["sceneId"], "base_revision": scene["revision"], "duration": 0.6, "motionStep": 0, "renderLook": "toon", "bindings": bindings, "camera": camera,
             "toon": LOOKS["toon" if args.look == "toon" else "retro"]}
    patched = call(args.port, args.token, "world3d.scene.patch", patch, args.workspace)
    patched = patched.get("scene", patched)
    call(args.port, args.token, "world3d.scene.beats", {"scene_id": scene["sceneId"], "base_revision": patched["revision"], "beats": beats}, args.workspace)
    document = call(args.port, args.token, "world3d.scene.inspect", {"scene_id": scene["sceneId"]}, args.workspace, mutate=False)
    document = document.get("scene", document)["document"]
    document["dressing"] = "none"
    document.setdefault("environment", {})["floorStyle"] = "sand"
    document["look"] = {**(document.get("look") or {}), "exposure": args.exposure}
    name = f"sheet_{int(time.time())}"
    receipt = call(args.port, args.token, "scenes.world3d.export", {"document": document, "refs": [], "quality": "draft", "output_name": name}, args.workspace)
    command = receipt["receipt"]["commandId"]
    for _ in range(600):
        status = call(args.port, args.token, "scenes.world3d.export.receipt", {"intent_id": command}, args.workspace, mutate=False)
        status = status.get("receipt") or status
        if status.get("status") in ("completed", "failed", "cancelled", "error"):
            break
        time.sleep(3)
    names = [a.get("name") for a in status.get("artifacts", [])]
    if status.get("status") != "completed" or not names:
        sys.exit(f"the export did not complete: {status}")
    return Path(args.outputs) / args.workspace / names[0]


def sheet(video: Path, out: Path, crop: str) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", "0.4", "-i", str(video), "-frames:v", "1", "-vf", crop, str(out)], check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--token-file", required=True)
    parser.add_argument("--specs", required=True)
    parser.add_argument("--out", default="sheets")
    parser.add_argument("--workspace", default="blobs")
    parser.add_argument("--outputs", required=True, help="the server's app/outputs folder (where workspace folders live)")
    parser.add_argument("--look", choices=("retro", "toon"), default="retro")
    parser.add_argument("--close", action="store_true")
    parser.add_argument("--yaws", default="0,35,90,180")
    parser.add_argument("--exposure", type=float, default=1.5)
    parser.add_argument("--step", type=float, default=0.9)
    parser.add_argument("--template", default="atmos-beach-wide")
    args = parser.parse_args()
    args.token = Path(args.token_file).read_text().strip()
    specs = json.loads(Path(args.specs).read_text())
    characters = [make(args, spec) for spec in specs]
    for character in characters:
        print("made", character["name"], character["files"])
    video = turntable(args, characters, [int(v) for v in args.yaws.split(",")])
    target = Path(args.out) / ("heads.png" if args.close else "bodies.png")
    sheet(video, target, "crop=1920:760:0:160" if args.close else "crop=1920:900:0:120")
    print("sheet", target)


if __name__ == "__main__":
    main()
