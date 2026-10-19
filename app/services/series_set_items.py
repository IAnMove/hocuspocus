"""Per-shot overrides for inherited location props, without copying unchanged library entries."""
from __future__ import annotations
import copy
from services.series_shot3d import MAX_OBJECTS


def merged_items(own, inherited, removed=()):
    rows={row['objectId']:copy.deepcopy(row) for row in inherited if row['objectId'] not in removed}
    rows.update({row['objectId']:copy.deepcopy(row) for row in own})
    return list(rows.values())


def store_items(config, rows, inherited):
    base={row['objectId']:row for row in inherited}
    ids={row['objectId'] for row in rows}
    config['objects']=[row for row in rows if row != base.get(row['objectId'])]
    removed=[id_ for id_ in base if id_ not in ids]
    if removed: config['removedSetObjects']=removed
    else: config.pop('removedSetObjects',None)


def hidden_items(value):
    items=value.get('removedSetObjects',[])
    if not isinstance(items,list) or len(items)>MAX_OBJECTS or not all(isinstance(id_,str) for id_ in items):
        raise ValueError('removedSetObjects must contain at most 12 object ids')
    return {'removedSetObjects':list(dict.fromkeys(items))} if items else {}
