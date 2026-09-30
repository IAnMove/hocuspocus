import {
  BackSide,
  BoxGeometry,
  BufferGeometry,
  Color,
  ConeGeometry,
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
} from 'three'
import type { AtmosHandle } from './clearing.ts'
import type { AtmosSetDefinition } from '../definition.ts'
import type { AtmosSettings, ResolvedAtmos } from '../params.ts'
import { hash2 } from '../noise.ts'
import { CLEARING_SUBJECT, scatter, type Area } from '../layout.ts'

type Kept = { geometries: BufferGeometry[]; materials: Material[] }

// PlaneGeometry faces +z. rotateX(-PI/2) stores ground depth in position.z and up in position.y.
// On the water plane, local +z is the shore, toward the camera.
const WATER_VERTEX = `
  uniform float uTime;
  uniform float uAmp;
  varying float vWave;
  varying vec3 vPos;
  void main() {
    vec3 p = position;
    float wave = sin(p.x * 0.72 - uTime * 1.15) + sin(p.z * 1.35 + uTime * 0.85);
    p.y += wave * uAmp * 0.045;
    vWave = wave;
    vPos = p;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
  }
`
const WATER_FRAGMENT = `
  uniform float uAmp;
  uniform vec3 uWater;
  uniform vec3 uFoam;
  uniform vec3 uGlint;
  varying float vWave;
  varying vec3 vPos;
  void main() {
    float crest = smoothstep(0.45, 1.35, vWave);
    float shore = smoothstep(2.2, 5.6, vPos.z);
    float foam = shore * max(crest, 0.35) * clamp(uAmp / 8.0, 0.0, 1.0);
    float band = exp(-pow(vPos.x + 4.2, 2.0) * 0.06);
    vec3 color = mix(uWater, uFoam, clamp(foam, 0.0, 1.0));
    color = mix(color, uGlint, band * shore * 0.8);
    gl_FragColor = vec4(color, 1.0);
  }
`
const GROUND_VERTEX = `
  varying float vZ;
  varying float vX;
  void main() {
    vZ = position.z;
    vX = position.x;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`
const GROUND_FRAGMENT = `
  uniform vec3 uSand;
  uniform vec3 uWet;
  uniform vec3 uGlint;
  varying float vZ;
  varying float vX;
  void main() {
    float wet = smoothstep(-1.7, -2.9, vZ);
    float band = exp(-pow(vX + 3.2, 2.0) * 0.08);
    vec3 color = mix(uSand, uWet, wet);
    color = mix(color, uGlint, wet * band * 0.45);
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
    gl_FragColor = vec4(mix(uHorizon, uZenith, smoothstep(0.02, 0.55, vH)), 1.0);
  }
`

const SHORE: Area = { x0: -7.2, x1: 6.4, z0: -2.55, z1: -2.15 }
const PALM_FIELD: Area = { x0: 3.5, x1: 7.2, z0: -3.2, z1: 0.4 }
const PALM_PAIR: Array<[number, number]> = [[-6.5, -1.75], [-5.4, -2.05]]
const GULL_SPOTS: Array<[number, number, number]> = [
  [-6.4, 6.2, -11.5], [-3.2, 7.0, -13.2], [-0.8, 5.6, -10.4],
  [2.6, 6.6, -12.4], [5.1, 7.4, -14.2], [-8.2, 8.0, -15.4],
]
const BOAT_PARTS: Array<{ at: [number, number, number]; scale: [number, number, number]; yaw: number }> = [
  { at: [-4.55, 0.22, -2.25], scale: [1.7, 0.28, 0.62], yaw: 0.45 },
  { at: [-5.25, 0.26, -2.72], scale: [0.5, 0.22, 0.4], yaw: 0.45 },
  { at: [-4.3, 0.5, -2.12], scale: [0.48, 0.34, 0.4], yaw: 0.45 },
  { at: [-4.5, 0.98, -2.28], scale: [0.06, 0.85, 0.06], yaw: 0 },
]

const PALM: Record<string, string> = { amber: '#2a6a38', coral: '#245c32' }
const TRUNK: Record<string, string> = { amber: '#6b4030', coral: '#5c3828' }
const WET: Record<string, string> = { amber: '#c48a58', coral: '#c07078' }
const WATER: Record<string, string> = { amber: '#2f6f88', coral: '#3a5f86' }
const FOAM: Record<string, string> = { amber: '#f7f1e4', coral: '#f8e8ea' }
const ROCK: Record<string, string> = { amber: '#8d7360', coral: '#7a6058' }
const GLINT: Record<string, string> = { amber: '#ffe1a8', coral: '#ffd0c4' }
const FALLBACK_GROUND: Record<string, string> = { amber: '#e6c07a', coral: '#d7a08a' }

const BEACH_PALETTES = {
  amber: { fog: '#ffc49a', ground: '#e6c07a', accent: '#2a6a38', sky: ['#ffc49a', '#7a4a78'] },
  coral: { fog: '#f0a0b0', ground: '#d7a08a', accent: '#245c32', sky: ['#f0a0b0', '#5a3a68'] },
} as const

const BEACH_TIMES = {
  golden: { sun: [-0.55, -0.22, -0.72], sunColor: '#ffc060' },
  dusk: { sun: [-0.28, -0.08, -0.82], sunColor: '#ff7848' },
} as const

const WIDE_EYE = [0.15, 1.5, 4.35] as const
const WIDE_LOOK = [-2.2, 1.85, -11] as const
const LOW_EYE = [1.15, 0.72, 2.85] as const
const LOW_LOOK = [-5.6, 1.45, -2.4] as const

function emptyKept(): Kept {
  return { geometries: [], materials: [] }
}

function hexColor(color: string): [number, number, number] {
  const n = Number.parseInt(color.slice(1), 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

function swatch(table: Record<string, string>, palette: string): string {
  return table[palette] ?? table.amber
}

function tideAmount(variant: number | undefined): number {
  const value = typeof variant === 'number' && Number.isFinite(variant) ? variant : 5
  return Math.min(8, Math.max(0, value))
}

function zenithColor(time: string): string {
  return time === 'dusk' ? '#3a2a58' : '#7a4a78'
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

function flatBeach(resolved: ResolvedAtmos): { root: Group; kept: Kept } {
  const root = new Group()
  root.name = 'atmos-beach'
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
  const geo = new PlaneGeometry(36, 36)
  geo.rotateX(-Math.PI / 2)
  const mat = new ShaderMaterial({
    uniforms: {
      uSand: { value: new Color(resolved.stone) },
      uWet: { value: new Color(swatch(WET, resolved.palette)) },
      uGlint: { value: new Color(swatch(GLINT, resolved.palette)) },
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

function addWater(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const geo = new PlaneGeometry(26, 12, 48, 24)
  geo.rotateX(-Math.PI / 2)
  const mat = new ShaderMaterial({
    uniforms: {
      uTime: { value: 0 },
      uAmp: { value: tideAmount(resolved.variant) },
      uWater: { value: new Color(swatch(WATER, resolved.palette)) },
      uFoam: { value: new Color(swatch(FOAM, resolved.palette)) },
      uGlint: { value: new Color(swatch(GLINT, resolved.palette)) },
    },
    vertexShader: WATER_VERTEX,
    fragmentShader: WATER_FRAGMENT,
  })
  const mesh = new Mesh(geo, mat)
  mesh.name = 'atmos-water'
  mesh.position.set(0, 0.04, -8.6)
  mesh.frustumCulled = false
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function addRocks(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const spots = scatter(7, resolved.seed, 23, [], SHORE, 0.8)
  if (spots.length < 1) return
  const geo = new BoxGeometry(1, 1, 1)
  const mat = new MeshBasicMaterial({ color: swatch(ROCK, resolved.palette) })
  const mesh = new InstancedMesh(geo, mat, spots.length)
  mesh.name = 'atmos-rock'
  const dummy = new Object3D()
  spots.forEach(([x, z], index) => {
    const scale = 0.35 + hash2(index, 4, resolved.seed) * 0.45
    dummy.position.set(x, scale * 0.35, z)
    dummy.rotation.set(0, hash2(index, 6, resolved.seed) * 1.2, 0)
    dummy.scale.set(scale * 1.4, scale * 0.7, scale)
    dummy.updateMatrix()
    mesh.setMatrixAt(index, dummy.matrix)
  })
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function palmSpots(count: number, seed: number): Array<[number, number]> {
  const pair = PALM_PAIR.slice(0, Math.min(PALM_PAIR.length, count))
  const extra = count > pair.length ? scatter(count - pair.length, seed, 17, [], PALM_FIELD, 0.9) : []
  return [...pair, ...extra]
}

function placePalms(mesh: InstancedMesh, spots: Array<[number, number]>, seed: number) {
  const dummy = new Object3D()
  spots.forEach(([x, z], index) => {
    const scale = 0.85 + hash2(index, 5, seed) * 0.3
    dummy.position.set(x, 1.15 * scale, z)
    dummy.rotation.set(0, 0, 0)
    dummy.scale.set(0.11 * scale, 2.3 * scale, 0.11 * scale)
    dummy.updateMatrix()
    mesh.setMatrixAt(index, dummy.matrix)
  })
}

function placeFronds(mesh: InstancedMesh, spots: Array<[number, number]>, seed: number, tiltX: number, tiltZ: number) {
  const dummy = new Object3D()
  spots.forEach(([x, z], index) => {
    const scale = 0.85 + hash2(index, 5, seed) * 0.3
    dummy.position.set(x, 2.35 * scale, z)
    dummy.rotation.set(tiltX, 0, tiltZ)
    dummy.scale.set(0.16 * scale, 1.7 * scale, 0.16 * scale)
    dummy.updateMatrix()
    mesh.setMatrixAt(index, dummy.matrix)
  })
}

function addFrond(root: Group, kept: Kept, name: string, spots: Array<[number, number]>, seed: number, color: string, tiltX: number, tiltZ: number) {
  const geo = new ConeGeometry(1, 1, 4)
  const mat = new MeshBasicMaterial({ color })
  const mesh = new InstancedMesh(geo, mat, spots.length)
  mesh.name = name
  placeFronds(mesh, spots, seed, tiltX, tiltZ)
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function addPalms(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const spots = palmSpots(resolved.grassBlades, resolved.seed)
  if (spots.length < 1) return
  const trunkGeo = new CylinderGeometry(1, 1, 1, 5)
  const trunkMat = new MeshBasicMaterial({ color: swatch(TRUNK, resolved.palette) })
  const trunks = new InstancedMesh(trunkGeo, trunkMat, spots.length)
  trunks.name = 'atmos-trunk'
  placePalms(trunks, spots, resolved.seed)
  addMesh(root, kept, trunks)
  kept.materials.push(trunkMat)
  const color = swatch(PALM, resolved.palette)
  addFrond(root, kept, 'atmos-palm', spots, resolved.seed, color, 1.05, 0)
  addFrond(root, kept, 'atmos-frond-a', spots, resolved.seed, color, -1.05, 0)
  addFrond(root, kept, 'atmos-frond-b', spots, resolved.seed, color, 0, 1.05)
  addFrond(root, kept, 'atmos-frond-c', spots, resolved.seed, color, 0, -1.05)
}

function addBoat(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const geo = new BoxGeometry(1, 1, 1)
  const mat = new MeshBasicMaterial({ color: swatch(TRUNK, resolved.palette) })
  const mesh = new InstancedMesh(geo, mat, BOAT_PARTS.length)
  mesh.name = 'atmos-boat'
  const dummy = new Object3D()
  BOAT_PARTS.forEach((part, index) => {
    dummy.position.set(part.at[0], part.at[1], part.at[2])
    dummy.rotation.set(0, part.yaw, 0)
    dummy.scale.set(part.scale[0], part.scale[1], part.scale[2])
    dummy.updateMatrix()
    mesh.setMatrixAt(index, dummy.matrix)
  })
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function placeGulls(mesh: InstancedMesh, seconds: number) {
  const dummy = new Object3D()
  GULL_SPOTS.forEach(([x, y, z], index) => {
    const drift = Math.sin(seconds * 0.55 + index * 1.3) * 0.7
    dummy.position.set(x + drift, y + Math.sin(seconds * 0.9 + index) * 0.12, z)
    dummy.rotation.set(0.4, 0, Math.sin(seconds * 0.4 + index) * 0.35)
    dummy.scale.set(0.9, 0.1, 0.28)
    dummy.updateMatrix()
    mesh.setMatrixAt(index, dummy.matrix)
  })
  mesh.instanceMatrix.needsUpdate = true
}

function addGulls(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const geo = new SphereGeometry(1, 5, 4)
  const mat = new MeshBasicMaterial({ color: swatch(FOAM, resolved.palette) })
  const mesh = new InstancedMesh(geo, mat, GULL_SPOTS.length)
  mesh.name = 'atmos-gull'
  placeGulls(mesh, 0)
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function addSun(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const geo = new SphereGeometry(0.85, 12, 8)
  const mat = new MeshBasicMaterial({ color: BEACH_TIMES[resolved.timeOfDay as keyof typeof BEACH_TIMES]?.sunColor ?? BEACH_TIMES.golden.sunColor })
  const mesh = new Mesh(geo, mat)
  mesh.name = 'atmos-sun'
  const low = resolved.timeOfDay === 'dusk'
  mesh.position.set(low ? -3.2 : -6.4, low ? 1.35 : 2.35, -14.5)
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function addSky(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const geo = new SphereGeometry(28, 16, 10)
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
  mesh.frustumCulled = false
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function syncBeach(root: Group, seconds: number, resolved: ResolvedAtmos, live?: AtmosSettings) {
  const water = root.getObjectByName('atmos-water') as Mesh | undefined
  const material = water?.material
  if (material instanceof ShaderMaterial) {
    material.uniforms.uTime.value = seconds
    material.uniforms.uAmp.value = tideAmount((live ?? resolved).variant)
  }
  const gulls = root.getObjectByName('atmos-gull') as InstancedMesh | undefined
  if (gulls) placeGulls(gulls, seconds)
  const fog = (root.parent as { fog?: unknown } | null)?.fog
  if (fog instanceof FogExp2) fog.density = 0.014 + (live ?? resolved).fogDensity * 0.034
}

function liveHandle(root: Group, kept: Kept, resolved: ResolvedAtmos): AtmosHandle {
  return {
    ms: { shafts: 0, dof: 0, grade: 0 },
    passes: () => [],
    sync: (seconds, _camera, _light, _quality, _focus, live) => syncBeach(root, seconds, resolved, live),
    dispose: disposeOnce(() => disposeKept(root, kept)),
  }
}

export function buildBeach(resolved: ResolvedAtmos, webgl2: boolean): { root: Group; handle: AtmosHandle } {
  if (!webgl2) {
    const flat = flatBeach(resolved)
    const handle = idleHandle(flat.root, flat.kept)
    flat.root.userData.atmos = handle
    return { root: flat.root, handle }
  }
  const root = new Group()
  root.name = 'atmos-beach'
  const kept = emptyKept()
  addGround(root, resolved, kept)
  addWater(root, resolved, kept)
  addRocks(root, resolved, kept)
  addPalms(root, resolved, kept)
  addBoat(root, resolved, kept)
  addGulls(root, resolved, kept)
  addSun(root, resolved, kept)
  addSky(root, resolved, kept)
  const handle = liveHandle(root, kept, resolved)
  root.userData.atmos = handle
  return { root, handle }
}

export const beachSet: AtmosSetDefinition = {
  id: 'atmos-beach',
  titleKey: 'template.atmos-beach-wide.title',
  setting: 'sea',
  seed: 71011,
  subject: CLEARING_SUBJECT,
  subjectYaw: 0.15,
  palettes: BEACH_PALETTES,
  times: BEACH_TIMES,
  defaults: { timeOfDay: 'golden', fogDensity: 0.2, wind: 0.45, motes: 0.2, palette: 'amber', variant: 5 },
  variant: { labelKey: 'atmos.tide', min: 0, max: 8 },
  low: { shaftSteps: 0, grassBlades: 4, moteCount: 6 },
  high: { shaftSteps: 0, grassBlades: 6, moteCount: 6 },
  templates: [
    { id: 'atmos-beach-wide', camera: 'establishment', eye: WIDE_EYE, look: WIDE_LOOK, fov: 48, duration: 6 },
    { id: 'atmos-beach-low', camera: 'establishment', eye: LOW_EYE, look: LOW_LOOK, fov: 54, duration: 6 },
  ],
  build: buildBeach,
  fallback(resolved) {
    const sky = BEACH_PALETTES[resolved.palette as keyof typeof BEACH_PALETTES]?.fog ?? BEACH_PALETTES.amber.fog
    return { sky: hexColor(sky), ground: hexColor(FALLBACK_GROUND[resolved.palette] ?? FALLBACK_GROUND.amber) }
  },
}
