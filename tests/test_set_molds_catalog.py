import math
import pytest
from services.set_molds import catalog, resolve_mold, CAMERAS, surface_sizes

RECIPES={'despacho','salon','cocina','dormitorio','bar','aula','hemiciclo','plato_tv','sala_prensa','hospital','cabina_avion','vagon','coche_interior','cabina','cabina_nave','juzgado','oficina_diafana'}
SHAPES={'sala','sala_ventana','mostrador','filas','pasillo','umbral','escalera','calle','plaza','orilla','escenario_publico','vehiculo','azotea'}
EXPECTED=RECIPES|SHAPES
CABINS={'cabina','coche_interior','cabina_nave','despacho'}      # a seated mark sits in the seat's own cushion: the occupant is lowered into it


def test_every_mold_has_complete_metadata():
    molds=catalog()
    assert {m['id'] for m in molds}==EXPECTED
    for mold in molds:
        assert len(mold['marks'])>=3 and len(mold['propAnchors'])>=4
        assert {c['id'] for c in mold['cameras']}==set(CAMERAS)
        assert mold['lights'] and mold['defaultSkin']
        if mold['id'] in RECIPES: assert mold['openings'] and mold['blocks']
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
                if block['kind'] in ('seat','bench') and block.get('rot') is not None or block['kind'] in ('seat','chair') and id_ in CABINS: continue   # a seated mark IS on its seat
                bx,by,bz,w,h,d=block['box']
                overlaps=abs(x-bx)<w/2+.2 and abs(z-bz)<d/2+.2 and y<by+h and y+1.7>by
                assert not overlaps,(id_,size,mark['id'],block['id'])


@pytest.mark.parametrize('id_', sorted(EXPECTED))
def test_dialogue_camera_rays_end_on_authored_room_surfaces(id_):
    for size in ('small', 'medium', 'large'):
        mold = resolve_mold(id_, size)
        w, d, h = mold['dimensions']
        bounds = [(-w / 2, w / 2), (0, h), (-d / 2, d / 2)]
        surfaces = [('wall_left', 'wall_right'), ('floor', 'ceiling'), ('wall_back', 'wall_front')]
        for camera in mold['cameras']:
            origin = camera['position']
            direction = [b - a for a, b in zip(origin, camera['lookAt'])]
            exits = []
            for axis, delta in enumerate(direction):
                if abs(delta) < 1e-9:
                    continue
                side = int(delta > 0)
                distance = (bounds[axis][side] - origin[axis]) / delta
                exits.append((distance, surfaces[axis][side]))
            _, surface = min(exits)
            assert surface in mold['surfaces'], (id_, size, camera['id'], surface)
            if surface.startswith('wall_'):
                assert surface.removeprefix('wall_') in mold['walls']


@pytest.mark.parametrize('id_', sorted(EXPECTED))
def test_no_furniture_hides_a_window_or_a_door(id_):
    from services.set_molds import mold_problems
    for size in ('small', 'medium', 'large'):
        assert mold_problems(resolve_mold(id_, size)) == [], (id_, size)


def test_the_check_names_the_wardrobe_that_stood_in_front_of_the_bedroom_window():
    from services.set_molds import mold_problems
    mold = {'dimensions': [6, 6, 3], 'openings': [{'wall': 'left', 'kind': 'window', 'x': 0.45, 'width': 1.5, 'height': 1.3, 'sill': 0.96}],
            'blocks': [{'id': 'wardrobe', 'kind': 'wardrobe', 'box': [-2.55, 0, -1, 0.7, 2.2, 1.6]}, {'id': 'curtain', 'kind': 'curtain', 'box': [-2.9, 0, -0.3, 0.1, 2.4, 1.0]}]}
    assert mold_problems(mold) == ['hidden_opening: wardrobe covers 57% of the width of the left window (and all its height)']
    mold['blocks'][0]['box'][2] = -2.2           # moved along the wall, clear of the glass
    assert mold_problems(mold) == []
