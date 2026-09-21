"""Persist review decisions onto the existing Director pipeline, atomically."""
from pathlib import Path
import time

from services.director_pipeline import (
    _exclusive_pipeline_operation, _find_pipeline_file, _load_pipeline_state_locked,
    _pipeline_file_lock, _write_pipeline_json_unlocked, hydrate_queue_clips,
)


def _select_take(clip: dict, name: str, workspace: Path, state: dict) -> None:
    attempts = {item.get("filename"): item for item in clip.get("video_attempts", []) if isinstance(item, dict)}
    available = set(attempts) | {clip.get("video_filename"), clip.get("selected_video_filename")}
    if not isinstance(name, str) or not name or name not in available or Path(name).name != name:
        raise ValueError("Select an existing take from this shot")
    file = workspace / name
    if not file.is_file() or file.resolve().parent != workspace.resolve() or file.stat().st_size == 0:
        raise ValueError("The selected take is missing from this workspace")
    changed = name != (clip.get("selected_video_filename") or clip.get("video_filename"))
    clip.update(selected_video_filename=name, video_filename=name)
    if changed:
        clip.update(video_stale=False, tag=None)
        segments = clip.get("h3_segments") or []
        if len(segments) == 1:
            attempt = attempts.get(name, {})
            segment = segments[0]
            segment.update(filename=name, prompt=attempt.get("prompt") or segment.get("prompt", ""),
                           seed=attempt.get("seed", segment.get("seed")), stale=False, updated_at=time.time())
            if attempt.get("video_length"):
                segment["frames"] = attempt["video_length"]
    if name not in state.get("output_files", []):
        state.setdefault("output_files", []).append(name)


def _apply_review(state: dict, commands: list, workspace: Path, pid: str) -> None:
    clips = {clip.get("index", index): clip for index, clip in enumerate(state.get("clips", []))}
    for command in commands:
        if not isinstance(command, dict) or command.get("pipelineId") != pid:
            raise ValueError("Review command belongs to another production")
        index = command.get("clipIndex")
        if type(index) is not int or index not in clips:
            raise ValueError("Review shot was not found")
        clip = clips[index]
        kind = command.get("type")
        if kind == "select_take":
            _select_take(clip, command.get("filename"), workspace, state)
        elif kind == "tag_clip":
            tag = command.get("tag")
            if tag not in (None, "good", "needs_work"):
                raise ValueError("Invalid review decision")
            # The desk always restates the current decision with notes/select.
            # After an image rerun the take stays tagged good and video_stale,
            # so rejecting a no-op "good" would drop the notes in the same
            # atomic batch. Only a new approval of a missing/stale take is
            # blocked; Rejoin/export still read video_stale independently.
            if (
                tag == "good"
                and clip.get("tag") != "good"
                and (not clip.get("video_filename") or clip.get("video_stale"))
            ):
                raise ValueError("Only a completed current take can be approved")
            clip["tag"] = tag
        elif kind == "note_clip":
            notes = command.get("notes")
            if not isinstance(notes, str) or len(notes) > 8000:
                raise ValueError("Review notes must contain at most 8000 characters")
            clip["review_notes"] = notes
        else:
            raise ValueError("Unsupported review command")


@_exclusive_pipeline_operation
def save_review(workspace: str, pid: str, commands: list) -> dict:
    if not isinstance(commands, list) or len(commands) > 1500:
        raise ValueError("Use a bounded list of review decisions")
    path = _find_pipeline_file(workspace, pid)
    if not path or Path(path).resolve().parent != Path(workspace).resolve():
        raise ValueError("Production not found in this workspace")
    with _pipeline_file_lock:
        # Same projection GET uses: sidecar/output_files histories are visible
        # on the desk, so persist must accept and return those takes.
        state = _load_pipeline_state_locked(workspace, pid)
        if not state or str(state.get("pipeline_id") or "") != pid:
            raise ValueError("Production not found in this workspace")
        _apply_review(state, commands, Path(workspace), pid)
        _write_pipeline_json_unlocked(path, state)
    return hydrate_queue_clips(state)
