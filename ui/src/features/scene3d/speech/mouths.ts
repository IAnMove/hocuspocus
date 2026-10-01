// Adapted from the user-owned Taberna talking-character kit. Procedural art, no network dependencies.
import * as THREE from 'three';
import { VISEMES } from './types';
const SHAPES = { rest:{open:0,wide:.72,round:0},M:{open:.01,wide:.68,round:0},A:{open:.95,wide:.82,round:.08},E:{open:.55,wide:1,round:0},I:{open:.26,wide:1,round:0},O:{open:.72,wide:.51,round:.9},U:{open:.34,wide:.4,round:1},F:{open:.15,wide:.77,round:0},L:{open:.48,wide:.8,round:.1} };
import { eyeUniforms, EYE_DECLARATIONS } from './eyes.js';

const SIZE = 256;
function openingPath(ctx: CanvasRenderingContext2D, w: number, h: number, round: number) {
  ctx.beginPath();
  if(round>.7) ctx.ellipse(0,0,w*.5,h*.5,0,0,Math.PI*2);
  else {ctx.moveTo(-w*.5,0);ctx.bezierCurveTo(-w*.35,-h*.58,w*.35,-h*.58,w*.5,0);ctx.bezierCurveTo(w*.35,h*.58,-w*.35,h*.58,-w*.5,0);}
  ctx.closePath();
}
export function createAtlas(art='soft', lip='#874d47') {
  const bold=art==='toon-bold';
  const canvas=document.createElement('canvas');canvas.width=SIZE*VISEMES.length;canvas.height=SIZE;
  const ctx=canvas.getContext('2d')!;
  for(let i=0;i<VISEMES.length;i++){
    const v=VISEMES[i], p=SHAPES[v];ctx.save();ctx.translate(SIZE*(i+.5),SIZE*.5);
    const w=SIZE*.79*p.wide, h=SIZE*(.015+p.open*.56);
    if(art==='pixel'){
      const tiny=document.createElement('canvas');tiny.width=32;tiny.height=32;const t=tiny.getContext('2d')!;
      t.translate(16,16);const pw=Math.round(w/8),ph=Math.max(1,Math.round(h/8));
      t.fillStyle=lip;t.fillRect(-Math.floor(pw/2)-1,-Math.floor(ph/2)-1,pw+2,ph+2);t.fillStyle='#351c22';t.fillRect(-Math.floor(pw/2),-Math.floor(ph/2),pw,ph);
      if(p.open>.18){t.fillStyle='#eee1c9';t.fillRect(-Math.floor(pw/2)+1,-Math.floor(ph/2),Math.max(1,pw-2),Math.min(2,ph-1));}
      ctx.imageSmoothingEnabled=false;ctx.drawImage(tiny,-128,-128,256,256);ctx.restore();continue;
    }
    if(v==='rest'||v==='M'){
      ctx.strokeStyle=lip;ctx.lineWidth=bold?32:v==='M'?4:3;ctx.lineCap='round';ctx.beginPath();ctx.moveTo(-w*.46,0);ctx.quadraticCurveTo(0,v==='rest'?(bold?12:7):0,w*.46,0);ctx.stroke();
      if(art==='toon'||bold){ctx.strokeStyle='#3b2429';ctx.lineWidth=bold?8:2;ctx.stroke();}ctx.restore();continue;
    }
    openingPath(ctx,w,h,p.round);ctx.fillStyle='#321c22';ctx.fill();ctx.strokeStyle=lip;ctx.lineWidth=bold?24:art==='toon'?9:4;ctx.stroke();ctx.save();ctx.clip();
    const grad=ctx.createLinearGradient(0,-h/2,0,h/2);grad.addColorStop(0,'#1e1219');grad.addColorStop(1,'#63313b');ctx.fillStyle=grad;ctx.fillRect(-128,-128,256,256);
    if(v!=='O'&&v!=='U'){
      ctx.fillStyle='#eee0c7';ctx.beginPath();ctx.moveTo(-w*.46,-h*.28);ctx.quadraticCurveTo(0,-h*.66,w*.46,-h*.28);ctx.lineTo(w*.42,-h*.04);ctx.quadraticCurveTo(0,-h*.16,-w*.42,-h*.04);ctx.fill();
      if(art==='toon'){ctx.strokeStyle='#bbaa94';ctx.lineWidth=1;for(let k=-2;k<3;k++){ctx.beginPath();ctx.moveTo(k*w*.13,-h*.5);ctx.lineTo(k*w*.13,-h*.12);ctx.stroke();}}
    }
    if(p.open>.38||v==='L'){
      ctx.fillStyle=art==='soft'?'#9a5a60':'#c46d77';ctx.beginPath();ctx.ellipse(0,h*(v==='L'?-.05:.43),w*.27,h*(v==='L'?.55:.25),0,0,Math.PI*2);ctx.fill();
    }
    if(v==='F'){ctx.fillStyle=lip;ctx.beginPath();ctx.ellipse(0,h*.5,w*.43,h*.38,0,0,Math.PI*2);ctx.fill();}
    ctx.restore();
    if(art==='soft'){ctx.strokeStyle=lip;ctx.globalAlpha=.5;ctx.lineWidth=2;ctx.beginPath();ctx.ellipse(0,0,w*.49,h*.5,0,.15,Math.PI-.15);ctx.stroke();}
    ctx.restore();
  }
  const texture=new THREE.CanvasTexture(canvas);texture.colorSpace=THREE.SRGBColorSpace;texture.minFilter=THREE.LinearFilter;texture.magFilter=art==='pixel'?THREE.NearestFilter:THREE.LinearFilter;texture.generateMipmaps=false;
  return texture;
}

export function faceMaterial(mesh: THREE.Mesh<THREE.BufferGeometry, THREE.MeshStandardMaterial>, atlas: THREE.Texture, withMouth: boolean) {
  const material=mesh.material.clone();
  const uniforms={
    ...eyeUniforms(),
    faceCenter:{value:new THREE.Vector3()},faceSize:{value:new THREE.Vector2(.1,.08)},skinColor:{value:new THREE.Color('#c49378')},cleanSkin:{value:1},faceEnabled:{value:1},
    mouthAtlas:{value:atlas},mouthA:{value:0},mouthB:{value:0},mouthMix:{value:1},mouthStrength:{value:1},paintMouth:{value:withMouth?1:0},
  };
  material.onBeforeCompile=shader=>{
    Object.assign(shader.uniforms,uniforms);
    shader.vertexShader=shader.vertexShader.replace('#include <common>','#include <common>\nvarying vec3 mouthRest;').replace('#include <begin_vertex>','#include <begin_vertex>\nmouthRest = position;');
    shader.fragmentShader=shader.fragmentShader.replace('#include <common>',`#include <common>
      varying vec3 mouthRest;
      uniform vec3 faceCenter; uniform vec2 faceSize; uniform vec3 skinColor;
      uniform float cleanSkin, faceEnabled, mouthA, mouthB, mouthMix, mouthStrength, paintMouth;
      uniform sampler2D mouthAtlas;
      ${EYE_DECLARATIONS}
    `).replace('#include <color_fragment>',`#include <color_fragment>
      vec2 mouthPoint=(mouthRest.xy-faceCenter.xy)/faceSize;
      float faceDepth=max(faceSize.x,faceSize.y);
      float front=smoothstep(faceCenter.z-faceDepth*0.22,faceCenter.z-faceDepth*0.06,mouthRest.z);
      float erase=(1.0-smoothstep(0.24,0.52,length(mouthPoint*vec2(1.0,1.5))))*front*cleanSkin*faceEnabled;
      diffuseColor.rgb=mix(diffuseColor.rgb,skinColor,erase);
      float mouthInk=0.0; vec3 mouthTint=vec3(0.0);
      vec2 mp=mouthPoint;
      mp.y /= max(0.12,mouthStrength);
      vec2 mu=mp+0.5;
      if(mu.x>=0.0&&mu.x<=1.0&&mu.y>=0.0&&mu.y<=1.0){
        vec4 ma=texture2D(mouthAtlas,vec2((mu.x+mouthA)/9.0,mu.y));
        vec4 mb=texture2D(mouthAtlas,vec2((mu.x+mouthB)/9.0,mu.y));
        // Blend premultiplied colors, then composite once to avoid a dark halo.
        float alpha=mix(ma.a,mb.a,mouthMix);
        vec3 color=mix(ma.rgb*ma.a,mb.rgb*mb.a,mouthMix)/max(alpha,0.00001);
        mouthInk=alpha*front*paintMouth*faceEnabled*step(0.001,mouthStrength);
        mouthTint=color;
        diffuseColor.rgb=mix(diffuseColor.rgb,color,mouthInk);
      }
      vec4 eyeLP=eyeLayer(mouthRest,eyeLeft,eyeSize,eyeSkinLeft,-1.0,eyeExpression,eyeBlink,eyeBrows);
      vec4 eyeRP=eyeLayer(mouthRest,eyeRight,eyeSize,eyeSkinRight,1.0,eyeExpression,eyeBlink,eyeBrows);
      eyeLP.a*=eyesEnabled*faceEnabled; eyeRP.a*=eyesEnabled*faceEnabled;
      diffuseColor.rgb=mix(diffuseColor.rgb,eyeLP.rgb,eyeLP.a);
      diffuseColor.rgb=mix(diffuseColor.rgb,eyeRP.rgb,eyeRP.a);
    `).replace('#include <emissivemap_fragment>',`#include <emissivemap_fragment>
      totalEmissiveRadiance=mix(totalEmissiveRadiance,skinColor*emissive,erase);
      totalEmissiveRadiance=mix(totalEmissiveRadiance,mouthTint*emissive,mouthInk);
      totalEmissiveRadiance=mix(totalEmissiveRadiance,eyeLP.rgb*emissive,eyeLP.a);
      totalEmissiveRadiance=mix(totalEmissiveRadiance,eyeRP.rgb*emissive,eyeRP.a);
    `);
  };
  material.customProgramCacheKey=()=>`taberna-face-v7-eyes-${withMouth}`;
  mesh.material=material;
  return {material,uniforms};
}
