import {
  AdditiveBlending, BoxGeometry, BufferAttribute, BufferGeometry, Color, DataTexture, DoubleSide, Group, HemisphereLight, Mesh, MeshStandardMaterial, NearestFilter, NoColorSpace,
  PlaneGeometry, RedFormat, RGBAFormat, SRGBColorSpace, ShaderMaterial, UnsignedByteType, Vector2, Vector3, Vector4,
  type Object3D, type Scene,
} from 'three'
import { Reflector } from 'three/addons/objects/Reflector.js'
import { ENERGY_NOISE } from '../../sceneFx/energyShaders'
import { flashPalette, mixPalettes, paletteAt, PIXEL_PALETTES, tintPalette, type PixelPalette, type PixelPaletteId } from './pixelPalettes'
import type { ScreenLight } from './screenGlow'
import { paintField, paintSails, paintSand } from './pixelPaintWorlds'
import type { IndexedLayer } from './pixelPaint'
import { fireworksAt, GLASS, meteorsAt, mixHex, writePalette } from './pixelCycle'
import { defaultPixelWorld, type PixelWorld } from './pixelWorld'
import { bodyDirection, isPixelWorldKind, PIXEL_WORLD_KINDS, resolvePixelScene, type PixelScene, type PixelWorldKind } from './pixelScene'
import { eclipseShade, hazeAt, launchGlow, tideLevel, worldPlan, type Beam, type LayerSpec, type WorldPlan } from './pixelWorlds'

export type PixelDressing = PixelWorldKind | 'pixel-gallery'
export const PIXEL_DRESSINGS: readonly PixelDressing[] = [...PIXEL_WORLD_KINDS, 'pixel-gallery']
export function isPixelDressing(kind: unknown): kind is PixelDressing {
  return typeof kind === 'string' && (PIXEL_DRESSINGS as readonly string[]).includes(kind)
}

type PixelRuntime = {
  kind: PixelDressing; key: string; palette: DataTexture; bytes: Uint8Array
  skies: ShaderMaterial[]; water?: ShaderMaterial; beam?: Group; shafts: Mesh[]; sky: [number, number]
  movers: { mesh: Mesh; speed: number; loop: number; offset?: number; bob?: number; rise?: boolean; y: number; x: number }[]
  fireworks?: boolean
  clearSky?: boolean
  rain?: number
  pulse?: string
  tide?: WorldPlan['tide']
  haze?: WorldPlan['haze']
  lake?: Object3D
  spinners: { mesh: Mesh; speed: number }[]
  swingers: { mesh: Mesh; swing: NonNullable<LayerSpec['swing']> }[]
  scrollers: { material: ShaderMaterial; speed: number; axis: 'uScroll' | 'uScrollY' }[]
  orbiters: { mesh: Mesh; orbit: NonNullable<LayerSpec['orbit']>; id?: string }[]
  celestials: Mesh[]
  sprites: { material: ShaderMaterial; frames: DataTexture[]; fps: number }[]
  launchers: { mesh: Mesh; y: number; launch: NonNullable<LayerSpec['launch']> }[]
  dissolvers: { material: ShaderMaterial; dissolve: NonNullable<LayerSpec['dissolve']> }[]
  shimmers: ShaderMaterial[]
  growers: { material: ShaderMaterial; grow: NonNullable<LayerSpec['grow']> }[]
  hazers: { material: ShaderMaterial; depth: number }[]
  revealers: { material: ShaderMaterial; reveal: NonNullable<LayerSpec['reveal']> }[]
  carry?: WorldPlan['carry']
  carrier?: Mesh
  lit: ShaderMaterial[]
  /** Palettes for planes that keep their own mood whatever the world's program. */
  moods: Map<PixelPaletteId, ReturnType<typeof newPalette>>
}

const LAYER_VERTEX = `varying vec2 vUv; varying vec3 vWorld; void main(){ vUv=uv; vWorld=(modelMatrix*vec4(position,1.)).xyz; gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.); }`
const LAYER_FRAGMENT = `varying vec2 vUv; varying vec3 vWorld;
  uniform sampler2D uIndex, uPalette, uOrder; uniform float uReveal; uniform vec2 uRes; uniform float uTime, uAurora, uSky, uHorizon, uAuroraBase, uScroll, uScrollY, uDissolve, uShimmer, uGrow, uHaze, uSway, uCaustic; uniform vec3 uHazeColor, uCarryColor; uniform vec4 uCarry;
  uniform vec3 uAuroraColor, uMeteorColor; uniform vec4 uMeteors[3]; uniform vec4 uBursts[4]; uniform vec3 uBurstColors[4];
  ${ENERGY_NOISE}
  float bayer4(vec2 p){ vec2 q=mod(p,4.); float i=q.y*4.+q.x;
    return (i==0.?0.:i==1.?8.:i==2.?2.:i==3.?10.:i==4.?12.:i==5.?4.:i==6.?14.:i==7.?6.:i==8.?3.:i==9.?11.:i==10.?1.:i==11.?9.:i==12.?15.:i==13.?7.:i==14.?13.:5.)/16.; }
  vec3 aurora(vec2 cell){
    float x=cell.x, y=cell.y;
    float base=uHorizon*uAuroraBase+sin(x*.011+uTime*.22)*uHorizon*.05+(noise2(vec2(x*.018,uTime*.08))-.5)*uHorizon*.12;
    float v=(y-base)/(uHorizon*.3);
    if(v<-.2||v>1.) return vec3(0.);
    float curtain=exp(-max(0.,-v)*18.)*pow(1.-max(v,0.),2.2);
    float rays=.55+.45*sin(x*.33+noise2(vec2(x*.045,uTime*.35))*7.);
    float wave=.55+.45*sin(x*.045-uTime*1.1);
    float amount=uAurora*curtain*rays*wave;
    float level=floor(min(1.,amount*2.2)*4.+bayer4(cell))/4.;
    return uAuroraColor*level*.8;
  }
  // Fireworks: a rising spark, then a ring of embers that spreads, sags
  // under gravity and fades, stippled on the pixel grid.
  vec3 fireworks(vec2 cell){
    vec3 add=vec3(0.);
    for(int i=0;i<4;i++){
      vec4 b=uBursts[i]; if(b.z<=0.) continue;
      vec2 d=cell+.5-b.xy;
      if(b.z<.15){ float rise=b.z/.15; float y=mix(uRes.y,b.y,rise);
        if(abs(d.x)<1.&&abs(cell.y-y)<3.) add+=vec3(1.,.9,.7)*(1.-abs(cell.y-y)/3.); continue; }
      float age=(b.z-.15)/.85, radius=38.*(1.-pow(1.-age,2.2));
      d.y-=age*age*14.;
      float dist=length(d), angle=atan(d.y,d.x);
      float spoke=step(.6,fract(angle*28./6.2832+b.w*.37));
      float ring=1.-smoothstep(0.,2.2+age*2.,abs(dist-radius));
      float trail=(1.-smoothstep(0.,radius*.7,radius-dist))*step(dist,radius)*.35;
      float glow=(ring+trail)*spoke*(1.-age);
      if(bayer4(cell)>glow*1.3) continue;
      add+=mix(uBurstColors[i],vec3(1.),ring*(1.-age)*.4)*glow*1.5;
    }
    return add;
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
    vec2 cell=floor(vUv*uRes); cell.x=mod(cell.x+floor(uScroll),uRes.x); cell.y=mod(cell.y+floor(uScrollY),uRes.y);
    // Wind: gusts roll across in world space, bending the tops of the stalks
    // (the texture's upper rows) while their roots stay put.
    float gust=0.;
    if(uSway>0.){
      gust=pow(.5+.5*sin(vWorld.x*.3+vWorld.z*.25-uTime*2.1),3.)*.8+.2*(.5+.5*sin(vWorld.x*1.3-uTime*3.7));
      cell.x=mod(cell.x+floor(uSway*gust*cell.y/uRes.y+.5),uRes.x);
    }
    // Heat haze: rows slide sideways by a wavering amount.
    if(uShimmer>0.) cell.x=mod(cell.x+floor(sin(cell.y*.45+uTime*4.)*uShimmer*(1.-cell.y/uRes.y)+.5),uRes.x); vec2 uv=(cell+.5)/uRes;
    float index=floor(texture2D(uIndex,uv).r*255.+.5);
    if(index<.5) discard;
    // A reveal: each texel waits for its own moment (a trail being traced).
    if(uReveal<1.5&&(texture2D(uOrder,uv).r*255.-1.)/254.>uReveal) discard;
    // A dithered dissolve: pixels drop out in Bayer order as it rises.
    if(bayer4(cell)<uDissolve) discard;
    // Growing: only what lies below the rising line is built yet.
    if(cell.y/uRes.y>uGrow*1.03+(bayer4(cell)-.5)*.03) discard;
    vec3 color=texture2D(uPalette,vec2((index+.5)/256.,.5)).rgb;
    // Bent stalks show their paler undersides: a sheen runs with the gust.
    if(uSway>0.) color*=1.+.3*floor(gust*cell.y/uRes.y*3.+bayer4(cell))/3.;
    // Caustics: the sun through the rippling surface draws a moving net of
    // light on the pool floor, stepped like everything else.
    if(uCaustic>0.&&index>=43.&&index<=46.){
      vec2 p=vWorld.xz*1.6;
      p+=vec2(sin(p.y*.9+uTime*.9),cos(p.x*.8-uTime*.7))*.7;
      float net=1.-clamp(abs(sin(p.x*1.7+uTime*.4)+sin(p.y*1.9-uTime*.5))*1.8,0.,1.);
      color=mix(color,vec3(.9,1.,1.),floor(net*net*3.+bayer4(cell))/3.*.55*uCaustic);
    }
    // Haze: distance fades toward the storm's colour in dithered steps;
    // lit windows and lamps still burn through it.
    bool lit=(index>=64.&&index<=71.)||index==90.;
    if(uHaze>0.&&!lit) color=mix(color,uHazeColor,floor(uHaze*4.+bayer4(cell))/4.);
    // A carried lamp lights what is near it in dithered rings, whichever plane it is on.
    if(uCarry.w>0.){
      float near=clamp(1.-length((vWorld-uCarry.xyz)*vec3(1.,1.,.5))/uCarry.w,0.,1.);
      float glow=floor(near*near*5.+bayer4(cell))/5.;
      color=color*(1.+glow*.9)+uCarryColor*glow*.4;
    }
    if(uSky>.5) color+=aurora(vec2(cell.x,uRes.y-1.-cell.y))+meteors(vec2(cell.x,uRes.y-1.-cell.y))+fireworks(vec2(cell.x,uRes.y-1.-cell.y));
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
  const painted = spec.paint(width, height, 0)
  const material = new ShaderMaterial({
    name: 'pixel-world-layer',
    uniforms: {
      uIndex: { value: indexTexture(painted) }, uPalette: { value: palette }, uReveal: { value: 2 },
      uOrder: { value: painted.order ? indexTexture({ ...painted, data: painted.order }) : null },
      uRes: { value: new Vector2(width, height) }, uTime: { value: 0 }, uAurora: { value: 0 }, uSky: { value: spec.sky ? 1 : 0 },
      uHorizon: { value: height }, uAuroraBase: { value: .34 }, uScroll: { value: 0 }, uScrollY: { value: 0 }, uDissolve: { value: 0 }, uShimmer: { value: spec.shimmer ?? 0 }, uSway: { value: spec.sway ?? 0 }, uCaustic: { value: spec.caustics ? 1 : 0 }, uGrow: { value: 2 }, uHaze: { value: 0 }, uHazeColor: { value: new Color() }, uCarry: { value: new Vector4(0, 0, 0, 0) }, uCarryColor: { value: new Color() }, uAuroraColor: { value: new Color() }, uMeteorColor: { value: new Color() },
      uMeteors: { value: [new Vector4(0, 0, 0, 0), new Vector4(0, 0, 0, 0), new Vector4(0, 0, 0, 0)] },
      uBursts: { value: [0, 1, 2, 3].map(() => new Vector4(0, 0, 0, 0)) }, uBurstColors: { value: [0, 1, 2, 3].map(() => new Color()) },
    },
    vertexShader: LAYER_VERTEX, fragmentShader: LAYER_FRAGMENT, depthWrite: true,
  })
  const mesh = new Mesh(new PlaneGeometry(spec.width, spec.height), material)
  mesh.position.set(spec.x ?? 0, spec.bottom + spec.height / 2, spec.z)
  // Sprite animations keep every frame's texture and swap between them.
  if (spec.frames) mesh.userData.frames = [material.uniforms.uIndex.value, ...Array.from({ length: spec.frames.count - 1 }, (_, k) => indexTexture(spec.paint(width, height, k + 1)))]
  if (spec.turn) mesh.rotation.y = spec.turn
  if (spec.floor) { mesh.rotation.x = -Math.PI / 2; mesh.position.y = spec.bottom }
  const hubs = painted.hubs
  const lamp = painted.lamp && [
    (painted.lamp[0] / width - .5) * spec.width, spec.bottom + (1 - painted.lamp[1] / height) * spec.height, spec.z + .4,
  ] as [number, number, number]
  return { mesh, lamp, hubs }
}

/** Lake water: the real scene mirrored, broken into rippling pixel rows,
 *  tinted by the palette, with glints where something bright reflects. */
function water(width: number, depth: number, z: number) {
  const reflectorShader = (Reflector as unknown as { ReflectorShader: { uniforms: Record<string, { value: unknown }>; vertexShader: string } }).ReflectorShader
  const shader = {
    uniforms: { ...reflectorShader.uniforms, uTime: { value: 0 }, uWater: { value: new Color('#121433') }, uCell: { value: 3 }, uCalm: { value: 0 }, uRain: { value: 0 } },
    vertexShader: reflectorShader.vertexShader.replace('varying vec4 vUv;', 'varying vec4 vUv; varying vec3 vWorld;')
      .replace('vUv = textureMatrix', 'vWorld=(modelMatrix*vec4(position,1.)).xyz; vUv = textureMatrix'),
    fragmentShader: `uniform vec3 color; uniform sampler2D tDiffuse; uniform float uTime, uCell, uCalm, uRain; uniform vec3 uWater;
      varying vec4 vUv; varying vec3 vWorld; ${ENERGY_NOISE}
      // Raindrop rings: each cell of the lake gets a drop on its own clock
      // whose ring spreads and fades, drawn as a crisp pixel line.
      float ripples(vec2 p){
        float ring=0.;
        for(int k=0;k<2;k++){
          vec2 q=p*(1.6+float(k)*.9)+float(k)*7.3, cell=floor(q);
          float seed=hash(cell), age=fract(uTime*(.7+seed*.5)+seed*9.);
          vec2 centre=cell+.5+(vec2(hash(cell+3.1),hash(cell+7.7))-.5)*.6;
          float d=length((q-centre)*vec2(1.,2.2)), r=age*.48;
          ring+=(1.-age)*step(abs(d-r),.045+age*.02);
        }
        return min(ring,1.);
      }
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
        if(uRain>0.) c=mix(c,mix(uWater,vec3(1.),.45)+reflected*.25,ripples(vWorld.xz)*uRain*.6*smoothstep(-34.,-6.,vWorld.z));
        gl_FragColor=vec4(c,1.);
        #include <colorspace_fragment>
      }`,
  }
  const mirror = new Reflector(new PlaneGeometry(width, depth), { textureWidth: 640, textureHeight: 360, clipBias: .003, shader })
  mirror.rotation.x = -Math.PI / 2
  mirror.position.set(0, 0, z)
  return mirror
}

/** A flat sand floor painted in depth, for worlds without water. */
function sandFloor(palette: DataTexture, y = 0) {
  const { mesh } = layerMesh({ z: 0, width: 150, height: 54, bottom: 0, texture: [300, 180], paint: (w, h) => paintSand(w, h, 7) }, palette)
  mesh.rotation.x = -Math.PI / 2
  mesh.position.set(0, y, -11)
  return mesh
}

/** A flower field floor whose rows run away from the camera. */
function fieldFloor(palette: DataTexture) {
  const { mesh } = layerMesh({ z: 0, width: 150, height: 54, bottom: 0, texture: [750, 216], paint: (w, h) => paintField(w, h, 11) }, palette)
  mesh.rotation.x = -Math.PI / 2
  mesh.position.set(0, 0, -11)
  return mesh
}

/** Sails on each hub a painter reports; each mill turns at its own pace. */
function sailsOn(spec: LayerSpec, hubs: [number, number][], palette: DataTexture, runtime: PixelRuntime, root: Object3D) {
  const [width, height] = spec.texture
  hubs.forEach(([hx, hy], i) => {
    const size = spec.height * .5
    const { mesh } = layerMesh({ z: spec.z + .3, width: size, height: size, bottom: 0, texture: [48, 48], paint: w => paintSails(w) }, palette)
    mesh.position.set((hx / width - .5) * spec.width, spec.bottom + (1 - hy / height) * spec.height, spec.z + .3)
    runtime.spinners.push({ mesh, speed: -(.35 + i * .12) })
    root.add(mesh)
  })
}

/** A shaft of light: a quad widening from the window to the floor, glowing
 *  in its glass hue and fading toward the floor and its edges. */
function lightShaft(beam: Beam) {
  const [fx, fy, fz] = beam.from, [tx, ty, tz] = beam.to, half = beam.width / 2
  const geometry = new BufferGeometry()
  geometry.setAttribute('position', new BufferAttribute(new Float32Array([fx - half * .6, fy, fz, fx + half * .6, fy, fz, tx - half, ty, tz, tx + half, ty, tz]), 3))
  geometry.setAttribute('uv', new BufferAttribute(new Float32Array([0, 0, 1, 0, 0, 1, 1, 1]), 2))
  geometry.setIndex([0, 2, 1, 1, 2, 3])
  const material = new ShaderMaterial({
    name: 'pixel-world-shaft',
    uniforms: { uColor: { value: new Color(GLASS[beam.hue]) }, uPower: { value: 1 } },
    vertexShader: 'varying vec2 vUv; void main(){ vUv=uv; gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.); }',
    fragmentShader: `uniform vec3 uColor; uniform float uPower; varying vec2 vUv;
      void main(){ float edge=1.-pow(abs(vUv.x-.5)*2.,2.); float a=edge*(.55-vUv.y*.3)*uPower; gl_FragColor=vec4(uColor*a,a); }`,
    transparent: true, depthWrite: false, blending: AdditiveBlending, side: DoubleSide,
  })
  const mesh = new Mesh(geometry, material)
  mesh.userData.hue = beam.hue
  return mesh
}

/** The lighthouse beam: two crossed light blades that sweep round the lamp. */
function lighthouseBeam(at: [number, number, number]) {
  const root = new Group()
  const material = new ShaderMaterial({
    name: 'pixel-world-beam',
    uniforms: { uColor: { value: new Color('#ffe7a8') } },
    vertexShader: 'varying vec2 vUv; void main(){ vUv=uv; gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.); }',
    fragmentShader: `uniform vec3 uColor; varying vec2 vUv;
      void main(){ float along=vUv.x, across=abs(vUv.y-.5)*2.;
        float spread=mix(.08,1.,along); float a=(1.-smoothstep(spread*.6,spread,across))*pow(1.-along,1.4)*.55;
        gl_FragColor=vec4(uColor*a,a); }`,
    transparent: true, depthWrite: false, blending: AdditiveBlending, side: DoubleSide,
  })
  for (const tilt of [0, Math.PI / 2]) {
    const blade = new Mesh(new PlaneGeometry(40, 5), material)
    blade.position.x = 20
    const holder = new Group(); holder.rotation.x = tilt; holder.add(blade)
    root.add(holder)
  }
  root.position.set(...at)
  return root
}

function gallery(root: Group) {
  const wall = new MeshStandardMaterial({ color: 0x0c0c10, roughness: .9 })
  for (const [w, h, d, x, y, z] of [[26, 9, .3, 0, 4.5, -4.2], [.3, 9, 14, -10, 4.5, 1.5], [.3, 9, 14, 10, 4.5, 1.5], [26, .3, 14, 0, 9, 1.5]]) {
    const mesh = new Mesh(new BoxGeometry(w, h, d), wall)
    mesh.position.set(x, y, z)
    root.add(mesh)
  }
}

/** The palette texture for planes held in one mood, made once and reused. */
function moodPalette(runtime: PixelRuntime, mood: PixelPaletteId) {
  if (!runtime.moods.has(mood)) runtime.moods.set(mood, newPalette())
  return runtime.moods.get(mood)!.palette
}

function newPalette() {
  const bytes = new Uint8Array(256 * 4)
  const palette = new DataTexture(bytes, 256, 1, RGBAFormat, UnsignedByteType)
  palette.colorSpace = SRGBColorSpace
  palette.magFilter = palette.minFilter = NearestFilter
  palette.generateMipmaps = false
  return { bytes, palette }
}

function clear(root: Object3D) {
  for (const child of [...root.children]) {
    root.remove(child)
    child.traverse(node => {
      if (!(node instanceof Mesh)) return
      node.geometry.dispose()
      const material = node.material as ShaderMaterial
      for (const frame of (node.userData.frames ?? []) as DataTexture[]) frame.dispose()
      material.uniforms?.uIndex?.value?.dispose?.()
      material.uniforms?.uOrder?.value?.dispose?.()
      material.dispose()
    })
    if (child instanceof Reflector) child.dispose()
  }
}

/** Paint the world's planes for this layout; runs again only when the
 *  layout (not the lighting) changes. */
/** Keep hold of whatever about this plane moves with the clock. */
function track(runtime: PixelRuntime, spec: LayerSpec, mesh: Mesh) {
  const material = mesh.material as ShaderMaterial
  if (spec.sky) runtime.skies.push(material)
  if (spec.drift) runtime.movers.push({ mesh, ...spec.drift, y: mesh.position.y, x: mesh.position.x })
  if (spec.spin) runtime.spinners.push({ mesh, speed: spec.spin })
  if (spec.swing) runtime.swingers.push({ mesh, swing: spec.swing })
  if (spec.scroll) runtime.scrollers.push({ material, speed: spec.scroll, axis: 'uScroll' })
  if (spec.scrollY) runtime.scrollers.push({ material, speed: spec.scrollY, axis: 'uScrollY' })
  if (spec.orbit) runtime.orbiters.push({ mesh, orbit: spec.orbit, id: spec.id })
  if (spec.celestial) runtime.celestials.push(mesh)
  if (spec.shimmer || spec.sway || spec.caustics) runtime.shimmers.push(material)
  if (spec.grow) runtime.growers.push({ material, grow: spec.grow })
  if (spec.reveal) runtime.revealers.push({ material, reveal: spec.reveal })
  // The farther the plane, the sooner the haze swallows it.
  if (runtime.haze) runtime.hazers.push({ material, depth: Math.max(0, Math.min(1, -spec.z / 55)) })
  // Whoever carries the lamp stays a silhouette against its light.
  if (runtime.carry && spec.id === runtime.carry.id) runtime.carrier = mesh
  else if (runtime.carry) runtime.lit.push(material)
  if (spec.dissolve) runtime.dissolvers.push({ material, dissolve: spec.dissolve })
  if (spec.launch) runtime.launchers.push({ mesh, y: mesh.position.y, launch: spec.launch })
  if (spec.frames) runtime.sprites.push({ material, frames: mesh.userData.frames, fps: spec.frames.fps })
}

function build(root: Object3D, runtime: PixelRuntime, scene: PixelScene) {
  clear(root)
  runtime.skies = []; runtime.water = undefined; runtime.beam = undefined; runtime.shafts = []; runtime.movers = []; runtime.spinners = []; runtime.swingers = []; runtime.orbiters = []; runtime.scrollers = []; runtime.celestials = []; runtime.sprites = []; runtime.launchers = []; runtime.dissolvers = []; runtime.shimmers = []; runtime.growers = []; runtime.hazers = []; runtime.revealers = []; runtime.lit = []; runtime.carrier = undefined
  if (runtime.kind === 'pixel-gallery') {
    gallery(root as Group)
    const floor = water(26, 14, 1.5)
    runtime.water = floor.material as ShaderMaterial
    root.add(floor)
    return
  }
  const plan = worldPlan(runtime.kind, scene)
  runtime.fireworks = plan.fireworks
  runtime.clearSky = plan.clearSky
  runtime.rain = plan.rain
  runtime.pulse = plan.pulse
  runtime.tide = plan.tide
  runtime.haze = plan.haze
  runtime.carry = plan.carry
  runtime.lake = undefined
  for (const beam of plan.beams ?? []) { const shaft = lightShaft(beam); runtime.shafts.push(shaft); root.add(shaft) }
  for (const spec of plan.layers) {
    const { mesh, lamp, hubs } = layerMesh(spec, spec.mood ? moodPalette(runtime, spec.mood) : runtime.palette)
    track(runtime, spec, mesh)
    root.add(mesh)
    if (lamp) { runtime.beam = lighthouseBeam(lamp); root.add(runtime.beam) }
    if (hubs) sailsOn(spec, hubs, runtime.palette, runtime, root)
  }
  if (plan.ground === 'none') return
  if (plan.ground === 'field') { root.add(fieldFloor(runtime.palette)); return }
  if (plan.ground === 'sand') { root.add(sandFloor(runtime.palette, plan.groundY)); return }
  const lake = water(150, 54, -11)
  runtime.water = lake.material as ShaderMaterial
  runtime.lake = lake
  root.add(lake)
}

/** An empty set; its planes are painted on the first frame, from the
 *  document's own layout. */
export function pixelWorldGroup(kind: PixelDressing): Object3D {
  const root = new Group()
  const runtime: PixelRuntime = { kind, key: '', ...newPalette(), skies: [], sky: [700, 214], shafts: [], movers: [], spinners: [], swingers: [], orbiters: [], scrollers: [], celestials: [], sprites: [], launchers: [], dissolvers: [], shimmers: [], growers: [], hazers: [], revealers: [], lit: [], moods: new Map() }
  root.userData.pixelWorld = runtime
  return root
}

function hemisphere(scene: Scene) {
  return scene.children.find((child): child is HemisphereLight => child instanceof HemisphereLight)
}

type Mover = PixelRuntime['movers'][number]

function placeMover(mover: Mover, seconds: number) {
  const along = -mover.loop / 2 + (((seconds * mover.speed + (mover.offset ?? 0)) % mover.loop) + mover.loop) % mover.loop
  const sway = mover.bob ? Math.sin(seconds * .6 + (mover.offset ?? 0)) * mover.bob : 0
  // Rising keeps its place across and sways about it.
  if (mover.rise) { mover.mesh.position.y = mover.y + along + mover.loop / 2; mover.mesh.position.x = mover.x + sway; return }
  mover.mesh.position.x = along
  if (mover.bob) mover.mesh.position.y = mover.y + sway
}

function placeOrbiter(mesh: Mesh, orbit: NonNullable<LayerSpec['orbit']>, seconds: number, centre?: Mesh) {
  const angle = orbit.phase + seconds * orbit.speed, ry = orbit.ry ?? orbit.radius
  // Around a moving body, the centre travels with it.
  const cx = centre ? centre.position.x : orbit.x, cz = centre ? centre.position.z : orbit.y
  mesh.position.x = cx + Math.cos(angle) * orbit.radius
  if (orbit.flat) {
    // Swimming on the ground plane: turn to face the way it goes.
    const way = Math.sign(orbit.speed)
    mesh.position.z = cz + Math.sin(angle) * ry
    if (orbit.upright) return
    mesh.rotation.z = Math.atan2(-Math.cos(angle) * ry * way, -Math.sin(angle) * orbit.radius * way)
    return
  }
  // Gondolas hang below their pivot on the rim and never tilt.
  mesh.position.y = orbit.y + Math.sin(angle) * ry - (orbit.drop ?? 0)
}

/** Planes that shimmer, fade into haze, grow or dither in and out over the scene. */
function fadeParts(runtime: PixelRuntime, seconds: number, palette: PixelPalette) {
  for (const material of runtime.shimmers) material.uniforms.uTime.value = seconds
  if (runtime.haze) for (const { material, depth } of runtime.hazers) material.uniforms.uHaze.value = Math.min(1, hazeAt(runtime.haze, seconds) * (.25 + depth * 1.1))
  for (const { material, reveal } of runtime.revealers) material.uniforms.uReveal.value = Math.max(0, Math.min(1, (seconds - reveal.from) / (reveal.to - reveal.from)))
  for (const { material, grow } of runtime.growers) material.uniforms.uGrow.value = Math.max(0, Math.min(1, (seconds - grow.from) / (grow.to - grow.from)))
  for (const { material, dissolve } of runtime.dissolvers) {
    const t = Math.max(0, Math.min(1, (seconds - dissolve.from) / (dissolve.to - dissolve.from)))
    // Just past 0 and 1 at the ends, so no Bayer step is left half-drawn.
    material.uniforms.uDissolve.value = dissolve.appear ? 1.001 - t * 1.002 : t * 1.001
  }
  for (const { material } of runtime.hazers) material.uniforms.uHazeColor.value.set(mixHex(palette.sky[2], '#e8eef6', .6))
}

/** Light from a lamp that walks with one of the planes, flickering a little. */
function carryLight(runtime: PixelRuntime, seconds: number) {
  const { carry, carrier } = runtime
  if (!carry || !carrier) return
  const lamp = carrier.getWorldPosition(new Vector3()).add(new Vector3(carry.dx, carry.dy, .1))
  const radius = carry.radius * (1 + .04 * Math.sin(seconds * 11) + .03 * Math.sin(seconds * 23.7))
  for (const material of runtime.lit) {
    material.uniforms.uCarry.value.set(lamp.x, lamp.y, lamp.z, radius)
    material.uniforms.uCarryColor.value.set(carry.color)
  }
}

/** Everything that travels, spins or orbits, on the scene clock. */
function moveParts(runtime: PixelRuntime, seconds: number) {
  // Travelling planes follow the scene clock, so scrubbing and export agree.
  for (const mover of runtime.movers) placeMover(mover, seconds)
  for (const { mesh, y, launch } of runtime.launchers) {
    // One liftoff, gathering speed; the flame lights just before it.
    const since = Math.max(0, seconds - launch.at)
    mesh.position.y = y + Math.min(400, .5 * launch.accel * since * since)
    if (launch.ignite) mesh.visible = seconds >= launch.at - 1.2
  }
  // The tide lifts the whole lake, covering whatever lies low.
  if (runtime.lake && runtime.tide) runtime.lake.position.y = tideLevel(runtime.tide, seconds)
  for (const spinner of runtime.spinners) spinner.mesh.rotation.z = seconds * spinner.speed
  for (const { mesh, swing } of runtime.swingers) mesh.rotation.z = swing.amp * Math.sin(seconds / swing.period * Math.PI * 2)
  // Shafts brighten with their glass as the sun moves round.
  for (const shaft of runtime.shafts) (shaft.material as ShaderMaterial).uniforms.uPower.value = .5 + .5 * Math.sin(seconds * .5 - shaft.userData.hue * 1.05)
  for (const sprite of runtime.sprites) sprite.material.uniforms.uIndex.value = sprite.frames[Math.floor(seconds * sprite.fps) % sprite.frames.length]
  for (const scroller of runtime.scrollers) scroller.material.uniforms[scroller.axis].value = seconds * scroller.speed
  const named = new Map(runtime.orbiters.map(item => [item.id, item.mesh]))
  for (const { mesh, orbit } of runtime.orbiters) placeOrbiter(mesh, orbit, seconds, orbit.around ? named.get(orbit.around) : undefined)
}

/** Paint the world's planes for its current layout, if that changed. */
function ensureBuilt(dressing: Object3D, runtime: PixelRuntime, pixel: PixelWorld) {
  const scene = isPixelWorldKind(runtime.kind) ? resolvePixelScene(runtime.kind, pixel.scene) : resolvePixelScene('pixel-lake', undefined)
  const key = runtime.kind + JSON.stringify(scene)
  if (runtime.key !== key) { build(dressing, runtime, scene); runtime.key = key }
  return scene
}

function syncSet(runtime: PixelRuntime, scene: PixelScene, pixel: PixelWorld, palette: PixelPalette, seconds: number, frameHeight: number) {
  writePalette(runtime.bytes, palette, seconds)
  for (const [mood, held] of runtime.moods) { writePalette(held.bytes, PIXEL_PALETTES[mood], seconds); held.palette.needsUpdate = true }
  fadeParts(runtime, seconds, palette)
  runtime.palette.needsUpdate = true
  const meteors = meteorsAt(seconds, pixel.meteors, runtime.sky, 5, scene.meteorDirection)
  const bursts = fireworksAt(runtime.fireworks ? seconds : -1, runtime.sky, scene.seed)
  for (const sky of runtime.skies) {
    sky.uniforms.uTime.value = seconds
    // No aurora hangs in open space.
    sky.uniforms.uAurora.value = runtime.clearSky || runtime.fireworks ? 0 : palette.auroraAmount
    sky.uniforms.uAuroraBase.value = .54 - .4 * scene.auroraHeight
    sky.uniforms.uAuroraColor.value.set(palette.aurora)
    sky.uniforms.uMeteorColor.value.set(palette.meteor)
    sky.uniforms.uMeteors.value = meteors
    sky.uniforms.uBursts.value = bursts.map(burst => burst.at)
    bursts.forEach((burst, i) => sky.uniforms.uBurstColors.value[i].set(burst.color))
  }
  if (runtime.water) {
    runtime.water.uniforms.uTime.value = seconds
    runtime.water.uniforms.uWater.value.set(palette.water)
    runtime.water.uniforms.uCell.value = Math.max(1, pixel.pixelSize * frameHeight / 720)
    runtime.water.uniforms.uRain.value = runtime.rain ?? 0
    runtime.water.uniforms.uCalm.value = runtime.kind === 'pixel-gallery' ? .85 : 1 - Math.min(1, scene.ripple * 1.25)
  }
  moveParts(runtime, seconds)
  carryLight(runtime, seconds)
  if (runtime.beam) {
    runtime.beam.rotation.y = seconds * .9
    const material = (runtime.beam.children[0].children[0] as Mesh).material as ShaderMaterial
    material.uniforms.uColor.value.set(palette.windows)
  }
  return scene
}

/** World-wide light events on the mood: an eclipse darkens the day, a
 *  launch washes the coast in engine light, a grotto breathes its glow. */
function worldLight(runtime: PixelRuntime | undefined, mood: PixelPalette, seconds: number) {
  if (!runtime) return mood
  if (runtime.kind === 'pixel-eclipse') return mixPalettes(mood, PIXEL_PALETTES.midnight, eclipseShade(seconds))
  if (runtime.kind === 'pixel-launch') return tintPalette(mood, '#ffb070', launchGlow(seconds) * 2.2)
  if (runtime.pulse) return tintPalette(mood, runtime.pulse, .35 + .35 * Math.sin(seconds * .8))
  return mood
}

/** Relight the world for `seconds`: palette, sky motion, water and lights.
 *  The key light comes from wherever the sun or moon hangs. */
export function paintPixelWorld(dressing: Object3D | null, scene: Scene, dir: { color: Color; intensity: number; position: Vector3 }, authored: PixelWorld | undefined, seconds: number, frameHeight: number, flash = 0, screens?: ScreenLight): PixelPalette | null {
  const runtime = dressing?.userData.pixelWorld as PixelRuntime | undefined
  if (!authored && !runtime) return null
  // A pixel set without authored lighting still needs a palette to show.
  const pixel = authored ?? defaultPixelWorld()
  // Build first, so the world's own light events count from the first frame.
  const built = runtime && dressing ? ensureBuilt(dressing, runtime, pixel) : undefined
  const mood = worldLight(runtime, paletteAt(pixel.palettes, pixel.hold, seconds, pixel.colors), seconds)
  const palette = flashPalette(screens ? tintPalette(mood, screens.color, screens.amount) : mood, flash)
  const layout = runtime && built ? syncSet(runtime, built, pixel, palette, seconds, frameHeight) : undefined
  dir.color.set(palette.light.color)
  dir.intensity = palette.light.intensity
  const highest = runtime?.celestials.reduce<Mesh | undefined>((best, mesh) => !best || mesh.position.y > best.position.y ? mesh : best, undefined)
  if (highest) dir.position.set(highest.position.x, Math.max(1, highest.position.y), 40).normalize().multiplyScalar(6)
  else if (layout && layout.body !== 'none') dir.position.set(...bodyDirection(layout)).multiplyScalar(6)
  const ambient = hemisphere(scene)
  if (ambient) {
    ambient.color.set(palette.ambient.sky)
    ambient.groundColor.set(palette.ambient.ground)
    ambient.intensity = palette.ambient.intensity
  }
  return palette
}
