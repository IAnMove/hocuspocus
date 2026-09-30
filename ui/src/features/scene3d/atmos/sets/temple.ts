import {
  AdditiveBlending,
  BackSide,
  BoxGeometry,
  BufferAttribute,
  BufferGeometry,
  Color,
  ConeGeometry,
  CylinderGeometry,
  DoubleSide,
  FogExp2,
  Group,
  InstancedMesh,
  Mesh,
  MeshBasicMaterial,
  Object3D,
  PlaneGeometry,
  ShaderMaterial,
  SphereGeometry,
  Vector2,
  type Material,
} from 'three'
import type { AtmosHandle } from './clearing.ts'
import type { AtmosSetDefinition } from '../definition.ts'
import type { AtmosSettings, ResolvedAtmos } from '../params.ts'
import { hash2 } from '../noise.ts'
import { CLEARING_SUBJECT } from '../layout.ts'

type Kept = { geometries: BufferGeometry[]; materials: Material[] }
type Spot = [number, number]
type Column = { at: Spot; height: number }
type Block = { at: [number, number, number]; scale: [number, number, number] }
type Wing = [number, number, number]
type Clump = [number, number, number, number]

// PlaneGeometry faces +z. rotateX(-PI/2) stores ground depth in position.z.
// ConeGeometry's apex is +y. Vines use rotation.x = PI so the apex hangs down.
const GROUND_VERTEX = `
  varying vec2 vXZ;
  void main() {
    vXZ = position.xz;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
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

const COLUMNS: readonly Column[] = [
  { at: [-2.75, -4.95], height: 4.35 },
  { at: [2.55, -4.85], height: 3.9 },
  { at: [-5.35, -5.5], height: 2.4 },
  { at: [5.15, -5.25], height: 2.7 },
  { at: [-1.35, -7.15], height: 3.4 },
  { at: [1.45, -7.05], height: 3.1 },
  { at: [-6.5, -3.35], height: 1.7 },
  { at: [5.9, -3.15], height: 2.05 },
]
const BLOCKS: readonly Block[] = [
  { at: [-1.7, 4.15, -4.85], scale: [2.4, 0.5, 0.75] },
  { at: [1.55, 3.85, -4.85], scale: [2.1, 0.42, 0.7] },
  { at: [-0.05, 0.14, -3.2], scale: [7.2, 0.26, 1.2] },
  { at: [-0.05, 0.38, -4.15], scale: [5.4, 0.24, 1.15] },
  { at: [-4.4, 0.26, -3.55], scale: [1.35, 0.42, 0.7] },
  { at: [4.1, 0.3, -3.4], scale: [1.15, 0.48, 0.62] },
]
const TREES: readonly Column[] = [
  { at: [-7.1, -3.7], height: 5.6 },
  { at: [-6.4, -6.6], height: 6.4 },
  { at: [6.9, -3.5], height: 5.3 },
  { at: [6.3, -6.4], height: 6.1 },
  { at: [-3.6, -8.6], height: 5.8 },
  { at: [3.8, -8.8], height: 5.5 },
]
const VINE_SPOTS: readonly Spot[] = [
  [-2.4, -4.8], [-1.6, -4.75], [-0.7, -4.85], [0.35, -4.8],
  [1.15, -4.78], [2.05, -4.72], [-4.6, -5.4], [4.4, -5.15],
]
const WING_SPOTS: readonly Wing[] = [
  [-3.3, 2.15, -3.7], [-1.7, 2.55, -4.3], [0.35, 1.95, -5.1], [2.3, 2.35, -4.1],
  [3.7, 1.75, -3.5], [-4.7, 2.7, -5.5], [4.9, 2.15, -5.2], [-2.5, 3.05, -6.3],
  [1.9, 2.95, -6.5], [-5.6, 1.65, -3.3], [0.9, 2.45, -3.9], [-0.8, 1.7, -6.8],
]
const SHAFTS: readonly Spot[] = [[-3.4, -4.55], [-0.9, -4.65], [1.15, -4.6], [3.5, -4.5]]

const STONE: Record<string, string> = { jade: '#e2d2ae', vine: '#d2c096' }
const MOSS: Record<string, string> = { jade: '#7dce45', vine: '#9be05a' }
const VINE: Record<string, string> = { jade: '#146b32', vine: '#1f8a28' }
const CANOPY: Record<string, string> = { jade: '#0e5a30', vine: '#146028' }
const TRUNK: Record<string, string> = { jade: '#6b4a32', vine: '#5c402c' }
const BEAM: Record<string, string> = { jade: '#ffc44a', vine: '#ffe08a' }
const FLOOR_MOSS: Record<string, string> = { jade: '#1e6a38', vine: '#2a7a30' }
const WING: Record<string, readonly string[]> = {
  jade: ['#ff8c1a', '#3ec0ff'],
  vine: ['#ff5a00', '#d6ff4a'],
}
const FALLBACK_GROUND: Record<string, string> = { jade: '#cbb892', vine: '#8a7d5c' }
const SUN_POSE = {
  mist: { at: [-0.4, 8.8, -12.2] as const, scale: 1.15, color: '#ffe6b0' },
  sun: { at: [-3.2, 8.1, -10.4] as const, scale: 1.85, color: '#ffb020' },
}

const TEMPLE_PALETTES = {
  jade: { fog: '#d5e2c4', ground: '#cbb892', accent: '#1f8a46', sky: ['#d5e2c4', '#16382c'] },
  vine: { fog: '#e4d7a4', ground: '#8a7d5c', accent: '#3faa32', sky: ['#e4d7a4', '#1d4a28'] },
} as const

const TEMPLE_TIMES = {
  mist: { sun: [0.08, -0.96, 0.24], sunColor: '#f3edd2' },
  sun: { sun: [-0.35, -0.78, 0.5], sunColor: '#ffc14a' },
} as const

const WIDE_EYE = [0.15, 1.5, 4.2] as const
const WIDE_LOOK = [0.0, 1.9, -7.2] as const
const LOW_EYE = [2.15, 0.62, 2.45] as const
const LOW_LOOK = [-3.8, 1.85, -5.0] as const

const GROUND_FRAGMENT = groundFragment()

function groundFragment(): string {
  const pool = SHAFTS.map(([x, z]) => {
    const sx = x.toFixed(2)
    const sz = z.toFixed(2)
    return `exp(-dot(vXZ - vec2(${sx}, ${sz}), vXZ - vec2(${sx}, ${sz})) * 0.7)`
  }).join(' + ')
  return `
    uniform vec3 uStone;
    uniform vec3 uMoss;
    uniform vec3 uBeam;
    uniform vec2 uSubject;
    varying vec2 vXZ;
    void main() {
      float dist = length(vXZ - uSubject);
      float circle = 1.0 - smoothstep(1.25, 1.55, dist);
      float lane = step(-1.05, vXZ.x) * step(vXZ.x, 1.7) * step(-1.15, vXZ.y) * step(vXZ.y, 3.5);
      float plaza = step(-6.0, vXZ.x) * step(vXZ.x, 6.0) * step(-8.8, vXZ.y) * step(vXZ.y, -1.9);
      float clear = max(circle, lane);
      float stone = max(clear, plaza);
      float speckle = 0.9 + 0.1 * sin(vXZ.x * 3.7) * sin(vXZ.y * 2.9);
      vec3 color = mix(uMoss * speckle, uStone, stone);
      float pool = ${pool};
      color = mix(color, uBeam, clamp(pool, 0.0, 1.0) * (1.0 - clear) * 0.55);
      gl_FragColor = vec4(color, 1.0);
    }
  `
}

function emptyKept(): Kept {
  return { geometries: [], materials: [] }
}

function hexColor(color: string): [number, number, number] {
  const n = Number.parseInt(color.slice(1), 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

function swatch(table: Record<string, string>, palette: string): string {
  return table[palette] ?? table.jade
}

function wingColors(palette: string): readonly string[] {
  return WING[palette] ?? WING.jade
}

function growthAmount(variant: number | undefined): number {
  const value = typeof variant === 'number' && Number.isFinite(variant) ? variant : 5
  return Math.min(8, Math.max(0, value))
}

function vineLength(variant: number | undefined): number {
  return 0.9 + growthAmount(variant) * 0.38
}

function shaftGirth(time: string): number {
  return time === 'sun' ? 0.36 : 0.22
}

function sunPose(time: string) {
  return time === 'sun' ? SUN_POSE.sun : SUN_POSE.mist
}

function zenithColor(palette: string, time: string): string {
  if (time === 'sun') return '#3d7ec4'
  const look = TEMPLE_PALETTES[palette as keyof typeof TEMPLE_PALETTES]
  return look?.sky[1] ?? TEMPLE_PALETTES.jade.sky[1]
}

function mistDensity(settings: AtmosSettings): number {
  const amount = 0.014 + settings.fogDensity * 0.034
  return settings.timeOfDay === 'sun' ? amount * 0.38 : amount
}

function storedGirth(mesh: InstancedMesh): number {
  return typeof mesh.userData.girth === 'number' ? mesh.userData.girth : 0.22
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
  mesh.frustumCulled = false
  root.add(mesh)
  kept.geometries.push(mesh.geometry)
}

function flatTemple(resolved: ResolvedAtmos): { root: Group; kept: Kept } {
  const root = new Group()
  root.name = 'atmos-temple'
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
  const geo = new PlaneGeometry(48, 48)
  geo.rotateX(-Math.PI / 2)
  const mat = new ShaderMaterial({
    uniforms: {
      uStone: { value: new Color(resolved.stone) },
      uMoss: { value: new Color(swatch(FLOOR_MOSS, resolved.palette)) },
      uBeam: { value: new Color(swatch(BEAM, resolved.palette)) },
      uSubject: { value: new Vector2(CLEARING_SUBJECT[0], CLEARING_SUBJECT[2]) },
    },
    vertexShader: GROUND_VERTEX,
    fragmentShader: GROUND_FRAGMENT,
  })
  const mesh = new Mesh(geo, mat)
  mesh.name = 'atmos-ground'
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function addSky(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const geo = new SphereGeometry(26, 16, 12)
  const mat = new ShaderMaterial({
    uniforms: {
      uHorizon: { value: new Color(resolved.fogColor) },
      uZenith: { value: new Color(zenithColor(resolved.palette, resolved.timeOfDay)) },
    },
    vertexShader: SKY_VERTEX,
    fragmentShader: SKY_FRAGMENT,
    side: BackSide,
  })
  const mesh = new Mesh(geo, mat)
  mesh.name = 'atmos-sky'
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function addSun(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const pose = sunPose(resolved.timeOfDay)
  const geo = new SphereGeometry(1, 14, 10)
  const mat = new MeshBasicMaterial({ color: pose.color })
  const mesh = new Mesh(geo, mat)
  mesh.name = 'atmos-sun'
  mesh.position.set(pose.at[0], pose.at[1], pose.at[2])
  mesh.scale.setScalar(pose.scale)
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function placeColumns(mesh: InstancedMesh, columns: readonly Column[]) {
  const dummy = new Object3D()
  columns.forEach((column, index) => {
    dummy.position.set(column.at[0], column.height * 0.5, column.at[1])
    dummy.rotation.set(0, 0, 0)
    dummy.scale.set(0.48, column.height, 0.48)
    dummy.updateMatrix()
    mesh.setMatrixAt(index, dummy.matrix)
  })
  mesh.instanceMatrix.needsUpdate = true
}

function addColumns(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const geo = new CylinderGeometry(1, 1.08, 1, 6)
  const mat = new MeshBasicMaterial({ color: swatch(STONE, resolved.palette) })
  const mesh = new InstancedMesh(geo, mat, COLUMNS.length)
  mesh.name = 'atmos-column'
  placeColumns(mesh, COLUMNS)
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function placeBlocks(mesh: InstancedMesh, blocks: readonly Block[]) {
  const dummy = new Object3D()
  blocks.forEach((block, index) => {
    dummy.position.set(block.at[0], block.at[1], block.at[2])
    dummy.rotation.set(0, 0, 0)
    dummy.scale.set(block.scale[0], block.scale[1], block.scale[2])
    dummy.updateMatrix()
    mesh.setMatrixAt(index, dummy.matrix)
  })
  mesh.instanceMatrix.needsUpdate = true
}

function addBlocks(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const geo = new BoxGeometry(1, 1, 1)
  const mat = new MeshBasicMaterial({ color: swatch(STONE, resolved.palette) })
  const mesh = new InstancedMesh(geo, mat, BLOCKS.length)
  mesh.name = 'atmos-ruin'
  placeBlocks(mesh, BLOCKS)
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function mossClumps(columns: readonly Column[]): Clump[] {
  const clumps: Clump[] = []
  columns.forEach(column => {
    clumps.push([column.at[0], 0.24, column.at[1], 0.9])
    clumps.push([column.at[0], column.height - 0.08, column.at[1], 0.78])
  })
  return clumps
}

function placeClumps(mesh: InstancedMesh, clumps: readonly Clump[]) {
  const dummy = new Object3D()
  clumps.forEach(([x, y, z, size], index) => {
    dummy.position.set(x, y, z)
    dummy.rotation.set(0, 0, 0)
    dummy.scale.set(size, size * 0.5, size)
    dummy.updateMatrix()
    mesh.setMatrixAt(index, dummy.matrix)
  })
  mesh.instanceMatrix.needsUpdate = true
}

function addMoss(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const clumps = mossClumps(COLUMNS)
  const geo = new SphereGeometry(1, 6, 5)
  const mat = new MeshBasicMaterial({ color: swatch(MOSS, resolved.palette) })
  const mesh = new InstancedMesh(geo, mat, clumps.length)
  mesh.name = 'atmos-moss'
  placeClumps(mesh, clumps)
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function placeVines(mesh: InstancedMesh, spots: readonly Spot[], seed: number, variant: number | undefined) {
  const length = vineLength(variant)
  const dummy = new Object3D()
  spots.forEach(([x, z], index) => {
    const thick = 0.22 + hash2(index, 3, seed) * 0.12
    dummy.position.set(x, 4.05 - length * 0.5, z)
    dummy.rotation.set(Math.PI, 0, 0)
    dummy.scale.set(thick, length, thick)
    dummy.updateMatrix()
    mesh.setMatrixAt(index, dummy.matrix)
  })
  mesh.instanceMatrix.needsUpdate = true
}

function addVines(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const spots = VINE_SPOTS.slice(0, resolved.grassBlades)
  if (spots.length < 1) return
  const geo = new ConeGeometry(1, 1, 5)
  const mat = new MeshBasicMaterial({ color: swatch(VINE, resolved.palette) })
  const mesh = new InstancedMesh(geo, mat, spots.length)
  mesh.name = 'atmos-vine'
  mesh.userData.spots = spots
  placeVines(mesh, spots, resolved.seed, resolved.variant)
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function wingGeometry(): BufferGeometry {
  const geo = new BufferGeometry()
  const verts = new Float32Array([
    0, 0, 0, -0.12, 0.46, 0, -0.62, 0.05, 0,
    0, 0, 0, 0.62, 0.04, 0, 0.14, 0.5, 0,
  ])
  geo.setAttribute('position', new BufferAttribute(verts, 3))
  geo.computeVertexNormals()
  return geo
}

function placeWings(mesh: InstancedMesh, spots: readonly Wing[], seconds: number) {
  const dummy = new Object3D()
  spots.forEach(([x, y, z], index) => {
    const drift = Math.sin(seconds * 0.7 + index) * 0.4
    const bob = Math.sin(seconds * 1.3 + index * 0.8) * 0.22
    const flap = Math.sin(seconds * 5 + index) * 0.7
    dummy.position.set(x + drift, y + bob, z)
    dummy.rotation.set(0.15, 0.2, flap)
    dummy.scale.set(1, 1, 1)
    dummy.updateMatrix()
    mesh.setMatrixAt(index, dummy.matrix)
  })
  mesh.instanceMatrix.needsUpdate = true
}

function paintWings(mesh: InstancedMesh, palette: string) {
  const colors = wingColors(palette)
  const color = new Color()
  for (let index = 0; index < mesh.count; index += 1) {
    color.set(colors[index % colors.length])
    mesh.setColorAt(index, color)
  }
  if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true
}

function addWings(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const spots = WING_SPOTS.slice(0, resolved.moteCount)
  if (spots.length < 1) return
  const geo = wingGeometry()
  const mat = new MeshBasicMaterial({ side: DoubleSide })
  const mesh = new InstancedMesh(geo, mat, spots.length)
  mesh.name = 'atmos-butterfly'
  mesh.userData.spots = spots
  placeWings(mesh, spots, 0)
  paintWings(mesh, resolved.palette)
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function placeShafts(mesh: InstancedMesh, seconds: number, girth: number) {
  const dummy = new Object3D()
  SHAFTS.forEach(([x, z], index) => {
    const sway = Math.sin(seconds * 0.35 + index) * 0.16
    const lean = index % 2 === 0 ? 0.07 : -0.07
    dummy.position.set(x + sway, 4.1, z)
    dummy.rotation.set(0, 0, lean)
    dummy.scale.set(girth, 8.4, girth)
    dummy.updateMatrix()
    mesh.setMatrixAt(index, dummy.matrix)
  })
  mesh.instanceMatrix.needsUpdate = true
}

function addShafts(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const geo = new BoxGeometry(1, 1, 1)
  const mat = new MeshBasicMaterial({
    color: swatch(BEAM, resolved.palette),
    transparent: true,
    opacity: 0.95,
    depthWrite: false,
    blending: AdditiveBlending,
    side: DoubleSide,
    toneMapped: false,
  })
  const mesh = new InstancedMesh(geo, mat, SHAFTS.length)
  mesh.name = 'atmos-shaft'
  mesh.userData.girth = shaftGirth(resolved.timeOfDay)
  placeShafts(mesh, 0, mesh.userData.girth as number)
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function placeTrunks(mesh: InstancedMesh, trees: readonly Column[]) {
  const dummy = new Object3D()
  trees.forEach((tree, index) => {
    dummy.position.set(tree.at[0], tree.height * 0.5, tree.at[1])
    dummy.rotation.set(0, 0, 0)
    dummy.scale.set(0.28, tree.height, 0.28)
    dummy.updateMatrix()
    mesh.setMatrixAt(index, dummy.matrix)
  })
  mesh.instanceMatrix.needsUpdate = true
}

function placeCanopy(mesh: InstancedMesh, trees: readonly Column[]) {
  const dummy = new Object3D()
  trees.forEach((tree, index) => {
    dummy.position.set(tree.at[0], tree.height + 1.05, tree.at[1])
    dummy.rotation.set(0, 0, 0)
    dummy.scale.set(1.45, 2.15, 1.45)
    dummy.updateMatrix()
    mesh.setMatrixAt(index, dummy.matrix)
  })
  mesh.instanceMatrix.needsUpdate = true
}

function addTrees(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const trunkGeo = new CylinderGeometry(1, 1.15, 1, 5)
  const trunkMat = new MeshBasicMaterial({ color: swatch(TRUNK, resolved.palette) })
  const trunks = new InstancedMesh(trunkGeo, trunkMat, TREES.length)
  trunks.name = 'atmos-trunk'
  placeTrunks(trunks, TREES)
  addMesh(root, kept, trunks)
  kept.materials.push(trunkMat)
  const leafGeo = new ConeGeometry(1, 1, 6)
  const leafMat = new MeshBasicMaterial({ color: swatch(CANOPY, resolved.palette) })
  const leaves = new InstancedMesh(leafGeo, leafMat, TREES.length)
  leaves.name = 'atmos-canopy'
  placeCanopy(leaves, TREES)
  addMesh(root, kept, leaves)
  kept.materials.push(leafMat)
}

function syncTemple(root: Group, seconds: number, resolved: ResolvedAtmos, live?: AtmosSettings) {
  const settings = live ?? resolved
  const vines = root.getObjectByName('atmos-vine') as InstancedMesh | undefined
  const vineSpots = vines?.userData.spots as Spot[] | undefined
  if (vines && vineSpots) placeVines(vines, vineSpots, resolved.seed, settings.variant)
  const wings = root.getObjectByName('atmos-butterfly') as InstancedMesh | undefined
  const wingSpots = wings?.userData.spots as Wing[] | undefined
  if (wings && wingSpots) placeWings(wings, wingSpots, seconds)
  const shafts = root.getObjectByName('atmos-shaft') as InstancedMesh | undefined
  if (shafts) placeShafts(shafts, seconds, storedGirth(shafts))
  const fog = (root.parent as { fog?: unknown } | null)?.fog
  if (fog instanceof FogExp2) fog.density = mistDensity(settings)
}

function liveHandle(root: Group, kept: Kept, resolved: ResolvedAtmos): AtmosHandle {
  return {
    ms: { shafts: 0, dof: 0, grade: 0 },
    passes: () => [],
    sync: (seconds, _camera, _light, _quality, _focus, live) => syncTemple(root, seconds, resolved, live),
    dispose: disposeOnce(() => disposeKept(root, kept)),
  }
}

export function buildTemple(resolved: ResolvedAtmos, webgl2: boolean): { root: Group; handle: AtmosHandle } {
  if (!webgl2) {
    const flat = flatTemple(resolved)
    const handle = idleHandle(flat.root, flat.kept)
    flat.root.userData.atmos = handle
    return { root: flat.root, handle }
  }
  const root = new Group()
  root.name = 'atmos-temple'
  const kept = emptyKept()
  addGround(root, resolved, kept)
  addColumns(root, resolved, kept)
  addBlocks(root, resolved, kept)
  addMoss(root, resolved, kept)
  addVines(root, resolved, kept)
  addWings(root, resolved, kept)
  addShafts(root, resolved, kept)
  addTrees(root, resolved, kept)
  addSun(root, resolved, kept)
  addSky(root, resolved, kept)
  const handle = liveHandle(root, kept, resolved)
  root.userData.atmos = handle
  return { root, handle }
}

export const templeSet: AtmosSetDefinition = {
  id: 'atmos-temple',
  titleKey: 'template.atmos-temple-wide.title',
  setting: 'jungle',
  seed: 92017,
  subject: CLEARING_SUBJECT,
  subjectYaw: 0.15,
  palettes: TEMPLE_PALETTES,
  times: TEMPLE_TIMES,
  defaults: { timeOfDay: 'mist', fogDensity: 0.34, wind: 0.35, motes: 0.55, palette: 'jade', variant: 5 },
  variant: { labelKey: 'atmos.growth', min: 0, max: 8 },
  low: { shaftSteps: 0, grassBlades: 6, moteCount: 8 },
  high: { shaftSteps: 0, grassBlades: 8, moteCount: 12 },
  templates: [
    { id: 'atmos-temple-wide', camera: 'establishment', eye: WIDE_EYE, look: WIDE_LOOK, fov: 52, duration: 6 },
    { id: 'atmos-temple-low', camera: 'establishment', eye: LOW_EYE, look: LOW_LOOK, fov: 56, duration: 6 },
  ],
  build: buildTemple,
  fallback(resolved) {
    const sky = TEMPLE_PALETTES[resolved.palette as keyof typeof TEMPLE_PALETTES]?.fog ?? TEMPLE_PALETTES.jade.fog
    return { sky: hexColor(sky), ground: hexColor(FALLBACK_GROUND[resolved.palette] ?? FALLBACK_GROUND.jade) }
  },
}
