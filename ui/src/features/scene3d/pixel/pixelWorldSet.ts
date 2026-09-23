import {
  AdditiveBlending, BoxGeometry, Color, DataTexture, DoubleSide, Group, HemisphereLight, Mesh, MeshStandardMaterial, NearestFilter, NoColorSpace,
  PlaneGeometry, RedFormat, RGBAFormat, SRGBColorSpace, ShaderMaterial, UnsignedByteType, Vector2, Vector4,
  type Object3D, type Scene, type Vector3,
} from 'three'
import { Reflector } from 'three/addons/objects/Reflector.js'
import { ENERGY_NOISE } from '../../sceneFx/energyShaders'
import { flashPalette, paletteAt, tintPalette, type PixelPalette } from './pixelPalettes'
import type { ScreenLight } from './screenGlow'
import { paintField, paintSails, paintSand } from './pixelPaintWorlds'
import type { IndexedLayer } from './pixelPaint'
import { meteorsAt, writePalette } from './pixelCycle'
import { defaultPixelWorld, type PixelWorld } from './pixelWorld'
import { bodyDirection, isPixelWorldKind, PIXEL_WORLD_KINDS, resolvePixelScene, type PixelScene, type PixelWorldKind } from './pixelScene'
import { worldPlan, type LayerSpec } from './pixelWorlds'

export type PixelDressing = PixelWorldKind | 'pixel-gallery'
export const PIXEL_DRESSINGS: readonly PixelDressing[] = [...PIXEL_WORLD_KINDS, 'pixel-gallery']
export function isPixelDressing(kind: unknown): kind is PixelDressing {
  return typeof kind === 'string' && (PIXEL_DRESSINGS as readonly string[]).includes(kind)
}

type PixelRuntime = {
  kind: PixelDressing; key: string; palette: DataTexture; bytes: Uint8Array
  skies: ShaderMaterial[]; water?: ShaderMaterial; beam?: Group; sky: [number, number]
  movers: { mesh: Mesh; speed: number; loop: number; offset?: number; bob?: number; y: number }[]
  spinners: { mesh: Mesh; speed: number }[]
  orbiters: { mesh: Mesh; orbit: NonNullable<LayerSpec['orbit']> }[]
}

const LAYER_VERTEX = `varying vec2 vUv; void main(){ vUv=uv; gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.); }`
const LAYER_FRAGMENT = `varying vec2 vUv;
  uniform sampler2D uIndex, uPalette; uniform vec2 uRes; uniform float uTime, uAurora, uSky, uHorizon, uAuroraBase;
  uniform vec3 uAuroraColor, uMeteorColor; uniform vec4 uMeteors[3];
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
  const painted = spec.paint(width, height)
  const material = new ShaderMaterial({
    name: 'pixel-world-layer',
    uniforms: {
      uIndex: { value: indexTexture(painted) }, uPalette: { value: palette },
      uRes: { value: new Vector2(width, height) }, uTime: { value: 0 }, uAurora: { value: 0 }, uSky: { value: spec.sky ? 1 : 0 },
      uHorizon: { value: height }, uAuroraBase: { value: .34 }, uAuroraColor: { value: new Color() }, uMeteorColor: { value: new Color() },
      uMeteors: { value: [new Vector4(0, 0, 0, 0), new Vector4(0, 0, 0, 0), new Vector4(0, 0, 0, 0)] },
    },
    vertexShader: LAYER_VERTEX, fragmentShader: LAYER_FRAGMENT, depthWrite: true,
  })
  const mesh = new Mesh(new PlaneGeometry(spec.width, spec.height), material)
  mesh.position.set(0, spec.bottom + spec.height / 2, spec.z)
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
    uniforms: { ...reflectorShader.uniforms, uTime: { value: 0 }, uWater: { value: new Color('#121433') }, uCell: { value: 3 }, uCalm: { value: 0 } },
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
      material.uniforms?.uIndex?.value?.dispose?.()
      material.dispose()
    })
    if (child instanceof Reflector) child.dispose()
  }
}

/** Paint the world's planes for this layout; runs again only when the
 *  layout (not the lighting) changes. */
function build(root: Object3D, runtime: PixelRuntime, scene: PixelScene) {
  clear(root)
  runtime.skies = []; runtime.water = undefined; runtime.beam = undefined; runtime.movers = []; runtime.spinners = []; runtime.orbiters = []
  if (runtime.kind === 'pixel-gallery') {
    gallery(root as Group)
    const floor = water(26, 14, 1.5)
    runtime.water = floor.material as ShaderMaterial
    root.add(floor)
    return
  }
  const plan = worldPlan(runtime.kind, scene)
  for (const spec of plan.layers) {
    const { mesh, lamp, hubs } = layerMesh(spec, runtime.palette)
    if (spec.sky) runtime.skies.push(mesh.material as ShaderMaterial)
    if (spec.drift) runtime.movers.push({ mesh, ...spec.drift, y: mesh.position.y })
    if (spec.spin) runtime.spinners.push({ mesh, speed: spec.spin })
    if (spec.orbit) runtime.orbiters.push({ mesh, orbit: spec.orbit })
    root.add(mesh)
    if (lamp) { runtime.beam = lighthouseBeam(lamp); root.add(runtime.beam) }
    if (hubs) sailsOn(spec, hubs, runtime.palette, runtime, root)
  }
  if (plan.ground === 'none') return
  if (plan.ground === 'field') { root.add(fieldFloor(runtime.palette)); return }
  if (plan.ground === 'sand') { root.add(sandFloor(runtime.palette, plan.groundY)); return }
  const lake = water(150, 54, -11)
  runtime.water = lake.material as ShaderMaterial
  root.add(lake)
}

/** An empty set; its planes are painted on the first frame, from the
 *  document's own layout. */
export function pixelWorldGroup(kind: PixelDressing): Object3D {
  const root = new Group()
  const runtime: PixelRuntime = { kind, key: '', ...newPalette(), skies: [], sky: [700, 214], movers: [], spinners: [], orbiters: [] }
  root.userData.pixelWorld = runtime
  return root
}

function hemisphere(scene: Scene) {
  return scene.children.find((child): child is HemisphereLight => child instanceof HemisphereLight)
}

function syncSet(dressing: Object3D, runtime: PixelRuntime, pixel: PixelWorld, palette: PixelPalette, seconds: number, frameHeight: number) {
  const scene = isPixelWorldKind(runtime.kind) ? resolvePixelScene(runtime.kind, pixel.scene) : resolvePixelScene('pixel-lake', undefined)
  const key = runtime.kind + JSON.stringify(scene)
  if (runtime.key !== key) { build(dressing, runtime, scene); runtime.key = key }
  writePalette(runtime.bytes, palette, seconds)
  runtime.palette.needsUpdate = true
  const meteors = meteorsAt(seconds, pixel.meteors, runtime.sky, 5, scene.meteorDirection)
  for (const sky of runtime.skies) {
    sky.uniforms.uTime.value = seconds
    // No aurora hangs in open space.
    sky.uniforms.uAurora.value = runtime.kind === 'pixel-orbit' ? 0 : palette.auroraAmount
    sky.uniforms.uAuroraBase.value = .54 - .4 * scene.auroraHeight
    sky.uniforms.uAuroraColor.value.set(palette.aurora)
    sky.uniforms.uMeteorColor.value.set(palette.meteor)
    sky.uniforms.uMeteors.value = meteors
  }
  if (runtime.water) {
    runtime.water.uniforms.uTime.value = seconds
    runtime.water.uniforms.uWater.value.set(palette.water)
    runtime.water.uniforms.uCell.value = Math.max(1, pixel.pixelSize * frameHeight / 720)
    runtime.water.uniforms.uCalm.value = runtime.kind === 'pixel-gallery' ? .85 : 1 - Math.min(1, scene.ripple * 1.25)
  }
  // Travelling planes follow the scene clock, so scrubbing and export agree.
  for (const mover of runtime.movers) {
    mover.mesh.position.x = -mover.loop / 2 + (((seconds * mover.speed + (mover.offset ?? 0)) % mover.loop) + mover.loop) % mover.loop
    if (mover.bob) mover.mesh.position.y = mover.y + Math.sin(seconds * .6 + (mover.offset ?? 0)) * mover.bob
  }
  for (const spinner of runtime.spinners) spinner.mesh.rotation.z = seconds * spinner.speed
  for (const { mesh, orbit } of runtime.orbiters) {
    const angle = orbit.phase + seconds * orbit.speed
    // Gondolas hang below their pivot on the rim and never tilt.
    mesh.position.x = orbit.x + Math.cos(angle) * orbit.radius
    mesh.position.y = orbit.y + Math.sin(angle) * orbit.radius - .7
  }
  if (runtime.beam) {
    runtime.beam.rotation.y = seconds * .9
    const material = (runtime.beam.children[0].children[0] as Mesh).material as ShaderMaterial
    material.uniforms.uColor.value.set(palette.windows)
  }
  return scene
}

/** Relight the world for `seconds`: palette, sky motion, water and lights.
 *  The key light comes from wherever the sun or moon hangs. */
export function paintPixelWorld(dressing: Object3D | null, scene: Scene, dir: { color: Color; intensity: number; position: Vector3 }, authored: PixelWorld | undefined, seconds: number, frameHeight: number, flash = 0, screens?: ScreenLight): PixelPalette | null {
  const runtime = dressing?.userData.pixelWorld as PixelRuntime | undefined
  if (!authored && !runtime) return null
  // A pixel set without authored lighting still needs a palette to show.
  const pixel = authored ?? defaultPixelWorld()
  const mood = paletteAt(pixel.palettes, pixel.hold, seconds, pixel.colors)
  const palette = flashPalette(screens ? tintPalette(mood, screens.color, screens.amount) : mood, flash)
  const layout = runtime && dressing ? syncSet(dressing, runtime, pixel, palette, seconds, frameHeight) : undefined
  dir.color.set(palette.light.color)
  dir.intensity = palette.light.intensity
  if (layout && layout.body !== 'none') dir.position.set(...bodyDirection(layout)).multiplyScalar(6)
  const ambient = hemisphere(scene)
  if (ambient) {
    ambient.color.set(palette.ambient.sky)
    ambient.groundColor.set(palette.ambient.ground)
    ambient.intensity = palette.ambient.intensity
  }
  return palette
}
