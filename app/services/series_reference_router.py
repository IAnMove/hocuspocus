"""Deterministic, model-aware reference routing for Series Lab shots."""

from __future__ import annotations

import copy
import re
from typing import Any


DEFAULT_H3_CAPABILITIES = {
    "model": "minimax_h3",
    "family": "minimax_h3",
    "version": "runtime-default",
    "limits": {"image": 9, "video": 3, "audio": 3, "total": 12},
    "supportsFirstFrame": True,
    "supportsFirstLast": False,
    "supportsContinuation": True,
    "supportsNativeAudio": True,
}


def _items(value: Any) -> list[dict]:
    return [item for item in value] if isinstance(value, list) and all(
        isinstance(item, dict) for item in value
    ) else []


def _ids(value: Any) -> list[str]:
    result: list[str] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item and item not in result:
                result.append(item)
    return result


def _label_token(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _resolve_entity_id(value: Any, entities: dict[str, dict]) -> str:
    raw = str(value or "")
    if raw in entities:
        return raw
    wanted = _label_token(raw)
    for entity_id in sorted(entities):
        entity = entities[entity_id]
        if any(
            _label_token(candidate) == wanted
            for candidate in [entity.get("name"), *(entity.get("aliases") or [])]
            if candidate
        ):
            return entity_id
    return raw


def _asset_media_type(asset: dict) -> str:
    kind = str(asset.get("kind") or "image")
    return kind if kind in {"image", "video", "audio"} else "image"


def _candidate(
    asset: dict,
    *,
    entity_type: str,
    entity_id: str,
    role: str,
    priority: int,
    reason: str,
    variant_id: str | None = None,
) -> dict:
    result = {
        "assetId": str(asset["id"]),
        "entityType": entity_type,
        "entityId": entity_id,
        "referenceRole": role,
        "mediaType": _asset_media_type(asset),
        "priority": priority,
        "reason": reason,
    }
    if variant_id:
        result["variantId"] = variant_id
    return result


def _entity_assets(
    entity: dict | None,
    assets: dict[str, dict],
    variant_id: str | None = None,
) -> list[dict]:
    if not entity:
        return []
    if entity.get("approval") != "approved":
        return []
    result: list[dict] = []
    if variant_id:
        for variant in _items(entity.get("variants")) + _items(entity.get("wardrobeVariants")):
            if variant.get("id") == variant_id:
                result.extend(assets[item] for item in _ids(variant.get("referenceAssetIds")) if item in assets)
                break
    primary = entity.get("primaryReferenceAssetId")
    if isinstance(primary, str) and primary in assets and assets[primary] not in result:
        result.append(assets[primary])
    result.extend(
        assets[item] for item in _ids(entity.get("referenceAssetIds"))
        if item in assets and assets[item] not in result
    )
    return result


def _capabilities(series: dict, override: dict | None) -> dict:
    provider = series.get("provider") if isinstance(series.get("provider"), dict) else {}
    stored = provider.get("videoCapabilities") if isinstance(provider.get("videoCapabilities"), dict) else {}
    result = copy.deepcopy(DEFAULT_H3_CAPABILITIES)
    result.update(copy.deepcopy(stored))
    if isinstance(override, dict):
        result.update(copy.deepcopy(override))
    limits = copy.deepcopy(DEFAULT_H3_CAPABILITIES["limits"])
    if isinstance(stored.get("limits"), dict):
        limits.update(stored["limits"])
    if isinstance(override, dict) and isinstance(override.get("limits"), dict):
        limits.update(override["limits"])
    result["limits"] = {
        key: max(0, int(limits.get(key, fallback) or 0))
        for key, fallback in DEFAULT_H3_CAPABILITIES["limits"].items()
    }
    return result


def _auto_strategy(
    series: dict,
    shot: dict,
    candidates: list[dict],
    capabilities: dict,
    has_exact_start: bool,
) -> str:
    visible_count = len(_ids(shot.get("visibleCharacterIds")))
    source_mode = str(series.get("sourceMode") or "original")
    if source_mode == "known_universe_experimental" and visible_count == 0:
        return "direct"
    if shot.get("continuityFromShotId") and capabilities.get("supportsContinuation"):
        if has_exact_start:
            return "first_frame"
        return "references" if candidates else "direct"
    if has_exact_start and capabilities.get("supportsFirstFrame"):
        return "first_frame"
    if candidates:
        return "references"
    return "direct"


def route_shot_references(
    series: dict,
    episode: dict,
    shot: dict,
    capability_override: dict | None = None,
) -> dict:
    """Return the exact, stable manifest to persist and submit to a model.

    The function is pure: it never changes the series, episode, shot or assets.
    """
    capabilities = _capabilities(series, capability_override)
    raw_assets = series.get("assets") if isinstance(series.get("assets"), dict) else {}
    assets = {
        str(item.get("id") or key): item
        for key, item in raw_assets.items() if isinstance(item, dict) and (item.get("id") or key)
    }
    characters = {
        str(item.get("id")): item for item in _items(series.get("characters")) if item.get("id")
    }
    locations = {
        str(item.get("id")): item for item in _items(series.get("locations")) if item.get("id")
    }
    props = {str(item.get("id")): item for item in _items(series.get("props")) if item.get("id")}
    shots = {str(item.get("id")): item for item in _items(episode.get("shots")) if item.get("id")}
    visible = []
    for raw_id in _ids(shot.get("visibleCharacterIds")):
        resolved_id = _resolve_entity_id(raw_id, characters)
        if resolved_id not in visible:
            visible.append(resolved_id)
    speaking = []
    for raw_id in _ids(shot.get("speakingCharacterIds")):
        resolved_id = _resolve_entity_id(raw_id, characters)
        if resolved_id in visible and resolved_id not in speaking:
            speaking.append(resolved_id)
    primary = _resolve_entity_id(shot.get("primarySpeakerId"), characters)
    if primary not in speaking:
        primary = speaking[0] if speaking else ""

    candidates: list[dict] = []
    warnings: list[str] = []
    errors: list[str] = []
    exact_start_ids: set[str] = set()
    exact_end_ids: set[str] = set()

    # A reviewed composed frame owned by this shot is the strongest visual lock.
    for asset in sorted(assets.values(), key=lambda item: str(item.get("id"))):
        metadata = asset.get("metadata") if isinstance(asset.get("metadata"), dict) else {}
        reference_role = str(metadata.get("referenceRole") or "")
        if (
            asset.get("ownerType") == "shot" and asset.get("ownerId") == shot.get("id")
            and reference_role in {"composed_start_frame", "composed_end_frame"}
        ):
            candidates.append(_candidate(
                asset, entity_type="continuity", entity_id=str(shot.get("id")),
                role=reference_role, priority=1,
                reason=f"Approved {reference_role.replace('_', ' ')} for this shot",
            ))
            if reference_role == "composed_start_frame":
                exact_start_ids.add(str(asset["id"]))
            else:
                exact_end_ids.add(str(asset["id"]))

    continuity_id = str(shot.get("continuityFromShotId") or "")
    previous = shots.get(continuity_id)
    if previous:
        attempt_id = previous.get("approvedAttemptId")
        attempt = next((item for item in _items(previous.get("attempts")) if item.get("id") == attempt_id), None)
        if attempt:
            for asset_id in _ids(attempt.get("outputAssetIds")):
                if asset_id in assets:
                    candidates.append(_candidate(
                        assets[asset_id], entity_type="continuity", entity_id=continuity_id,
                        role="previous_segment", priority=1,
                        reason="Approved output from the requested continuity shot",
                    ))
                    if _asset_media_type(assets[asset_id]) == "image":
                        exact_start_ids.add(asset_id)
                    break

    ordered_character_ids: list[tuple[str, int, str, str]] = []
    if primary:
        ordered_character_ids.append((primary, 2, "primary_speaker_identity", "Primary speaker is visible"))
    for character_id in speaking:
        if character_id != primary:
            ordered_character_ids.append((
                character_id, 3, "visible_speaking_character_identity",
                "Speaking character is visible",
            ))
    for character_id in visible:
        if character_id not in speaking:
            ordered_character_ids.append((
                character_id, 4, "visible_character_identity",
                "Recurring reaction/listening character is visible",
            ))
    for character_id, priority, role, reason in ordered_character_ids:
        character = characters.get(character_id)
        if not character:
            errors.append(f"Visible character {character_id} is missing from the series bible.")
            continue
        if character.get("approval") != "approved":
            errors.append(f"Visible character {character.get('name', character_id)} is not approved in canon.")
        wardrobe_map = shot.get("wardrobeByCharacterId") \
            if isinstance(shot.get("wardrobeByCharacterId"), dict) else {}
        entity_refs = _entity_assets(character, assets, str(wardrobe_map.get(character_id) or "") or None)
        if not entity_refs:
            warnings.append(f"Visible character {character.get('name', character_id)} has no approved reference.")
        for asset in entity_refs:
            candidates.append(_candidate(
                asset, entity_type="character", entity_id=character_id,
                role=role, priority=priority, reason=reason,
                variant_id=str(wardrobe_map.get(character_id) or "") or None,
            ))

    location_id = _resolve_entity_id(shot.get("locationId"), locations)
    if location_id:
        location = locations.get(location_id)
        if not location:
            errors.append(f"Shot location {location_id} is missing from the series bible.")
        else:
            if location.get("approval") != "approved":
                errors.append(f"Shot location {location.get('name', location_id)} is not approved in canon.")
            variant_id = str(shot.get("locationVariantId") or "") or None
            for asset in _entity_assets(location, assets, variant_id):
                candidates.append(_candidate(
                    asset, entity_type="location", entity_id=location_id,
                    role="location_variant" if variant_id else "location_identity",
                    priority=5, reason="Location selected by this shot", variant_id=variant_id,
                ))

    for raw_prop_id in _ids(shot.get("propIds")):
        prop_id = _resolve_entity_id(raw_prop_id, props)
        prop = props.get(prop_id)
        if not prop:
            errors.append(f"Shot prop {prop_id} is missing from the series bible.")
            continue
        if prop.get("approval") != "approved":
            errors.append(f"Shot prop {prop.get('name', prop_id)} is not approved in canon.")
        for asset in _entity_assets(prop, assets):
            candidates.append(_candidate(
                asset, entity_type="prop", entity_id=prop_id,
                role="plot_critical_prop", priority=6,
                reason="Plot-critical prop is present in this shot",
            ))

    policy = shot.get("referencePolicy") if isinstance(shot.get("referencePolicy"), dict) else {}
    includes = _ids(policy.get("manualIncludeAssetIds"))
    excludes = set(_ids(policy.get("manualExcludeAssetIds")))
    visible_set = set(visible)
    for asset_id in includes:
        asset = assets.get(asset_id)
        if not asset:
            warnings.append(f"Manual reference {asset_id} no longer exists.")
            continue
        if asset.get("ownerType") == "character" and asset.get("ownerId") not in visible_set:
            warnings.append(f"Manual reference {asset_id} was ignored because its character is absent.")
            continue
        owner_collections = {"character": characters, "location": locations, "prop": props}
        owner_collection = owner_collections.get(str(asset.get("ownerType") or ""))
        owner = owner_collection.get(str(asset.get("ownerId") or "")) if owner_collection else None
        if owner_collection is not None and (not owner or owner.get("approval") != "approved"):
            warnings.append(f"Manual reference {asset_id} was ignored because its canon entity is not approved.")
            continue
        if not any(item["assetId"] == asset_id for item in candidates):
            candidates.append(_candidate(
                asset, entity_type="style", entity_id=str(asset.get("ownerId") or series.get("id")),
                role="manual_override", priority=7, reason="Explicit manual include",
            ))

    # De-duplicate by asset while keeping the strongest semantic role.
    candidates.sort(key=lambda item: (item["priority"], item["entityId"], item["assetId"], item["referenceRole"]))
    deduplicated: list[dict] = []
    seen_assets: set[str] = set()
    for item in candidates:
        if item["assetId"] not in seen_assets:
            seen_assets.add(item["assetId"])
            deduplicated.append(item)

    requested_strategy = str(shot.get("renderStrategy") or "auto")
    strategy = _auto_strategy(series, shot, deduplicated, capabilities, bool(exact_start_ids)) \
        if requested_strategy == "auto" else requested_strategy
    if strategy == "first_last" and not capabilities.get("supportsFirstLast"):
        warnings.append("The selected model does not support first-and-last-frame rendering; using first frame.")
        strategy = "first_frame" if capabilities.get("supportsFirstFrame") else "references"
    elif strategy == "first_last" and not exact_end_ids:
        warnings.append("First-and-last rendering needs an approved composed end frame; using first frame.")
        strategy = "first_frame" if capabilities.get("supportsFirstFrame") else "references"
    if strategy == "first_frame" and not capabilities.get("supportsFirstFrame"):
        warnings.append("The selected model does not support first-frame rendering; using routed references.")
        strategy = "references"
    if strategy == "direct":
        for item in deduplicated:
            warnings.append(f"Reference {item['assetId']} was omitted because direct mode accepts no references.")
        deduplicated = []

    if len(visible) >= 3 and not exact_start_ids:
        if strategy == "direct":
            warnings.append(
                "Direct text-to-video will improvise this crowd composition because no approved "
                "composed start frame is available."
            )
        else:
            warnings.append(
                "This crowd cannot be blocked reliably with loose portraits; approve a composed start frame."
            )
            errors.append("Approve a composed start frame before rendering this crowd shot.")
            if capabilities.get("supportsFirstFrame"):
                strategy = "first_frame"
    elif len(visible) == 2 and not exact_start_ids:
        warnings.append(
            "Two-character blocking from loose portraits is approximate; use an approved composed start frame when composition matters."
        )
    elif strategy in {"first_frame", "first_last"} and visible and not exact_start_ids:
        warnings.append(
            "No approved composed start frame exists for the visible cast; using routed identity references."
        )
        strategy = "references"

    limits = capabilities["limits"]
    override = policy.get("maxReferencesOverride")
    max_total = limits["total"]
    if isinstance(override, int):
        max_total = min(max_total, max(0, override))
    selected: list[dict] = []
    omitted: list[dict] = []
    media_counts = {"image": 0, "video": 0, "audio": 0}
    for item in deduplicated:
        reason = ""
        media_type = item["mediaType"]
        if item["assetId"] in excludes:
            reason = "Explicit manual exclude"
        elif len(selected) >= max_total:
            reason = f"Model total reference budget is exhausted ({max_total})"
        elif media_counts[media_type] >= limits[media_type]:
            reason = f"Model {media_type} reference budget is exhausted ({limits[media_type]})"
        if reason:
            omitted.append({key: value for key, value in item.items() if key != "priority"} | {"reason": reason})
        else:
            selected.append(item)
            media_counts[media_type] += 1
    if omitted:
        warnings.append(f"{len(omitted)} reference(s) were omitted by model or manual limits.")
    if strategy in {"references", "first_frame", "first_last"} and not selected:
        if requested_strategy == "auto":
            warnings.append(
                "Auto routing found no usable reference file; using direct text-to-video generation."
            )
        else:
            errors.append("The selected render strategy has no usable routed references.")
        strategy = "direct"
        warnings.append("Falling back to direct generation because no usable reference remains.")
    if strategy in {"first_frame", "first_last"} and not any(
        item["mediaType"] == "image" and item["assetId"] in exact_start_ids for item in selected
    ):
        warnings.append("No exact start image survived reference routing; using reference generation.")
        strategy = "references" if selected else "direct"

    first_frame_role = "none"
    if strategy in {"first_frame", "first_last"}:
        first_frame_role = "exact" if any(item["assetId"] in exact_start_ids for item in selected) else "visual_reference"
    return {
        "strategy": strategy,
        "selected": selected,
        "omitted": omitted,
        "warnings": warnings,
        "errors": errors,
        "firstFrameRole": first_frame_role,
        "capabilitySnapshot": capabilities,
    }


def route_episode_references(
    series: dict,
    episode: dict,
    capability_override: dict | None = None,
) -> dict[str, dict]:
    return {
        str(shot["id"]): route_shot_references(series, episode, shot, capability_override)
        for shot in _items(episode.get("shots")) if shot.get("id")
    }
