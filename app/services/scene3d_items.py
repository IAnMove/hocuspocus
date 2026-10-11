"""Place or edit real-sized props through the existing shot and working-scene mutations."""
from __future__ import annotations

import copy
import math
import re
import threading
from pathlib import Path
from urllib.parse import quote

from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool
from services.media_paths import resolve_permitted_media_path
from services.mcp_intent import IntentConflict, check_intent_id, intent_digest, load_intent, store_intent
from services.prop_library import get_prop
from services.scene_documents import WORKSPACE_RE
from services.set_generation import require_result
from services.set_molds import resolve_mold
from services.series_shot3d import MAX_OBJECTS

_LOCK = threading.RLock()


def _positive(value):
    return type(value) in (int, float) and math.isfinite(value) and .01 <= value <= 30


def placement(at: dict, room: dict | None, height: float) -> tuple[list, list]:
    if not isinstance(at, dict) or len(at) != 1:
        raise ValueError('at must contain one mark, anchor or position')
    if 'position' in at:
        point = at['position']
        if not isinstance(point, list) or len(point) != 3 or not all(type(n) in (int, float) and math.isfinite(n) for n in point):
            raise ValueError('position must be three finite metre coordinates')
        return point, []
    if not room:
        raise ValueError('mark or anchor requires a room set')
    mold = room.get('mold')
    mold = resolve_mold(mold, room.get('size', 'medium')) if isinstance(mold, str) else mold
    key = 'marks' if 'mark' in at else 'propAnchors'
    id_ = at.get('mark', at.get('anchor'))
    found = next((row for row in mold[key] if row['id'] == id_), None)
    if not found:
        raise ValueError(f'unknown {key}: {id_}')
    warnings = [{'code': 'item_too_tall', 'anchor': id_, 'maxHeight': found['maxHeight'], 'heightM': height}] if height > found.get('maxHeight', math.inf) else []
    return list(found['position']), warnings


def item_id(name: str, ids) -> str:
    stem = re.sub('[^a-z0-9]+', '-', name.lower()).strip('-')[:60] or 'object'
    n = 1
    while f'prop-{stem}-{n}' in ids:
        n += 1
    return f'prop-{stem}-{n}'


def change_items(objects, action, data, item=None, room=None, *, limit=MAX_OBJECTS):
    """Pure shot-object edit; unchanged inputs retain their exact values."""
    rows = copy.deepcopy(objects); warnings = []
    if action == 'list': return rows, warnings
    current = next((r for r in rows if r['objectId'] == data.get('id')), None)
    if action != 'add' and current is None:
        raise ValueError('item_not_found')
    if action == 'remove':
        rows.remove(current); return rows, warnings
    if action == 'add':
        if len(rows) >= limit:
            raise ValueError(f'object_limit: {len(rows)+1} requested; maximum {limit}')
        current = {'objectId': item_id(item['name'], {r['objectId'] for r in rows}), 'add': True}
        rows.append(current)
    if item:
        current.update(file=item['file'], media=item['media'])
    height = data.get('heightM', item.get('heightM') if item else current.get('setItem', {}).get('heightM'))
    if height is None:
        height = current.get('scale', 1) * (2 if current.get('media') == 'image' else 1.7)
    if not _positive(height): raise ValueError('heightM must be between 0.01 and 30 metres')
    current.update(scale=height/(2 if current['media']=='image' else 1.7), grounded=True)
    meta = {**current.get('setItem', {}), 'heightM': height}
    if item and item.get('prop'): meta['prop'] = item['prop']
    at = data.get('at') or ({'position': [0,0,0]} if action == 'add' else None)
    if at:
        point, warnings = placement(at, room, height); current['position'] = point; meta['at'] = copy.deepcopy(at)
    rotation = data.get('rotationY', current.get('rotationY', 0))
    if type(rotation) not in (int,float) or not math.isfinite(rotation) or abs(rotation) > 20: raise ValueError('invalid rotationY in radians')
    current['rotationY'] = rotation; current['setItem'] = meta
    if current['media'] == 'image':
        current['imageLook'] = {**current.get('imageLook', {}), 'grounded': True}
        if 'shadow' in data: current['imageLook']['shadow'] = .35 if data['shadow'] else 0
        if 'billboard' in data: current['billboard'] = bool(data['billboard'])
    return rows, warnings


def glb_height(path):
    from services.procedural_3d.glb_inspector import inspect_glb
    if inspect_glb(path).status != 'valid':
        raise ValueError('GLB inspector rejected this asset')
    import trimesh
    scene = trimesh.load(str(path), force='scene', process=False)
    height = float(scene.bounds[1][1]-scene.bounds[0][1])
    if not _positive(height): raise ValueError('GLB has no measurable height; provide heightM')
    return height


class ItemService:
    def __init__(self, workspace_dir, uploads_dir, call):
        self.workspace_dir, self.uploads_dir, self.call = workspace_dir, uploads_dir, call

    def _item(self, data):
        value = data.get('item')
        if value is None: return None
        if not isinstance(value, dict) or len(value) != 1: raise ValueError('item must name one prop, image or glb')
        root = Path(self.workspace_dir(data['workspace']))
        if 'prop' in value:
            prop = get_prop(root, value['prop'], approved=True)
            return {**prop, 'prop': prop['id'], 'media': 'image'}
        media = 'model3d' if 'glb' in value else 'image'
        source = value.get('glb', value.get('image'))
        path = Path(resolve_permitted_media_path(source, uploads_root=self.uploads_dir(), workspace_root=str(root), workspace_name=data['workspace'], kinds=(media,)))
        if not path.is_relative_to(root):
            import shutil
            target = root/f'prop-import-{intent_digest({"source":str(path)})[:12]}{path.suffix}'
            shutil.copy2(path,target);path=target
        height = data.get('heightM')
        if height is None and media == 'model3d': height = glb_height(path)
        if height is None: raise ValueError('heightM is required for an image')
        return {'file': path.relative_to(root).as_posix(), 'heightM': height, 'media': media, 'name': path.stem}

    def _series_room(self, data, shot):
        if shot.get('scene3d', {}).get('room'): return shot['scene3d']['room']
        result = require_result(self.call('series.get', {'version':1, 'input':{'workspace':data['workspace'],'series_id':data['target']['series_id']}}))
        series = result.get('series', result)
        return next((loc.get('set3d') for loc in series.get('locations',[]) if loc['id'] == shot.get('location')),None)

    def _shot(self, action, data, intent):
        args = {'workspace':data['workspace'], **data['target']}
        viewed = require_result(self.call('series.shot.get', {'version':1,'input':args}))
        script = viewed.get('script', viewed.get('shot', {}).get('script', {})); config = copy.deepcopy(script.get('scene3d'))
        if not config: raise ValueError('target is not a 3D shot')
        room = self._series_room(data,script) if (data.get('at') or {}).keys() & {'mark','anchor'} else None
        rows,warnings = change_items(config.get('objects',[]), action,data,self._item(data),room)
        if action != 'list':
            config['objects']=rows
            require_result(self.call('series.shot.update',{'version':1,'intent_id':f'{intent}-edit','input':{**args,'changes':{'scene3d':config}}}))
        return {'items':rows,'warnings':warnings}

    def _scene(self, action,data,intent):
        from services.world3d_scenes import inspect_scene, patch_scene
        workspace=data['workspace']; id_=data['target']['scene_id']
        scene=inspect_scene(workspace,id_,self.workspace_dir); slots=scene['document']['slots']
        rows=[{**s,'objectId':s['id'],'file':s.get('sourceUrl','')} for s in slots if s.get('slot')=='prop']
        rows,warnings=change_items(rows,action,data,self._item(data),scene['document'].get('room'),limit=24-len(slots)+len(rows))
        if action=='list': return {'items':rows,'warnings':[],'revision':scene['revision']}
        if action=='remove': binding={'object_id':data['id'],'remove':True}
        else:
            updated=next(r for r in rows if r['objectId']==data.get('id')) if action=='update' else rows[-1]
            binding={k:v for k,v in updated.items() if k not in {'file','objectId','id','add'}}
            binding.update(object_id=updated['objectId'],add=action=='add')
            file=updated['file']; binding['source_url']=file if file.startswith('/api/') else f"/api/v1/file/{quote(file)}?workspace={quote(workspace)}"
        changed=patch_scene(workspace,id_,self.workspace_dir,{'bindings':[binding]},data.get('base_revision',scene['revision']))
        return {'items':rows,'warnings':warnings,'revision':changed['revision']}

    def execute(self,operation,arguments):
        try:
            data=arguments['input']; workspace=data['workspace']; action=operation.rsplit('.',1)[-1]
            if arguments.get('version')!=1 or not WORKSPACE_RE.fullmatch(workspace) or action not in {'add','update','remove','list'}: raise ValueError('invalid item command')
            target=data.get('target',{}); scene='scene_id' in target
            if (scene and set(target)!={'scene_id'}) or (not scene and set(target)!={'series_id','episode_id','shot'}): raise ValueError('target must identify one scene or Series shot')
            if action=='add' and not data.get('item'): raise ValueError('item required')
            with _LOCK:
                intent=check_intent_id(arguments.get('intent_id')) if action!='list' else 'read'
                root=Path(self.workspace_dir(workspace));digest=intent_digest(data)
                result=load_intent(root,operation,intent,digest) if action!='list' else None
                if result is None:
                    result=(self._scene if scene else self._shot)(action,data,intent)
                    if action!='list': store_intent(root,operation,intent,digest,result)
            return {'version':1,'operation':operation,'status':'completed','result':result}
        except IntentConflict as error: raise HTTPException(409,str(error)) from error
        except (ValueError,KeyError) as error: raise HTTPException(getattr(error,'status',422),str(error)) from error

    def handlers(self):
        def handler(name):
            async def run(arguments): return await run_in_threadpool(self.execute,name,arguments)
            return run
        return {f'scene3d.item.{action}':handler(f'scene3d.item.{action}') for action in ('add','update','remove','list')}


def command_catalog():
    fields={'workspace':{'type':'string'},'target':{'type':'object','description':'{series_id, episode_id, shot} or {scene_id}'},'item':{'type':'object','description':'One of {prop}, {image}, {glb}'},
        'at':{'type':'object','description':'One of {mark}, {anchor}, {position: [x,y,z] metres}'},'id':{'type':'string'},'heightM':{'type':'number'},'rotationY':{'type':'number'},
        'billboard':{'type':'boolean'},'shadow':{'type':'boolean'},'base_revision':{'type':'integer'}}
    output=[]
    for action in ('add','update','remove','list'):
        props={'version':{'const':1},'input':{'type':'object','properties':fields,'additionalProperties':False,'required':['workspace','target',*(['item','at'] if action=='add' else ['id'] if action!='list' else [])]}}
        if action!='list': props['intent_id']={'type':'string'}
        output.append({'name':f'scene3d.item.{action}','version':1,'domain':'scenes','mutation':action!='list','destructive':False,
            'description':f'{action.capitalize()} real-sized props in a Series 3D shot or working Video 3D scene. Use marks, anchors or metre positions; Series shots allow at most 12 objects.',
            'inputSchema':{'type':'object','properties':props,'required':list(props),'additionalProperties':False}})
    return output
