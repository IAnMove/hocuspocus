import {
  AdditiveBlending,
  BackSide,
  BufferGeometry,
  CircleGeometry,
  DoubleSide,
  Color,
  ConeGeometry,
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
  RingGeometry,
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

const GRID_VERTEX = `
  varying vec3 vWorld;
  void main() {
    vec4 world = modelMatrix * vec4(position, 1.0);
    vWorld = world.xyz;
    gl_Position = projectionMatrix * viewMatrix * world;
  }
`
const GRID_FRAGMENT = `
  uniform vec3 uLine;
  uniform vec3 uFloor;
  uniform float uScroll;
  uniform float uDensity;
  uniform float uGain;
  varying vec3 vWorld;
  void main() {
    vec2 p = vec2(vWorld.x, vWorld.z + uScroll);
    vec2 cell = abs(fract(p * uDensity) - 0.5);
    vec2 major = abs(fract(p * uDensity * 0.25) - 0.5);
    float fine = 1.0 - smoothstep(0.0, 0.09, min(cell.x, cell.y) * 2.0);
    float bold = 1.0 - smoothstep(0.0, 0.16, min(major.x, major.y) * 2.0);
    float line = max(fine, bold * 1.35);
    float fade = exp(-length(vWorld.xz) * 0.028);
    gl_FragColor = vec4(uFloor + uLine * (line * fade * uGain), 1.0);
  }
`
const SUN_VERTEX = `
  varying vec2 vUv;
  varying float vWorldY;
  void main() {
    vUv = uv;
    vec4 world = modelMatrix * vec4(position, 1.0);
    vWorldY = world.y;
    gl_Position = projectionMatrix * viewMatrix * world;
  }
`
const SUN_FRAGMENT = `
  uniform vec3 uTop;
  uniform vec3 uBottom;
  uniform float uClip;
  varying vec2 vUv;
  varying float vWorldY;
  void main() {
    if (vWorldY < uClip) discard;
    float y = clamp(vUv.y, 0.0, 1.0);
    vec3 grad = mix(uBottom, uTop, y);
    float bands = mix(16.0, 5.0, y);
    float stripe = step(0.46, fract(y * bands));
    gl_FragColor = vec4(grad * mix(0.06, 1.0, stripe), 1.0);
  }
`
const SKY_VERTEX = `
  varying vec3 vDir;
  void main() {
    vec4 world = modelMatrix * vec4(position, 1.0);
    vDir = world.xyz;
    gl_Position = projectionMatrix * viewMatrix * world;
  }
`
const SKY_FRAGMENT = `
  uniform vec3 uHigh;
  uniform vec3 uMid;
  uniform vec3 uLow;
  varying vec3 vDir;
  void main() {
    float h = clamp(normalize(vDir).y * 0.5 + 0.45, 0.0, 1.0);
    vec3 color = mix(uLow, uMid, smoothstep(0.0, 0.42, h));
    color = mix(color, uHigh, smoothstep(0.38, 1.0, h));
    gl_FragColor = vec4(color, 1.0);
  }
`

const WIDE_EYE = [0.2, 1.35, 3.4] as const
const WIDE_LOOK = [0.15, 1.05, -12] as const
const LOW_EYE = [0.85, 0.28, 0.35] as const
const LOW_LOOK = [0.1, 0.85, -14] as const
const SUN_Z = -22
const GRID_PALETTES = {
  outrun: { fog: '#120458', ground: '#05010f', accent: '#05d9e8', sky: ['#7a04eb', '#ff2a6d'] },
  chrome: { fog: '#01012b', ground: '#02020a', accent: '#d1f7ff', sky: ['#005678', '#ffd166'] },
} as const
const GRID_TIMES = {
  dusk: { sun: [0.04, -0.42, -0.91] as const, sunColor: '#ffd1ea' },
  night: { sun: [0.02, -0.16, -0.99] as const, sunColor: '#9aa4ff' },
}
const LINE: Record<string, string> = { outrun: '#05d9e8', chrome: '#d1f7ff' }
const SECOND: Record<string, string> = { outrun: '#ff6ec7', chrome: '#ffd166' }
const SUN_TOP: Record<string, string> = { outrun: '#ff2a6d', chrome: '#ffd166' }
const SUN_BOTTOM: Record<string, string> = { outrun: '#7a04eb', chrome: '#005678' }
const SKY_HIGH: Record<string, string> = { outrun: '#120458', chrome: '#01012b' }
const FALLBACK_GROUND: Record<string, string> = { outrun: '#05010f', chrome: '#02020a' }

function emptyKept(): Kept {
  return { geometries: [], materials: [] }
}

function hexColor(color: string): [number, number, number] {
  const n = Number.parseInt(color.slice(1), 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

function gridAmount(variant: number | undefined): number {
  const value = typeof variant === 'number' && Number.isFinite(variant) ? variant : 4
  return Math.min(8, Math.max(0, value))
}

function gridDensity(variant: number | undefined): number {
  return 0.95 + gridAmount(variant) * 0.22
}

function gridSpeed(variant: number | undefined): number {
  return 0.7 + gridAmount(variant) * 0.28
}

function gridGain(time: string): number {
  return time === 'night' ? 1.45 : 0.78
}

function sunHeight(time: string): number {
  return time === 'night' ? 0.62 : 3.55
}

function starSize(time: string): number {
  return time === 'night' ? 0.055 : 0.028
}

function swatch(table: Record<string, string>, palette: string): string {
  return table[palette] ?? table.outrun
}

function paletteOf(name: string) {
  if (name === 'chrome') return GRID_PALETTES.chrome
  return GRID_PALETTES.outrun
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

function idleHandle(root: Group, kept: Kept): AtmosHandle {
  return {
    ms: { shafts: 0, dof: 0, grade: 0 },
    passes: () => [],
    sync: () => {},
    dispose: disposeOnce(() => disposeKept(root, kept)),
  }
}

function flatGrid(resolved: ResolvedAtmos): { root: Group; kept: Kept } {
  const root = new Group()
  root.name = 'atmos-silicon-grid'
  const kept = emptyKept()
  const geo = new PlaneGeometry(8, 8)
  geo.rotateX(-Math.PI / 2)
  const mat = new MeshBasicMaterial({ color: paletteOf(resolved.palette).ground })
  const mesh = new Mesh(geo, mat)
  mesh.name = 'atmos-pad'
  mesh.position.set(CLEARING_SUBJECT[0], 0, CLEARING_SUBJECT[2])
  addDrawn(root, kept, mesh)
  return { root, kept }
}

function addSky(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const look = paletteOf(resolved.palette)
  const geo = new SphereGeometry(48, 16, 12)
  const mat = new ShaderMaterial({
    side: BackSide,
    depthWrite: false,
    uniforms: {
      uHigh: { value: new Color(swatch(SKY_HIGH, resolved.palette)) },
      uMid: { value: new Color(look.sky[0]) },
      uLow: { value: new Color(look.sky[1]) },
    },
    vertexShader: SKY_VERTEX,
    fragmentShader: SKY_FRAGMENT,
  })
  const mesh = new Mesh(geo, mat)
  mesh.name = 'atmos-sky'
  mesh.frustumCulled = false
  addDrawn(root, kept, mesh)
}

function addGrid(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const look = paletteOf(resolved.palette)
  const geo = new PlaneGeometry(64, 64, 1, 1)
  geo.rotateX(-Math.PI / 2)
  const mat = new ShaderMaterial({
    uniforms: {
      uLine: { value: new Color(swatch(LINE, resolved.palette)) },
      uFloor: { value: new Color(look.ground) },
      uScroll: { value: 0 },
      uDensity: { value: gridDensity(resolved.variant) },
      uGain: { value: gridGain(resolved.timeOfDay) },
    },
    vertexShader: GRID_VERTEX,
    fragmentShader: GRID_FRAGMENT,
  })
  const mesh = new Mesh(geo, mat)
  mesh.name = 'atmos-grid'
  mesh.position.y = 0
  addDrawn(root, kept, mesh)
}

function addSun(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const geo = new CircleGeometry(5.6, 48)
  const mat = new ShaderMaterial({
    uniforms: {
      uTop: { value: new Color(swatch(SUN_TOP, resolved.palette)) },
      uBottom: { value: new Color(swatch(SUN_BOTTOM, resolved.palette)) },
      uClip: { value: 0.04 },
    },
    vertexShader: SUN_VERTEX,
    fragmentShader: SUN_FRAGMENT,
  })
  const mesh = new Mesh(geo, mat)
  mesh.name = 'atmos-sun'
  mesh.position.set(0.2, sunHeight(resolved.timeOfDay), SUN_Z)
  addDrawn(root, kept, mesh)
  const haloGeo = new CircleGeometry(8.2, 32)
  const haloMat = new MeshBasicMaterial({
    color: swatch(SUN_TOP, resolved.palette),
    transparent: true,
    opacity: 0.22,
    blending: AdditiveBlending,
    depthWrite: false,
  })
  const halo = new Mesh(haloGeo, haloMat)
  halo.name = 'atmos-halo'
  halo.position.copy(mesh.position)
  halo.position.z += 0.2
  addDrawn(root, kept, halo)
}

function peakCount(row: number, total: number): number {
  const near = Math.ceil(total * 0.45)
  return row === 0 ? near : Math.max(0, total - near)
}

function placePeak(mesh: InstancedMesh, slot: number, local: number, row: number, seed: number, total: number, bulge: number) {
  const count = peakCount(row, total)
  const span = row === 0 ? 16 : 28
  const x = count <= 1 ? 0 : -span / 2 + (span / (count - 1)) * local
  const height = (row === 0 ? 1.4 : 2.2) + hash2(local, row + 3, seed) * (row === 0 ? 1.6 : 2.8)
  const width = (0.85 + hash2(local, 8, seed) * 0.7) * bulge
  const dummy = new Object3D()
  dummy.position.set(x, height / 2, row === 0 ? -8.2 : -16.5)
  dummy.scale.set(width, height * bulge, width)
  dummy.rotation.y = hash2(local, 5, seed) * 0.6
  dummy.updateMatrix()
  mesh.setMatrixAt(slot, dummy.matrix)
}

function addPeaks(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const total = resolved.grassBlades
  const near = peakCount(0, total)
  const geo = new ConeGeometry(1, 1, 4)
  const body = new InstancedMesh(geo, new MeshBasicMaterial({ color: '#070212' }), total)
  body.name = 'atmos-peak'
  const wire = new InstancedMesh(geo, new MeshBasicMaterial({ color: swatch(LINE, resolved.palette), wireframe: true }), total)
  wire.name = 'atmos-wire'
  for (let index = 0; index < total; index += 1) {
    const row = index < near ? 0 : 1
    const local = row === 0 ? index : index - near
    placePeak(body, index, local, row, resolved.seed, total, 1)
    placePeak(wire, index, local, row, resolved.seed, total, 1.02)
    const dim = row === 0 ? 1 : 0.42
    body.setColorAt(index, new Color('#12081c').multiplyScalar(dim))
    wire.setColorAt(index, new Color(swatch(row === 0 ? LINE : SECOND, resolved.palette)).multiplyScalar(dim))
  }
  body.instanceMatrix.needsUpdate = true
  wire.instanceMatrix.needsUpdate = true
  if (body.instanceColor) body.instanceColor.needsUpdate = true
  if (wire.instanceColor) wire.instanceColor.needsUpdate = true
  addDrawn(root, kept, body)
  addDrawn(root, kept, wire)
}

function addStars(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const count = resolved.moteCount
  const positions: number[] = []
  for (let index = 0; index < count; index += 1) {
    const theta = hash2(index, 2, resolved.seed) * Math.PI * 2
    const lift = 0.15 + hash2(index, 4, resolved.seed) * 0.75
    const radius = 30 + hash2(index, 6, resolved.seed) * 12
    positions.push(Math.cos(theta) * radius * 0.7, 4 + lift * 22, -8 - Math.sin(theta) * radius)
  }
  const geo = new BufferGeometry()
  geo.setAttribute('position', new Float32BufferAttribute(positions, 3))
  const mat = new PointsMaterial({
    color: swatch(LINE, resolved.palette),
    size: starSize(resolved.timeOfDay),
    sizeAttenuation: true,
    depthWrite: false,
  })
  const points = new Points(geo, mat)
  points.name = 'atmos-star'
  addDrawn(root, kept, points)
}

function shipGeometry(): BufferGeometry {
  const geo = new BufferGeometry()
  geo.setAttribute('position', new Float32BufferAttribute([0, 0.22, 0, -0.42, -0.1, 0, 0.42, -0.1, 0], 3))
  return geo
}

function shipSpot(index: number, seconds: number): [number, number, number] {
  const phase = index * 1.8
  const x = (index === 0 ? -7.4 : 6.6) + Math.sin(seconds * 0.21 + phase) * 1.6
  const y = 5.1 + index * 1.35 + Math.sin(seconds * 0.17 + phase) * 0.18
  return [x, y, -13.5 - index * 2.4]
}

function addShips(root: Group, kept: Kept) {
  const ships = new InstancedMesh(shipGeometry(), new MeshBasicMaterial({ color: '#ff6ec7', side: DoubleSide }), 2)
  ships.name = 'atmos-ship'
  const trails = new InstancedMesh(new PlaneGeometry(1.4, 0.06), new MeshBasicMaterial({
    color: '#05d9e8',
    transparent: true,
    opacity: 0.85,
    blending: AdditiveBlending,
    depthWrite: false,
  }), 2)
  trails.name = 'atmos-trail'
  addDrawn(root, kept, ships)
  addDrawn(root, kept, trails)
}

function addPad(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const geo = new CircleGeometry(1.05, 24)
  geo.rotateX(-Math.PI / 2)
  const mat = new MeshBasicMaterial({ color: '#070212', transparent: true, opacity: 0.72 })
  const mesh = new Mesh(geo, mat)
  mesh.name = 'atmos-pad'
  mesh.position.set(CLEARING_SUBJECT[0], 0.02, CLEARING_SUBJECT[2])
  addDrawn(root, kept, mesh)
  const rim = new RingGeometry(0.92, 1.08, 32)
  rim.rotateX(-Math.PI / 2)
  const rimMat = new MeshBasicMaterial({ color: swatch(LINE, resolved.palette) })
  const ring = new Mesh(rim, rimMat)
  ring.name = 'atmos-rim'
  ring.position.copy(mesh.position)
  ring.position.y += 0.01
  addDrawn(root, kept, ring)
}

function poseShips(root: Group, seconds: number, palette: string) {
  const ships = root.getObjectByName('atmos-ship') as InstancedMesh | undefined
  const trails = root.getObjectByName('atmos-trail') as InstancedMesh | undefined
  if (!ships || !trails) return
  const dummy = new Object3D()
  const shipColor = new Color(swatch(SECOND, palette))
  const trailColor = new Color(swatch(LINE, palette))
  for (let index = 0; index < 2; index += 1) {
    const [x, y, z] = shipSpot(index, seconds)
    dummy.position.set(x, y, z)
    dummy.rotation.set(0, seconds * 0.05 + index, 0)
    dummy.scale.set(1, 1, 1)
    dummy.updateMatrix()
    ships.setMatrixAt(index, dummy.matrix)
    ships.setColorAt(index, shipColor)
    dummy.position.set(x, y - 0.05, z + 0.85)
    dummy.rotation.set(-Math.PI / 2, 0, 0)
    dummy.scale.set(1, 1, 1)
    dummy.updateMatrix()
    trails.setMatrixAt(index, dummy.matrix)
    trails.setColorAt(index, trailColor)
  }
  ships.instanceMatrix.needsUpdate = true
  trails.instanceMatrix.needsUpdate = true
  if (ships.instanceColor) ships.instanceColor.needsUpdate = true
  if (trails.instanceColor) trails.instanceColor.needsUpdate = true
}

function paintGrid(root: Group, settings: AtmosSettings, seconds: number) {
  const mesh = root.getObjectByName('atmos-grid') as Mesh | undefined
  if (!mesh) return
  const mat = mesh.material as ShaderMaterial
  mat.uniforms.uScroll.value = seconds * gridSpeed(settings.variant)
  mat.uniforms.uDensity.value = gridDensity(settings.variant)
  mat.uniforms.uGain.value = gridGain(settings.timeOfDay)
  ;(mat.uniforms.uLine.value as Color).set(swatch(LINE, settings.palette))
  ;(mat.uniforms.uFloor.value as Color).set(paletteOf(settings.palette).ground)
}

function paintSun(root: Group, settings: AtmosSettings) {
  const sun = root.getObjectByName('atmos-sun') as Mesh | undefined
  const halo = root.getObjectByName('atmos-halo') as Mesh | undefined
  if (!sun || !halo) return
  sun.position.y = sunHeight(settings.timeOfDay)
  halo.position.y = sun.position.y
  const mat = sun.material as ShaderMaterial
  ;(mat.uniforms.uTop.value as Color).set(swatch(SUN_TOP, settings.palette))
  ;(mat.uniforms.uBottom.value as Color).set(swatch(SUN_BOTTOM, settings.palette))
  const glow = halo.material as MeshBasicMaterial
  glow.color.set(swatch(SUN_TOP, settings.palette))
  glow.opacity = settings.timeOfDay === 'night' ? 0.14 : 0.28
}

function paintSky(root: Group, settings: AtmosSettings) {
  const sky = root.getObjectByName('atmos-sky') as Mesh | undefined
  if (!sky) return
  const look = paletteOf(settings.palette)
  const mat = sky.material as ShaderMaterial
  ;(mat.uniforms.uHigh.value as Color).set(swatch(SKY_HIGH, settings.palette))
  ;(mat.uniforms.uMid.value as Color).set(look.sky[0])
  ;(mat.uniforms.uLow.value as Color).set(look.sky[1])
  const stars = root.getObjectByName('atmos-star') as Points | undefined
  if (!stars) return
  const points = stars.material as PointsMaterial
  points.color.set(swatch(LINE, settings.palette))
  points.size = starSize(settings.timeOfDay)
}

function tuneFog(root: Group, density: number) {
  const fog = (root.parent as { fog?: unknown } | null)?.fog
  if (fog instanceof FogExp2) fog.density = 0.01 + density * 0.02
}

function syncGrid(root: Group, seconds: number, resolved: ResolvedAtmos, live?: AtmosSettings) {
  const settings = live ?? resolved
  paintGrid(root, settings, seconds)
  paintSun(root, settings)
  paintSky(root, settings)
  poseShips(root, seconds, settings.palette)
  tuneFog(root, settings.fogDensity)
}

function liveHandle(root: Group, kept: Kept, resolved: ResolvedAtmos): AtmosHandle {
  return {
    ms: { shafts: 0, dof: 0, grade: 0 },
    passes: () => [],
    sync: (seconds, _camera, _light, _quality, _focus, live) => syncGrid(root, seconds, resolved, live),
    dispose: disposeOnce(() => disposeKept(root, kept)),
  }
}

export function buildSiliconGrid(resolved: ResolvedAtmos, webgl2: boolean): { root: Group; handle: AtmosHandle } {
  if (!webgl2) {
    const flat = flatGrid(resolved)
    const handle = idleHandle(flat.root, flat.kept)
    flat.root.userData.atmos = handle
    return { root: flat.root, handle }
  }
  const root = new Group()
  root.name = 'atmos-silicon-grid'
  const kept = emptyKept()
  addSky(root, resolved, kept)
  addGrid(root, resolved, kept)
  addSun(root, resolved, kept)
  addPeaks(root, resolved, kept)
  addStars(root, resolved, kept)
  addShips(root, kept)
  addPad(root, resolved, kept)
  const handle = liveHandle(root, kept, resolved)
  root.userData.atmos = handle
  return { root, handle }
}

export const siliconGridSet: AtmosSetDefinition = {
  id: 'atmos-silicon-grid',
  titleKey: 'template.atmos-silicon-grid-wide.title',
  setting: 'grid',
  seed: 88021,
  subject: CLEARING_SUBJECT,
  subjectYaw: 0.15,
  palettes: GRID_PALETTES,
  times: GRID_TIMES,
  defaults: { timeOfDay: 'dusk', fogDensity: 0.18, wind: 0.15, motes: 0.6, palette: 'outrun', variant: 4 },
  variant: { labelKey: 'atmos.grid', min: 0, max: 8 },
  low: { shaftSteps: 0, grassBlades: 8, moteCount: 36 },
  high: { shaftSteps: 0, grassBlades: 14, moteCount: 72 },
  templates: [
    { id: 'atmos-silicon-grid-wide', camera: 'establishment', eye: WIDE_EYE, look: WIDE_LOOK, fov: 48, duration: 6 },
    { id: 'atmos-silicon-grid-low', camera: 'establishment', eye: LOW_EYE, look: LOW_LOOK, fov: 56, duration: 6 },
  ],
  build: buildSiliconGrid,
  fallback(resolved) {
    const sky = GRID_PALETTES[resolved.palette as keyof typeof GRID_PALETTES]?.fog ?? GRID_PALETTES.outrun.fog
    return { sky: hexColor(sky), ground: hexColor(FALLBACK_GROUND[resolved.palette] ?? FALLBACK_GROUND.outrun) }
  },
}
