import {
  BackSide,
  BoxGeometry,
  BufferGeometry,
  CircleGeometry,
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
import { backdropRidge } from './kit.ts'

type Kept = { geometries: BufferGeometry[]; materials: Material[] }

const GROUND_VERTEX = `
  uniform float uTime;
  uniform float uAmp;
  varying float vWave;
  void main() {
    vec3 p = position;
    float wave = sin(p.x * 1.7 + uTime * 0.85) + sin(p.z * 2.15 - uTime * 0.55);
    vec2 spot = p.xz - vec2(0.72, -0.55);
    float clear = smoothstep(1.15, 2.5, length(spot));
    float lane = (p.z > -1.15 && p.z < 3.5 && p.x > -1.05 && p.x < 1.7) ? 0.0 : 1.0;
    p.y += wave * uAmp * 0.045 * clear * lane;
    vWave = wave;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
  }
`
const GROUND_FRAGMENT = `
  uniform vec3 uSand;
  uniform vec3 uShade;
  varying float vWave;
  void main() {
    gl_FragColor = vec4(mix(uShade, uSand, smoothstep(-0.4, 0.8, vWave)), 1.0);
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
    gl_FragColor = vec4(mix(uHorizon, uZenith, smoothstep(0.0, 0.42, vH)), 1.0);
  }
`

const RIGHT_FIELD: Area = { x0: 2.3, x1: 6.5, z0: -5.5, z1: 1.1 }
const POOL = { x: -2.7, z: -3.2 }
const DUNE_SPOTS: Array<[number, number]> = [
  [-6.3, 0.6], [-5.6, -7.4], [3.4, -2.6], [5.6, 0.5], [0.1, -11.4], [-2.6, -11.2], [4.9, -10.2],
]
const RUIN_SPOTS: Array<[number, number, number]> = [
  [2.7, 1.15, -5.4], [3.5, 0.7, -6.2], [2.35, 0.38, -6.3],
]

const PALM: Record<string, string> = { sand: '#2f6b3a', gold: '#245c32' }
const TRUNK: Record<string, string> = { sand: '#6b4a32', gold: '#5a3a28' }
const DUNE: Record<string, string> = { sand: '#d7b06a', gold: '#c49248' }
const RUIN: Record<string, string> = { sand: '#b08968', gold: '#9a7048' }
const WATER: Record<string, string> = { sand: '#3aa0b8', gold: '#2f7f96' }
const FALLBACK_GROUND: Record<string, string> = { sand: '#c9a56a', gold: '#b18448' }

const DESERT_PALETTES = {
  sand: { fog: '#f2d7a4', ground: '#e8c98a', accent: '#2f6b3a', sky: ['#f2d7a4', '#8ec4ea'] },
  gold: { fog: '#e7b07a', ground: '#d7a15a', accent: '#245c32', sky: ['#e7b07a', '#c46a4a'] },
} as const

const DESERT_TIMES = {
  noon: { sun: [0.15, -0.82, -0.42], sunColor: '#fff1c8' },
  dusk: { sun: [-0.55, -0.28, -0.62], sunColor: '#ffb070' },
} as const

const WIDE_EYE = [0.08, 1.62, 4.25] as const
const WIDE_LOOK = [-0.4, 2.15, -8.6] as const
const LOW_EYE = [0.35, 0.9, 2.7] as const
const LOW_LOOK = [-2.55, 1.05, -3.15] as const

function emptyKept(): Kept {
  return { geometries: [], materials: [] }
}

function hexColor(color: string): [number, number, number] {
  const n = Number.parseInt(color.slice(1), 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

function swatch(table: Record<string, string>, palette: string): string {
  return table[palette] ?? table.sand
}

function rippleAmount(variant: number | undefined): number {
  const value = typeof variant === 'number' && Number.isFinite(variant) ? variant : 5
  return Math.min(8, Math.max(0, value))
}

function zenithColor(time: string): string {
  return time === 'dusk' ? '#c46a4a' : '#8ec4ea'
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

function flatDesert(resolved: ResolvedAtmos): { root: Group; kept: Kept } {
  const root = new Group()
  root.name = 'atmos-desert'
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
  const geo = new PlaneGeometry(36, 36, 48, 48)
  geo.rotateX(-Math.PI / 2)
  const mat = new ShaderMaterial({
    uniforms: {
      uTime: { value: 0 },
      uAmp: { value: rippleAmount(resolved.variant) },
      uSand: { value: new Color(resolved.stone) },
      uShade: { value: new Color(swatch(DUNE, resolved.palette)) },
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

function addDunes(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const geo = new SphereGeometry(1, 7, 5)
  const mat = new MeshBasicMaterial({ color: swatch(DUNE, resolved.palette) })
  const mesh = new InstancedMesh(geo, mat, DUNE_SPOTS.length)
  mesh.name = 'atmos-dune'
  const dummy = new Object3D()
  DUNE_SPOTS.forEach(([x, z], index) => {
    const scale = 1.7 + hash2(index, 2, resolved.seed) * 1.1
    dummy.position.set(x, 0.15 * scale, z)
    dummy.rotation.set(0, 0, 0)
    dummy.scale.set(scale, scale * 0.22, scale * 0.72)
    dummy.updateMatrix()
    mesh.setMatrixAt(index, dummy.matrix)
  })
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function palmSpots(count: number, seed: number): Array<[number, number]> {
  const ring: Array<[number, number]> = [
    [POOL.x - 2.9, POOL.z - 0.4],
    [POOL.x + 2.7, POOL.z - 1.5],
    [POOL.x - 0.6, POOL.z + 2.9],
  ]
  const extra = count > ring.length ? scatter(count - ring.length, seed, 17, [], RIGHT_FIELD, 0.9) : []
  return [...ring.slice(0, Math.min(ring.length, count)), ...extra]
}

function placePalms(mesh: InstancedMesh, spots: Array<[number, number]>, seed: number, base: number, height: number, radius: number) {
  const dummy = new Object3D()
  spots.forEach(([x, z], index) => {
    const scale = 0.85 + hash2(index, 5, seed) * 0.35
    dummy.position.set(x, base * scale + height * scale * 0.5, z)
    dummy.rotation.set(0, 0, 0)
    dummy.scale.set(radius * scale, height * scale, radius * scale)
    dummy.updateMatrix()
    mesh.setMatrixAt(index, dummy.matrix)
  })
}

function placeFronds(mesh: InstancedMesh, spots: Array<[number, number]>, seed: number, tiltX: number, tiltZ: number) {
  const dummy = new Object3D()
  spots.forEach(([x, z], index) => {
    const scale = 0.85 + hash2(index, 5, seed) * 0.35
    dummy.position.set(x, 2.45 * scale, z)
    dummy.rotation.set(tiltX, 0, tiltZ)
    dummy.scale.set(0.16 * scale, 1.85 * scale, 0.16 * scale)
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
  placePalms(trunks, spots, resolved.seed, 0, 2.4, 0.12)
  addMesh(root, kept, trunks)
  kept.materials.push(trunkMat)
  const color = swatch(PALM, resolved.palette)
  addFrond(root, kept, 'atmos-palm', spots, resolved.seed, color, 1.05, 0)
  addFrond(root, kept, 'atmos-frond-a', spots, resolved.seed, color, -1.05, 0)
  addFrond(root, kept, 'atmos-frond-b', spots, resolved.seed, color, 0, 1.05)
  addFrond(root, kept, 'atmos-frond-c', spots, resolved.seed, color, 0, -1.05)
}

function addPool(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const geo = new CircleGeometry(1.7, 24)
  geo.rotateX(-Math.PI / 2)
  const mat = new MeshBasicMaterial({ color: swatch(WATER, resolved.palette) })
  const mesh = new Mesh(geo, mat)
  mesh.name = 'atmos-pool'
  mesh.position.set(POOL.x, 0.04, POOL.z)
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function addRuins(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const geo = new BoxGeometry(1, 1, 1)
  const mat = new MeshBasicMaterial({ color: swatch(RUIN, resolved.palette) })
  const mesh = new InstancedMesh(geo, mat, RUIN_SPOTS.length)
  mesh.name = 'atmos-ruin'
  const dummy = new Object3D()
  const scales: Array<[number, number, number]> = [[0.7, 2.3, 0.7], [0.55, 1.4, 0.55], [1.6, 0.55, 0.6]]
  RUIN_SPOTS.forEach(([x, y, z], index) => {
    const [sx, sy, sz] = scales[index] ?? [1, 1, 1]
    dummy.position.set(x, y, z)
    dummy.rotation.set(0, 0, 0)
    dummy.scale.set(sx, sy, sz)
    dummy.updateMatrix()
    mesh.setMatrixAt(index, dummy.matrix)
  })
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

function syncDesert(root: Group, seconds: number, resolved: ResolvedAtmos, live?: AtmosSettings) {
  const ground = root.getObjectByName('atmos-ground') as Mesh | undefined
  const material = ground?.material
  if (material instanceof ShaderMaterial) {
    material.uniforms.uTime.value = seconds
    material.uniforms.uAmp.value = rippleAmount((live ?? resolved).variant)
  }
  const fog = (root.parent as { fog?: unknown } | null)?.fog
  if (fog instanceof FogExp2) fog.density = 0.014 + (live ?? resolved).fogDensity * 0.034
}

function liveHandle(root: Group, kept: Kept, resolved: ResolvedAtmos): AtmosHandle {
  return {
    ms: { shafts: 0, dof: 0, grade: 0 },
    passes: () => [],
    sync: (seconds, _camera, _light, _quality, _focus, live) => syncDesert(root, seconds, resolved, live),
    dispose: disposeOnce(() => disposeKept(root, kept)),
  }
}

export function buildDesert(resolved: ResolvedAtmos, webgl2: boolean): { root: Group; handle: AtmosHandle } {
  if (!webgl2) {
    const flat = flatDesert(resolved)
    const handle = idleHandle(flat.root, flat.kept)
    flat.root.userData.atmos = handle
    return { root: flat.root, handle }
  }
  const root = new Group()
  root.name = 'atmos-desert'
  const kept = emptyKept()
  addGround(root, resolved, kept)
  addDunes(root, resolved, kept)
  addPalms(root, resolved, kept)
  addPool(root, resolved, kept)
  addRuins(root, resolved, kept)
  backdropRidge(root, kept, resolved, { height: [1.0, 2.4], width: [6, 10], tone: 0.86, radius: 16 })
  addSky(root, resolved, kept)
  const handle = liveHandle(root, kept, resolved)
  root.userData.atmos = handle
  return { root, handle }
}

export const desertSet: AtmosSetDefinition = {
  id: 'atmos-desert',
  titleKey: 'template.atmos-desert-wide.title',
  setting: 'desert',
  seed: 66029,
  subject: CLEARING_SUBJECT,
  subjectYaw: 0.15,
  palettes: DESERT_PALETTES,
  times: DESERT_TIMES,
  defaults: { timeOfDay: 'noon', fogDensity: 0.28, wind: 0.55, motes: 0.35, palette: 'sand', variant: 5 },
  variant: { labelKey: 'atmos.ripples', min: 0, max: 8 },
  low: { shaftSteps: 0, grassBlades: 6, moteCount: 24 },
  high: { shaftSteps: 0, grassBlades: 10, moteCount: 48 },
  templates: [
    { id: 'atmos-desert-wide', camera: 'establishment', eye: WIDE_EYE, look: WIDE_LOOK, fov: 48, duration: 6 },
    { id: 'atmos-desert-low', camera: 'establishment', eye: LOW_EYE, look: LOW_LOOK, fov: 54, duration: 6 },
  ],
  build: buildDesert,
  fallback(resolved) {
    const sky = DESERT_PALETTES[resolved.palette as keyof typeof DESERT_PALETTES]?.fog ?? DESERT_PALETTES.sand.fog
    return { sky: hexColor(sky), ground: hexColor(FALLBACK_GROUND[resolved.palette] ?? FALLBACK_GROUND.sand) }
  },
}
