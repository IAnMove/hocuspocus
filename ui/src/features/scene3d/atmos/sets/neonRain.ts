import {
  BackSide,
  BufferGeometry,
  Color,
  FogExp2,
  Group,
  InstancedMesh,
  Mesh,
  MeshBasicMaterial,
  Object3D,
  PlaneGeometry,
  ShaderMaterial,
  SphereGeometry,
  BoxGeometry,
  Vector3,
  Vector4,
  type Material,
} from 'three'
import type { AtmosHandle } from './clearing.ts'
import type { AtmosSetDefinition } from '../definition.ts'
import type { AtmosSettings, ResolvedAtmos } from '../params.ts'
import { hash2 } from '../noise.ts'
import { CLEARING_SUBJECT } from '../layout.ts'

type Kept = { geometries: BufferGeometry[]; materials: Material[] }
type Lamp = { x: number; y: number; z: number; sx: number; sy: number; sz: number; swatch: number }
type Puff = { x: number; z: number; layer: number }
type Cam = { position?: { x: number; y: number; z: number } }
type GroundLook = {
  cam: Vector3
  asphalt: Color
  fog: Color
  signs: Color[]
  rain: { value: number }
  time: { value: number }
  storm: { value: number }
}
type SkyLook = { horizon: Color; zenith: Color }

// PlaneGeometry faces +z. rotateX(-PI/2) stores alley depth in position.z (world z) and up in position.y.
// Reflections are computed in this ground shader from the view ray. There is no composer pass.
const GROUND_VERTEX = `
  varying vec3 vPos;
  void main() {
    vPos = position;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`
const GROUND_FRAGMENT = `
  uniform vec3 uCam;
  uniform vec3 uAsphalt;
  uniform vec3 uFog;
  uniform float uRain;
  uniform float uTime;
  uniform float uStorm;
  uniform vec4 uSign[6];
  uniform vec4 uBox[6];
  uniform vec3 uColor[6];
  uniform vec4 uPuddle[4];
  varying vec3 vPos;
  float puddle(vec2 p) {
    float wet = 0.0;
    for (int i = 0; i < 4; i++) {
      vec2 d = (p - uPuddle[i].xy) / max(uPuddle[i].zw, vec2(0.2));
      wet = max(wet, 1.0 - smoothstep(0.45, 1.0, length(d)));
    }
    return wet;
  }
  vec3 reflected(vec3 p) {
    vec3 eye = p - uCam;
    float span = max(length(eye), 0.001);
    vec3 ray = vec3(eye.x / span, -eye.y / span, eye.z / span);
    vec3 acc = vec3(0.0);
    for (int i = 0; i < 6; i++) {
      float denom = ray.x;
      float safe = abs(denom) < 0.02 ? 0.02 : denom;
      float t = (uSign[i].x - p.x) / safe;
      float ok = abs(denom) < 0.02 || t < 0.05 || t > 48.0 ? 0.0 : 1.0;
      float hy = t * ray.y;
      float hz = p.z + t * ray.z;
      float dy = (hy - uSign[i].y) / max(uBox[i].x * 2.6, 0.2);
      float dz = (hz - uSign[i].z) / max(uBox[i].y * 2.6, 0.2);
      float blob = exp(-0.7 * (dy * dy + dz * dz)) * exp(-t * 0.045);
      acc += uColor[i] * blob * ok;
    }
    return acc;
  }
  void main() {
    vec3 p = vec3(vPos.x, 0.0, vPos.z);
    float grain = fract(sin(dot(p.xz, vec2(27.1, 91.7))) * 13.7);
    vec3 asphalt = uAsphalt * (0.86 + 0.14 * grain);
    float seamX = smoothstep(0.04, 0.0, abs(fract(p.x * 0.42) - 0.5) - 0.46);
    float seamZ = smoothstep(0.04, 0.0, abs(fract(p.z * 0.42) - 0.5) - 0.46);
    asphalt *= 1.0 - 0.3 * max(seamX, seamZ);
    if (uStorm > 0.5) asphalt *= 0.72;
    vec3 toCam = normalize(uCam - p);
    asphalt += vec3(0.07, 0.06, 0.09) * pow(max(toCam.y, 0.0), 5.0);
    float wet = clamp(0.48 + uRain * 0.035 + puddle(p.xz), 0.0, 1.0);
    float ripple = 0.86 + 0.14 * sin(p.z * 2.5 - uTime * 2.3 + p.x);
    vec3 color = asphalt + reflected(p) * wet * ripple * (0.8 + uRain * 0.05);
    float far = smoothstep(5.0, 17.0, length(p.xz - uCam.xz));
    color = mix(color, uFog, far * 0.75);
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
    gl_FragColor = vec4(mix(uHorizon, uZenith, smoothstep(-0.05, 0.62, vH)), 1.0);
  }
`

const LAMPS: Lamp[] = [
  { x: -4.15, y: 2.55, z: -4.6, sx: 0.16, sy: 2.1, sz: 2.4, swatch: 0 },
  { x: -3.95, y: 3.35, z: -7.1, sx: 0.14, sy: 2.4, sz: 0.7, swatch: 1 },
  { x: -4.25, y: 1.65, z: -2.55, sx: 0.14, sy: 1.35, sz: 1.7, swatch: 2 },
  { x: 4.5, y: 2.5, z: -5.2, sx: 0.16, sy: 2.0, sz: 2.2, swatch: 3 },
  { x: 4.4, y: 1.85, z: -3.15, sx: 0.14, sy: 2.2, sz: 0.65, swatch: 4 },
  { x: 4.6, y: 3.15, z: -7.7, sx: 0.14, sy: 1.5, sz: 1.9, swatch: 5 },
  { x: -2.55, y: 2.4, z: -2.45, sx: 1.65, sy: 1.5, sz: 0.1, swatch: 0 },
  { x: -2.85, y: 3.65, z: -4.85, sx: 1.3, sy: 0.7, sz: 0.1, swatch: 1 },
  { x: 2.9, y: 2.2, z: -2.85, sx: 1.5, sy: 1.35, sz: 0.1, swatch: 5 },
  { x: 3.15, y: 3.45, z: -5.2, sx: 1.35, sy: 0.8, sz: 0.1, swatch: 4 },
  { x: 0.1, y: 3.35, z: -11.4, sx: 3.2, sy: 0.72, sz: 0.1, swatch: 1 },
  { x: -4.55, y: 4.85, z: -5.1, sx: 0.08, sy: 0.14, sz: 13.2, swatch: 0 },
  { x: 4.9, y: 4.85, z: -5.1, sx: 0.08, sy: 0.14, sz: 13.2, swatch: 1 },
]
const PUDDLES: Array<[number, number, number, number]> = [
  [-2.2, 0.42, 0.78, 0.5],
  [2.6, 0.7, 0.62, 0.45],
  [-2.75, -2.6, 0.72, 0.46],
  [2.9, -3.2, 0.78, 0.5],
]
const VENTS: Array<[number, number]> = [
  [-4.42, -3.3], [-4.48, -6.2], [-4.35, -8.4],
  [4.55, -3.0], [4.62, -5.8], [4.5, -8.0],
]
const STEAM: Puff[] = VENTS.flatMap(([x, z]) => [
  { x, z, layer: 0 },
  { x, z, layer: 1 },
  { x, z, layer: 2 },
])
const WALLS: Array<[number, number, number, number, number, number]> = [
  [-5.35, 2.45, -5.1, 1.5, 4.9, 14.2],
  [5.55, 2.45, -5.1, 1.6, 4.9, 14.2],
  [0.1, 2.55, -12.0, 12.6, 5.1, 0.7],
]

const LAMP_COLORS: Record<string, readonly string[]> = {
  magenta: ['#ff3aa2', '#46f0ff', '#ffd15c', '#ff5a3c', '#d6ff4a', '#ff9ae8'],
  violet: ['#b388ff', '#4d7dff', '#ff4fd8', '#3dffe4', '#ffe56a', '#f0e6ff'],
}
const WALL: Record<string, string> = { magenta: '#32243f', violet: '#2a2748' }
const STEAM_COLOR: Record<string, string> = { magenta: '#f4fbff', violet: '#f3f0ff' }
const FALLBACK_GROUND: Record<string, string> = { magenta: '#3a2848', violet: '#2e2a50' }

const NEON_PALETTES = {
  magenta: { fog: '#2a1238', ground: '#3a2848', accent: '#ff4fa8', sky: ['#2a1238', '#160818'] },
  violet: { fog: '#1a1840', ground: '#2e2a50', accent: '#8b7cff', sky: ['#1a1840', '#12182e'] },
} as const

const NEON_TIMES = {
  night: { sun: [0.1, -0.86, -0.42], sunColor: '#ffe6f4' },
  storm: { sun: [-0.16, -0.74, -0.52], sunColor: '#c9d4ff' },
} as const

const WIDE_EYE = [0.15, 1.48, 3.9] as const
const WIDE_LOOK = [0.2, 1.35, -6.2] as const
const LOW_EYE = [0.55, 0.58, 2.45] as const
const LOW_LOOK = [-3.8, 1.55, -4.2] as const
const REFLECT = 6

function emptyKept(): Kept {
  return { geometries: [], materials: [] }
}

function hexColor(color: string): [number, number, number] {
  const n = Number.parseInt(color.slice(1), 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

function swatch(table: Record<string, string>, palette: string): string {
  return table[palette] ?? table.magenta
}

function paletteLook(palette: string) {
  return NEON_PALETTES[palette as keyof typeof NEON_PALETTES] ?? NEON_PALETTES.magenta
}

function lampTable(palette: string): readonly string[] {
  return LAMP_COLORS[palette] ?? LAMP_COLORS.magenta
}

function rainAmount(variant: number | undefined): number {
  const value = typeof variant === 'number' && Number.isFinite(variant) ? variant : 5
  return Math.min(8, Math.max(0, value))
}

function streakLength(amount: number): number {
  return 0.48 + amount * 0.12
}

function zenithColor(time: string): string {
  return time === 'storm' ? '#12182e' : '#160818'
}

function cameraXYZ(camera: Cam): [number, number, number] {
  const x = camera.position?.x
  const y = camera.position?.y
  const z = camera.position?.z
  if (typeof x !== 'number' || typeof y !== 'number' || typeof z !== 'number') return [WIDE_EYE[0], WIDE_EYE[1], WIDE_EYE[2]]
  if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(z)) return [WIDE_EYE[0], WIDE_EYE[1], WIDE_EYE[2]]
  return [x, y, z]
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

function flatAlley(resolved: ResolvedAtmos): { root: Group; kept: Kept } {
  const root = new Group()
  root.name = 'atmos-neon-rain'
  const kept = emptyKept()
  const geo = new PlaneGeometry(16, 16)
  geo.rotateX(-Math.PI / 2)
  const mat = new MeshBasicMaterial({ color: resolved.stone })
  root.add(new Mesh(geo, mat))
  kept.geometries.push(geo)
  kept.materials.push(mat)
  return { root, kept }
}

function reflectBoxes(lamps: Lamp[]): Vector4[] {
  return lamps.slice(0, REFLECT).map(lamp => new Vector4(lamp.x, lamp.y, lamp.z, 1))
}

function reflectSizes(lamps: Lamp[]): Vector4[] {
  return lamps.slice(0, REFLECT).map(lamp => new Vector4(lamp.sy * 0.5, lamp.sz * 0.5, 0, 0))
}

function reflectColors(palette: string): Color[] {
  const table = lampTable(palette)
  return LAMPS.slice(0, REFLECT).map(lamp => new Color(table[lamp.swatch] ?? table[0]))
}

function addGround(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const geo = new PlaneGeometry(32, 32)
  geo.rotateX(-Math.PI / 2)
  const look = paletteLook(resolved.palette)
  const view: GroundLook = {
    cam: new Vector3(WIDE_EYE[0], WIDE_EYE[1], WIDE_EYE[2]),
    asphalt: new Color(look.ground),
    fog: new Color(look.fog),
    signs: reflectColors(resolved.palette),
    rain: { value: rainAmount(resolved.variant) },
    time: { value: 0 },
    storm: { value: resolved.timeOfDay === 'storm' ? 1 : 0 },
  }
  const mat = new ShaderMaterial({
    uniforms: {
      uCam: { value: view.cam },
      uAsphalt: { value: view.asphalt },
      uFog: { value: view.fog },
      uRain: view.rain,
      uTime: view.time,
      uStorm: view.storm,
      uSign: { value: reflectBoxes(LAMPS) },
      uBox: { value: reflectSizes(LAMPS) },
      uColor: { value: view.signs },
      uPuddle: { value: PUDDLES.map(puddle => new Vector4(puddle[0], puddle[1], puddle[2], puddle[3])) },
    },
    vertexShader: GROUND_VERTEX,
    fragmentShader: GROUND_FRAGMENT,
    fog: false,
  })
  const mesh = new Mesh(geo, mat)
  mesh.name = 'atmos-ground'
  mesh.frustumCulled = false
  mesh.userData.puddles = PUDDLES.map(puddle => [puddle[0], puddle[1]])
  mesh.userData.look = view
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function placeLamps(mesh: InstancedMesh) {
  const dummy = new Object3D()
  LAMPS.forEach((lamp, index) => {
    dummy.position.set(lamp.x, lamp.y, lamp.z)
    dummy.rotation.set(0, 0, 0)
    dummy.scale.set(lamp.sx, lamp.sy, lamp.sz)
    dummy.updateMatrix()
    mesh.setMatrixAt(index, dummy.matrix)
  })
  mesh.instanceMatrix.needsUpdate = true
}

function paintLamps(mesh: InstancedMesh, palette: string) {
  const table = lampTable(palette)
  const color = new Color()
  LAMPS.forEach((lamp, index) => {
    color.set(table[lamp.swatch] ?? table[0])
    mesh.setColorAt(index, color)
  })
  if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true
}

function addLamps(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const geo = new BoxGeometry(1, 1, 1)
  const mat = new MeshBasicMaterial()
  const mesh = new InstancedMesh(geo, mat, LAMPS.length)
  mesh.name = 'atmos-sign'
  mesh.frustumCulled = false
  placeLamps(mesh)
  paintLamps(mesh, resolved.palette)
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function rainSpots(count: number, seed: number): Array<[number, number]> {
  const spots: Array<[number, number]> = []
  for (let index = 0; index < count; index += 1) {
    const x = -4.1 + hash2(index, 3, seed) * 8.2
    const z = -8.6 + hash2(index, 5, seed) * 11
    spots.push([x, z])
  }
  return spots
}

function placeRain(mesh: InstancedMesh, spots: Array<[number, number]>, seconds: number, amount: number) {
  const dummy = new Object3D()
  const length = streakLength(amount)
  const speed = 1.1 + amount * 0.14
  spots.forEach(([x, z], index) => {
    const phase = (seconds * speed + index * 0.37) % 7.2
    dummy.position.set(x, 6.5 - phase, z)
    dummy.rotation.set(0, 0, 0)
    dummy.scale.set(0.045, length, 0.045)
    dummy.updateMatrix()
    mesh.setMatrixAt(index, dummy.matrix)
  })
  mesh.instanceMatrix.needsUpdate = true
}

function addRain(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const spots = rainSpots(resolved.moteCount, resolved.seed)
  if (spots.length < 1) return
  const geo = new BoxGeometry(1, 1, 1)
  const mat = new MeshBasicMaterial({ color: '#e7f6ff' })
  const mesh = new InstancedMesh(geo, mat, spots.length)
  mesh.name = 'atmos-rain'
  mesh.frustumCulled = false
  mesh.userData.spots = spots
  placeRain(mesh, spots, 0, rainAmount(resolved.variant))
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function placeSteam(mesh: InstancedMesh, seconds: number, amount: number) {
  const dummy = new Object3D()
  STEAM.forEach((puff, index) => {
    const phase = (seconds * 0.48 + index * 0.23 + puff.layer * 0.72) % 2.25
    const size = (0.14 + phase * 0.1) * (0.65 + amount * 0.04)
    const drift = Math.sin(seconds * 0.7 + index) * 0.1
    dummy.position.set(puff.x + drift, 0.16 + phase * 0.95, puff.z)
    dummy.rotation.set(0, 0, 0)
    dummy.scale.set(size, size * 1.25, size)
    dummy.updateMatrix()
    mesh.setMatrixAt(index, dummy.matrix)
  })
  mesh.instanceMatrix.needsUpdate = true
}

function addSteam(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const geo = new SphereGeometry(1, 6, 4)
  const mat = new MeshBasicMaterial({
    color: swatch(STEAM_COLOR, resolved.palette),
    transparent: true,
    opacity: 0.5,
    depthWrite: false,
  })
  const mesh = new InstancedMesh(geo, mat, STEAM.length)
  mesh.name = 'atmos-steam'
  mesh.frustumCulled = false
  placeSteam(mesh, 0, rainAmount(resolved.variant))
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function placeWalls(mesh: InstancedMesh) {
  const dummy = new Object3D()
  WALLS.forEach(([x, y, z, sx, sy, sz], index) => {
    dummy.position.set(x, y, z)
    dummy.rotation.set(0, 0, 0)
    dummy.scale.set(sx, sy, sz)
    dummy.updateMatrix()
    mesh.setMatrixAt(index, dummy.matrix)
  })
  mesh.instanceMatrix.needsUpdate = true
}

function addWalls(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const geo = new BoxGeometry(1, 1, 1)
  const mat = new MeshBasicMaterial({ color: swatch(WALL, resolved.palette) })
  const mesh = new InstancedMesh(geo, mat, WALLS.length)
  mesh.name = 'atmos-wall'
  mesh.frustumCulled = false
  placeWalls(mesh)
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function addSky(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const look = paletteLook(resolved.palette)
  const sky: SkyLook = { horizon: new Color(look.fog), zenith: new Color(zenithColor(resolved.timeOfDay)) }
  const geo = new SphereGeometry(18, 16, 10)
  const mat = new ShaderMaterial({
    uniforms: {
      uHorizon: { value: sky.horizon },
      uZenith: { value: sky.zenith },
    },
    vertexShader: SKY_VERTEX,
    fragmentShader: SKY_FRAGMENT,
    side: BackSide,
    fog: false,
  })
  const mesh = new Mesh(geo, mat)
  mesh.name = 'atmos-sky'
  mesh.position.set(0, -1, -1)
  mesh.frustumCulled = false
  mesh.userData.look = sky
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function syncGround(root: Group, camera: Cam, seconds: number, settings: AtmosSettings) {
  const mesh = root.getObjectByName('atmos-ground')
  if (!(mesh instanceof Mesh)) return
  const look = mesh.userData.look as GroundLook | undefined
  if (!look?.signs) return
  const at = cameraXYZ(camera)
  const palette = paletteLook(settings.palette)
  const table = lampTable(settings.palette)
  look.cam.set(at[0], at[1], at[2])
  look.asphalt.set(palette.ground)
  look.fog.set(palette.fog)
  look.rain.value = rainAmount(settings.variant)
  look.time.value = seconds
  look.storm.value = settings.timeOfDay === 'storm' ? 1 : 0
  LAMPS.slice(0, REFLECT).forEach((lamp, index) => {
    look.signs[index].set(table[lamp.swatch] ?? table[0])
  })
}

function syncLamps(root: Group, settings: AtmosSettings) {
  const mesh = root.getObjectByName('atmos-sign')
  if (mesh instanceof InstancedMesh) paintLamps(mesh, settings.palette)
}

function syncRain(root: Group, seconds: number, amount: number) {
  const mesh = root.getObjectByName('atmos-rain')
  const spots = mesh?.userData.spots as Array<[number, number]> | undefined
  if (mesh instanceof InstancedMesh && spots) placeRain(mesh, spots, seconds, amount)
}

function syncSteam(root: Group, seconds: number, amount: number, palette: string) {
  const mesh = root.getObjectByName('atmos-steam')
  if (!(mesh instanceof InstancedMesh)) return
  placeSteam(mesh, seconds, amount)
  const material = mesh.material
  if (material instanceof MeshBasicMaterial) material.color.set(swatch(STEAM_COLOR, palette))
}

function syncSky(root: Group, settings: AtmosSettings) {
  const mesh = root.getObjectByName('atmos-sky')
  const look = mesh?.userData.look as SkyLook | undefined
  if (!look) return
  look.horizon.set(paletteLook(settings.palette).fog)
  look.zenith.set(zenithColor(settings.timeOfDay))
}

function syncFog(root: Group, settings: AtmosSettings) {
  const fog = (root.parent as { fog?: unknown } | null)?.fog
  if (fog instanceof FogExp2) fog.density = 0.014 + settings.fogDensity * 0.034
}

function syncNeon(root: Group, seconds: number, camera: Cam, resolved: ResolvedAtmos, live?: AtmosSettings) {
  const settings = live ?? resolved
  const amount = rainAmount(settings.variant)
  syncGround(root, camera, seconds, settings)
  syncLamps(root, settings)
  syncRain(root, seconds, amount)
  syncSteam(root, seconds, amount, settings.palette)
  syncSky(root, settings)
  syncFog(root, settings)
}

function liveHandle(root: Group, kept: Kept, resolved: ResolvedAtmos): AtmosHandle {
  return {
    ms: { shafts: 0, dof: 0, grade: 0 },
    passes: () => [],
    sync: (seconds, camera, _light, _quality, _focus, live) => syncNeon(root, seconds, camera, resolved, live),
    dispose: disposeOnce(() => disposeKept(root, kept)),
  }
}

export function buildNeonRain(resolved: ResolvedAtmos, webgl2: boolean): { root: Group; handle: AtmosHandle } {
  if (!webgl2) {
    const flat = flatAlley(resolved)
    const handle = idleHandle(flat.root, flat.kept)
    flat.root.userData.atmos = handle
    return { root: flat.root, handle }
  }
  const root = new Group()
  root.name = 'atmos-neon-rain'
  const kept = emptyKept()
  addGround(root, resolved, kept)
  addWalls(root, resolved, kept)
  addLamps(root, resolved, kept)
  addRain(root, resolved, kept)
  addSteam(root, resolved, kept)
  addSky(root, resolved, kept)
  const handle = liveHandle(root, kept, resolved)
  root.userData.atmos = handle
  return { root, handle }
}

export const neonRainSet: AtmosSetDefinition = {
  id: 'atmos-neon-rain',
  titleKey: 'template.atmos-neon-rain-wide.title',
  setting: 'street',
  seed: 94017,
  subject: CLEARING_SUBJECT,
  subjectYaw: 0.15,
  palettes: NEON_PALETTES,
  times: NEON_TIMES,
  defaults: { timeOfDay: 'night', fogDensity: 0.34, wind: 0.22, motes: 0.3, palette: 'magenta', variant: 5 },
  variant: { labelKey: 'atmos.rain', min: 0, max: 8 },
  low: { shaftSteps: 0, grassBlades: 8, moteCount: 42 },
  high: { shaftSteps: 0, grassBlades: 12, moteCount: 72 },
  templates: [
    { id: 'atmos-neon-rain-wide', camera: 'establishment', eye: WIDE_EYE, look: WIDE_LOOK, fov: 50, duration: 6 },
    { id: 'atmos-neon-rain-low', camera: 'establishment', eye: LOW_EYE, look: LOW_LOOK, fov: 56, duration: 6 },
  ],
  build: buildNeonRain,
  fallback(resolved) {
    const sky = paletteLook(resolved.palette).fog
    return { sky: hexColor(sky), ground: hexColor(FALLBACK_GROUND[resolved.palette] ?? FALLBACK_GROUND.magenta) }
  },
}
