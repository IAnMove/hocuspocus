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
    assert one['wall_left']==one['wall_right']=={'color':'#784628'}
    assert one['floor']=={'color':'#8a6f55'}


def test_floor_without_a_mold_colour_takes_a_darker_wall_tone(tmp_path):
    resolved={'wall_back':{'color':'#c8c8c8'},'floor':{'color':'#d8d2c4'},'wall_left':{'color':'#d8d2c4'},'wall_right':{'color':'#102030'}}
    skins._auto_color(resolved,{'wall_right':{'color':'#102030'}},{},tmp_path,'default')
    assert resolved=={'wall_back':{'color':'#c8c8c8'},'floor':{'color':'#8c8c8c'},'wall_left':{'color':'#c8c8c8'},'wall_right':{'color':'#102030'}}


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


def _small_textures(monkeypatch):
    """Textures stay 128 px so a test picture keeps its own seam (an upscale smooths the inside, not the wrap)."""
    import copy
    config=copy.deepcopy(skins.defaults());config['texture']['resolution']='128x128'
    monkeypatch.setattr(skins,'defaults',lambda:config)


def _ramp(strength):
    """Noise that tiles, plus a left-to-right ramp: the stronger the ramp, the more its wrap shows."""
    noise=np.random.default_rng(3).integers(90,110,(128,128,3))
    ramp=np.tile(np.linspace(0,1,128)[None,:,None],(128,1,3))
    return Image.fromarray(np.clip(noise+strength*ramp*120,0,255).astype(np.uint8))


def _healer(tmp_path,strengths,calls):
    """A fake batch: the first call paints the texture, each heal returns the next picture rolled (the code unrolls it)."""
    def batch(call,ws,requests,tag):
        calls.append(requests)
        picture=_ramp(strengths[len(calls)-1])
        if requests[0].get('guide'): picture=skins.roll_half(picture)
        name=f'made-{len(calls)}.png';picture.save(tmp_path/name)
        return [{'files':[name]}]
    return batch


def test_a_texture_that_will_not_tile_is_painted_once_with_a_warning(tmp_path,monkeypatch):
    _small_textures(monkeypatch);calls=[]
    monkeypatch.setattr(skins,'generate_batch',_healer(tmp_path,[1.0,0.6,0.6],calls))
    result=skins.build_skin('cocina','medium',{'floor':{'texture':'terracotta tiles','tile_m':1}},'paper',root=tmp_path,call=lambda *a:None)
    floor=result['floor']
    assert len(calls)==3, 'two passes that do not improve: no extra pass'
    assert set(floor)=={'image','metrics'} and floor['metrics']['fallback']=='image' and floor['metrics']['seam_error']>1.5
    with Image.open(skins.asset_path(floor['image']['asset'],tmp_path,'default')) as image: assert image.size==(1536,1536)
    assert skins.skin_warnings(result)==[{'code':'seam_fallback','surface':'floor','seam_error':floor['metrics']['seam_error'],'limit':1.5}]


def test_one_more_heal_pass_while_the_seam_still_improves(tmp_path,monkeypatch):
    _small_textures(monkeypatch);calls=[]
    monkeypatch.setattr(skins,'generate_batch',_healer(tmp_path,[1.0,0.6,0.3,0.0],calls))
    floor=skins.build_skin('cocina','medium',{'floor':{'texture':'terracotta tiles'}},'paper',root=tmp_path,call=lambda *a:None)['floor']
    assert len(calls)==4 and 'texture' in floor and floor['metrics']['seam_error']<=1.5 and 'fallback' not in floor['metrics']


def test_a_given_texture_falls_back_and_only_an_unreadable_one_fails(tmp_path,monkeypatch):
    import pytest
    _small_textures(monkeypatch)
    _ramp(1.0).save(tmp_path/'tiles.png');(tmp_path/'broken.png').write_bytes(b'not a picture')
    result=skins.build_skin('cocina','medium',{'floor':{'texture':{'asset':'tiles.png'}}},'paper',root=tmp_path)
    assert result['floor']['metrics']['fallback']=='image' and skins.skin_warnings(result)[0]['surface']=='floor'
    with pytest.raises(OSError):
        skins.build_skin('cocina','medium',{'floor':{'texture':{'asset':'broken.png'}}},'paper',root=tmp_path)
