import {
  BackSide,
  BufferGeometry,
  Color,
  DoubleSide,
  Float32BufferAttribute,
  FogExp2,
  Group,
  InstancedMesh,
  Mesh,
  MeshStandardMaterial,
  Object3D,
  PlaneGeometry,
  Points,
  ShaderMaterial,
  SphereGeometry,
  type BufferAttribute,
} from 'three'
import type { AtmosHandle } from './clearing.ts'
import type { AtmosSetDefinition } from '../definition.ts'
import type { AtmosSettings, ResolvedAtmos } from '../params.ts'
import { hash2 } from '../noise.ts'
import { CLEARING_SUBJECT } from '../layout.ts'
import type { Kept } from '../forest.ts'
import { FALLS_X, SHEET_Z, WATER } from './waterfallLayout.ts'
import { addBankPlants, addGround, addPines, addPool, addRainbow, addRockWalls } from './waterfallScenery.ts'

type MistCard = { x: number; y: number; z: number; yaw: number; sx: number; sy: number }

const SHEET_VERTEX = `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`
const SHEET_FRAGMENT = `
  uniform float uTime;
  uniform float uFlow;
  uniform float uSplash;
  uniform float uTopFade;
  uniform vec3 uDeep;
  uniform vec3 uFoam;
  varying vec2 vUv;
  float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
  float noise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash(i), hash(i + vec2(1.0, 0.0)), f.x), mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), f.x), f.y);
  }
  void main() {
    float lane = floor(vUv.x * 22.0);
    float pace = 0.75 + 0.5 * hash(vec2(lane, 3.0));
    float streak = noise(vec2(vUv.x * 26.0, vUv.y * 2.2 + uTime * uFlow * pace * 1.6));
    float fine = noise(vec2(vUv.x * 70.0, vUv.y * 9.0 + uTime * uFlow * 2.6));
    float body = smoothstep(0.32, 0.82, streak * 0.7 + fine * 0.4);
    float lip = smoothstep(0.9, 1.0, vUv.y) * 0.7;
    float base = smoothstep(0.22, 0.0, vUv.y) * uSplash;
    float foam = clamp(body * 0.85 + lip + base, 0.0, 1.0);
    vec3 color = mix(uDeep, uFoam, foam);
    float ragged = 0.06 + 0.04 * hash(vec2(floor(vUv.y * 14.0), 1.0));
    float edge = smoothstep(0.0, ragged, vUv.x) * smoothstep(1.0, 1.0 - ragged, vUv.x);
    float top = mix(1.0, smoothstep(1.0, 0.78, vUv.y), uTopFade);
    gl_FragColor = vec4(color, (0.72 + 0.26 * foam) * edge * top);
  }
`
const SKY_VERTEX = `
  varying float vH;
  void main() {
    vH = normalize(position).y;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`
const SKY_FRAGMENT = `
  uniform vec3 uHorizon;
  uniform vec3 uZenith;
  varying float vH;
  void main() {
    gl_FragColor = vec4(mix(uHorizon, uZenith, smoothstep(-0.05, 0.6, vH)), 1.0);
  }
`


const FOAM: Record<string, string> = { moss: '#e7f6f1', amber: '#f8e7cf' }
const ZENITH: Record<string, string> = { moss: '#e7f3ee', amber: '#f6ead6' }
const FALLBACK_GROUND: Record<string, string> = { moss: '#4e6254', amber: '#7a6248' }

const WATERFALL_PALETTES = {
  moss: { fog: '#c9ddd0', ground: '#8a9a78', accent: '#3e8f86', sky: ['#c9ddd0', '#e7f2ea'] },
  amber: { fog: '#f0d8b4', ground: '#a89070', accent: '#c47848', sky: ['#f0d8b4', '#f6e4c4'] },
} as const

const WATERFALL_TIMES = {
  morning: { sun: [0.4, -0.82, 0.16], sunColor: '#fff4dc' },
  golden: { sun: [0.82, -0.55, 0.16], sunColor: '#ffd39a' },
} as const

const WIDE_EYE = [0.2, 1.42, 3.55] as const
const WIDE_LOOK = [0.45, 1.15, -2.4] as const
const LOW_EYE = [1.35, 0.46, 1.85] as const
const LOW_LOOK = [0.15, 1.7, -2.6] as const

function emptyKept(): Kept {
  return { geometries: [], materials: [], textures: [], lights: [] }
}

function hexColor(color: string): [number, number, number] {
  const n = Number.parseInt(color.slice(1), 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

function flowSpeed(variant: number | undefined): number {
  const value = typeof variant === 'number' && Number.isFinite(variant) ? variant : 60
  return 0.4 + value / 80
}

function foamOf(palette: string): string {
  return FOAM[palette] ?? FOAM.moss
}

function disposeOnce(run: () => void) {
  let done = false
  return () => {
    if (done) return
    done = true
    run()
  }
}

function disposeKept(root: Group, kept: Kept) {
  root.removeFromParent()
  for (const geometry of kept.geometries) geometry.dispose()
  for (const material of kept.materials) material.dispose()
  for (const texture of kept.textures) texture.dispose()
}

function idleHandle(root: Group, kept: Kept): AtmosHandle {
  return {
    ms: { shafts: 0, dof: 0, grade: 0 },
    passes: () => [],
    sync: () => {},
    dispose: disposeOnce(() => disposeKept(root, kept)),
  }
}

function flatWaterfall(resolved: ResolvedAtmos): { root: Group; kept: Kept } {
  const root = new Group()
  root.name = 'atmos-waterfall'
  const kept = emptyKept()
  const geo = new PlaneGeometry(16, 16)
  geo.rotateX(-Math.PI / 2)
  const mat = new MeshStandardMaterial({ color: resolved.stone, roughness: 1 })
  root.add(new Mesh(geo, mat))
  kept.geometries.push(geo)
  kept.materials.push(mat)
  return { root, kept }
}

function addMesh(root: Group, kept: Kept, mesh: Mesh | InstancedMesh | Points) {
  root.add(mesh)
  kept.geometries.push(mesh.geometry)
}

function sheetMaterial(resolved: ResolvedAtmos, splash: number): ShaderMaterial {
  return new ShaderMaterial({
    transparent: true,
    depthWrite: false,
    uniforms: {
      uTime: { value: 0 },
      uFlow: { value: flowSpeed(resolved.variant) },
      uSplash: { value: splash },
      uTopFade: { value: splash < 0.9 ? 1 : 0 },
      uDeep: { value: new Color(WATER[resolved.palette] ?? WATER.moss).multiplyScalar(0.8) },
      uFoam: { value: new Color(foamOf(resolved.palette)) },
    },
    vertexShader: SHEET_VERTEX,
    fragmentShader: SHEET_FRAGMENT,
  })
}

function addSheets(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const layers: Array<{ width: number; height: number; y: number; z: number; splash: number }> = [
    { width: 2.2, height: 5.1, y: 2.55, z: SHEET_Z, splash: 1 },
    { width: 1.5, height: 4.1, y: 2.1, z: SHEET_Z + 0.09, splash: 0.4 },
  ]
  for (const layer of layers) {
    const geo = new PlaneGeometry(layer.width, layer.height)
    const mat = sheetMaterial(resolved, layer.splash)
    const mesh = new Mesh(geo, mat)
    mesh.name = 'atmos-sheet'
    mesh.position.set(FALLS_X, layer.y, layer.z)
    addMesh(root, kept, mesh)
    kept.materials.push(mat)
  }
}

function addMist(root: Group, kept: Kept) {
  const geo = new PlaneGeometry(1, 1)
  const mat = new ShaderMaterial({
    transparent: true,
    depthWrite: false,
    side: DoubleSide,
    uniforms: { uColor: { value: new Color(0xd7efe8) } },
    vertexShader: 'varying vec2 vUv; void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * instanceMatrix * vec4(position, 1.0); }',
    fragmentShader: 'uniform vec3 uColor; varying vec2 vUv; void main() { float d = length(vUv - 0.5) * 2.0; gl_FragColor = vec4(uColor, 0.34 * smoothstep(1.0, 0.0, d) * smoothstep(1.0, 0.55, d)); }',
  })
  const cards: MistCard[] = [
    { x: FALLS_X, y: 0.32, z: -2.2, yaw: 0, sx: 3.4, sy: 0.6 },
    { x: FALLS_X, y: 0.7, z: -2.3, yaw: 0.04, sx: 2.6, sy: 0.5 },
    { x: FALLS_X, y: 1.15, z: -2.45, yaw: -0.03, sx: 2.0, sy: 0.45 },
  ]
  const mesh = new InstancedMesh(geo, mat, cards.length)
  mesh.name = 'atmos-mist'
  const dummy = new Object3D()
  for (let i = 0; i < cards.length; i += 1) {
    const card = cards[i]
    dummy.position.set(card.x, card.y, card.z)
    dummy.rotation.y = card.yaw
    dummy.scale.set(card.sx, card.sy, 1)
    dummy.updateMatrix()
    mesh.setMatrixAt(i, dummy.matrix)
  }
  mesh.userData.cards = cards
  mesh.instanceMatrix.needsUpdate = true
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function dewPosition(index: number, seed: number): [number, number, number] {
  return [
    (hash2(index, 11, seed) - 0.5) * 2.4,
    0.4 + hash2(index, 12, seed) * 2.3,
    -2.5 + hash2(index, 13, seed) * 0.5,
  ]
}

function addDew(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const geo = new BufferGeometry()
  const base = new Float32Array(resolved.moteCount * 3)
  for (let i = 0; i < resolved.moteCount; i += 1) {
    const [x, y, z] = dewPosition(i, resolved.seed)
    base[i * 3] = x
    base[i * 3 + 1] = y
    base[i * 3 + 2] = z
  }
  geo.setAttribute('position', new Float32BufferAttribute(base, 3))
  const mat = new ShaderMaterial({
    transparent: true,
    depthWrite: false,
    uniforms: { uSize: { value: 9 + resolved.motes * 8 }, uColor: { value: new Color(foamOf(resolved.palette)) } },
    vertexShader: `
      uniform float uSize;
      void main() {
        vec4 mv = modelViewMatrix * vec4(position, 1.0);
        gl_PointSize = uSize * (1.2 / max(0.3, -mv.z));
        gl_Position = projectionMatrix * mv;
      }
    `,
    fragmentShader: `
      uniform vec3 uColor;
      void main() {
        float d = length(gl_PointCoord - 0.5);
        if (d > 0.5) discard;
        gl_FragColor = vec4(uColor, 0.85);
      }
    `,
  })
  const points = new Points(geo, mat)
  points.name = 'atmos-dew'
  points.userData.base = base
  addMesh(root, kept, points)
  kept.materials.push(mat)
}

function addSky(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const geo = new SphereGeometry(22, 16, 10)
  const zenith = new Color(ZENITH[resolved.palette] ?? ZENITH.moss)
  if (resolved.timeOfDay === 'golden') zenith.lerp(new Color(resolved.sunColor), 0.5)
  const mat = new ShaderMaterial({
    side: BackSide,
    depthWrite: false,
    uniforms: {
      uHorizon: { value: new Color(resolved.fogColor) },
      uZenith: { value: zenith },
    },
    vertexShader: SKY_VERTEX,
    fragmentShader: SKY_FRAGMENT,
  })
  const mesh = new Mesh(geo, mat)
  mesh.name = 'atmos-sky'
  mesh.frustumCulled = false
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function paintWater(root: Group, seconds: number, flow: number) {
  root.traverse(child => {
    const material = (child as Mesh).material
    if (!(material instanceof ShaderMaterial) || !('uFlow' in material.uniforms)) return
    material.uniforms.uTime.value = seconds
    material.uniforms.uFlow.value = flow
  })
}

function riseMist(root: Group, seconds: number) {
  const mist = root.getObjectByName('atmos-mist') as InstancedMesh | undefined
  const cards = mist?.userData.cards as MistCard[] | undefined
  if (!mist || !cards) return
  const dummy = new Object3D()
  for (let i = 0; i < cards.length; i += 1) {
    const card = cards[i]
    dummy.position.set(card.x, card.y + ((seconds * 0.22 + i * 0.17) % 0.45), card.z)
    dummy.rotation.y = card.yaw
    dummy.scale.set(card.sx, card.sy, 1)
    dummy.updateMatrix()
    mist.setMatrixAt(i, dummy.matrix)
  }
  mist.instanceMatrix.needsUpdate = true
}

function driftDew(root: Group, seconds: number) {
  const points = root.getObjectByName('atmos-dew') as Points | undefined
  const attr = points?.geometry.getAttribute('position') as BufferAttribute | undefined
  const base = points?.userData.base as Float32Array | undefined
  if (!attr || !base) return
  for (let i = 0; i < attr.count; i += 1) {
    attr.setXYZ(i, base[i * 3], base[i * 3 + 1] + Math.sin(seconds * 0.8 + i) * 0.06, base[i * 3 + 2])
  }
  attr.needsUpdate = true
}

function showRainbow(root: Group, time: string) {
  const arc = root.getObjectByName('atmos-rainbow')
  if (arc) arc.visible = time === 'golden'
}

function tuneFog(root: Group, density: number) {
  const fog = (root.parent as { fog?: unknown } | null)?.fog
  if (fog instanceof FogExp2) fog.density = 0.014 + density * 0.034
}

function syncWater(root: Group, seconds: number, resolved: ResolvedAtmos, live?: AtmosSettings) {
  const look = live ?? resolved
  paintWater(root, seconds, flowSpeed(look.variant))
  riseMist(root, seconds)
  driftDew(root, seconds)
  showRainbow(root, look.timeOfDay)
  tuneFog(root, look.fogDensity)
}

function liveHandle(root: Group, kept: Kept, resolved: ResolvedAtmos): AtmosHandle {
  return {
    ms: { shafts: 0, dof: 0, grade: 0 },
    passes: () => [],
    sync: (seconds, _camera, _light, _quality, _focus, live) => syncWater(root, seconds, resolved, live),
    dispose: disposeOnce(() => disposeKept(root, kept)),
  }
}

export function buildWaterfall(resolved: ResolvedAtmos, webgl2: boolean): { root: Group; handle: AtmosHandle } {
  if (!webgl2) {
    const flat = flatWaterfall(resolved)
    const handle = idleHandle(flat.root, flat.kept)
    flat.root.userData.atmos = handle
    return { root: flat.root, handle }
  }
  const root = new Group()
  root.name = 'atmos-waterfall'
  const kept = emptyKept()
  addGround(root, resolved, kept)
  addRockWalls(root, resolved, kept)
  addPool(root, resolved, kept, flowSpeed(resolved.variant))
  addSheets(root, resolved, kept)
  addMist(root, kept)
  addDew(root, resolved, kept)
  addRainbow(root, resolved, kept)
  addPines(root, resolved, kept)
  addBankPlants(root, resolved, kept)
  addSky(root, resolved, kept)
  const handle = liveHandle(root, kept, resolved)
  root.userData.atmos = handle
  return { root, handle }
}

export const waterfallSet: AtmosSetDefinition = {
  id: 'atmos-waterfall',
  titleKey: 'template.atmos-waterfall-wide.title',
  setting: 'canyon',
  seed: 24011,
  subject: CLEARING_SUBJECT,
  subjectYaw: 0.15,
  palettes: WATERFALL_PALETTES,
  times: WATERFALL_TIMES,
  defaults: { timeOfDay: 'golden', fogDensity: 0.26, wind: 0.28, motes: 0.55, palette: 'moss', variant: 60 },
  variant: { labelKey: 'atmos.flow', min: 20, max: 100 },
  low: { shaftSteps: 0, grassBlades: 18, moteCount: 48 },
  high: { shaftSteps: 0, grassBlades: 36, moteCount: 96 },
  templates: [
    { id: 'atmos-waterfall-wide', camera: 'establishment', eye: WIDE_EYE, look: WIDE_LOOK, fov: 40, duration: 6 },
    { id: 'atmos-waterfall-low', camera: 'establishment', eye: LOW_EYE, look: LOW_LOOK, fov: 46, duration: 6 },
  ],
  build: buildWaterfall,
  fallback(resolved) {
    const sky = WATERFALL_PALETTES[resolved.palette as keyof typeof WATERFALL_PALETTES]?.fog ?? WATERFALL_PALETTES.moss.fog
    return { sky: hexColor(sky), ground: hexColor(FALLBACK_GROUND[resolved.palette] ?? FALLBACK_GROUND.moss) }
  },
}
