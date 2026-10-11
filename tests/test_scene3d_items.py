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
    Image.new('RGBA',(4,4),(0,0,255,255)).save(tmp_path/'new-lamp.png')
    service.execute('scene3d.item.update',{'version':1,'intent_id':'new-image','input':{
        'workspace':'demo','target':data['target'],'id':id_,'item':{'image':'new-lamp.png'}}})
    slot=inspect_scene('demo',scene['sceneId'],directory)['document']['slots'][0]
    assert slot['scale']==.2 and slot['setItem']['heightM']==.4
    assert 'new-lamp.png' in slot['sourceUrl']
    service.execute('scene3d.item.remove',{'version':1,'intent_id':'remove','input':{k:v for k,v in update.items() if k!='at'}})
    assert inspect_scene('demo',scene['sceneId'],directory)['document']['slots']==[]


def test_editor_scale_preserves_physical_height_on_next_move():
    from services.series_shot3d import normalize_scene3d
    rows,_=change_items([],'add',{'at':{'position':[0,0,0]}},PROP)
    rows[0]['scale']=.6
    config=normalize_scene3d({'template':'two-shot','objects':rows})
    moved,_=change_items(config['objects'],'update',{'id':rows[0]['objectId'],'at':{'position':[1,0,0]}})
    assert moved[0]['scale']==.6 and moved[0]['setItem']['heightM']==1.2


def test_existing_glb_uses_inspected_world_height_without_mesh_engine(tmp_path):
    import pygltflib
    from tests.test_glb_cleanup import write_parts_glb
    from services.set_glb_size import glb_height
    path=write_parts_glb(tmp_path/'object.glb',[(9,0,1.3)])
    model=pygltflib.GLTF2().load_binary(str(path))
    model.nodes.append(pygltflib.Node(children=[0],scale=[1,2,1],translation=[0,10,0]))
    model.scenes[0].nodes=[1]
    model.save_binary(str(path))
    assert glb_height(path)==pytest.approx(2.6)
    service=ItemService(lambda _:str(tmp_path),lambda:str(tmp_path/'uploads'),lambda *a:None)
    item=service._item({'workspace':'demo','item':{'glb':'object.glb'}})
    assert item['heightM']==pytest.approx(2.6)
