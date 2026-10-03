import {
  AdditiveBlending,
  BackSide,
  BoxGeometry,
  BufferGeometry,
  CircleGeometry,
  Color,
  ConeGeometry,
  CylinderGeometry,
  Float32BufferAttribute,
  FogExp2,
  Group,
  InstancedMesh,
  Mesh,
  MeshBasicMaterial,
  Object3D,
  PlaneGeometry,
  Points,
  PointsMaterial,
  ShaderMaterial,
  SphereGeometry,
  type Material,
} from 'three'
import type { AtmosHandle } from './clearing.ts'
import type { AtmosSetDefinition } from '../definition.ts'
import type { AtmosSettings, ResolvedAtmos } from '../params.ts'
import { hash2 } from '../noise.ts'
import { CLEARING_SUBJECT } from '../layout.ts'
import {
  cableBeads,
  cabinetLit,
  diskDrives,
  mainframeCabinets,
  scanRate,
  tapeReels,
  type Bead,
  type Cabinet,
  type Drive,
  type Reel,
} from './siliconMainframeLayout.ts'

type Kept = { geometries: BufferGeometry[]; materials: Material[] }
type LedSpot = { x: number; y: number; z: number }

const SCREEN_VERTEX = `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    vec4 local = vec4(position, 1.0);
    #ifdef USE_INSTANCING
      local = instanceMatrix * local;
    #endif
    vec4 world = modelMatrix * local;
    gl_Position = projectionMatrix * viewMatrix * world;
  }
`
const SCREEN_FRAGMENT = `
  uniform vec3 uColor;
  uniform float uSweep;
  uniform float uGain;
  varying vec2 vUv;
  void main() {
    float scan = step(0.55, fract(vUv.y * 26.0 - uSweep));
    float bar = 1.0 - smoothstep(0.0, 0.08, abs(fract(vUv.y - uSweep) - 0.5));
    float lit = 0.28 + scan * 0.45 + bar * 0.35;
    gl_FragColor = vec4(uColor * lit * uGain, 1.0);
  }
`
const HAZE_VERTEX = `
  varying vec3 vWorld;
  void main() {
    vec4 world = modelMatrix * vec4(position, 1.0);
    vWorld = world.xyz;
    gl_Position = projectionMatrix * viewMatrix * world;
  }
`
const HAZE_FRAGMENT = `
  uniform vec3 uTint;
  varying vec3 vWorld;
  void main() {
    float h = clamp(vWorld.y / 5.6, 0.0, 1.0);
    gl_FragColor = vec4(uTint, h * h * 0.42);
  }
`
const FLOOR_VERTEX = `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`
const FLOOR_FRAGMENT = `
  uniform vec3 uFloor;
  uniform vec3 uLine;
  varying vec2 vUv;
  void main() {
    vec2 cell = fract(vUv * vec2(22.0, 26.0));
    float line = 1.0 - smoothstep(0.0, 0.06, min(cell.x, cell.y));
    gl_FragColor = vec4(mix(uFloor, uLine, line * 0.22), 1.0);
  }
`

const WIDE_EYE = [0.35, 1.85, 4.4] as const
const WIDE_LOOK = [0.3, 1.7, -7] as const
const LOW_EYE = [1.15, 0.42, 1.35] as const
const LOW_LOOK = [0.35, 1.55, -8] as const
const FRAME_PALETTES = {
  phosphor: { fog: '#02110a', ground: '#010804', accent: '#33ff66', sky: ['#02110a', '#0b3d1e'] },
  chrome: { fog: '#01012b', ground: '#02020a', accent: '#d1f7ff', sky: ['#01012b', '#005678'] },
} as const
const FRAME_TIMES = {
  idle: { sun: [0.15, -0.62, -0.77] as const, sunColor: '#8fd9ff' },
  burst: { sun: [0.04, -0.9, -0.4] as const, sunColor: '#f4fff8' },
}

function emptyKept(): Kept {
  return { geometries: [], materials: [] }
}

function hexColor(color: string): [number, number, number] {
  const n = Number.parseInt(color.slice(1), 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

function paletteOf(name: string) {
  if (name === 'chrome') return FRAME_PALETTES.chrome
  return FRAME_PALETTES.phosphor
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

function addDrawn(parent: Group, kept: Kept, mesh: Mesh | InstancedMesh | Points) {
  parent.add(mesh)
  kept.geometries.push(mesh.geometry)
  const material = mesh.material
  if (Array.isArray(material)) kept.materials.push(...material)
  else kept.materials.push(material)
}

function placeBox(mesh: InstancedMesh, index: number, x: number, y: number, z: number, sx: number, sy: number, sz: number, roll: number) {
  const dummy = new Object3D()
  dummy.position.set(x, y, z)
  dummy.rotation.z = roll
  dummy.scale.set(sx, sy, sz)
  dummy.updateMatrix()
  mesh.setMatrixAt(index, dummy.matrix)
}

function idleHandle(root: Group, kept: Kept): AtmosHandle {
  return {
    ms: { shafts: 0, dof: 0, grade: 0 },
    passes: () => [],
    sync: () => {},
    dispose: disposeOnce(() => disposeKept(root, kept)),
  }
}

function addRoom(root: Group, kept: Kept) {
  const mesh = new InstancedMesh(new BoxGeometry(1, 1, 1), new MeshBasicMaterial({ color: '#07080c', side: BackSide }), 4)
  mesh.name = 'atmos-wall'
  const walls: Array<[number, number, number, number, number, number]> = [
    [-8.1, 3.1, -1.4, 0.35, 6.2, 17],
    [8.1, 3.1, -1.4, 0.35, 6.2, 17],
    [0, 3.1, -9.4, 16.2, 6.2, 0.35],
    [0, 6.15, -1.4, 16.2, 0.28, 17],
  ]
  walls.forEach(([x, y, z, sx, sy, sz], index) => placeBox(mesh, index, x, y, z, sx, sy, sz, 0))
  mesh.instanceMatrix.needsUpdate = true
  addDrawn(root, kept, mesh)
}

function addFloor(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const look = paletteOf(resolved.palette)
  const geo = new PlaneGeometry(16, 18)
  geo.rotateX(-Math.PI / 2)
  const mat = new ShaderMaterial({
    uniforms: {
      uFloor: { value: new Color(look.ground) },
      uLine: { value: new Color(look.accent) },
    },
    vertexShader: FLOOR_VERTEX,
    fragmentShader: FLOOR_FRAGMENT,
  })
  const mesh = new Mesh(geo, mat)
  mesh.name = 'atmos-floor'
  mesh.position.set(0.4, 0, -1.2)
  addDrawn(root, kept, mesh)
}

function addHaze(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const geo = new BoxGeometry(15.4, 6.0, 16.4)
  const mat = new ShaderMaterial({
    transparent: true,
    depthWrite: false,
    side: BackSide,
    uniforms: { uTint: { value: new Color(paletteOf(resolved.palette).fog) } },
    vertexShader: HAZE_VERTEX,
    fragmentShader: HAZE_FRAGMENT,
  })
  const mesh = new Mesh(geo, mat)
  mesh.name = 'atmos-haze'
  mesh.position.set(0.4, 3.0, -1.4)
  addDrawn(root, kept, mesh)
}

function addSky(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const look = paletteOf(resolved.palette)
  const geo = new SphereGeometry(40, 12, 8)
  const mat = new MeshBasicMaterial({ color: look.sky[1], side: BackSide, depthWrite: false })
  const mesh = new Mesh(geo, mat)
  mesh.name = 'atmos-sky'
  mesh.frustumCulled = false
  addDrawn(root, kept, mesh)
}

function addCabinets(root: Group, cabinets: readonly Cabinet[], kept: Kept) {
  const mesh = new InstancedMesh(new BoxGeometry(1, 1, 1), new MeshBasicMaterial({ color: '#10141a' }), cabinets.length)
  mesh.name = 'atmos-cabinet'
  cabinets.forEach((cabinet, index) => {
    placeBox(mesh, index, cabinet.x, cabinet.h / 2, cabinet.z, cabinet.w, cabinet.h, cabinet.d, 0)
  })
  mesh.instanceMatrix.needsUpdate = true
  addDrawn(root, kept, mesh)
}

function ledSpots(cabinets: readonly Cabinet[]): LedSpot[] {
  const spots: LedSpot[] = []
  for (const cabinet of cabinets) {
    for (let row = 0; row < 3; row += 1) {
      for (let col = 0; col < 2; col += 1) {
        spots.push({
          x: cabinet.x + cabinet.face * (cabinet.w / 2 + 0.04),
          y: 1.15 + row * 0.55,
          z: cabinet.z + (col - 0.5) * 0.42,
        })
      }
    }
  }
  return spots
}

function addLeds(root: Group, cabinets: readonly Cabinet[], kept: Kept, palette: string) {
  const spots = ledSpots(cabinets)
  const mesh = new InstancedMesh(new BoxGeometry(0.08, 0.08, 0.16), new MeshBasicMaterial({
    color: '#ffffff',
    blending: AdditiveBlending,
    depthWrite: false,
    transparent: true,
  }), spots.length)
  mesh.name = 'atmos-led'
  mesh.userData.leds = spots
  const color = new Color(paletteOf(palette).accent)
  spots.forEach((spot, index) => {
    placeBox(mesh, index, spot.x, spot.y, spot.z, 1, 1, 1, 0)
    mesh.setColorAt(index, color)
  })
  mesh.instanceMatrix.needsUpdate = true
  if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true
  addDrawn(root, kept, mesh)
}

function addScreens(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const look = paletteOf(resolved.palette)
  const mat = new ShaderMaterial({
    uniforms: {
      uColor: { value: new Color(look.accent) },
      uSweep: { value: 0 },
      uGain: { value: resolved.timeOfDay === 'burst' ? 1.45 : 0.62 },
    },
    vertexShader: SCREEN_VERTEX,
    fragmentShader: SCREEN_FRAGMENT,
  })
  const mesh = new InstancedMesh(new PlaneGeometry(1.35, 1.7), mat, 3)
  mesh.name = 'atmos-screen'
  ;[-1.15, 0.7, 2.35].forEach((x, index) => placeBox(mesh, index, x, 2.55, -6.5, 1, 1, 1, 0))
  mesh.instanceMatrix.needsUpdate = true
  addDrawn(root, kept, mesh)
}

function addReels(root: Group, reels: readonly Reel[], kept: Kept) {
  const mesh = new InstancedMesh(new CylinderGeometry(1, 1, 1, 12), new MeshBasicMaterial({ color: '#c5a15a' }), reels.length)
  mesh.name = 'atmos-reel'
  reels.forEach((reel, index) => placeBox(mesh, index, reel.x, reel.y, reel.z, reel.r, 0.12, reel.r, Math.PI / 2))
  mesh.instanceMatrix.needsUpdate = true
  addDrawn(root, kept, mesh)
}

function addDrives(root: Group, drives: readonly Drive[], kept: Kept) {
  const mesh = new InstancedMesh(new BoxGeometry(1, 1, 1), new MeshBasicMaterial({ color: '#1a1e24' }), drives.length)
  mesh.name = 'atmos-drive'
  drives.forEach((drive, index) => placeBox(mesh, index, drive.x, drive.h / 2, drive.z, drive.w, drive.h, drive.d, 0))
  mesh.instanceMatrix.needsUpdate = true
  addDrawn(root, kept, mesh)
}

function addCables(root: Group, beads: readonly Bead[], kept: Kept) {
  const mesh = new InstancedMesh(new BoxGeometry(0.1, 0.1, 0.1), new MeshBasicMaterial({ color: '#2a241c' }), beads.length)
  mesh.name = 'atmos-cable'
  beads.forEach((bead, index) => placeBox(mesh, index, bead.x, bead.y, bead.z, 1, 1, 1, 0))
  mesh.instanceMatrix.needsUpdate = true
  addDrawn(root, kept, mesh)
}

function addBeam(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const geo = new ConeGeometry(1.35, 6.4, 16, 1, true)
  geo.rotateX(Math.PI)
  const mat = new MeshBasicMaterial({
    color: paletteOf(resolved.palette).accent,
    transparent: true,
    opacity: resolved.timeOfDay === 'burst' ? 0.2 : 0.08,
    blending: AdditiveBlending,
    depthWrite: false,
    side: BackSide,
  })
  const mesh = new Mesh(geo, mat)
  mesh.name = 'atmos-beam'
  mesh.position.set(CLEARING_SUBJECT[0], 3.3, CLEARING_SUBJECT[2])
  addDrawn(root, kept, mesh)
}

function addMotes(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const positions: number[] = []
  for (let index = 0; index < resolved.moteCount; index += 1) {
    const angle = hash2(index, 1, resolved.seed) * Math.PI * 2
    const radius = 0.12 + hash2(index, 2, resolved.seed) * 0.72
    positions.push(
      CLEARING_SUBJECT[0] + Math.cos(angle) * radius,
      0.45 + hash2(index, 3, resolved.seed) * 4.4,
      CLEARING_SUBJECT[2] + Math.sin(angle) * radius,
    )
  }
  const geo = new BufferGeometry()
  geo.setAttribute('position', new Float32BufferAttribute(positions, 3))
  const mat = new PointsMaterial({
    color: paletteOf(resolved.palette).accent,
    size: 0.035,
    sizeAttenuation: true,
    depthWrite: false,
  })
  const points = new Points(geo, mat)
  points.name = 'atmos-mote'
  points.userData.base = positions.slice()
  addDrawn(root, kept, points)
}

function addPad(root: Group, kept: Kept) {
  const geo = new CircleGeometry(1.05, 24)
  geo.rotateX(-Math.PI / 2)
  const mesh = new Mesh(geo, new MeshBasicMaterial({ color: '#05060a' }))
  mesh.name = 'atmos-pad'
  mesh.position.set(CLEARING_SUBJECT[0], 0.02, CLEARING_SUBJECT[2])
  addDrawn(root, kept, mesh)
}

function flatHall(resolved: ResolvedAtmos): { root: Group; kept: Kept } {
  const root = new Group()
  root.name = 'atmos-silicon-mainframe'
  const kept = emptyKept()
  const geo = new PlaneGeometry(10, 10)
  geo.rotateX(-Math.PI / 2)
  const mesh = new Mesh(geo, new MeshBasicMaterial({ color: paletteOf(resolved.palette).ground }))
  mesh.name = 'atmos-pad'
  mesh.position.set(CLEARING_SUBJECT[0], 0, CLEARING_SUBJECT[2])
  addDrawn(root, kept, mesh)
  return { root, kept }
}

function paintScreens(root: Group, settings: AtmosSettings, seconds: number) {
  const mesh = root.getObjectByName('atmos-screen') as InstancedMesh | undefined
  if (!mesh) return
  const mat = mesh.material as ShaderMaterial
  mat.uniforms.uSweep.value = (seconds * scanRate(settings.timeOfDay)) % 1
  mat.uniforms.uGain.value = settings.timeOfDay === 'burst' ? 1.45 : 0.62
  ;(mat.uniforms.uColor.value as Color).set(paletteOf(settings.palette).accent)
}

function paintLeds(root: Group, resolved: ResolvedAtmos, seconds: number) {
  const leds = root.getObjectByName('atmos-led') as InstancedMesh | undefined
  const spots = leds?.userData.leds as LedSpot[] | undefined
  if (!leds || !spots) return
  const cabinets = Math.max(1, Math.round(spots.length / 6))
  const dummy = new Object3D()
  const on = new Color(paletteOf(resolved.palette).accent)
  const off = new Color('#041208')
  spots.forEach((spot, index) => {
    const cabinet = Math.floor(index / 6)
    const lit = cabinetLit(cabinet, cabinets, resolved.variant, seconds, resolved.timeOfDay, resolved.seed)
    dummy.position.set(spot.x, spot.y, spot.z)
    dummy.rotation.set(0, 0, 0)
    dummy.scale.set(1, lit ? 1 : 0.15, 1)
    dummy.updateMatrix()
    leds.setMatrixAt(index, dummy.matrix)
    leds.setColorAt(index, lit ? on : off)
  })
  leds.instanceMatrix.needsUpdate = true
  if (leds.instanceColor) leds.instanceColor.needsUpdate = true
}

function paintMotes(root: Group, seconds: number, time: string, seed: number) {
  const points = root.getObjectByName('atmos-mote') as Points | undefined
  const base = points?.userData.base as number[] | undefined
  if (!points || !base) return
  const attr = points.geometry.getAttribute('position')
  const rate = time === 'burst' ? 1.4 : 0.45
  for (let index = 0; index < attr.count; index += 1) {
    const phase = hash2(index, 5, seed)
    attr.setY(index, base[index * 3 + 1] + Math.sin(seconds * rate + phase * 6.2) * 0.08)
  }
  attr.needsUpdate = true
}

function paintBeam(root: Group, settings: AtmosSettings) {
  const beam = root.getObjectByName('atmos-beam') as Mesh | undefined
  if (!beam) return
  const mat = beam.material as MeshBasicMaterial
  mat.color.set(paletteOf(settings.palette).accent)
  mat.opacity = settings.timeOfDay === 'burst' ? 0.2 : 0.08
}

function tuneFog(root: Group, density: number) {
  const fog = (root.parent as { fog?: unknown } | null)?.fog
  if (fog instanceof FogExp2) fog.density = 0.016 + density * 0.022
}

function syncHall(root: Group, seconds: number, resolved: ResolvedAtmos, live?: AtmosSettings) {
  const settings = live ?? resolved
  const next = { ...resolved, ...settings }
  paintScreens(root, next, seconds)
  paintLeds(root, next, seconds)
  paintMotes(root, seconds, next.timeOfDay, next.seed)
  paintBeam(root, next)
  tuneFog(root, next.fogDensity)
}

function liveHandle(root: Group, kept: Kept, resolved: ResolvedAtmos): AtmosHandle {
  return {
    ms: { shafts: 0, dof: 0, grade: 0 },
    passes: () => [],
    sync: (seconds, _camera, _light, _quality, _focus, live) => syncHall(root, seconds, resolved, live),
    dispose: disposeOnce(() => disposeKept(root, kept)),
  }
}

export function buildSiliconMainframe(resolved: ResolvedAtmos, webgl2: boolean): { root: Group; handle: AtmosHandle } {
  if (!webgl2) {
    const flat = flatHall(resolved)
    const handle = idleHandle(flat.root, flat.kept)
    flat.root.userData.atmos = handle
    return { root: flat.root, handle }
  }
  const root = new Group()
  root.name = 'atmos-silicon-mainframe'
  const kept = emptyKept()
  const cabinets = mainframeCabinets(Math.max(4, resolved.grassBlades))
  addSky(root, resolved, kept)
  addRoom(root, kept)
  addFloor(root, resolved, kept)
  addHaze(root, resolved, kept)
  addCabinets(root, cabinets, kept)
  addLeds(root, cabinets, kept, resolved.palette)
  addScreens(root, resolved, kept)
  addReels(root, tapeReels(), kept)
  addDrives(root, diskDrives(), kept)
  addCables(root, cableBeads(), kept)
  addBeam(root, resolved, kept)
  addMotes(root, resolved, kept)
  addPad(root, kept)
  const handle = liveHandle(root, kept, resolved)
  root.userData.atmos = handle
  return { root, handle }
}

export const siliconMainframeSet: AtmosSetDefinition = {
  id: 'atmos-silicon-mainframe',
  titleKey: 'template.atmos-silicon-mainframe-wide.title',
  setting: 'mainframe',
  seed: 88023,
  subject: CLEARING_SUBJECT,
  subjectYaw: 0.15,
  palettes: FRAME_PALETTES,
  times: FRAME_TIMES,
  defaults: { timeOfDay: 'idle', fogDensity: 0.28, wind: 0.04, motes: 0.55, palette: 'phosphor', variant: 4 },
  variant: { labelKey: 'atmos.lit', min: 0, max: 8 },
  low: { shaftSteps: 0, grassBlades: 8, moteCount: 24 },
  high: { shaftSteps: 0, grassBlades: 14, moteCount: 48 },
  templates: [
    { id: 'atmos-silicon-mainframe-wide', camera: 'establishment', eye: WIDE_EYE, look: WIDE_LOOK, fov: 50, duration: 6 },
    { id: 'atmos-silicon-mainframe-low', camera: 'establishment', eye: LOW_EYE, look: LOW_LOOK, fov: 58, duration: 6 },
  ],
  build: buildSiliconMainframe,
  fallback(resolved) {
    const sky = FRAME_PALETTES[resolved.palette as keyof typeof FRAME_PALETTES]?.fog ?? FRAME_PALETTES.phosphor.fog
    const ground = FRAME_PALETTES[resolved.palette as keyof typeof FRAME_PALETTES]?.ground ?? FRAME_PALETTES.phosphor.ground
    return { sky: hexColor(sky), ground: hexColor(ground) }
  },
}
