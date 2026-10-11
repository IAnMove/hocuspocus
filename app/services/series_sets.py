"""Location room sets and optional shot inheritance; old locations are strict no-ops."""
from __future__ import annotations

import copy
import hashlib
import json
import threading
from pathlib import Path

from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool
from services.mcp_intent import check_intent_id, intent_digest, load_intent, store_intent, IntentConflict
from services.prop_library import atomic_json
from services.production_rooms import prop_objects, validate_props
from services.set_molds import resolve_mold
from services.set_skins import build_skin, validate_skin
from services.series_shot_edit import reset_approvals
from services.series_set_items import merged_items

_LOCK=threading.RLock()


def location_for(series,shot):
    return next((loc for loc in series.get('locations',[]) if loc['id']==shot.get('locationId',shot.get('location'))),{})


def series_style(series):
    return str(series.get('characterVisualStyle') or series.get('masterUniversePrompt') or '')


def script_scene3d(shot,location):
    config=copy.deepcopy(shot.get('scene3d') or {})
    if not location.get('set3d') or shot.get('kind')!='3d': return config
    if not config.get('scene'): config.setdefault('template','two-shot')
    config.setdefault('roomCamera','two_shot')
    by_character={entry['characterId']:entry for entry in config.get('cast',[])}
    for index,raw in enumerate(shot.get('cast',[])):
        from services.series_script import _cast_entry
        entry=_cast_entry(raw)
        if not entry.get('characterId'): continue
        value=by_character.setdefault(entry['characterId'],{'characterId':entry['characterId'],'objectId':f'subject_{index+1}','poseId':entry.get('poseId','base')})
        if entry.get('mark'): value['mark']=entry['mark']
    config['cast']=list(by_character.values())
    return config


def mark_warnings(shot,location):
    if not location.get('set3d') or shot.get('kind')!='3d': return []
    names={m['id'] for m in resolve_mold(location['set3d']['mold'],location['set3d'].get('size','medium'))['marks']}
    return [{'code':'unknown_set_mark','message':f'Unknown room mark: {entry["mark"]}', 'subject':entry['mark']}
            for entry in script_scene3d(shot,location).get('cast',[]) if entry.get('mark') and entry['mark'] not in names]


def inherit_shot(series,shot):
    location=location_for(series,shot)
    if shot.get('productionMethod')!='animation_3d' or not location.get('set3d'): return shot
    result=copy.deepcopy(shot);config=result.setdefault('scene3d',{})
    if config.get('scene'): return result
    config.setdefault('template','two-shot');config['roomSet']=copy.deepcopy(location['set3d'])
    built=location.get('set3dBuilt')
    if not built: raise ValueError('location room is not ready; poll series.location.set3d.status')
    camera=config.get('roomCamera','two_shot')
    if camera not in built['templates']: raise ValueError(f'unknown room camera: {camera}')
    config['template']=built['templates'][camera]
    # Every shot receives the location props once, then its own overrides win by id.
    rows=merged_items(config.get('objects',[]),built.get('objects',[]),config.get('removedSetObjects',[]))
    if len(rows)>12: raise ValueError(f'object_limit: {len(rows)} requested; maximum 12')
    if rows: config['objects']=rows
    else: config.pop('objects',None)
    return result


def room_cast_bindings(config):
    room=config.get('roomSet')
    if not room: return []
    marks=resolve_mold(room['mold'],room.get('size','medium'))['marks'];bindings=[]
    for index,entry in enumerate(config.get('cast',[])):
        mark=next((m for m in marks if m['id']==entry.get('mark')),None) or marks[index % len(marks)]
        bindings.append({'object_id':entry['objectId'],'position':mark['position'],'rotationY':mark['facing']*3.141592653589793/180,'scale':.85,'grounded':True})
    return bindings


def bind_silent_cast(call,workspace,stem,scene,config,lines,kits,characters):
    """Room listeners retain their approved pose even in a shot with no dialogue."""
    if not config.get('roomSet'): return scene
    from services.set_generation import require_result
    speaking={line['characterId'] for line in lines};bindings=[]
    for entry in config.get('cast',[]):
        if entry['characterId'] in speaking: continue
        kit=kits.get(characters.get(entry['characterId']),{})
        pose=entry.get('poseId','base')
        asset=kit.get('base',{}) if pose=='base' else kit.get('poses',{}).get(pose,{})
        if not asset.get('source') or asset.get('reviewState')!='approved':
            raise ValueError(f"Character {entry['characterId']} needs an approved {pose} pose")
        source=asset['source']
        if not source.startswith(('/api/','http://','https://')):
            from urllib.parse import quote
            source=f"/api/v1/file/{quote(source.removeprefix('outputs/'))}?workspace={quote(workspace)}"
        bindings.append({'object_id':entry['objectId'],'media':'image','source_url':source,'imageLook':{'grounded':True}})
    if not bindings: return scene
    return require_result(call('world3d.scene.patch',{'version':1,'intent_id':f'{stem}-listeners','input':{
        'workspace':workspace,'scene_id':scene['sceneId'],'base_revision':scene['revision'],'bindings':bindings}}))['scene']


class SeriesSets:
    def __init__(self,workspace_dir,read_series,change_series,call,*,inline=False,compiler=None):
        self.workspace_dir,self.read_series,self.change_series,self.call=workspace_dir,read_series,change_series,call
        self.inline,self.compiler=inline,compiler

    def _location(self,data):
        series=self.read_series(data['workspace'],data['series_id'])
        location=next((loc for loc in series['locations'] if loc['id']==data['location_id']),None)
        if location is None: raise ValueError('location not found')
        return series,location

    def _start(self,data,intent):
        series,location=self._location(data);entry={key:data[key] for key in ('mold','size','skin','props') if key in data}
        entry.setdefault('size','medium');entry.setdefault('skin',{});entry.setdefault('props',[])
        mold=resolve_mold(entry['mold'],entry['size']);validate_skin(mold,entry['skin']);validate_props(entry,mold)
        digest=intent_digest([entry,series_style(series)])
        def store(project):
            loc=next(l for l in project['locations'] if l['id']==data['location_id'])
            loc['set3d']=entry;loc.pop('set3dBuilt',None);loc['set3dStatus']={'status':'queued','fingerprint':digest}
            for episode in project.get('episodesById',{}).values():
                for shot in episode.get('shots',[]):
                    if shot.get('locationId')==loc['id'] and shot.get('productionMethod')=='animation_3d':
                        shot.setdefault('scene3d',{})['roomFingerprint']=digest
                        reset_approvals(episode,shot['id'])
        self.change_series(data['workspace'],data['series_id'],store)
        if self.inline: self._build(data,entry,digest)
        else: threading.Thread(target=self._build,args=(data,entry,digest),daemon=True).start()
        return {'location_id':location['id'],'status':'queued','fingerprint':digest}

    def _build(self,data,entry,digest):
        try:
            series,location=self._location(data);root=Path(self.workspace_dir(data['workspace']))
            location_image=None
            if any(value.get('image')=='location' for value in entry['skin'].values()):
                from services.series_shot_plan import background_for
                if location.get('approval')!='approved': raise ValueError('approve the location image before using it as a skin')
                found=background_for(series,{'locationId':location['id']},data['workspace'],('image',))
                location_image=found['source'] if found else None
            skin=build_skin(entry['mold'],entry['size'],entry['skin'],series_style(series),root=root,workspace=data['workspace'],call=self.call,location_image=location_image)
            room={'mold':resolve_mold(entry['mold'],entry['size']),'skin':skin}
            templates=self._templates(room,digest,data['workspace'])
            built={'room':room,'templates':templates,'objects':prop_objects(entry,root)}
            status={'status':'completed','fingerprint':digest}
        except Exception as error:
            built=None;status={'status':'failed','fingerprint':digest,'error':str(error)}
        def finish(project):
            loc=next(l for l in project['locations'] if l['id']==data['location_id'])
            if loc.get('set3dStatus',{}).get('fingerprint')!=digest:return
            loc['set3dStatus']=status
            if built:loc['set3dBuilt']=built
        self.change_series(data['workspace'],data['series_id'],finish)

    def _templates(self,room,digest,workspace):
        from services.production_scene3d import compile_document
        from services.set_generation import require_result
        compile_=self.compiler or compile_document;templates={}
        for camera in room['mold']['cameras']:
            document=compile_({'key':'room','scene3d':{'template':'two-shot','background':{'room':{**room,'camera':camera['id']}}}},5)
            # Until a character is bound, place its marker at the room's first two marks.
            for index,slot in enumerate(s for s in document['slots'] if s['slot'] in {'subject_1','subject_2'}):
                mark=room['mold']['marks'][index];slot.update(position=mark['position'],rotationY=mark['facing']*3.141592653589793/180,scale=.85,surface='cutout')
            # Compiler changes must not replay an older immutable template with the same skin request.
            identity=hashlib.sha256(json.dumps([digest,document],sort_keys=True).encode()).hexdigest()
            id_=f'user-room-{identity[:20]}-{camera["id"]}'
            require_result(self.call('world3d.templates.user.put',{'version':1,'intent_id':f'template-{id_}','input':{'workspace':workspace,'id':id_,'title':id_,'document':document}}))
            templates[camera['id']]=id_
        return templates

    def execute(self,name,arguments):
        try:
            data=arguments['input']
            if arguments.get('version')!=1: raise ValueError('version 1 required')
            if name.endswith('.status'):
                _,location=self._location(data);result={'location_id':location['id'],**location.get('set3dStatus',{'status':'not_configured'})}
            else:
                intent=check_intent_id(arguments.get('intent_id'));root=Path(self.workspace_dir(data['workspace']));digest=intent_digest(data)
                with _LOCK:
                    result=load_intent(root,name,intent,digest)
                    if result is None:
                        result=self._start(data,intent);store_intent(root,name,intent,digest,result)
            return {'version':1,'operation':name,'status':'completed','result':result}
        except IntentConflict as error: raise HTTPException(409,str(error)) from error
        except (ValueError,KeyError) as error: raise HTTPException(422,str(error)) from error

    def handlers(self):
        def handler(name):
            async def run(arguments): return await run_in_threadpool(self.execute,name,arguments)
            return run
        return {name:handler(name) for name in ('series.location.set3d','series.location.set3d.status')}


def command_catalog():
    fields={key:{'type':'string'} for key in ('workspace','series_id','location_id','mold','size')}
    fields.update(skin={'type':'object'},props={'type':'array','items':{'type':'object'}})
    output=[]
    for status in (False,True):
        name='series.location.set3d'+('.status' if status else '')
        props={'version':{'const':1},'input':{'type':'object','properties':fields,'additionalProperties':False,'required':['workspace','series_id','location_id',*([] if status else ['mold'])]}}
        if not status:props['intent_id']={'type':'string'}
        output.append({'name':name,'version':1,'domain':'series','mutation':not status,'destructive':False,
            'description':'Read the room skin build status for a location.' if status else 'Set a location interior mold, size, skin and anchored library props. Builds a cached skin in the series style; its 3D shots inherit the set.',
            'inputSchema':{'type':'object','properties':props,'additionalProperties':False,'required':list(props)}})
    return output
