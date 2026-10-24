"""Territory licences for catalogue families, stored in one JSON file.

A family points at a record by id. Variants do not copy the record. A family
with no entry is unchanged, and nothing here refuses a download or a run.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "runtime" / "model_licences.json"
_FIELDS = ("id", "url", "territoryExcluded", "commercial", "note")


def _check_record(record: dict) -> None:
    if set(record) != set(_FIELDS):
        raise ValueError("a licence record must be id, url, territoryExcluded, commercial, note")
    places = record["territoryExcluded"]
    if not isinstance(places, list) or not places or any(not isinstance(item, str) or not item for item in places):
        raise ValueError(f"{record.get('id')}: territoryExcluded must list places")
    if not isinstance(record["commercial"], bool):
        raise ValueError(f"{record.get('id')}: commercial must be true or false")
    if not str(record["url"]).startswith("https://") or not str(record["note"]).strip():
        raise ValueError(f"{record.get('id')}: url and note are required")


@lru_cache(maxsize=1)
def _load() -> dict:
    data = json.loads(_PATH.read_text(encoding="utf-8"))
    records = {}
    for record in data["records"]:
        _check_record(record)
        records[record["id"]] = record
    families = data.get("families") or {}
    unknown = [family for family, licence_id in families.items() if licence_id not in records]
    if unknown:
        raise ValueError(f"licence family has no record: {', '.join(unknown)}")
    return {"records": records, "families": dict(families)}


def _public(record: dict) -> dict:
    return {
        "id": record["id"],
        "url": record["url"],
        "territoryExcluded": list(record["territoryExcluded"]),
        "commercial": record["commercial"],
        "note": record["note"],
    }


def for_id(licence_id: str | None) -> dict | None:
    """The record with this id, or None when the catalog does not name one."""
    if not licence_id:
        return None
    record = _load()["records"].get(licence_id)
    return _public(record) if record else None


def for_family(family_id: str | None) -> dict | None:
    """The family's record, or None when that family has no territory notice."""
    if not family_id:
        return None
    return for_id(_load()["families"].get(family_id))


def annotate_catalog(payload: dict) -> dict:
    """Put the record on each family once, and only the id on each model."""
    for family in payload.get("families") or []:
        if isinstance(family, dict):
            record = for_family(family.get("id"))
            if record:
                family["licence"] = record
    for model in payload.get("models") or []:
        if isinstance(model, dict):
            record = for_family(model.get("family"))
            if record:
                model["licenceId"] = record["id"]
    return payload
