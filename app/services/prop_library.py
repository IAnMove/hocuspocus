"""Workspace prop records and atomic, optimistic updates. Images remain in the workspace."""
from __future__ import annotations

import copy
import json
import math
import os
import tempfile
import threading
from pathlib import Path

from fastapi import HTTPException

FILE = '.prop-library-v1.json'
MAX_PROPS = 500
LOCK = threading.RLock()


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, prefix=path.name, suffix='.tmp', delete=False) as handle:
            temporary = handle.name
            json.dump(value, handle, ensure_ascii=False, allow_nan=False)
            handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def read_library(root: Path) -> dict:
    try:
        value = json.loads((Path(root)/FILE).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {'version': 1, 'revision': 0, 'props': []}
    if value.get('version') != 1 or not isinstance(value.get('props'), list):
        raise ValueError('Invalid prop library')
    return value


def validate_prop(row: dict):
    height = row.get('heightM')
    if isinstance(height, bool) or not isinstance(height, (int, float)) or not math.isfinite(height) or not 0.01 <= height <= 30:
        raise ValueError('heightM must be between 0.01 and 30 metres')
    for field in ('id', 'name', 'description', 'file', 'style'):
        if not isinstance(row.get(field), str) or len(row[field]) > 4000:
            raise ValueError(f'invalid prop {field}')
    if row.get('anchor') not in {'bottom', 'center'} or row.get('facing') not in {'front', 'three_quarter'}:
        raise ValueError('invalid prop anchor or facing')
    if not isinstance(row.get('approved'), bool) or not isinstance(row.get('provenance'), dict):
        raise ValueError('invalid prop approval or provenance')


def update_library(root: Path, change, base_revision=None) -> dict:
    with LOCK:
        value = read_library(root)
        if base_revision is not None and base_revision != value['revision']:
            raise HTTPException(409, {'code': 'revision_conflict', 'revision': value['revision']})
        result = copy.deepcopy(value)
        change(result['props'])
        if len(result['props']) > MAX_PROPS:
            raise ValueError(f'prop library allows at most {MAX_PROPS} objects')
        if len({row['id'] for row in result['props']}) != len(result['props']):
            raise ValueError('duplicate prop id')
        for row in result['props']:
            validate_prop(row)
        result['revision'] += 1
        atomic_json(Path(root)/FILE, result)
        return result


def get_prop(root: Path, id_: str, *, approved=False) -> dict:
    row = next((p for p in read_library(root)['props'] if p['id'] == id_), None)
    if row is None:
        raise HTTPException(404, {'code': 'prop_not_found', 'id': id_})
    if approved and not row['approved']:
        raise ValueError(f'prop {id_} must be approved')
    return row
