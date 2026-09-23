import {
  BoxGeometry, Color, DataTexture, Group, HemisphereLight, Mesh, MeshStandardMaterial, NearestFilter, NoColorSpace,
  PlaneGeometry, RedFormat, RGBAFormat, SRGBColorSpace, ShaderMaterial, UnsignedByteType, Vector2, Vector4,
  type Object3D, type Scene,
} from 'three'
import { Reflector } from 'three/addons/objects/Reflector.js'
import { ENERGY_NOISE } from '../../sceneFx/energyShaders'
import { fxRandom } from '../../sceneFx/types'
import { hexRgb, paletteAt, type PixelPalette } from './pixelPalettes'
import { INDEX, paintRange, paintReeds, paintSky, type IndexedLayer } from './pixelPaint'
import { defaultPixelWorld, type PixelWorld } from './pixelWorld'

export type PixelDressing = 'pixel-lake' | 'pixel-peaks' | 'pixel-gallery'
export const PIXEL_DRESSINGS: readonly PixelDressing[] = ['pixel-lake', 'pixel-peaks', 'pixel-gallery']
export function isPixelDressing(kind: unknown): kind is PixelDressing {
  return typeof kind === 'string' && (PIXEL_DRESSINGS as readonly string[]).includes(kind)
}

type LayerSpec = { z: number; width: number; height: number; bottom: number; texture: [number, number]; sky?: boolean; paint: (w: number, h: number) => IndexedLayer }
type PixelRuntime = { palette: DataTexture; bytes: Uint8Array; skies: ShaderMaterial[]; water?: ShaderMaterial; sky: [number, number] }

const METEOR_LIFE = 1.3

const LAYER_VERTEX = `varying vec2 vUv; void main(){ vUv=uv; gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.); }`
const LAYER_FRAGMENT = `varying vec2 vUv;
  uniform sampler2D uIndex, uPalette; uniform vec2 uRes; uniform float uTime, uAurora, uSky, uHorizon;
  uniform vec3 uAuroraColor, uMeteorColor; uniform vec4 uMeteors[3];
  ${ENERGY_NOISE}
  float bayer4(vec2 p){ vec2 q=mod(p,4.); float i=q.y*4.+q.x;
    return (i==0.?0.:i==1.?8.:i==2.?2.:i==3.?10.:i==4.?12.:i==5.?4.:i==6.?14.:i==7.?6.:i==8.?3.:i==9.?11.:i==10.?1.:i==11.?9.:i==12.?15.:i==13.?7.:i==14.?13.:5.)/16.; }
  vec3 aurora(vec2 cell){
    float x=cell.x, y=cell.y;
    float base=uHorizon*.34+sin(x*.011+uTime*.22)*uHorizon*.05+(noise2(vec2(x*.018,uTime*.08))-.5)*uHorizon*.12;
    float v=(y-base)/(uHorizon*.3);
    if(v<-.2||v>1.) return vec3(0.);
    float curtain=exp(-max(0.,-v)*18.)*pow(1.-max(v,0.),2.2);
    float rays=.55+.45*sin(x*.33+noise2(vec2(x*.045,uTime*.35))*7.);
    float wave=.55+.45*sin(x*.045-uTime*1.1);
    float amount=uAurora*curtain*rays*wave;
    float level=floor(min(1.,amount*2.2)*4.+bayer4(cell))/4.;
    return uAuroraColor*level*.8;
  }
  vec3 meteors(vec2 cell){
    vec3 add=vec3(0.);
    for(int i=0;i<3;i++){
      vec4 m=uMeteors[i]; if(m.w<=0.) continue;
      vec2 dir=vec2(cos(m.z),sin(m.z)), head=m.xy;
      vec2 d=cell+.5-head; float along=-dot(d,dir), across=abs(dot(d,vec2(-dir.y,dir.x)));
      float len=42.*min(1.,m.w*4.);
      if(along<-2.||along>len) continue;
      float a=max(0.,along)/len;
      float width=mix(2.2,.4,a);
      if(across>width) continue;
      float glow=pow(1.-a,1.6)*(1.-smoothstep(.75,1.,m.w));
      if(bayer4(cell)>glow*1.2) continue;
      add+=mix(uMeteorColor,vec3(1.),step(along,2.5))*glow*1.4;
    }
    return add;
  }
  void main(){
    vec2 cell=floor(vUv*uRes); vec2 uv=(cell+.5)/uRes;
    float index=floor(texture2D(uIndex,uv).r*255.+.5);
    if(index<.5) discard;
    vec3 color=texture2D(uPalette,vec2((index+.5)/256.,.5)).rgb;
    if(uSky>.5) color+=aurora(vec2(cell.x,uRes.y-1.-cell.y))+meteors(vec2(cell.x,uRes.y-1.-cell.y));
    gl_FragColor=vec4(color,1.);
    #include <colorspace_fragment>
  }`

function indexTexture(layer: IndexedLayer) {
  // Rows are painted top-down; textures start at the bottom.
  const flipped = new Uint8Array(layer.data.length)
  for (let y = 0; y < layer.height; y++) flipped.set(layer.data.subarray(y * layer.width, (y + 1) * layer.width), (layer.height - 1 - y) * layer.width)
  const texture = new DataTexture(flipped, layer.width, layer.height, RedFormat, UnsignedByteType)
  texture.magFilter = texture.minFilter = NearestFilter
  texture.generateMipmaps = false
  texture.colorSpace = NoColorSpace
  texture.needsUpdate = true
  return texture
}

function layerMesh(spec: LayerSpec, palette: DataTexture) {
  const [width, height] = spec.texture
  const material = new ShaderMaterial({
    name: 'pixel-world-layer',
    uniforms: {
      uIndex: { value: indexTexture(spec.paint(width, height)) }, uPalette: { value: palette },
      uRes: { value: new Vector2(width, height) }, uTime: { value: 0 }, uAurora: { value: 0 }, uSky: { value: spec.sky ? 1 : 0 },
      uHorizon: { value: height }, uAuroraColor: { value: new Color() }, uMeteorColor: { value: new Color() },
      uMeteors: { value: [new Vector4(0, 0, 0, 0), new Vector4(0, 0, 0, 0), new Vector4(0, 0, 0, 0)] },
    },
    vertexShader: LAYER_VERTEX, fragmentShader: LAYER_FRAGMENT, depthWrite: true,
  })
  const mesh = new Mesh(new PlaneGeometry(spec.width, spec.height), material)
  mesh.position.set(0, spec.bottom + spec.height / 2, spec.z)
  mesh.userData.pixelLayer = true
  return mesh
}

/** Lake water: the real scene mirrored, broken into rippling pixel rows,
 *  tinted by the palette, with glints where something bright reflects. */
function water(width: number, depth: number, z: number, calm: number) {
  const reflectorShader = (Reflector as unknown as { ReflectorShader: { uniforms: Record<string, { value: unknown }>; vertexShader: string } }).ReflectorShader
  const shader = {
    uniforms: { ...reflectorShader.uniforms, uTime: { value: 0 }, uWater: { value: new Color('#121433') }, uCell: { value: 3 }, uCalm: { value: calm } },
    vertexShader: reflectorShader.vertexShader.replace('varying vec4 vUv;', 'varying vec4 vUv; varying vec3 vWorld;')
      .replace('vUv = textureMatrix', 'vWorld=(modelMatrix*vec4(position,1.)).xyz; vUv = textureMatrix'),
    fragmentShader: `uniform vec3 color; uniform sampler2D tDiffuse; uniform float uTime, uCell, uCalm; uniform vec3 uWater;
      varying vec4 vUv; varying vec3 vWorld; ${ENERGY_NOISE}
      void main(){
        float row=floor(gl_FragCoord.y/uCell);
        float wobble=(noise2(vec2(row*.37,uTime*.9))-.5)*.016*(1.-uCalm);
        vec2 uv=vUv.xy/vUv.w+vec2(wobble,0.);
        vec3 reflected=texture2D(tDiffuse,uv).rgb;
        float lum=dot(reflected,vec3(.3,.59,.11));
        float dash=step(.52,noise2(vec2(floor(gl_FragCoord.x/(uCell*4.))+row*13.1,floor(uTime*5.)+row*.7)));
        float near=smoothstep(-6.,12.,vWorld.z);
        vec3 c=mix(uWater,reflected*vec3(.72,.76,.92),mix(.62,.35,near));
        c+=reflected*smoothstep(.35,.9,lum)*dash*(1.-uCalm*.8)*.9;
        gl_FragColor=vec4(c,1.);
        #include <colorspace_fragment>
      }`,
  }
  const mirror = new Reflector(new PlaneGeometry(width, depth), { textureWidth: 640, textureHeight: 360, clipBias: .003, shader })
  mirror.rotation.x = -Math.PI / 2
  mirror.position.set(0, 0, z)
  return mirror
}

function lakeLayers(peaks: boolean): LayerSpec[] {
  const seed = peaks ? 311 : 97
  return [
    { z: -62, width: 170, height: 52, bottom: -4, texture: [700, 214], sky: true,
      paint: (w, h) => paintSky(w, h, { seed, horizonRow: Math.round(h * .92), stars: peaks ? 260 : 340, moon: { x: peaks ? .36 : .59, y: .58, radius: 11 } }) },
    { z: -46, width: 130, height: peaks ? 24 : 18, bottom: -1.5, texture: [680, peaks ? 126 : 94],
      paint: (w, h) => paintRange(w, h, { seed: seed + 1, base: h * .72, rough: h * .2, peaks: peaks ? 6 : 4, peakLift: h * (peaks ? .55 : .45), body: INDEX.far, rim: INDEX.farRim, shade: INDEX.farShade, lightFrom: peaks ? .36 : .59, mist: true }) },
    { z: -37, width: 110, height: 7, bottom: -1, texture: [720, 46],
      paint: (w, h) => paintRange(w, h, { seed: seed + 2, base: h * (peaks ? .8 : .5), rough: h * (peaks ? .08 : .25), peaks: 2, body: INDEX.near, rim: INDEX.nearRim, lightFrom: .5, trees: !peaks }) },
    { z: 4.5, width: 7, height: 1.15, bottom: -.02, texture: [480, 80], paint: (w, h) => paintReeds(w, h, seed + 3) },
  ]
}

function gallery(root: Group) {
  const wall = new MeshStandardMaterial({ color: 0x0c0c10, roughness: .9 })
  for (const [w, h, d, x, y, z] of [[26, 9, .3, 0, 4.5, -4.2], [.3, 9, 14, -10, 4.5, 1.5], [.3, 9, 14, 10, 4.5, 1.5], [26, .3, 14, 0, 9, 1.5]]) {
    const mesh = new Mesh(new BoxGeometry(w, h, d), wall)
    mesh.position.set(x, y, z)
    root.add(mesh)
  }
}

export function pixelWorldGroup(kind: PixelDressing): Object3D {
  const root = new Group()
  const bytes = new Uint8Array(256 * 4)
  const palette = new DataTexture(bytes, 256, 1, RGBAFormat, UnsignedByteType)
  palette.colorSpace = SRGBColorSpace
  palette.magFilter = palette.minFilter = NearestFilter
  palette.generateMipmaps = false
  const runtime: PixelRuntime = { palette, bytes, skies: [], sky: [700, 214] }
  if (kind === 'pixel-gallery') {
    gallery(root)
    const floor = water(26, 14, 1.5, .85)
    runtime.water = floor.material as ShaderMaterial
    root.add(floor)
  } else {
    // The frozen peaks rise straight out of the lake, without a wooded shore.
    for (const spec of lakeLayers(kind === 'pixel-peaks').filter((_spec, i) => !(kind === 'pixel-peaks' && i === 2))) {
      const mesh = layerMesh(spec, palette)
      if (spec.sky) runtime.skies.push(mesh.material as ShaderMaterial)
      root.add(mesh)
    }
    const lake = water(150, 54, -11, kind === 'pixel-peaks' ? .55 : 0)
    runtime.water = lake.material as ShaderMaterial
    root.add(lake)
  }
  root.userData.pixelWorld = runtime
  return root
}

function writeColor(bytes: Uint8Array, index: number, hex: string, scale = 1) {
  const [r, g, b] = hexRgb(hex)
  bytes.set([Math.round(Math.min(1, r * scale) * 255), Math.round(Math.min(1, g * scale) * 255), Math.round(Math.min(1, b * scale) * 255), 255], index * 4)
}

function mix(a: string, b: string, t: number) {
  const x = hexRgb(a), y = hexRgb(b)
  return '#' + x.map((v, i) => Math.round((v + (y[i] - v) * t) * 255).toString(16).padStart(2, '0')).join('')
}

/** Every palette slot for this moment: the mood plus the cycling ranges. */
export function writePalette(bytes: Uint8Array, palette: PixelPalette, seconds: number) {
  for (let step = 0; step < INDEX.skySteps; step++) {
    const t = step / (INDEX.skySteps - 1)
    writeColor(bytes, INDEX.sky + step, t < .55 ? mix(palette.sky[0], palette.sky[1], t / .55) : mix(palette.sky[1], palette.sky[2], (t - .55) / .45))
  }
  for (let star = 0; star < INDEX.starSteps; star++) {
    const twinkle = .3 + .7 * (.5 + .5 * Math.sin(seconds * 1.9 + star * 2.1))
    writeColor(bytes, INDEX.star + star, mix(palette.sky[0], palette.stars, twinkle))
  }
  writeColor(bytes, INDEX.moon, palette.moon)
  writeColor(bytes, INDEX.moonShade, mix(palette.moon, palette.sky[1], .28))
  writeColor(bytes, INDEX.haloInner, mix(palette.sky[1], palette.moon, .42))
  writeColor(bytes, INDEX.haloOuter, mix(palette.sky[1], palette.moon, .18))
  writeColor(bytes, INDEX.far, palette.far[0]); writeColor(bytes, INDEX.farRim, palette.far[1])
  writeColor(bytes, INDEX.farShade, mix(palette.far[0], palette.sky[0], .45))
  writeColor(bytes, INDEX.near, palette.near[0]); writeColor(bytes, INDEX.nearRim, palette.near[1])
  writeColor(bytes, INDEX.trees, palette.trees)
}

/** Shooting stars on a seeded schedule: [x, y, heading, age 0..1] in sky
 *  texels, y counted down from the top of the sky. */
export function meteorsAt(seconds: number, rate: number, sky: [number, number], seed = 5): Vector4[] {
  const out = [new Vector4(0, 0, 0, 0), new Vector4(0, 0, 0, 0), new Vector4(0, 0, 0, 0)]
  if (rate <= 0) return out
  const mean = 7 / rate
  let at = fxRandom(seed, 0) * mean * .5, slot = 0
  for (let k = 0; at <= seconds && k < 4000; k++) {
    const age = (seconds - at) / METEOR_LIFE
    if (age >= 0 && age < 1 && slot < 3) {
      const left = fxRandom(seed, k * 5 + 1) > .5
      const fall = .25 + fxRandom(seed, k * 5 + 2) * .45
      const heading = left ? Math.PI - fall : fall
      const travel = age * METEOR_LIFE * (150 + fxRandom(seed, k * 5 + 3) * 90)
      const x0 = sky[0] * (.12 + fxRandom(seed, k * 5 + 4) * .76)
      const y0 = sky[1] * (.06 + fxRandom(seed, k * 5 + 5) * .34)
      out[slot++].set(x0 + Math.cos(heading) * travel, y0 + Math.sin(heading) * travel, heading, Math.max(.001, age))
    }
    at += mean * (.35 + fxRandom(seed, k + 9000) * 1.3)
  }
  return out
}

function hemisphere(scene: Scene) {
  return scene.children.find((child): child is HemisphereLight => child instanceof HemisphereLight)
}

/** Relight the world for `seconds`: palette, sky motion, water and lights. */
export function paintPixelWorld(dressing: Object3D | null, scene: Scene, dir: { color: Color; intensity: number }, authored: PixelWorld | undefined, seconds: number, frameHeight: number): PixelPalette | null {
  const runtime = dressing?.userData.pixelWorld as PixelRuntime | undefined
  if (!authored && !runtime) return null
  // A pixel set without authored lighting still needs a palette to show.
  const pixel = authored ?? defaultPixelWorld()
  const palette = paletteAt(pixel.palettes, pixel.hold, seconds)
  if (runtime) {
    writePalette(runtime.bytes, palette, seconds)
    runtime.palette.needsUpdate = true
    const meteors = meteorsAt(seconds, pixel.meteors, runtime.sky)
    for (const sky of runtime.skies) {
      sky.uniforms.uTime.value = seconds
      sky.uniforms.uAurora.value = palette.auroraAmount
      sky.uniforms.uAuroraColor.value.set(palette.aurora)
      sky.uniforms.uMeteorColor.value.set(palette.meteor)
      sky.uniforms.uMeteors.value = meteors
    }
    if (runtime.water) {
      runtime.water.uniforms.uTime.value = seconds
      runtime.water.uniforms.uWater.value.set(palette.water)
      runtime.water.uniforms.uCell.value = Math.max(1, pixel.pixelSize * frameHeight / 720)
    }
  }
  dir.color.set(palette.light.color)
  dir.intensity = palette.light.intensity
  const ambient = hemisphere(scene)
  if (ambient) {
    ambient.color.set(palette.ambient.sky)
    ambient.groundColor.set(palette.ambient.ground)
    ambient.intensity = palette.ambient.intensity
  }
  return palette
}
