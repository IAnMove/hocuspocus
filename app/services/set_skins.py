"""Fingerprint-cached surface artwork: elevations, fitted location plates and seamless textures."""
from __future__ import annotations

import hashlib
import json
import re
import threading
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit, parse_qs

import numpy as np
from PIL import Image, ImageOps
from services.game_tiles import roll_half, seam_mask, seam_error, unroll
from services.prop_library import atomic_json
from services.set_generation import generate_batch
from services.set_molds import defaults, resolve_mold, surface_sizes

_LOCK = threading.RLock()
ELEVATION = 'Straight-on elevation of {description}, flat, no perspective, edges are the wall\'s corners, no floor, no ceiling, no people'
TEXTURE = 'Seamless tileable surface texture of {description}, straight-on orthographic view, flat even light, edge to edge, no perspective, no objects, no people'


def validate_skin(mold, skin, *, allow_location=True):
    if not isinstance(skin, dict) or set(skin)-set(mold['surfaces']):
        raise ValueError('skin names unknown surfaces')
    for surface, value in skin.items():
        if not isinstance(value, dict) or len(set(value)&{'color','texture','image','video'}) != 1 or set(value)-{'color','texture','image','video','tile_m'}:
            raise ValueError(f'{surface}: choose color, texture, image or video')
        if 'color' in value and not re.fullmatch(r'#[a-fA-F0-9]{6}', str(value['color'])):
            raise ValueError(f'{surface}: invalid color')
        if 'tile_m' in value and (type(value['tile_m']) not in (int,float) or not 0 < value['tile_m'] <= 30):
            raise ValueError(f'{surface}: invalid tile_m')
        for key in ('texture','image','video'):
            if key not in value: continue
            source = value[key]
            if isinstance(source, dict) and isinstance(source.get('asset'), str): continue
            if key == 'video' or not isinstance(source, str) or not source.strip(): raise ValueError(f'{surface}: asset or prompt required')
            if source == 'location' and (key != 'image' or not allow_location): raise ValueError('location image is only available in Series')


def wall_resolution(width, height):
    cfg=defaults()['wall']; step=cfg['multiple']; long=cfg['longSide']
    factor=long/max(width,height)
    return tuple(max(step, round(n*factor/step)*step) for n in (width,height))


def image_requests(mold, skin, style):
    sizes=surface_sizes(mold); requests={}
    for name,value in skin.items():
        kind=next((k for k in ('image','texture') if k in value),None)
        if not kind or not isinstance(value[kind],str) or value[kind]=='location': continue
        resolution=defaults()['texture']['resolution'] if kind=='texture' else 'x'.join(map(str,wall_resolution(*sizes[name])))
        staging=TEXTURE if kind=='texture' else ELEVATION
        requests[name]={'prompt':f"{style}. {staging.format(description=value[kind])}", 'negative':'text, watermark, people, perspective', 'resolution':resolution}
    return requests


def asset_path(value: str, root: Path, workspace: str) -> Path:
    parsed=urlsplit(str(value))
    if parsed.scheme or parsed.netloc: raise ValueError('skin assets must be local workspace files')
    if parsed.path.startswith('/api/v1/file/'):
        ws=parse_qs(parsed.query).get('workspace',[workspace])[0]
        if ws != workspace: raise ValueError('skin asset belongs to another workspace')
        value=unquote(parsed.path[len('/api/v1/file/'):])
    candidate=Path(value)
    path=(candidate if candidate.is_absolute() else root/candidate).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file(): raise ValueError('skin asset not found in workspace')
    return path


def _url(path, root, workspace):
    return f"/api/v1/file/{quote(path.relative_to(root).as_posix())}?workspace={quote(workspace)}"


def _identity(mold,size,skin,style,location_image,root,workspace):
    files={}
    for name,value in skin.items():
        media=value.get('image',value.get('texture',value.get('video')))
        source=location_image if media=='location' else media.get('asset') if isinstance(media,dict) else None
        if source:
            path=asset_path(str(source),root,workspace);files[name]=hashlib.sha256(path.read_bytes()).hexdigest()
    data=[resolve_mold(mold,size),skin,style,files,defaults()]
    return hashlib.sha256(json.dumps(data,sort_keys=True,allow_nan=False).encode()).hexdigest()


def _heal_pass(picture, request, root, workspace, call, tag, index):
    cfg=defaults()['texture']
    rolled=roll_half(picture)
    guide=root/f'{tag}-guide-{index}.png';mask=root/f'{tag}-mask-{index}.png'
    rolled.save(guide);Image.fromarray(seam_mask(*picture.size,max(2,min(picture.size)//cfg['bandDivisor']))).save(mask)
    response=generate_batch(call,workspace,[{**request,'guide':_url(guide,root,workspace),'mask':_url(mask,root,workspace)}],f'{tag}-heal-{index}')
    with Image.open(asset_path(response[0]['files'][0],root,workspace)) as image:
        return unroll(image.convert('RGB'))


def _heal_texture(picture, request, root, workspace, call, tag):
    """Inpaint the wrap seam: ``1 + extraPasses`` passes, and one more while the last pass still lowered the error
    (a turbo pass costs seconds). The caller decides what a seam still over ``seamMax`` becomes."""
    cfg=defaults()['texture']; error=seam_error(picture); configured=1+cfg['extraPasses']; passes=configured
    for index in range(configured+1):
        if index == passes: break
        before=error
        picture=_heal_pass(picture,request,root,workspace,call,tag,index); error=seam_error(picture)
        if error <= cfg['seamMax']: break
        if index+1 == configured and error < before: passes+=1      # still improving: one last pass
    return picture,error


def _pictures(mold,skin,style,root,workspace,call,tag,provided):
    requests=image_requests(mold,skin,style)
    pending={name:request for name,request in requests.items() if name not in provided}
    if pending and call is None: raise ValueError('generation callback required for skin prompts')
    made=generate_batch(call,workspace,list(pending.values()),tag) if pending else []
    sources={**provided,**{name:row['files'][0] for name,row in zip(pending,made)}}
    return requests,sources


def _surface(name,value,mold,requests,sources,root,workspace,call,tag,location_image):
    if 'color' in value: return dict(value)
    kind=next(k for k in ('texture','image','video') if k in value); source=value[kind]
    raw=location_image if source=='location' else source.get('asset') if isinstance(source,dict) else sources.get(name)
    if not raw: raise ValueError(f'{name}: location image must be approved')
    path=asset_path(str(raw),root,workspace)
    if kind=='video': return {'video':{'asset':_url(path,root,workspace)}}
    with Image.open(path) as opened: picture=opened.convert('RGB')
    metrics={}
    if kind=='texture':
        if name in requests: picture,metrics['seam_error']=_heal_texture(picture,requests[name],root,workspace,call,f'{tag}-{name}')
        target=tuple(map(int,defaults()['texture']['resolution'].split('x')))
        picture=picture.resize(target,Image.Resampling.LANCZOS)
        metrics['seam_error']=round(seam_error(picture),3)
        if metrics['seam_error']>defaults()['texture']['seamMax']:
            # A texture that will not tile must not cost the production: it is painted once over the surface instead.
            kind='image';metrics['fallback']='image'
            picture=ImageOps.fit(picture,wall_resolution(*surface_sizes(mold)[name]),method=Image.Resampling.LANCZOS)
    else:
        from services.diorama_set import trim_border
        if name in requests: picture=trim_border(picture)
        picture=ImageOps.fit(picture,wall_resolution(*surface_sizes(mold)[name]),method=Image.Resampling.LANCZOS)
    destination=root/f'{tag}-{name}.png';picture.save(destination)
    return {kind:{'asset':_url(destination,root,workspace)}, **({'tile_m':value.get('tile_m',defaults()['texture']['tile_m'])} if kind=='texture' else {}), **({'metrics':metrics} if metrics else {})}


def skin_warnings(resolved):
    """``seam_fallback`` for every texture painted once as an image because its seam stayed visible."""
    limit=defaults()['texture']['seamMax']
    return [{'code':'seam_fallback','surface':name,'seam_error':value['metrics']['seam_error'],'limit':limit}
            for name,value in sorted((resolved or {}).items())
            if isinstance(value,dict) and (value.get('metrics') or {}).get('fallback')=='image']


def _hex(rgb):
    return '#'+''.join(f'{int(round(v)):02x}' for v in rgb)


def _auto_color(resolved,requested,mold_defaults,root,workspace):
    """Walls the request leaves alone follow the back wall's mean tone; the floor keeps the mold's colour, else a darker tone."""
    back=resolved.get('wall_back',{})
    source=back.get('image',{}).get('asset') or back.get('texture',{}).get('asset')
    if source:
        with Image.open(asset_path(source,root,workspace)) as image: tone=np.asarray(image.convert('RGB')).mean(axis=(0,1))
    elif re.fullmatch(r'#[a-fA-F0-9]{6}',str(back.get('color',''))): tone=np.array([int(back['color'][i:i+2],16) for i in (1,3,5)],dtype=float)
    else: return
    for name in ('wall_left','wall_right','wall_front'):
        if name in resolved and name not in requested: resolved[name]={'color':_hex(tone)}
    if 'floor' in resolved and 'floor' not in requested and 'floor' not in mold_defaults: resolved['floor']={'color':_hex(tone*defaults()['skin']['floorShade'])}


def build_skin(mold, size, skin, style, *, location_image=None, root=None, workspace='default', call=None, provided=None):
    """Build all requested art in one batch; provided images join the production's larger batch."""
    room=resolve_mold(mold,size);validate_skin(room,skin)
    if root is None: raise ValueError('workspace root is required to persist a skin')
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    tag='skin-'+_identity(mold,size,skin,style,location_image,root,workspace)[:24]
    cache=root/'.set-skins'/f'{tag}.json'
    with _LOCK:
        if cache.is_file():
            result=json.loads(cache.read_text())
            try:
                for value in result.values():
                    for kind in ('image','texture','video'):
                        if kind in value: asset_path(value[kind]['asset'],root,workspace)
                return result
            except ValueError: pass
        requests,sources=_pictures(room,skin,style,root,workspace,call,tag,provided or {})
        values={**{name:{'color':'#d8d2c4'} for name in room['surfaces']},**room['defaultSkin'],**skin}
        resolved={name:_surface(name,value,room,requests,sources,root,workspace,call,tag,location_image) for name,value in values.items()}
        _auto_color(resolved,skin,room['defaultSkin'],root,workspace);atomic_json(cache,resolved)
        return resolved
