import numpy as np
from PIL import Image
from services import set_skins as skins
from services.game_tiles import seam_error


def test_wall_ratio_cache_and_automatic_color(tmp_path,monkeypatch):
    calls=[]
    def batch(call,ws,requests,tag):
        calls.append(requests)
        rows=[]
        for index,request in enumerate(requests):
            assert 'straight-on elevation' in request['prompt'].lower()
            name=f'wall-{index}.png';Image.new('RGB',(800,400),(120,70,40)).save(tmp_path/name)
            rows.append({'files':[name]})
        return rows
    monkeypatch.setattr(skins,'generate_batch',batch)
    skin={'wall_back':{'image':'wood panels'}}
    one=skins.build_skin('despacho','medium',skin,'paper',root=tmp_path,call=lambda *a:None)
    two=skins.build_skin('despacho','medium',skin,'paper',root=tmp_path,call=lambda *a:None)
    assert one==two and len(calls)==1
    with Image.open(skins.asset_path(one['wall_back']['image']['asset'],tmp_path,'default')) as image: assert image.size==(1536,768)
    assert one['floor']=={'color':'#784628'}


def test_location_is_fitted_without_generation(tmp_path):
    Image.new('RGB',(400,800),(40,60,100)).save(tmp_path/'location.png')
    result=skins.build_skin('despacho','medium',{'wall_back':{'image':'location'}},'paper',root=tmp_path,location_image='location.png')
    with Image.open(skins.asset_path(result['wall_back']['image']['asset'],tmp_path,'default')) as image:
        assert image.size==(1536,768) and image.getpixel((0,0))==(40,60,100)


def test_texture_roll_heals_below_threshold(tmp_path,monkeypatch):
    calls=[]
    def batch(call,ws,requests,tag):
        calls.append(requests)
        image=np.zeros((128,128,3),dtype=np.uint8)
        image[:,:64]=120 if len(calls)==1 else 0
        name=f'generated-{len(calls)}.png';Image.fromarray(image).save(tmp_path/name)
        return [{'files':[name]}]
    monkeypatch.setattr(skins,'generate_batch',batch)
    result=skins.build_skin('despacho','medium',{'floor':{'texture':'parquet'}},'realistic',root=tmp_path,call=lambda *a:None)
    assert len(calls)==2 and calls[1][0]['guide'] and calls[1][0]['mask']
    with Image.open(skins.asset_path(result['floor']['texture']['asset'],tmp_path,'default')) as image: assert seam_error(image)<=1.5


def test_all_surface_images_admitted_in_one_batch(tmp_path,monkeypatch):
    def batch(call,ws,requests,tag):
        assert len(requests)==2
        Image.new('RGB',(100,100),'red').save(tmp_path/'image.png')
        return [{'files':['image.png']} for _ in requests]
    monkeypatch.setattr(skins,'generate_batch',batch)
    result=skins.build_skin('despacho','medium',{'wall_back':{'image':'panels'},'desk_front':{'image':'drawers'}},'paper',root=tmp_path,call=lambda *a:None)
    assert 'image' in result['desk_front']
