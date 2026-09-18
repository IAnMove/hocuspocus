"""Series production permissions and deliberate reference updates for existing episodes."""
from __future__ import annotations

import copy

PRODUCTION_METHODS = ("generated_video", "animation_2d", "animation_3d", "imported_video")


def existing_generated_reference(series: dict, owner_type: str, owner_id: str, metadata: dict) -> dict | None:
    job_id = metadata.get("jobId")
    if not isinstance(job_id, str) or not job_id:
        return None
    return next((asset for asset in series.get("assets", {}).values()
                 if asset.get("ownerType") == owner_type and asset.get("ownerId") == owner_id
                 and asset.get("metadata", {}).get("jobId") == job_id), None)


def attach_series_import(series: dict, asset: dict, *, as_take: bool = False, source_path: str = "") -> None:
    """Attach an imported reference or a verified completed take to its exact owner."""
    owner_type, owner_id = asset["ownerType"], asset["ownerId"]
    if owner_type not in {"series", "character", "location", "prop", "episode", "shot"}:
        raise ValueError("Unsupported Series asset owner")
    if as_take and (owner_type != "shot" or asset["kind"] != "video"):
        raise ValueError("A completed take must be a video owned by a shot")
    collection = {"character": "characters", "location": "locations", "prop": "props"}.get(owner_type)
    if collection:
        _attach_entity_reference(series, asset, collection)
    elif owner_type == "episode" and owner_id not in series.get("episodesById", {}):
        raise ValueError("Series episode not found")
    elif owner_type == "shot":
        _attach_shot_asset(series, asset, as_take, source_path)
    elif owner_type == "series" and owner_id != series["id"]:
        raise ValueError("Series asset belongs to another project")
    series.setdefault("assets", {})[asset["id"]] = asset


def _attach_entity_reference(series: dict, asset: dict, collection: str) -> None:
    entity = next((item for item in series.get(collection, []) if item.get("id") == asset["ownerId"]), None)
    if entity is None:
        raise ValueError("Series reference subject no longer exists")
    entity["referenceAssetIds"] = list(dict.fromkeys([*entity.get("referenceAssetIds", []), asset["id"]]))
    if asset["ownerType"] == "character" and not entity.get("primaryReferenceAssetId"):
        entity["primaryReferenceAssetId"] = asset["id"]
    entity["approval"] = "draft"
    series["canon"].update(approval="draft", approvedAt="")


def _verified_take_media(series: dict, shot: dict, source_path: str) -> tuple[str, dict]:
    from services.video_editor import probe_media
    method = series_shot_method(series, shot)
    if method == "generated_video":
        raise ValueError("Choose an animation or imported-video method before attaching a completed take")
    if any(item.get("status") in {"queued", "running", "cancelling"} for item in shot.get("attempts", [])):
        raise ValueError("Wait for this shot's render to finish before importing a take")
    media = probe_media(source_path)
    if float(media["duration"]) + .05 < float(shot.get("durationSeconds") or 0):
        raise ValueError("This clip is shorter than the shot; adjust its duration before importing")
    return method, media


def _attach_shot_asset(series: dict, asset: dict, as_take: bool, source_path: str) -> None:
    from services.series_library import append_shot_render_attempt
    found = next(((episode, index, shot) for episode in series.get("episodesById", {}).values()
                  for index, shot in enumerate(episode.get("shots", [])) if shot.get("id") == asset["ownerId"]), None)
    if found is None:
        raise ValueError("Series shot not found")
    if not as_take:
        return
    episode, index, shot = found
    method, media = _verified_take_media(series, shot, source_path)
    updated, attempt = append_shot_render_attempt(shot, manifest=shot.get("referenceManifest") or {},
        model=method, settings={"productionMethod": method, "sourceDurationSeconds": media["duration"]}, seed=None)
    updated["attempts"][-1].update(status="completed", outputAssetIds=[asset["id"]])
    asset.update(ownerType="attempt", ownerId=attempt["id"])
    asset["metadata"].update(productionMethod=method, **media)
    episode["shots"][index] = updated


def normalize_production_methods(value=None) -> list[str]:
    if value is None:
        return ["generated_video"]
    if not isinstance(value, list) or not value or any(item not in PRODUCTION_METHODS for item in value):
        raise ValueError("Choose at least one supported Series production method")
    return list(dict.fromkeys(value))


def series_shot_method(series: dict, shot: dict) -> str:
    allowed = normalize_production_methods(series.get("allowedProductionMethods"))
    selected = shot.get("productionMethod") or allowed[0]
    if selected not in allowed:
        raise ValueError(f"Shot {shot.get('order', shot.get('id'))}: production method {selected} is not permitted for this series")
    return selected


def refresh_episode_references(series: dict, episode_id: str, base_revision: int) -> dict:
    from services.series_library import SeriesConflictError, create_episode_canon_snapshot
    if int(series.get("revision") or 1) != base_revision:
        raise SeriesConflictError("Series changed; reload before updating episode references")
    if series.get("canon", {}).get("approval") != "approved":
        raise ValueError("Approve the current canon before updating episode references")
    result = copy.deepcopy(series)
    episode = result.get("episodesById", {}).get(episode_id)
    if not isinstance(episode, dict):
        raise ValueError("Series episode not found")
    if any(attempt.get("status") in {"queued", "running", "cancelling"}
           for shot in episode.get("shots", []) for attempt in shot.get("attempts", [])):
        raise SeriesConflictError("Wait for the episode render to finish before updating references")
    latest = create_episode_canon_snapshot(series)
    snapshot = episode.setdefault("canonSnapshot", {})
    for collection in ("characters", "locations", "props"):
        by_id = {item["id"]: item for item in latest.get(collection, [])}
        for entity in snapshot.get(collection, []):
            current = by_id.get(entity.get("id"))
            if current is None:
                continue
            entity["referenceAssetIds"] = copy.deepcopy(current.get("referenceAssetIds", []))
            if collection == "characters":
                entity["primaryReferenceAssetId"] = current.get("primaryReferenceAssetId", "")
            _refresh_variant_references(entity, current)
    snapshot.setdefault("assets", {}).update(copy.deepcopy(latest["assets"]))
    snapshot["approvedReferenceAssetIds"] = list(dict.fromkeys([
        *snapshot.get("approvedReferenceAssetIds", []), *latest["approvedReferenceAssetIds"],
    ]))
    snapshot["referenceRevision"] = latest["revision"]
    for shot in episode.get("shots", []):
        shot.pop("referenceManifest", None)
    result["revision"] = base_revision + 1
    return result


def _refresh_variant_references(entity: dict, current: dict) -> None:
    for key in ("variants", "wardrobeVariants"):
        variants = {item["id"]: item for item in current.get(key, [])}
        for variant in entity.get(key, []):
            if variant.get("id") in variants:
                variant["referenceAssetIds"] = copy.deepcopy(variants[variant["id"]].get("referenceAssetIds", []))
