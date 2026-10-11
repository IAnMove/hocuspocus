import copy
import pytest
from services.scene3d_items import change_items, ItemService
from services.set_molds import resolve_mold
from services.world3d_scenes import put_user_template, instantiate_template, inspect_scene

ROOM={'mold':resolve_mold('despacho')}
PROP={'file':'lamp.png','heightM':.4,'media':'image','name':'lamp'}


def test_mark_and_table_anchor_ground_and_scale():
    rows,warnings=change_items([],'add',{'at':{'mark':'visitor'}},PROP,ROOM)
    assert rows[0]['position']==[.4,0,.6] and rows[0]['scale']==.2 and not warnings
    moved,warnings=change_items(rows,'update',{'id':rows[0]['objectId'],'at':{'anchor':'desk_left'}},room=ROOM)
    assert moved[0]['position']==[-.6,.75,-.8]
    assert moved[0]['imageLook']['grounded']
    _,warnings=change_items(moved,'update',{'id':moved[0]['objectId'],'heightM':1,'at':{'anchor':'desk_left'}},room=ROOM)
    assert warnings[0]['code']=='item_too_tall'


def test_object_13_is_rejected_and_remove_is_exact():
    rows=[]
    for _ in range(12): rows,_=change_items(rows,'add',{'at':{'position':[0,0,0]}},PROP)
    with pytest.raises(ValueError,match='13 requested; maximum 12'): change_items(rows,'add',{},PROP)
    remaining,_=change_items(rows,'remove',{'id':'prop-lamp-2'})
    assert len(remaining)==11 and all(r['objectId']!='prop-lamp-2' for r in remaining)


def test_list_preserves_legacy_objects_snapshot():
    legacy=[{'objectId':'ship','media':'model3d','file':'ship.glb','clips':[{'clip':'Fly','start':0}]}]
    before=copy.deepcopy(legacy)
    assert change_items(legacy,'list',{})==(before,[])
    assert legacy==before


def test_working_scene_can_add_move_and_remove(tmp_path):
    from PIL import Image
    Image.new('RGBA',(4,4),(255,0,0,255)).save(tmp_path/'lamp.png')
    document={'version':1,'units':'meters','up':'y','templateId':'user-test','width':1280,'height':720,'fps':30,'duration':4,
        'slots':[],'camera':{'family':'fixed','eye':[0,1,2],'look':[0,1,0],'fov':50},'room':ROOM,
        'light':{'kind':'directional','direction':[0,-1,0],'intensity':1,'color':'#ffffff'}}
    directory=lambda ws:str(tmp_path)
    put_user_template('demo',directory,{'id':'user-test','title':'Test','document':document})
    scene=instantiate_template('demo','user-test',directory)
    service=ItemService(directory,lambda:str(tmp_path/'uploads'),lambda *a:None)
    data={'workspace':'demo','target':{'scene_id':scene['sceneId']},'item':{'image':'lamp.png'},'heightM':.4,'at':{'anchor':'desk_left'}}
    result=service.execute('scene3d.item.add',{'version':1,'intent_id':'add','input':data})['result']
    id_=result['items'][0]['objectId']
    assert inspect_scene('demo',scene['sceneId'],directory)['document']['slots'][0]['position'][1]==.75
    update={'workspace':'demo','target':data['target'],'id':id_,'at':{'mark':'visitor'}}
    service.execute('scene3d.item.update',{'version':1,'intent_id':'move','input':update})
    assert inspect_scene('demo',scene['sceneId'],directory)['document']['slots'][0]['position'][1]==0
    service.execute('scene3d.item.remove',{'version':1,'intent_id':'remove','input':{k:v for k,v in update.items() if k!='at'}})
    assert inspect_scene('demo',scene['sceneId'],directory)['document']['slots']==[]
