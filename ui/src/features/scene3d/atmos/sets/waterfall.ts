import {
  BackSide,
  BoxGeometry,
  BufferGeometry,
  Color,
  ConeGeometry,
  CylinderGeometry,
  DoubleSide,
  Float32BufferAttribute,
  FogExp2,
  Group,
  InstancedMesh,
  Mesh,
  MeshBasicMaterial,
  MeshStandardMaterial,
  Object3D,
  PlaneGeometry,
  Points,
  ShaderMaterial,
  RingGeometry,
  SphereGeometry,
  type BufferAttribute,
  type Material,
} from 'three'
import type { AtmosHandle } from './clearing.ts'
import type { AtmosSetDefinition } from '../definition.ts'
import type { AtmosSettings, ResolvedAtmos } from '../params.ts'
import { hash2 } from '../noise.ts'
import { CLEARING_SUBJECT, scatter, type Area } from '../layout.ts'

type Kept = { geometries: BufferGeometry[]; materials: Material[] }
type MistCard = { x: number; y: number; z: number; yaw: number; sx: number; sy: number }

const WATER_VERTEX = `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`
const WATER_FRAGMENT = `
  uniform float uTime;
  uniform float uFlow;
  uniform float uSplash;
  uniform vec3 uDeep;
  uniform vec3 uFoam;
  varying vec2 vUv;
  void main() {
    float lane = abs(fract(vUv.x * 9.0) - 0.5);
    float thread = smoothstep(0.48, 0.16, lane);
    float rush = 0.62 + 0.38 * sin(vUv.y * 34.0 - uTime * uFlow * 4.0 + vUv.x * 11.0);
    float splash = smoothstep(0.2, 0.0, vUv.y) * uSplash;
    vec3 color = mix(uDeep, uFoam, thread * rush * 0.72 + splash);
    float side = smoothstep(0.0, 0.05, vUv.x) * smoothstep(1.0, 0.95, vUv.x);
    gl_FragColor = vec4(color, mix(0.55, 0.94, max(thread, splash)) * side);
  }
`
const RAINBOW_VERTEX = `
  varying float vT;
  void main() {
    vT = uv.x;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`
const RAINBOW_FRAGMENT = `
  varying float vT;
  void main() {
    vec3 color = 0.55 + 0.45 * cos(6.28318 * (vec3(vT) + vec3(0.0, 0.33, 0.67)));
    gl_FragColor = vec4(color, 0.62);
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

const LEFT_BANK: Area = { x0: -6.2, x1: -1.25, z0: -2.15, z1: 2.4 }
const RIGHT_BANK: Area = { x0: 1.85, x1: 6.2, z0: -2.15, z1: 2.4 }
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
  return { geometries: [], materials: [] }
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

function addGround(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const geo = new PlaneGeometry(26, 26, 10, 10)
  geo.rotateX(-Math.PI / 2)
  const pos = geo.attributes.position as BufferAttribute
  for (let i = 0; i < pos.count; i += 1) {
    const z = pos.getZ(i)
    pos.setY(i, z < -1.5 ? (-1.5 - z) * 0.08 : 0)
  }
  geo.computeVertexNormals()
  const mat = new MeshStandardMaterial({
    color: resolved.stone, roughness: 0.94, flatShading: true,
    emissive: resolved.stone, emissiveIntensity: 0.14,
  })
  const mesh = new Mesh(geo, mat)
  mesh.name = 'atmos-ground'
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function cliffPose(index: number, seed: number) {
  const side = index < 8 ? -1 : 1
  const n = index % 8
  const col = n % 4
  const row = Math.floor(n / 4)
  const height = 1.6 + row * 1.7 + hash2(index, 5, seed) * 0.55
  return {
    x: side * (1.95 + col * 1.12) + (hash2(index, 9, seed) - 0.5) * 0.22,
    y: height / 2,
    z: -3.05 - row * 1.4 + (hash2(index, 10, seed) - 0.5) * 0.18,
    sy: height,
    yaw: (hash2(index, 6, seed) - 0.5) * 0.22,
  }
}

function addCliffs(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const geo = new BoxGeometry(1, 1, 1)
  const mat = new MeshStandardMaterial({
    color: 0xffffff, roughness: 0.96, flatShading: true,
    emissive: resolved.stone, emissiveIntensity: 0.06,
  })
  const mesh = new InstancedMesh(geo, mat, 16)
  mesh.name = 'atmos-cliff'
  const dummy = new Object3D()
  for (let i = 0; i < 16; i += 1) {
    const pose = cliffPose(i, resolved.seed)
    dummy.position.set(pose.x, pose.y, pose.z)
    dummy.scale.set(1.05, pose.sy, 1.2)
    dummy.rotation.y = pose.yaw
    dummy.updateMatrix()
    mesh.setMatrixAt(i, dummy.matrix)
    mesh.setColorAt(i, new Color(resolved.stone).multiplyScalar(0.46 + hash2(i, 8, resolved.seed) * 0.28))
  }
  mesh.instanceMatrix.needsUpdate = true
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function waterMaterial(resolved: ResolvedAtmos, splash: number): ShaderMaterial {
  return new ShaderMaterial({
    transparent: true,
    depthWrite: false,
    uniforms: {
      uTime: { value: 0 },
      uFlow: { value: flowSpeed(resolved.variant) },
      uSplash: { value: splash },
      uDeep: { value: new Color(resolved.grass).multiplyScalar(0.55) },
      uFoam: { value: new Color(foamOf(resolved.palette)) },
    },
    vertexShader: WATER_VERTEX,
    fragmentShader: WATER_FRAGMENT,
  })
}

function addSheet(root: Group, material: ShaderMaterial, kept: Kept) {
  const geo = new PlaneGeometry(2.2, 5.1)
  const mesh = new Mesh(geo, material)
  mesh.name = 'atmos-sheet'
  mesh.position.set(0.12, 2.55, -2.55)
  addMesh(root, kept, mesh)
  kept.materials.push(material)
}

function addRiver(root: Group, material: ShaderMaterial, kept: Kept) {
  const geo = new PlaneGeometry(3.1, 1.5)
  geo.rotateX(-Math.PI / 2)
  const mesh = new Mesh(geo, material)
  mesh.name = 'atmos-river'
  mesh.position.set(0.12, 0.05, -2.85)
  addMesh(root, kept, mesh)
  kept.materials.push(material)
}

function addMist(root: Group, kept: Kept) {
  const geo = new PlaneGeometry(1, 1)
  const mat = new MeshBasicMaterial({
    color: 0xd7efe8, transparent: true, opacity: 0.16, depthWrite: false, side: DoubleSide,
  })
  const cards: MistCard[] = [
    { x: 0.12, y: 0.32, z: -2.15, yaw: 0, sx: 3.1, sy: 0.55 },
    { x: 0.12, y: 0.62, z: -2.22, yaw: 0.04, sx: 2.2, sy: 0.38 },
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
    (hash2(index, 11, seed) - 0.5) * 2.0,
    0.4 + hash2(index, 12, seed) * 2.3,
    -2.6 + hash2(index, 13, seed) * 0.4,
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

function addRainbow(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const geo = new RingGeometry(1.2, 1.48, 40, 1, 0, Math.PI)
  const mat = new ShaderMaterial({
    transparent: true,
    depthWrite: false,
    side: DoubleSide,
    vertexShader: RAINBOW_VERTEX,
    fragmentShader: RAINBOW_FRAGMENT,
  })
  const mesh = new Mesh(geo, mat)
  mesh.name = 'atmos-rainbow'
  mesh.position.set(0.05, 2.15, -2.2)
  mesh.visible = resolved.timeOfDay === 'golden'
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function seatInstances(mesh: InstancedMesh, spots: Array<[number, number]>, seed: number, salt: number, y: number) {
  const dummy = new Object3D()
  for (let i = 0; i < spots.length; i += 1) {
    const [x, z] = spots[i]
    dummy.position.set(x, y, z)
    dummy.rotation.y = hash2(i, salt, seed) * Math.PI
    const scale = 0.75 + hash2(i, salt + 2, seed) * 0.7
    dummy.scale.setScalar(scale)
    dummy.updateMatrix()
    mesh.setMatrixAt(i, dummy.matrix)
  }
  mesh.instanceMatrix.needsUpdate = true
}

function bankSpots(count: number, seed: number, salt: number): Array<[number, number]> {
  const half = Math.ceil(count / 2)
  return [
    ...scatter(half, seed, salt, [], LEFT_BANK, 0.4),
    ...scatter(count - half, seed, salt + 5, [], RIGHT_BANK, 0.4),
  ]
}

function addFerns(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const spots = bankSpots(resolved.grassBlades, resolved.seed, 41)
  if (!spots.length) return
  const geo = new ConeGeometry(0.16, 0.55, 5)
  geo.translate(0, 0.28, 0)
  const mat = new MeshStandardMaterial({
    color: new Color(resolved.grass).multiplyScalar(0.72),
    roughness: 0.85, flatShading: true,
    emissive: resolved.grass, emissiveIntensity: 0.1,
  })
  const mesh = new InstancedMesh(geo, mat, spots.length)
  mesh.name = 'atmos-fern'
  seatInstances(mesh, spots, resolved.seed, 43, 0)
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function addStones(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const spots = bankSpots(8, resolved.seed, 71)
  if (!spots.length) return
  const geo = new BoxGeometry(0.38, 0.22, 0.3)
  const mat = new MeshStandardMaterial({
    color: new Color(resolved.stone).multiplyScalar(0.78),
    roughness: 0.95, flatShading: true,
  })
  const mesh = new InstancedMesh(geo, mat, spots.length)
  mesh.name = 'atmos-stone'
  seatInstances(mesh, spots, resolved.seed, 73, 0.11)
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function addLogs(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const spots = bankSpots(4, resolved.seed, 91)
  if (!spots.length) return
  const geo = new CylinderGeometry(0.08, 0.1, 1.1, 6)
  geo.rotateZ(Math.PI / 2)
  const mat = new MeshStandardMaterial({ color: 0x6a5344, roughness: 0.9, flatShading: true })
  const mesh = new InstancedMesh(geo, mat, spots.length)
  mesh.name = 'atmos-log'
  seatInstances(mesh, spots, resolved.seed, 93, 0.12)
  addMesh(root, kept, mesh)
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
  for (const name of ['atmos-sheet', 'atmos-river']) {
    const mesh = root.getObjectByName(name) as Mesh | undefined
    const material = mesh?.material
    if (!(material instanceof ShaderMaterial)) continue
    material.uniforms.uTime.value = seconds
    material.uniforms.uFlow.value = flow
  }
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
  addCliffs(root, resolved, kept)
  addSheet(root, waterMaterial(resolved, 1), kept)
  addRiver(root, waterMaterial(resolved, 0), kept)
  addMist(root, kept)
  addDew(root, resolved, kept)
  addRainbow(root, resolved, kept)
  addFerns(root, resolved, kept)
  addStones(root, resolved, kept)
  addLogs(root, resolved, kept)
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
