"""Freeze approved episode canon and overlay it while retaining its live shot outputs."""
import copy


def _approved_references(entities, raw_assets, objects, unique_ids):
    approved_asset_ids: set[str] = set()
    for entity in entities:
        approved_asset_ids.update(unique_ids(entity.get("referenceAssetIds")))
        primary = entity.get("primaryReferenceAssetId")
        if isinstance(primary, str) and primary:
            approved_asset_ids.add(primary)
        for variant in [*objects(entity.get("wardrobeVariants")), *objects(entity.get("variants"))]:
            approved_asset_ids.update(unique_ids(variant.get("referenceAssetIds")))
    return sorted(
        asset_id for asset_id in approved_asset_ids
        if isinstance(raw_assets.get(asset_id), dict) and not raw_assets[asset_id].get("isDerivedThumbnail")
    )


def create_snapshot(series: dict, *, normalize_canon, objects, text, unique_ids) -> dict:
    canon = normalize_canon(series.get("canon"))
    provider = copy.deepcopy(series.get("provider")) if isinstance(series.get("provider"), dict) else {}
    capability = copy.deepcopy(provider.get("videoCapabilities")) \
        if isinstance(provider.get("videoCapabilities"), dict) else {
            "model": text(provider.get("videoModel"), "minimax_h3").replace("minimax-h3", "minimax_h3"),
            "family": "minimax_h3", "version": "unknown",
            "limits": {"image": 9, "video": 3, "audio": 3, "total": 12},
            "supportsFirstFrame": True, "supportsFirstLast": False,
            "supportsContinuation": True, "supportsNativeAudio": True,
        }
    raw_assets = series.get("assets") if isinstance(series.get("assets"), dict) else {}
    frozen_characters = [
        copy.deepcopy(item) for item in objects(series.get("characters"))
        if item.get("approval") == "approved"
    ]
    frozen_locations = [
        copy.deepcopy(item) for item in objects(series.get("locations"))
        if item.get("approval") == "approved"
    ]
    frozen_props = [
        copy.deepcopy(item) for item in objects(series.get("props"))
        if item.get("approval") == "approved"
    ]
    approved_assets = _approved_references([*frozen_characters, *frozen_locations, *frozen_props], raw_assets, objects, unique_ids)
    return {
        "revision": canon["revision"],
        "worldSummary": canon["worldSummary"],
        "immutableRules": copy.deepcopy(canon["immutableRules"]),
        "currentFacts": copy.deepcopy(canon["currentFacts"]),
        "characters": frozen_characters,
        "relationships": copy.deepcopy(objects(series.get("relationships"))),
        "locations": frozen_locations,
        "props": frozen_props,
        "characterStates": {
            item["id"]: copy.deepcopy(item.get("currentState") or {})
            for item in objects(series.get("characters")) if item.get("id")
        },
        "relationshipStates": {
            item["id"]: text(item.get("currentState"), text(item.get("dynamic")))
            for item in objects(series.get("relationships")) if item.get("id")
        },
        "locationStates": {
            item["id"]: copy.deepcopy(item.get("currentState") or {})
            for item in objects(series.get("locations")) if item.get("id")
        },
        "propStates": {
            item["id"]: copy.deepcopy(item.get("currentState") or {})
            for item in objects(series.get("props")) if item.get("id")
        },
        "sourceMode": series.get("sourceMode", "original"),
        "masterUniversePrompt": text(series.get("masterUniversePrompt")),
        "rightsNote": text(series.get("rightsNote")),
        "visualStyle": text(series.get("visualStyle")),
        "characterVisualStyle": text(series.get("characterVisualStyle")),
        "cameraLanguage": text(series.get("cameraLanguage")),
        "spokenLanguage": text(series.get("spokenLanguage"), text(series.get("language"))),
        "protagonistConsistency": series.get("protagonistConsistency") is True,
        "protagonistCharacterId": text(series.get("protagonistCharacterId")),
        "allowClipText": series.get("allowClipText") is True,
        "provider": provider,
        "capabilitySnapshot": capability,
        "approvedReferenceAssetIds": approved_assets,
        "assets": {
            asset_id: copy.deepcopy(raw_assets[asset_id]) for asset_id in approved_assets
        },
    }


def overlay_snapshot(series: dict, episode: dict, *, objects, unique_ids) -> dict:
    """Overlay immutable episode canon onto live storage while retaining new shot outputs."""
    result = copy.deepcopy(series)
    snapshot = episode.get("canonSnapshot") if isinstance(episode.get("canonSnapshot"), dict) else {}
    for key in (
        "sourceMode", "masterUniversePrompt", "rightsNote", "visualStyle",
        "characterVisualStyle", "cameraLanguage", "allowClipText", "provider",
        "characters", "relationships", "locations", "props",
    ):
        if key in snapshot:
            result[key] = copy.deepcopy(snapshot[key])
    frozen_assets = snapshot.get("assets") if isinstance(snapshot.get("assets"), dict) else None
    live_assets = series.get("assets") if isinstance(series.get("assets"), dict) else {}
    if frozen_assets is None:
        approved_ids = set(unique_ids(snapshot.get("approvedReferenceAssetIds")))
        frozen_assets = {
            asset_id: copy.deepcopy(asset) for asset_id, asset in live_assets.items()
            if asset_id in approved_ids and isinstance(asset, dict)
        }
    assets = copy.deepcopy(frozen_assets)
    episode_attempt_ids = {
        str(attempt.get("id"))
        for shot in objects(episode.get("shots"))
        for attempt in objects(shot.get("attempts")) if attempt.get("id")
    }
    episode_shot_ids = {
        str(shot.get("id")) for shot in objects(episode.get("shots")) if shot.get("id")
    }
    for asset_id, asset in live_assets.items():
        if not isinstance(asset, dict):
            continue
        if (
            asset.get("ownerType") == "shot" and str(asset.get("ownerId")) in episode_shot_ids
        ) or (
            asset.get("ownerType") == "attempt" and str(asset.get("ownerId")) in episode_attempt_ids
        ):
            assets[asset_id] = copy.deepcopy(asset)
    result["assets"] = assets
    result["canon"] = {
        **copy.deepcopy(result.get("canon") or {}),
        "worldSummary": copy.deepcopy(snapshot.get("worldSummary", result.get("canon", {}).get("worldSummary", ""))),
        "immutableRules": copy.deepcopy(snapshot.get("immutableRules", result.get("canon", {}).get("immutableRules", []))),
        "currentFacts": copy.deepcopy(snapshot.get("currentFacts", result.get("canon", {}).get("currentFacts", []))),
        "revision": int(snapshot.get("revision") or episode.get("canonRevisionAtCreation") or 1),
    }
    return result
