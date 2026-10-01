import {
  BackSide,
  BufferGeometry,
  CircleGeometry,
  Color,
  DoubleSide,
  FogExp2,
  Group,
  InstancedBufferAttribute,
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
import { CLEARING_SUBJECT, scatter, type Area } from '../layout.ts'

type Kept = { geometries: BufferGeometry[]; materials: Material[] }
type Spot = [number, number]
type Cloud = [number, number, number, number, number, number]

// PlaneGeometry faces +z. rotateX(-PI/2) lays the meadow on y = 0 with the normal pointing up.
// Wind is added in world x after instanceMatrix, so a blade's yaw does not steer the gust.
const GRASS_VERTEX = `
  attribute float aPhase;
  uniform float uTime;
  uniform float uBend;
  varying float vH;
  varying float vTint;
  #include <fog_pars_vertex>
  void main() {
    vH = uv.y;
    vTint = fract(aPhase * 3.17);
    vec3 shaped = position;
    shaped.x *= mix(1.0, 0.22, uv.y);
    float sway = (0.72 + 0.28 * sin(uTime * 1.7 + aPhase)) * uBend;
    vec4 world = modelMatrix * instanceMatrix * vec4(shaped, 1.0);
    world.x += sway * position.y * position.y;
    vec4 mvPosition = viewMatrix * world;
    gl_Position = projectionMatrix * mvPosition;
    #include <fog_vertex>
  }
`
const GRASS_FRAGMENT = `
  uniform vec3 uBase;
  uniform vec3 uTip;
  uniform vec3 uBloom;
  varying float vH;
  varying float vTint;
  #include <fog_pars_fragment>
  void main() {
    vec3 color = mix(uBase, uTip, vH);
    color *= mix(0.84, 1.08, vTint);
    color = mix(color, uBloom, step(0.94, vTint) * vH);
    gl_FragColor = vec4(color, 1.0);
    #include <fog_fragment>
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
    gl_FragColor = vec4(mix(uHorizon, uZenith, smoothstep(0.0, 0.48, vH)), 1.0);
  }
`

const LEFT: Area = { x0: -11.2, x1: -1.7, z0: -14.5, z1: 2.3 }
const RIGHT: Area = { x0: 2.35, x1: 11.2, z0: -14.5, z1: 2.3 }
const FAR: Area = { x0: -9.4, x1: 9.4, z0: -18.5, z1: -2.5 }
const CLOUD_SPOTS: Cloud[] = [
  [-6.4, 2.85, -8.2, 4.8, 0.72, 2.3],
  [-1.6, 3.05, -11.2, 5.6, 0.78, 2.5],
  [3.6, 2.75, -9.2, 5.0, 0.7, 2.2],
  [7.2, 3.15, -12.6, 5.2, 0.76, 2.4],
  [-4.6, 3.35, -15.0, 6.0, 0.82, 2.7],
  [0.3, 2.55, -6.6, 4.2, 0.62, 1.9],
  [5.6, 2.7, -6.2, 4.0, 0.64, 1.8],
  [-8.6, 3.2, -6.4, 4.6, 0.7, 2.1],
  [1.6, 3.45, -16.4, 6.4, 0.86, 2.8],
  [-3.4, 2.65, -7.4, 3.8, 0.6, 1.7],
  [8.8, 3.25, -9.0, 4.8, 0.72, 2.2],
  [-0.5, 2.95, -13.4, 5.4, 0.74, 2.4],
]

const FIELD: Record<string, string> = { clover: '#2f9a3e', hay: '#c9a044' }
const BARE: Record<string, string> = { clover: '#b7e38a', hay: '#f0e2a4' }
const BLADE: Record<string, string> = { clover: '#1d6630', hay: '#8a6424' }
const TIP: Record<string, string> = { clover: '#c8f270', hay: '#f6e08a' }
const BLOOM: Record<string, string> = { clover: '#ffe56a', hay: '#fff1b0' }
const CLOUD: Record<string, string> = { clover: '#f7fbff', hay: '#fff8ea' }
const CLOUD_GREY: Record<string, string> = { clover: '#d5dee6', hay: '#e4ddd0' }
const HORIZON: Record<string, string> = { clover: '#bfe3f6', hay: '#f0ddb0' }
const FALLBACK_GROUND: Record<string, string> = { clover: '#3d8c46', hay: '#c4a04c' }

const MEADOW_PALETTES = {
  clover: { fog: '#bfe3f6', ground: '#3d8c46', accent: '#8ed45a', sky: ['#bfe3f6', '#6eafdf'] },
  hay: { fog: '#f0ddb0', ground: '#c4a04c', accent: '#e8c86a', sky: ['#f0ddb0', '#b7c6d6'] },
} as const

const MEADOW_TIMES = {
  spring: { sun: [0.38, -0.74, -0.5], sunColor: '#fff6d8' },
  overcast: { sun: [0.1, -0.96, -0.22], sunColor: '#d7e0ea' },
} as const

const WIDE_EYE = [0.1, 1.7, 6.2] as const
const WIDE_LOOK = [0.15, 0.95, -7.5] as const
const LOW_EYE = [1.05, 0.48, 5.8] as const
const LOW_LOOK = [-2.8, 1.05, -4.4] as const

function emptyKept(): Kept {
  return { geometries: [], materials: [] }
}

function hexColor(color: string): [number, number, number] {
  const n = Number.parseInt(color.slice(1), 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

function swatch(table: Record<string, string>, palette: string): string {
  return table[palette] ?? table.clover
}

function breezeAmount(variant: number | undefined): number {
  const value = typeof variant === 'number' && Number.isFinite(variant) ? variant : 4
  return Math.min(8, Math.max(0, value))
}

function bendOf(variant: number | undefined): number {
  return 0.22 + breezeAmount(variant) * 0.1
}

function horizonHex(palette: string, time: string): string {
  if (time === 'overcast') return '#c5ced6'
  return swatch(HORIZON, palette)
}

function zenithHex(palette: string, time: string): string {
  if (time === 'overcast') return palette === 'hay' ? '#a39e94' : '#8e99a6'
  return palette === 'hay' ? '#b7c6d6' : '#6eafdf'
}

function cloudHex(palette: string, time: string): string {
  if (time === 'overcast') return swatch(CLOUD_GREY, palette)
  return swatch(CLOUD, palette)
}

function band(value: number, limit: number): number {
  const span = limit * 2
  let shifted = (value + limit) % span
  if (shifted < 0) shifted += span
  return shifted - limit
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

function grassSpots(count: number, seed: number): Spot[] {
  const left = Math.ceil(count * 0.4)
  const right = Math.ceil(count * 0.4)
  const far = Math.max(0, count - left - right)
  return [
    ...scatter(left, seed, 11, [], LEFT, 0.4),
    ...scatter(right, seed, 19, [], RIGHT, 0.4),
    ...scatter(far, seed, 29, [], FAR, 0.55),
  ]
}

function flatMeadow(resolved: ResolvedAtmos): { root: Group; kept: Kept } {
  const root = new Group()
  root.name = 'atmos-meadow'
  const kept = emptyKept()
  const geo = new PlaneGeometry(16, 16)
  geo.rotateX(-Math.PI / 2)
  const mat = new MeshBasicMaterial({ color: resolved.stone })
  root.add(new Mesh(geo, mat))
  kept.geometries.push(geo)
  kept.materials.push(mat)
  return { root, kept }
}

function addDisc(root: Group, kept: Kept, name: string, color: string, radius: number, y: number) {
  const geo = new CircleGeometry(radius, 28)
  geo.rotateX(-Math.PI / 2)
  const mat = new MeshBasicMaterial({ color, fog: false })
  const mesh = new Mesh(geo, mat)
  mesh.name = name
  mesh.position.set(CLEARING_SUBJECT[0], y, CLEARING_SUBJECT[2])
  mesh.frustumCulled = false
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function addGround(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  // Extends behind both cameras. A uniform unlit color still clips cleanly at the near plane.
  const geo = new PlaneGeometry(220, 420, 22, 40)
  geo.rotateX(-Math.PI / 2)
  geo.translate(0, 0, -190)
  const mat = new MeshBasicMaterial({ color: swatch(FIELD, resolved.palette), fog: false })
  const mesh = new Mesh(geo, mat)
  mesh.name = 'atmos-ground'
  mesh.frustumCulled = false
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
  addDisc(root, kept, 'atmos-clearing', swatch(BARE, resolved.palette), 1.55, 0.02)
}

function grassMaterial(resolved: ResolvedAtmos): ShaderMaterial {
  return new ShaderMaterial({
    uniforms: {
      uTime: { value: 0 },
      uBend: { value: bendOf(resolved.variant) },
      uBase: { value: new Color(swatch(BLADE, resolved.palette)) },
      uTip: { value: new Color(swatch(TIP, resolved.palette)) },
      uBloom: { value: new Color(swatch(BLOOM, resolved.palette)) },
    },
    vertexShader: GRASS_VERTEX,
    fragmentShader: GRASS_FRAGMENT,
    side: DoubleSide,
  })
}

function seatBlade(mesh: InstancedMesh, dummy: Object3D, spot: Spot, spotIndex: number, slot: number, seed: number, yaw: number, phases: Float32Array) {
  const height = 0.62 + hash2(spotIndex, 4, seed) * 0.48
  const width = 0.7 + hash2(spotIndex, 5, seed) * 0.55
  dummy.position.set(spot[0], 0, spot[1])
  dummy.rotation.set(0, yaw, 0)
  dummy.scale.set(width, height, 1)
  dummy.updateMatrix()
  mesh.setMatrixAt(slot, dummy.matrix)
  phases[slot] = hash2(slot, 6, seed) * Math.PI * 2
}

function addGrass(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const spots = grassSpots(resolved.grassBlades, resolved.seed)
  if (spots.length < 1) return
  const geo = new PlaneGeometry(0.42, 0.92, 1, 3)
  geo.translate(0, 0.46, 0)
  const phases = new Float32Array(spots.length * 2)
  const mat = grassMaterial(resolved)
  const mesh = new InstancedMesh(geo, mat, spots.length * 2)
  mesh.name = 'atmos-grass'
  mesh.frustumCulled = false
  const dummy = new Object3D()
  let slot = 0
  for (let index = 0; index < spots.length; index += 1) {
    const yaw = (hash2(index, 8, resolved.seed) - 0.5) * 0.8
    seatBlade(mesh, dummy, spots[index], index, slot, resolved.seed, yaw, phases)
    slot += 1
    seatBlade(mesh, dummy, spots[index], index, slot, resolved.seed, yaw + Math.PI / 2, phases)
    slot += 1
  }
  mesh.geometry.setAttribute('aPhase', new InstancedBufferAttribute(phases, 1))
  mesh.instanceMatrix.needsUpdate = true
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function placeClouds(mesh: InstancedMesh | undefined, seconds: number, bend: number) {
  const spots = mesh?.userData.spots as Cloud[] | undefined
  if (!mesh || !spots) return
  const speed = 0.55 + bend
  const dummy = new Object3D()
  for (let index = 0; index < spots.length; index += 1) {
    const spot = spots[index]
    const drift = band(spot[0] + seconds * speed, 12)
    dummy.position.set(drift, spot[1] + Math.sin(seconds * 0.35 + index) * 0.1, spot[2])
    dummy.rotation.set(0, 0, 0)
    dummy.scale.set(spot[3], spot[4], spot[5])
    dummy.updateMatrix()
    mesh.setMatrixAt(index, dummy.matrix)
  }
  mesh.instanceMatrix.needsUpdate = true
}

function addClouds(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const spots = CLOUD_SPOTS.slice(0, resolved.moteCount)
  if (spots.length < 1) return
  const geo = new SphereGeometry(1, 8, 6)
  const mat = new MeshBasicMaterial({ color: cloudHex(resolved.palette, resolved.timeOfDay) })
  const mesh = new InstancedMesh(geo, mat, spots.length)
  mesh.name = 'atmos-cloud'
  mesh.frustumCulled = false
  mesh.userData.spots = spots
  placeClouds(mesh, 0, bendOf(resolved.variant))
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function addSky(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const geo = new SphereGeometry(48, 16, 10)
  const mat = new ShaderMaterial({
    uniforms: {
      uHorizon: { value: new Color(horizonHex(resolved.palette, resolved.timeOfDay)) },
      uZenith: { value: new Color(zenithHex(resolved.palette, resolved.timeOfDay)) },
    },
    vertexShader: SKY_VERTEX,
    fragmentShader: SKY_FRAGMENT,
    side: BackSide,
    fog: false,
  })
  const mesh = new Mesh(geo, mat)
  mesh.name = 'atmos-sky'
  mesh.frustumCulled = false
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function paintGrass(mesh: InstancedMesh | undefined, seconds: number, bend: number, palette: string) {
  const material = mesh?.material
  if (!(material instanceof ShaderMaterial)) return
  material.uniforms.uTime.value = seconds
  material.uniforms.uBend.value = bend
  material.uniforms.uBase.value.set(swatch(BLADE, palette))
  material.uniforms.uTip.value.set(swatch(TIP, palette))
  material.uniforms.uBloom.value.set(swatch(BLOOM, palette))
}

function paintClouds(mesh: InstancedMesh | undefined, palette: string, time: string) {
  const material = mesh?.material
  if (!(material instanceof MeshBasicMaterial)) return
  material.color.set(cloudHex(palette, time))
}

function paintBasic(root: Group, name: string, color: string) {
  const mesh = root.getObjectByName(name) as Mesh | undefined
  const material = mesh?.material
  if (material instanceof MeshBasicMaterial) material.color.set(color)
}

function paintGround(root: Group, palette: string) {
  paintBasic(root, 'atmos-ground', swatch(FIELD, palette))
  paintBasic(root, 'atmos-clearing', swatch(BARE, palette))
}

function paintSky(root: Group, palette: string, time: string) {
  const mesh = root.getObjectByName('atmos-sky') as Mesh | undefined
  const material = mesh?.material
  if (!(material instanceof ShaderMaterial)) return
  material.uniforms.uHorizon.value.set(horizonHex(palette, time))
  material.uniforms.uZenith.value.set(zenithHex(palette, time))
}

function paintFog(root: Group, palette: string, time: string, density: number) {
  const parent = root.parent as { fog?: unknown; background?: unknown } | null
  if (!(parent?.fog instanceof FogExp2)) return
  parent.fog.density = 0.014 + density * 0.034
  parent.fog.color.set(horizonHex(palette, time))
  if (parent.background instanceof Color) parent.background.set(horizonHex(palette, time))
}

function syncMeadow(root: Group, seconds: number, resolved: ResolvedAtmos, live?: AtmosSettings) {
  const settings = live ?? resolved
  const bend = bendOf(settings.variant)
  const clouds = root.getObjectByName('atmos-cloud') as InstancedMesh | undefined
  paintGrass(root.getObjectByName('atmos-grass') as InstancedMesh | undefined, seconds, bend, settings.palette)
  placeClouds(clouds, seconds, bend)
  paintClouds(clouds, settings.palette, settings.timeOfDay)
  paintGround(root, settings.palette)
  paintSky(root, settings.palette, settings.timeOfDay)
  paintFog(root, settings.palette, settings.timeOfDay, settings.fogDensity)
}

function liveHandle(root: Group, kept: Kept, resolved: ResolvedAtmos): AtmosHandle {
  return {
    ms: { shafts: 0, dof: 0, grade: 0 },
    passes: () => [],
    sync: (seconds, _camera, _light, _quality, _focus, live) => syncMeadow(root, seconds, resolved, live),
    dispose: disposeOnce(() => disposeKept(root, kept)),
  }
}

export function buildMeadow(resolved: ResolvedAtmos, webgl2: boolean): { root: Group; handle: AtmosHandle } {
  if (!webgl2) {
    const flat = flatMeadow(resolved)
    const handle = idleHandle(flat.root, flat.kept)
    flat.root.userData.atmos = handle
    return { root: flat.root, handle }
  }
  const root = new Group()
  root.name = 'atmos-meadow'
  const kept = emptyKept()
  addGround(root, resolved, kept)
  addGrass(root, resolved, kept)
  addClouds(root, resolved, kept)
  addSky(root, resolved, kept)
  const handle = liveHandle(root, kept, resolved)
  root.userData.atmos = handle
  return { root, handle }
}

export const meadowSet: AtmosSetDefinition = {
  id: 'atmos-meadow',
  titleKey: 'template.atmos-meadow-wide.title',
  setting: 'forest',
  seed: 96017,
  subject: CLEARING_SUBJECT,
  subjectYaw: 0.15,
  palettes: MEADOW_PALETTES,
  times: MEADOW_TIMES,
  defaults: { timeOfDay: 'spring', fogDensity: 0.16, wind: 0.55, motes: 0.3, palette: 'clover', variant: 4 },
  variant: { labelKey: 'atmos.breeze', min: 0, max: 8 },
  low: { shaftSteps: 0, grassBlades: 100, moteCount: 8 },
  high: { shaftSteps: 0, grassBlades: 140, moteCount: 12 },
  templates: [
    { id: 'atmos-meadow-wide', camera: 'establishment', eye: WIDE_EYE, look: WIDE_LOOK, fov: 50, duration: 6 },
    { id: 'atmos-meadow-low', camera: 'establishment', eye: LOW_EYE, look: LOW_LOOK, fov: 56, duration: 6 },
  ],
  build: buildMeadow,
  fallback(resolved) {
    const sky = MEADOW_PALETTES[resolved.palette as keyof typeof MEADOW_PALETTES]?.fog ?? MEADOW_PALETTES.clover.fog
    return { sky: hexColor(sky), ground: hexColor(FALLBACK_GROUND[resolved.palette] ?? FALLBACK_GROUND.clover) }
  },
}
