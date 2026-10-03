import {
  BackSide,
  BoxGeometry,
  BufferGeometry,
  Color,
  ConeGeometry,
  CylinderGeometry,
  Float32BufferAttribute,
  FogExp2,
  Group,
  InstancedMesh,
  Matrix4,
  Mesh,
  MeshBasicMaterial,
  Object3D,
  PlaneGeometry,
  Points,
  ShaderMaterial,
  SphereGeometry,
  Vector3,
  type Material,
  type Texture,
} from 'three'
import type { AtmosHandle } from './clearing.ts'
import type { AtmosSetDefinition } from '../definition.ts'
import type { AtmosSettings, ResolvedAtmos } from '../params.ts'
import { fbm2, hash2 } from '../noise.ts'
import { CLEARING_SUBJECT, scatter, type Area } from '../layout.ts'
import { boulders, paintedTerrain, ridge } from './kit.ts'

type Kept = { geometries: BufferGeometry[]; materials: Material[]; textures: Texture[] }

const DUST_VERTEX = `
  attribute float aSeed;
  uniform float uTime;
  void main() {
    vec3 p = position;
    p.x += sin(uTime * 0.35 + aSeed) * 0.18;
    p.y += sin(uTime * 0.22 + aSeed * 1.7) * 0.1;
    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    gl_PointSize = 3.8;
    gl_Position = projectionMatrix * mv;
  }
`
const DUST_FRAGMENT = `
  uniform vec3 uColor;
  void main() {
    gl_FragColor = vec4(uColor, 0.88);
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
    gl_FragColor = vec4(mix(uHorizon, uZenith, smoothstep(-0.02, 0.55, vH)), 1.0);
  }
`

const LEFT_FIELD: Area = { x0: -6.4, x1: -1.85, z0: -6.4, z1: 1.4 }
const RIGHT_FIELD: Area = { x0: 2.2, x1: 6.4, z0: -6.4, z1: 1.4 }
const ROVER = { x: -3.4, z: -2.8 }
const ZENITH: Record<string, string> = { rust: '#f3c98a', dusk: '#5c3458' }
const DUST: Record<string, string> = { rust: '#c47a48', dusk: '#a85a3c' }
const ROCK: Record<string, string> = { rust: '#8a3d28', dusk: '#6a2e24' }
const STRATA: Record<string, string> = { rust: '#e4b07a', dusk: '#d4926a' }
const FALLBACK_GROUND: Record<string, string> = { rust: '#9a5a38', dusk: '#6e3a30' }

const MARS_PALETTES = {
  rust: { fog: '#e09a55', ground: '#c47a48', accent: '#8a3d28', sky: ['#e09a55', '#f3c98a'] },
  dusk: { fog: '#c46a62', ground: '#a85a3c', accent: '#6a2e24', sky: ['#c46a62', '#5c3458'] },
} as const

const MARS_TIMES = {
  noon: { sun: [0.2, -0.78, -0.48], sunColor: '#ffe0b0' },
  dusk: { sun: [-0.62, -0.22, -0.55], sunColor: '#ffb070' },
} as const

const WIDE_EYE = [0.1, 1.45, 4.0] as const
const WIDE_LOOK = [0.0, 2.2, -9.0] as const
const LOW_EYE = [1.35, 0.42, 1.9] as const
const LOW_LOOK = [-0.4, 2.6, -9.5] as const

function emptyKept(): Kept {
  return { geometries: [], materials: [], textures: [] }
}

function hexColor(color: string): [number, number, number] {
  const n = Number.parseInt(color.slice(1), 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

function swatch(table: Record<string, string>, palette: string): string {
  return table[palette] ?? table.rust
}

function devilCount(variant: number | undefined): number {
  const value = typeof variant === 'number' && Number.isFinite(variant) ? variant : 3
  return Math.round(Math.min(8, Math.max(0, value)))
}

function moonHeight(time: string): number {
  return time === 'dusk' ? 3.35 : 6.5
}

function sunAlong(sun: readonly [number, number, number]) {
  const span = Math.hypot(sun[0], sun[2]) || 1
  return { x: sun[0] / span, z: sun[2] / span }
}

function shadowReach(sunY: number): number {
  return 0.85 / Math.max(0.12, -sunY)
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

function addMesh(root: Group, kept: Kept, mesh: Mesh | InstancedMesh | Points) {
  root.add(mesh)
  kept.geometries.push(mesh.geometry)
}

function flatMars(resolved: ResolvedAtmos): { root: Group; kept: Kept } {
  const root = new Group()
  root.name = 'atmos-mars'
  const kept = emptyKept()
  const geo = new PlaneGeometry(16, 16)
  geo.rotateX(-Math.PI / 2)
  const mat = new MeshBasicMaterial({ color: resolved.stone })
  root.add(new Mesh(geo, mat))
  kept.geometries.push(geo)
  kept.materials.push(mat)
  return { root, kept }
}

const SOIL: Record<string, { base: string; alt: string; fleck: string; rock: string[]; sand: string[]; mesa: string; haze: string }> = {
  rust: { base: '#b8683c', alt: '#d99a62', fleck: '#f0c48c', rock: ['#7d3a26', '#92472e', '#6a2f20'], sand: ['#e0aa74', '#d39a66', '#ebbf8a'], mesa: '#a24d2e', haze: '#e09a55' },
  dusk: { base: '#8a4630', alt: '#a85a3c', fleck: '#d98a64', rock: ['#5e2a22', '#6f332a', '#4d221c'], sand: ['#c27c58', '#b46d4c', '#d19070'], mesa: '#6e3028', haze: '#c46a62' },
}

/** Wind-rippled plain with a few broad dunes. */
function marsHeight(resolved: ResolvedAtmos, x: number, z: number): number {
  const dune = (fbm2(x * 0.11, z * 0.11, resolved.seed) - 0.5) * 0.9
  const ripple = Math.sin(x * 2.3 + fbm2(x * 0.3, z * 0.3, resolved.seed + 3) * 4) * 0.035
  return dune + ripple
}

function addGround(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const soil = SOIL[resolved.palette] ?? SOIL.rust
  paintedTerrain(root, kept, {
    size: 44, segments: 110, seed: resolved.seed,
    paint: { base: soil.base, alt: soil.alt, fleck: soil.fleck, seed: resolved.seed, fleckAbove: 0.87 },
    height: (x, z) => marsHeight(resolved, x, z),
    tint: (x, z) => 0.88 + fbm2(x * 0.07 + 2, z * 0.07, resolved.seed + 5) * 0.4,
    flat: { x: CLEARING_SUBJECT[0], z: CLEARING_SUBJECT[2], radius: 1.4 },
    emissive: 0x4a2412,
  })
}

function fieldSpots(count: number, seed: number, salt: number): Array<[number, number]> {
  const half = Math.ceil(count / 2)
  return [
    ...scatter(half, seed, salt, [], LEFT_FIELD, 0.7),
    ...scatter(count - half, seed, salt + 5, [], RIGHT_FIELD, 0.7),
  ]
}

function addRocks(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const soil = SOIL[resolved.palette] ?? SOIL.rust
  const spots = fieldSpots(resolved.grassBlades, resolved.seed, 17)
  boulders(root, kept, spots.map(([x, z], index) => ({
    x, z, size: 0.16 + hash2(index, 9, resolved.seed) * 0.4, flat: 0.6 + hash2(index, 10, resolved.seed) * 0.3,
  })), soil.rock, resolved.seed, 'atmos-rock')
  const pale = fieldSpots(Math.max(4, Math.round(resolved.grassBlades * 0.6)), resolved.seed, 41)
  boulders(root, kept, pale.map(([x, z], index) => ({ x, z, size: 0.12 + hash2(index, 12, resolved.seed) * 0.26, flat: 0.5 })), soil.sand, resolved.seed + 3, 'atmos-strata')
}

function addDunes(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const spots = fieldSpots(6, resolved.seed, 29)
  const geo = new SphereGeometry(1, 6, 4)
  const mat = new MeshBasicMaterial({ color: swatch(STRATA, resolved.palette) })
  const mesh = new InstancedMesh(geo, mat, spots.length)
  mesh.name = 'atmos-dune'
  mesh.visible = false // the dunes are part of the ground relief now
  const dummy = new Object3D()
  spots.forEach(([x, z], index) => {
    const width = 1.1 + hash2(index, 4, resolved.seed) * 0.9
    dummy.position.set(x, 0.12, z)
    dummy.scale.set(width, 0.2, width * 0.72)
    dummy.updateMatrix()
    mesh.setMatrixAt(index, dummy.matrix)
  })
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function addRidge(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const soil = SOIL[resolved.palette] ?? SOIL.rust
  ridge(root, kept, { seed: resolved.seed, count: 12, radius: 15, height: [1.8, 4.2], width: [3.6, 7.2], color: soil.mesa, haze: soil.haze, layers: 2 })
}

function shadeMatrix(matrix: Matrix4, x: number, z: number, alongX: number, alongZ: number, length: number, width: number) {
  const side = new Vector3(-alongZ, 0, alongX)
  const along = new Vector3(alongX, 0, alongZ)
  matrix.makeBasis(side, along, new Vector3(0, 1, 0))
  matrix.scale(new Vector3(width, length, 1))
  matrix.elements[12] = x + alongX * length * 0.5
  matrix.elements[13] = 0.03
  matrix.elements[14] = z + alongZ * length * 0.5
}

function addShadow(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const geo = new PlaneGeometry(1, 1)
  const mat = new MeshBasicMaterial({ color: '#4a2418', transparent: true, opacity: 0.55, depthWrite: false })
  const mesh = new InstancedMesh(geo, mat, 1)
  mesh.name = 'atmos-shadow'
  const along = sunAlong(resolved.sun)
  const length = shadowReach(resolved.sun[1])
  mesh.userData.reach = length
  const matrix = new Matrix4()
  shadeMatrix(matrix, ROVER.x, ROVER.z, along.x, along.z, length, 0.85)
  mesh.setMatrixAt(0, matrix)
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function addWheels(root: Group, kept: Kept) {
  const geo = new CylinderGeometry(0.16, 0.16, 0.1, 6)
  const mat = new MeshBasicMaterial({ color: '#3a302c' })
  const mesh = new InstancedMesh(geo, mat, 6)
  mesh.name = 'atmos-wheel'
  const dummy = new Object3D()
  for (let i = 0; i < 6; i += 1) {
    const axle = (i % 3) - 1
    const side = i < 3 ? -1 : 1
    dummy.position.set(ROVER.x + axle * 0.38, 0.16, ROVER.z + side * 0.32)
    dummy.rotation.set(0, 0, Math.PI / 2)
    dummy.updateMatrix()
    mesh.setMatrixAt(i, dummy.matrix)
  }
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function addRover(root: Group, kept: Kept) {
  const bodyGeo = new BoxGeometry(1.15, 0.36, 0.72)
  const bodyMat = new MeshBasicMaterial({ color: '#d9d3c6' })
  const body = new Mesh(bodyGeo, bodyMat)
  body.name = 'atmos-rover'
  body.position.set(ROVER.x, 0.42, ROVER.z)
  const cabGeo = new BoxGeometry(0.42, 0.26, 0.4)
  const cabMat = new MeshBasicMaterial({ color: '#efe8da' })
  const cab = new Mesh(cabGeo, cabMat)
  cab.position.set(ROVER.x, 0.7, ROVER.z + 0.08)
  const mastGeo = new BoxGeometry(0.06, 0.55, 0.06)
  const mastMat = new MeshBasicMaterial({ color: '#efe8da' })
  const mast = new Mesh(mastGeo, mastMat)
  mast.position.set(ROVER.x - 0.28, 0.9, ROVER.z)
  addMesh(root, kept, body)
  addMesh(root, kept, cab)
  addMesh(root, kept, mast)
  addWheels(root, kept)
  kept.materials.push(bodyMat, cabMat, mastMat)
}

function devilSpots(count: number, seed: number): Array<[number, number]> {
  return fieldSpots(count, seed, 41)
}

function placeDevils(mesh: InstancedMesh, spots: Array<[number, number]>, seconds: number, height: number, radius: number) {
  const dummy = new Object3D()
  spots.forEach(([x, z], index) => {
    dummy.position.set(x, height * 0.5, z)
    dummy.rotation.set(0, seconds * (1.5 + index * 0.2), 0)
    dummy.scale.set(radius, height, radius)
    dummy.updateMatrix()
    mesh.setMatrixAt(index, dummy.matrix)
  })
  mesh.instanceMatrix.needsUpdate = true
}

function addDevils(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const count = devilCount(resolved.variant)
  if (count < 1) return
  const spots = devilSpots(count, resolved.seed)
  const column = new ConeGeometry(0.45, 1, 5)
  const skirt = new ConeGeometry(0.7, 1, 6)
  const mat = new MeshBasicMaterial({ color: swatch(ROCK, resolved.palette), transparent: true, opacity: 0.94 })
  const skirtMat = new MeshBasicMaterial({ color: '#5c2418', transparent: true, opacity: 0.72 })
  const devils = new InstancedMesh(column, mat, spots.length)
  const skirts = new InstancedMesh(skirt, skirtMat, spots.length)
  devils.name = 'atmos-devil'
  skirts.name = 'atmos-skirt'
  devils.userData.spots = spots
  skirts.userData.spots = spots
  placeDevils(devils, spots, 0, 2.35, 0.55)
  placeDevils(skirts, spots, 0, 1.15, 0.95)
  addMesh(root, kept, devils)
  addMesh(root, kept, skirts)
  kept.materials.push(mat, skirtMat)
}

function addMoons(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const group = new Group()
  group.name = 'atmos-moons'
  const height = moonHeight(resolved.timeOfDay)
  const phobosGeo = new SphereGeometry(0.62, 8, 6)
  const deimosGeo = new SphereGeometry(0.3, 7, 5)
  const phobosMat = new MeshBasicMaterial({ color: '#f6efe2' })
  const deimosMat = new MeshBasicMaterial({ color: swatch(STRATA, resolved.palette) })
  const phobos = new Mesh(phobosGeo, phobosMat)
  const deimos = new Mesh(deimosGeo, deimosMat)
  phobos.name = 'atmos-phobos'
  deimos.name = 'atmos-deimos'
  phobos.position.set(-4.4, height, -11.5)
  deimos.position.set(3.6, height - 1.35, -10.2)
  group.add(phobos)
  group.add(deimos)
  root.add(group)
  kept.geometries.push(phobosGeo, deimosGeo)
  kept.materials.push(phobosMat, deimosMat)
}

function dustPosition(index: number, seed: number): [number, number, number] {
  const x = -7 + hash2(index, 2, seed) * 14
  const y = 0.35 + hash2(index, 3, seed) * 2.6
  const z = -7.5 + hash2(index, 4, seed) * 9
  return [x, y, z]
}

function addDust(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const count = resolved.moteCount
  const geo = new BufferGeometry()
  const positions = new Float32Array(count * 3)
  const seeds = new Float32Array(count)
  for (let i = 0; i < count; i += 1) {
    const [x, y, z] = dustPosition(i, resolved.seed)
    positions[i * 3] = x
    positions[i * 3 + 1] = y
    positions[i * 3 + 2] = z
    seeds[i] = hash2(i, 6, resolved.seed) * Math.PI * 2
  }
  geo.setAttribute('position', new Float32BufferAttribute(positions, 3))
  geo.setAttribute('aSeed', new Float32BufferAttribute(seeds, 1))
  const mat = new ShaderMaterial({
    uniforms: { uTime: { value: 0 }, uColor: { value: new Color(swatch(DUST, resolved.palette)) } },
    vertexShader: DUST_VERTEX,
    fragmentShader: DUST_FRAGMENT,
    transparent: true,
    depthWrite: false,
  })
  const points = new Points(geo, mat)
  points.name = 'atmos-dust'
  addMesh(root, kept, points)
  kept.materials.push(mat)
}

function addSky(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const geo = new SphereGeometry(28, 16, 10)
  const mat = new ShaderMaterial({
    uniforms: {
      uHorizon: { value: new Color(resolved.fogColor) },
      uZenith: { value: new Color(swatch(ZENITH, resolved.palette)) },
    },
    vertexShader: SKY_VERTEX,
    fragmentShader: SKY_FRAGMENT,
    side: BackSide,
  })
  const mesh = new Mesh(geo, mat)
  mesh.name = 'atmos-sky'
  mesh.frustumCulled = false
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function spinNamed(root: Group, name: string, seconds: number, height: number, radius: number) {
  const mesh = root.getObjectByName(name) as InstancedMesh | undefined
  const spots = mesh?.userData.spots as Array<[number, number]> | undefined
  if (!mesh || !spots) return
  placeDevils(mesh, spots, seconds, height, radius)
}

function syncMars(root: Group, seconds: number, resolved: ResolvedAtmos, live?: AtmosSettings) {
  const dust = root.getObjectByName('atmos-dust') as Points | undefined
  if (dust) (dust.material as ShaderMaterial).uniforms.uTime.value = seconds
  const moons = root.getObjectByName('atmos-moons')
  if (moons) moons.rotation.y = seconds * 0.08
  spinNamed(root, 'atmos-devil', seconds, 2.35, 0.55)
  spinNamed(root, 'atmos-skirt', seconds, 1.15, 0.95)
  const fog = (root.parent as { fog?: unknown } | null)?.fog
  if (fog instanceof FogExp2) fog.density = 0.014 + (live ?? resolved).fogDensity * 0.034
}

function liveHandle(root: Group, kept: Kept, resolved: ResolvedAtmos): AtmosHandle {
  return {
    ms: { shafts: 0, dof: 0, grade: 0 },
    passes: () => [],
    sync: (seconds, _camera, _light, _quality, _focus, live) => syncMars(root, seconds, resolved, live),
    dispose: disposeOnce(() => disposeKept(root, kept)),
  }
}

export function buildMars(resolved: ResolvedAtmos, webgl2: boolean): { root: Group; handle: AtmosHandle } {
  if (!webgl2) {
    const flat = flatMars(resolved)
    const handle = idleHandle(flat.root, flat.kept)
    flat.root.userData.atmos = handle
    return { root: flat.root, handle }
  }
  const root = new Group()
  root.name = 'atmos-mars'
  const kept = emptyKept()
  addGround(root, resolved, kept)
  addDunes(root, resolved, kept)
  addRocks(root, resolved, kept)
  addRidge(root, resolved, kept)
  addRover(root, kept)
  addShadow(root, resolved, kept)
  addDevils(root, resolved, kept)
  addMoons(root, resolved, kept)
  addDust(root, resolved, kept)
  addSky(root, resolved, kept)
  const handle = liveHandle(root, kept, resolved)
  root.userData.atmos = handle
  return { root, handle }
}

export const marsSet: AtmosSetDefinition = {
  id: 'atmos-mars',
  titleKey: 'template.atmos-mars-wide.title',
  setting: 'desert',
  seed: 44021,
  subject: CLEARING_SUBJECT,
  subjectYaw: 0.15,
  palettes: MARS_PALETTES,
  times: MARS_TIMES,
  defaults: { timeOfDay: 'noon', fogDensity: 0.36, wind: 0.4, motes: 0.75, palette: 'rust', variant: 3 },
  variant: { labelKey: 'atmos.devils', min: 0, max: 8 },
  low: { shaftSteps: 0, grassBlades: 8, moteCount: 36 },
  high: { shaftSteps: 0, grassBlades: 14, moteCount: 72 },
  templates: [
    { id: 'atmos-mars-wide', camera: 'establishment', eye: WIDE_EYE, look: WIDE_LOOK, fov: 48, duration: 6 },
    { id: 'atmos-mars-low', camera: 'establishment', eye: LOW_EYE, look: LOW_LOOK, fov: 54, duration: 6 },
  ],
  build: buildMars,
  fallback(resolved) {
    const sky = MARS_PALETTES[resolved.palette as keyof typeof MARS_PALETTES]?.fog ?? MARS_PALETTES.rust.fog
    return { sky: hexColor(sky), ground: hexColor(FALLBACK_GROUND[resolved.palette] ?? FALLBACK_GROUND.rust) }
  },
}
