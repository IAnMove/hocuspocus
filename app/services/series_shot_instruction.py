"""A shot edit from words: "put a hat on him", "make the camera push in", "add an explosion when he shouts".

``series.shot.update`` with an ``instruction`` and no ``changes`` asks the
configured LLM to write the ``changes`` / ``append`` of the edit. The model sees
the shot in the script vocabulary, the series' characters and poses, its
locations, the workspace's sound and image files and the screen effects, and
must use only those. The edit it writes is checked like any other; when the
check finds problems they go back to the model once, with the problems, before
the call fails. The reply lists what the model wrote, so the edit can be read
and redone by hand.
"""
from __future__ import annotations

import json
from typing import Any, Callable

from services.series_guide import audio_files
from services.series_shot_extras import EFFECT_KINDS
from services.series_shot_edit import LIST_KEYS, SCRIPT_KEYS

IMAGES = (".png", ".webp", ".jpg", ".jpeg")
MAX_IMAGES = 80
SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["summary"],
    "properties": {"changes": {"type": "object"}, "append": {"type": "object"}, "summary": {"type": "string", "maxLength": 400}},
}
SYSTEM = f"""You edit ONE shot of an animated series episode in HocusPocus Series Lab.
Answer with JSON only: {{"changes": {{...}}, "append": {{...}}, "summary": "what you changed, in the user's language"}}.
- changes replaces whole keys of the shot (keys: {', '.join(SCRIPT_KEYS)}); a key set to null is removed.
- append adds items to a list key ({', '.join(LIST_KEYS)}) and keeps what is there: prefer it to add one effect, sound, prop or line.
- Change only what the instruction asks; never resend keys that stay the same.
- Use only the character ids, poses, location ids, files and effect kinds you are given. Never invent a file name.
Shot vocabulary (same as series.episode.from_script):
- cast: [{{"characterId", "poseId", "x" (% of frame width), "enterFrom": "left"|"right", "motion": "idle"|"still"|"shake"}}]
- lines: [{{"who": characterId, "es": "...", "en": "...", "pauseBefore": seconds}}] (one key per language the episode has)
- framing: wide|two|medium|close|insert|title; camera: static|push (push on punchlines and reveals)
- fx: [{{"kind", "line": index | "at": seconds, "anchor": "start"|"end", "offset", "duration": seconds | "shot", "x", "y", "size" (%), "color": "#rrggbb"}}]
- sfx: [{{"file", "at": seconds | "line": index, "anchor": "start"|"end", "offset", "volume" 0-1, "in": source second, "length": seconds}}]
- props: [{{"file", "x", "y" (%), "scale" (fraction of frame height), "ground": true}}] (an image with alpha)
- layers: [{{"file", "depth" 0-1, "front": true|false, "x", "y", "scale"}}]
- music: {{"file", "volume", "start"}}; timing: {{"intro", "gap", "tail"}}; foley: {{"prompt": "sounds only", "volume"}}
- duration: seconds (a shot without lines); clipAudio: keep|drop (a generated or imported video take)
"""


def _characters(series: dict[str, Any], kits: dict[str, Any]) -> list[dict[str, Any]]:
    found = []
    for character in series.get("characters") or []:
        kit = kits.get(((character.get("voiceProfile") or {}).get("characterKitRef") or {}).get("id") or "") or {}
        found.append({"id": character.get("id"), "name": character.get("name"),
                      "poses": (["base"] if kit.get("base") else []) + sorted(kit.get("poses") or {})})
    return found


def context(series: dict[str, Any], episode: dict[str, Any], view: dict[str, Any], kits: dict[str, Any], files: set[str]) -> dict[str, Any]:
    """What the model may use: the shot, the cast it can call, places, files and effects."""
    names = sorted(name for name in files if "/" not in name)
    return {
        "shot": view, "episodeLanguages": [series.get("spokenLanguage"), *sorted(episode.get("languageVersions") or {})],
        "characters": _characters(series, kits),
        "locations": [{"id": item.get("id"), "variants": [variant.get("id") for variant in item.get("variants") or []]}
                      for item in series.get("locations") or []],
        "audio": audio_files(names),
        "images": [name for name in names if name.lower().endswith(IMAGES) and "-cut-" not in name][:MAX_IMAGES],
        "effects": sorted(EFFECT_KINDS),
    }


def _prompt(instruction: str, facts: dict[str, Any], problems: list[str] | None) -> str:
    prompt = f"Instruction: {instruction}\n\nWhat you can use:\n{json.dumps(facts, ensure_ascii=False)}"
    if problems:
        prompt += "\n\nYour previous edit was refused. Fix these problems and answer again:\n- " + "\n- ".join(problems[:12])
    return prompt


def plan_edit(generate: Callable[[str, str, dict], dict], instruction: str, facts: dict[str, Any],
              problems: list[str] | None = None) -> dict[str, Any]:
    """The model's ``{changes, append, summary}`` for the instruction (with the last refusal's problems, if any)."""
    reply = generate(_prompt(instruction, facts, problems), SYSTEM, SCHEMA)
    if not isinstance(reply, dict):
        raise ValueError("The model did not answer with an edit")
    changes = reply.get("changes") if isinstance(reply.get("changes"), dict) else {}
    append = reply.get("append") if isinstance(reply.get("append"), dict) else {}
    return {"changes": changes, "append": append, "summary": str(reply.get("summary") or "")[:400]}


__all__ = ["SCHEMA", "SYSTEM", "context", "plan_edit"]
