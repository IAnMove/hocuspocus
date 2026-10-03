import {
  BackSide,
  BoxGeometry,
  BufferGeometry,
  Color,
  DoubleSide,
  Float32BufferAttribute,
  FogExp2,
  Group,
  IcosahedronGeometry,
  InstancedMesh,
  Mesh,
  MeshBasicMaterial,
  Object3D,
  Points,
  PointsMaterial,
  RingGeometry,
  ShaderMaterial,
  SphereGeometry,
  Vector3,
  type Material,
  MeshStandardMaterial,
} from 'three'
import type { AtmosHandle } from './clearing.ts'
import type { AtmosSetDefinition } from '../definition.ts'
import type { AtmosSettings, ResolvedAtmos } from '../params.ts'
import { hash2 } from '../noise.ts'
import { CLEARING_SUBJECT, scatter, type Area } from '../layout.ts'

type Kept = { geometries: BufferGeometry[]; materials: Material[] }
type Spot = [number, number]
type Band = 'near' | 'far'
type Rock = { x: number; y: number; z: number; scale: number; rx: number; ry: number; rz: number }

// RingGeometry sits in XY. rotation.x tilts it; DoubleSide keeps a near-edge view.
const PLANET_VERTEX = `
  varying vec3 vN;
  void main() {
    vN = normalize(normal);
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`
const PLANET_FRAGMENT = `
  uniform vec3 uLit;
  uniform vec3 uDark;
  uniform vec3 uBand;
  uniform vec3 uRim;
  uniform vec3 uSun;
  uniform float uEclipse;
  varying vec3 vN;
  void main() {
    vec3 n = normalize(vN);
    float day = clamp(dot(n, normalize(uSun)) * 0.5 + 0.5, 0.0, 1.0);
    float shade = mix(day, day * day * 0.18, uEclipse);
    vec3 color = mix(uDark, uLit, shade);
    float stripe = 0.5 + 0.5 * sin(n.y * 11.0 + n.x * 2.4);
    color = mix(color, uBand, stripe * 0.55);
    float rim = pow(1.0 - clamp(dot(n, vec3(0.0, 0.08, 0.99)), 0.0, 1.0), 2.6);
    color += uRim * rim * (0.28 + uEclipse * 1.05);
    gl_FragColor = vec4(color, 1.0);
  }
`

const LEFT: Area = { x0: -8.2, x1: -2.7, z0: -3.4, z1: 2.6 }
const RIGHT: Area = { x0: 3.35, x1: 8.4, z0: -3.2, z1: 2.6 }
const FAR_LEFT: Area = { x0: -8.4, x1: -3.3, z0: -9.2, z1: -4.6 }
const FAR_RIGHT: Area = { x0: 3.3, x1: 8.4, z0: -9.2, z1: -4.6 }
const HEROES: Rock[] = [
  { x: -3.2, y: 0.78, z: -2.2, scale: 1.12, rx: 0.4, ry: 0.9, rz: 0.25 },
  { x: 3.62, y: 0.9, z: -1.85, scale: 0.78, rx: 0.2, ry: 1.4, rz: 0.55 },
]
const PLANET_AT = [-0.15, 3.45, -13.4] as const
const BODY_SCALE = 3.15
const CRUISE_SUN = [0.62, 0.22, 0.75] as const
const ECLIPSE_SUN = [-0.12, 0.08, -0.99] as const

const PLANET = {
  ice: { lit: '#d7ecff', dark: '#101a2c', band: '#6e9cc4', rim: '#f4fbff' },
  copper: { lit: '#f0b27a', dark: '#2a140c', band: '#c46234', rim: '#ffe0c2' },
} as const
const RING_A: Record<string, string> = { ice: '#f7fbff', copper: '#f6d2b0' }
const RING_B: Record<string, string> = { ice: '#7eafd6', copper: '#c46234' }
const ROCKS: Record<string, readonly string[]> = {
  ice: ['#d5dee8', '#f4f7fb', '#8ea0b4'],
  copper: ['#e0b088', '#f3d2b4', '#a56b45'],
}
const MARK: Record<string, string> = { ice: '#eaf4ff', copper: '#ffd7b0' }
const FALLBACK_GROUND: Record<string, string> = { ice: '#c5d2e0', copper: '#c4895c' }

const SPACE_PALETTES = {
  ice: { fog: '#05070e', ground: '#c5d2e0', accent: '#eaf4ff', sky: ['#05070e', '#020308'] },
  copper: { fog: '#120a07', ground: '#c4895c', accent: '#ffd7b0', sky: ['#120a07', '#1a0c08'] },
} as const

const SPACE_TIMES = {
  cruise: { sun: [-0.38, -0.58, -0.72], sunColor: '#f4f8ff' },
  eclipse: { sun: [-0.22, -0.5, -0.84], sunColor: '#d5e4f4' },
} as const

const WIDE_EYE = [0.22, 1.55, 3.15] as const
const WIDE_LOOK = [0.05, 1.85, -7.5] as const
const LOW_EYE = [0.7, 0.32, 0.85] as const
const LOW_LOOK = [-0.15, 3.05, -11] as const

function emptyKept(): Kept {
  return { geometries: [], materials: [] }
}

function hexColor(color: string): [number, number, number] {
  const n = Number.parseInt(color.slice(1), 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

function swatch(table: Record<string, string>, palette: string): string {
  return table[palette] ?? table.ice
}

function planetLook(palette: string) {
  if (palette === 'copper') return PLANET.copper
  return PLANET.ice
}

function orbitAmount(variant: number | undefined): number {
  const value = typeof variant === 'number' && Number.isFinite(variant) ? variant : 4
  return Math.min(8, Math.max(0, value))
}

function ringTilt(variant: number | undefined): number {
  return 1.48 - orbitAmount(variant) * 0.12
}

function driftSpeed(variant: number | undefined): number {
  return 0.035 + orbitAmount(variant) * 0.07
}

function eclipseAmount(time: string): number {
  return time === 'eclipse' ? 1 : 0
}

function rockHeight(band: Band, index: number, seed: number): number {
  if (band === 'far') return 0.4 + hash2(index, 6, seed) * 1.7
  return 0.32 + hash2(index, 6, seed) * 2.15
}

function rockScale(band: Band, index: number, seed: number): number {
  const spread = hash2(index, 5, seed)
  if (band === 'far') return 0.42 + spread * 0.7
  return 0.2 + spread * 0.42
}

function makeRock(x: number, z: number, index: number, seed: number, band: Band): Rock {
  return {
    x, z,
    y: rockHeight(band, index, seed),
    scale: rockScale(band, index, seed),
    rx: hash2(index, 8, seed) * 3.1,
    ry: hash2(index, 9, seed) * 3.1,
    rz: hash2(index, 10, seed) * 3.1,
  }
}

function appendRocks(rocks: Rock[], spots: Spot[], seed: number, salt: number, band: Band) {
  spots.forEach(([x, z], index) => {
    rocks.push(makeRock(x, z, salt + index, seed, band))
  })
}

function fieldRocks(count: number, seed: number): Rock[] {
  const heroes = HEROES.slice(0, Math.min(HEROES.length, count))
  const rest = Math.max(0, count - heroes.length)
  const near = Math.round(rest * 0.62)
  const left = scatter(Math.ceil(near / 2), seed, 11, [], LEFT, 0.8)
  const right = scatter(Math.floor(near / 2), seed, 23, [], RIGHT, 0.8)
  const farCount = Math.max(0, rest - left.length - right.length)
  const farLeft = scatter(Math.ceil(farCount / 2), seed, 37, [], FAR_LEFT, 1)
  const farRight = scatter(farCount - Math.ceil(farCount / 2), seed, 53, [], FAR_RIGHT, 1)
  const rocks = [...heroes]
  appendRocks(rocks, left, seed, 40, 'near')
  appendRocks(rocks, right, seed, 80, 'near')
  appendRocks(rocks, farLeft, seed, 120, 'far')
  appendRocks(rocks, farRight, seed, 160, 'far')
  return rocks
}

function outward(x: number, z: number): [number, number] {
  const dx = x - CLEARING_SUBJECT[0]
  const dz = z - CLEARING_SUBJECT[2]
  const len = Math.hypot(dx, dz) || 1
  return [dx / len, dz / len]
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

function addDrawn(parent: Group, kept: Kept, mesh: Mesh | InstancedMesh | Points) {
  parent.add(mesh)
  kept.geometries.push(mesh.geometry)
}

function flatRing(resolved: ResolvedAtmos): { root: Group; kept: Kept } {
  const root = new Group()
  root.name = 'atmos-space-ring'
  const kept = emptyKept()
  const geo = new BoxGeometry(2.8, 0.16, 2.8)
  const mat = new MeshBasicMaterial({ color: resolved.stone })
  const mesh = new Mesh(geo, mat)
  mesh.name = 'atmos-pad'
  mesh.position.set(CLEARING_SUBJECT[0], -0.08, CLEARING_SUBJECT[2])
  addDrawn(root, kept, mesh)
  kept.materials.push(mat)
  return { root, kept }
}

function addPad(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const geo = new BoxGeometry(2.8, 0.16, 2.8)
  const mat = new MeshBasicMaterial({ color: resolved.stone })
  const mesh = new Mesh(geo, mat)
  mesh.name = 'atmos-pad'
  mesh.position.set(CLEARING_SUBJECT[0], -0.08, CLEARING_SUBJECT[2])
  addDrawn(root, kept, mesh)
  kept.materials.push(mat)
  const markGeo = new RingGeometry(0.82, 1.08, 40)
  markGeo.rotateX(-Math.PI / 2)
  const markMat = new MeshBasicMaterial({ color: swatch(MARK, resolved.palette), side: DoubleSide })
  const mark = new Mesh(markGeo, markMat)
  mark.name = 'atmos-mark'
  mark.position.set(CLEARING_SUBJECT[0], 0.02, CLEARING_SUBJECT[2])
  addDrawn(root, kept, mark)
  kept.materials.push(markMat)
}

function placeAsteroids(mesh: InstancedMesh, spots: Rock[], seconds: number, speed: number) {
  const dummy = new Object3D()
  const travel = seconds * speed
  spots.forEach((spot, index) => {
    const [ox, oz] = outward(spot.x, spot.z)
    dummy.position.set(spot.x + ox * travel, spot.y, spot.z + oz * travel)
    dummy.rotation.set(spot.rx, spot.ry, spot.rz)
    dummy.scale.setScalar(spot.scale)
    dummy.updateMatrix()
    mesh.setMatrixAt(index, dummy.matrix)
  })
  mesh.instanceMatrix.needsUpdate = true
}

/** Irregular, lumpy asteroids instead of a regular solid. */
function jitterRock(geo: IcosahedronGeometry, seed: number) {
  const pos = geo.getAttribute('position')
  for (let i = 0; i < pos.count; i += 1) {
    const k = 1 + (hash2(Math.round(pos.getX(i) * 40), Math.round(pos.getZ(i) * 40) + Math.round(pos.getY(i) * 13), seed) - 0.5) * 0.5
    pos.setXYZ(i, pos.getX(i) * k, pos.getY(i) * k, pos.getZ(i) * k)
  }
  geo.computeVertexNormals()
}

function addAsteroids(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const spots = fieldRocks(resolved.grassBlades, resolved.seed)
  if (spots.length < 1) return
  const geo = new IcosahedronGeometry(1, 1)
  jitterRock(geo, resolved.seed)
  const mat = new MeshStandardMaterial({ color: 0xffffff, flatShading: true, roughness: 1, emissive: 0x30343c, emissiveIntensity: 0.6 })
  const mesh = new InstancedMesh(geo, mat, spots.length)
  mesh.name = 'atmos-asteroid'
  mesh.frustumCulled = false
  mesh.userData.spots = spots
  const colors = ROCKS[resolved.palette] ?? ROCKS.ice
  const color = new Color()
  spots.forEach((_, index) => {
    color.set(colors[index % colors.length])
    mesh.setColorAt(index, color)
  })
  if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true
  placeAsteroids(mesh, spots, 0, driftSpeed(resolved.variant))
  addDrawn(root, kept, mesh)
  kept.materials.push(mat)
}

function addPlanet(body: Group, resolved: ResolvedAtmos, kept: Kept) {
  const look = planetLook(resolved.palette)
  const geo = new SphereGeometry(1, 28, 18)
  const mat = new ShaderMaterial({
    uniforms: {
      uLit: { value: new Color(look.lit) },
      uDark: { value: new Color(look.dark) },
      uBand: { value: new Color(look.band) },
      uRim: { value: new Color(look.rim) },
      uSun: { value: new Vector3() },
      uEclipse: { value: eclipseAmount(resolved.timeOfDay) },
    },
    vertexShader: PLANET_VERTEX,
    fragmentShader: PLANET_FRAGMENT,
  })
  const sun = resolved.timeOfDay === 'eclipse' ? ECLIPSE_SUN : CRUISE_SUN
  mat.uniforms.uSun.value.set(sun[0], sun[1], sun[2])
  const mesh = new Mesh(geo, mat)
  mesh.name = 'atmos-planet'
  addDrawn(body, kept, mesh)
  kept.materials.push(mat)
}

function ringColor(table: Record<string, string>, palette: string, eclipse: number): Color {
  const color = new Color(swatch(table, palette))
  color.multiplyScalar(1 - eclipse * 0.42)
  return color
}

function addOneRing(parent: Group, kept: Kept, name: string, inner: number, outer: number, color: string) {
  const geo = new RingGeometry(inner, outer, 72)
  const mat = new MeshBasicMaterial({ color, side: DoubleSide })
  const mesh = new Mesh(geo, mat)
  mesh.name = name
  mesh.frustumCulled = false
  parent.add(mesh)
  kept.geometries.push(geo)
  kept.materials.push(mat)
}

function addRings(body: Group, resolved: ResolvedAtmos, kept: Kept) {
  const ring = new Group()
  ring.name = 'atmos-ring'
  ring.frustumCulled = false
  ring.rotation.x = ringTilt(resolved.variant)
  const eclipse = eclipseAmount(resolved.timeOfDay)
  addOneRing(ring, kept, 'atmos-ring-a', 1.34, 1.82, ringColor(RING_A, resolved.palette, eclipse).getStyle())
  addOneRing(ring, kept, 'atmos-ring-b', 1.98, 2.42, ringColor(RING_B, resolved.palette, eclipse).getStyle())
  body.add(ring)
}

function addBody(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const body = new Group()
  body.name = 'atmos-body'
  body.position.set(PLANET_AT[0], PLANET_AT[1], PLANET_AT[2])
  body.scale.setScalar(BODY_SCALE)
  body.frustumCulled = false
  addPlanet(body, resolved, kept)
  addRings(body, resolved, kept)
  root.add(body)
}

function starPosition(index: number, seed: number): [number, number, number] {
  const side = hash2(index, 2, seed) > 0.5 ? 1 : -1
  const x = side * (2.8 + hash2(index, 3, seed) * 16)
  const y = 2.4 + hash2(index, 4, seed) * 14
  const z = -9 - hash2(index, 5, seed) * 20
  return [x, y, z]
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
  const mat = new PointsMaterial({ color: '#f7f4ea', size: 3.8, sizeAttenuation: false })
  const points = new Points(geo, mat)
  points.name = 'atmos-stars'
  points.frustumCulled = false
  addDrawn(root, kept, points)
  kept.materials.push(mat)
}

function addSky(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const geo = new SphereGeometry(46, 16, 12)
  const mat = new MeshBasicMaterial({ color: resolved.fogColor, side: BackSide })
  const mesh = new Mesh(geo, mat)
  mesh.name = 'atmos-sky'
  mesh.frustumCulled = false
  addDrawn(root, kept, mesh)
  kept.materials.push(mat)
}

function tiltRings(root: Group, variant: number | undefined) {
  const ring = root.getObjectByName('atmos-ring')
  if (ring) ring.rotation.x = ringTilt(variant)
}

function driftRocks(root: Group, seconds: number, variant: number | undefined) {
  const mesh = root.getObjectByName('atmos-asteroid') as InstancedMesh | undefined
  const spots = mesh?.userData.spots as Rock[] | undefined
  if (!mesh || !spots) return
  placeAsteroids(mesh, spots, seconds, driftSpeed(variant))
}

function paintPlanet(root: Group, settings: AtmosSettings) {
  const mesh = root.getObjectByName('atmos-planet') as Mesh | undefined
  if (!mesh) return
  const look = planetLook(settings.palette)
  const mat = mesh.material as ShaderMaterial
  mat.uniforms.uLit.value.set(look.lit)
  mat.uniforms.uDark.value.set(look.dark)
  mat.uniforms.uBand.value.set(look.band)
  mat.uniforms.uRim.value.set(look.rim)
  mat.uniforms.uEclipse.value = eclipseAmount(settings.timeOfDay)
  const sun = settings.timeOfDay === 'eclipse' ? ECLIPSE_SUN : CRUISE_SUN
  mat.uniforms.uSun.value.set(sun[0], sun[1], sun[2])
}

function paintOneRing(root: Group, name: string, table: Record<string, string>, settings: AtmosSettings) {
  const mesh = root.getObjectByName(name) as Mesh | undefined
  if (!mesh) return
  const mat = mesh.material as MeshBasicMaterial
  mat.color.copy(ringColor(table, settings.palette, eclipseAmount(settings.timeOfDay)))
}

function paintRings(root: Group, settings: AtmosSettings) {
  paintOneRing(root, 'atmos-ring-a', RING_A, settings)
  paintOneRing(root, 'atmos-ring-b', RING_B, settings)
}

function tuneFog(root: Group, density: number) {
  const fog = (root.parent as { fog?: unknown } | null)?.fog
  if (fog instanceof FogExp2) fog.density = 0.003 + density * 0.01
}

function syncSpace(root: Group, seconds: number, resolved: ResolvedAtmos, live?: AtmosSettings) {
  const settings = live ?? resolved
  tiltRings(root, settings.variant)
  driftRocks(root, seconds, settings.variant)
  paintPlanet(root, settings)
  paintRings(root, settings)
  tuneFog(root, settings.fogDensity)
}

function liveHandle(root: Group, kept: Kept, resolved: ResolvedAtmos): AtmosHandle {
  return {
    ms: { shafts: 0, dof: 0, grade: 0 },
    passes: () => [],
    sync: (seconds, _camera, _light, _quality, _focus, live) => syncSpace(root, seconds, resolved, live),
    dispose: disposeOnce(() => disposeKept(root, kept)),
  }
}

export function buildSpaceRing(resolved: ResolvedAtmos, webgl2: boolean): { root: Group; handle: AtmosHandle } {
  if (!webgl2) {
    const flat = flatRing(resolved)
    const handle = idleHandle(flat.root, flat.kept)
    flat.root.userData.atmos = handle
    return { root: flat.root, handle }
  }
  const root = new Group()
  root.name = 'atmos-space-ring'
  const kept = emptyKept()
  addSky(root, resolved, kept)
  addStars(root, resolved, kept)
  addPad(root, resolved, kept)
  addAsteroids(root, resolved, kept)
  addBody(root, resolved, kept)
  const handle = liveHandle(root, kept, resolved)
  root.userData.atmos = handle
  return { root, handle }
}

export const spaceRingSet: AtmosSetDefinition = {
  id: 'atmos-space-ring',
  titleKey: 'template.atmos-space-ring-wide.title',
  setting: 'space',
  seed: 99017,
  subject: CLEARING_SUBJECT,
  subjectYaw: 0.15,
  palettes: SPACE_PALETTES,
  times: SPACE_TIMES,
  defaults: { timeOfDay: 'cruise', fogDensity: 0.06, wind: 0.2, motes: 0.55, palette: 'ice', variant: 4 },
  variant: { labelKey: 'atmos.orbit', min: 0, max: 8 },
  low: { shaftSteps: 0, grassBlades: 14, moteCount: 40 },
  high: { shaftSteps: 0, grassBlades: 22, moteCount: 72 },
  templates: [
    { id: 'atmos-space-ring-wide', camera: 'establishment', eye: WIDE_EYE, look: WIDE_LOOK, fov: 50, duration: 6 },
    { id: 'atmos-space-ring-low', camera: 'establishment', eye: LOW_EYE, look: LOW_LOOK, fov: 58, duration: 6 },
  ],
  build: buildSpaceRing,
  fallback(resolved) {
    const sky = SPACE_PALETTES[resolved.palette as keyof typeof SPACE_PALETTES]?.fog ?? SPACE_PALETTES.ice.fog
    return { sky: hexColor(sky), ground: hexColor(FALLBACK_GROUND[resolved.palette] ?? FALLBACK_GROUND.ice) }
  },
}
