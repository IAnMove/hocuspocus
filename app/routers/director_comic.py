"""Director comic HTTP routes for the full server.

The core server has no Director comic routes, so only the full server mounts
this router. Handlers stay module-level so a move keeps the launch function
name, and the served route table names this file. This module does not import
WanGP or ``_launch_runtime``.
"""
from __future__ import annotations

import copy
import json
import os
import time
import uuid

from fastapi import APIRouter, HTTPException

import services.director_comic_jobs as jobs
from services.comic_director_json import _generate_comic_director_json
from services.comic_helpers import (
    _COMIC_TEXT_PAGE_SCHEMA,
    _comic_page_has_probable_english_drift,
    _comic_page_problem,
    _comic_page_summary,
    _comic_writing_llm,
    _enforce_comic_page_text_budget,
    _normalize_comic_panel_arrays,
    _normalize_comic_panel_character_ids,
    _repair_comic_page_language,
)
from services.director_comic_jobs import (
    _comic_plan_active_jobs,
    _comic_plan_checkpoint_dir,
    _comic_plan_job_update,
    _comic_plan_jobs,
    _comic_plan_jobs_lock,
    _load_comic_plan_job,
    _persist_comic_plan_job,
    _start_comic_plan_worker,
)
from services.story_lab_schema import _storyboard_page_problem

# Injected by bind_director_comic_runtime. None until the full server binds them.
_ensure_llm_loaded = None
_get_active_workspace = None
_publish_generic_legacy_task = None
_reset_canonical_task_for_resume = None


_COMIC_PLAN_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "title",
        "logline",
        "synopsis",
        "storyStructure",
        "styleBible",
        "characters",
        "pages",
    ],
    "properties": {
        "title": {"type": "string"},
        "logline": {"type": "string"},
        "synopsis": {"type": "string"},
        "storyStructure": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "pageNumber",
                    "stage",
                    "goal",
                    "turningPoint",
                ],
                "properties": {
                    "pageNumber": {"type": "integer"},
                    "stage": {"type": "string"},
                    "goal": {"type": "string"},
                    "turningPoint": {"type": "string"},
                },
            },
        },
        "styleBible": {
            "type": "string",
            "maxLength": 900,
            "description": (
                "Optional visual continuity bible. Return an empty string when a dedicated "
                "bible would not materially improve visual consistency."
            ),
        },
        "characters": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["id", "name", "description", "locked"],
            "properties": {
                "id": {"type": "string"}, "name": {"type": "string"},
                "description": {"type": "string"}, "locked": {"type": "boolean"},
                "wardrobe": {"type": "string"}, "referenceAssetId": {"type": "string"},
            },
        }},
        "pages": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["pageNumber", "layoutHint", "panels"],
            "properties": {
                "pageNumber": {"type": "integer"}, "layoutHint": {"type": "string"},
                "panels": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False,
                    "required": ["id", "order", "narrativeRole", "sceneDescription", "imagePrompt",
                                 "characters", "framing", "dialogue", "captions", "soundEffects",
                                 "continuityNotes"],
                    "properties": {
                        "id": {"type": "string"}, "order": {"type": "integer"},
                        "narrativeRole": {"type": "string"}, "sceneDescription": {"type": "string"},
                        "imagePrompt": {"type": "string", "maxLength": 700}, "characters": {"type": "array", "items": {"type": "string"}},
                        "framing": {"type": "string"}, "continuityNotes": {"type": "string"},
                        "videoPrompt": {"type": "string", "maxLength": 1400},
                        "durationSeconds": {"type": "number", "minimum": 0.8, "maximum": 20},
                        "cameraMove": {
                            "type": "string",
                            "enum": ["none", "push-in", "pull-out", "pan-left", "pan-right"],
                        },
                        "captions": {"type": "array", "items": {"type": "string"}},
                        "soundEffects": {"type": "array", "items": {"type": "string"}},
                        "dialogue": {"type": "array", "items": {
                            "type": "object", "additionalProperties": False,
                            "required": ["text", "bubbleType"],
                            "properties": {
                                "speakerId": {"type": "string"}, "text": {"type": "string", "minLength": 1},
                                "bubbleType": {"type": "string"},
                            },
                        }},
                    },
                }},
            },
        }},
    },
}

_COMIC_BIBLE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["title", "logline", "synopsis", "styleBible", "characters"],
    "properties": {
        key: value
        for key, value in _COMIC_PLAN_SCHEMA["properties"].items()
        if key != "pages"
    },
}
_COMIC_PAGE_SCHEMA = _COMIC_PLAN_SCHEMA["properties"]["pages"]["items"]


def director_comic_plan(body: dict, job_id: str | None = None):
    """Create a strict, editable comic plan without generating images."""
    premise = str(body.get("premise") or "").strip()
    page_count = max(1, min(100, int(body.get("pageCount") or 1)))
    production_mode = (
        "storyboard"
        if str(body.get("productionMode") or "").strip().lower() == "storyboard"
        else "comic"
    )
    is_storyboard = production_mode == "storyboard"
    panels_per_page = (
        1
        if is_storyboard
        else max(1, min(12, int(body.get("panelsPerPage") or 4)))
    )
    storyboard_aspect = (
        "portrait"
        if str(body.get("storyboardAspect") or "").strip().lower() == "portrait"
        else "landscape"
    )
    storyboard_quality = (
        "final"
        if str(body.get("storyboardQuality") or "").strip().lower() == "final"
        else "draft"
    )
    storyboard_resolution = {
        ("landscape", "draft"): "832x448",
        ("landscape", "final"): "1280x704",
        ("portrait", "draft"): "448x832",
        ("portrait", "final"): "704x1280",
    }[(storyboard_aspect, storyboard_quality)]
    if not premise:
        raise HTTPException(status_code=400, detail="Comic premise is required")
    characters = body.get("characters") if isinstance(body.get("characters"), list) else []
    dialogue_density = str(body.get("dialogueDensity") or "medium").lower()
    requested_language = str(body.get("language") or "English").strip()
    manual_art_style = str(body.get("artStyle") or "").strip()
    manual_world_context = str(body.get("worldContext") or "").strip()
    manual_forbidden = str(body.get("forbiddenElements") or "").strip()
    story_context = str(body.get("storyContext") or "").strip()[:50000]
    source_story = body.get("sourceStory") if isinstance(body.get("sourceStory"), dict) else {}
    writing_llm = _comic_writing_llm(body)
    tone_line = f"Tone: {tone}\n" if (tone := str(body.get("tone") or "").strip()) else ""
    shared_brief = f"""Production mode: {production_mode}
Premise: {premise}
Source Story Lab project: {json.dumps(source_story, ensure_ascii=False) if source_story else 'not supplied'}
Source story bible / adaptation brief:
{story_context or 'not supplied'}
{"Exact storyboard shot count" if is_storyboard else "Exact page count"}: {page_count}
{"Exactly one clean first-frame image per shot." if is_storyboard else f"Exactly {panels_per_page} panels per page."}
{f"Video canvas: {storyboard_aspect}, {storyboard_quality}, {storyboard_resolution}. Every generated frame must use this same aspect ratio." if is_storyboard else ""}
Language for ALL reader-facing dialogue/captions: {requested_language}
Genre: {body.get('genre', 'Adventure')}
{tone_line}Audience: {body.get('audience', 'General')}
User art-style preference (highest-priority visual lock; it overrides conflicting inherited
medium, rendering or palette guidance): {manual_art_style or 'not provided; choose an appropriate treatment'}
User world / period / location override: {manual_world_context or 'not provided'}
User forbidden-elements override: {manual_forbidden or 'not provided'}
If an inherited visual exclusion conflicts with the explicit art-style preference, keep the
art-style preference and ignore only that conflicting exclusion; preserve all story and
continuity exclusions that do not conflict.
Dialogue density: {body.get('dialogueDensity', 'medium')}
Ending requirement: {body.get('ending') or 'a satisfying ending'}
Locked character bible: {json.dumps(characters, ensure_ascii=False)}"""
    system_prompt = """You are HocusPocus Lab Comic Director, a professional comics writer, visual
storyteller and continuity editor. Return only the JSON object required by the supplied schema.
Keep every field concise and use stable character IDs."""
    try:
        if not writing_llm:
            _ensure_llm_loaded()
        checkpoint = {}
        if job_id:
            with _comic_plan_jobs_lock:
                checkpoint = copy.deepcopy(
                    (_comic_plan_jobs.get(job_id) or {}).get("planningCheckpoint") or {}
                )
        if job_id:
            _comic_plan_job_update(
                job_id,
                status="planning_bible",
                message="Writing the story outline and character bible…",
                current=0,
                total=page_count,
                stage="bible",
            )
        bible = checkpoint.get("bible")
        if (
            not isinstance(bible, dict)
            or not isinstance(bible.get("storyStructure"), list)
            or len(bible["storyStructure"]) != page_count
        ):
            bible_schema = copy.deepcopy(_COMIC_BIBLE_SCHEMA)
            bible_schema["properties"]["storyStructure"]["minItems"] = page_count
            bible_schema["properties"]["storyStructure"]["maxItems"] = page_count
            bible = _generate_comic_director_json(
                prompt=f"""Create the compact story and character bible for a {"video storyboard" if is_storyboard else "sequential comic"}.
{shared_brief}

When a source story bible is supplied, its facts, character identities, relationships,
world rules, long-term arcs, theme and eventual ending are canon. The Premise above is the
production brief for THIS comic. If it asks for a self-contained chapter or side incident,
invent one compact conflict that fits the canon: do not summarize every master beat, replay
the complete source plot, finish the long-term arcs or reach the master ending. User edits in
the production brief override inferred details but never silently rewrite the supplied canon.

The synopsis must cover the complete arc across all {page_count} {"shots" if is_storyboard else "pages"}. Use concrete,
repeatable visual descriptions for characters and wardrobe.

Create exactly one storyStructure entry for every {"shot" if is_storyboard else "page"}. Together they must form a causal,
readable dramatic arc rather than a collection of unrelated scenes. Cover these fundamental
stages, combining adjacent stages when the comic is short and distributing development across
multiple pages when it is long:
1. Setup: protagonist, normal world, concrete desire and stakes.
2. Inciting incident: a visible event breaks the status quo and forces a choice.
3. Rising action: attempts, obstacles and consequences escalate through cause and effect.
4. Midpoint or reversal: new information or a costly decision changes the direction.
5. Crisis and climax: the central conflict reaches an irreversible decisive action.
6. Resolution: show the consequence, emotional change and a clear final image.
Each beat must advance the same conflict, specify its dramatic goal, and end with a
turning point that motivates the following {"shot" if is_storyboard else "page"}. Do not repeat the same revelation or climax.

Decide whether a dedicated visual continuity bible materially helps this particular story.
It normally helps historical, period, fantasy, science-fiction and strongly art-directed work.
When it helps, styleBible must state only applicable facts: era or year, geography,
architecture, materials, technology, props, wardrobe, rendering medium, linework, palette,
lighting, forbidden anachronisms and continuity anchors. Respect every user override exactly.
Never put page count, panel count, comic-page layout, grids or lettering instructions in
styleBible: it is sent to an image generator for one individual illustration at a time.
When a dedicated bible is unnecessary, return styleBible as an empty string. Do not fill it
with generic advice or invented restrictions merely because the field exists.""",
                system_prompt=system_prompt,
                schema=bible_schema,
                max_new_tokens=max(1400, 900 + page_count * 120),
                stage="the story bible",
                llm_override=writing_llm,
            )
            if job_id:
                _comic_plan_job_update(
                    job_id,
                    planningCheckpoint={"bible": bible, "pages": []},
                    message="Story bible checkpoint saved.",
                )
        planned_pages = checkpoint.get("pages")
        if not isinstance(planned_pages, list):
            planned_pages = []
        planned_pages = [
            page for page in planned_pages[:page_count]
            if isinstance(page, dict)
        ]
        page_schema = copy.deepcopy(_COMIC_PAGE_SCHEMA)
        page_schema["properties"]["panels"]["minItems"] = panels_per_page
        page_schema["properties"]["panels"]["maxItems"] = panels_per_page
        panel_properties = page_schema["properties"]["panels"]["items"]["properties"]
        panel_required = page_schema["properties"]["panels"]["items"]["required"]
        dialogue_schema = panel_properties["dialogue"]
        if is_storyboard:
            for required_field in ("videoPrompt", "durationSeconds", "cameraMove"):
                if required_field not in panel_required:
                    panel_required.append(required_field)
            dialogue_schema["maxItems"] = 0
            panel_properties["captions"]["maxItems"] = 0
            panel_properties["soundEffects"]["maxItems"] = 0
        else:
            dialogue_schema["maxItems"] = 2 if dialogue_density == "high" else 1
            panel_properties["captions"]["maxItems"] = 1
            panel_properties["soundEffects"]["maxItems"] = 1
        for page_index in range(page_count):
            page_number = page_index + 1
            text_panel_ratio = {"low": 0.3, "medium": 0.55, "high": 0.8}.get(
                dialogue_density,
                0.55,
            )
            text_panel_budget = max(
                1,
                min(panels_per_page, int(panels_per_page * text_panel_ratio + 0.999)),
            )
            per_panel_text_limit = 0 if is_storyboard else (1 if panels_per_page >= 7 else 2)
            existing_page = planned_pages[page_index] if page_index < len(planned_pages) else None
            existing_problem = (
                _storyboard_page_problem(existing_page, panels_per_page)
                if is_storyboard
                else _comic_page_problem(existing_page, panels_per_page)
            )
            if (
                existing_page is not None
                and existing_problem is None
                and _comic_page_has_probable_english_drift(
                    existing_page,
                    requested_language,
                )
            ):
                existing_problem = (
                    f"some reader-facing lines are not written in {requested_language}"
                )
            if existing_page is not None and existing_problem is None:
                continue
            previous_page = planned_pages[page_index - 1] if page_index > 0 else None
            next_page = (
                planned_pages[page_index + 1]
                if page_index + 1 < len(planned_pages)
                else None
            )
            previous_summary = _comic_page_summary(previous_page)
            next_summary = _comic_page_summary(next_page)
            continuity = (
                f"Continuity entering from page {page_number - 1}: {previous_summary}"
                if previous_summary
                else "Opening page; establish the premise and visual geography."
            )
            future_continuity = (
                f"Already-saved page {page_number + 1} follows with these continuity anchors: "
                f"{next_summary}. Make this repaired page lead naturally into them."
                if next_summary
                else "No later saved page constrains this page."
            )
            assigned_beat = (
                bible.get("storyStructure", [])[page_index]
                if page_index < len(bible.get("storyStructure", []))
                else {}
            )
            if is_storyboard:
                production_rules = f"""This page is storyboard shot {page_number} and contains exactly one panel.
The panel is a clean, full-bleed FIRST FRAME for a {storyboard_aspect} {storyboard_resolution}
video. imagePrompt must describe a frozen initial state before any action begins, use the
canonical appearance of every visible character, preserve screen direction, and describe
only the held pose at the instant before the shot's action—not the later motion. It must
request one image only: never a storyboard sheet, page, grid, collage,
split screen, inset, frame, border, speech bubble, caption, subtitle, logo or watermark.

videoPrompt is the actual prompt that will be sent to LTX image-to-video. Write one literal,
chronological continuous shot under 180 words. Start from the supplied first frame and specify
character performance and gestures, environmental motion, camera movement, timing, any spoken
dialogue in quotation marks, and the final visual beat. No montage, cuts, alternate angles,
new written text or redesign of the opening composition. Keep the established rendering
medium—including anime or cel shading—throughout; never drift to photorealism or 3D.

Choose durationSeconds between 2 and 10 seconds according to the amount of visible action.
Choose cameraMove from none, push-in, pull-out, pan-left or pan-right. Keep captions, dialogue
and soundEffects as empty arrays: spoken dialogue belongs inside videoPrompt for performance
and audio generation, never as lettering on the first frame. List character IDs in visual
priority order and make imagePrompt self-contained and shorter than 700 characters."""
            else:
                production_rules = f"""Every imagePrompt describes exactly ONE full-bleed
illustration for ONE panel, includes framing and repeats the canonical description of every
character shown. Never ask the image model to render dialogue, captions, bubbles, lettering,
logos or watermarks. Put readable text only in dialogue, captions or soundEffects. Keep each
imagePrompt concise and below 700 characters. Never copy the complete styleBible into
imagePrompt; include only details visibly needed for that shot. Never mention the comic's
page count, panel count, page layout, grids, collages, split screens, inset panels or borders
in imagePrompt. Every imagePrompt must be self-contained. Include the chosen art treatment
and only the world details that visibly apply to that shot. Repeat exact era/year,
architecture, technology and wardrobe when the premise or styleBible establishes them; do
not invent a period constraint for contemporary, abstract or setting-neutral work. Preserve
props and screen direction.
List panel character IDs in visual-priority order. The first ID is the identity anchor for
image providers that accept only one character reference, so place the dominant or closest
character first while still describing every visible character in imagePrompt.
Lettering budget per panel: zero or one short caption, zero or
{"two" if dialogue_density == "high" else "one"} short dialogue lines, and zero or one short
sound effect, with {per_panel_text_limit} reader-facing text element
{"s" if per_panel_text_limit != 1 else ""} maximum in total. This page may use lettering in
at most {text_panel_budget} of its {panels_per_page} panels; all remaining panels MUST be
silent. Silence is intentional visual storytelling. Prefer caption and dialogue; include a
sound effect only when the panel's total budget permits it.
Never repeat or paraphrase the same line in multiple fields. Complete all
{panels_per_page} panels before adding detail to any one panel.
CRITICAL LANGUAGE LOCK: before returning JSON, scan every caption and dialogue line and
ensure it is written in {requested_language}. Do not fall back to English unless the requested
language itself is English. Keep only proper names unchanged.
Dialogue may be omitted whenever silent storytelling is stronger."""
            if job_id:
                _comic_plan_job_update(
                    job_id,
                    status="planning_page",
                    message=(
                        f"Repairing invalid {'shot' if is_storyboard else 'page'} {page_number} of {page_count}: "
                        f"{existing_problem}…"
                        if existing_page is not None
                        else f"Writing {'shot' if is_storyboard else 'page'} {page_number} of {page_count}…"
                    ),
                    current=page_index,
                    total=page_count,
                    stage="page",
                    page=page_number,
                )
            page = None
            page_problem = existing_problem
            for attempt in range(1, 4):
                page = _generate_comic_director_json(
                    prompt=f"""Write {"storyboard shot" if is_storyboard else "page"} {page_number} of this {"video storyboard" if is_storyboard else "comic"}.
{shared_brief}
Story bible: {json.dumps(bible, ensure_ascii=False)}
MANDATORY STORY BEAT FOR THIS {"SHOT" if is_storyboard else "PAGE"}: {json.dumps(assigned_beat, ensure_ascii=False)}
{continuity}
{future_continuity}

Return one page with exactly {panels_per_page} panels and pageNumber {page_number}.
Every panel must causally develop this assigned beat and land on its turningPoint.
Do not jump ahead to a later climax or repeat an earlier resolution.
{production_rules}
{f"A previous attempt was rejected because {page_problem}. Return a complete corrected page." if page_problem else ""}
""",
                    system_prompt=system_prompt,
                    schema=page_schema,
                    max_new_tokens=min(5000, max(1800, 700 + panels_per_page * 420)),
                    stage=f"page {page_number}, attempt {attempt}",
                    llm_override=writing_llm,
                )
                page_problem = (
                    _storyboard_page_problem(page, panels_per_page)
                    if is_storyboard
                    else _comic_page_problem(page, panels_per_page)
                )
                if (
                    page_problem is None
                    and _comic_page_has_probable_english_drift(
                        page,
                        requested_language,
                    )
                ):
                    if job_id:
                        _comic_plan_job_update(
                            job_id,
                            status="planning_page",
                            message=(
                                f"Correcting page {page_number} lettering to "
                                f"{requested_language}…"
                            ),
                            current=page_index,
                            total=page_count,
                            stage="page",
                            page=page_number,
                        )
                    page = _repair_comic_page_language(
                        page,
                        requested_language,
                        page_number,
                        writing_llm,
                    )
                    if _comic_page_has_probable_english_drift(
                        page,
                        requested_language,
                    ):
                        page_problem = (
                            f"some reader-facing lines are not written in "
                            f"{requested_language}"
                        )
                if page_problem is None:
                    break
                if job_id:
                    _comic_plan_job_update(
                        job_id,
                        status="planning_page",
                        message=(
                            f"Page {page_number} attempt {attempt} was incomplete "
                            f"({page_problem}); retrying…"
                        ),
                        current=page_index,
                        total=page_count,
                        stage="page",
                        page=page_number,
                    )
            if page is None or page_problem is not None:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"Page {page_number} remained invalid after 3 attempts: "
                        f"{page_problem}. Resume to try this page again."
                    ),
                )
            # Keep reusable art direction separate from each shot. The image
            # client adds only the compact context its provider can accept.
            for panel in page.get("panels", []):
                if not isinstance(panel, dict):
                    continue
                panel["imagePrompt"] = str(panel.get("imagePrompt") or "").strip()
            if page_index < len(planned_pages):
                planned_pages[page_index] = page
            else:
                planned_pages.append(page)
            if job_id:
                _comic_plan_job_update(
                    job_id,
                    planningCheckpoint={
                        "bible": bible,
                        "pages": copy.deepcopy(planned_pages),
                    },
                    message=f"{'Shot' if is_storyboard else 'Page'} {page_number} checkpoint saved.",
                    current=page_number,
                    total=page_count,
                )
            if job_id:
                _comic_plan_job_update(
                    job_id,
                    status="planning_page",
                    message=f"{'Shot' if is_storyboard else 'Page'} {page_number} of {page_count} completed.",
                    current=page_number,
                    total=page_count,
                    stage="page",
                    page=page_number,
                )
        planned = {**bible, "pages": planned_pages}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Comic planning failed: {exc}") from exc
    pages = planned.get("pages")
    if not isinstance(pages, list) or len(pages) != page_count:
        raise HTTPException(status_code=422, detail=f"Director returned {len(pages) if isinstance(pages, list) else 0} pages; expected {page_count}. Try again.")
    for page_index, page in enumerate(pages):
        panels = page.get("panels")
        if not isinstance(panels, list) or len(panels) != panels_per_page:
            raise HTTPException(status_code=422, detail=f"Page {page_index + 1} has the wrong panel count. Try again.")
        page["pageNumber"] = page_index + 1
        page["layoutHint"] = "dynamic" if page.get("layoutHint") == "dynamic" else "grid"
        for panel_index, panel in enumerate(panels):
            # json_repair can salvage a response that was cut off near the end
            # of its token budget, but the final panel may consequently be
            # missing optional-looking fields that are required by the editor.
            # Normalize every panel before calling the plan "validated".
            if not isinstance(panel, dict):
                panel = {}
                panels[panel_index] = panel
            panel["id"] = panel.get("id") or f"p{page_index + 1}-panel{panel_index + 1}"
            panel["order"] = panel_index + 1
            panel["narrativeRole"] = str(panel.get("narrativeRole") or "Story beat")
            panel["sceneDescription"] = str(panel.get("sceneDescription") or panel["narrativeRole"])
            panel["imagePrompt"] = str(panel.get("imagePrompt") or panel["sceneDescription"])
            panel["framing"] = str(panel.get("framing") or "Medium shot")
            panel["continuityNotes"] = str(panel.get("continuityNotes") or "")
            panel["videoPrompt"] = str(panel.get("videoPrompt") or "").strip()
            try:
                panel["durationSeconds"] = max(
                    0.8,
                    min(20.0, float(panel.get("durationSeconds") or 3)),
                )
            except (TypeError, ValueError):
                panel["durationSeconds"] = 3
            if panel.get("cameraMove") not in {
                "none", "push-in", "pull-out", "pan-left", "pan-right",
            }:
                panel["cameraMove"] = "push-in"
            _normalize_comic_panel_arrays(panel)
            _normalize_comic_panel_character_ids(panel, characters)
            normalized_dialogue = []
            for dialogue in panel["dialogue"]:
                if not isinstance(dialogue, dict):
                    continue
                dialogue["text"] = str(dialogue.get("text") or "").strip()
                if not dialogue["text"]:
                    continue
                if dialogue.get("bubbleType") not in ("speech", "thought", "caption", "scream"):
                    dialogue["bubbleType"] = "speech"
                normalized_dialogue.append(dialogue)
            panel["dialogue"] = normalized_dialogue
        if is_storyboard:
            for panel in panels:
                panel["captions"] = []
                panel["dialogue"] = []
                panel["soundEffects"] = []
            page["layoutHint"] = "grid"
        else:
            _enforce_comic_page_text_budget(page, dialogue_density)
        if (
            not is_storyboard
            and
            len(panels) in (3, 4, 6, 9)
            and page_index % 2 == 1
        ):
            page["layoutHint"] = "dynamic"
    # User-supplied character records are the source of truth for IDs,
    # references and locked canonical descriptions. The LLM sees them for
    # planning but must never be allowed to silently drop a reference asset
    # or rewrite a locked character in the persisted project.
    if characters:
        planned_by_id = {
            str(item.get("id")): item
            for item in planned.get("characters", [])
            if isinstance(item, dict) and item.get("id")
        }
        merged_characters = []
        for original in characters:
            if not isinstance(original, dict):
                continue
            generated = planned_by_id.get(str(original.get("id")), {})
            merged = {**generated, **original}
            merged["locked"] = bool(original.get("locked", True))
            merged_characters.append(merged)
        planned["characters"] = merged_characters
    plan = {
        "version": 1,
        "id": f"comic-plan-{uuid.uuid4().hex[:12]}",
        "language": str(body.get("language") or "English"),
        **planned,
    }
    return {"plan": plan}


def director_comic_text_page(body: dict):
    """Rewrite or translate one page's lettering without touching artwork or visual prompts."""
    plan = body.get("plan")
    page_index = int(body.get("pageIndex") or 0)
    mode = str(body.get("mode") or "rewrite").lower()
    instruction = str(body.get("instruction") or "").strip()[:3000]
    target_language = str(body.get("targetLanguage") or "").strip()[:120]
    raw_glossary = body.get("glossary")
    glossary = []
    if isinstance(raw_glossary, list):
        for item in raw_glossary[:100]:
            if not isinstance(item, dict):
                continue
            source_term = str(item.get("source") or "").strip()[:160]
            translated_term = str(item.get("translation") or "").strip()[:160]
            note = str(item.get("note") or "").strip()[:240]
            if source_term and translated_term:
                glossary.append({
                    "source": source_term,
                    "translation": translated_term,
                    "note": note,
                })
    dialogue_density = str(body.get("dialogueDensity") or "medium").lower()
    writing_llm = _comic_writing_llm(body)
    if not isinstance(plan, dict) or not isinstance(plan.get("pages"), list):
        raise HTTPException(status_code=400, detail="A valid comic plan is required")
    if page_index < 0 or page_index >= len(plan["pages"]):
        raise HTTPException(status_code=400, detail="Comic page index is out of range")
    if mode not in ("rewrite", "translate"):
        raise HTTPException(status_code=400, detail="Text mode must be rewrite or translate")
    if mode == "translate" and not target_language:
        raise HTTPException(status_code=400, detail="Choose a target language")
    source_page = copy.deepcopy(plan["pages"][page_index])
    source_panels = source_page.get("panels")
    if not isinstance(source_panels, list) or not source_panels:
        raise HTTPException(status_code=400, detail="The comic page has no panels")
    schema = copy.deepcopy(_COMIC_TEXT_PAGE_SCHEMA)
    schema["properties"]["panels"]["minItems"] = len(source_panels)
    schema["properties"]["panels"]["maxItems"] = len(source_panels)
    panel_schema = schema["properties"]["panels"]["items"]["properties"]
    dense_grid = len(source_panels) >= 7
    panel_schema["captions"]["maxItems"] = 1
    panel_schema["soundEffects"]["maxItems"] = 1
    panel_schema["dialogue"]["maxItems"] = 1 if dense_grid else 2
    source = [{
        "id": panel.get("id"),
        "narrativeRole": panel.get("narrativeRole"),
        "sceneDescription": panel.get("sceneDescription"),
        "captions": panel.get("captions") or [],
        "dialogue": panel.get("dialogue") or [],
        "soundEffects": panel.get("soundEffects") or [],
    } for panel in source_panels if isinstance(panel, dict)]
    if mode == "translate":
        task = f"""Translate every existing reader-facing text faithfully into {target_language}.
Preserve which panels are silent, the number and type of text blocks, speaker IDs, meaning,
tone, names and sound-effect intent. If a line is already in {target_language}, copy it
exactly, character for character. Do not add, remove, summarize or rewrite story content.
Mandatory terminology glossary (use these exact target forms when applicable):
{json.dumps(glossary, ensure_ascii=False) if glossary else "No custom glossary."}"""
    else:
        task = f"""Rewrite the page's lettering according to this editorial instruction:
{instruction or "Make the text concise, natural and dramatically effective."}
Use the comic language {plan.get("language") or "English"}. You may make panels silent."""
    max_elements = 1 if dense_grid else 2
    ratio = {"low": 0.3, "medium": 0.55, "high": 0.8}.get(dialogue_density, 0.55)
    page_budget = max(1, min(len(source_panels), int(len(source_panels) * ratio + 0.999)))
    try:
        if not writing_llm:
            _ensure_llm_loaded()
        generated = _generate_comic_director_json(
            prompt=f"""{task}

Return exactly {len(source_panels)} panel records in the original order with unchanged IDs.
This is a text-only operation: do not return image prompts or visual changes.
At most {max_elements} text block{"s" if max_elements != 1 else ""} may appear in one panel.
{"Preserve the source's exact silent/text pattern." if mode == "translate" else f"At most {page_budget} panels on this page may contain text; the rest must be silent."}
Never duplicate or paraphrase the same message across caption, dialogue and sound effect.
Source page: {json.dumps(source, ensure_ascii=False)}""",
            system_prompt=(
                "You are HocusPocus Lab's comic lettering editor and literary translator. "
                "Return only the strict JSON requested by the schema."
            ),
            schema=schema,
            max_new_tokens=min(3200, max(900, len(source_panels) * 260)),
            stage=f"{mode} lettering for page {page_index + 1}",
            llm_override=writing_llm,
            root_array_key="panels",
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Comic text {mode} failed: {exc}") from exc
    generated_panels = generated.get("panels")
    if not isinstance(generated_panels, list) or len(generated_panels) != len(source_panels):
        raise HTTPException(status_code=422, detail="The LLM returned the wrong number of panels")
    by_id = {
        str(panel.get("id")): panel
        for panel in generated_panels
        if isinstance(panel, dict) and panel.get("id")
    }
    for index, panel in enumerate(source_panels):
        candidate = by_id.get(str(panel.get("id")))
        if not isinstance(candidate, dict):
            candidate = generated_panels[index] if isinstance(generated_panels[index], dict) else {}
        panel["captions"] = candidate.get("captions") if isinstance(candidate.get("captions"), list) else []
        panel["soundEffects"] = candidate.get("soundEffects") if isinstance(candidate.get("soundEffects"), list) else []
        panel["dialogue"] = candidate.get("dialogue") if isinstance(candidate.get("dialogue"), list) else []
    if mode == "translate":
        # Translation must never alter the editorial rhythm chosen in the source.
        for source_panel, translated in zip(source, source_panels):
            expected = (
                len(source_panel["captions"]),
                len(source_panel["dialogue"]),
                len(source_panel["soundEffects"]),
            )
            actual = (
                len(translated["captions"]),
                len(translated["dialogue"]),
                len(translated["soundEffects"]),
            )
            if actual != expected:
                raise HTTPException(
                    status_code=422,
                    detail="The translation changed the number or type of text blocks",
                )
            translated["captions"] = translated["captions"][:len(source_panel["captions"])]
            translated["dialogue"] = translated["dialogue"][:len(source_panel["dialogue"])]
            translated["soundEffects"] = translated["soundEffects"][:len(source_panel["soundEffects"])]
            for source_line, translated_line in zip(
                source_panel["dialogue"],
                translated["dialogue"],
            ):
                translated_line["bubbleType"] = source_line.get("bubbleType", "speech")
                if source_line.get("speakerId"):
                    translated_line["speakerId"] = source_line["speakerId"]
                else:
                    translated_line.pop("speakerId", None)
            if not source_panel["captions"]:
                translated["captions"] = []
            if not source_panel["dialogue"]:
                translated["dialogue"] = []
            if not source_panel["soundEffects"]:
                translated["soundEffects"] = []
    else:
        _enforce_comic_page_text_budget(source_page, dialogue_density)
    return {"page": source_page}


def director_comic_story_revise(body: dict):
    """Improve an existing editable script while preserving its exact production shape."""
    plan = body.get("plan")
    instruction = str(body.get("instruction") or "").strip()[:4000]
    dialogue_density = str(body.get("dialogueDensity") or "medium").lower()
    is_storyboard = str(body.get("productionMode") or "").lower() == "storyboard"
    writing_llm = _comic_writing_llm(body)
    if not isinstance(plan, dict) or not isinstance(plan.get("pages"), list) or not plan["pages"]:
        raise HTTPException(status_code=400, detail="A valid comic plan is required")
    page_count = len(plan["pages"])
    panel_counts = [len(page.get("panels") or []) for page in plan["pages"] if isinstance(page, dict)]
    if len(panel_counts) != page_count or not panel_counts or len(set(panel_counts)) != 1:
        raise HTTPException(status_code=400, detail="Story revision currently requires a consistent panel count per page")
    panel_count = panel_counts[0]
    schema = copy.deepcopy(_COMIC_PLAN_SCHEMA)
    schema["properties"]["pages"]["minItems"] = page_count
    schema["properties"]["pages"]["maxItems"] = page_count
    schema["properties"]["pages"]["items"]["properties"]["panels"]["minItems"] = panel_count
    schema["properties"]["pages"]["items"]["properties"]["panels"]["maxItems"] = panel_count
    if is_storyboard:
        panel_schema = schema["properties"]["pages"]["items"]["properties"]["panels"]["items"]
        for field in ("videoPrompt", "durationSeconds", "cameraMove"):
            if field not in panel_schema["required"]:
                panel_schema["required"].append(field)
        panel_schema["properties"]["captions"]["maxItems"] = 0
        panel_schema["properties"]["dialogue"]["maxItems"] = 0
        panel_schema["properties"]["soundEffects"]["maxItems"] = 0
    try:
        if not writing_llm:
            _ensure_llm_loaded()
        revised = _generate_comic_director_json(
            prompt=f"""Revise this complete comic script as a professional story editor.
Editorial instruction: {instruction or "Strengthen causality, escalation, character agency, midpoint reversal, climax payoff and a concise ending."}

Keep exactly {page_count} pages and {panel_count} panels on every page.
Keep every pageNumber, panel id and panel order unchanged.
Keep the same language: {plan.get("language") or "English"}.
Return a complete plan. Improve storyStructure, logline, synopsis, narrativeRole,
sceneDescription, dialogue, captions and continuityNotes. Update imagePrompt only when
the revised action requires it. {"For every shot, also improve and preserve videoPrompt, durationSeconds and cameraMove; keep captions, dialogue and soundEffects empty because the clean first frame contains no lettering." if is_storyboard else ""}
Do not introduce unexplained characters. Prefer silent
visual storytelling; never use dialogue to repeat what the image already shows.

Existing plan: {json.dumps(plan, ensure_ascii=False)}""",
            system_prompt=(
                "You are HocusPocus Lab's senior comics editor. Build clear setup, inciting incident, "
                "progressive complications, reversal, crisis, climax and resolution. Return only strict JSON."
            ),
            schema=schema,
            max_new_tokens=min(16000, max(5000, page_count * panel_count * 420)),
            stage="revising comic story",
            llm_override=writing_llm,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Comic story revision failed: {exc}") from exc
    pages = revised.get("pages")
    if not isinstance(pages, list) or len(pages) != page_count:
        raise HTTPException(status_code=422, detail="Story revision changed the page count")
    for page_index, page in enumerate(pages):
        source_page = plan["pages"][page_index]
        if not isinstance(page, dict) or len(page.get("panels") or []) != panel_count:
            raise HTTPException(status_code=422, detail=f"Story revision changed page {page_index + 1} panel count")
        page["pageNumber"] = source_page.get("pageNumber", page_index + 1)
        for panel_index, panel in enumerate(page["panels"]):
            source_panel = source_page["panels"][panel_index]
            panel["id"] = source_panel.get("id")
            panel["order"] = source_panel.get("order", panel_index + 1)
        if is_storyboard:
            for panel in page["panels"]:
                panel["captions"] = []
                panel["dialogue"] = []
                panel["soundEffects"] = []
        else:
            _enforce_comic_page_text_budget(page, dialogue_density)
    revised["characters"] = copy.deepcopy(plan.get("characters") or [])
    revised["version"] = 1
    revised["id"] = plan.get("id") or f"comic-plan-{uuid.uuid4().hex[:12]}"
    revised["language"] = plan.get("language") or "English"
    return {"plan": revised}


def start_director_comic_plan(body: dict):
    premise = str(body.get("premise") or "").strip()
    if not premise:
        raise HTTPException(status_code=400, detail="Comic premise is required")
    job_id = f"comic-plan-job-{uuid.uuid4().hex[:12]}"
    task_id = f"task-comic-plan-{job_id}"
    now = time.time()
    workspace = str(body.get("workspace") or _get_active_workspace())
    request_body = dict(body)
    request_body["workspace"] = workspace
    with _comic_plan_jobs_lock:
        # Bound this process-local status cache. Completed results live in
        # the browser project after delivery, so old job records are expendable.
        if len(_comic_plan_jobs) >= 50:
            oldest = sorted(
                _comic_plan_jobs,
                key=lambda key: _comic_plan_jobs[key].get("updatedAt", 0),
            )[:10]
            for stale_id in oldest:
                _comic_plan_jobs.pop(stale_id, None)
        _comic_plan_jobs[job_id] = {
            "jobId": job_id,
            "status": "queued",
            "message": "Comic Director accepted the request.",
            "createdAt": now,
            "updatedAt": now,
            "workspace": workspace,
            "request": request_body,
            "taskId": task_id,
            "rootTaskId": task_id,
        }
        initial_job = copy.deepcopy(_comic_plan_jobs[job_id])
    _persist_comic_plan_job(initial_job)
    publisher = globals().get("_publish_generic_legacy_task")
    if callable(publisher):
        task = publisher(initial_job, "comic-plan")
        if isinstance(task, dict):
            initial_job["taskId"] = task.get("id")
            initial_job["rootTaskId"] = task.get("root_id") or task.get("id")
            with _comic_plan_jobs_lock:
                _comic_plan_jobs[job_id].update({
                    "taskId": initial_job["taskId"],
                    "rootTaskId": initial_job["rootTaskId"],
                })
            _persist_comic_plan_job(initial_job)
    _start_comic_plan_worker(
        job_id,
        request_body,
        thread_name=f"comic-plan-{job_id[-6:]}",
    )
    return {
        "jobId": job_id,
        "taskId": initial_job.get("taskId"),
        "rootTaskId": initial_job.get("rootTaskId"),
        "status": "queued",
        "message": "Comic Director accepted the request.",
    }


def get_director_comic_plan_status(job_id: str):
    with _comic_plan_jobs_lock:
        job = _comic_plan_jobs.get(job_id)
    if job is None:
        job = _load_comic_plan_job(job_id, _get_active_workspace())
        if job is not None:
            with _comic_plan_jobs_lock:
                _comic_plan_jobs[job_id] = job
    if job is None:
        raise HTTPException(status_code=404, detail="Comic planning job not found")
    return dict(job)


def resume_director_comic_plan(job_id: str):
    job = get_director_comic_plan_status(job_id)
    with _comic_plan_jobs_lock:
        active = job_id in _comic_plan_active_jobs
    if active:
        return {"jobId": job_id, "status": job["status"], "message": job.get("message", "Already running")}
    body = job.get("request")
    if not isinstance(body, dict):
        raise HTTPException(status_code=409, detail="This legacy checkpoint has no saved request and cannot resume planning")
    _reset_canonical_task_for_resume(
        str(job.get("workspace") or "default"),
        str(job.get("taskId") or f"task-comic-plan-{job_id}"),
    )
    _comic_plan_job_update(
        job_id,
        status="queued",
        message="Resuming from the latest durable checkpoint…",
        error=None,
        result=None,
        finishedAt=None,
    )
    if not _start_comic_plan_worker(
        job_id,
        body,
        thread_name=f"comic-plan-resume-{job_id[-6:]}",
    ):
        current = get_director_comic_plan_status(job_id)
        return {
            "jobId": job_id,
            "status": current.get("status") or "queued",
            "message": current.get("message") or "Already running",
        }
    return {"jobId": job_id, "status": "queued", "message": "Resuming from the latest durable checkpoint…"}


def get_latest_completed_director_comic_plan():
    """Recover the newest completed plan after a browser-side placement error."""
    workspace = _get_active_workspace()
    with _comic_plan_jobs_lock:
        completed = [
            dict(job)
            for job in _comic_plan_jobs.values()
            if job.get("status") == "completed"
            and str(job.get("workspace") or "default") == workspace
            and isinstance(job.get("result"), dict)
            and isinstance(job["result"].get("plan"), dict)
        ]
    try:
        for name in os.listdir(_comic_plan_checkpoint_dir(workspace)):
            if not name.endswith(".json"):
                continue
            job = _load_comic_plan_job(name[:-5], workspace)
            if (
                isinstance(job, dict)
                and job.get("status") == "completed"
                and isinstance(job.get("result"), dict)
                and isinstance(job["result"].get("plan"), dict)
            ):
                completed.append(job)
    except OSError:
        pass
    if not completed:
        raise HTTPException(status_code=404, detail="No completed comic plan is available to recover")
    return max(completed, key=lambda job: job.get("finishedAt") or job.get("updatedAt") or 0)


def bind_director_comic_runtime(
    *,
    wgp_module,
    ensure_llm_loaded,
    effective_llm_routing,
    workspace_dir,
    get_active_workspace,
    publish_legacy_task,
    reset_task,
) -> None:
    """Point the comic planner and its job store at one server's helpers."""
    global _ensure_llm_loaded, _get_active_workspace
    global _reset_canonical_task_for_resume, _publish_generic_legacy_task
    _ensure_llm_loaded = ensure_llm_loaded
    _get_active_workspace = get_active_workspace
    _reset_canonical_task_for_resume = reset_task
    _publish_generic_legacy_task = publish_legacy_task
    jobs.wgp = wgp_module
    jobs._effective_llm_routing = effective_llm_routing
    jobs._ensure_llm_loaded = ensure_llm_loaded
    jobs._workspace_dir = workspace_dir
    jobs.director_comic_plan = director_comic_plan
    jobs._publish_generic_legacy_task = publish_legacy_task


def create_director_comic_router() -> APIRouter:
    """Director comic routes in the order the full server registered them."""
    router = APIRouter()
    router.add_api_route("/api/v1/director/comic/plan", director_comic_plan, methods=["POST"])
    router.add_api_route("/api/v1/director/comic/text/page", director_comic_text_page, methods=["POST"])
    router.add_api_route("/api/v1/director/comic/story/revise", director_comic_story_revise, methods=["POST"])
    router.add_api_route("/api/v1/director/comic/plan/start", start_director_comic_plan, methods=["POST"])
    router.add_api_route(
        "/api/v1/director/comic/plan/status/{job_id}",
        get_director_comic_plan_status,
        methods=["GET"],
    )
    router.add_api_route(
        "/api/v1/director/comic/plan/resume/{job_id}",
        resume_director_comic_plan,
        methods=["POST"],
    )
    router.add_api_route(
        "/api/v1/director/comic/plan/recent/completed",
        get_latest_completed_director_comic_plan,
        methods=["GET"],
    )
    return router
