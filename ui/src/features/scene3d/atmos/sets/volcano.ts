import {
  BackSide,
  BufferGeometry,
  Color,
  ConeGeometry,
  FogExp2,
  IcosahedronGeometry,
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
import { CLEARING_SUBJECT, scatter, type Area, type Trunk } from '../layout.ts'

type Kept = { geometries: BufferGeometry[]; materials: Material[] }
type Spot = [number, number]
type Cone = { x: number; z: number; height: number; radius: number }

// PlaneGeometry faces +z. rotateX(-PI/2) lays the field on xz with the front facing +y.
// ConeGeometry's apex is +y, so a cone at height/2 sits with its base on the rock.
// The lava pad matches layout.ts: the 1.4 m circle and the lane stay rock, a little wider so feet are not in the river.
const GROUND_VERTEX = `
  varying vec2 vXZ;
  void main() {
    vXZ = position.xz;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`
const GROUND_FRAGMENT = `
  uniform vec3 uRock;
  uniform vec3 uDust;
  uniform vec3 uHaze;
  varying vec2 vXZ;
  void main() {
    float ridge = sin(vXZ.x * 0.31 + vXZ.y * 0.17) * sin(vXZ.y * 0.23);
    vec3 color = mix(uRock, uDust, smoothstep(-0.15, 0.75, ridge));
    float far = smoothstep(8.0, 40.0, length(vXZ));
    gl_FragColor = vec4(mix(color, uHaze, far * 0.82), 1.0);
  }
`
const LAVA_VERTEX = `
  varying vec2 vXZ;
  void main() {
    vXZ = position.xz;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`
const LAVA_FRAGMENT = `
  uniform float uTime;
  uniform float uHeat;
  uniform float uFlow;
  uniform vec3 uLava;
  uniform vec3 uCore;
  varying vec2 vXZ;

  float safePad(vec2 xz) {
    vec2 spot = vec2(0.72, -0.55);
    float circle = 1.0 - smoothstep(1.15, 1.6, length(xz - spot));
    float laneX = smoothstep(-1.28, -1.02, xz.x) * (1.0 - smoothstep(1.72, 2.0, xz.x));
    float laneZ = smoothstep(-1.4, -1.12, xz.y) * (1.0 - smoothstep(3.5, 3.85, xz.y));
    return max(circle, laneX * laneZ);
  }

  float channel(float d) {
    float core = 1.0 - smoothstep(0.08, 0.28, d);
    float body = 1.0 - smoothstep(0.22, 0.72, d);
    return core + body * 0.85;
  }

  void main() {
    vec2 xz = vXZ;
    float flow = uTime * uFlow;
    float left = abs(xz.x - (-2.75 + sin(xz.y * 0.52 + flow) * 0.42 + sin(xz.y * 1.3) * 0.12));
    float right = abs(xz.x - (3.25 + sin(xz.y * 0.41 - flow * 0.85) * 0.38 + sin(xz.y * 1.15) * 0.1));
    float far = abs(xz.y - (-6.3 + sin(xz.x * 0.29 + flow * 0.65) * 0.5));
    float mask = (channel(left) + channel(right) + channel(far) * 0.9) * (1.0 - safePad(xz));
    if (mask < 0.12) discard;
    float hot = clamp(smoothstep(0.35, 1.2, mask) * uHeat, 0.0, 1.35);
    float travel = 0.62 + 0.38 * sin(xz.y * 2.8 - flow * 3.6);
    vec3 color = mix(uLava, uCore, clamp(hot * travel, 0.0, 1.0));
    gl_FragColor = vec4(color, clamp(mask, 0.5, 1.0));
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
    gl_FragColor = vec4(mix(uHorizon, uZenith, smoothstep(-0.02, 0.62, vH)), 1.0);
  }
`

const LEFT: Area = { x0: -9.4, x1: -4.15, z0: -8.2, z1: 1.4 }
const RIGHT: Area = { x0: 4.45, x1: 9.4, z0: -8.2, z1: 1.4 }
const ASH_LEFT: Area = { x0: -7.4, x1: -2.15, z0: -6.4, z1: 1.6 }
const ASH_RIGHT: Area = { x0: 2.35, x1: 7.4, z0: -6.4, z1: 1.6 }
const ASH_FAR: Area = { x0: -6.2, x1: 6.2, z0: -9.2, z1: -2.4 }
const CONES: Cone[] = [
  { x: -6.2, z: -5.5, height: 3.3, radius: 1.65 },
  { x: -8.2, z: -12.2, height: 6.4, radius: 2.55 },
  { x: 0.4, z: -14.2, height: 8.1, radius: 3.15 },
  { x: 8.4, z: -11.0, height: 5.1, radius: 2.15 },
]

const ROCK: Record<string, string> = { magma: '#5a4034', ash: '#6a6460' }
const DUST: Record<string, string> = { magma: '#3a2c26', ash: '#4a4542' }
const LAVA: Record<string, string> = { magma: '#ff4a10', ash: '#e07030' }
const CORE: Record<string, string> = { magma: '#fff0a4', ash: '#ffc898' }
const ASH: Record<string, string> = { magma: '#6e655e', ash: '#8a8680' }
const ASH_LIGHT: Record<string, string> = { magma: '#efe6dc', ash: '#d8d2cc' }
const EMBER: Record<string, string> = { magma: '#ffb020', ash: '#e09040' }
const VENT: Record<string, string> = { magma: '#ffd060', ash: '#e8a060' }
const HAZE: Record<string, string> = { magma: '#7a241c', ash: '#5a3834' }
const FALLBACK_GROUND: Record<string, string> = { magma: '#241c18', ash: '#3a3632' }

const VOLCANO_PALETTES = {
  magma: { fog: '#c43228', ground: '#241c18', accent: '#ff4a10', sky: ['#c43228', '#5c1418'] },
  ash: { fog: '#a05048', ground: '#3a3632', accent: '#e07030', sky: ['#a05048', '#4a2824'] },
} as const

const VOLCANO_TIMES = {
  erupt: { sun: [0.2, -0.78, -0.42], sunColor: '#ffe0c0' },
  calm: { sun: [-0.16, -0.58, -0.68], sunColor: '#ffb090' },
} as const

const WIDE_EYE = [0.12, 1.7, 4.8] as const
const WIDE_LOOK = [0.15, 2.05, -8.5] as const
const LOW_EYE = [0.9, 1.05, 2.55] as const
const LOW_LOOK = [-2.9, 0.42, -4.4] as const

function emptyKept(): Kept {
  return { geometries: [], materials: [] }
}

function hexColor(color: string): [number, number, number] {
  const n = Number.parseInt(color.slice(1), 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

function swatch(table: Record<string, string>, palette: string): string {
  return table[palette] ?? table.magma
}

function heatAmount(variant: number | undefined): number {
  const value = typeof variant === 'number' && Number.isFinite(variant) ? variant : 5
  return Math.min(8, Math.max(0, value))
}

function heatScale(variant: number | undefined): number {
  return 0.4 + heatAmount(variant) * 0.1
}

function dayGain(time: string): number {
  return time === 'calm' ? 0.55 : 1
}

function heatLook(settings: AtmosSettings): number {
  return heatScale(settings.variant) * dayGain(settings.timeOfDay)
}

function flowLook(time: string): number {
  return time === 'calm' ? 0.4 : 1.15
}

function ashPace(time: string): number {
  return time === 'calm' ? 0.35 : 0.95
}

function zenithColor(time: string, palette: string): string {
  if (palette === 'ash') return time === 'calm' ? '#241816' : '#4a2824'
  return time === 'calm' ? '#1a0a10' : '#5c1418'
}

function horizonColor(palette: string): string {
  const look = VOLCANO_PALETTES[palette as keyof typeof VOLCANO_PALETTES]
  return look?.fog ?? VOLCANO_PALETTES.magma.fog
}

function ashColor(index: number, palette: string): string {
  if (index % 4 === 0) return swatch(EMBER, palette)
  if (index % 4 === 1) return swatch(ASH_LIGHT, palette)
  return swatch(ASH, palette)
}

function coneTrunks(): Trunk[] {
  return CONES.map(cone => ({
    x: cone.x, z: cone.z, height: cone.height, radius: cone.radius, layer: 1, yaw: 0,
  }))
}

function rockSpots(count: number, seed: number): Spot[] {
  const trunks = coneTrunks()
  const left = Math.ceil(count / 2)
  return [
    ...scatter(left, seed, 11, trunks, LEFT, 0.85),
    ...scatter(count - left, seed, 29, trunks, RIGHT, 0.85),
  ]
}

function ashSpots(count: number, seed: number): Spot[] {
  const trunks = coneTrunks()
  const side = Math.ceil(count / 2)
  const left = Math.ceil(side / 2)
  return [
    ...scatter(left, seed, 41, trunks, ASH_LEFT, 0.3),
    ...scatter(side - left, seed, 43, trunks, ASH_RIGHT, 0.3),
    ...scatter(count - side, seed, 47, trunks, ASH_FAR, 0.3),
  ]
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

function flatVolcano(resolved: ResolvedAtmos): { root: Group; kept: Kept } {
  const root = new Group()
  root.name = 'atmos-volcano'
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
  const geo = new PlaneGeometry(160, 160)
  geo.rotateX(-Math.PI / 2)
  const mat = new ShaderMaterial({
    uniforms: {
      uRock: { value: new Color(resolved.stone) },
      uDust: { value: new Color(swatch(DUST, resolved.palette)) },
      uHaze: { value: new Color(swatch(HAZE, resolved.palette)) },
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

function addLava(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const geo = new PlaneGeometry(160, 160)
  geo.rotateX(-Math.PI / 2)
  const mat = new ShaderMaterial({
    uniforms: {
      uTime: { value: 0 },
      uHeat: { value: heatLook(resolved) },
      uFlow: { value: flowLook(resolved.timeOfDay) },
      uLava: { value: new Color(swatch(LAVA, resolved.palette)) },
      uCore: { value: new Color(swatch(CORE, resolved.palette)) },
    },
    vertexShader: LAVA_VERTEX,
    fragmentShader: LAVA_FRAGMENT,
    transparent: true,
    depthWrite: false,
    toneMapped: false,
  })
  const mesh = new Mesh(geo, mat)
  mesh.name = 'atmos-lava'
  mesh.position.set(0, 0.04, 0)
  mesh.frustumCulled = false
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function placeRocks(mesh: InstancedMesh, spots: Spot[], seed: number) {
  const dummy = new Object3D()
  spots.forEach(([x, z], index) => {
    const span = 0.36 + hash2(index, 4, seed) * 0.42
    dummy.position.set(x, span * 0.42, z)
    dummy.rotation.set(0, hash2(index, 6, seed) * 1.4, hash2(index, 8, seed) * 0.4)
    dummy.scale.set(span * 1.15, span * 0.72, span)
    dummy.updateMatrix()
    mesh.setMatrixAt(index, dummy.matrix)
  })
  mesh.instanceMatrix.needsUpdate = true
}

function addRocks(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const spots = rockSpots(resolved.grassBlades, resolved.seed)
  if (spots.length < 1) return
  const geo = new IcosahedronGeometry(1, 0)
  const mat = new MeshBasicMaterial({ color: swatch(ROCK, resolved.palette) })
  const mesh = new InstancedMesh(geo, mat, spots.length)
  mesh.name = 'atmos-rock'
  mesh.frustumCulled = false
  placeRocks(mesh, spots, resolved.seed)
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function placeCones(mesh: InstancedMesh) {
  const dummy = new Object3D()
  CONES.forEach((cone, index) => {
    dummy.position.set(cone.x, cone.height * 0.5, cone.z)
    dummy.rotation.set(0, 0, 0)
    dummy.scale.set(cone.radius, cone.height, cone.radius)
    dummy.updateMatrix()
    mesh.setMatrixAt(index, dummy.matrix)
  })
  mesh.instanceMatrix.needsUpdate = true
}

function addCones(root: Group, kept: Kept) {
  const geo = new ConeGeometry(1, 1, 7)
  const mat = new MeshBasicMaterial({ color: '#3a2a24' })
  const mesh = new InstancedMesh(geo, mat, CONES.length)
  mesh.name = 'atmos-cone'
  mesh.frustumCulled = false
  placeCones(mesh)
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function placeVents(mesh: InstancedMesh) {
  const dummy = new Object3D()
  CONES.forEach((cone, index) => {
    dummy.position.set(cone.x, cone.height * 0.84, cone.z)
    dummy.rotation.set(0, 0, 0)
    dummy.scale.set(cone.radius * 0.16, cone.radius * 0.11, cone.radius * 0.16)
    dummy.updateMatrix()
    mesh.setMatrixAt(index, dummy.matrix)
  })
  mesh.instanceMatrix.needsUpdate = true
}

function addVents(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const geo = new SphereGeometry(1, 8, 6)
  const mat = new MeshBasicMaterial({ color: swatch(VENT, resolved.palette), toneMapped: false })
  const mesh = new InstancedMesh(geo, mat, CONES.length)
  mesh.name = 'atmos-vent'
  mesh.frustumCulled = false
  placeVents(mesh)
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function placeAsh(mesh: InstancedMesh, spots: Spot[], seconds: number, pace: number) {
  const dummy = new Object3D()
  spots.forEach(([x, z], index) => {
    const span = 3.6
    const phase = (seconds * pace + index * 0.37) % span
    const drift = Math.sin(seconds * 0.6 + index) * 0.1
    const size = 0.055 + (index % 4) * 0.028
    dummy.position.set(x + drift, 1.15 + (span - phase), z)
    dummy.rotation.set(0, 0, 0)
    dummy.scale.setScalar(size)
    dummy.updateMatrix()
    mesh.setMatrixAt(index, dummy.matrix)
  })
  mesh.instanceMatrix.needsUpdate = true
}

function paintAsh(mesh: InstancedMesh, palette: string) {
  const color = new Color()
  for (let index = 0; index < mesh.count; index += 1) {
    color.set(ashColor(index, palette))
    mesh.setColorAt(index, color)
  }
  if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true
}

function addAsh(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const spots = ashSpots(resolved.moteCount, resolved.seed)
  if (spots.length < 1) return
  const geo = new SphereGeometry(1, 6, 4)
  const mat = new MeshBasicMaterial({ toneMapped: false })
  const mesh = new InstancedMesh(geo, mat, spots.length)
  mesh.name = 'atmos-ash'
  mesh.frustumCulled = false
  mesh.userData.spots = spots
  placeAsh(mesh, spots, 0, ashPace(resolved.timeOfDay))
  paintAsh(mesh, resolved.palette)
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function addSky(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const geo = new SphereGeometry(90, 16, 12)
  const mat = new ShaderMaterial({
    uniforms: {
      uHorizon: { value: new Color(resolved.fogColor) },
      uZenith: { value: new Color(zenithColor(resolved.timeOfDay, resolved.palette)) },
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

function shaderOf(root: Group, name: string): ShaderMaterial | undefined {
  const mesh = root.getObjectByName(name) as Mesh | undefined
  const material = mesh?.material
  if (material instanceof ShaderMaterial) return material
  return undefined
}

function syncVolcano(root: Group, seconds: number, resolved: ResolvedAtmos, live?: AtmosSettings) {
  const settings = live ?? resolved
  const lava = shaderOf(root, 'atmos-lava')
  if (lava) {
    lava.uniforms.uTime.value = seconds
    lava.uniforms.uHeat.value = heatLook(settings)
    lava.uniforms.uFlow.value = flowLook(settings.timeOfDay)
    lava.uniforms.uLava.value.set(swatch(LAVA, settings.palette))
    lava.uniforms.uCore.value.set(swatch(CORE, settings.palette))
  }
  const sky = shaderOf(root, 'atmos-sky')
  if (sky) {
    sky.uniforms.uHorizon.value.set(horizonColor(settings.palette))
    sky.uniforms.uZenith.value.set(zenithColor(settings.timeOfDay, settings.palette))
  }
  const ash = root.getObjectByName('atmos-ash') as InstancedMesh | undefined
  const spots = ash?.userData.spots as Spot[] | undefined
  if (ash && spots) {
    placeAsh(ash, spots, seconds, ashPace(settings.timeOfDay))
    paintAsh(ash, settings.palette)
  }
  const fog = (root.parent as { fog?: unknown } | null)?.fog
  if (fog instanceof FogExp2) fog.density = 0.014 + settings.fogDensity * 0.034
}

function liveHandle(root: Group, kept: Kept, resolved: ResolvedAtmos): AtmosHandle {
  return {
    ms: { shafts: 0, dof: 0, grade: 0 },
    passes: () => [],
    sync: (seconds, _camera, _light, _quality, _focus, live) => syncVolcano(root, seconds, resolved, live),
    dispose: disposeOnce(() => disposeKept(root, kept)),
  }
}

export function buildVolcano(resolved: ResolvedAtmos, webgl2: boolean): { root: Group; handle: AtmosHandle } {
  if (!webgl2) {
    const flat = flatVolcano(resolved)
    const handle = idleHandle(flat.root, flat.kept)
    flat.root.userData.atmos = handle
    return { root: flat.root, handle }
  }
  const root = new Group()
  root.name = 'atmos-volcano'
  const kept = emptyKept()
  addGround(root, resolved, kept)
  addLava(root, resolved, kept)
  addRocks(root, resolved, kept)
  addCones(root, kept)
  addVents(root, resolved, kept)
  addAsh(root, resolved, kept)
  addSky(root, resolved, kept)
  const handle = liveHandle(root, kept, resolved)
  root.userData.atmos = handle
  return { root, handle }
}

export const volcanoSet: AtmosSetDefinition = {
  id: 'atmos-volcano',
  titleKey: 'template.atmos-volcano-wide.title',
  setting: 'volcano',
  seed: 91017,
  subject: CLEARING_SUBJECT,
  subjectYaw: 0.15,
  palettes: VOLCANO_PALETTES,
  times: VOLCANO_TIMES,
  defaults: { timeOfDay: 'erupt', fogDensity: 0.16, wind: 0.55, motes: 0.7, palette: 'magma', variant: 5 },
  variant: { labelKey: 'atmos.heat', min: 0, max: 8 },
  low: { shaftSteps: 0, grassBlades: 7, moteCount: 28 },
  high: { shaftSteps: 0, grassBlades: 11, moteCount: 44 },
  templates: [
    { id: 'atmos-volcano-wide', camera: 'establishment', eye: WIDE_EYE, look: WIDE_LOOK, fov: 52, duration: 6 },
    { id: 'atmos-volcano-low', camera: 'establishment', eye: LOW_EYE, look: LOW_LOOK, fov: 56, duration: 6 },
  ],
  build: buildVolcano,
  fallback(resolved) {
    return {
      sky: hexColor(horizonColor(resolved.palette)),
      ground: hexColor(FALLBACK_GROUND[resolved.palette] ?? FALLBACK_GROUND.magma),
    }
  },
}
