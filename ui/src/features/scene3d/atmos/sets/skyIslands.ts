import {
  BackSide,
  BufferGeometry,
  Color,
  ConeGeometry,
  CylinderGeometry,
  DoubleSide,
  FogExp2,
  Group,
  InstancedMesh,
  Mesh,
  MeshBasicMaterial,
  Object3D,
  OctahedronGeometry,
  PlaneGeometry,
  ShaderMaterial,
  SphereGeometry,
  type Material,
} from 'three'
import type { AtmosHandle } from './clearing.ts'
import type { AtmosSetDefinition } from '../definition.ts'
import type { AtmosSettings, ResolvedAtmos } from '../params.ts'
import { hash2 } from '../noise.ts'
import { CLEARING_SUBJECT, scatter, type Area } from '../layout.ts'

type Kept = { geometries: BufferGeometry[]; materials: Material[] }
type Spot3 = [number, number, number]
type Cloud = [number, number, number, number, number, number]
type Isle = [number, number, number, number, number]

// PlaneGeometry faces +z. rotateX(-PI/2) lays the checker on xz with a +y normal.
// Coin cylinders are turned so their faces point along local ±z; rotation.y spins each one in place.
const CHECK_VERTEX = `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`
const CHECK_INSTANCE_VERTEX = `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * instanceMatrix * vec4(position, 1.0);
  }
`
const CHECK_FRAGMENT = `
  uniform vec3 uA;
  uniform vec3 uB;
  uniform float uCells;
  varying vec2 vUv;
  void main() {
    float cx = floor(vUv.x * uCells);
    float cz = floor(vUv.y * uCells);
    gl_FragColor = vec4(mix(uA, uB, mod(cx + cz, 2.0)), 1.0);
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
    gl_FragColor = vec4(mix(uHorizon, uZenith, smoothstep(-0.45, 0.05, vH)), 1.0);
  }
`

// Main top covers the open circle (r 1.4 at the subject) and the lane
// (x -1.05..1.7, z -1.15..3.5). World extent is center ± half size.
const MAIN = { x: 0.5, z: 0.8, w: 4.7, d: 6.7 }
const ISLES: Isle[] = [
  [-4.6, 0.15, -3.6, 2.4, 1.8],
  [5.0, 0.25, -4.2, 2.6, 1.9],
  [0.2, 0.45, -7.4, 3.0, 2.0],
  [-3.4, 0.85, -6.2, 2.0, 1.5],
]
const LEFT: Area = { x0: -1.75, x1: -1.15, z0: -2.35, z1: -1.3 }
const RIGHT: Area = { x0: 2.22, x1: 2.75, z0: -2.35, z1: -1.3 }
const FAR: Area = { x0: -0.8, x1: 2.0, z0: -2.48, z1: -2.12 }
const CLOUDS: Cloud[] = [
  [-5.2, 4.6, -5.4, 2.2, 0.9, 1.5],
  [-4.0, 4.9, -4.6, 1.4, 0.65, 1.0],
  [-6.0, 5.2, -6.8, 1.5, 0.7, 1.1],
  [4.8, 4.7, -5.8, 2.1, 0.85, 1.4],
  [6.0, 5.0, -4.8, 1.4, 0.6, 1.0],
  [3.6, 5.3, -7.2, 1.6, 0.7, 1.1],
  [-1.6, 5.4, -8.6, 2.4, 0.95, 1.6],
  [0.6, 5.7, -9.4, 1.6, 0.7, 1.1],
  [2.0, 5.1, -7.8, 1.3, 0.55, 0.9],
  [-3.2, 5.8, -10.2, 2.0, 0.8, 1.4],
  [-4.4, 6.0, -11.0, 1.3, 0.55, 0.9],
  [3.4, 5.9, -10.6, 1.8, 0.75, 1.2],
  [1.2, 4.4, -4.2, 1.5, 0.6, 1.0],
  [-2.4, 4.5, -5.0, 1.7, 0.7, 1.2],
  [5.4, 5.6, -8.4, 1.5, 0.65, 1.0],
  [-6.4, 4.4, -8.0, 1.8, 0.75, 1.2],
  [0.0, 6.1, -12.0, 2.2, 0.85, 1.5],
  [-1.0, 4.8, -6.4, 1.2, 0.5, 0.85],
]

const ISLAND_PALETTES = {
  peach: { fog: '#ffc49a', ground: '#a86b3c', accent: '#ffd84a', sky: ['#ffc49a', '#16357a'] },
  mint: { fog: '#bff8e4', ground: '#6d8f62', accent: '#7ddec0', sky: ['#bff8e4', '#0e4a72'] },
} as const

const ISLAND_TIMES = {
  clear: { sun: [0.18, -0.9, -0.38], sunColor: '#fff8ef' },
  pink: { sun: [-0.12, -0.88, -0.36], sunColor: '#ffe0f4' },
} as const

const WIDE_EYE = [0.55, 2.45, 5.9] as const
const WIDE_LOOK = [0.4, 1.05, -2.8] as const
const LOW_EYE = [0.72, 1.25, 2.35] as const
const LOW_LOOK = [0.35, 0.72, -6.2] as const

function emptyKept(): Kept {
  return { geometries: [], materials: [] }
}

function hexColor(color: string): [number, number, number] {
  const n = Number.parseInt(color.slice(1), 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

function checkerColors(palette: string): [string, string] {
  if (palette === 'mint') return ['#14956e', '#f4fff8']
  return ['#e86a22', '#ffe6b5']
}

function rockColor(palette: string): string {
  if (palette === 'mint') return '#6d8f62'
  return '#a86b3c'
}

function skyLook(palette: string, time: string): { horizon: string; zenith: string } {
  if (time === 'pink') return { horizon: '#ffb3d8', zenith: '#3a1454' }
  if (palette === 'mint') return { horizon: '#bff8e4', zenith: '#0e4a72' }
  return { horizon: '#ffc49a', zenith: '#16357a' }
}

function spinSpeed(variant: number | undefined): number {
  const value = typeof variant === 'number' && Number.isFinite(variant) ? variant : 5
  return Math.min(8, Math.max(0, value)) * 1.25
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

function checkerMaterial(palette: string, cells: number, instanced: boolean): ShaderMaterial {
  const [a, b] = checkerColors(palette)
  return new ShaderMaterial({
    uniforms: {
      uA: { value: new Color(a) },
      uB: { value: new Color(b) },
      uCells: { value: cells },
    },
    vertexShader: instanced ? CHECK_INSTANCE_VERTEX : CHECK_VERTEX,
    fragmentShader: CHECK_FRAGMENT,
    side: DoubleSide,
  })
}

function paintChecker(material: Material | Material[] | undefined, palette: string) {
  if (!(material instanceof ShaderMaterial)) return
  const [a, b] = checkerColors(palette)
  material.uniforms.uA.value.set(a)
  material.uniforms.uB.value.set(b)
}

function flatIslands(resolved: ResolvedAtmos): { root: Group; kept: Kept } {
  const root = new Group()
  root.name = 'atmos-sky-islands'
  const kept = emptyKept()
  const geo = new PlaneGeometry(16, 16)
  geo.rotateX(-Math.PI / 2)
  const mat = new MeshBasicMaterial({ color: resolved.stone, fog: false })
  const mesh = new Mesh(geo, mat)
  mesh.name = 'atmos-sky-islands'
  root.add(mesh)
  kept.geometries.push(geo)
  kept.materials.push(mat)
  return { root, kept }
}

function addMainIsland(root: Group, kept: Kept, palette: string) {
  const geo = new PlaneGeometry(MAIN.w, MAIN.d)
  geo.rotateX(-Math.PI / 2)
  const mat = checkerMaterial(palette, 6, false)
  const mesh = new Mesh(geo, mat)
  mesh.name = 'atmos-island'
  mesh.position.set(MAIN.x, 0, MAIN.z)
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function addMainCliff(root: Group, kept: Kept, palette: string) {
  const geo = new ConeGeometry(0.5, 1, 6)
  geo.rotateX(Math.PI)
  const mat = new MeshBasicMaterial({ color: rockColor(palette), fog: false })
  const mesh = new Mesh(geo, mat)
  mesh.name = 'atmos-cliff'
  const height = 1.8
  mesh.position.set(MAIN.x, -0.08 - height * 0.5, MAIN.z)
  mesh.scale.set(MAIN.w * 0.92, height, MAIN.d * 0.92)
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function placeIsles(tops: InstancedMesh, rocks: InstancedMesh) {
  const dummy = new Object3D()
  const height = 0.55
  ISLES.forEach(([x, y, z, sx, sz], index) => {
    dummy.position.set(x, y, z)
    dummy.rotation.set(0, 0, 0)
    dummy.scale.set(sx, 1, sz)
    dummy.updateMatrix()
    tops.setMatrixAt(index, dummy.matrix)
    dummy.position.set(x, y - 0.06 - height * 0.5, z)
    dummy.scale.set(sx * 0.92, height, sz * 0.92)
    dummy.updateMatrix()
    rocks.setMatrixAt(index, dummy.matrix)
  })
  tops.instanceMatrix.needsUpdate = true
  rocks.instanceMatrix.needsUpdate = true
}

function addIsles(root: Group, kept: Kept, palette: string) {
  const topGeo = new PlaneGeometry(1, 1)
  topGeo.rotateX(-Math.PI / 2)
  const topMat = checkerMaterial(palette, 4, true)
  const tops = new InstancedMesh(topGeo, topMat, ISLES.length)
  tops.name = 'atmos-isle'
  const rockGeo = new ConeGeometry(0.5, 1, 6)
  rockGeo.rotateX(Math.PI)
  const rockMat = new MeshBasicMaterial({ color: rockColor(palette), fog: false })
  const rocks = new InstancedMesh(rockGeo, rockMat, ISLES.length)
  rocks.name = 'atmos-isle-rock'
  placeIsles(tops, rocks)
  addMesh(root, kept, tops)
  addMesh(root, kept, rocks)
  kept.materials.push(topMat, rockMat)
}

function coinSpots(count: number, seed: number): Spot3[] {
  const third = Math.ceil(count / 3)
  const left = scatter(third, seed, 3, [], LEFT, 0.2)
  const right = scatter(third, seed, 9, [], RIGHT, 0.2)
  const far = scatter(Math.max(0, count - left.length - right.length), seed, 15, [], FAR, 0.2)
  return [...left, ...right, ...far].map(([x, z], index) => [x, 0.55 + hash2(index, 4, seed) * 0.25, z])
}

function spinCoin(mesh: Object3D, seconds: number, speed: number) {
  mesh.rotation.x = 0
  mesh.rotation.z = 0
  mesh.rotation.y = seconds * speed
}

function placeCoins(mesh: InstancedMesh, spots: Spot3[], seconds: number, speed: number) {
  const dummy = new Object3D()
  spots.forEach(([x, y, z], index) => {
    dummy.position.set(x, y, z)
    dummy.scale.set(1, 1, 1)
    spinCoin(dummy, seconds, speed)
    dummy.rotation.y += index * 0.9
    dummy.updateMatrix()
    mesh.setMatrixAt(index, dummy.matrix)
  })
  mesh.instanceMatrix.needsUpdate = true
}

const COIN_VERTEX = `
  varying vec3 vLocal;
  void main() {
    vLocal = position;
    gl_Position = projectionMatrix * modelViewMatrix * instanceMatrix * vec4(position, 1.0);
  }
`
const COIN_FRAGMENT = `
  varying vec3 vLocal;
  void main() {
    float rim = smoothstep(0.09, 0.16, length(vLocal.xy));
    gl_FragColor = vec4(mix(vec3(1.0, 0.95, 0.42), vec3(0.78, 0.36, 0.04), rim), 1.0);
  }
`

function addCoins(root: Group, kept: Kept, spots: Spot3[], speed: number) {
  if (spots.length < 1) return
  const geo = new CylinderGeometry(0.16, 0.16, 0.035, 16)
  geo.rotateX(Math.PI / 2)
  const mat = new ShaderMaterial({ vertexShader: COIN_VERTEX, fragmentShader: COIN_FRAGMENT, side: DoubleSide })
  const mesh = new InstancedMesh(geo, mat, spots.length)
  mesh.name = 'atmos-coin'
  mesh.userData.spots = spots
  placeCoins(mesh, spots, 0, speed)
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function placeClouds(mesh: InstancedMesh) {
  const dummy = new Object3D()
  const color = new Color()
  CLOUDS.forEach(([x, y, z, sx, sy, sz], index) => {
    dummy.position.set(x, y - 0.35, z)
    dummy.rotation.set(0, index * 0.45, 0)
    dummy.scale.set(sx, sy, sz)
    dummy.updateMatrix()
    mesh.setMatrixAt(index, dummy.matrix)
    color.set(index % 2 === 0 ? '#ffffff' : '#d7e7fb')
    mesh.setColorAt(index, color)
  })
  mesh.instanceMatrix.needsUpdate = true
  if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true
}

function addClouds(root: Group, kept: Kept) {
  const geo = new OctahedronGeometry(1, 0)
  const mat = new MeshBasicMaterial({ color: '#ffffff', fog: false })
  const mesh = new InstancedMesh(geo, mat, CLOUDS.length)
  mesh.name = 'atmos-cloud'
  placeClouds(mesh)
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function starSpots(count: number, seed: number): Spot3[] {
  const spots: Spot3[] = []
  let n = 0
  while (spots.length < count && n < count * 8) {
    const yaw = -1.05 + hash2(n, 1, seed) * 2.1
    const ring = 16 + hash2(n, 2, seed) * 10
    const y = 1.85 + hash2(n, 3, seed) * 0.85
    spots.push([Math.sin(yaw) * ring, y, -Math.abs(Math.cos(yaw)) * ring])
    n += 1
  }
  return spots
}

function placeStars(mesh: InstancedMesh, spots: Spot3[]) {
  const dummy = new Object3D()
  spots.forEach(([x, y, z], index) => {
    dummy.position.set(x, y, z)
    dummy.rotation.set(0, 0, 0)
    dummy.scale.setScalar(0.22 + (index % 5) * 0.06)
    dummy.updateMatrix()
    mesh.setMatrixAt(index, dummy.matrix)
  })
  mesh.instanceMatrix.needsUpdate = true
}

function addStars(root: Group, kept: Kept, spots: Spot3[]) {
  if (spots.length < 1) return
  const geo = new OctahedronGeometry(1, 0)
  const mat = new MeshBasicMaterial({ color: '#ffe56a', fog: false })
  const mesh = new InstancedMesh(geo, mat, spots.length)
  mesh.name = 'atmos-star'
  mesh.frustumCulled = false
  placeStars(mesh, spots)
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function addSky(root: Group, kept: Kept, palette: string, time: string) {
  const look = skyLook(palette, time)
  const geo = new SphereGeometry(80, 16, 12)
  const mat = new ShaderMaterial({
    uniforms: {
      uHorizon: { value: new Color(look.horizon) },
      uZenith: { value: new Color(look.zenith) },
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

function paintRocks(root: Group, palette: string) {
  for (const name of ['atmos-cliff', 'atmos-isle-rock']) {
    const mesh = root.getObjectByName(name) as Mesh | undefined
    const material = mesh?.material
    if (material instanceof MeshBasicMaterial) material.color.set(rockColor(palette))
  }
}

function paintSky(root: Group, look: { horizon: string; zenith: string }) {
  const sky = root.getObjectByName('atmos-sky') as Mesh | undefined
  const material = sky?.material
  if (!(material instanceof ShaderMaterial)) return
  material.uniforms.uHorizon.value.set(look.horizon)
  material.uniforms.uZenith.value.set(look.zenith)
}

function paintFog(root: Group, horizon: string, density: number) {
  const scene = root.parent as { fog?: unknown; background?: unknown } | null
  if (!scene) return
  if (scene.fog instanceof FogExp2) {
    scene.fog.color.set(horizon)
    scene.fog.density = 0.004 + density * 0.012
  }
  if (scene.background instanceof Color) scene.background.set(horizon)
}

function namedMaterial(root: Group, name: string): Material | Material[] | undefined {
  const mesh = root.getObjectByName(name) as Mesh | undefined
  return mesh?.material
}

function syncIslands(root: Group, seconds: number, resolved: ResolvedAtmos, live?: AtmosSettings) {
  const settings = live ?? resolved
  const look = skyLook(settings.palette, settings.timeOfDay)
  paintChecker(namedMaterial(root, 'atmos-island'), settings.palette)
  paintChecker(namedMaterial(root, 'atmos-isle'), settings.palette)
  paintRocks(root, settings.palette)
  paintSky(root, look)
  paintFog(root, look.horizon, settings.fogDensity)
  const coins = root.getObjectByName('atmos-coin') as InstancedMesh | undefined
  const spots = coins?.userData.spots as Spot3[] | undefined
  if (coins && spots) placeCoins(coins, spots, seconds, spinSpeed(settings.variant))
}

function liveHandle(root: Group, kept: Kept, resolved: ResolvedAtmos): AtmosHandle {
  return {
    ms: { shafts: 0, dof: 0, grade: 0 },
    passes: () => [],
    sync: (seconds, _camera, _light, _quality, _focus, live) => syncIslands(root, seconds, resolved, live),
    dispose: disposeOnce(() => disposeKept(root, kept)),
  }
}

export function buildSkyIslands(resolved: ResolvedAtmos, webgl2: boolean): { root: Group; handle: AtmosHandle } {
  if (!webgl2) {
    const flat = flatIslands(resolved)
    const handle = idleHandle(flat.root, flat.kept)
    flat.root.userData.atmos = handle
    return { root: flat.root, handle }
  }
  const root = new Group()
  root.name = 'atmos-sky-islands'
  const kept = emptyKept()
  addMainIsland(root, kept, resolved.palette)
  addMainCliff(root, kept, resolved.palette)
  addIsles(root, kept, resolved.palette)
  addCoins(root, kept, coinSpots(resolved.grassBlades, resolved.seed), spinSpeed(resolved.variant))
  addClouds(root, kept)
  addStars(root, kept, starSpots(resolved.moteCount, resolved.seed))
  addSky(root, kept, resolved.palette, resolved.timeOfDay)
  const handle = liveHandle(root, kept, resolved)
  root.userData.atmos = handle
  return { root, handle }
}

export const skyIslandsSet: AtmosSetDefinition = {
  id: 'atmos-sky-islands',
  titleKey: 'template.atmos-sky-islands-wide.title',
  setting: 'islands',
  seed: 95017,
  subject: CLEARING_SUBJECT,
  subjectYaw: 0.15,
  palettes: ISLAND_PALETTES,
  times: ISLAND_TIMES,
  defaults: { timeOfDay: 'clear', fogDensity: 0.08, wind: 0.22, motes: 0.55, palette: 'peach', variant: 5 },
  variant: { labelKey: 'atmos.spin', min: 0, max: 8 },
  low: { shaftSteps: 0, grassBlades: 8, moteCount: 22 },
  high: { shaftSteps: 0, grassBlades: 12, moteCount: 36 },
  templates: [
    { id: 'atmos-sky-islands-wide', camera: 'establishment', eye: WIDE_EYE, look: WIDE_LOOK, fov: 52, duration: 6 },
    { id: 'atmos-sky-islands-low', camera: 'establishment', eye: LOW_EYE, look: LOW_LOOK, fov: 50, duration: 6 },
  ],
  build: buildSkyIslands,
  fallback(resolved) {
    const sky = ISLAND_PALETTES[resolved.palette as keyof typeof ISLAND_PALETTES]?.fog ?? ISLAND_PALETTES.peach.fog
    const ground = ISLAND_PALETTES[resolved.palette as keyof typeof ISLAND_PALETTES]?.ground ?? ISLAND_PALETTES.peach.ground
    return { sky: hexColor(sky), ground: hexColor(ground) }
  },
}
