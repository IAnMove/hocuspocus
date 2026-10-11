"""Small production hooks for interior sets; surface images join the normal picture batch."""
from __future__ import annotations

import copy
from pathlib import Path
from urllib.parse import quote
from services.set_molds import defaults, resolve_mold, validate_mold
from services.set_skins import build_skin, image_requests, validate_skin
from services.prop_library import get_prop
from services.scene3d_items import change_items
from services.set_generation import image_model

FIELDS = {'kind','mold','size','skin','props','camera'}


def is_room(value):
    return isinstance(value,dict) and value.get('kind')=='room'


def check_room(name, entry, text=None):
    try:
        if set(entry)-FIELDS: raise ValueError('unknown room fields')
        mold=resolve_mold(entry.get('mold'),entry.get('size','medium'))
        validate_skin(mold,entry.get('skin',{}),allow_location=False)
        validate_props(entry,mold)
    except (ValueError,TypeError,KeyError) as error:
        return f'sets.{name}: {error}'
    return None


def validate_props(entry,mold):
    props=entry.get('props',[])
    if not isinstance(props,list) or len(props)>12: raise ValueError('at most 12 props per set')
    for prop in props:
        if not isinstance(prop,dict) or not isinstance(prop.get('prop'),str): raise ValueError('set props need a library prop id')
        if prop.get('anchor') not in {a['id'] for a in mold['propAnchors']}: raise ValueError(f'unknown anchor: {prop.get("anchor")}')
    if entry.get('camera','two_shot') not in {c['id'] for c in mold['cameras']}: raise ValueError('unknown room camera')


def recipe(entry):
    return {**entry,'geometry':resolve_mold(entry['mold'],entry.get('size','medium')),'defaults':defaults()}


def is_built(record):
    return bool(record.get('room'))


def prop_objects(entry,root):
    room={'mold':resolve_mold(entry['mold'],entry.get('size','medium'))};rows=[]
    for asked in entry.get('props',[]):
        prop=get_prop(Path(root),asked['prop'],approved=True)
        rows,_=change_items(rows,'add',{'at':{'anchor':asked['anchor']},**{k:asked[k] for k in ('heightM','rotationY','billboard','shadow') if k in asked}},
                            {**prop,'prop':prop['id'],'media':'image'},room)
    return rows


def picture_jobs(production,name,entry,look,choice):
    mold=resolve_mold(entry['mold'],entry.get('size','medium'))
    requests=image_requests(mold,entry.get('skin',{}),look)
    record=production.state['sets'][name];record.update(entry=copy.deepcopy(entry),style=look)
    if not requests:
        build(production,name,record);production.save();return {}
    model=image_model(production.mcp)
    return {f'set:{name}:{surface}':production.image(f'set-{name}-{surface}',asked['prompt'],None,asked['resolution'],index+1,model,None,production._attempt('set_attempts',name))
            for index,(surface,asked) in enumerate(requests.items())}


def build(production,name,record):
    entry=record['entry']
    skin=build_skin(entry['mold'],entry.get('size','medium'),entry.get('skin',{}),record['style'],root=production.root,workspace=production.ws,
                    call=production.mcp,provided=record.get('pictures',{}))
    record.update(room={'mold':resolve_mold(entry['mold'],entry.get('size','medium')),'skin':skin,'camera':entry.get('camera','two_shot')},objects=prop_objects(entry,production.root))
    record.pop('pictures',None)
    production.log(f'set {name}: room {entry["mold"]}')


def resolved_background(entry,made):
    if not made or not made.get('room'): return None
    return {'room':copy.deepcopy(made['room'])}


def has_room(config):
    return isinstance(config.get('background'),dict) and 'room' in config['background']


def check_background(config):
    if not has_room(config): return False
    room=config['background']['room']
    if not isinstance(room,dict) or not isinstance(room.get('mold'),dict): raise ValueError('background.room needs a resolved mold')
    validate_mold({**room['mold'],'sizes':{**room['mold']['sizes'],'medium':room['mold']['dimensions']}})
    if config.get('roomCamera',room.get('camera','two_shot')) not in {c['id'] for c in room['mold']['cameras']}:
        raise ValueError('unknown room camera')
    return True


def resolve_background(resolved,sets,workspace):
    background=resolved.get('background')
    if has_room(resolved): return True
    source=background.get('source') if isinstance(background,dict) else background
    made=(sets or {}).get(source,{})
    if not made.get('room'): return False
    resolved['background']={'room':copy.deepcopy(made['room'])}
    cast=resolved.setdefault('cast',{})
    for row in made.get('objects',[]):
        cast.setdefault(row['objectId'],{**{k:v for k,v in row.items() if k not in {'objectId','file','media'}},
            'source':f"/api/v1/file/{quote(row['file'])}?workspace={quote(workspace)}"})
    return True


def dry_run_images(spec):
    rooms={name:entry for name,entry in (spec.get('sets') or {}).items() if is_room(entry)}
    if not rooms: return {}
    counts={}
    for name,entry in rooms.items():
        try: counts[name]=len(image_requests(resolve_mold(entry['mold'],entry.get('size','medium')),entry.get('skin',{}),''))
        except (ValueError,KeyError): counts[name]=0
    return {'room_skin_images':sum(counts.values()),'room_sets':counts}
