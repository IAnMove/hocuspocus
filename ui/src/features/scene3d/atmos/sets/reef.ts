import {
  BackSide,
  BufferGeometry,
  Color,
  ConeGeometry,
  DoubleSide,
  Float32BufferAttribute,
  FogExp2,
  Group,
  InstancedMesh,
  Mesh,
  MeshBasicMaterial,
  Object3D,
  PlaneGeometry,
  ShaderMaterial,
  SphereGeometry,
  type Material,
} from 'three'
import type { AtmosHandle } from './clearing.ts'
import type { AtmosSetDefinition } from '../definition.ts'
import type { AtmosSettings, ResolvedAtmos } from '../params.ts'
import { hash2 } from '../noise.ts'
import { CLEARING_SUBJECT } from '../layout.ts'

type Kept = { geometries: BufferGeometry[]; materials: Material[] }
type Spot = readonly [number, number]
// x, y, z, fixed yaw, drift sign. Nose is local −z; ±π/2 turns that nose onto ±x.
type FishSpot = readonly [number, number, number, number, number]

// PlaneGeometry faces +z. rotateX(-PI/2) lays it on xz with the normal pointing up.
const GROUND_VERTEX = `
  varying vec2 vXZ;
  void main() {
    vXZ = position.xz;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`
const GROUND_FRAGMENT = `
  uniform vec3 uSand;
  uniform vec3 uCaustic;
  uniform vec3 uWater;
  uniform float uTime;
  uniform float uCurrent;
  uniform float uGain;
  varying vec2 vXZ;
  void main() {
    vec2 p = vXZ;
    float t = uTime * (0.32 + uCurrent * 0.05);
    float n1 = sin(p.x * 1.15 + sin(p.y * 0.62 + t) * 1.15 + t);
    float n2 = sin(p.y * 1.02 + sin(p.x * 0.58 - t * 0.75) * 1.05 - t * 0.8);
    float net = smoothstep(0.28, 0.86, n1) * smoothstep(0.28, 0.86, n2);
    float n3 = sin(p.x * 0.72 + p.y * 0.48 + t * 1.15);
    float n4 = sin(p.x * 0.5 - p.y * 0.8 - t * 0.9);
    float cross = smoothstep(0.42, 0.9, n3) * smoothstep(0.42, 0.9, n4);
    float caustic = clamp(max(net, cross), 0.0, 1.0) * uGain;
    float far = smoothstep(8.0, 16.0, length(vXZ));
    vec3 color = mix(uSand, uCaustic, caustic);
    gl_FragColor = vec4(mix(color, uWater, far), 1.0);
  }
`
const WATER_VERTEX = `
  varying float vH;
  void main() {
    vH = normalize(position).y;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`
const WATER_FRAGMENT = `
  uniform vec3 uHorizon;
  uniform vec3 uAbove;
  uniform vec3 uDeep;
  varying float vH;
  void main() {
    vec3 mid = mix(uDeep, uHorizon, smoothstep(-0.35, 0.12, vH));
    gl_FragColor = vec4(mix(mid, uAbove, smoothstep(0.28, 0.82, vH)), 1.0);
  }
`

const FISH_SPOTS: readonly FishSpot[] = [
  [-4.4, 1.65, -4.2, Math.PI / 2, -1],
  [-3.7, 1.15, -5.1, Math.PI / 2, -1],
  [-5.1, 2.15, -5.4, Math.PI / 2, -1],
  [-4.6, 2.35, -3.5, Math.PI / 2, -1],
  [-5.5, 1.35, -3.3, Math.PI / 2, -1],
  [4.3, 1.55, -4.0, -Math.PI / 2, 1],
  [3.6, 2.05, -5.2, -Math.PI / 2, 1],
  [5.1, 1.15, -4.8, -Math.PI / 2, 1],
  [4.7, 2.3, -3.4, -Math.PI / 2, 1],
  [3.5, 1.4, -3.2, -Math.PI / 2, 1],
  [-6.1, 1.9, -6.3, Math.PI / 2, -1],
  [-3.4, 1.85, -6.5, Math.PI / 2, -1],
  [5.9, 1.75, -6.1, -Math.PI / 2, 1],
  [3.4, 2.15, -6.4, -Math.PI / 2, 1],
  [-4.8, 0.95, -6.6, Math.PI / 2, -1],
  [4.5, 0.95, -6.5, -Math.PI / 2, 1],
]

const BUBBLE_SPOTS: readonly Spot[] = [
  [-2.7, -3.4], [-2.3, -4.6], [-3.2, -2.5],
  [3.1, -3.3], [2.7, -4.5], [3.5, -2.3],
  [-4.5, -5.6], [4.6, -5.4],
  [-2.0, -6.2], [2.4, -6.3],
  [-5.2, -1.9], [5.0, -1.7],
  [-3.8, -0.2], [4.0, 0.2],
  [-6.2, -4.2], [6.0, -3.8],
  [-2.6, -6.8], [3.2, -6.7],
]

const ROCK_SPOTS: readonly Spot[] = [
  [-6.6, -3.4], [6.4, -3.0], [-5.4, -6.8], [5.6, -6.6], [-7.4, -5.2], [6.8, -5.4],
]

const CORAL_SPOTS: readonly Spot[] = [
  [-5.6, -3.8], [5.4, -3.5], [-4.6, -6.2], [4.6, -6.0],
  [-6.4, -5.6], [5.8, -4.8], [-5.0, -4.6], [4.2, -4.4],
]

const FISH: Record<string, readonly string[]> = {
  lagoon: ['#ff7a2a', '#ffe14a', '#3ec6ff', '#ff4f88'],
  abyss: ['#7dffe8', '#e7ff5a', '#ff6ad5', '#8fd0ff'],
}
const CORAL: Record<string, readonly string[]> = {
  lagoon: ['#ff5d73', '#ffb03a', '#2ec8a0'],
  abyss: ['#ff4fa3', '#7dffe0', '#c8ff4a'],
}
const ROCK: Record<string, string> = { lagoon: '#5e6e66', abyss: '#2a3844' }
const BUBBLE: Record<string, string> = { lagoon: '#f4fffc', abyss: '#dffbff' }
const CAUSTIC: Record<string, string> = { lagoon: '#f6fffd', abyss: '#8dfff8' }
const WATER: Record<string, string> = { lagoon: '#147888', abyss: '#0c1e28' }
const DEEP: Record<string, string> = { lagoon: '#0a3e4c', abyss: '#071018' }
const SAND: Record<string, string> = { lagoon: '#c9924e', abyss: '#243240' }
const FALLBACK_GROUND: Record<string, string> = { lagoon: '#c9924e', abyss: '#243240' }
const ZENITH: Record<string, Record<string, string>> = {
  lagoon: { shallows: '#7ee7f4', trench: '#14586a' },
  abyss: { shallows: '#1f6f88', trench: '#0a2838' },
}

const REEF_PALETTES = {
  lagoon: { fog: '#147888', ground: '#c9924e', accent: '#ff7a2a', sky: ['#9af4ff', '#0a3e4c'] },
  abyss: { fog: '#0c1e28', ground: '#243240', accent: '#7dffe8', sky: ['#1f6f88', '#071018'] },
} as const

const REEF_TIMES = {
  shallows: { sun: [0.18, -0.9, -0.38], sunColor: '#f4fff8' },
  trench: { sun: [0.06, -0.72, -0.22], sunColor: '#8ecfff' },
} as const

const WIDE_EYE = [0.15, 1.48, 3.9] as const
const WIDE_LOOK = [0.2, 1.75, -5.4] as const
const LOW_EYE = [0.55, 0.62, 2.35] as const
const LOW_LOOK = [-4.4, 1.45, -4.1] as const

function emptyKept(): Kept {
  return { geometries: [], materials: [] }
}

function hexColor(color: string): [number, number, number] {
  const n = Number.parseInt(color.slice(1), 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

function swatch(table: Record<string, string>, palette: string): string {
  return table[palette] ?? table.lagoon
}

function currentAmount(variant: number | undefined): number {
  const value = typeof variant === 'number' && Number.isFinite(variant) ? variant : 4
  return Math.min(8, Math.max(0, value))
}

function causticGain(time: string): number {
  return time === 'trench' ? 0.42 : 1
}

function zenithColor(palette: string, time: string): string {
  const row = ZENITH[palette] ?? ZENITH.lagoon
  return row[time] ?? row.shallows
}

function paletteColors(table: Record<string, readonly string[]>, palette: string): readonly string[] {
  return table[palette] ?? table.lagoon
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

function addMesh(root: Group, kept: Kept, mesh: Mesh | InstancedMesh) {
  root.add(mesh)
  kept.geometries.push(mesh.geometry)
}

function flatReef(resolved: ResolvedAtmos): { root: Group; kept: Kept } {
  const root = new Group()
  root.name = 'atmos-reef'
  const kept = emptyKept()
  const geo = new PlaneGeometry(16, 16)
  geo.rotateX(-Math.PI / 2)
  const mat = new MeshBasicMaterial({ color: resolved.stone })
  const mesh = new Mesh(geo, mat)
  mesh.name = 'atmos-reef'
  root.add(mesh)
  kept.geometries.push(geo)
  kept.materials.push(mat)
  return { root, kept }
}

function schoolSpots(count: number, seed: number): FishSpot[] {
  return FISH_SPOTS.slice(0, Math.max(0, count)).map((spot, index) => {
    const jx = (hash2(index, 3, seed) - 0.5) * 0.36
    const jz = (hash2(index, 5, seed) - 0.5) * 0.36
    const next: FishSpot = [spot[0] + jx, spot[1], spot[2] + jz, spot[3], spot[4]]
    return next
  })
}

function bubbleSpots(count: number): Spot[] {
  return BUBBLE_SPOTS.slice(0, Math.max(0, count))
}

function fishGeometry(): BufferGeometry {
  const positions = [
    0, 0, -0.9, 0.16, 0, 0.1, 0, 0.28, 0.05,
    0, 0, -0.9, 0, 0.28, 0.05, -0.16, 0, 0.1,
    0, 0, -0.9, -0.16, 0, 0.1, 0, -0.22, 0.05,
    0, 0, -0.9, 0, -0.22, 0.05, 0.16, 0, 0.1,
    0, 0, 0.55, 0, 0.28, 0.05, 0.16, 0, 0.1,
    0, 0, 0.55, -0.16, 0, 0.1, 0, 0.28, 0.05,
    0, 0, 0.55, 0, -0.22, 0.05, -0.16, 0, 0.1,
    0, 0, 0.55, 0.16, 0, 0.1, 0, -0.22, 0.05,
    0, 0.42, 1.05, 0, -0.36, 1.05, 0, 0, 0.42,
    0, -0.36, 1.05, 0, 0.42, 1.05, 0, 0, 0.42,
    0, 0.28, 0.05, 0, 0.55, 0.35, 0, 0.22, 0.48,
    0, 0.55, 0.35, 0, 0.28, 0.05, 0, 0.22, 0.48,
  ]
  const geo = new BufferGeometry()
  geo.setAttribute('position', new Float32BufferAttribute(positions, 3))
  geo.computeVertexNormals()
  return geo
}

function paintInstances(mesh: InstancedMesh, colors: readonly string[]) {
  const color = new Color()
  for (let index = 0; index < mesh.count; index += 1) {
    color.set(colors[index % colors.length])
    mesh.setColorAt(index, color)
  }
  if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true
}

function placeFish(mesh: InstancedMesh, spots: FishSpot[], seconds: number, current: number) {
  const dummy = new Object3D()
  const amp = 0.08 + current * 0.12
  const speed = 0.35 + current * 0.05
  spots.forEach(([x, y, z, yaw, drift], index) => {
    const along = Math.sin(seconds * speed + index * 0.7) * amp
    const bob = Math.sin(seconds * 0.85 + index * 1.3) * 0.1
    const sway = Math.sin(seconds * 0.4 + index * 0.5) * amp * 0.25
    dummy.position.set(x + along * drift, y + bob, z + sway)
    dummy.rotation.set(0, yaw, 0)
    dummy.scale.setScalar(0.78 + (index % 3) * 0.1)
    dummy.updateMatrix()
    mesh.setMatrixAt(index, dummy.matrix)
  })
  mesh.instanceMatrix.needsUpdate = true
}

function addFish(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const spots = schoolSpots(resolved.grassBlades, resolved.seed)
  if (spots.length < 1) return
  const mat = new MeshBasicMaterial({ side: DoubleSide })
  const mesh = new InstancedMesh(fishGeometry(), mat, spots.length)
  mesh.name = 'atmos-fish'
  mesh.frustumCulled = false
  mesh.userData.spots = spots
  paintInstances(mesh, paletteColors(FISH, resolved.palette))
  placeFish(mesh, spots, 0, currentAmount(resolved.variant))
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function placeBubbles(mesh: InstancedMesh, spots: Spot[], seconds: number, current: number) {
  const dummy = new Object3D()
  const span = 3.6
  const speed = 0.32 + current * 0.05
  const swayAmp = 0.04 + current * 0.03
  spots.forEach(([x, z], index) => {
    const phase = (seconds * speed + index * 0.47) % span
    const sway = Math.sin(seconds * 0.7 + index * 1.1) * swayAmp
    dummy.position.set(x + sway, 0.18 + phase, z)
    dummy.rotation.set(0, 0, 0)
    dummy.scale.setScalar(0.24 + (index % 4) * 0.08)
    dummy.updateMatrix()
    mesh.setMatrixAt(index, dummy.matrix)
  })
  mesh.instanceMatrix.needsUpdate = true
}

function addBubbles(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const spots = bubbleSpots(resolved.moteCount)
  if (spots.length < 1) return
  const geo = new SphereGeometry(1, 7, 5)
  const mat = new MeshBasicMaterial({ color: swatch(BUBBLE, resolved.palette) })
  const mesh = new InstancedMesh(geo, mat, spots.length)
  mesh.name = 'atmos-bubble'
  mesh.frustumCulled = false
  mesh.userData.spots = spots
  placeBubbles(mesh, spots, 0, currentAmount(resolved.variant))
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function addRocks(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const geo = new SphereGeometry(1, 6, 5)
  const mat = new MeshBasicMaterial({ color: swatch(ROCK, resolved.palette) })
  const mesh = new InstancedMesh(geo, mat, ROCK_SPOTS.length)
  mesh.name = 'atmos-rock'
  mesh.frustumCulled = false
  const dummy = new Object3D()
  ROCK_SPOTS.forEach(([x, z], index) => {
    const height = 0.48 + hash2(index, 2, resolved.seed) * 0.42
    const wide = 0.72 + hash2(index, 4, resolved.seed) * 0.38
    dummy.position.set(x, height, z)
    dummy.rotation.set(0, hash2(index, 6, resolved.seed), 0)
    dummy.scale.set(wide, height, wide * 0.82)
    dummy.updateMatrix()
    mesh.setMatrixAt(index, dummy.matrix)
  })
  mesh.instanceMatrix.needsUpdate = true
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function addCoral(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const geo = new ConeGeometry(1, 1, 5)
  const mat = new MeshBasicMaterial()
  const mesh = new InstancedMesh(geo, mat, CORAL_SPOTS.length)
  mesh.name = 'atmos-coral'
  mesh.frustumCulled = false
  const dummy = new Object3D()
  CORAL_SPOTS.forEach(([x, z], index) => {
    const height = 0.7 + hash2(index, 8, resolved.seed) * 0.7
    const radius = 0.16 + hash2(index, 9, resolved.seed) * 0.12
    dummy.position.set(x, height * 0.5, z)
    dummy.rotation.set(0, hash2(index, 11, resolved.seed), 0)
    dummy.scale.set(radius, height, radius)
    dummy.updateMatrix()
    mesh.setMatrixAt(index, dummy.matrix)
  })
  mesh.instanceMatrix.needsUpdate = true
  paintInstances(mesh, paletteColors(CORAL, resolved.palette))
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function addGround(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const geo = new PlaneGeometry(32, 32)
  geo.rotateX(-Math.PI / 2)
  const mat = new ShaderMaterial({
    uniforms: {
      uSand: { value: new Color(swatch(SAND, resolved.palette)) },
      uCaustic: { value: new Color(swatch(CAUSTIC, resolved.palette)) },
      uWater: { value: new Color(swatch(WATER, resolved.palette)) },
      uTime: { value: 0 },
      uCurrent: { value: currentAmount(resolved.variant) },
      uGain: { value: causticGain(resolved.timeOfDay) },
    },
    vertexShader: GROUND_VERTEX,
    fragmentShader: GROUND_FRAGMENT,
  })
  const mesh = new Mesh(geo, mat)
  mesh.name = 'atmos-ground'
  mesh.frustumCulled = false
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function addWater(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const geo = new SphereGeometry(12, 18, 12)
  const mat = new ShaderMaterial({
    uniforms: {
      uHorizon: { value: new Color(swatch(WATER, resolved.palette)) },
      uAbove: { value: new Color(zenithColor(resolved.palette, resolved.timeOfDay)) },
      uDeep: { value: new Color(swatch(DEEP, resolved.palette)) },
    },
    vertexShader: WATER_VERTEX,
    fragmentShader: WATER_FRAGMENT,
    side: BackSide,
  })
  const mesh = new Mesh(geo, mat)
  mesh.name = 'atmos-water'
  mesh.position.set(0, -1.4, -0.8)
  mesh.frustumCulled = false
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function syncGround(root: Group, seconds: number, settings: AtmosSettings) {
  const ground = root.getObjectByName('atmos-ground')
  if (!(ground instanceof Mesh) || !(ground.material instanceof ShaderMaterial)) return
  const uniforms = ground.material.uniforms
  uniforms.uTime.value = seconds
  uniforms.uCurrent.value = currentAmount(settings.variant)
  uniforms.uGain.value = causticGain(settings.timeOfDay)
  uniforms.uSand.value.set(swatch(SAND, settings.palette))
  uniforms.uCaustic.value.set(swatch(CAUSTIC, settings.palette))
  uniforms.uWater.value.set(swatch(WATER, settings.palette))
}

function syncWater(root: Group, settings: AtmosSettings) {
  const water = root.getObjectByName('atmos-water')
  if (!(water instanceof Mesh) || !(water.material instanceof ShaderMaterial)) return
  water.material.uniforms.uAbove.value.set(zenithColor(settings.palette, settings.timeOfDay))
  water.material.uniforms.uHorizon.value.set(swatch(WATER, settings.palette))
  water.material.uniforms.uDeep.value.set(swatch(DEEP, settings.palette))
}

function syncColors(root: Group, palette: string) {
  const fish = root.getObjectByName('atmos-fish') as InstancedMesh | undefined
  if (fish) paintInstances(fish, paletteColors(FISH, palette))
  const coral = root.getObjectByName('atmos-coral') as InstancedMesh | undefined
  if (coral) paintInstances(coral, paletteColors(CORAL, palette))
  const rockMat = (root.getObjectByName('atmos-rock') as InstancedMesh | undefined)?.material
  if (rockMat instanceof MeshBasicMaterial) rockMat.color.set(swatch(ROCK, palette))
  const bubbleMat = (root.getObjectByName('atmos-bubble') as InstancedMesh | undefined)?.material
  if (bubbleMat instanceof MeshBasicMaterial) bubbleMat.color.set(swatch(BUBBLE, palette))
}

function syncSchool(root: Group, seconds: number, settings: AtmosSettings) {
  const current = currentAmount(settings.variant)
  const fish = root.getObjectByName('atmos-fish') as InstancedMesh | undefined
  const spots = fish?.userData.spots as FishSpot[] | undefined
  if (fish && spots) placeFish(fish, spots, seconds, current)
  const bubbles = root.getObjectByName('atmos-bubble') as InstancedMesh | undefined
  const bubbleSpots = bubbles?.userData.spots as Spot[] | undefined
  if (bubbles && bubbleSpots) placeBubbles(bubbles, bubbleSpots, seconds, current)
}

function syncReef(root: Group, seconds: number, resolved: ResolvedAtmos, live?: AtmosSettings) {
  const settings = live ?? resolved
  syncGround(root, seconds, settings)
  syncWater(root, settings)
  syncColors(root, settings.palette)
  syncSchool(root, seconds, settings)
  const fog = (root.parent as { fog?: unknown } | null)?.fog
  if (fog instanceof FogExp2) fog.density = 0.014 + settings.fogDensity * 0.034
}

function liveHandle(root: Group, kept: Kept, resolved: ResolvedAtmos): AtmosHandle {
  return {
    ms: { shafts: 0, dof: 0, grade: 0 },
    passes: () => [],
    sync: (seconds, _camera, _light, _quality, _focus, live) => syncReef(root, seconds, resolved, live),
    dispose: disposeOnce(() => disposeKept(root, kept)),
  }
}

export function buildReef(resolved: ResolvedAtmos, webgl2: boolean): { root: Group; handle: AtmosHandle } {
  if (!webgl2) {
    const flat = flatReef(resolved)
    const handle = idleHandle(flat.root, flat.kept)
    flat.root.userData.atmos = handle
    return { root: flat.root, handle }
  }
  const root = new Group()
  root.name = 'atmos-reef'
  const kept = emptyKept()
  addGround(root, resolved, kept)
  addWater(root, resolved, kept)
  addRocks(root, resolved, kept)
  addCoral(root, resolved, kept)
  addFish(root, resolved, kept)
  addBubbles(root, resolved, kept)
  const handle = liveHandle(root, kept, resolved)
  root.userData.atmos = handle
  return { root, handle }
}

export const reefSet: AtmosSetDefinition = {
  id: 'atmos-reef',
  titleKey: 'template.atmos-reef-wide.title',
  setting: 'sea',
  seed: 93017,
  subject: CLEARING_SUBJECT,
  subjectYaw: 0.15,
  palettes: REEF_PALETTES,
  times: REEF_TIMES,
  defaults: { timeOfDay: 'shallows', fogDensity: 0.22, wind: 0.35, motes: 0.55, palette: 'lagoon', variant: 4 },
  variant: { labelKey: 'atmos.current', min: 0, max: 8 },
  low: { shaftSteps: 0, grassBlades: 10, moteCount: 14 },
  high: { shaftSteps: 0, grassBlades: 16, moteCount: 18 },
  templates: [
    { id: 'atmos-reef-wide', camera: 'establishment', eye: WIDE_EYE, look: WIDE_LOOK, fov: 50, duration: 6 },
    { id: 'atmos-reef-low', camera: 'establishment', eye: LOW_EYE, look: LOW_LOOK, fov: 56, duration: 6 },
  ],
  build: buildReef,
  fallback(resolved) {
    const sky = REEF_PALETTES[resolved.palette as keyof typeof REEF_PALETTES]?.fog ?? REEF_PALETTES.lagoon.fog
    return { sky: hexColor(sky), ground: hexColor(FALLBACK_GROUND[resolved.palette] ?? FALLBACK_GROUND.lagoon) }
  },
}
