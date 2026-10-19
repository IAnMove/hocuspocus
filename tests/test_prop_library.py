from pathlib import Path
import pytest
from fastapi import HTTPException
from PIL import Image
from services import prop_library as library
from services.prop_commands import PropService


def row():
    return dict(id='cup',name='Cup',description='red cup',heightM=.15,file='cup.png',style='paper',anchor='bottom',facing='front',approved=False,provenance={})


def test_atomic_revision_and_limit(tmp_path,monkeypatch):
    calls=[]; original=library.os.replace
    monkeypatch.setattr(library.os,'replace',lambda a,b:(calls.append((a,b)),original(a,b))[1])
    saved=library.update_library(tmp_path,lambda rows:rows.append(row()),0)
    assert calls and saved['revision']==1 and library.read_library(tmp_path)==saved
    assert not list(tmp_path.glob('*.tmp'))
    with pytest.raises(HTTPException) as error: library.update_library(tmp_path,lambda rows:None,0)
    assert error.value.status_code==409
    with pytest.raises(ValueError,match='500'): library.update_library(tmp_path,lambda rows:rows.extend([{**row(),'id':str(n)} for n in range(500)]))
    assert library.read_library(tmp_path)==saved


def test_create_generates_crops_and_stores_unapproved_candidates(tmp_path,monkeypatch):
    from services import prop_commands as mod
    calls=[]
    def batch(call,ws,requests,intent):
        assert requests[0]['candidates']==2 and 'no floor' in requests[0]['prompt']
        return [{'files':['one.png','two.png'],'provenance':{'model':'simulated','prompt':requests[0]['prompt'],'seed':1}}]
    monkeypatch.setattr(mod,'generate_batch',batch)
    def call(tool,args):
        calls.append((tool,args)); file=args['input']['source']; Image.new('RGBA',(20,20),(255,0,0,0)).save(tmp_path/file)
        return {'result':{'file':file,'report':{'haze':0}}}
    service=PropService(lambda ws:str(tmp_path),lambda:str(tmp_path/'uploads'),call,inline=True)
    args={'version':1,'intent_id':'new','input':{'workspace':'demo','name':'Lamp','description':'Desk lamp','heightM':.4,'style':'paper-cutout'}}
    job=service.execute('props.create',args)['result']
    assert job['status']=='completed' and len(calls)==2
    rows=library.read_library(tmp_path)['props']
    assert all(p['heightM']==.4 and not p['approved'] for p in rows)
    assert all(args['input']['crop'] for _,args in calls)
    assert service.execute('props.create',args)['result']==job


def test_import_alpha_does_not_key_again(tmp_path):
    Image.new('RGBA',(12,14),(255,0,0,128)).save(tmp_path/'alpha.png')
    def call(*args): raise AssertionError('must not key existing alpha')
    service=PropService(lambda ws:str(tmp_path),lambda:str(tmp_path/'uploads'),call)
    result=service.execute('props.import',{'version':1,'intent_id':'import','input':{'workspace':'demo','name':'Cup','heightM':.2,'source':str(tmp_path/'alpha.png')}})['result']
    assert Image.open(tmp_path/result['prop']['file']).size==(12,14)
    assert result['revision']==1


def test_batch_uses_installed_model_defaults_and_satisfies_native_admission():
    from services.set_generation import generate_batch
    from services.studio_image_spec import freeze_studio_image_spec
    admitted=[]
    def call(name,args):
        if name=='media.options': return {'local':{'image':[{'id':'qwen_image_21_viggle_turbo'}]}}
        if name=='generation.image':
            from services.generation_output_name import prepare_command_output_name
            command,output_name=prepare_command_output_name({'operation':name,**args})
            assert output_name==args['intent_id']
            frozen=freeze_studio_image_spec(command)
            params=frozen['effective']['input']['params']
            from services.studio_image_preparation import _validate_conditioning
            _validate_conditioning(params, {'no_negative_prompt':True})
            admitted.append(params)
            return {'job_id':f'job-{len(admitted)}'}
        assert name=='jobs.wait' and len(admitted)==2
        return {'status':'completed','output_files':['object.png']}
    result=generate_batch(call,'test',[{'prompt':'lamp','negative':'text, watermark, hands','resolution':'1024x1024'},{'prompt':'mug','resolution':'1024x1024'}],'batch-check')
    assert len(result)==2
    assert all(p['num_inference_steps']==6 and p['guidance_scale']==1 for p in admitted)
    assert [p['prompt'] for p in admitted]==['lamp','mug']
    assert all(p['negative_prompt']=='' for p in admitted)
