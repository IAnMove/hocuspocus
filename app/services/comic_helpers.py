"""Comic page checks shared by Director comic and Story Lab.

Moved verbatim from the full server. This module does not import WanGP or
``_launch_runtime``. The writing-provider lookup receives WanGP's server
config through ``bind_comic_helpers``.
"""
from __future__ import annotations

import copy
import json
import re

from fastapi import HTTPException

from services.comic_director_json import _generate_comic_director_json

# Injected by bind_comic_helpers. None until the full server binds it.
wgp = None


def _normalize_comic_panel_arrays(panel: dict) -> None:
    """Repair common single-item JSON shortcuts without discarding copy."""
    for key in ("characters", "captions", "soundEffects"):
        value = panel.get(key)
        if isinstance(value, list):
            continue
        if isinstance(value, str) and value.strip():
            panel[key] = [value.strip()]
        else:
            panel[key] = []

    value = panel.get("dialogue")
    if isinstance(value, list):
        items = value
    elif isinstance(value, dict):
        items = [value]
    elif isinstance(value, str) and value.strip():
        items = [{"text": value.strip(), "bubbleType": "speech"}]
    else:
        items = []
    panel["dialogue"] = [
        {"text": item.strip(), "bubbleType": "speech"}
        if isinstance(item, str) and item.strip()
        else item
        for item in items
        if isinstance(item, dict) or (isinstance(item, str) and item.strip())
    ]


def _normalize_comic_panel_character_ids(panel: dict, characters: list) -> None:
    """Resolve harmless LLM name/ID drift while preserving visual priority order."""
    lookup: dict[str, str] = {}
    canonical_ids: set[str] = set()
    for character in characters:
        if not isinstance(character, dict):
            continue
        canonical = str(character.get("id") or "").strip()
        if not canonical:
            continue
        canonical_ids.add(canonical)
        for alias in (character.get("id"), character.get("name")):
            value = str(alias or "").strip()
            if value:
                lookup.setdefault(value.casefold(), canonical)
                token = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
                if token:
                    lookup.setdefault(token, canonical)

    normalized: list[str] = []
    for value in panel.get("characters", []):
        stripped = str(value or "").strip()
        token = re.sub(r"[^a-z0-9]+", "-", stripped.casefold()).strip("-")
        canonical = (
            stripped
            if stripped in canonical_ids
            else lookup.get(stripped.casefold()) or lookup.get(token)
        )
        if canonical and canonical not in normalized:
            normalized.append(canonical)
    panel["characters"] = normalized


def _comic_page_problem(page, expected_panels: int) -> str | None:
    """Return why a generated page is unsafe to checkpoint, if anything."""
    if not isinstance(page, dict):
        return "the page is not a JSON object"
    panels = page.get("panels")
    if not isinstance(panels, list):
        return "the panels field is not an array"
    if len(panels) != expected_panels:
        return f"it contains {len(panels)} panels instead of {expected_panels}"
    for panel_index, panel in enumerate(panels, 1):
        if not isinstance(panel, dict):
            return f"panel {panel_index} is not a JSON object"
        _normalize_comic_panel_arrays(panel)
        dialogue = panel.get("dialogue")
        if not isinstance(dialogue, list):
            return f"panel {panel_index} dialogue is not an array"
        if any(not isinstance(line, dict) for line in dialogue):
            return f"panel {panel_index} contains malformed dialogue"
        normalized_lines = [
            str(line.get("text") or "").strip().casefold()
            for line in dialogue
            if str(line.get("text") or "").strip()
        ]
        if len(normalized_lines) > 2:
            return f"panel {panel_index} contains excessive dialogue"
        if normalized_lines and len(set(normalized_lines)) < len(normalized_lines) * 0.6:
            return f"panel {panel_index} contains repetitive dialogue"
    return None



def _compact_comic_panel_copy(
    panel: dict,
    dialogue_limit: int = 1,
    max_elements: int = 2,
) -> None:
    """Keep generated lettering readable even when the planning model overproduces."""
    seen = set()

    def unique_text(values, limit):
        if limit <= 0:
            return []
        compacted = []
        for value in values if isinstance(values, list) else []:
            text = str(value or "").strip()
            key = re.sub(r"\s+", " ", text).casefold()
            if not key or key in seen:
                continue
            seen.add(key)
            compacted.append(text)
            if len(compacted) >= limit:
                break
        return compacted

    panel["captions"] = unique_text(panel.get("captions"), min(1, max_elements))
    dialogue = []
    dialogue_limit = min(dialogue_limit, max(0, max_elements - len(panel["captions"])))
    for value in panel.get("dialogue") if isinstance(panel.get("dialogue"), list) else []:
        if not isinstance(value, dict):
            continue
        text = str(value.get("text") or "").strip()
        key = re.sub(r"\s+", " ", text).casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        dialogue.append({**value, "text": text})
        if len(dialogue) >= dialogue_limit:
            break
    panel["dialogue"] = dialogue
    remaining_lettering_slots = max(
        0,
        max_elements - len(panel["captions"]) - len(panel["dialogue"]),
    )
    panel["soundEffects"] = unique_text(panel.get("soundEffects"), remaining_lettering_slots)


def _enforce_comic_page_text_budget(page: dict, dialogue_density: str) -> None:
    panels = page.get("panels") if isinstance(page, dict) else None
    if not isinstance(panels, list) or not panels:
        return
    dense_grid = len(panels) >= 7
    for panel_index, panel in enumerate(panels):
        if isinstance(panel, dict):
            is_large_panel = (
                len(panels) <= 4
                or (page.get("layoutHint") == "dynamic" and panel_index == 0)
            )
            _compact_comic_panel_copy(
                panel,
                dialogue_limit=1 if dense_grid else (2 if dialogue_density == "high" else 1),
                max_elements=2 if is_large_panel else 1,
            )
    ratio = {"low": 0.3, "medium": 0.55, "high": 0.8}.get(dialogue_density, 0.55)
    keep_count = max(1, min(len(panels), int(len(panels) * ratio + 0.999)))
    text_panel_indices = [
        index
        for index, panel in enumerate(panels)
        if isinstance(panel, dict) and (
            panel.get("captions") or panel.get("dialogue") or panel.get("soundEffects")
        )
    ]
    if len(text_panel_indices) <= keep_count:
        return
    if keep_count == 1:
        keep = {text_panel_indices[0]}
    else:
        keep = {
            text_panel_indices[
                round(position * (len(text_panel_indices) - 1) / (keep_count - 1))
            ]
            for position in range(keep_count)
        }
    for index, panel in enumerate(panels):
        if isinstance(panel, dict) and index not in keep:
            panel["captions"] = []
            panel["dialogue"] = []
            panel["soundEffects"] = []


_COMIC_ENGLISH_DRIFT_WORDS = {
    "the", "this", "that", "these", "those", "is", "are", "was", "were",
    "be", "been", "being", "and", "but", "with", "without", "from", "into",
    "nothing", "everything", "silence", "absolute", "measurement", "truth",
    "lie", "void", "world", "future", "power", "freedom", "insignificant",
    "we", "you", "your", "our", "they", "their", "not", "never", "always",
}


def _comic_page_has_probable_english_drift(page: dict, target_language: str) -> bool:
    language = str(target_language or "").strip().lower()
    if not language or language in {"english", "ingles", "inglés", "en", "en-us", "en-gb"}:
        return False
    hits = 0
    suspicious_lines = 0
    for panel in page.get("panels") or []:
        if not isinstance(panel, dict):
            continue
        reader_lines = [str(value) for value in (panel.get("captions") or [])]
        reader_lines.extend(
            str(item.get("text") or "")
            for item in (panel.get("dialogue") or [])
            if isinstance(item, dict)
        )
        for line in reader_lines:
            words = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ']+", line.lower())
            line_hits = sum(word in _COMIC_ENGLISH_DRIFT_WORDS for word in words)
            hits += line_hits
            if line_hits >= 2:
                suspicious_lines += 1
    return suspicious_lines > 0 or hits >= 4


def _comic_page_summary(page) -> str:
    if not isinstance(page, dict):
        return ""
    panels = page.get("panels")
    if not isinstance(panels, list):
        return ""
    beats = []
    for panel in panels:
        if not isinstance(panel, dict):
            continue
        beat = str(
            panel.get("continuityNotes")
            or panel.get("sceneDescription")
            or panel.get("narrativeRole")
            or ""
        ).strip()
        if beat:
            beats.append(beat)
    return " ".join(beats)[-1600:]


def _comic_writing_llm(body: dict) -> dict | None:
    """Resolve a comic-only LLM override without changing global LLM state."""
    from services.provider_profile import resolve_writing_override

    try:
        return resolve_writing_override(
            provider=str(body.get("writingProvider") or "maestro"),
            model=str(body.get("writingModel") or ""),
            requested_url=str(body.get("writingBaseUrl") or ""),
            services=wgp.server_config.get("services", {}),
            mode=str(body.get("mode") or ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


_COMIC_TEXT_PAGE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["panels"],
    "properties": {
        "panels": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "captions", "dialogue", "soundEffects"],
                "properties": {
                    "id": {"type": "string"},
                    "captions": {"type": "array", "items": {"type": "string"}},
                    "soundEffects": {"type": "array", "items": {"type": "string"}},
                    "dialogue": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["text", "bubbleType"],
                            "properties": {
                                "speakerId": {"type": "string"},
                                "text": {"type": "string", "minLength": 1},
                                "bubbleType": {"type": "string"},
                            },
                        },
                    },
                },
            },
        },
    },
}


def _repair_comic_page_language(
    page: dict,
    target_language: str,
    page_number: int,
    llm_override: dict | None = None,
) -> dict:
    source_panels = []
    for panel in page.get("panels") or []:
        if not isinstance(panel, dict):
            continue
        source_panels.append({
            "id": str(panel.get("id") or ""),
            "captions": [str(value) for value in (panel.get("captions") or [])],
            "soundEffects": [str(value) for value in (panel.get("soundEffects") or [])],
            "dialogue": [
                {
                    "text": str(item.get("text") or ""),
                    "bubbleType": str(item.get("bubbleType") or "speech"),
                    **(
                        {"speakerId": str(item.get("speakerId"))}
                        if item.get("speakerId")
                        else {}
                    ),
                }
                for item in (panel.get("dialogue") or [])
                if isinstance(item, dict)
            ],
        })
    schema = copy.deepcopy(_COMIC_TEXT_PAGE_SCHEMA)
    schema["properties"]["panels"]["minItems"] = len(source_panels)
    schema["properties"]["panels"]["maxItems"] = len(source_panels)
    generated = _generate_comic_director_json(
        prompt=f"""Repair the reader-facing language of comic page {page_number}.
TARGET LANGUAGE: {target_language}

Translate every caption and dialogue line that is not in {target_language}.
If a line is already in {target_language}, copy it exactly, character for character.
Keep proper names unchanged. Copy sound effects exactly without translating them.
Return the exact same panel IDs, order, array lengths, bubble types and speaker IDs.
Never add or remove a line.

Source page text: {json.dumps({"panels": source_panels}, ensure_ascii=False)}""",
        system_prompt=(
            "You are HocusPocus Lab's meticulous comic letterer and translator. "
            "Return only the strict JSON requested by the schema."
        ),
        schema=schema,
        max_new_tokens=min(2600, max(900, len(source_panels) * 260)),
        stage=f"language repair for page {page_number}",
        llm_override=llm_override,
        root_array_key="panels",
    )
    candidate_panels = generated.get("panels")
    if not isinstance(candidate_panels, list) or len(candidate_panels) != len(source_panels):
        raise RuntimeError("Language repair changed the panel count")

    merged = copy.deepcopy(page)
    for index, (source, candidate) in enumerate(zip(source_panels, candidate_panels)):
        if not isinstance(candidate, dict) or str(candidate.get("id") or "") != source["id"]:
            raise RuntimeError("Language repair changed a panel ID")
        candidate_captions = candidate.get("captions")
        candidate_dialogue = candidate.get("dialogue")
        candidate_effects = candidate.get("soundEffects")
        if not all(isinstance(value, list) for value in (
            candidate_captions,
            candidate_dialogue,
            candidate_effects,
        )):
            raise RuntimeError("Language repair returned invalid lettering")
        if (
            len(candidate_captions) != len(source["captions"])
            or len(candidate_dialogue) != len(source["dialogue"])
            or len(candidate_effects) != len(source["soundEffects"])
        ):
            raise RuntimeError("Language repair changed the lettering structure")
        merged_panel = merged["panels"][index]
        merged_panel["captions"] = [str(value) for value in candidate_captions]
        for line_index, candidate_line in enumerate(candidate_dialogue):
            if not isinstance(candidate_line, dict):
                raise RuntimeError("Language repair returned invalid dialogue")
            merged_panel["dialogue"][line_index]["text"] = str(
                candidate_line.get("text") or ""
            )
        merged_panel["soundEffects"] = source["soundEffects"]
    return merged


def bind_comic_helpers(*, wgp_module) -> None:
    """Install the full server's WanGP module for the comic writing lookup."""
    global wgp
    wgp = wgp_module
