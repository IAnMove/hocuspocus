import {
  BackSide,
  BufferGeometry,
  Color,
  ConeGeometry,
  DoubleSide,
  FogExp2,
  Group,
  InstancedMesh,
  Mesh,
  MeshBasicMaterial,
  Object3D,
  PlaneGeometry,
  ShaderMaterial,
  SphereGeometry,
  Vector2,
  type Material,
} from 'three'
import type { AtmosHandle } from './clearing.ts'
import type { AtmosSetDefinition } from '../definition.ts'
import type { AtmosSettings, ResolvedAtmos } from '../params.ts'
import { hash2 } from '../noise.ts'
import { CLEARING_SUBJECT, scatter, type Area } from '../layout.ts'

type Kept = { geometries: BufferGeometry[]; materials: Material[] }
type Spot = [number, number]

// ConeGeometry's apex is +y. Ceiling crystals use rotation.x = PI so the apex points down.
const GROUND_VERTEX = `
  varying vec2 vXZ;
  void main() {
    vXZ = position.xz;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`
const GROUND_FRAGMENT = `
  uniform vec3 uStone;
  uniform vec3 uGlow;
  uniform vec2 uLeft;
  uniform vec2 uRight;
  varying vec2 vXZ;
  void main() {
    float left = exp(-dot(vXZ - uLeft, vXZ - uLeft) * 0.28);
    float right = exp(-dot(vXZ - uRight, vXZ - uRight) * 0.28);
    gl_FragColor = vec4(mix(uStone, uGlow, clamp(left + right, 0.0, 1.0) * 0.72), 1.0);
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
    gl_FragColor = vec4(mix(uHorizon, uZenith, smoothstep(-0.05, 0.55, vH)), 1.0);
  }
`

const LEFT: Area = { x0: -5.4, x1: -2.6, z0: -6.2, z1: -2.8 }
const RIGHT: Area = { x0: 2.5, x1: 5.2, z0: -6.2, z1: -2.7 }
const ROCK_SPOTS: Spot[] = [[-6.3, -3.5], [6.0, -3.2], [-1.4, -7.6], [2.6, -7.3]]
const MOTE_SPOTS: Array<[number, number, number]> = [
  [-4.6, 2.3, -4.8], [-3.4, 2.7, -5.6], [-5.4, 2.0, -3.8],
  [3.8, 2.4, -4.4], [5.0, 2.8, -5.4], [3.0, 2.1, -3.5],
]

const CRYSTAL: Record<string, readonly string[]> = {
  amethyst: ['#49d6ff', '#e056c8', '#ffd27a'],
  aqua: ['#3ee0c2', '#7ec8ff', '#d8ffe6'],
}
const ROCK: Record<string, string> = { amethyst: '#4a3b5c', aqua: '#2c4550' }
const DRIP: Record<string, string> = { amethyst: '#b7ecff', aqua: '#d4fff4' }
const MOTE: Record<string, string> = { amethyst: '#f6e4ff', aqua: '#e7fff6' }
const GLOW: Record<string, string> = { amethyst: '#49d6ff', aqua: '#3ee0c2' }
const FALLBACK_GROUND: Record<string, string> = { amethyst: '#3c2c52', aqua: '#1c3a44' }

const CAVE_PALETTES = {
  amethyst: { fog: '#2a1844', ground: '#3c2c52', accent: '#49d6ff', sky: ['#2a1844', '#100818'] },
  aqua: { fog: '#14303a', ground: '#1c3a44', accent: '#3ee0c2', sky: ['#14303a', '#071820'] },
} as const

const CAVE_TIMES = {
  deep: { sun: [0.05, -0.95, -0.12], sunColor: '#6e5a90' },
  glow: { sun: [-0.1, -0.7, -0.2], sunColor: '#d0b0ff' },
} as const

const WIDE_EYE = [0.15, 1.48, 3.9] as const
const WIDE_LOOK = [0.2, 1.75, -5.4] as const
const LOW_EYE = [0.55, 0.62, 2.35] as const
const LOW_LOOK = [-3.6, 1.6, -4.0] as const

function emptyKept(): Kept {
  return { geometries: [], materials: [] }
}

function hexColor(color: string): [number, number, number] {
  const n = Number.parseInt(color.slice(1), 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

function swatch(table: Record<string, string>, palette: string): string {
  return table[palette] ?? table.amethyst
}

function glowAmount(variant: number | undefined): number {
  const value = typeof variant === 'number' && Number.isFinite(variant) ? variant : 5
  return Math.min(8, Math.max(0, value))
}

function glowScale(variant: number | undefined): number {
  return 0.28 + glowAmount(variant) * 0.09
}

function zenithColor(time: string): string {
  return time === 'glow' ? '#3a1860' : '#1c1234'
}

function floorSpots(count: number, seed: number): Spot[] {
  const left = Math.ceil(count / 2)
  return [
    ...scatter(left, seed, 11, [], LEFT, 0.75),
    ...scatter(Math.max(0, count - left), seed, 29, [], RIGHT, 0.75),
  ]
}

function centroid(spots: Spot[], fallback: Spot): Spot {
  if (spots.length < 1) return fallback
  let x = 0
  let z = 0
  for (const spot of spots) {
    x += spot[0]
    z += spot[1]
  }
  return [x / spots.length, z / spots.length]
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

function flatCave(resolved: ResolvedAtmos): { root: Group; kept: Kept } {
  const root = new Group()
  root.name = 'atmos-crystal-cave'
  const kept = emptyKept()
  const geo = new PlaneGeometry(16, 16)
  geo.rotateX(-Math.PI / 2)
  const mat = new MeshBasicMaterial({ color: resolved.stone })
  root.add(new Mesh(geo, mat))
  kept.geometries.push(geo)
  kept.materials.push(mat)
  return { root, kept }
}

function addGround(root: Group, resolved: ResolvedAtmos, kept: Kept, left: Spot, right: Spot) {
  const geo = new PlaneGeometry(28, 28)
  geo.rotateX(-Math.PI / 2)
  const mat = new ShaderMaterial({
    uniforms: {
      uStone: { value: new Color(resolved.stone) },
      uGlow: { value: new Color(swatch(GLOW, resolved.palette)) },
      uLeft: { value: new Vector2(left[0], left[1]) },
      uRight: { value: new Vector2(right[0], right[1]) },
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

function paintCrystals(mesh: InstancedMesh, spots: Spot[], palette: string, seed: number, glow: number, ceiling: boolean) {
  const colors = CRYSTAL[palette] ?? CRYSTAL.amethyst
  const dummy = new Object3D()
  const color = new Color()
  spots.forEach(([x, z], index) => {
    const height = 0.9 + hash2(index, ceiling ? 3 : 1, seed) * 1.15
    const radius = 0.16 + hash2(index, 7, seed) * 0.16
    const y = ceiling ? 4.02 - height * 0.5 : height * 0.5
    dummy.position.set(x, y, z)
    dummy.rotation.set(ceiling ? Math.PI : 0, hash2(index, 9, seed) * 0.8, 0)
    dummy.scale.set(radius, height, radius)
    dummy.updateMatrix()
    mesh.setMatrixAt(index, dummy.matrix)
    color.set(colors[index % colors.length])
    color.multiplyScalar(glow)
    mesh.setColorAt(index, color)
  })
  mesh.instanceMatrix.needsUpdate = true
  if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true
}

function addCrystals(root: Group, kept: Kept, name: string, spots: Spot[], palette: string, seed: number, glow: number, ceiling: boolean) {
  if (spots.length < 1) return
  const geo = new ConeGeometry(1, 1, 5)
  const mat = new MeshBasicMaterial()
  const mesh = new InstancedMesh(geo, mat, spots.length)
  mesh.name = name
  mesh.userData.spots = spots
  paintCrystals(mesh, spots, palette, seed, glow, ceiling)
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function addRocks(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const geo = new ConeGeometry(1, 1, 5)
  const mat = new MeshBasicMaterial({ color: swatch(ROCK, resolved.palette) })
  const mesh = new InstancedMesh(geo, mat, ROCK_SPOTS.length)
  mesh.name = 'atmos-rock'
  const dummy = new Object3D()
  ROCK_SPOTS.forEach(([x, z], index) => {
    const height = 1.1 + hash2(index, 2, resolved.seed) * 1.1
    dummy.position.set(x, height * 0.5, z)
    dummy.rotation.set(0, hash2(index, 4, resolved.seed), 0)
    dummy.scale.set(0.45, height, 0.45)
    dummy.updateMatrix()
    mesh.setMatrixAt(index, dummy.matrix)
  })
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function placeDrips(mesh: InstancedMesh, spots: Spot[], seconds: number) {
  const dummy = new Object3D()
  spots.forEach(([x, z], index) => {
    const span = 2.6
    const phase = (seconds * 0.5 + index * 0.41) % span
    dummy.position.set(x, 3.05 - phase, z)
    dummy.rotation.set(0, 0, 0)
    dummy.scale.set(0.07, 0.28, 0.07)
    dummy.updateMatrix()
    mesh.setMatrixAt(index, dummy.matrix)
  })
  mesh.instanceMatrix.needsUpdate = true
}

function addDrips(root: Group, resolved: ResolvedAtmos, kept: Kept, spots: Spot[]) {
  const used = spots.slice(0, resolved.moteCount)
  if (used.length < 1) return
  const geo = new SphereGeometry(1, 6, 4)
  const mat = new MeshBasicMaterial({ color: swatch(DRIP, resolved.palette) })
  const mesh = new InstancedMesh(geo, mat, used.length)
  mesh.name = 'atmos-drip'
  mesh.userData.spots = used
  placeDrips(mesh, used, 0)
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function placeMotes(mesh: InstancedMesh, seconds: number) {
  const dummy = new Object3D()
  MOTE_SPOTS.forEach(([x, y, z], index) => {
    const drift = Math.sin(seconds * 0.4 + index * 1.1) * 0.18
    dummy.position.set(x + drift, y + Math.sin(seconds * 0.7 + index) * 0.08, z)
    dummy.scale.setScalar(0.1)
    dummy.updateMatrix()
    mesh.setMatrixAt(index, dummy.matrix)
  })
  mesh.instanceMatrix.needsUpdate = true
}

function addMotes(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const geo = new SphereGeometry(1, 6, 4)
  const mat = new MeshBasicMaterial({ color: swatch(MOTE, resolved.palette) })
  const mesh = new InstancedMesh(geo, mat, MOTE_SPOTS.length)
  mesh.name = 'atmos-mote'
  placeMotes(mesh, 0)
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function addRoof(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const geo = new PlaneGeometry(22, 22)
  geo.rotateX(Math.PI / 2)
  const mat = new MeshBasicMaterial({ color: swatch(ROCK, resolved.palette), side: DoubleSide })
  const mesh = new Mesh(geo, mat)
  mesh.name = 'atmos-roof'
  mesh.position.set(0, 4.05, -2)
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function addSky(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const geo = new SphereGeometry(9, 16, 12)
  const mat = new ShaderMaterial({
    uniforms: {
      uHorizon: { value: new Color(resolved.fogColor) },
      uZenith: { value: new Color(zenithColor(resolved.timeOfDay)) },
    },
    vertexShader: SKY_VERTEX,
    fragmentShader: SKY_FRAGMENT,
    side: BackSide,
  })
  const mesh = new Mesh(geo, mat)
  mesh.name = 'atmos-sky'
  mesh.position.set(0, -1.2, -0.5)
  mesh.frustumCulled = false
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function syncCave(root: Group, seconds: number, resolved: ResolvedAtmos, live?: AtmosSettings) {
  const settings = live ?? resolved
  const glow = glowScale(settings.variant)
  const palette = settings.palette
  for (const name of ['atmos-crystal', 'atmos-ceiling'] as const) {
    const mesh = root.getObjectByName(name) as InstancedMesh | undefined
    const spots = mesh?.userData.spots as Spot[] | undefined
    if (mesh && spots) paintCrystals(mesh, spots, palette, resolved.seed, glow, name === 'atmos-ceiling')
  }
  const drips = root.getObjectByName('atmos-drip') as InstancedMesh | undefined
  const dripSpots = drips?.userData.spots as Spot[] | undefined
  if (drips && dripSpots) placeDrips(drips, dripSpots, seconds)
  const motes = root.getObjectByName('atmos-mote') as InstancedMesh | undefined
  if (motes) placeMotes(motes, seconds)
  const fog = (root.parent as { fog?: unknown } | null)?.fog
  if (fog instanceof FogExp2) fog.density = 0.014 + settings.fogDensity * 0.034
}

function liveHandle(root: Group, kept: Kept, resolved: ResolvedAtmos): AtmosHandle {
  return {
    ms: { shafts: 0, dof: 0, grade: 0 },
    passes: () => [],
    sync: (seconds, _camera, _light, _quality, _focus, live) => syncCave(root, seconds, resolved, live),
    dispose: disposeOnce(() => disposeKept(root, kept)),
  }
}

export function buildCrystalCave(resolved: ResolvedAtmos, webgl2: boolean): { root: Group; handle: AtmosHandle } {
  if (!webgl2) {
    const flat = flatCave(resolved)
    const handle = idleHandle(flat.root, flat.kept)
    flat.root.userData.atmos = handle
    return { root: flat.root, handle }
  }
  const root = new Group()
  root.name = 'atmos-crystal-cave'
  const kept = emptyKept()
  const spots = floorSpots(resolved.grassBlades, resolved.seed)
  const left = spots.filter(spot => spot[0] < 0)
  const right = spots.filter(spot => spot[0] >= 0)
  addGround(root, resolved, kept, centroid(left, [-4.2, -4.2]), centroid(right, [4.2, -4.2]))
  addCrystals(root, kept, 'atmos-crystal', spots, resolved.palette, resolved.seed, glowScale(resolved.variant), false)
  addCrystals(root, kept, 'atmos-ceiling', spots, resolved.palette, resolved.seed, glowScale(resolved.variant), true)
  addRoof(root, resolved, kept)
  addRocks(root, resolved, kept)
  addDrips(root, resolved, kept, spots)
  addMotes(root, resolved, kept)
  addSky(root, resolved, kept)
  const handle = liveHandle(root, kept, resolved)
  root.userData.atmos = handle
  return { root, handle }
}

export const crystalCaveSet: AtmosSetDefinition = {
  id: 'atmos-crystal-cave',
  titleKey: 'template.atmos-crystal-cave-wide.title',
  setting: 'cave',
  seed: 88017,
  subject: CLEARING_SUBJECT,
  subjectYaw: 0.15,
  palettes: CAVE_PALETTES,
  times: CAVE_TIMES,
  defaults: { timeOfDay: 'deep', fogDensity: 0.48, wind: 0.15, motes: 0.4, palette: 'amethyst', variant: 5 },
  variant: { labelKey: 'atmos.glow', min: 0, max: 8 },
  low: { shaftSteps: 0, grassBlades: 8, moteCount: 8 },
  high: { shaftSteps: 0, grassBlades: 12, moteCount: 14 },
  templates: [
    { id: 'atmos-crystal-cave-wide', camera: 'establishment', eye: WIDE_EYE, look: WIDE_LOOK, fov: 52, duration: 6 },
    { id: 'atmos-crystal-cave-low', camera: 'establishment', eye: LOW_EYE, look: LOW_LOOK, fov: 56, duration: 6 },
  ],
  build: buildCrystalCave,
  fallback(resolved) {
    const sky = CAVE_PALETTES[resolved.palette as keyof typeof CAVE_PALETTES]?.fog ?? CAVE_PALETTES.amethyst.fog
    return { sky: hexColor(sky), ground: hexColor(FALLBACK_GROUND[resolved.palette] ?? FALLBACK_GROUND.amethyst) }
  },
}
