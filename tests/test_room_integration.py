"""Room sets in production batches and Series, without GPU or server."""
import copy
import pytest
import json
from pathlib import Path
from types import SimpleNamespace

from services.production_models import check_sets, _set_jobs
from services.production_rooms import dry_run_images, resolve_background
from services.series_sets import SeriesSets, inherit_shot, room_cast_bindings, script_scene3d, mark_warnings
from services.series_shot3d import normalize_scene3d
from services.set_molds import resolve_mold

ROOM={'kind':'room','mold':'despacho','skin':{'wall_back':{'image':'painted cabinets'},'floor':{'texture':'parquet'}}}


def test_surface_images_join_one_batch_and_dry_run_counts(monkeypatch,tmp_path):
    check_sets({'sets':{'office':ROOM}})
    assert dry_run_images({'sets':{'office':ROOM}})=={'room_skin_images':2,'room_sets':{'office':2}}
    from services import production_rooms
    monkeypatch.setattr(production_rooms,'image_model',lambda call:'qwen_image_21_turbo')
    requests=[]
    p=SimpleNamespace(state={},mcp=lambda *a:None,image=lambda *args:requests.append(args) or f'job-{len(requests)}',_attempt=lambda *a:1)
    jobs=_set_jobs(p,{'sets':{'office':ROOM},'style':{'image':'cut paper layers'}})
    assert len(requests)==2 and set(jobs)=={'set:office:wall_back','set:office:floor'}
    assert all('paper' in args[1] and args[5]=='qwen_image_21_turbo' for args in requests)
    p.state['sets']['office']['room']={'cached':True}
    assert _set_jobs(p,{'sets':{'office':ROOM},'style':{'image':'cut paper layers'}})=={}


def test_series_location_skin_build_once_and_inheritance(tmp_path,monkeypatch):
    from services import series_sets
    series={'locations':[{'id':'office'}],'characterVisualStyle':'layered paper','episodesById':{}}
    calls=[];skins=[]
    monkeypatch.setattr(series_sets,'build_skin',lambda *a,**k:skins.append(a) or {'wall_back':{'color':'#998877'}})
    monkeypatch.setattr(series_sets,'prop_objects',lambda *a:[{'objectId':'prop-lamp-1','media':'image','file':'lamp.png','add':True}])
    def call(name,args):calls.append((name,args));return {'result':{}}
    service=SeriesSets(lambda ws:tmp_path,lambda *a:series,lambda ws,sid,fn:fn(series),call,inline=True,
                       compiler=lambda *a:{'slots':[{'slot':'subject_1'},{'slot':'subject_2'}]})
    args={'version':1,'intent_id':'room-office','input':{'workspace':'test','series_id':'s','location_id':'office','mold':'despacho','skin':{}}}
    service.execute('series.location.set3d',args);service.execute('series.location.set3d',args)
    assert len(skins)==1 and len(calls)==7
    assert service.execute('series.location.set3d.status',{'version':1,'input':args['input']})['result']['status']=='completed'
    assert skins[0][3]=='layered paper'
    shot={'productionMethod':'animation_3d','locationId':'office','scene3d':{'template':'two-shot','cast':[{'characterId':'a','objectId':'subject_1','mark':'behind_desk'}]}}
    a,b=inherit_shot(series,shot),inherit_shot(series,{**shot,'id':'b'})
    assert a['scene3d']['objects']==b['scene3d']['objects']
    assert room_cast_bindings(normalize_scene3d(a['scene3d']))[0]['position']==resolve_mold('despacho')['marks'][0]['position']
    assert 'objects' not in shot['scene3d']


def test_compact_script_marks_warn_and_existing_shots_keep_snapshot():
    from services.series_script import EpisodeScript, _cast_entry
    series={'id':'s','characters':[{'id':'a','voiceProfile':{'characterKitRef':{'id':'kit-a'}}}],
            'locations':[{'id':'office','set3d':{'mold':'despacho'}}]}
    shot={'scene':'s1','kind':'3d','cast':[['a','base','not-a-mark']]}
    script={'scenes':[{'id':'s1','location':'office'}],'shots':[shot]}
    built=EpisodeScript(series,script,1,{'kit-a':{'base':{}}},set())
    built._check_cast(shot,'shot 1')
    stored=built.shots()[0]
    assert stored['scene3d']['template']=='two-shot'
    assert stored['scene3d']['cast'][0]['mark']=='not-a-mark'
    assert built.warnings[0]['code']=='unknown_set_mark'
    assert _cast_entry(['a','base',35])=={'characterId':'a','poseId':'base','x':35}
    old={'kind':'3d','scene3d':{'template':'two-shot','cast':[]}}
    before=json.dumps(old,sort_keys=True)
    assert script_scene3d(old,{})==old['scene3d']
    assert json.dumps(old,sort_keys=True)==before
    assert inherit_shot({},old) is old
    assert dry_run_images({})=={}


def test_set_props_resolve_into_every_shot_without_overwriting_own_props():
    room={'mold':resolve_mold('despacho'),'skin':{}}
    sets={'office':{'room':room,'objects':[{'objectId':'lamp','media':'image','file':'lamp.png','add':True,'scale':.2}]}}
    first={'background':'office','cast':{'subject_1':{'source':'a.png'}}}
    second=copy.deepcopy(first)
    for config in (first,second):
        assert resolve_background(config,sets,'test')
        assert config['cast']['lamp']['source']=='/api/v1/file/lamp.png?workspace=test'
    assert first==second
    legacy={'background':'old'};before=copy.deepcopy(legacy)
    assert not resolve_background(legacy,sets,'test') and before==legacy


def test_inherited_items_count_move_hide_and_keep_new_set_skin(tmp_path):
    import pytest
    from PIL import Image
    from services.scene3d_items import ItemService
    from services.series_shot3d import normalize_scene3d
    Image.new('RGBA',(4,4),'red').save(tmp_path/'lamp.png')
    objects=[{'objectId':f'prop-lamp-{i}','media':'image','file':'lamp.png','add':True,'scale':.2,'position':[0,0,0]} for i in range(12)]
    location={'id':'office','set3d':{'mold':'despacho'},'set3dBuilt':{'objects':objects,'templates':{'two_shot':'user-room-test'}}}
    series={'locations':[location]};script={'location':'office','scene3d':{'template':'two-shot','cast':[]}}
    def call(name,args):
        if name=='series.get':return {'result':{'series':series}}
        if name=='series.shot.get':return {'result':{'script':script}}
        if name=='series.shot.update':
            script['scene3d']=normalize_scene3d(args['input']['changes']['scene3d'])
            return {'result':{}}
        raise AssertionError(name)
    service=ItemService(lambda _:str(tmp_path),lambda:str(tmp_path/'uploads'),call)
    target={'workspace':'test','target':{'series_id':'s','episode_id':'e','shot':1}}
    def edit(action,**fields):return service.execute('scene3d.item.'+action,{'version':1,'intent_id':action,'input':{**target,**fields}})['result']
    assert len(edit('list')['items'])==12
    from fastapi import HTTPException
    with pytest.raises(HTTPException,match='13 requested; maximum 12'):
        edit('add',item={'image':'lamp.png'},heightM=.4,at={'anchor':'desk_left'})
    edit('update',id='prop-lamp-0',at={'anchor':'desk_left'})
    assert script['scene3d']['objects'][0]['position']==[-.6,.75,-.8]
    edit('remove',id='prop-lamp-1')
    assert script['scene3d']['removedSetObjects']==['prop-lamp-1']
    assert len(edit('list')['items'])==11 and len(location['set3dBuilt']['objects'])==12
    shot={'productionMethod':'animation_3d','locationId':'office','scene3d':script['scene3d']}
    assert len(inherit_shot(series,shot)['scene3d']['objects'])==11


def test_room_listener_uses_approved_kit_review_state():
    from services.series_sets import bind_silent_cast
    calls=[]
    def call(name,args):calls.append(args['input']);return {'result':{'scene':{'sceneId':'scene','revision':2}}}
    result=bind_silent_cast(call,'test','trial',{'sceneId':'scene','revision':1},
        {'roomSet':{},'cast':[]},[],{}, {})
    assert result['revision']==1
    result=bind_silent_cast(call,'test','trial',{'sceneId':'scene','revision':1},
        {'roomSet':{'mold':'despacho'},'cast':[{'characterId':'a','objectId':'subject_1'}]},[],
        {'kit':{'base':{'source':'a.png','reviewState':'approved'}}},{'a':'kit'})
    assert result['revision']==2 and calls[0]['bindings'][0]['source_url'].endswith('a.png?workspace=test')
    assert calls[0]['bindings'][0]['imageLook']=={'grounded':True}


def test_room_rest_binds_running_event_loop():
    import asyncio
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routers.series_sets import create_series_sets_router
    class Service:
        def handlers(self):
            async def status(args):return {'loop':asyncio.get_running_loop().is_running()}
            return {'series.location.set3d.status':status}
    loops=[];app=FastAPI();app.include_router(create_series_sets_router(Service(),loops.append))
    with TestClient(app) as client:
        result=client.post('/api/v1/series/sets/commands',json={'operation':'series.location.set3d.status'})
    assert result.status_code==200 and result.json()['loop'] and len(loops)==1


@pytest.mark.skipif(not (Path(__file__).resolve().parents[1]/'ui/node_modules').is_dir(), reason='UI compiler dependencies are not installed')
def test_actual_room_compiler_persists_all_seven_templates(tmp_path):
    from services.world3d_scenes import put_user_template
    from services.series_review import content_digest
    series={'locations':[{'id':'office'}],'episodesById':{'e':{'shots':[{'id':'shot','productionMethod':'animation_3d','locationId':'office','scene3d':{'template':'two-shot'},'approvedAttemptId':'take'}]}}}
    stored=series['episodesById']['e']['shots'][0];before=content_digest(stored)
    def call(name,args):
        assert name=='world3d.templates.user.put'
        return {'result':put_user_template('test',lambda _:str(tmp_path),args['input'])}
    service=SeriesSets(lambda _:str(tmp_path),lambda *a:series,lambda ws,sid,fn:fn(series),call,inline=True)
    args={'version':1,'intent_id':'actual-room','input':{'workspace':'test','series_id':'s','location_id':'office','mold':'despacho'}}
    service.execute('series.location.set3d',args)
    loc=series['locations'][0]
    assert loc['set3dStatus']['status']=='completed',loc['set3dStatus']
    assert len(loc['set3dBuilt']['templates'])==7
    assert 'approvedAttemptId' not in stored and content_digest(stored)!=before


def test_room_templates_prepare_cutout_cast_and_fingerprint_compiler_output(tmp_path):
    import copy
    captured=[]
    def call(name,args):
        captured.append(args['input'])
        return {'result':{}}
    document={'slots':[{'id':'subject_1','slot':'subject_1'},{'id':'subject_2','slot':'subject_2'}]}
    service=SeriesSets(lambda _:str(tmp_path),lambda *a:{},lambda *a:None,call,
                       compiler=lambda *a:copy.deepcopy(document))
    room={'mold':resolve_mold('despacho'),'skin':{}}
    first=service._templates(room,'same-skin','test')
    assert all(slot['surface']=='cutout' for template in captured for slot in template['document']['slots'])
    assert service._templates(room,'same-skin','test')==first
    document['rendererRevision']=2
    assert service._templates(room,'same-skin','test')!=first
