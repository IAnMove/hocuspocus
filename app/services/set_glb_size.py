"""Measure the world-space bounds of an inspected GLB without an optional mesh engine."""
from __future__ import annotations

import itertools
import json
from pathlib import Path

import numpy as np
from services.procedural_3d.glb_container import parse_glb_container
from services.procedural_3d.glb_inspector import GlbInspectorLimits, inspect_glb


def _matrix(node):
    if 'matrix' in node:
        return np.asarray(node['matrix'],dtype=float).reshape(4,4,order='F')
    x,y,z,w=node.get('rotation',[0,0,0,1])
    matrix=np.array([[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w),0],
        [2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w),0],
        [2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y),0],[0,0,0,1]],dtype=float)
    matrix=matrix@np.diag([*node.get('scale',[1,1,1]),1])
    matrix[:3,3]=node.get('translation',[0,0,0])
    return matrix


def _mesh_corners(document,index):
    for primitive in document['meshes'][index]['primitives']:
        accessor=document['accessors'][primitive['attributes']['POSITION']]
        low,high=accessor.get('min'),accessor.get('max')
        if not isinstance(low,list) or not isinstance(high,list) or len(low)!=3 or len(high)!=3:
            raise ValueError('GLB needs position bounds to measure its height; provide heightM')
        yield from ([*corner,1] for corner in itertools.product(*zip(low,high)))


def glb_height(path):
    path=Path(path)
    limits=GlbInspectorLimits()
    if inspect_glb(path,limits=limits).status!='valid': raise ValueError('GLB inspector rejected this asset')
    container=parse_glb_container(path.read_bytes(),max_chunks=limits.max_chunks,max_json_bytes=limits.max_json_bytes)
    document=json.loads(container.json_bytes)
    nodes=document.get('nodes',[])
    scene=document.get('scenes',[])[document.get('scene',0)] if document.get('scenes') else None
    children={child for node in nodes for child in node.get('children',[])}
    roots=scene.get('nodes',[]) if scene is not None else [i for i in range(len(nodes)) if i not in children]
    heights=[]
    def visit(index,parent,ancestors):
        if index in ancestors or len(ancestors)>64: raise ValueError('GLB node hierarchy cannot be measured')
        node=nodes[index];matrix=parent@_matrix(node)
        if 'mesh' in node:
            heights.extend(float((matrix@corner)[1]) for corner in _mesh_corners(document,node['mesh']))
        for child in node.get('children',[]): visit(child,matrix,(*ancestors,index))
    for index in roots:visit(index,np.eye(4),())
    if not heights or not np.isfinite(heights).all(): raise ValueError('GLB has no measurable height; provide heightM')
    height=max(heights)-min(heights)
    if not .01<=height<=30: raise ValueError('GLB height is outside 0.01 to 30 metres; provide heightM')
    return height
