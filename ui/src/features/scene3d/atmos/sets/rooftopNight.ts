import {
  BackSide,
  BoxGeometry,
  BufferGeometry,
  Color,
  CylinderGeometry,
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
  MeshStandardMaterial,
  type Texture,
} from 'three'
import type { AtmosHandle } from './clearing.ts'
import type { AtmosSetDefinition } from '../definition.ts'
import type { AtmosSettings, ResolvedAtmos } from '../params.ts'
import { CLEARING_SUBJECT } from '../layout.ts'
import { composeGeometry, skylineLayers, type Piece } from './kit.ts'

type Kept = { geometries: BufferGeometry[]; materials: Material[]; textures: Texture[] }
type Tower = { x: number; z: number; w: number; d: number; h: number }
type BoxSpot = { x: number; y: number; z: number; sx: number; sy: number; sz: number; yaw: number }
type Win = [number, number, number]
type Aerial = [number, number, number]

// PlaneGeometry faces +z. rotateX(-PI/2) lays the roof on y=0 so the figure stands on it.
const ROOF_VERTEX = `
  varying float vX;
  varying float vZ;
  void main() {
    vX = position.x;
    vZ = position.z;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`
const ROOF_FRAGMENT = `
  uniform vec3 uRoof;
  uniform vec3 uSpill;
  varying float vX;
  varying float vZ;
  void main() {
    float open = smoothstep(4.8, 0.2, abs(vX - 0.72));
    open *= smoothstep(6.5, 0.15, abs(vZ + 0.55));
    float spill = smoothstep(1.2, -7.2, vZ);
    vec3 color = mix(uRoof * 0.86, uRoof, open);
    color = mix(color, uSpill, spill * 0.42);
    gl_FragColor = vec4(color, 1.0);
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
    gl_FragColor = vec4(mix(uHorizon, uZenith, smoothstep(-0.04, 0.62, vH)), 1.0);
  }
`

const TOWERS: Tower[] = [
  { x: -8.6, z: -12.4, w: 2.7, d: 2.4, h: 7.4 },
  { x: -5.2, z: -11.5, w: 3.2, d: 2.6, h: 10.6 },
  { x: -1.7, z: -12.8, w: 2.4, d: 2.2, h: 6.4 },
  { x: 1.8, z: -11.3, w: 3.5, d: 2.8, h: 13.2 },
  { x: 5.4, z: -12.2, w: 2.8, d: 2.4, h: 8.8 },
  { x: 8.7, z: -11.7, w: 2.5, d: 2.3, h: 10.2 },
  { x: -3.4, z: -16.2, w: 3.6, d: 2.8, h: 15.4 },
  { x: 4.2, z: -16.6, w: 3.1, d: 2.6, h: 12.4 },
]

const PARAPET: BoxSpot[] = [
  { x: -8.8, y: 0.46, z: -5.0, sx: 0.32, sy: 0.92, sz: 5.2, yaw: 0 },
  { x: 8.8, y: 0.46, z: -5.0, sx: 0.32, sy: 0.92, sz: 5.2, yaw: 0 },
  { x: 0, y: 0.46, z: -7.55, sx: 17.3, sy: 0.92, sz: 0.32, yaw: 0 },
]

const VENTS: BoxSpot[] = [
  { x: -3.5, y: 0.38, z: -4.15, sx: 1.15, sy: 0.76, sz: 0.82, yaw: 0.18 },
  { x: 3.7, y: 0.42, z: -3.55, sx: 0.95, sy: 0.84, sz: 1.15, yaw: -0.22 },
  { x: -4.7, y: 0.3, z: 1.55, sx: 0.85, sy: 0.6, sz: 0.78, yaw: 0.35 },
  { x: 4.6, y: 0.34, z: -5.45, sx: 1.25, sy: 0.68, sz: 0.72, yaw: 0.12 },
]

const AERIALS: Aerial[] = [
  [-2.9, -5.55, 3.6],
  [3.35, -5.15, 4.3],
  [-6.9, -6.55, 2.7],
  [6.5, 1.7, 2.5],
]

const WINDOW: Record<string, string> = { sodium: '#ffd27a', indigo: '#9ec0ff' }
const SPILL: Record<string, string> = { sodium: '#ffb15a', indigo: '#7aa2ff' }
const TOWER_COLOR: Record<string, string> = { sodium: '#1a1416', indigo: '#121820' }
const RIM: Record<string, string> = { sodium: '#2a2624', indigo: '#222a34' }
const VENT_COLOR: Record<string, string> = { sodium: '#3a342e', indigo: '#2e3642' }
const AERIAL_COLOR: Record<string, string> = { sodium: '#c8c2b8', indigo: '#d2d8e2' }
const CITY: Record<string, string> = { sodium: '#100e10', indigo: '#0c1016' }
const ROOF_COLOR: Record<string, string> = { sodium: '#6a6258', indigo: '#4a5568' }
const FALLBACK_GROUND: Record<string, string> = { sodium: '#4a453e', indigo: '#3c4452' }

const ROOF_PALETTES = {
  sodium: { fog: '#3a261c', ground: '#4a453e', accent: '#ffd27a', sky: ['#3a261c', '#100c14'] },
  indigo: { fog: '#1c2c4e', ground: '#3c4452', accent: '#9ec0ff', sky: ['#1c2c4e', '#101828'] },
} as const

const ROOF_TIMES = {
  night: { sun: [0.12, -0.96, -0.18], sunColor: '#ffe0b8' },
  late: { sun: [0.46, -0.58, -0.24], sunColor: '#c9d6ff' },
} as const

const HORIZON: Record<string, string> = {
  sodium: ROOF_PALETTES.sodium.fog,
  indigo: ROOF_PALETTES.indigo.fog,
}

const WIDE_EYE = [0.2, 1.65, 4.6] as const
const WIDE_LOOK = [0.45, 2.1, -11] as const
const LOW_EYE = [0.85, 0.55, 2.4] as const
const LOW_LOOK = [-0.2, 2.4, -11] as const

function emptyKept(): Kept {
  return { geometries: [], materials: [], textures: [] }
}

function hexColor(color: string): [number, number, number] {
  const n = Number.parseInt(color.slice(1), 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

function swatch(table: Record<string, string>, palette: string): string {
  return table[palette] ?? table.sodium
}

function skylineAmount(variant: number | undefined): number {
  const value = typeof variant === 'number' && Number.isFinite(variant) ? variant : 5
  return Math.min(8, Math.max(0, value))
}

function zenithColor(time: string): string {
  return time === 'late' ? '#243456' : '#100c14'
}

function windowOn(index: number, skyline: number): boolean {
  return index % 9 < skyline + 1
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

function addMesh(root: Group, kept: Kept, mesh: Mesh | InstancedMesh) {
  root.add(mesh)
  kept.geometries.push(mesh.geometry)
}

function flatRoof(resolved: ResolvedAtmos): { root: Group; kept: Kept } {
  const root = new Group()
  root.name = 'atmos-rooftop-night'
  const kept = emptyKept()
  const geo = new PlaneGeometry(16, 16)
  geo.rotateX(-Math.PI / 2)
  const mat = new MeshBasicMaterial({ color: resolved.stone })
  root.add(new Mesh(geo, mat))
  kept.geometries.push(geo)
  kept.materials.push(mat)
  return { root, kept }
}

function placeBoxes(mesh: InstancedMesh, spots: readonly BoxSpot[]) {
  const dummy = new Object3D()
  spots.forEach((spot, index) => {
    dummy.position.set(spot.x, spot.y, spot.z)
    dummy.rotation.set(0, spot.yaw, 0)
    dummy.scale.set(spot.sx, spot.sy, spot.sz)
    dummy.updateMatrix()
    mesh.setMatrixAt(index, dummy.matrix)
  })
  mesh.instanceMatrix.needsUpdate = true
}

function addBoxes(root: Group, kept: Kept, name: string, spots: readonly BoxSpot[], color: string) {
  if (spots.length < 1) return
  const geo = new BoxGeometry(1, 1, 1)
  const mat = new MeshBasicMaterial({ color })
  const mesh = new InstancedMesh(geo, mat, spots.length)
  mesh.name = name
  placeBoxes(mesh, spots)
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function towerSpots(count: number): BoxSpot[] {
  return TOWERS.slice(0, count).map(tower => ({
    x: tower.x,
    y: tower.h * 0.5,
    z: tower.z,
    sx: tower.w,
    sy: tower.h,
    sz: tower.d,
    yaw: 0,
  }))
}

function pushTowerWindows(spots: Win[], tower: Tower, cols: number) {
  const front = tower.z + tower.d * 0.5 + 0.1
  const rows = Math.floor((tower.h - 1.7) / 1.02)
  for (let row = 0; row < rows; row += 1) {
    for (let col = 0; col < cols; col += 1) {
      const x = tower.x - tower.w * 0.5 + (col + 0.5) * (tower.w / cols)
      spots.push([x, 1.25 + row * 1.02, front])
    }
  }
}

function windowSpots(count: number, cols: number): Win[] {
  const spots: Win[] = []
  const used = Math.max(0, Math.min(count, TOWERS.length))
  for (let index = 0; index < used; index += 1) pushTowerWindows(spots, TOWERS[index], cols)
  return spots
}

function paintTowers(mesh: InstancedMesh, palette: string) {
  const color = new Color(swatch(TOWER_COLOR, palette))
  const tint = new Color()
  for (let index = 0; index < mesh.count; index += 1) {
    tint.copy(color)
    tint.multiplyScalar(0.78 + (index % 3) * 0.14)
    mesh.setColorAt(index, tint)
  }
  if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true
}

function paintWindows(mesh: InstancedMesh, spots: readonly Win[], palette: string, skyline: number) {
  const lit = swatch(WINDOW, palette)
  const color = new Color()
  const dummy = new Object3D()
  const gain = 0.16 + skyline * 0.15
  spots.forEach((spot, index) => {
    dummy.position.set(spot[0], spot[1], spot[2])
    dummy.rotation.set(0, 0, 0)
    dummy.scale.set(0.34, 0.5, 0.08)
    dummy.updateMatrix()
    mesh.setMatrixAt(index, dummy.matrix)
    color.set(windowOn(index, skyline) ? lit : '#120e12')
    if (windowOn(index, skyline)) color.multiplyScalar(gain)
    mesh.setColorAt(index, color)
  })
  mesh.instanceMatrix.needsUpdate = true
  if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true
}

function addWindows(root: Group, kept: Kept, spots: Win[], palette: string, skyline: number) {
  if (spots.length < 1) return
  const geo = new BoxGeometry(1, 1, 1)
  const mat = new MeshBasicMaterial({ color: '#ffffff', toneMapped: false })
  const mesh = new InstancedMesh(geo, mat, spots.length)
  mesh.name = 'atmos-window'
  mesh.userData.spots = spots
  paintWindows(mesh, spots, palette, skyline)
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function placeAerials(mesh: InstancedMesh, seconds: number, wind: number) {
  const spots = mesh.userData.spots as Aerial[]
  const dummy = new Object3D()
  const leanAmp = 0.02 + wind * 0.08
  spots.forEach(([x, z, height], index) => {
    const lean = Math.sin(seconds * 0.7 + index) * leanAmp
    dummy.position.set(x, height * 0.5, z)
    dummy.rotation.set(lean, 0, lean * 0.6)
    dummy.scale.set(0.045, height, 0.045)
    dummy.updateMatrix()
    mesh.setMatrixAt(index, dummy.matrix)
  })
  mesh.instanceMatrix.needsUpdate = true
}

function addAerials(root: Group, kept: Kept, palette: string, wind: number) {
  const geo = new CylinderGeometry(1, 1, 1, 5)
  const mat = new MeshBasicMaterial({ color: swatch(AERIAL_COLOR, palette) })
  const mesh = new InstancedMesh(geo, mat, AERIALS.length)
  mesh.name = 'atmos-aerial'
  mesh.userData.spots = AERIALS
  placeAerials(mesh, 0, wind)
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function addGround(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const geo = new PlaneGeometry(28, 24)
  geo.rotateX(-Math.PI / 2)
  const mat = new ShaderMaterial({
    uniforms: {
      uRoof: { value: new Color(swatch(ROOF_COLOR, resolved.palette)) },
      uSpill: { value: new Color(swatch(SPILL, resolved.palette)) },
    },
    vertexShader: ROOF_VERTEX,
    fragmentShader: ROOF_FRAGMENT,
  })
  const mesh = new Mesh(geo, mat)
  mesh.name = 'atmos-ground'
  mesh.frustumCulled = false
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

/** Parapet, AC units, a water tank on legs, vents and a mast: the clutter of a real roof, in one mesh. */
function roofPieces(): Piece[] {
  const concrete = '#4a4a56'
  return [
    { type: 'box', at: [0, 0.3, -11.8], size: [27.6, 0.6, 0.35], color: concrete },
    { type: 'box', at: [-13.8, 0.3, 0], size: [0.35, 0.6, 24], color: concrete },
    { type: 'box', at: [13.8, 0.3, 0], size: [0.35, 0.6, 24], color: concrete },
    { type: 'box', at: [-7, 0.55, -8], size: [2.2, 1.1, 1.4], color: '#6c6f7a' },
    { type: 'cylinder', at: [-7, 1.13, -8], size: [1.0, 0.06, 1.0], color: '#2a2b33' },
    { type: 'box', at: [-4.2, 0.45, -9.2], size: [1.5, 0.9, 1.1], color: '#6c6f7a' },
    { type: 'cylinder', at: [-4.2, 0.93, -9.2], size: [0.8, 0.06, 0.8], color: '#2a2b33' },
    { type: 'box', at: [6.5, 0.5, -9], size: [2.6, 1.0, 1.3], color: '#6c6f7a' },
    { type: 'cylinder', at: [6.5, 1.03, -9], size: [1.1, 0.06, 1.1], color: '#2a2b33' },
    { type: 'cylinder', at: [10, 0.5, -6.5], size: [0.34, 1.0, 0.34], color: '#7a7d88' },
    { type: 'cone', at: [10, 1.12, -6.5], size: [0.5, 0.26, 0.5], color: '#7a7d88' },
    { type: 'cylinder', at: [-10.5, 3.0, -7], size: [2.2, 2.0, 2.2], color: '#7a5a42' },
    { type: 'cone', at: [-10.5, 4.35, -7], size: [2.4, 0.8, 2.4], color: '#5a4030' },
    { type: 'cylinder', at: [-11, 1.0, -7.6], size: [0.16, 2.0, 0.16], color: '#2a2b33' },
    { type: 'cylinder', at: [-10, 1.0, -7.6], size: [0.16, 2.0, 0.16], color: '#2a2b33' },
    { type: 'cylinder', at: [-10, 1.0, -6.4], size: [0.16, 2.0, 0.16], color: '#2a2b33' },
    { type: 'cylinder', at: [-11, 1.0, -6.4], size: [0.16, 2.0, 0.16], color: '#2a2b33' },
    { type: 'cylinder', at: [12, 2.6, -10.5], size: [0.08, 5.2, 0.08], color: '#2a2b33' },
    { type: 'box', at: [12, 4.2, -10.5], size: [1.2, 0.06, 0.06], color: '#2a2b33' },
    { type: 'box', at: [12, 3.6, -10.5], size: [0.8, 0.06, 0.06], color: '#2a2b33' },
    { type: 'box', at: [3.5, 0.2, -10.4], size: [4.2, 0.4, 0.5], color: '#3a3a44' },
  ]
}

function addRoofProps(root: Group, kept: Kept) {
  const geo = composeGeometry(roofPieces())
  const mat = new MeshStandardMaterial({ vertexColors: true, flatShading: true, roughness: 0.95, emissive: 0x3a3a46, emissiveIntensity: 1 })
  const mesh = new Mesh(geo, mat)
  mesh.name = 'atmos-roof-props'
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function addCity(root: Group, kept: Kept, palette: string) {
  const geo = new PlaneGeometry(40, 26)
  geo.rotateX(-Math.PI / 2)
  const mat = new MeshBasicMaterial({ color: swatch(CITY, palette) })
  const mesh = new Mesh(geo, mat)
  mesh.name = 'atmos-city'
  mesh.position.set(0, -0.04, -19)
  mesh.frustumCulled = false
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function addTowers(root: Group, kept: Kept, count: number, palette: string) {
  const spots = towerSpots(count)
  if (spots.length < 1) return
  const geo = new BoxGeometry(1, 1, 1)
  const mat = new MeshBasicMaterial({ color: '#ffffff' })
  const mesh = new InstancedMesh(geo, mat, spots.length)
  mesh.name = 'atmos-tower'
  placeBoxes(mesh, spots)
  paintTowers(mesh, palette)
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function addSky(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const geo = new SphereGeometry(42, 18, 12)
  const mat = new ShaderMaterial({
    uniforms: {
      uHorizon: { value: new Color(swatch(HORIZON, resolved.palette)) },
      uZenith: { value: new Color(zenithColor(resolved.timeOfDay)) },
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

function paintLook(root: Group, settings: AtmosSettings) {
  const windows = root.getObjectByName('atmos-window') as InstancedMesh | undefined
  const spots = windows?.userData.spots as Win[] | undefined
  if (windows && spots) paintWindows(windows, spots, settings.palette, skylineAmount(settings.variant))
  const towers = root.getObjectByName('atmos-tower') as InstancedMesh | undefined
  if (towers) paintTowers(towers, settings.palette)
  const sky = root.getObjectByName('atmos-sky') as Mesh | undefined
  const material = sky?.material
  if (material instanceof ShaderMaterial) {
    material.uniforms.uHorizon.value.set(swatch(HORIZON, settings.palette))
    material.uniforms.uZenith.value.set(zenithColor(settings.timeOfDay))
  }
  const ground = root.getObjectByName('atmos-ground') as Mesh | undefined
  const groundMat = ground?.material
  if (groundMat instanceof ShaderMaterial) groundMat.uniforms.uSpill.value.set(swatch(SPILL, settings.palette))
}

function syncRoof(root: Group, seconds: number, resolved: ResolvedAtmos, live?: AtmosSettings) {
  const settings = live ?? resolved
  paintLook(root, settings)
  const aerials = root.getObjectByName('atmos-aerial') as InstancedMesh | undefined
  if (aerials) placeAerials(aerials, seconds, settings.wind)
  const fog = (root.parent as { fog?: unknown } | null)?.fog
  if (fog instanceof FogExp2) fog.density = 0.014 + settings.fogDensity * 0.034
}

function liveHandle(root: Group, kept: Kept, resolved: ResolvedAtmos): AtmosHandle {
  return {
    ms: { shafts: 0, dof: 0, grade: 0 },
    passes: () => [],
    sync: (seconds, _camera, _light, _quality, _focus, live) => syncRoof(root, seconds, resolved, live),
    dispose: disposeOnce(() => disposeKept(root, kept)),
  }
}

export function buildRooftopNight(resolved: ResolvedAtmos, webgl2: boolean): { root: Group; handle: AtmosHandle } {
  if (!webgl2) {
    const flat = flatRoof(resolved)
    const handle = idleHandle(flat.root, flat.kept)
    flat.root.userData.atmos = handle
    return { root: flat.root, handle }
  }
  const root = new Group()
  root.name = 'atmos-rooftop-night'
  const kept = emptyKept()
  const skyline = skylineAmount(resolved.variant)
  addGround(root, resolved, kept)
  addRoofProps(root, kept)
  skylineLayers(root, kept, { seed: 11, count: 14, radius: 26, height: [7, 15], width: [3, 5.5], body: '#1b1830', haze: '#4a3a5c', layers: 3 })
  addCity(root, kept, resolved.palette)
  addBoxes(root, kept, 'atmos-parapet', PARAPET, swatch(RIM, resolved.palette))
  addBoxes(root, kept, 'atmos-vent', VENTS, swatch(VENT_COLOR, resolved.palette))
  addAerials(root, kept, resolved.palette, resolved.wind)
  addTowers(root, kept, resolved.grassBlades, resolved.palette)
  addWindows(root, kept, windowSpots(resolved.grassBlades, resolved.moteCount), resolved.palette, skyline)
  addSky(root, resolved, kept)
  const handle = liveHandle(root, kept, resolved)
  root.userData.atmos = handle
  return { root, handle }
}

export const rooftopNightSet: AtmosSetDefinition = {
  id: 'atmos-rooftop-night',
  titleKey: 'template.atmos-rooftop-night-wide.title',
  setting: 'rooftop',
  seed: 97017,
  subject: CLEARING_SUBJECT,
  subjectYaw: 0.15,
  palettes: ROOF_PALETTES,
  times: ROOF_TIMES,
  defaults: { timeOfDay: 'night', fogDensity: 0.24, wind: 0.22, motes: 0.35, palette: 'sodium', variant: 5 },
  variant: { labelKey: 'atmos.skyline', min: 0, max: 8 },
  low: { shaftSteps: 0, grassBlades: 6, moteCount: 4 },
  high: { shaftSteps: 0, grassBlades: 8, moteCount: 6 },
  templates: [
    { id: 'atmos-rooftop-night-wide', camera: 'establishment', eye: WIDE_EYE, look: WIDE_LOOK, fov: 58, duration: 6 },
    { id: 'atmos-rooftop-night-low', camera: 'establishment', eye: LOW_EYE, look: LOW_LOOK, fov: 60, duration: 6 },
  ],
  build: buildRooftopNight,
  fallback(resolved) {
    const sky = ROOF_PALETTES[resolved.palette as keyof typeof ROOF_PALETTES]?.fog ?? ROOF_PALETTES.sodium.fog
    return { sky: hexColor(sky), ground: hexColor(FALLBACK_GROUND[resolved.palette] ?? FALLBACK_GROUND.sodium) }
  },
}
