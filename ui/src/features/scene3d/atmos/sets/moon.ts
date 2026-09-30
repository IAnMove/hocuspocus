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
  PointsMaterial,
  RingGeometry,
  ShaderMaterial,
  SphereGeometry,
  Vector3,
  type BufferAttribute,
  type Material,
} from 'three'
import type { AtmosHandle } from './clearing.ts'
import type { AtmosSetDefinition } from '../definition.ts'
import type { AtmosSettings, ResolvedAtmos } from '../params.ts'
import { hash2 } from '../noise.ts'
import { CLEARING_SUBJECT, scatter, type Area } from '../layout.ts'

type Kept = { geometries: BufferGeometry[]; materials: Material[] }
type Spot = { x: number; z: number; size: number }

const EARTH_VERTEX = `
  varying vec3 vN;
  void main() {
    vN = normalize(position);
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`
const EARTH_FRAGMENT = `
  uniform vec3 uOcean;
  uniform vec3 uLand;
  uniform vec3 uCloud;
  uniform float uTime;
  varying vec3 vN;
  void main() {
    float land = smoothstep(0.05, 0.62, sin(vN.y * 2.4) * 0.55 + sin(vN.x * 1.7 + vN.z * 1.3 + uTime * 0.05));
    vec3 color = mix(uOcean, uLand, land);
    float cloud = smoothstep(0.62, 0.95, sin(vN.x * 3.2 + uTime * 0.2) * 0.45 + vN.y * 0.35);
    gl_FragColor = vec4(mix(color, uCloud, cloud * 0.55), 1.0);
  }
`

const LEFT_FIELD: Area = { x0: -6.5, x1: -1.7, z0: -5.6, z1: 1.5 }
const RIGHT_FIELD: Area = { x0: 2.15, x1: 6.5, z0: -5.6, z1: 1.5 }
const LANDER = { x: -3.55, z: -2.65 }
const EARTH_LOOK = {
  regolith: { ocean: '#2a6fbe', land: '#3f8f45', cloud: '#f4f7fb' },
  basalt: { ocean: '#1c3e86', land: '#8d5a32', cloud: '#d5dbe6' },
} as const
const FALLBACK_GROUND: Record<string, string> = { regolith: '#8d877c', basalt: '#3a3836' }

const MOON_PALETTES = {
  regolith: { fog: '#07080e', ground: '#b7b1a4', accent: '#5e5952', sky: ['#07080e', '#12141c'] },
  basalt: { fog: '#04050a', ground: '#5c5854', accent: '#2a3038', sky: ['#04050a', '#10131a'] },
} as const

const MOON_TIMES = {
  day: { sun: [-0.25, -0.16, -0.92], sunColor: '#fff6ea' },
  earthrise: { sun: [0.22, -0.62, 0.74], sunColor: '#d5e4ff' },
} as const

const WIDE_EYE = [0.15, 1.28, 3.7] as const
const WIDE_LOOK = [0.05, 1.85, -7.2] as const
const LOW_EYE = [1.4, 0.38, 1.85] as const
const LOW_LOOK = [-0.8, 2.15, -8.4] as const

function emptyKept(): Kept {
  return { geometries: [], materials: [] }
}

function hexColor(color: string): [number, number, number] {
  const n = Number.parseInt(color.slice(1), 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

function hexVec(color: string): Color {
  return new Color(color)
}

function printCount(variant: number | undefined): number {
  const value = typeof variant === 'number' && Number.isFinite(variant) ? variant : 18
  return Math.round(Math.min(40, Math.max(8, value)))
}

function earthColors(palette: string) {
  return EARTH_LOOK[palette as keyof typeof EARTH_LOOK] ?? EARTH_LOOK.regolith
}

function earthHeight(time: string): number {
  return time === 'earthrise' ? 2.55 : 5.05
}

function sunAlong(sun: readonly [number, number, number]) {
  const span = Math.hypot(sun[0], sun[2]) || 1
  return { x: sun[0] / span, z: sun[2] / span }
}

function shadowReach(sunY: number): number {
  return 1.15 / Math.max(0.08, -sunY)
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

function addMesh(root: Group, kept: Kept, mesh: Mesh | InstancedMesh | Points) {
  root.add(mesh)
  kept.geometries.push(mesh.geometry)
}

function flatMoon(resolved: ResolvedAtmos): { root: Group; kept: Kept } {
  const root = new Group()
  root.name = 'atmos-moon'
  const kept = emptyKept()
  const geo = new PlaneGeometry(16, 16)
  geo.rotateX(-Math.PI / 2)
  const mat = new MeshBasicMaterial({ color: resolved.stone })
  root.add(new Mesh(geo, mat))
  kept.geometries.push(geo)
  kept.materials.push(mat)
  return { root, kept }
}

function addGround(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const geo = new PlaneGeometry(30, 30, 12, 12)
  geo.rotateX(-Math.PI / 2)
  const pos = geo.attributes.position as BufferAttribute
  for (let i = 0; i < pos.count; i += 1) {
    const x = pos.getX(i)
    const z = pos.getZ(i)
    const dx = x - CLEARING_SUBJECT[0]
    const dz = z - CLEARING_SUBJECT[2]
    if (dx * dx + dz * dz < 2.2) continue
    pos.setY(i, (hash2(Math.round(x * 4), Math.round(z * 4), resolved.seed) - 0.5) * 0.06)
  }
  geo.computeVertexNormals()
  const mat = new MeshBasicMaterial({ color: resolved.stone })
  const mesh = new Mesh(geo, mat)
  mesh.name = 'atmos-ground'
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function craterSpot(index: number, seed: number): Spot {
  const col = index % 3
  const row = Math.floor(index / 3)
  return {
    x: -1.35 + col * 2.35 + (hash2(index, 3, seed) - 0.5) * 0.35,
    z: -2.45 - row * 1.25 + (hash2(index, 4, seed) - 0.5) * 0.2,
    size: 0.55 + hash2(index, 5, seed) * 0.85,
  }
}

function layFlat(matrix: Matrix4, x: number, z: number, scale: number) {
  matrix.makeBasis(new Vector3(1, 0, 0), new Vector3(0, 0, -1), new Vector3(0, 1, 0))
  matrix.scale(new Vector3(scale, scale, 1))
  matrix.elements[12] = x
  matrix.elements[13] = 0.02
  matrix.elements[14] = z
}

function addCraters(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const floors = new RingGeometry(0, 0.82, 8)
  const rims = new RingGeometry(0.72, 1, 8)
  const floorMat = new MeshBasicMaterial({ color: '#2c2926' })
  const rimMat = new MeshBasicMaterial({ color: '#d9d3c6' })
  const floorMesh = new InstancedMesh(floors, floorMat, 9)
  const rimMesh = new InstancedMesh(rims, rimMat, 9)
  floorMesh.name = 'atmos-crater'
  rimMesh.name = 'atmos-rim'
  const matrix = new Matrix4()
  for (let i = 0; i < 9; i += 1) {
    const spot = craterSpot(i, resolved.seed)
    layFlat(matrix, spot.x, spot.z, spot.size)
    floorMesh.setMatrixAt(i, matrix)
    layFlat(matrix, spot.x, spot.z, spot.size)
    rimMesh.setMatrixAt(i, matrix)
  }
  addMesh(root, kept, floorMesh)
  addMesh(root, kept, rimMesh)
  kept.materials.push(floorMat, rimMat)
}

function rockSpots(count: number, seed: number): Array<[number, number]> {
  const half = Math.ceil(count / 2)
  return [
    ...scatter(half, seed, 17, [], LEFT_FIELD, 0.45),
    ...scatter(count - half, seed, 22, [], RIGHT_FIELD, 0.45),
  ]
}

function addRocks(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const geo = new ConeGeometry(0.42, 0.78, 5)
  geo.translate(0, 0.39, 0)
  const mat = new MeshBasicMaterial({ color: '#ffffff' })
  const spots = rockSpots(resolved.grassBlades, resolved.seed)
  const mesh = new InstancedMesh(geo, mat, spots.length)
  mesh.name = 'atmos-rock'
  const dummy = new Object3D()
  spots.forEach(([x, z], index) => {
    const height = 0.55 + hash2(index, 8, resolved.seed) * 0.9
    dummy.position.set(x, 0, z)
    dummy.scale.set(0.7 + hash2(index, 9, resolved.seed) * 0.8, height, 0.7 + hash2(index, 10, resolved.seed) * 0.6)
    dummy.updateMatrix()
    mesh.setMatrixAt(index, dummy.matrix)
    mesh.setColorAt(index, hexVec(resolved.grass).multiplyScalar(0.75 + hash2(index, 11, resolved.seed) * 0.45))
  })
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function shadeMatrix(matrix: Matrix4, x: number, z: number, alongX: number, alongZ: number, length: number, width: number) {
  const side = new Vector3(-alongZ, 0, alongX)
  const along = new Vector3(alongX, 0, alongZ)
  matrix.makeBasis(side, along, new Vector3(0, 1, 0))
  matrix.scale(new Vector3(width, length, 1))
  matrix.elements[12] = x + alongX * length * 0.5
  matrix.elements[13] = 0.025
  matrix.elements[14] = z + alongZ * length * 0.5
}

function casterSpots(root: Group): Spot[] {
  const rocks = root.getObjectByName('atmos-rock') as InstancedMesh | undefined
  const matrix = new Matrix4()
  const spots: Spot[] = []
  if (rocks) {
    for (let i = 0; i < rocks.count; i += 1) {
      rocks.getMatrixAt(i, matrix)
      spots.push({ x: matrix.elements[12], z: matrix.elements[14], size: 0.55 })
    }
  }
  spots.push({ x: LANDER.x, z: LANDER.z, size: 1.15 })
  return spots
}

function addShadows(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const geo = new PlaneGeometry(1, 1)
  const mat = new MeshBasicMaterial({ color: '#161410', transparent: true, opacity: 0.78, depthWrite: false })
  const spots = casterSpots(root)
  const mesh = new InstancedMesh(geo, mat, spots.length)
  mesh.name = 'atmos-shadow'
  const along = sunAlong(resolved.sun)
  const length = shadowReach(resolved.sun[1])
  mesh.userData.reach = length
  const matrix = new Matrix4()
  spots.forEach((spot, index) => {
    shadeMatrix(matrix, spot.x, spot.z, along.x, along.z, length, spot.size)
    mesh.setMatrixAt(index, matrix)
  })
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function addLander(root: Group, kept: Kept) {
  const bodyGeo = new BoxGeometry(0.95, 0.5, 0.95)
  const bodyMat = new MeshBasicMaterial({ color: '#e4dece' })
  const body = new Mesh(bodyGeo, bodyMat)
  body.name = 'atmos-lander'
  body.position.set(LANDER.x, 0.95, LANDER.z)
  addMesh(root, kept, body)
  const legGeo = new BoxGeometry(0.08, 0.72, 0.08)
  const legMat = new MeshBasicMaterial({ color: '#8b857a' })
  const legs = new InstancedMesh(legGeo, legMat, 4)
  legs.name = 'atmos-leg'
  const dummy = new Object3D()
  for (let i = 0; i < 4; i += 1) {
    const side = i < 2 ? -1 : 1
    const fore = i % 2 === 0 ? -1 : 1
    dummy.position.set(LANDER.x + side * 0.5, 0.36, LANDER.z + fore * 0.5)
    dummy.updateMatrix()
    legs.setMatrixAt(i, dummy.matrix)
  }
  const dishGeo = new CylinderGeometry(0.28, 0.34, 0.08, 6)
  const dishMat = new MeshBasicMaterial({ color: '#c5d0dc' })
  const dish = new Mesh(dishGeo, dishMat)
  dish.position.set(LANDER.x, 1.32, LANDER.z)
  addMesh(root, kept, legs)
  addMesh(root, kept, dish)
  kept.materials.push(bodyMat, legMat, dishMat)
}

function printSpot(index: number, count: number): { x: number; z: number } {
  const t = ((index + 1) / (count + 3)) * 0.42
  return {
    x: LANDER.x + (CLEARING_SUBJECT[0] - LANDER.x) * t,
    z: LANDER.z + (CLEARING_SUBJECT[2] - LANDER.z) * t,
  }
}

function addPrints(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const count = printCount(resolved.variant)
  const geo = new PlaneGeometry(1, 1)
  const mat = new MeshBasicMaterial({ color: '#241f1b' })
  const mesh = new InstancedMesh(geo, mat, count)
  mesh.name = 'atmos-print'
  const along = sunAlong([
    CLEARING_SUBJECT[0] - LANDER.x,
    0,
    CLEARING_SUBJECT[2] - LANDER.z,
  ])
  const matrix = new Matrix4()
  for (let i = 0; i < count; i += 1) {
    const spot = printSpot(i, count)
    const side = i % 2 === 0 ? 0.1 : -0.1
    shadeMatrix(matrix, spot.x + along.z * side, spot.z - along.x * side, along.x, along.z, 0.46, 0.2)
    mesh.setMatrixAt(i, matrix)
  }
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function addEarth(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const look = earthColors(resolved.palette)
  const geo = new SphereGeometry(2.9, 18, 12)
  const mat = new ShaderMaterial({
    uniforms: {
      uOcean: { value: hexVec(look.ocean) },
      uLand: { value: hexVec(look.land) },
      uCloud: { value: hexVec(look.cloud) },
      uTime: { value: 0 },
    },
    vertexShader: EARTH_VERTEX,
    fragmentShader: EARTH_FRAGMENT,
  })
  const mesh = new Mesh(geo, mat)
  mesh.name = 'atmos-earth'
  mesh.position.set(-1.6, earthHeight(resolved.timeOfDay), -12.5)
  const glowGeo = new SphereGeometry(3.15, 14, 10)
  const glowMat = new MeshBasicMaterial({ color: look.ocean, transparent: true, opacity: 0.28, depthWrite: false })
  const glow = new Mesh(glowGeo, glowMat)
  glow.name = 'atmos-glow'
  glow.position.copy(mesh.position)
  addMesh(root, kept, mesh)
  addMesh(root, kept, glow)
  kept.materials.push(mat, glowMat)
}

function starPosition(index: number, seed: number): [number, number, number] {
  const yaw = hash2(index, 2, seed) * Math.PI * 2
  const lift = 0.18 + hash2(index, 3, seed) * 0.78
  const radius = 16 + hash2(index, 4, seed) * 3
  const ring = Math.sqrt(Math.max(0, 1 - lift * lift))
  return [Math.cos(yaw) * ring * radius, lift * radius, Math.sin(yaw) * ring * radius - 4]
}

function addStars(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const geo = new BufferGeometry()
  const count = resolved.moteCount
  const positions = new Float32Array(count * 3)
  for (let i = 0; i < count; i += 1) {
    const [x, y, z] = starPosition(i, resolved.seed)
    positions[i * 3] = x
    positions[i * 3 + 1] = y
    positions[i * 3 + 2] = z
  }
  geo.setAttribute('position', new Float32BufferAttribute(positions, 3))
  const mat = new PointsMaterial({ color: '#f7f4ea', size: 2.4, sizeAttenuation: false })
  const points = new Points(geo, mat)
  points.name = 'atmos-stars'
  addMesh(root, kept, points)
  kept.materials.push(mat)
}

function addSky(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const geo = new SphereGeometry(26, 16, 10)
  const mat = new MeshBasicMaterial({ color: resolved.fogColor, side: BackSide })
  const mesh = new Mesh(geo, mat)
  mesh.name = 'atmos-sky'
  mesh.frustumCulled = false
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function turnEarth(root: Group, seconds: number) {
  const earth = root.getObjectByName('atmos-earth') as Mesh | undefined
  const glow = root.getObjectByName('atmos-glow')
  const stars = root.getObjectByName('atmos-stars')
  if (earth) {
    earth.rotation.y = seconds * 0.12
    const mat = earth.material as ShaderMaterial
    mat.uniforms.uTime.value = seconds
  }
  if (glow) glow.rotation.y = seconds * 0.12
  if (stars) stars.rotation.y = seconds * 0.02
}

function tuneFog(root: Group, density: number) {
  const fog = (root.parent as { fog?: unknown } | null)?.fog
  if (fog instanceof FogExp2) fog.density = 0.014 + density * 0.034
}

function syncMoon(root: Group, seconds: number, resolved: ResolvedAtmos, live?: AtmosSettings) {
  turnEarth(root, seconds)
  tuneFog(root, (live ?? resolved).fogDensity)
}

function liveHandle(root: Group, kept: Kept, resolved: ResolvedAtmos): AtmosHandle {
  return {
    ms: { shafts: 0, dof: 0, grade: 0 },
    passes: () => [],
    sync: (seconds, _camera, _light, _quality, _focus, live) => syncMoon(root, seconds, resolved, live),
    dispose: disposeOnce(() => disposeKept(root, kept)),
  }
}

export function buildMoon(resolved: ResolvedAtmos, webgl2: boolean): { root: Group; handle: AtmosHandle } {
  if (!webgl2) {
    const flat = flatMoon(resolved)
    const handle = idleHandle(flat.root, flat.kept)
    flat.root.userData.atmos = handle
    return { root: flat.root, handle }
  }
  const root = new Group()
  root.name = 'atmos-moon'
  const kept = emptyKept()
  addGround(root, resolved, kept)
  addCraters(root, resolved, kept)
  addRocks(root, resolved, kept)
  addLander(root, kept)
  addShadows(root, resolved, kept)
  addPrints(root, resolved, kept)
  addEarth(root, resolved, kept)
  addStars(root, resolved, kept)
  addSky(root, resolved, kept)
  const handle = liveHandle(root, kept, resolved)
  root.userData.atmos = handle
  return { root, handle }
}

export const moonSet: AtmosSetDefinition = {
  id: 'atmos-moon',
  titleKey: 'template.atmos-moon-wide.title',
  setting: 'moon',
  seed: 31017,
  subject: CLEARING_SUBJECT,
  subjectYaw: 0.15,
  palettes: MOON_PALETTES,
  times: MOON_TIMES,
  defaults: { timeOfDay: 'day', fogDensity: 0.04, wind: 0.05, motes: 0.7, palette: 'regolith', variant: 18 },
  variant: { labelKey: 'atmos.prints', min: 8, max: 40 },
  low: { shaftSteps: 0, grassBlades: 10, moteCount: 48 },
  high: { shaftSteps: 0, grassBlades: 18, moteCount: 96 },
  templates: [
    { id: 'atmos-moon-wide', camera: 'establishment', eye: WIDE_EYE, look: WIDE_LOOK, fov: 48, duration: 6 },
    { id: 'atmos-moon-low', camera: 'establishment', eye: LOW_EYE, look: LOW_LOOK, fov: 52, duration: 6 },
  ],
  build: buildMoon,
  fallback(resolved) {
    const sky = MOON_PALETTES[resolved.palette as keyof typeof MOON_PALETTES]?.fog ?? MOON_PALETTES.regolith.fog
    return { sky: hexColor(sky), ground: hexColor(FALLBACK_GROUND[resolved.palette] ?? FALLBACK_GROUND.regolith) }
  },
}
