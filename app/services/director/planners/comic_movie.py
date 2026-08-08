"""Comic-to-film planner.

A finished comic is source material, not an edit decision list.  This planner
can therefore omit, fuse or split source panels into a smaller sequence of
film shots before it writes motion-only I2V directions.  The public payload
remains backwards compatible: small/legacy ``comic_shots`` collections still
produce one shot per panel, while callers may pass reviewed ``film_shots`` to
bypass adaptation entirely.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import re
from typing import Any, Iterable

from ..schema import AudioPlan, CameraPlan, ProductionPlan, ShotPlan, SubjectRef
from .base import BasePlanner


VALID_RENDERERS = {"hold", "parallax", "cinemagraph", "ltx"}
VALID_FIT_MODES = {"reframe", "cover", "contain"}
MAX_DIALOGUE_METADATA_CHARS = 1600
RISK_PRIORITY = (
    "portrait",
    "face",
    "action",
    "landscape",
    "multi-character",
    "line-art",
)

_MOVEMENT_LABELS = {
    "none": "locked-off camera",
    "static": "locked-off camera",
    "locked": "locked-off camera",
    "locked-off": "locked-off camera",
    "push-in": "slow cinematic push-in",
    "pull-out": "slow cinematic pull-out",
    "pan-left": "controlled pan left",
    "pan-right": "controlled pan right",
}

_LIVING_STILL_PROMPT = (
    "Animate the supplied comic artwork as a restrained living still. "
    "The camera and crop remain locked and every subject stays in the same "
    "position. Only breathing, blinking and one subtle ambient detail move. "
    "End on a stable hold of the opening composition."
)

_ACTION_TERMS = {
    "run", "runs", "running", "fight", "fights", "jump", "jumps", "fall",
    "falls", "throw", "throws", "attack", "attacks", "chase", "explodes",
    "corre", "lucha", "salta", "cae", "lanza", "ataca", "persigue", "explota",
}
_FACE_TERMS = {
    "close-up", "close up", "closeup", "portrait", "face", "eyes", "expression",
    "primer plano", "retrato", "rostro", "ojos", "expresión",
}
_LANDSCAPE_TERMS = {
    "wide shot", "panorama", "landscape", "horizon", "cityscape", "establishing",
    "gran plano", "panorámica", "paisaje", "horizonte", "ciudad", "general",
}
_LINE_ART_TERMS = {
    "comic", "ink", "line art", "linework", "cel-shaded", "cel shaded", "anime",
    "cómic", "tinta", "línea", "entintado",
}
_CRITICAL_STORY_TERMS = {
    "inciting", "turning point", "turning-point", "midpoint", "reversal",
    "revelation", "crisis", "climax", "resolution", "catalyst",
    "detonante", "punto de giro", "giro", "revelación", "crisis", "clímax",
    "resolución",
}
_SOURCE_OVERRIDE_FLAGS = (
    "action_override",
    "renderer_override",
    "fit_override",
    "motion_mode_override",
    "motion_level_override",
    "duration_override",
    "camera_override",
    "video_prompt_override",
    "seed_override",
    "end_frame_override",
    "test_selected_override",
)


@dataclass(frozen=True)
class _SourcePanel:
    """Normalized source panel with an immutable ID."""

    source_id: str
    source_index: int
    payload: dict[str, Any]


def _clean_text(value: Any, *, limit: int = 900) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    shortened = text[:limit].rsplit(" ", 1)[0].rstrip(" .;,")
    return f"{shortened}…" if shortened else ""


def _limit_words(value: Any, *, maximum: int = 110) -> str:
    text = _clean_text(value, limit=2400)
    words = text.split()
    if len(words) <= maximum:
        return text
    return " ".join(words[:maximum]).rstrip(" ,;:.") + "."


def _clamp_float(value: Any, default: float, low: float, high: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(low, min(high, parsed))


def _clamp_int(value: Any, default: int, low: int, high: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(low, min(high, parsed))


def _motion_mode(source: dict) -> str:
    raw = str(source.get("motion_mode") or "action").strip().lower()
    if raw in {"living-still", "living_still", "still"}:
        return "living-still"
    if raw in {"contextual", "context", "directed"}:
        return "contextual"
    return "action"


def _renderer(source: dict) -> str:
    requested = str(source.get("renderer") or "").strip().lower()
    if requested in VALID_RENDERERS:
        return requested
    mode = _motion_mode(source)
    if mode == "living-still":
        # Legacy living-still meant a generated ambient shot, not a literal
        # still frame.  Keep that behavior while exposing the clearer renderer.
        return "cinemagraph"
    text = " ".join(
        _clean_text(source.get(key), limit=320).lower()
        for key in ("scene_description", "narrative_role", "framing")
    )
    characters = source.get("characters") or []
    if mode == "contextual":
        # "Contextual" means choose the cheapest renderer that can express
        # the beat; it must not silently mean "send every panel to LTX".
        # Performance, dialogue and concrete action still need I2V, while
        # quiet environments and portraits are safer as deterministic or
        # tightly restrained shots.
        if (
            any(term in text for term in _ACTION_TERMS)
            or bool(_dialogue(source))
        ):
            return "ltx"
        if not characters and any(term in text for term in _LANDSCAPE_TERMS):
            return "parallax"
        if characters:
            # A "cinemagraph" is currently full-frame LTX I2V, not masked
            # local motion. Quiet character beats are therefore much safer as
            # exact holds: otherwise an automatic default may redraw faces and
            # line art even though the beat asks for no visible performance.
            # Users can still opt into AI motion explicitly in PRE or with the
            # dedicated living-still treatment.
            return "hold"
        if text:
            return "parallax"
        return "hold"
    if not characters and any(term in text for term in _LANDSCAPE_TERMS):
        return "cinemagraph"
    if not _clean_text(source.get("scene_description")) and not characters:
        return "hold"
    return "ltx"


def _camera(source: dict, renderer: str) -> str:
    if _motion_mode(source) == "contextual":
        return "locked"
    raw = str(
        source.get("camera")
        or source.get("camera_move")
        or source.get("requested_camera")
        or "locked"
    ).strip().lower()
    if renderer in {"hold", "cinemagraph"}:
        return "locked"
    aliases = {
        "none": "locked",
        "static": "locked",
        "locked-off": "locked",
        "slow push-in": "push-in",
        "slow push in": "push-in",
        "slow pull-out": "pull-out",
        "slow pull out": "pull-out",
    }
    return aliases.get(raw, raw or "locked")


def _dialogue(source: dict) -> str:
    raw = source.get("dialogue")
    if isinstance(raw, list):
        lines: list[str] = []
        for item in raw:
            if isinstance(item, dict):
                text = _clean_text(
                    item.get("text")
                    or item.get("spoken_text")
                    or item.get("spokenText"),
                    limit=220,
                )
                speaker = _clean_text(
                    item.get("speaker")
                    or item.get("speaker_id")
                    or item.get("speakerId"),
                    limit=60,
                )
                if text:
                    lines.append(f"{speaker}: {text}" if speaker else text)
            else:
                text = _clean_text(item, limit=220)
                if text:
                    lines.append(text)
        if lines:
            return _clean_text(
                " / ".join(lines),
                limit=MAX_DIALOGUE_METADATA_CHARS,
            )
    if isinstance(raw, dict):
        return _clean_text(
            raw.get("text") or raw.get("spoken_text"),
            limit=MAX_DIALOGUE_METADATA_CHARS,
        )
    if raw:
        return _clean_text(raw, limit=MAX_DIALOGUE_METADATA_CHARS)
    script = str(source.get("script") or "").strip()
    if not script:
        return ""

    # Comic clients historically send one editable ``script`` string that
    # contains captions, spoken lines and sound effects:
    #
    #   [Caption] At dusk…
    #   [Nara] We leave now.
    #   [SFX] RUMBLE
    #
    # Treating the whole block as dialogue made LTX animate narration and
    # sound-effect labels as speech. Preserve backwards compatibility for
    # untagged legacy scripts, but when tags are present retain only actual
    # speaker lines.
    tagged = False
    spoken_lines: list[str] = []
    for raw_line in script.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = re.match(r"^\[([^\]]+)\]\s*(.+)$", line)
        if not match:
            continue
        tagged = True
        tag = _clean_text(match.group(1), limit=60)
        text = _clean_text(match.group(2), limit=220)
        normalized_tag = tag.casefold().replace("_", " ").replace("-", " ")
        if normalized_tag in {
            "caption",
            "captions",
            "sfx",
            "sound effect",
            "sound effects",
            "effect",
            "effects",
        }:
            continue
        if text:
            spoken_lines.append(
                text
                if normalized_tag in {"dialogue", "dialog", "speech"}
                else f"{tag}: {text}"
            )
    if tagged:
        return _clean_text(
            " / ".join(spoken_lines),
            limit=MAX_DIALOGUE_METADATA_CHARS,
        )

    normalized_script = _clean_text(
        script,
        limit=MAX_DIALOGUE_METADATA_CHARS,
    )
    if re.match(
        r"^(?:no\s+dialogue|without\s+dialogue|sin\s+di[aá]logo)\b",
        normalized_script,
        flags=re.IGNORECASE,
    ):
        return ""
    return normalized_script


def _critical_story_panel(source: dict) -> bool:
    text = " ".join(
        _clean_text(source.get(key), limit=420).lower()
        for key in ("narrative_role", "scene_description", "continuity_notes")
    )
    return any(term in text for term in _CRITICAL_STORY_TERMS)


def _has_source_override(source: dict) -> bool:
    for flag in _SOURCE_OVERRIDE_FLAGS:
        if not bool(source.get(flag)):
            continue
        # Explicitly excluding a beat from the representative quality sample
        # is a test-selection preference, not a request to preserve that panel
        # as a primary film shot. Only a positive sample lock needs a visible
        # primary frame.
        if flag == "test_selected_override":
            if bool(source.get("test_selected")):
                return True
            continue
        return True
    return False


def _split_fallback_groups_for_overrides(
    groups: list[list[_SourcePanel]],
) -> list[list[_SourcePanel]]:
    """Keep explicitly edited source beats as visible/primary film shots.

    A fused shot has only one real first frame.  Treating an edited secondary
    source as "covered" would silently discard the user's visual and motion
    choices, so explicit source overrides split the deterministic fallback.
    """

    split_groups: list[list[_SourcePanel]] = []
    for group in groups:
        automatic: list[_SourcePanel] = []
        for source in group:
            if _has_source_override(source.payload):
                if automatic:
                    split_groups.append(automatic)
                    automatic = []
                split_groups.append([source])
            else:
                automatic.append(source)
        if automatic:
            split_groups.append(automatic)
    return split_groups


def _panel_dimensions(source: dict) -> tuple[float, float]:
    width = 0.0
    height = 0.0
    for key in ("capture_width", "image_width", "panel_width", "width"):
        try:
            width = float(source.get(key) or 0)
        except (TypeError, ValueError):
            width = 0.0
        if width > 0:
            break
    for key in ("capture_height", "image_height", "panel_height", "height"):
        try:
            height = float(source.get(key) or 0)
        except (TypeError, ValueError):
            height = 0.0
        if height > 0:
            break
    return width, height


def classify_comic_shot_risks(sources: Iterable[dict]) -> list[str]:
    """Return stable risk labels used to choose representative test clips."""

    source_list = [source for source in sources if isinstance(source, dict)]
    text = " ".join(
        _clean_text(source.get(key), limit=500).lower()
        for source in source_list
        for key in ("scene_description", "narrative_role", "framing", "visual_style")
    )
    tags: list[str] = []
    for source in source_list:
        width, height = _panel_dimensions(source)
        if width > 0 and height > width * 1.12:
            tags.append("portrait")
            break
    if any(term in text for term in _FACE_TERMS):
        tags.append("face")
    if any(term in text for term in _ACTION_TERMS):
        tags.append("action")
    if any(term in text for term in _LANDSCAPE_TERMS):
        tags.append("landscape")
    character_ids = {
        str(character).strip()
        for source in source_list
        for character in (source.get("characters") or [])
        if str(character).strip()
    }
    if len(character_ids) >= 2:
        tags.append("multi-character")
    if any(term in text for term in _LINE_ART_TERMS):
        tags.append("line-art")
    return [tag for tag in RISK_PRIORITY if tag in set(tags)]


def select_representative_shot_indices(
    shots: Iterable[ShotPlan | dict],
    *,
    max_count: int = 6,
) -> list[int]:
    """Choose a compact test set covering the riskiest visual categories.

    Selection is deterministic.  One shot is selected for every uncovered
    category first; remaining capacity is filled at evenly spaced positions so
    beginning, middle and ending material can all be inspected.
    """

    items = list(shots)
    if not items or max_count <= 0:
        return []

    def metadata(item: ShotPlan | dict) -> dict:
        if isinstance(item, ShotPlan):
            return item.metadata or {}
        nested = item.get("metadata") if isinstance(item, dict) else None
        return nested if isinstance(nested, dict) else item if isinstance(item, dict) else {}

    selected: list[int] = []
    for risk in RISK_PRIORITY:
        for index, item in enumerate(items):
            if index in selected:
                continue
            if risk in (metadata(item).get("risk_tags") or []):
                selected.append(index)
                break
        if len(selected) >= max_count:
            return sorted(selected)

    remaining = max_count - len(selected)
    candidates = [index for index in range(len(items)) if index not in selected]
    if remaining > 0 and candidates:
        if remaining >= len(candidates):
            selected.extend(candidates)
        else:
            for step in range(remaining):
                position = round(step * (len(candidates) - 1) / max(1, remaining - 1))
                candidate = candidates[position]
                if candidate not in selected:
                    selected.append(candidate)
    return sorted(selected[:max_count])


def _recommended_shot_range(panel_count: int) -> tuple[int, int, int]:
    """Return an editorial suggestion, never a hard validation constraint."""

    if panel_count <= 8:
        return panel_count, panel_count, panel_count
    minimum = max(4, round(panel_count * 0.26))
    maximum = max(minimum, round(panel_count * 0.42))
    target = max(minimum, min(maximum, round(panel_count * 0.34)))
    return minimum, target, maximum


def _balanced_slices(item_count: int, group_count: int) -> list[tuple[int, int]]:
    if item_count <= 0 or group_count <= 0:
        return []
    group_count = min(item_count, group_count)
    return [
        (
            round(index * item_count / group_count),
            round((index + 1) * item_count / group_count),
        )
        for index in range(group_count)
    ]


def _stable_seed(shot_id: str) -> int:
    return int(hashlib.sha1(shot_id.encode("utf-8")).hexdigest()[:8], 16) % 2_147_483_647


def _stable_shot_id(
    source_panel_ids: list[str],
    occurrence: int,
    explicit: Any = None,
) -> str:
    if _clean_text(explicit, limit=120):
        return _clean_text(explicit, limit=120)
    primary = re.sub(r"[^a-zA-Z0-9_-]+", "-", source_panel_ids[0]).strip("-_")[:28]
    key = f"{'|'.join(source_panel_ids)}:{occurrence}"
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:8]
    return f"comic-{primary or 'shot'}-{digest}"


def _motion_prompt(
    *,
    renderer: str,
    action: str,
    camera: str,
    end_beat: str,
    dialogue: str,
) -> str:
    """Build a short LTX I2V prompt describing changes, not the visible style."""

    # Reserve part of LTX's compact prompt budget for the actual spoken line.
    # The complete dialogue remains in shot metadata/PRE; this excerpt is only
    # the performance/audio cue sent to the native video+soundtrack model.
    action = _limit_words(_clean_text(action, limit=520), maximum=42).rstrip(" .")
    end_beat = _limit_words(
        _clean_text(end_beat, limit=260),
        maximum=18,
    ).rstrip(" .")
    dialogue = _limit_words(
        _clean_text(dialogue, limit=180),
        maximum=28,
    ).strip()
    if renderer == "hold":
        return "The approved frame holds unchanged for the requested duration."
    if renderer == "cinemagraph":
        prompt = (
            "CINEMAGRAPH_MOTION. The camera remains locked. "
            f"{action or 'One small ambient detail moves continuously'}."
        )
    elif renderer == "parallax":
        prompt = (
            f"{action or 'Foreground and background settle into a restrained depth shift'}. "
            "A subtle parallax move reveals depth without changing the composition."
        )
    else:
        prompt = f"{action or 'The visible subject completes one clear continuous action'}."
        if camera in {"", "none", "static", "locked", "locked-off"}:
            prompt += " The camera remains locked."
        else:
            movement = _MOVEMENT_LABELS.get(camera, camera)
            prompt += f" The camera performs a {movement} after the action begins."
    if dialogue and renderer in {"ltx", "cinemagraph"}:
        spoken = dialogue.replace('"', "'")
        if spoken[-1:] not in {".", "!", "?", "…"}:
            spoken += "."
        prompt += (
            f' Spoken performance: "{spoken}" '
            "Visible speakers mouth the line naturally in turn."
        )
    elif dialogue:
        # A non-LTX renderer cannot synthesize a performance or soundtrack.
        # Keep the line visible in metadata/PRE, but do not claim that a
        # deterministic hold/parallax renderer will speak it.
        prompt += " The spoken line remains editorial script for later audio."
    if end_beat:
        prompt += f" The shot ends when {end_beat}."
    words = prompt.split()
    if len(words) > 110:
        prompt = " ".join(words[:110]).rstrip(" ,;:.") + "."
    return prompt


def _append_spoken_performance_cue(prompt: str, dialogue: str) -> str:
    """Keep real speech in an LLM-authored legacy motion prompt.

    The motion-direction request receives the editorial script, but a provider
    can still omit it from its structured response.  Preserve the authored
    movement while reserving enough of LTX's compact prompt budget for the
    actual spoken line.  Explicit user-written prompts remain untouched.
    """

    spoken = _limit_words(
        _clean_text(dialogue, limit=180),
        maximum=24,
    ).strip()
    if not spoken:
        return _limit_words(prompt)
    if spoken.casefold().rstrip(" .!?…") in prompt.casefold():
        return _limit_words(prompt)
    if spoken[-1:] not in {".", "!", "?", "…"}:
        spoken += "."
    spoken = spoken.replace('"', "'")
    base = _limit_words(prompt, maximum=72).rstrip()
    return _limit_words(
        f'{base} Spoken performance: "{spoken}" '
        "Visible speakers mouth the line naturally in turn.",
        maximum=110,
    )


class ComicMoviePlanner(BasePlanner):
    """Adapt comic panels into an editable, identity-linked film plan."""

    skill_type = "comic_movie"

    @staticmethod
    def _normalise_sources(comic_shots: list[dict]) -> list[_SourcePanel]:
        sources: list[_SourcePanel] = []
        seen: dict[str, int] = {}
        for index, raw in enumerate(comic_shots or []):
            if not isinstance(raw, dict):
                continue
            page = raw.get("page_number", raw.get("page", 1))
            panel = raw.get("panel_number", raw.get("panel", index + 1))
            candidate = _clean_text(
                raw.get("source_panel_id")
                or raw.get("panel_id")
                or raw.get("id")
                or f"page-{page}-panel-{panel}",
                limit=160,
            )
            duplicate = seen.get(candidate, 0)
            seen[candidate] = duplicate + 1
            source_id = candidate if duplicate == 0 else f"{candidate}--{duplicate + 1}"
            payload = dict(raw)
            payload["source_panel_id"] = source_id
            payload["source_index"] = index
            sources.append(_SourcePanel(source_id, index, payload))
        return sources

    @staticmethod
    def _primary_source(group: list[_SourcePanel]) -> _SourcePanel:
        def score(panel: _SourcePanel) -> tuple[int, int, int]:
            source = panel.payload
            text = " ".join(
                _clean_text(source.get(key), limit=300).lower()
                for key in ("narrative_role", "scene_description")
            )
            turning = int(any(term in text for term in (
                "turn", "climax", "reveal", "resolution",
                "giro", "clímax", "revela", "resolución",
            )))
            has_image = int(bool(_clean_text(source.get("image_path"), limit=400)))
            return turning, has_image, panel.source_index

        return max(group, key=score)

    def _fallback_adaptation(
        self,
        sources: list[_SourcePanel],
        *,
        target_shots: int | None = None,
    ) -> list[dict]:
        _, suggested, _ = _recommended_shot_range(len(sources))
        group_count = _clamp_int(target_shots, suggested, 1, len(sources))
        drafts: list[dict] = []
        balanced_groups = [
            sources[start:end]
            for start, end in _balanced_slices(len(sources), group_count)
            if sources[start:end]
        ]
        for group in _split_fallback_groups_for_overrides(balanced_groups):
            if not group:
                continue
            primary = self._primary_source(group)
            source = primary.payload
            action = _clean_text(
                source.get("action")
                or source.get("scene_description")
                or source.get("narrative_role")
                or "The visible story beat resolves through one clear action.",
                limit=520,
            )
            renderer = _renderer(source)
            drafts.append({
                "included": True,
                "source_panel_ids": [panel.source_id for panel in group],
                "primary_source_panel_id": primary.source_id,
                "action": action,
                "camera": _camera(source, renderer),
                "motion_level": (
                    _clamp_int(source.get("motion_level"), 1, 0, 3)
                    if source.get("motion_level_override")
                    else (
                        0 if renderer == "hold"
                        else 1 if renderer in {"parallax", "cinemagraph"}
                        else 3 if any(
                            term in action.lower() for term in _ACTION_TERMS
                        )
                        else 2
                    )
                ),
                "duration_seconds": _clamp_float(
                    source.get("duration_seconds", source.get("duration")),
                    3.0,
                    1.2,
                    8.0,
                ),
                "renderer": renderer,
                # Framing is an editorial/source contract, not something the
                # story adapter should silently invent.  ``contain`` is the
                # safe fallback until a real full-bleed reframe exists.
                "fit_mode": str(source.get("fit_mode") or "contain").lower(),
                "end_beat": _clean_text(
                    source.get("end_beat")
                    or source.get("ending_beat")
                    or "the action settles into a stable pose",
                    limit=260,
                ),
                "dialogue": _dialogue(source),
                "narrative_role": _clean_text(source.get("narrative_role"), limit=240),
                "framing": _clean_text(source.get("framing"), limit=180),
                "test_selected": any(
                    bool(panel.payload.get("test_selected"))
                    for panel in group
                ),
                "seed": (
                    source.get("seed")
                    if source.get("seed_override")
                    else None
                ),
                "motion_mode": (
                    source.get("motion_mode")
                    if source.get("motion_mode_override")
                    else None
                ),
                "end_frame_mode": (
                    source.get("end_frame_mode")
                    if source.get("end_frame_override")
                    else None
                ),
                "video_prompt": (
                    _clean_text(source.get("video_prompt"), limit=1000)
                    if (
                        source.get("video_prompt_override")
                        or (len(group) == 1 and _motion_mode(source) == "action")
                    )
                    else ""
                ),
            })
        return drafts

    def _adapt_chunk(
        self,
        comic_context: str,
        sources: list[_SourcePanel],
        *,
        target_shots: int | None = None,
    ) -> list[dict]:
        minimum, suggested, maximum = _recommended_shot_range(len(sources))
        if target_shots is not None:
            suggested = _clamp_int(target_shots, suggested, 1, len(sources) * 2)
        source_ids = [source.source_id for source in sources]
        schema = {
            "type": "array",
            "minItems": 1,
            "maxItems": max(2, len(sources) * 2),
            "items": {
                "type": "object",
                "properties": {
                    "source_panel_ids": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "string", "enum": source_ids},
                    },
                    "primary_source_panel_id": {"type": "string", "enum": source_ids},
                    "action": {"type": "string"},
                    "camera": {"type": "string"},
                    "motion_level": {"type": "integer", "minimum": 0, "maximum": 3},
                    "duration_seconds": {"type": "number", "minimum": 1.2, "maximum": 8},
                    "renderer": {"type": "string", "enum": sorted(VALID_RENDERERS)},
                    "fit_mode": {"type": "string", "enum": sorted(VALID_FIT_MODES)},
                    "end_beat": {"type": "string"},
                    "dialogue": {"type": "string"},
                    "narrative_role": {"type": "string"},
                    "framing": {"type": "string"},
                },
                "required": [
                    "source_panel_ids",
                    "primary_source_panel_id",
                    "action",
                    "camera",
                    "motion_level",
                    "duration_seconds",
                    "renderer",
                    "fit_mode",
                    "end_beat",
                    "dialogue",
                    "narrative_role",
                    "framing",
                ],
                "additionalProperties": False,
            },
        }
        compact_panels = [{
            "source_panel_id": source.source_id,
            "page": source.payload.get("page_number"),
            "panel": source.payload.get("panel_number"),
            "role": _clean_text(source.payload.get("narrative_role"), limit=180),
            "scene": _clean_text(source.payload.get("scene_description"), limit=420),
            "framing": _clean_text(source.payload.get("framing"), limit=120),
            "characters": source.payload.get("characters") or [],
            "dialogue": _dialogue(source.payload),
            "current_motion": _motion_mode(source.payload),
            "requested_fit": (
                str(source.payload.get("fit_mode") or "contain").lower()
                if str(source.payload.get("fit_mode") or "contain").lower()
                in VALID_FIT_MODES
                else "contain"
            ),
            "explicit_overrides": {
                "action": (
                    _clean_text(source.payload.get("scene_description"), limit=520)
                    if source.payload.get("action_override")
                    else None
                ),
                "renderer": (
                    source.payload.get("renderer")
                    if source.payload.get("renderer_override")
                    else None
                ),
                "fit_mode": (
                    source.payload.get("fit_mode")
                    if source.payload.get("fit_override")
                    else None
                ),
                "motion_mode": (
                    source.payload.get("motion_mode")
                    if source.payload.get("motion_mode_override")
                    else None
                ),
                "motion_level": (
                    source.payload.get("motion_level")
                    if source.payload.get("motion_level_override")
                    else None
                ),
                "duration_seconds": (
                    source.payload.get("duration_seconds")
                    if source.payload.get("duration_override")
                    else None
                ),
                "camera": (
                    source.payload.get("camera_move")
                    if source.payload.get("camera_override")
                    else None
                ),
                "video_prompt": (
                    _clean_text(source.payload.get("video_prompt"), limit=1000)
                    if source.payload.get("video_prompt_override")
                    else None
                ),
                "seed": (
                    source.payload.get("seed")
                    if source.payload.get("seed_override")
                    else None
                ),
                "end_frame_mode": (
                    source.payload.get("end_frame_mode")
                    if source.payload.get("end_frame_override")
                    else None
                ),
                "test_selected": (
                    bool(source.payload.get("test_selected"))
                    if source.payload.get("test_selected_override")
                    else None
                ),
            },
        } for source in sources]
        system = """You are the film editor adapting an existing comic into a short film.
Return ONLY a JSON array of film shots.

Panels are source material, not a mandatory one-panel/one-shot edit. You may:
- omit a redundant panel;
- fuse adjacent panels into one shot by listing all source_panel_ids;
- split an important panel into two distinct shots by repeating its ID.

List every panel that materially contributes to a fused beat, even though only
the primary panel supplies pixels. Cover at least 80 percent of the source IDs
and never omit an inciting incident, turning point, reversal, revelation,
crisis, climax or resolution. Omission is only for genuinely redundant beats.

Choose one primary_source_panel_id whose clean artwork is the actual first
frame. Every other referenced panel contributes story context only. Preserve
chronology and do not invent story events. Prefer a concise, purposeful edit:
quiet holds, restrained parallax/cinemagraphs and LTX performance/action shots
are all valid. Camera movement is rare and must not replace subject action.

For action, describe ONLY the concrete chronological change after the approved
first frame. Do not repeat visible appearance, setting, comic style, palette or
negative instructions. end_beat is the stable visible moment that finishes the
shot. Dialogue is optional spoken text, never lettering inside the image.
motion_level is 0=still, 1=ambient, 2=performance, 3=action. renderer must be
hold, parallax, cinemagraph or ltx. Preserve each primary panel's requested_fit.
Use reframe only when the source already declares it; never assume that an AI
reframe exists. Values in explicit_overrides are user locks: preserve them on
the film shot that uses that source as primary. Every source with one or more
explicit_overrides MUST be primary_source_panel_id in at least one returned
shot; listing it only as secondary context is invalid. A panel explicitly
selected as a test must remain represented by a test-selected film shot."""
        user = (
            f"MASTER STORY CONTEXT:\n{_clean_text(comic_context, limit=16000)}\n\n"
            f"SOURCE PANELS:\n{json.dumps(compact_panels, ensure_ascii=False)}\n\n"
            f"A useful editorial range for this block is roughly {minimum}-{maximum} "
            f"shots (about {suggested}), but story rhythm is more important than a "
            "fixed count. Return only the selected film shots."
        )
        try:
            generated = self._call_llm_json(
                user_prompt=user,
                system_prompt=system,
                max_tokens=max(3600, suggested * 520),
                thinking_budget=0,
                temperature=0.35,
                streaming=True,
                json_schema=schema,
            )
        except Exception as exc:
            print(f"[ComicMoviePlanner] Film adaptation failed ({exc}); using deterministic edit")
            return self._fallback_adaptation(sources, target_shots=target_shots)

        source_by_id = {source.source_id: source for source in sources}
        normalized: list[dict] = []
        covered: set[str] = set()
        for item in generated[:len(sources) * 2]:
            if not isinstance(item, dict):
                continue
            ids: list[str] = []
            for source_id in item.get("source_panel_ids") or []:
                source_id = str(source_id)
                if source_id in source_by_id and source_id not in ids:
                    ids.append(source_id)
            primary_id = str(item.get("primary_source_panel_id") or "")
            if not ids or primary_id not in ids:
                continue
            renderer = str(item.get("renderer") or "ltx").lower()
            if renderer not in VALID_RENDERERS:
                renderer = "ltx"
            primary_source = source_by_id[primary_id].payload
            linked_source_payloads = [
                source_by_id[source_id].payload for source_id in ids
            ]
            explicit_renderer = (
                str(primary_source.get("renderer") or "").lower()
                if primary_source.get("renderer_override")
                else ""
            )
            inherited_fit = str(
                primary_source.get("fit_mode") or "contain"
            ).lower()
            fit_mode = (
                inherited_fit
                if inherited_fit in VALID_FIT_MODES
                else str(item.get("fit_mode") or "contain").lower()
            )
            if fit_mode not in VALID_FIT_MODES:
                fit_mode = "contain"
            renderer = (
                explicit_renderer
                if explicit_renderer in VALID_RENDERERS
                else renderer
            )
            motion_level = _clamp_int(item.get("motion_level"), 2, 0, 3)
            if primary_source.get("motion_level_override"):
                motion_level = _clamp_int(
                    primary_source.get("motion_level"),
                    motion_level,
                    0,
                    3,
                )
            duration_seconds = _clamp_float(
                item.get("duration_seconds"),
                3,
                1.2,
                8,
            )
            if primary_source.get("duration_override"):
                duration_seconds = _clamp_float(
                    primary_source.get("duration_seconds"),
                    duration_seconds,
                    1.2,
                    20,
                )
            camera_source = dict(item)
            if primary_source.get("camera_override"):
                camera_source["camera"] = (
                    primary_source.get("camera_move")
                    or primary_source.get("camera")
                    or "locked"
                )
            if primary_source.get("motion_mode_override"):
                camera_source["motion_mode"] = primary_source.get(
                    "motion_mode"
                )
            action = (
                _clean_text(primary_source.get("scene_description"), limit=520)
                if primary_source.get("action_override")
                else _clean_text(item.get("action"), limit=520)
            )
            video_prompt = (
                _clean_text(primary_source.get("video_prompt"), limit=1200)
                if primary_source.get("video_prompt_override")
                else ""
            )
            normalized.append({
                "included": True,
                "source_panel_ids": ids,
                "primary_source_panel_id": primary_id,
                "action": action,
                "camera": _camera(camera_source, renderer),
                "motion_level": motion_level,
                "duration_seconds": duration_seconds,
                "renderer": renderer,
                "fit_mode": fit_mode,
                "end_beat": _clean_text(item.get("end_beat"), limit=260),
                "dialogue": _clean_text(
                    item.get("dialogue"),
                    limit=MAX_DIALOGUE_METADATA_CHARS,
                ),
                "narrative_role": _clean_text(item.get("narrative_role"), limit=240),
                "framing": _clean_text(item.get("framing"), limit=180),
                "video_prompt": video_prompt,
                "test_selected": any(
                    bool(payload.get("test_selected"))
                    and bool(payload.get("test_selected_override"))
                    for payload in linked_source_payloads
                ),
                "seed": (
                    primary_source.get("seed")
                    if primary_source.get("seed_override")
                    else None
                ),
                "motion_mode": (
                    primary_source.get("motion_mode")
                    if primary_source.get("motion_mode_override")
                    else None
                ),
                "end_frame_mode": (
                    primary_source.get("end_frame_mode")
                    if primary_source.get("end_frame_override")
                    else None
                ),
            })
            covered.update(ids)

        # An empty response or an implausibly tiny fragment is not a usable
        # adaptation. Omission is allowed, but losing most of a block usually
        # means the provider truncated or misunderstood the response.
        minimum_coverage = max(1, math.ceil(len(sources) * 0.80))
        critical_ids = {
            source.source_id
            for source in sources
            if _critical_story_panel(source.payload)
        }
        explicit_ids = {
            source.source_id
            for source in sources
            if _has_source_override(source.payload)
        }
        primary_ids = {
            str(item.get("primary_source_panel_id") or "")
            for item in normalized
        }
        if (
            not normalized
            or len(covered) < minimum_coverage
            or not critical_ids.issubset(covered)
            or not explicit_ids.issubset(primary_ids)
        ):
            return self._fallback_adaptation(sources, target_shots=target_shots)
        source_order = {source.source_id: source.source_index for source in sources}
        return [
            item for _, item in sorted(
                enumerate(normalized),
                key=lambda pair: (
                    min(source_order[source_id] for source_id in pair[1]["source_panel_ids"]),
                    pair[0],
                ),
            )
        ]

    def _adapt_sources(
        self,
        comic_context: str,
        sources: list[_SourcePanel],
        *,
        target_shots: int | None = None,
    ) -> list[dict]:
        if len(sources) <= 8:
            return self._fallback_adaptation(sources, target_shots=len(sources))

        # Balanced blocks bound input/output size without arbitrarily cutting
        # the final small remainder into a one-panel LLM request.
        chunk_count = max(1, math.ceil(len(sources) / 24))
        chunks = [
            sources[start:end]
            for start, end in _balanced_slices(len(sources), chunk_count)
            if sources[start:end]
        ]
        drafts: list[dict] = []
        remaining_target = target_shots
        remaining_panels = len(sources)
        for chunk in chunks:
            chunk_target = None
            if remaining_target is not None:
                chunk_target = max(
                    1,
                    round(remaining_target * len(chunk) / max(1, remaining_panels)),
                )
                remaining_target -= chunk_target
                remaining_panels -= len(chunk)
            drafts.extend(
                self._adapt_chunk(
                    comic_context,
                    chunk,
                    target_shots=chunk_target,
                )
            )
        minimum, _, maximum = _recommended_shot_range(len(sources))
        # The range is editorial guidance rather than a fixed count, but a
        # wildly sparse/truncated or bloated response is not a usable edit.
        if (
            len(drafts) < max(1, round(minimum * 0.75))
            or len(drafts) > max(len(sources), round(maximum * 1.35))
        ):
            return self._fallback_adaptation(sources, target_shots=target_shots)
        return drafts

    @staticmethod
    def _manual_drafts(
        film_shots: list[dict],
        sources: list[_SourcePanel],
    ) -> list[dict]:
        known_ids = {source.source_id for source in sources}
        drafts: list[dict] = []
        for index, raw in enumerate(film_shots or []):
            if not isinstance(raw, dict) or raw.get("included") is False:
                continue
            ids = [
                str(source_id)
                for source_id in (raw.get("source_panel_ids") or [])
                if str(source_id) in known_ids
            ]
            if not ids and index < len(sources):
                ids = [sources[index].source_id]
            if not ids:
                continue
            primary_id = str(raw.get("primary_source_panel_id") or ids[0])
            if primary_id not in ids:
                primary_id = ids[0]
            renderer = _renderer(raw)
            drafts.append({
                **raw,
                "included": True,
                "source_panel_ids": ids,
                "primary_source_panel_id": primary_id,
                "renderer": renderer,
                "camera": _camera(raw, renderer),
                "motion_level": _clamp_int(
                    raw.get("motion_level"),
                    0 if renderer == "hold" else 1 if renderer != "ltx" else 2,
                    0,
                    3,
                ),
                "duration_seconds": _clamp_float(
                    raw.get("duration_seconds", raw.get("duration")),
                    3,
                    1.2,
                    20,
                ),
                "fit_mode": (
                    str(raw.get("fit_mode") or "contain").lower()
                    if str(raw.get("fit_mode") or "contain").lower() in VALID_FIT_MODES
                    else "contain"
                ),
                "action": _clean_text(
                    raw.get("action") or raw.get("scene_description"),
                    limit=520,
                ),
                "end_beat": _clean_text(
                    raw.get("end_beat") or raw.get("ending_beat"),
                    limit=260,
                ),
                "dialogue": _dialogue(raw),
            })
        return drafts

    def _legacy_treatments(
        self,
        comic_context: str,
        sources: list[_SourcePanel],
    ) -> dict[int, str]:
        treatments: dict[int, str] = {}
        missing: list[_SourcePanel] = []
        for source in sources:
            payload = source.payload
            mode = _motion_mode(payload)
            if mode == "living-still":
                treatments[source.source_index] = _LIVING_STILL_PROMPT
            else:
                reviewed = _clean_text(payload.get("video_prompt"), limit=1400)
                if mode == "action" and reviewed:
                    treatments[source.source_index] = reviewed
                else:
                    missing.append(source)
        if not missing:
            return treatments

        system = """You are adapting finished comic panels into image-to-video shots.
Return ONLY the requested JSON array, one object for every source panel.

The panel is the ACTUAL FIRST FRAME. EACH PANEL MUST PLAY AS ITS OWN SHOT,
NOT AS A TRANSITION TO THE NEXT PANEL. Describe only the concrete changes after
that first frame: one meaningful chronological action, restrained secondary
motion, deliberate camera behavior and the stable end beat. Camera movement is secondary
to performance. Never repeat appearance, setting, style, palette or
linework already visible in the image. Do not write negative instructions,
captions, subtitles or lettering in video_prompt.

When motion_mode is "contextual", keep the camera locked. When requested_camera
is none/static/locked-off, action stays inside the fixed frame. One continuous
shot, no montage or internal cuts. Keep every video_prompt below 110 words."""
        missing_indices = {source.source_index for source in missing}
        # A long storyboard used to submit all 96 panels, their images and an
        # approximately 40K-token response contract in one request. Remote
        # providers commonly returned an empty/truncated response, forcing
        # nearly every shot onto the generic fallback. Keep each multimodal
        # request bounded while preserving the immutable source_index contract.
        # Twelve panels is large enough to retain local sequence context and
        # small enough for structured output and image payloads to remain
        # practical across local and OpenAI-compatible providers.
        for batch_start in range(0, len(missing), 12):
            batch = missing[batch_start:batch_start + 12]
            schema = {
                "type": "array",
                "minItems": len(batch),
                "maxItems": len(batch),
                "items": {
                    "type": "object",
                    "properties": {
                        "source_index": {"type": "integer"},
                        "video_prompt": {"type": "string"},
                    },
                    "required": ["source_index", "video_prompt"],
                    "additionalProperties": False,
                },
            }
            items = [{
                "source_index": source.source_index,
                "page": source.payload.get("page_number"),
                "panel": source.payload.get("panel_number"),
                "duration_seconds": source.payload.get("duration", 3),
                "motion_mode": _motion_mode(source.payload),
                "narrative_role": source.payload.get("narrative_role", ""),
                "scene": source.payload.get("scene_description", ""),
                "first_frame_visual_description": source.payload.get(
                    "image_prompt", ""
                ),
                # Captions and SFX stay editorial metadata; only actual
                # speaker lines may influence an I2V performance prompt.
                "script_for_performance": _dialogue(source.payload),
                "framing": source.payload.get("framing", ""),
                "requested_camera": (
                    source.payload.get("camera_move") or "none"
                ),
                "characters": source.payload.get("characters", []),
            } for source in batch]
            user = (
                "MASTER COMIC CONTEXT:\n"
                f"{_clean_text(comic_context, limit=24000)}\n\n"
                "PANELS IN THIS BATCH:\n"
                f"{json.dumps(items, ensure_ascii=False)}\n\n"
                f"Return exactly {len(batch)} objects and preserve source_index."
            )
            try:
                generated = self._call_llm_json(
                    user_prompt=user,
                    system_prompt=system,
                    max_tokens=max(2048, len(batch) * 420),
                    thinking_budget=0,
                    temperature=0.4,
                    streaming=True,
                    json_schema=schema,
                    image_paths=[
                        str(source.payload.get("image_path") or "")
                        for source in batch
                        if str(source.payload.get("image_path") or "").strip()
                    ],
                )
            except Exception as exc:
                print(
                    "[ComicMoviePlanner] Motion direction batch "
                    f"{batch_start // 12 + 1} failed ({exc}); using fallback "
                    "only for that batch"
                )
                generated = []
            for item in generated:
                if not isinstance(item, dict):
                    continue
                try:
                    source_index = int(item.get("source_index"))
                except (TypeError, ValueError):
                    continue
                prompt = _clean_text(item.get("video_prompt"), limit=1200)
                if source_index in missing_indices and prompt:
                    treatments[source_index] = _limit_words(prompt)
        return treatments

    def plan(
        self,
        comic_context: str,
        comic_shots: list[dict],
        film_shots: list[dict] | None = None,
        adapt_to_film: bool = True,
        target_shots: int | None = None,
        visual_style: str = "",
        **_: Any,
    ) -> ProductionPlan:
        sources = self._normalise_sources(comic_shots)
        if not sources:
            return ProductionPlan(skill_type=self.skill_type, shots=[], total_duration_sec=0)
        # Public clients use zero to mean "Auto". Treat it exactly like an
        # omitted target instead of collapsing each planning chunk to one
        # giant shot.
        try:
            if target_shots is not None and int(target_shots) <= 0:
                target_shots = None
        except (TypeError, ValueError):
            target_shots = None

        if film_shots is not None:
            drafts = self._manual_drafts(film_shots, sources)
            adapted = True
        elif adapt_to_film and len(sources) > 8:
            drafts = self._adapt_sources(
                comic_context,
                sources,
                target_shots=target_shots,
            )
            adapted = True
        else:
            drafts = self._fallback_adaptation(sources, target_shots=len(sources))
            adapted = False

        source_by_id = {source.source_id: source for source in sources}
        legacy_treatments = (
            {}
            if adapted
            else self._legacy_treatments(comic_context, sources)
        )
        occurrence_by_group: dict[str, int] = {}
        shots: list[ShotPlan] = []

        for draft in drafts:
            if draft.get("included") is False:
                continue
            source_panel_ids = [
                source_id for source_id in draft.get("source_panel_ids") or []
                if source_id in source_by_id
            ]
            if not source_panel_ids:
                continue
            primary_id = str(draft.get("primary_source_panel_id") or source_panel_ids[0])
            if primary_id not in source_panel_ids:
                primary_id = source_panel_ids[0]
            primary = source_by_id[primary_id]
            linked_sources = [source_by_id[source_id] for source_id in source_panel_ids]
            source = primary.payload

            renderer = str(draft.get("renderer") or _renderer(source)).lower()
            if renderer not in VALID_RENDERERS:
                renderer = "ltx"
            camera = _camera(draft, renderer)
            motion_level = _clamp_int(
                draft.get("motion_level"),
                0 if renderer == "hold" else 1 if renderer != "ltx" else 2,
                0,
                3,
            )
            duration = _clamp_float(
                draft.get("duration_seconds", draft.get("duration")),
                3,
                1.2,
                20,
            )
            action = _clean_text(
                draft.get("action")
                or source.get("scene_description")
                or source.get("narrative_role")
                or "The visible subject completes one clear action",
                limit=520,
            )
            end_beat = _clean_text(
                draft.get("end_beat")
                or source.get("end_beat")
                or source.get("ending_beat")
                or "the action settles into a stable pose",
                limit=260,
            )
            dialogue = _clean_text(
                draft.get("dialogue") or _dialogue(source),
                limit=MAX_DIALOGUE_METADATA_CHARS,
            )
            fit_mode = str(draft.get("fit_mode") or "contain").lower()
            if fit_mode not in VALID_FIT_MODES:
                fit_mode = "contain"

            group_key = "|".join(source_panel_ids)
            occurrence = occurrence_by_group.get(group_key, 0)
            occurrence_by_group[group_key] = occurrence + 1
            shot_id = _stable_shot_id(
                source_panel_ids,
                occurrence,
                explicit=draft.get("shot_id"),
            )
            seed = _clamp_int(
                draft.get("seed"),
                _stable_seed(shot_id),
                0,
                2_147_483_647,
            )
            risk_tags = classify_comic_shot_risks(
                linked.payload for linked in linked_sources
            )
            legacy_mode = (
                _motion_mode(source)
                if not adapted
                else (
                    "living-still" if renderer in {"hold", "cinemagraph"}
                    else "contextual" if renderer == "parallax"
                    else "action"
                )
            )
            requested_motion_mode = str(
                draft.get("motion_mode") or ""
            ).strip().lower()
            if requested_motion_mode in {
                "living-still",
                "living_still",
                "still",
            }:
                legacy_mode = "living-still"
            elif requested_motion_mode in {
                "contextual",
                "context",
                "directed",
            }:
                legacy_mode = "contextual"
            elif requested_motion_mode == "action":
                legacy_mode = "action"
            explicit_prompt = _clean_text(draft.get("video_prompt"), limit=1400)
            legacy_generated = legacy_treatments.get(primary.source_index, "")
            if explicit_prompt:
                # A reviewed PRE/manual prompt is the user's source of truth.
                video_prompt = explicit_prompt
            elif legacy_generated:
                video_prompt = (
                    _append_spoken_performance_cue(
                        legacy_generated,
                        dialogue,
                    )
                    if renderer in {"ltx", "cinemagraph"}
                    else legacy_generated
                )
            else:
                video_prompt = (
                    ("Starting from the supplied comic artwork, " if not adapted else "")
                    + _motion_prompt(
                        renderer=renderer,
                        action=action,
                        camera=camera,
                        end_beat=end_beat,
                        dialogue=dialogue,
                    )
                )
            if not video_prompt:
                video_prompt = (
                    "Starting from the supplied comic artwork, "
                    + _motion_prompt(
                        renderer=renderer,
                        action=action,
                        camera=camera,
                        end_beat=end_beat,
                        dialogue=dialogue,
                    )
                )

            characters: list[str] = []
            for linked in linked_sources:
                for character in linked.payload.get("characters") or []:
                    character = str(character).strip()
                    if character and character not in characters:
                        characters.append(character)
            narrative_role = _clean_text(
                draft.get("narrative_role")
                or source.get("narrative_role")
                or f"Film beat from {primary_id}",
                limit=240,
            )
            framing = _clean_text(
                draft.get("framing")
                or source.get("framing")
                or "match the prepared video keyframe",
                limit=180,
            )
            shot_visual_style = _clean_text(
                source.get("visual_style") or visual_style,
                limit=480,
            )
            metadata = {
                "included": True,
                "renderer": renderer,
                "source_panel_ids": source_panel_ids,
                "source_panel_indices": [linked.source_index for linked in linked_sources],
                "primary_source_panel_id": primary_id,
                "primary_source_index": primary.source_index,
                "context_source_panel_ids": [
                    source_id
                    for source_id in source_panel_ids
                    if source_id != primary_id
                ],
                "provided_image_path": source.get("image_path"),
                "action": action,
                "camera": camera,
                "motion_level": motion_level,
                "duration_seconds": duration,
                "fit_mode": fit_mode,
                "test_selected": bool(draft.get("test_selected")),
                "seed": seed,
                "end_beat": end_beat,
                "dialogue": dialogue,
                "risk_tags": risk_tags,
                "motion_mode": legacy_mode,
                "end_frame_mode": draft.get("end_frame_mode"),
                "page_number": source.get("page_number"),
                "panel_number": source.get("panel_number"),
                "adapted_from_comic": adapted,
                # The first frame already defines appearance. This tells the
                # I2V renderer not to prepend the visual style again.
                "motion_only_prompt": True,
            }
            shots.append(ShotPlan(
                shot_id=shot_id,
                index=len(shots),
                duration_sec=duration,
                skill_type=self.skill_type,
                scene_goal=narrative_role,
                narrative_role=narrative_role,
                scene_type="dialogue" if dialogue else renderer,
                source_mode_preference="i2v",
                image_strategy="none",
                continuity_strategy="independent",
                subjects_on_screen=[
                    SubjectRef(visual_description=name, character_id=name)
                    for name in characters
                ],
                spatial_setup=framing,
                environment="Use the prepared source panel as the complete first frame.",
                visual_style=shot_visual_style,
                lighting="Use the lighting already established in the prepared first frame.",
                mood=narrative_role or "cinematic",
                action_beats=[action],
                camera_plan=CameraPlan(
                    framing=framing,
                    movement=_MOVEMENT_LABELS.get(camera, camera),
                    movement_intensity=(
                        "static" if camera in {"locked", "none", "static"}
                        else "subtle" if motion_level <= 2
                        else "moderate"
                    ),
                ),
                audio_plan=AudioPlan(
                    mode="dialogue_driven" if dialogue else "ambient_only",
                    lip_sync_critical=False,
                ),
                ending_beat=end_beat,
                metadata=metadata,
                image_prompt=_clean_text(
                    source.get("image_prompt") or source.get("scene_description"),
                    limit=1100,
                ),
                video_prompt=video_prompt,
                visual_changes=[action],
                image_source="original",
                keyframe_prompts=[],
                window_prompts=[],
            ))

        if not any(
            bool((shot.metadata or {}).get("test_selected"))
            for shot in shots
        ):
            for index in select_representative_shot_indices(shots, max_count=6):
                if shots[index].metadata is not None:
                    shots[index].metadata["test_selected"] = True

        return ProductionPlan(
            skill_type=self.skill_type,
            shots=shots,
            title=str(sources[0].payload.get("comic_title") or "Comic movie"),
            global_style=(
                _clean_text(visual_style, limit=480)
                or "Use the prepared comic keyframes as the visual source of truth."
            ),
            total_duration_sec=sum(shot.duration_sec for shot in shots),
            continuity_notes=[
                "Film shots retain stable source_panel_ids and a primary source image.",
                "The edit may omit, fuse or split comic panels without changing story chronology.",
                "I2V prompts describe only motion after the approved first frame.",
            ],
        )
