"""Room sets in production batches and Series, without GPU or server."""
import copy
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
