#!/usr/bin/env python3
"""One command, one realistic character that talks: the server job model3d.real.make, then a voice and a talking test clip.

    python scripts/dev/real_character.py --port 42096 --token-file <worktree>/.server.token --outputs <worktree>/app/outputs \\
        --name marta --gender woman --skin "#E3B58F" \\
        --body "a dark green bomber jacket, a white t-shirt, blue jeans, white sneakers" \\
        --face "a woman in her thirties, brown eyes, high cheekbones, shoulder-length dark hair tucked behind her ears, a small mole near the mouth" \\
        --say "Hola, me llamo Marta y esto lo ha hecho la aplicacion de una sola vez." \\
        --voice "a warm, calm young woman, natural Spanish"

The character is made by model3d.real.make (the job the Studio 3D panel «Realista (PS2)» and the Wizard start: guides, the two Qwen
pictures, the textured character, the photo face kit; see docs/agents/CHARACTER_STYLES.md). This script only waits for it, then adds
generation.speech and audio.mouth_cues for the line and a Video 3D scene of the character turning while it talks, exported to
<outputs>/<workspace>/<name>_habla.mp4 (against YOUR test server, never the live one). One GPU model family at a time: the job's
pictures, then the voice, then the render. A rerun reuses what the job already made. Nothing here changes the app."""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

_counter = [0]


class Server:
    def __init__(self, port: int, token: str, workspace: str, outputs: Path) -> None:
        self.port, self.token, self.workspace, self.outputs = port, token, workspace, outputs / workspace
        self.outputs.mkdir(parents=True, exist_ok=True)

    def call(self, tool: str, payload: dict, mutate: bool = True, version: int = 1, raw_body: dict | None = None) -> dict:
        body = raw_body or {"version": version, "input": {"workspace": self.workspace, **payload}}
        if mutate and "intent_id" not in body:
            _counter[0] += 1
            body["intent_id"] = f"rc-{tool}-{int(time.time())}-{_counter[0]}"
        data = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": body}}).encode()
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/v1/mcp", data=data, method="POST", headers={
            "Authorization": f"Bearer {self.token}", "Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
        raw = urllib.request.urlopen(request, timeout=900).read().decode()
        reply = json.loads(raw) if raw.lstrip().startswith("{") else json.loads([line[5:] for line in raw.splitlines() if line.startswith("data:")][-1])
        result = reply.get("result") or reply
        out = result["structuredContent"] if isinstance(result.get("structuredContent"), dict) else json.loads(result["content"][0]["text"])
        out = out.get("result", out) if isinstance(out, dict) else out
        if isinstance(out, dict) and out.get("status") == "failed":
            sys.exit(f"{tool} failed: {out.get('error')}")
        return out

    def generate(self, tool: str, name: str, params: dict, suffix: str, limit: int = 3600) -> Path:
        """A version 2 generation: submit, then wait for the file (and its meta) to appear."""
        target = self.outputs / f"{name}.{suffix}"
        if target.exists() and (self.outputs / f"{name}.meta.json").exists():
            return target
        body = {"version": 2, "intent_id": f"rc-{name}-{int(time.time())}", "output_name": name, "input": {"workspace": self.workspace, "params": params}}
        self.call(tool, {}, mutate=False, raw_body=body)
        started = time.time()
        while time.time() - started < limit:
            if target.exists() and (self.outputs / f"{name}.meta.json").exists():
                return target
            time.sleep(3)
        sys.exit(f"{tool} {name}: nothing after {limit} s")


def make(server: Server, args: argparse.Namespace) -> dict:
    """model3d.real.make, waited for: the job's result (everything model3d.anime.make returns, kit_id of the photo kit, warnings)."""
    payload = {"name": args.name, "gender": args.gender, "skin": args.skin, "outfit_prompt": args.body, "face_prompt": args.face, "seed": args.seed,
               "traits": json.loads(args.traits)}
    job = server.call("model3d.real.make", payload)
    while job.get("status") in ("queued", "running", "cancelling"):
        time.sleep(5)
        job = server.call("model3d.real.status", {"job_id": job["jobId"]}, mutate=False)
    if job.get("status") != "completed":
        sys.exit(f"model3d.real.make {job.get('status')}: {job.get('error')}")
    for note in job["result"].get("warnings") or []:
        print(f"  warning {note['code']}: {note['message']}")
    return job["result"]


def speech(server: Server, name: str, text: str, voice: str, seed: int, language: str) -> tuple[str, list, float]:
    wav = server.generate("generation.speech", name, {"model_type": "voxcpm2_voicedesign", "prompt": text, "alt_prompt": voice, "resolution": "720p", "seed": seed}, "wav")
    seconds = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(wav)]).decode().strip())
    cues = server.call("audio.mouth_cues", {"file": f"{name}.wav", "duration": round(seconds, 3), "dialogue": text, "language": language, "engine": "auto"}, mutate=False)
    return name, cues.get("mouthCues") or cues.get("cues") or cues.get("mouth_cues") or [], seconds


def scene(server: Server, made: dict, kit_id: str, line: tuple[str, list, float] | None, turn: float, label: str | None) -> Path:
    height, anchor = made["traits"]["height"], made["faceAnchor"]
    duration = round((line[2] + 1.2) if line else 5.0, 2)
    head_y = anchor["center"][1]
    started = server.call("world3d.scene.instantiate", {"template_id": "atmos-beach-wide"})
    sc = started.get("scene", started)
    patch = {"scene_id": sc["sceneId"], "base_revision": sc["revision"], "duration": duration, "motionStep": 0, "renderLook": "toon",
             "toon": {"steps": 4, "outline": 0, "ink": "#2a2030", "shade": "classic"},
             "camera": {"family": "fixed", "eye": [0, round(head_y, 3), 1.35], "look": [0, round(head_y - 0.01, 3), 0], "fov": 24},
             "bindings": [{"object_id": "subject_1", "source_url": f"/api/v1/file/{made['rigged_file']}?workspace={server.workspace}", "fit": {"heightM": height},
                           "position": [0, 0, 0], "rotationY": -turn, "grounded": True}]}
    patched = server.call("world3d.scene.patch", patch)
    patched = patched.get("scene", patched)
    server.call("world3d.scene.beats", {"scene_id": sc["sceneId"], "base_revision": patched["revision"], "beats": [{"t": 0.3, "who": "subject_1", "verb": "do", "action": "talk", "duration": duration - 0.4}]})

    def revision() -> int:
        current = server.call("world3d.scene.inspect", {"scene_id": sc["sceneId"]}, mutate=False)
        return (current.get("scene", current))["revision"]

    server.call("world3d.scene.face", {"scene_id": sc["sceneId"], "base_revision": revision(), "object_id": "subject_1", "kit_id": kit_id, "shape": "mesh",
                                       "center": anchor["center"], "radii": anchor["radii"], "size": 1.0})
    if line:
        server.call("world3d.scene.talk", {"scene_id": sc["sceneId"], "base_revision": revision(), "object_id": "subject_1", "kit_id": kit_id, "blink": False,
                                           "lines": [{"start": 0.4, "cues": line[1], "audio": f"/api/v1/file/{line[0]}.wav?workspace={server.workspace}", "gain": 1.0}]})
    if turn:   # the beats own the motion of a slot they drive: the turn goes in last
        server.call("world3d.scene.patch", {"scene_id": sc["sceneId"], "base_revision": revision(), "bindings": [
            {"object_id": "subject_1", "motion": {"to": [0, 0, 0], "turnTo": turn, "start": 0.2, "end": round(duration - 0.3, 2), "easing": "smooth"}}]})
    current = server.call("world3d.scene.inspect", {"scene_id": sc["sceneId"]}, mutate=False)
    document = (current.get("scene", current))["document"]
    document["dressing"] = "none"
    document.setdefault("environment", {})["floorStyle"] = "sand"
    document["look"] = {**(document.get("look") or {}), "exposure": 1.5}
    if label:
        document["texts"] = [{"id": "label", "text": label, "start": 0.0, "end": duration, "preset": "rise", "x": 50, "y": 8, "size": 4.2, "color": "#ffffff", "rotation": 0,
                              "font": "sans", "weight": 800, "align": "center", "stroke": {"color": "#000000", "width": 6}}]
    name = f"{made['name_slug']}_habla"
    receipt = server.call("scenes.world3d.export", {"document": document, "refs": [], "quality": "draft", "output_name": name})
    command = receipt["receipt"]["commandId"]
    for _ in range(900):
        status = server.call("scenes.world3d.export.receipt", {"intent_id": command}, mutate=False)
        status = status.get("receipt") or status
        if status.get("status") in ("completed", "failed", "cancelled", "error"):
            break
        time.sleep(3)
    if status.get("status") != "completed":
        sys.exit(f"the export did not complete: {status}")
    return server.outputs / status["artifacts"][0]["name"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--token-file", required=True)
    parser.add_argument("--outputs", required=True, help="the test server's app/outputs folder")
    parser.add_argument("--workspace", default="blobs")
    parser.add_argument("--name", required=True)
    parser.add_argument("--gender", choices=("man", "woman"), default="man")
    parser.add_argument("--skin", default="#C9966B")
    parser.add_argument("--body", required=True, help="the clothes and the body, in English, for Qwen")
    parser.add_argument("--face", required=True, help="the face and the hair, in English, for Qwen")
    parser.add_argument("--traits", default="{}", help="more model3d.anime.make traits of style real as JSON (face_depth, face_span, hair_style, ...)")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--say", help="a line for the character to say (Spanish unless --language)")
    parser.add_argument("--voice", default="a calm adult voice, natural Spanish")
    parser.add_argument("--language", default="es")
    parser.add_argument("--turn", type=float, default=1.1, help="radians the character turns each way while it talks (0: stays)")
    parser.add_argument("--label", help="a title burned into the clip")
    args = parser.parse_args()
    server = Server(args.port, Path(args.token_file).read_text().strip(), args.workspace, Path(args.outputs))
    slug = "".join(c if c.isalnum() else "-" for c in args.name.lower()).strip("-")
    print("1/2 model3d.real.make (the mould, the two Qwen pictures, the character, the face kit)")
    made = make(server, args)
    made["name_slug"] = slug
    if not made.get("kit_id"):
        sys.exit("the character has no face kit: read the warnings above")
    line = speech(server, f"{slug}_voz", args.say, args.voice, args.seed, args.language) if args.say else None
    print("2/2 the talking clip")
    clip = scene(server, made, made["kit_id"], line, args.turn, args.label)
    pictures = made["recipe"]["pictures"]
    print(json.dumps({"character": made["rigged_file"], "kit": made["kit_id"], "body_picture": pictures["body"]["file"], "head_picture": pictures["head"]["file"],
                      "clip": str(clip)}, indent=1))


if __name__ == "__main__":
    main()
