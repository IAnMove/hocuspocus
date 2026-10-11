import math
import pytest
from services.set_molds import catalog, resolve_mold, CAMERAS, surface_sizes

EXPECTED={'despacho','salon','cocina','dormitorio','bar','aula','hemiciclo','plato_tv','sala_prensa','hospital','cabina_avion','vagon','coche_interior','juzgado','oficina_diafana'}


def test_fifteen_molds_have_complete_metadata():
    molds=catalog()
    assert {m['id'] for m in molds}==EXPECTED
    for mold in molds:
        assert len(mold['marks'])>=3 and len(mold['propAnchors'])>=4
        assert {c['id'] for c in mold['cameras']}==set(CAMERAS)
        assert mold['lights'] and mold['defaultSkin'] and mold['openings'] and mold['blocks']
        for size in ('small','medium','large'): assert set(surface_sizes(resolve_mold(mold['id'],size)))==set(mold['surfaces'])


def in_cone(camera, mark):
    direction=[b-a for a,b in zip(camera['position'],camera['lookAt'])]
    head=[*mark['position']];head[1]+=1.1
    to=[b-a for a,b in zip(camera['position'],head)]
    cosine=sum(a*b for a,b in zip(direction,to))/(math.sqrt(sum(n*n for n in direction))*math.sqrt(sum(n*n for n in to)))
    return cosine>=math.cos(math.radians(camera['fov']/2))


@pytest.mark.parametrize('id_',sorted(EXPECTED))
def test_seven_cameras_see_a_character_and_seated_marks_clear_boxes(id_):
    for size in ('small','medium','large'):
        mold=resolve_mold(id_,size)
        for camera in mold['cameras']:
            assert any(in_cone(camera,mark) for mark in mold['marks']), (id_,size,camera['id'])
        for mark in mold['marks']:
            if mark['pose']!='sit': continue
            x,y,z=mark['position']
            for block in mold['blocks']:
                bx,by,bz,w,h,d=block['box']
                overlaps=abs(x-bx)<w/2+.2 and abs(z-bz)<d/2+.2 and y<by+h and y+1.7>by
                assert not overlaps,(id_,size,mark['id'],block['id'])
