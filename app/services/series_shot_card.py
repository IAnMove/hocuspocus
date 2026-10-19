"""Put a Video 2D card on a Series shot as a new take: the one operation behind every door.

A person did it in five steps (find the card, compile it, edit it, export it, import and approve the take). An MCP client calls
``series.shot.card.apply`` and the Wizard ``apply_series_shot_card``; both reach ``SeriesShotCard.apply`` through
``POST /api/v1/series/{series}/episodes/{episode}/shots/{shot}/card`` (routers/series_shot_card.py).

1. **Bind.** The card is resolved in ``scenes.templates.catalog`` and its character slots get the shot's characters: pose pictures,
   or for the sheet cards (``walk-cycle-sheet``, ``walk-two-pose``, ``character-reaction``) the character's APPROVED animation
   sheet (``series_shot_card_bind``). ``background`` is the shot's location plate. A pending or rejected sheet is refused with
   the words of the script check.
2. **Compile.** ``video2d_compile.execute`` (the code of ``scenes.template.compile``) at the series frame, 24 fps, as long as the
   shot needs (or ``controls.duration``). The shot's recorded lines are laid in as speech and subtitles
   (``series_shot_card_lines``).
3. **Save.** The scene document is written to the workspace under a stable name, ``<series>-<episode>-<shot>-card-<card>.scene.json``
   (a second apply replaces it), so the person opens and edits it in Video 2D; the take's ``sceneFilename`` points at it.
4. **Export and attach.** The scene is exported by ``scenes.video2d.export`` (the exporter the server render uses) and imported with
   ``series.asset.import`` as a new take of the shot (``productionMethod`` ``animation_2d``, the shot's ``renderInputs``). The
   episode render builds every scene from the script, so it cannot export a card scene; this operation does. An export that is not
   ready after ``wait_seconds`` answers ``exporting`` and the same call finishes it: the export intent comes from the scene, so the
   second call finds the first one's work and imports it.
5. **Approve.** The take is a candidate. ``approve`` approves it only when the owner turned on «Modo un solo disparo»
   (``agent_autonomy`` = ``one_shot``, ``services/agent_autonomy.py``), stamped ``approvedBy`` agent or wizard; a take a person
   approved (in this language or in Series Lab for the original) is never replaced.

Applying the same card with the same inputs again finds its take and does nothing twice; other inputs make a new take and reject
the earlier unapproved take of the same scene as superseded. A take approved in any language (the original's ``approvedAttemptId``
or a version's) is left alone: rejecting it would undo that language's decision.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from services import agent_activity, agent_autonomy, video2d_compile
from services.series_kit_pins import kits_for_episode
from services.series_language_versions import LANGUAGES, localized_view, set_version_duration, set_version_take
from services.series_library import _now, approve_shot_render_attempt, reject_shot_render_attempt
from services.series_native_render import audio_seconds
from services.series_production import series_shot_method
from services.series_shot_card_bind import CardBindError, bind_card, card_controls, card_duration
from services.series_shot_card_lines import LinesError, heard, lay_dialogue, plan, recorded, spoken
from services.series_expression_silence import card_warnings
from services.series_shot_edit import ShotEditError, find_shot
from services.series_shot_plan import FPS, frame_size, kit_ref, language_key
from services.series_take_inputs import INPUTS_VERSION, render_inputs
from services.series_voice_rooms import apply_room

CAPABILITY = "series.shot.card.apply"
APPROVE_OFF = ("Agent approval is off (agent_autonomy is review): a person approves a take in Series Lab. "
               "Apruébala en Series Lab o activa el modo un solo disparo (Ajustes › Servicios).")
PERSON_KEPT = "A person approved another take of this shot, so the new take stays a candidate: only a person replaces that decision."
# A scene export the server lost (interrupted, discarded, forgotten) is asked for again under a new intent.
EXPORT_RETRIES = 2
EXPORTING = ("The scene is being exported (a few minutes on a busy machine). Call series.shot.card.apply again with the same input to "
             "finish: it finds this export and attaches the take.")
WAIT_SECONDS = 60.0
POLL_SECONDS = 2.5


class CardApplyError(RuntimeError):
    def __init__(self, code: str, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.code, self.status = code, status


def agent_actor() -> str:
    """The one who asked for this approval: the Wizard when it declared itself, else the agent. Never ``user``: a person approves in Series Lab."""
    actor = agent_activity.current_actor()
    return actor if actor in ("agent", "wizard") else "agent"


@dataclass
class CardDeps:
    read_library: Callable[[str], dict]
    read_kits: Callable[[str], dict]
    workspace_dir: Callable[[str], str]
    # A tool of the server, run in process (``LocalMcp.call``): the exporter and the take import.
    call: Callable[[str, dict], dict]
    # ``change(series)`` under the library lock; returns the stored series (``_change_series`` of the launch module).
    change_series: Callable[[str, str, Callable[[dict], None]], dict]
    services: Callable[[], Mapping[str, Any]]
    # Who answers for an approval (``agent`` or ``wizard``, never a person): read on the request's own thread.
    actor: Callable[[], str] = agent_actor
    compile: Callable[..., dict] = video2d_compile.execute
    probe: Callable[[str], float] = audio_seconds
    room: Callable[[str, str, str], str] = apply_room
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic
    wait_seconds: float = WAIT_SECONDS
    poll_seconds: float = POLL_SECONDS


@dataclass
class Context:
    workspace: str
    root: str
    series_id: str
    episode_id: str
    language: str
    original: bool
    series: dict[str, Any]
    episode: dict[str, Any]
    shot: dict[str, Any]
    number: int
    kits: dict[str, Any]


def _ok(result: Any, label: str) -> dict[str, Any]:
    if not isinstance(result, dict) or result.get("_is_error") or result.get("status") == "failed":
        error = result.get("error") if isinstance(result, dict) else None
        message = error.get("message") if isinstance(error, dict) else json.dumps(result)[:300]
        raise CardApplyError("tool_failed", f"{label}: {message}", 502)
    return result


def _stem(ctx: Context, card: str) -> str:
    suffix = "" if ctx.original else f"-{ctx.language}"
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", f"{ctx.series_id}-{ctx.episode_id}-{ctx.shot['id']}-card-{card}").strip("-._")
    return name[:100 - len(suffix)] + suffix


def _kit_animations(ctx: Context, who: str) -> dict[str, Any]:
    """The animations of the kit of character ``who`` (empty when it has none)."""
    ref = kit_ref(ctx.series, who)
    found = (ctx.kits.get(ref["id"]) or {}).get("animations") if ref else None
    return found if isinstance(found, dict) else {}


def _card_take(series: dict[str, Any], attempt: dict[str, Any]) -> dict[str, Any] | None:
    """The metadata of the card take an attempt holds (None for any other take)."""
    for asset_id in attempt.get("outputAssetIds") or []:
        meta = ((series.get("assets") or {}).get(asset_id) or {}).get("metadata")
        if isinstance(meta, dict) and meta.get("cardId"):
            return {**meta, "assetId": asset_id}
    return None


class SeriesShotCard:
    def __init__(self, deps: CardDeps) -> None:
        self.deps = deps

    # The operation ---------------------------------------------------------------------

    def apply(self, workspace: str, series_id: str, episode_id: str, shot: str | int, card: str, *, controls: dict[str, Any] | None = None,
              cast: list[dict[str, Any]] | None = None, assets: dict[str, Any] | None = None, language: str | None = None,
              approve: bool = False) -> dict[str, Any]:
        if approve and not agent_autonomy.is_one_shot(self.deps.services()):
            raise CardApplyError("agent_review_off", APPROVE_OFF, 403)
        ctx = self._context(workspace, series_id, episode_id, shot, language)
        scene = self._scene(ctx, card, controls or {}, cast, assets)
        saved = self._save_scene(ctx, scene["card"], scene["document"])
        base = {"shotId": ctx.shot["id"], "number": ctx.number, "card": scene["card"], "scene": saved["name"], "sceneUrl": saved["url"],
                "bindings": scene["bindings"], "controls": scene["controls"], "duration": scene["document"]["duration"], "warnings": scene["warnings"]}
        take = self._existing(ctx, scene["digest"])
        if take is None:
            video, intent = self._export(ctx, scene["document"], scene["digest"])
            if video is None:
                return {"status": "exporting", **base, "exportIntent": intent, "message": EXPORTING}
            take = self._attach(ctx, scene, saved["name"], video)
        approved, note = self._approve(ctx, take["attemptId"]) if approve else (False, None)
        return {"status": "completed", **base, "take": {**take, "approved": approved}, **({"approvalNote": note} if note else {})}

    def _scene(self, ctx: Context, card: str, controls: dict[str, Any], cast: list[dict[str, Any]] | None,
               assets: dict[str, Any] | None) -> dict[str, Any]:
        """The card bound to the shot and compiled, with the shot's lines in it: its document, digest, bindings and warnings."""
        try:
            entry, _preset, _alias = video2d_compile.resolve_card(card)
            bound = bind_card(entry, series=ctx.series, kits=ctx.kits, shot=ctx.shot, workspace=ctx.workspace, root=ctx.root, cast=cast, assets=assets)
            lines, seconds = self._dialogue(ctx)
            kept, dropped = card_controls(entry, bound["autoControls"])
            merged = {**kept, **controls}
            duration = card_duration(entry, merged, max(seconds, self._needed(ctx)))
            if duration is not None and duration + 0.001 < seconds:
                raise CardBindError("card_shorter_than_lines", f"controls.duration {duration:g} s is shorter than the shot's lines ({seconds:g} s)")
            merged = {**merged, **({"duration": duration} if duration is not None else {})}
            compiled = self._compile(ctx, entry["id"], bound["assets"], merged)
        except (CardBindError, LinesError) as error:
            raise CardApplyError(error.code, str(error), error.status) from error
        except video2d_compile.CompileError as error:
            raise CardApplyError(error.code, str(error), 422) from error
        document = lay_dialogue(compiled["document"], lines, seconds)
        document["name"] = f"{ctx.series.get('title') or ctx.series_id} · {ctx.episode.get('title') or ctx.episode_id} · {ctx.shot['id']} · {entry['id']}"[:200]
        warnings = [video2d_compile.warning_text(item) for item in compiled["warnings"]]
        if dropped:
            warnings.append(f"{', '.join(dropped)} of the sheet does not fit the card and was left to its default")
        warnings.extend(card_warnings(bound["bindings"], lines, lambda who: _kit_animations(ctx, who)))
        return {"card": entry["id"], "document": document, "controls": merged, "bindings": bound["bindings"], "warnings": warnings,
                "digest": hashlib.sha1(json.dumps([ctx.language, document], sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]}

    # Context ---------------------------------------------------------------------------

    def _context(self, workspace: str, series_id: str, episode_id: str, shot_ref: Any, language: str | None) -> Context:
        raw = (self.deps.read_library(workspace).get("seriesById") or {}).get(series_id)
        raw_episode = ((raw or {}).get("episodesById") or {}).get(episode_id)
        if not isinstance(raw_episode, dict):
            raise CardApplyError("not_found", "Series episode not found", 404)
        original = language_key(raw)
        language = language or original
        if language not in LANGUAGES:
            raise CardApplyError("invalid_language", f"Unknown language {language}", 400)
        try:
            series, episode = localized_view(raw, raw_episode, None if language == original else language)
        except ValueError as error:
            raise CardApplyError("no_version", str(error), 404) from error
        try:
            shot, number = find_shot(episode, shot_ref)
        except ShotEditError as error:
            raise CardApplyError(error.code, str(error), error.status) from error
        self._check_2d(series, shot)
        root = self.deps.workspace_dir(workspace)
        kits = kits_for_episode(self.deps.read_kits(workspace), raw_episode, root)
        return Context(workspace, root, series_id, episode_id, language, language == original, series, episode, shot, number, kits)

    @staticmethod
    def _check_2d(series: dict[str, Any], shot: dict[str, Any]) -> None:
        try:
            method = series_shot_method(series, shot)
        except ValueError as error:
            raise CardApplyError("method_not_allowed", str(error), 409) from error
        if method != "animation_2d":
            raise CardApplyError("shot_not_2d", f"Shot {shot['id']} is a {method} shot: a card is a 2D scene. Make the shot 2D first "
                                 "(series.shot.update changes {kind: \"2d\"}) or choose a 2D shot", 409)

    @staticmethod
    def _needed(ctx: Context) -> float:
        """How long the shot is now (in this language): a take shorter than that is refused on import."""
        from services.series_language_versions import take_length_floor
        return take_length_floor(ctx.series, ctx.episode, ctx.shot, None if ctx.original else ctx.language)

    def _dialogue(self, ctx: Context) -> tuple[list[dict[str, Any]], float]:
        if not spoken(ctx.shot):
            return [], 0.0
        clips = recorded(ctx.series, ctx.episode, ctx.shot, ctx.kits, ctx.language, ctx.root, self.deps.probe)
        return plan(ctx.series, ctx.episode, ctx.shot, heard(ctx.series, ctx.shot, clips, ctx.root, self.deps.room))

    # Compile and save ------------------------------------------------------------------

    def _compile(self, ctx: Context, card: str, assets: dict[str, str], controls: dict[str, Any]) -> dict[str, Any]:
        width, height = frame_size(ctx.series)
        command = {"version": 1, "operation": "scenes.template.compile",
                   "input": {"templateId": card, "assets": assets, "controls": controls, "width": width, "height": height, "fps": FPS, "full": True}}
        return self.deps.compile(command, workspace_dir=lambda _name: ctx.root)["result"]

    def _save_scene(self, ctx: Context, card: str, document: dict[str, Any]) -> dict[str, Any]:
        """The scene document under its stable name; a second apply replaces it. Opens in Video 2D like any saved scene."""
        from services.scene_commands import DocumentInput, command_error
        from services.scene_save import publish_layer_scene
        try:
            valid = DocumentInput(document=document).document
        except ValueError as error:
            raise CardApplyError("invalid_document", f"The compiled scene is not a valid Video 2D document: {command_error(error)}", 422) from error
        os.makedirs(ctx.root, exist_ok=True)
        saved = publish_layer_scene(folder=Path(ctx.root), stem=_stem(ctx, card), encoded=json.dumps(valid, ensure_ascii=False, allow_nan=False, indent=2),
                                    png=None, workspace=ctx.workspace, document=valid, capability=CAPABILITY)
        return {"name": saved["name"], "url": saved["url"]}

    # Export ----------------------------------------------------------------------------

    def _export(self, ctx: Context, document: dict[str, Any], digest: str) -> tuple[str | None, str]:
        """The exported video's file name, or None when the export is still running after ``wait_seconds``; and its intent."""
        deadline = self.deps.clock() + self.deps.wait_seconds
        intent = ""
        for retry in range(EXPORT_RETRIES + 1):
            intent = f"card-{ctx.shot['id']}-{digest}{f'-r{retry}' if retry else ''}"[:160]
            _ok(self.deps.call("scenes.video2d.export", {"version": 1, "intent_id": intent,
                                                         "input": {"workspace": ctx.workspace, "document": document}}), "export")
            state, name = self._wait_export(ctx.workspace, intent, deadline)
            if state != "lost":
                return name, intent
        raise CardApplyError("export_failed", f"The export was lost {EXPORT_RETRIES + 1} times", 502)

    def _wait_export(self, workspace: str, intent: str, deadline: float) -> tuple[str, str | None]:
        while True:
            receipt = self.deps.call("scenes.video2d.export.receipt", {"version": 1, "input": {"workspace": workspace, "intent_id": intent}})
            error = receipt.get("error") if receipt.get("_is_error") and isinstance(receipt.get("error"), dict) else None
            body = receipt.get("result") if isinstance(receipt.get("result"), dict) else receipt
            artifacts = (body.get("receipt") or {}).get("artifacts") or []
            task = body.get("task") or {}
            if artifacts:
                return "ready", artifacts[0]["name"]
            if task.get("status") in ("interrupted", "discarded") or (error is not None and (error.get("status") == 404 or error.get("code") == "receipt_not_found")):
                return "lost", None
            if error is not None:
                raise CardApplyError("tool_failed", f"export receipt: {error.get('message') or error}"[:300], 502)
            if task.get("status") in ("failed", "cancelled"):
                raise CardApplyError("export_failed", str(task.get("error") or task.get("message") or "export failed")[:300], 502)
            if self.deps.clock() >= deadline:
                return "waiting", None
            self.deps.sleep(self.deps.poll_seconds)

    # The take --------------------------------------------------------------------------

    def _fresh(self, ctx: Context) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        """The series, episode and shot as stored now, in this language."""
        raw = (self.deps.read_library(ctx.workspace).get("seriesById") or {})[ctx.series_id]
        series, episode = localized_view(raw, raw["episodesById"][ctx.episode_id], None if ctx.original else ctx.language)
        return series, episode, next(item for item in episode["shots"] if item["id"] == ctx.shot["id"])

    def _existing(self, ctx: Context, digest: str) -> dict[str, Any] | None:
        """The live take this very scene already made (same card, bindings, controls and lines): applying twice does nothing twice."""
        series, _episode, shot = self._fresh(ctx)
        for attempt in reversed(shot.get("attempts") or []):
            meta = _card_take(series, attempt)
            if meta and meta.get("cardDigest") == digest and attempt.get("reviewDecision") != "rejected" and attempt.get("status") == "completed":
                return {"attemptId": attempt["id"], "assetId": meta["assetId"], "reused": True}
        return None

    def _set_length(self, ctx: Context, seconds: float) -> None:
        """The take's length becomes the shot's, in its own language only (as the server render does before importing)."""
        def change(series: dict[str, Any]) -> None:
            episode = series["episodesById"][ctx.episode_id]
            if ctx.original:
                for shot in episode["shots"]:
                    if shot["id"] == ctx.shot["id"]:
                        shot["durationSeconds"] = round(seconds, 3)
            else:
                set_version_duration(episode, ctx.language, ctx.shot["id"], seconds)
        self.deps.change_series(ctx.workspace, ctx.series_id, change)

    def _attach(self, ctx: Context, scene: dict[str, Any], name: str, video: str) -> dict[str, Any]:
        card, document = scene["card"], scene["document"]
        self._set_length(ctx, float(document["duration"]))
        series, episode, shot = self._fresh(ctx)
        inputs = render_inputs(series, shot, ctx.kits, ctx.root, episode=episode)
        metadata = {"productionMethod": "animation_2d", "sceneFilename": name, "duration": document["duration"], "language": ctx.language,
                    "cardId": card, "cardScene": name, "cardDigest": scene["digest"], "cardBindings": scene["bindings"],
                    "renderInputs": inputs, "renderInputsVersion": INPUTS_VERSION}
        imported = _ok(self.deps.call("series.asset.import", {"version": 1, "input": {
            "workspace": ctx.workspace, "series_id": ctx.series_id, "file": video, "owner_type": "shot", "owner_id": ctx.shot["id"],
            "kind": "video", "as_take": True, "name": f"{ctx.shot['id']}-card-{card}"[:300], "metadata": metadata}}), "import take")
        result = imported.get("result") or imported
        attempt = result.get("attempt") or {}
        if not attempt.get("id"):
            raise CardApplyError("import_failed", "The take was imported without an attempt id", 502)
        asset_id = (result.get("asset") or {}).get("id")
        return {"attemptId": attempt["id"], "assetId": asset_id, "reused": False, "superseded": self._supersede(ctx, name, attempt["id"])}

    def _protected(self, ctx: Context) -> set[str]:
        """Takes already approved for this shot in any language. Rejecting one undoes that language's decision:
        ``reject_shot_render_attempt`` clears ``approvedAttemptId`` when the id matches, so a version apply
        must not treat a Series Lab approval of the original as an unapproved candidate."""
        raw = (self.deps.read_library(ctx.workspace).get("seriesById") or {})[ctx.series_id]["episodesById"][ctx.episode_id]
        shot = next(item for item in raw["shots"] if item["id"] == ctx.shot["id"])
        kept = {shot.get("approvedAttemptId"), self._approval(ctx)[0]}
        for version in (raw.get("languageVersions") or {}).values():
            if isinstance(version, dict):
                kept.add((version.get("approvedAttemptIds") or {}).get(shot["id"]))
        return {item for item in kept if isinstance(item, str) and item}

    def _supersede(self, ctx: Context, scene: str, keep: str) -> list[str]:
        """The earlier unapproved takes of this same scene are rejected: the new one replaces them (a take approved in any language is left alone)."""
        done: list[str] = []
        protected = self._protected(ctx) | {keep}

        def change(series: dict[str, Any]) -> None:
            episode = series["episodesById"][ctx.episode_id]
            for index, shot in enumerate(episode["shots"]):
                if shot["id"] != ctx.shot["id"]:
                    continue
                for attempt in list(shot.get("attempts") or []):
                    meta = _card_take(series, attempt) or {}
                    if (meta.get("cardScene") != scene or attempt["id"] in protected
                            or attempt.get("reviewDecision") in ("rejected", "approved")):
                        continue
                    shot = reject_shot_render_attempt(shot, attempt["id"], "server")
                    done.append(attempt["id"])
                episode["shots"][index] = shot
        self.deps.change_series(ctx.workspace, ctx.series_id, change)
        return done

    # Approval --------------------------------------------------------------------------

    def _approve(self, ctx: Context, attempt_id: str) -> tuple[bool, str | None]:
        """Approve the take for the agent: not when it already is, and never over a take a person approved."""
        approved, by = self._approval(ctx)
        if approved == attempt_id:
            return True, None
        if approved and by == "user":
            return False, PERSON_KEPT
        actor = self.deps.actor()

        def change(series: dict[str, Any]) -> None:
            episode = series["episodesById"][ctx.episode_id]
            if ctx.original:
                index = next(i for i, item in enumerate(episode["shots"]) if item["id"] == ctx.shot["id"])
                episode["shots"][index] = approve_shot_render_attempt(episode["shots"][index], attempt_id, actor)
                if all(item.get("approvedAttemptId") for item in episode["shots"]):
                    episode["status"] = "completed"
            else:
                set_version_take(episode, ctx.language, ctx.shot["id"], attempt_id, actor)
            episode["updatedAt"] = _now()
        # Not the ``series.take.approve`` tool: a tool run in process is stamped as the server's own job, and this approval is the
        # agent's (or the Wizard's) to answer for, as the take records it (``approvedBy``).
        self.deps.change_series(ctx.workspace, ctx.series_id, change)
        return True, None

    def _approval(self, ctx: Context) -> tuple[str | None, str | None]:
        """The shot's approved take in this language and who approved it (a take approved before the reviewer was recorded is a person's)."""
        raw = (self.deps.read_library(ctx.workspace).get("seriesById") or {})[ctx.series_id]["episodesById"][ctx.episode_id]
        shot = next(item for item in raw["shots"] if item["id"] == ctx.shot["id"])
        version = (raw.get("languageVersions") or {}).get(ctx.language) or {}
        approved = shot.get("approvedAttemptId") if ctx.original else (version.get("approvedAttemptIds") or {}).get(shot["id"])
        current = next((item for item in shot.get("attempts") or [] if item.get("id") == approved), None)
        return (approved, current.get("approvedBy", "user")) if current else (None, None)
