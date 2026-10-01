import {
  BoxGeometry,
  BufferGeometry,
  Color,
  DoubleSide,
  FogExp2,
  FrontSide,
  Group,
  InstancedMesh,
  Mesh,
  MeshBasicMaterial,
  Object3D,
  PlaneGeometry,
  type Material,
  type Side,
  MeshStandardMaterial,
  PointLight,
  type Texture,
} from 'three'
import type { AtmosHandle } from './clearing.ts'
import type { AtmosSetDefinition } from '../definition.ts'
import type { AtmosSettings, ResolvedAtmos } from '../params.ts'
import { hash2 } from '../noise.ts'
import { CLEARING_SUBJECT } from '../layout.ts'
import { composeGeometry, type Piece } from './kit.ts'
import { plankTexture, wallpaperTexture } from '../textures.ts'

type Kept = { geometries: BufferGeometry[]; materials: Material[]; textures: Texture[] }
type Part = {
  at: [number, number, number]
  scale: [number, number, number]
  yaw?: number
  roll?: number
  color?: string
}

// PlaneGeometry faces +z. rotateX(-PI/2) lays the floor in xz with the normal pointing +y.
// Wall boxes are DoubleSide: a closed FrontSide box is invisible from inside the room.
const SCREEN_X = -2.05
const SCREEN_Y = 1.06
const SCREEN_Z = -3.54
const PAD_X = -1.85
const PAD_Y = 0.07
const PAD_Z = -1.15

const WALL: Record<string, string> = { cream: '#efe4d2', mauve: '#e7c4d6' }
const FLOOR: Record<string, string> = { cream: '#b8895a', mauve: '#7a4a68' }
const CEILING: Record<string, string> = { cream: '#f6efe4', mauve: '#f0d5e4' }
const WOOD: Record<string, string> = { cream: '#8d5a32', mauve: '#6a3a48' }
const BEZEL: Record<string, string> = { cream: '#1a1816', mauve: '#221820' }
const PHOSPHOR: Record<string, string> = { cream: '#d7ffe6', mauve: '#ffd0f2' }
const RUG: Record<string, string> = { cream: '#8a5a34', mauve: '#5c3050' }
const POSTER: Record<string, string> = { cream: '#d24b32', mauve: '#6a48d0' }
const CART: Record<string, string> = { cream: '#d24a3a', mauve: '#e056c8' }
const FOG_ON: Record<string, string> = { cream: '#cabbab', mauve: '#c9a8ba' }
const FOG_DIM: Record<string, string> = { cream: '#6e6458', mauve: '#6a4858' }
const FALLBACK_GROUND: Record<string, string> = { cream: '#b8895a', mauve: '#7a4a68' }

const ROOM_PALETTES = {
  cream: { fog: '#cabbab', ground: '#b8895a', accent: '#e7d3b0', sky: ['#cabbab', '#8d7d6c'] },
  mauve: { fog: '#c9a8ba', ground: '#7a4a68', accent: '#f0c6de', sky: ['#c9a8ba', '#6d4862'] },
} as const

const ROOM_TIMES = {
  dim: { sun: [0.08, -0.92, -0.18], sunColor: '#ffd2a2' },
  on: { sun: [0.02, -0.98, 0.04], sunColor: '#fff6d4' },
} as const

const WIDE_EYE = [0.16, 1.52, 2.18] as const
const WIDE_LOOK = [-0.45, 0.98, -3.5] as const
const LOW_EYE = [0.28, 0.44, 1.72] as const
const LOW_LOOK = [-0.55, 0.88, -3.55] as const

function emptyKept(): Kept {
  return { geometries: [], materials: [], textures: [] }
}

function hexColor(color: string): [number, number, number] {
  const n = Number.parseInt(color.slice(1), 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

function swatch(table: Record<string, string>, palette: string): string {
  return table[palette] ?? table.cream
}

function staticAmount(variant: number | undefined): number {
  const value = typeof variant === 'number' && Number.isFinite(variant) ? variant : 3
  return Math.min(8, Math.max(0, value))
}

function screenGain(variant: number | undefined): number {
  return 0.42 + staticAmount(variant) * 0.09
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

function flatRoom(resolved: ResolvedAtmos): { root: Group; kept: Kept } {
  const root = new Group()
  root.name = 'atmos-retro-room'
  const kept = emptyKept()
  const geo = new PlaneGeometry(16, 16)
  geo.rotateX(-Math.PI / 2)
  const mat = new MeshBasicMaterial({ color: resolved.stone })
  root.add(new Mesh(geo, mat))
  kept.geometries.push(geo)
  kept.materials.push(mat)
  return { root, kept }
}

function paintBoxes(mesh: InstancedMesh, parts: readonly Part[]) {
  const dummy = new Object3D()
  const color = new Color()
  const tinted = parts.some(part => part.color)
  parts.forEach((part, index) => {
    dummy.position.set(part.at[0], part.at[1], part.at[2])
    dummy.rotation.set(0, part.yaw ?? 0, part.roll ?? 0)
    dummy.scale.set(part.scale[0], part.scale[1], part.scale[2])
    dummy.updateMatrix()
    mesh.setMatrixAt(index, dummy.matrix)
    if (!tinted) return
    color.set(part.color ?? '#ffffff')
    mesh.setColorAt(index, color)
  })
  mesh.instanceMatrix.needsUpdate = true
  if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true
}

function addBoxes(root: Group, kept: Kept, name: string, fallback: string, parts: readonly Part[], side: Side = FrontSide) {
  const tinted = parts.some(part => part.color)
  const geo = new BoxGeometry(1, 1, 1)
  const mat = new MeshBasicMaterial({ color: tinted ? '#ffffff' : fallback, side })
  const mesh = new InstancedMesh(geo, mat, parts.length)
  mesh.name = name
  paintBoxes(mesh, parts)
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
  return mesh
}

function addPlane(
  root: Group,
  kept: Kept,
  name: string,
  color: string,
  width: number,
  height: number,
  at: [number, number, number],
  rotX: number,
  yaw = 0,
  side: Side = FrontSide,
) {
  const geo = new PlaneGeometry(width, height)
  if (rotX) geo.rotateX(rotX)
  const mat = new MeshBasicMaterial({ color, side })
  const mesh = new Mesh(geo, mat)
  mesh.name = name
  mesh.position.set(at[0], at[1], at[2])
  mesh.rotation.y = yaw
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
  return mesh
}

function wallParts(): Part[] {
  const cy = 1.35
  const cz = 0.35
  return [
    { at: [0, cy, -4.42], scale: [6.98, 2.7, 0.14] },
    { at: [0, cy, 5.12], scale: [6.98, 2.7, 0.14] },
    { at: [-3.42, cy, cz], scale: [0.14, 2.7, 9.68] },
    { at: [3.42, cy, cz], scale: [0.14, 2.7, 9.68] },
  ]
}

function trimParts(): Part[] {
  const y = 0.06
  return [
    { at: [0, y, -4.28], scale: [6.5, 0.12, 0.06] },
    { at: [0, y, 4.98], scale: [6.5, 0.12, 0.06] },
    { at: [-3.28, y, 0.35], scale: [0.06, 0.12, 9.2] },
    { at: [3.28, y, 0.35], scale: [0.06, 0.12, 9.2] },
  ]
}

function scanParts(count: number): Part[] {
  const parts: Part[] = []
  for (let i = 0; i < count; i += 1) {
    const t = count === 1 ? 0.5 : i / (count - 1)
    const y = SCREEN_Y + (t - 0.5) * 0.62
    parts.push({ at: [SCREEN_X, y, SCREEN_Z + 0.012], scale: [1.0, 0.016, 0.006] })
  }
  return parts
}

function snowSpots(count: number, seed: number): Array<[number, number, number]> {
  const spots: Array<[number, number, number]> = []
  for (let n = 0; n < count; n += 1) {
    const x = SCREEN_X + (hash2(n, 3, seed) - 0.5) * 0.9
    spots.push([x, SCREEN_Y, SCREEN_Z + 0.022])
  }
  return spots
}

function crtParts(palette: string): Part[] {
  const wood = swatch(WOOD, palette)
  const bezel = swatch(BEZEL, palette)
  return [
    { at: [-2.05, 0.22, -3.72], scale: [1.36, 0.44, 0.46], color: wood },
    { at: [-2.05, 0.46, -3.7], scale: [1.5, 0.06, 0.54], color: wood },
    { at: [-2.05, 1.02, -3.78], scale: [1.34, 1.06, 0.42], color: bezel },
    { at: [-2.83, 0.72, -3.74], scale: [0.22, 0.72, 0.28], color: '#2a2824' },
    { at: [-1.27, 0.72, -3.74], scale: [0.22, 0.72, 0.28], color: '#2a2824' },
    { at: [-2.32, 1.72, -3.78], scale: [0.03, 0.32, 0.03], roll: 0.55, color: '#b7bcc4' },
    { at: [-1.78, 1.72, -3.78], scale: [0.03, 0.32, 0.03], roll: -0.55, color: '#b7bcc4' },
  ]
}

function consoleParts(palette: string): Part[] {
  return [
    { at: [2.15, 0.16, -3.58], scale: [1.15, 0.28, 0.64], color: '#8b909a' },
    { at: [2.15, 0.38, -3.58], scale: [0.38, 0.24, 0.16], color: swatch(CART, palette) },
    { at: [2.15, 0.18, -3.24], scale: [0.72, 0.05, 0.03], color: '#2a2e34' },
    { at: [2.58, 0.22, -3.24], scale: [0.07, 0.07, 0.03], color: '#3dba6a' },
  ]
}

function padAt(x: number, y: number, z: number): [number, number, number] {
  return [PAD_X + x, PAD_Y + y, PAD_Z + z]
}

function controllerParts(): Part[] {
  const grip = '#5c626c'
  return [
    { at: padAt(0, 0, 0.04), scale: [0.36, 0.09, 0.42], color: '#6d7380' },
    { at: padAt(-0.52, 0, 0.06), scale: [0.3, 0.08, 0.72], color: grip },
    { at: padAt(0.52, 0, 0.06), scale: [0.3, 0.08, 0.72], color: grip },
    { at: padAt(0, 0.01, 0.28), scale: [0.26, 0.08, 0.36], color: '#7a808a' },
    { at: padAt(0, 0.12, 0.36), scale: [0.12, 0.14, 0.12], color: '#2a2e34' },
    { at: padAt(-0.52, 0.07, 0.18), scale: [0.16, 0.04, 0.16], color: '#3a4048' },
    { at: padAt(0.42, 0.07, 0.26), scale: [0.11, 0.05, 0.11], color: '#f0d24a' },
    { at: padAt(0.62, 0.07, 0.26), scale: [0.11, 0.05, 0.11], color: '#3cba6a' },
    { at: padAt(0.42, 0.07, 0.08), scale: [0.11, 0.05, 0.11], color: '#e04a4a' },
    { at: padAt(0.62, 0.07, 0.08), scale: [0.11, 0.05, 0.11], color: '#3a7ee0' },
  ]
}

function gameParts(): Part[] {
  const labels = ['#d24a3a', '#3a7ee0', '#3cba6a', '#f0d050']
  return labels.map((color, index) => ({
    at: [1.55 + index * 0.28, 1.72, -4.28] as [number, number, number],
    scale: [0.22, 0.32, 0.04] as [number, number, number],
    color,
  }))
}

function placeSnow(mesh: InstancedMesh, spots: Array<[number, number, number]>, seconds: number, palette: string, variant: number | undefined, seed: number) {
  const dummy = new Object3D()
  const tint = new Color(swatch(PHOSPHOR, palette)).multiplyScalar(screenGain(variant))
  tint.lerp(new Color('#f4fff6'), staticAmount(variant) / 8)
  spots.forEach(([x, , z], index) => {
    const roll = (seconds * 0.55 + hash2(index, 9, seed)) % 1
    const jx = Math.sin(seconds * 5 + index) * 0.015
    dummy.position.set(x + jx, SCREEN_Y + (roll - 0.5) * 0.62, z)
    dummy.rotation.set(0, 0, 0)
    dummy.scale.set(0.04, 0.04, 0.008)
    dummy.updateMatrix()
    mesh.setMatrixAt(index, dummy.matrix)
    mesh.setColorAt(index, tint)
  })
  mesh.instanceMatrix.needsUpdate = true
  if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true
}

function paintScreen(root: Group, palette: string, variant: number | undefined) {
  const phosphor = new Color(swatch(PHOSPHOR, palette)).multiplyScalar(screenGain(variant))
  const mix = staticAmount(variant) / 8
  const screen = root.getObjectByName('atmos-screen') as Mesh | undefined
  const scan = root.getObjectByName('atmos-scan') as InstancedMesh | undefined
  const glow = root.getObjectByName('atmos-glow') as Mesh | undefined
  if (screen?.material instanceof MeshBasicMaterial) screen.material.color.copy(phosphor)
  if (scan?.material instanceof MeshBasicMaterial) scan.material.color.copy(phosphor).lerp(new Color('#10141c'), mix)
  if (glow?.material instanceof MeshBasicMaterial) glow.material.color.copy(phosphor).multiplyScalar(0.45)
}

function tintNamed(root: Group, name: string, hex: string, gain: number) {
  const mesh = root.getObjectByName(name) as Mesh | undefined
  const material = mesh?.material
  if (material instanceof MeshBasicMaterial || material instanceof MeshStandardMaterial) material.color.set(hex).multiplyScalar(gain)
}

function paintRoom(root: Group, palette: string, time: string) {
  const gain = time === 'on' ? 1 : 0.55
  tintNamed(root, 'atmos-wall', swatch(WALL, palette), gain)
  tintNamed(root, 'atmos-floor', swatch(FLOOR, palette), gain)
  tintNamed(root, 'atmos-ceiling', swatch(CEILING, palette), gain)
  tintNamed(root, 'atmos-rug', swatch(RUG, palette), gain)
  tintNamed(root, 'atmos-trim', swatch(WOOD, palette), gain)
  const lamp = root.getObjectByName('atmos-lamp') as Mesh | undefined
  if (lamp?.material instanceof MeshBasicMaterial) lamp.material.color.set(time === 'on' ? '#fff3c2' : '#2a261c')
}

function syncFog(root: Group, settings: AtmosSettings) {
  const parent = root.parent as { fog?: unknown; background?: unknown } | null
  if (!parent) return
  const hex = settings.timeOfDay === 'on' ? swatch(FOG_ON, settings.palette) : swatch(FOG_DIM, settings.palette)
  if (parent.fog instanceof FogExp2) {
    parent.fog.color.set(hex)
    parent.fog.density = 0.01 + settings.fogDensity * 0.018
  }
  if (parent.background instanceof Color) parent.background.set(hex)
}

/** Swap a flat unlit surface for a lit, textured one that keeps its colour, side and name. */
function litSurface(mesh: Mesh | InstancedMesh, kept: Kept, texture: Texture | null, repeat: [number, number]) {
  const old = mesh.material as MeshBasicMaterial
  if (texture) {
    texture.repeat.set(repeat[0], repeat[1])
    kept.textures.push(texture)
  }
  const mat = new MeshStandardMaterial({ color: old.color.clone(), map: texture, roughness: 0.92, side: old.side })
  mesh.material = mat
  kept.materials.push(mat)
}

function addShell(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const floor = addPlane(root, kept, 'atmos-floor', swatch(FLOOR, resolved.palette), 6.7, 9.4, [0, 0, 0.35], -Math.PI / 2)
  floor.frustumCulled = false
  litSurface(floor, kept, plankTexture(resolved.seed), [6.7, 9.4])
  const walls = addBoxes(root, kept, 'atmos-wall', swatch(WALL, resolved.palette), wallParts(), DoubleSide)
  walls.frustumCulled = false
  litSurface(walls, kept, wallpaperTexture(resolved.seed), [3.5, 1])
  const ceiling = addPlane(root, kept, 'atmos-ceiling', swatch(CEILING, resolved.palette), 6.7, 9.4, [0, 2.7, 0.35], Math.PI / 2, 0, DoubleSide)
  ceiling.frustumCulled = false
  addBoxes(root, kept, 'atmos-trim', swatch(WOOD, resolved.palette), trimParts())
  addPlane(root, kept, 'atmos-rug', swatch(RUG, resolved.palette), 2.2, 1.5, [-2.05, 0.01, -3.35], -Math.PI / 2)
  addPlane(root, kept, 'atmos-glow', swatch(PHOSPHOR, resolved.palette), 1.15, 0.7, [SCREEN_X, 0.02, -2.95], -Math.PI / 2)
}

function addTelevision(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  addBoxes(root, kept, 'atmos-crt', swatch(BEZEL, resolved.palette), crtParts(resolved.palette))
  addPlane(root, kept, 'atmos-screen', swatch(PHOSPHOR, resolved.palette), 1.02, 0.74, [SCREEN_X, SCREEN_Y, SCREEN_Z], 0)
  addBoxes(root, kept, 'atmos-scan', '#10141c', scanParts(resolved.moteCount))
  const spots = snowSpots(resolved.grassBlades, resolved.seed)
  const snow = addBoxes(root, kept, 'atmos-static', '#ffffff', spots.map(at => ({ at, scale: [0.04, 0.04, 0.008] as [number, number, number] })))
  snow.userData.spots = spots
}

function addConsole(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  addBoxes(root, kept, 'atmos-console', '#c5c8d0', consoleParts(resolved.palette))
  addBoxes(root, kept, 'atmos-games', '#ffffff', gameParts())
}

function addController(root: Group, kept: Kept) {
  addBoxes(root, kept, 'atmos-controller', '#d7dae2', controllerParts())
}

const SPINES = ['#d24a3a', '#3a6ad2', '#e6c43a', '#4aa86a', '#8a8f9a', '#7a4ad2']

/** A bookshelf of cartridges, bean bag, plant, curtains, framed pictures and a floor lamp, merged into one mesh. */
function decorPieces(seed: number): Piece[] {
  const pieces: Piece[] = [
    { type: 'box', at: [-3.33, 0.95, -1.2], size: [0.03, 1.9, 1.44], color: '#6b4a2e' },
    { type: 'box', at: [-3.17, 0.95, -1.9], size: [0.36, 1.9, 0.04], color: '#8a5a34' },
    { type: 'box', at: [-3.17, 0.95, -0.5], size: [0.36, 1.9, 0.04], color: '#8a5a34' },
    { type: 'sphere', at: [2.5, 0.3, -1.4], size: [1.0, 0.62, 0.95], color: '#d24a3a' },
    { type: 'cylinder', at: [2.9, 0.18, -3.95], size: [0.34, 0.36, 0.34], color: '#a8573a' },
    { type: 'box', at: [3.25, 1.45, -0.78], size: [0.06, 1.45, 0.34], color: '#a8453a' },
    { type: 'box', at: [3.25, 1.45, 0.38], size: [0.06, 1.45, 0.34], color: '#a8453a' },
    { type: 'cylinder', at: [3.25, 2.2, -0.2], size: [0.04, 1.4, 0.04], turn: [Math.PI / 2, 0, 0], color: '#3a2a1c' },
    { type: 'cylinder', at: [-0.6, 0.02, -3.95], size: [0.26, 0.04, 0.26], color: '#2a2a2a' },
    { type: 'cylinder', at: [-0.6, 0.77, -3.95], size: [0.03, 1.5, 0.03], color: '#2a2a2a' },
    { type: 'cone', at: [-0.6, 1.62, -3.95], size: [0.42, 0.34, 0.42], color: '#f2d9a0' },
  ]
  for (const y of [0.02, 0.5, 0.95, 1.4, 1.88]) pieces.push({ type: 'box', at: [-3.17, y, -1.2], size: [0.36, 0.04, 1.44], color: '#8a5a34' })
  for (const [row, y] of [0.04, 0.52, 0.97, 1.42].entries()) {
    for (let i = 0; i < 10; i += 1) {
      const h = 0.18 + hash2(row * 10 + i, 3, seed) * 0.14
      pieces.push({ type: 'box', at: [-3.17, y + h / 2 + 0.02, -1.83 + i * 0.14], size: [0.22, h, 0.1], color: SPINES[Math.floor(hash2(row * 10 + i, 4, seed) * SPINES.length)] })
    }
  }
  for (let k = 0; k < 5; k += 1) {
    const a = k * 1.26
    pieces.push({ type: 'cone', at: [2.9 + Math.cos(a) * 0.12, 0.62, -3.95 + Math.sin(a) * 0.12], size: [0.22, 0.75, 0.22], turn: [Math.sin(a) * 0.45, 0, -Math.cos(a) * 0.45], color: '#3f8a4a' })
  }
  for (const [x, y, inner] of [[-0.9, 1.75, '#e8c25a'], [0.1, 1.55, '#4a8ad2'], [1.1, 1.8, '#d24a3a']] as const) {
    pieces.push({ type: 'box', at: [x, y, -4.32], size: [0.55, 0.42, 0.03], color: '#2a2018' })
    pieces.push({ type: 'box', at: [x, y, -4.3], size: [0.45, 0.32, 0.035], color: inner })
  }
  return pieces
}

function addDecor(root: Group, kept: Kept, seed: number) {
  const geo = composeGeometry(decorPieces(seed))
  const mat = new MeshStandardMaterial({ vertexColors: true, flatShading: true, roughness: 0.9 })
  const mesh = new Mesh(geo, mat)
  mesh.name = 'atmos-decor'
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

/** The lamp warms the room; the TV washes it in phosphor and flickers with the picture. */
function addLights(root: Group, resolved: ResolvedAtmos) {
  const lamp = new PointLight(0xffc98a, 6, 9, 2)
  lamp.name = 'atmos-lamp-light'
  lamp.position.set(-0.6, 1.2, -3.5)
  const tube = new PointLight(new Color(swatch(PHOSPHOR, resolved.palette)), 7, 8, 2)
  tube.name = 'atmos-crt-light'
  tube.position.set(SCREEN_X, SCREEN_Y, SCREEN_Z + 0.9)
  root.add(lamp, tube)
}

function addDressing(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  addDecor(root, kept, resolved.seed)
  addLights(root, resolved)
  addPlane(root, kept, 'atmos-poster', swatch(POSTER, resolved.palette), 0.62, 0.86, [-3.28, 1.5, -1.6], 0, Math.PI / 2)
  addPlane(root, kept, 'atmos-window', '#1c2436', 0.9, 0.7, [3.28, 1.55, -0.2], 0, -Math.PI / 2)
  addBoxes(root, kept, 'atmos-lamp', '#2a261c', [{ at: [-0.2, 2.58, -2.2], scale: [0.55, 0.06, 0.28] }])
}

function syncRoom(root: Group, seconds: number, resolved: ResolvedAtmos, live?: AtmosSettings) {
  const settings = live ?? resolved
  const tube = root.getObjectByName('atmos-crt-light') as PointLight | undefined
  if (tube) {
    tube.intensity = 7 * screenGain(settings.variant) * (0.84 + 0.16 * Math.sin(seconds * 31 + Math.sin(seconds * 7)))
    tube.color.set(swatch(PHOSPHOR, settings.palette))
  }
  paintScreen(root, settings.palette, settings.variant)
  paintRoom(root, settings.palette, settings.timeOfDay)
  const snow = root.getObjectByName('atmos-static') as InstancedMesh | undefined
  const spots = snow?.userData.spots as Array<[number, number, number]> | undefined
  if (snow && spots) placeSnow(snow, spots, seconds, settings.palette, settings.variant, resolved.seed)
  syncFog(root, settings)
}

function liveHandle(root: Group, kept: Kept, resolved: ResolvedAtmos): AtmosHandle {
  return {
    ms: { shafts: 0, dof: 0, grade: 0 },
    passes: () => [],
    sync: (seconds, _camera, _light, _quality, _focus, live) => syncRoom(root, seconds, resolved, live),
    dispose: disposeOnce(() => disposeKept(root, kept)),
  }
}

export function buildRetroRoom(resolved: ResolvedAtmos, webgl2: boolean): { root: Group; handle: AtmosHandle } {
  if (!webgl2) {
    const flat = flatRoom(resolved)
    const handle = idleHandle(flat.root, flat.kept)
    flat.root.userData.atmos = handle
    return { root: flat.root, handle }
  }
  const root = new Group()
  root.name = 'atmos-retro-room'
  const kept = emptyKept()
  addShell(root, resolved, kept)
  addTelevision(root, resolved, kept)
  addConsole(root, resolved, kept)
  addController(root, kept)
  addDressing(root, resolved, kept)
  syncRoom(root, 0, resolved)
  const handle = liveHandle(root, kept, resolved)
  root.userData.atmos = handle
  return { root, handle }
}

export const retroRoomSet: AtmosSetDefinition = {
  id: 'atmos-retro-room',
  titleKey: 'template.atmos-retro-room-wide.title',
  setting: 'room',
  seed: 98017,
  subject: CLEARING_SUBJECT,
  subjectYaw: 0.15,
  palettes: ROOM_PALETTES,
  times: ROOM_TIMES,
  defaults: { timeOfDay: 'dim', fogDensity: 0.08, wind: 0.05, motes: 0.2, palette: 'cream', variant: 3 },
  variant: { labelKey: 'atmos.static', min: 0, max: 8 },
  low: { shaftSteps: 0, grassBlades: 24, moteCount: 8 },
  high: { shaftSteps: 0, grassBlades: 36, moteCount: 10 },
  templates: [
    { id: 'atmos-retro-room-wide', camera: 'establishment', eye: WIDE_EYE, look: WIDE_LOOK, fov: 56, duration: 6 },
    { id: 'atmos-retro-room-low', camera: 'establishment', eye: LOW_EYE, look: LOW_LOOK, fov: 62, duration: 6 },
  ],
  build: buildRetroRoom,
  fallback(resolved) {
    const sky = ROOM_PALETTES[resolved.palette as keyof typeof ROOM_PALETTES]?.fog ?? ROOM_PALETTES.cream.fog
    return { sky: hexColor(sky), ground: hexColor(FALLBACK_GROUND[resolved.palette] ?? FALLBACK_GROUND.cream) }
  },
}
