import {
  AdditiveBlending,
  BackSide,
  BoxGeometry,
  BufferGeometry,
  CircleGeometry,
  Color,
  ConeGeometry,
  CylinderGeometry,
  DataTexture,
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
  RGBAFormat,
  ShaderMaterial,
  SphereGeometry,
  type Material,
  type Texture,
} from 'three'
import type { AtmosHandle } from './clearing.ts'
import type { AtmosSetDefinition } from '../definition.ts'
import type { AtmosSettings, ResolvedAtmos } from '../params.ts'
import { hash2 } from '../noise.ts'
import { CLEARING_SUBJECT } from '../layout.ts'
import { canvasTexture } from '../textures.ts'
import {
  circuitBridges,
  circuitChips,
  circuitTowers,
  heatsinkFins,
  ledLit,
  pulseRate,
  worldOffset,
  type Bridge,
  type Chip,
  type Fin,
  type Tower,
} from './siliconCircuitLayout.ts'

type Kept = { geometries: BufferGeometry[]; materials: Material[]; textures: Texture[] }
type LedSpot = { x: number; y: number; z: number }

const BOARD_VERTEX = `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`
const BOARD_FRAGMENT = `
  uniform sampler2D uMap;
  uniform float uUseMap;
  uniform float uSweep;
  uniform float uGain;
  uniform vec3 uTrace;
  uniform vec3 uBoard;
  varying vec2 vUv;
  void main() {
    vec3 base = uBoard;
    if (uUseMap > 0.5) base = texture2D(uMap, vUv * 3.0).rgb;
    float band = 1.0 - smoothstep(0.0, 0.08, abs(fract(vUv.y * 2.0 - uSweep) - 0.5));
    gl_FragColor = vec4(base + uTrace * band * 0.85 * uGain, 1.0);
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
  uniform vec3 uLow;
  uniform vec3 uCopper;
  varying vec3 vDir;
  void main() {
    float h = clamp(normalize(vDir).y * 0.5 + 0.35, 0.0, 1.0);
    vec3 band = mix(uLow, uHigh, smoothstep(0.05, 0.85, h));
    float cap = smoothstep(0.42, 0.9, h);
    gl_FragColor = vec4(mix(band, uCopper, cap * 0.75), 1.0);
  }
`

const WIDE_EYE = [0.25, 2.15, 4.6] as const
const WIDE_LOOK = [0.2, 2.4, -6] as const
const LOW_EYE = [1.2, 0.18, 0.85] as const
const LOW_LOOK = [0.15, 2.8, -8] as const
const CIRCUIT_PALETTES = {
  phosphor: { fog: '#02110a', ground: '#010804', accent: '#33ff66', sky: ['#02110a', '#0b3d1e'] },
  outrun: { fog: '#120458', ground: '#05010f', accent: '#05d9e8', sky: ['#7a04eb', '#ff2a6d'] },
} as const
const CIRCUIT_TIMES = {
  idle: { sun: [0.2, -0.55, -0.8] as const, sunColor: '#9ad7ff' },
  compute: { sun: [0.05, -0.92, -0.35] as const, sunColor: '#e8fbff' },
}
const SECOND: Record<string, string> = { phosphor: '#ffb000', outrun: '#ff6ec7' }
const FALLBACK_GROUND: Record<string, string> = { phosphor: '#010804', outrun: '#05010f' }

function emptyKept(): Kept {
  return { geometries: [], materials: [], textures: [] }
}

function hexColor(color: string): [number, number, number] {
  const n = Number.parseInt(color.slice(1), 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

function swatch(table: Record<string, string>, palette: string): string {
  return table[palette] ?? table.phosphor
}

function paletteOf(name: string) {
  if (name === 'outrun') return CIRCUIT_PALETTES.outrun
  return CIRCUIT_PALETTES.phosphor
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

function paintTraces(ctx: CanvasRenderingContext2D, size: number, seed: number, trace: string, board: string) {
  ctx.fillStyle = board
  ctx.fillRect(0, 0, size, size)
  ctx.fillStyle = trace
  for (let i = 0; i < 36; i += 1) {
    const x = Math.floor(hash2(i, 1, seed) * (size - 8))
    const y = Math.floor(hash2(i, 2, seed) * (size - 8))
    const alongX = hash2(i, 3, seed) > 0.5
    const len = 14 + Math.floor(hash2(i, 4, seed) * 36)
    if (alongX) ctx.fillRect(x, y, len, 2)
    else ctx.fillRect(x, y, 2, len)
    const elbow = hash2(i, 5, seed) > 0.4
    if (elbow && alongX) ctx.fillRect(x + len, y, 2, 18)
    if (elbow && !alongX) ctx.fillRect(x, y + len, 18, 2)
    ctx.fillRect(x - 1, y - 1, 4, 4)
  }
}

function diagonalTraces(ctx: CanvasRenderingContext2D, size: number, seed: number) {
  for (let i = 0; i < 12; i += 1) {
    let x = Math.floor(hash2(i, 8, seed) * size)
    let y = Math.floor(hash2(i, 9, seed) * size)
    const steps = 8 + Math.floor(hash2(i, 10, seed) * 14)
    const down = hash2(i, 11, seed) > 0.5 ? 3 : -3
    for (let k = 0; k < steps; k += 1) {
      ctx.fillRect(x, y, 2, 2)
      x += 3
      y += down
    }
  }
}

function boardTexture(resolved: ResolvedAtmos, kept: Kept): { map: Texture; use: number } {
  const look = paletteOf(resolved.palette)
  const painted = canvasTexture(128, (ctx, size) => {
    paintTraces(ctx, size, resolved.seed, look.accent, look.ground)
    diagonalTraces(ctx, size, resolved.seed)
  }, true)
  if (painted) {
    kept.textures.push(painted)
    return { map: painted, use: 1 }
  }
  const blank = new DataTexture(new Uint8Array([1, 8, 4, 255]), 1, 1, RGBAFormat)
  blank.needsUpdate = true
  kept.textures.push(blank)
  return { map: blank, use: 0 }
}

function addBoard(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const look = paletteOf(resolved.palette)
  const geo = new PlaneGeometry(22, 22)
  geo.rotateX(-Math.PI / 2)
  const board = boardTexture(resolved, kept)
  const mat = new ShaderMaterial({
    uniforms: {
      uMap: { value: board.map },
      uUseMap: { value: board.use },
      uSweep: { value: 0 },
      uGain: { value: resolved.timeOfDay === 'compute' ? 1.35 : 0.62 },
      uTrace: { value: new Color(look.accent) },
      uBoard: { value: new Color(look.ground) },
    },
    vertexShader: BOARD_VERTEX,
    fragmentShader: BOARD_FRAGMENT,
  })
  const mesh = new Mesh(geo, mat)
  mesh.name = 'atmos-board'
  addDrawn(root, kept, mesh)
}

function addSky(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const look = paletteOf(resolved.palette)
  const geo = new SphereGeometry(40, 16, 10)
  const mat = new ShaderMaterial({
    side: BackSide,
    depthWrite: false,
    uniforms: {
      uHigh: { value: new Color(look.sky[0]) },
      uLow: { value: new Color(look.sky[1]) },
      uCopper: { value: new Color('#5c3318') },
    },
    vertexShader: SKY_VERTEX,
    fragmentShader: SKY_FRAGMENT,
  })
  const mesh = new Mesh(geo, mat)
  mesh.name = 'atmos-sky'
  mesh.frustumCulled = false
  addDrawn(root, kept, mesh)
}

function addBeam(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const geo = new ConeGeometry(2.2, 9.2, 16, 1, true)
  geo.rotateX(Math.PI)
  const mat = new MeshBasicMaterial({
    color: paletteOf(resolved.palette).accent,
    transparent: true,
    opacity: resolved.timeOfDay === 'compute' ? 0.18 : 0.08,
    blending: AdditiveBlending,
    depthWrite: false,
    side: BackSide,
  })
  const mesh = new Mesh(geo, mat)
  mesh.name = 'atmos-beam'
  mesh.position.set(CLEARING_SUBJECT[0], 4.7, CLEARING_SUBJECT[2])
  addDrawn(root, kept, mesh)
}

function placeBox(mesh: InstancedMesh, index: number, x: number, y: number, z: number, sx: number, sy: number, sz: number, yaw: number) {
  const dummy = new Object3D()
  dummy.position.set(x, y, z)
  dummy.rotation.y = yaw
  dummy.scale.set(sx, sy, sz)
  dummy.updateMatrix()
  mesh.setMatrixAt(index, dummy.matrix)
}

function addChips(root: Group, chips: readonly Chip[], kept: Kept) {
  const mesh = new InstancedMesh(new BoxGeometry(1, 1, 1), new MeshBasicMaterial({ color: '#07080c' }), chips.length)
  mesh.name = 'atmos-chip'
  chips.forEach((chip, index) => placeBox(mesh, index, chip.x, chip.h / 2, chip.z, chip.w, chip.h, chip.d, chip.yaw))
  mesh.instanceMatrix.needsUpdate = true
  addDrawn(root, kept, mesh)
}

function addPins(root: Group, chips: readonly Chip[], kept: Kept) {
  const mesh = new InstancedMesh(new BoxGeometry(1, 1, 1), new MeshBasicMaterial({ color: '#8b95a1' }), chips.length * 4)
  mesh.name = 'atmos-pin'
  chips.forEach((chip, index) => {
    const side = chip.w / 2 + 0.08
    const inset = chip.d * 0.28
    const spots: Array<[number, number]> = [[side, inset], [side, -inset], [-side, inset], [-side, -inset]]
    spots.forEach(([lx, lz], pin) => {
      const [dx, dz] = worldOffset(chip.yaw, lx, lz)
      placeBox(mesh, index * 4 + pin, chip.x + dx, chip.h * 0.16, chip.z + dz, 0.2, Math.max(0.5, chip.h * 0.1), 0.14, chip.yaw)
    })
  })
  mesh.instanceMatrix.needsUpdate = true
  addDrawn(root, kept, mesh)
}

function addDots(root: Group, chips: readonly Chip[], kept: Kept, palette: string) {
  const mesh = new InstancedMesh(new BoxGeometry(1, 1, 1), new MeshBasicMaterial({ color: swatch(SECOND, palette) }), chips.length)
  mesh.name = 'atmos-dot'
  chips.forEach((chip, index) => {
    const [dx, dz] = worldOffset(chip.yaw, chip.w * 0.32, chip.d * 0.28)
    placeBox(mesh, index, chip.x + dx, chip.h + 0.04, chip.z + dz, 0.22, 0.06, 0.22, chip.yaw)
  })
  mesh.instanceMatrix.needsUpdate = true
  addDrawn(root, kept, mesh)
}

function addTowers(root: Group, towers: readonly Tower[], kept: Kept) {
  const mesh = new InstancedMesh(new CylinderGeometry(1, 1, 1, 10), new MeshBasicMaterial({ color: '#c5cad1' }), towers.length)
  mesh.name = 'atmos-cap'
  towers.forEach((tower, index) => placeBox(mesh, index, tower.x, tower.h / 2, tower.z, tower.r, tower.h, tower.r, 0))
  mesh.instanceMatrix.needsUpdate = true
  addDrawn(root, kept, mesh)
}

function addBridges(root: Group, bridges: readonly Bridge[], kept: Kept) {
  const mesh = new InstancedMesh(new BoxGeometry(1, 1, 1), new MeshBasicMaterial({ color: '#b4532a' }), bridges.length)
  mesh.name = 'atmos-bridge'
  bridges.forEach((bridge, index) => placeBox(mesh, index, bridge.x, 0.34, bridge.z, bridge.length, 0.38, 0.46, bridge.yaw))
  mesh.instanceMatrix.needsUpdate = true
  addDrawn(root, kept, mesh)
}

function addFins(root: Group, fins: readonly Fin[], kept: Kept) {
  const ridge = new Mesh(new BoxGeometry(6.2, 0.55, 1.45), new MeshBasicMaterial({ color: '#12161c' }))
  ridge.name = 'atmos-ridge'
  ridge.position.set(0, 0.42, -8.7)
  addDrawn(root, kept, ridge)
  const mesh = new InstancedMesh(new BoxGeometry(1, 1, 1), new MeshBasicMaterial({ color: '#1c242e' }), fins.length)
  mesh.name = 'atmos-fin'
  fins.forEach((fin, index) => placeBox(mesh, index, fin.x, fin.y, fin.z, fin.sx, fin.sy, fin.sz, 0))
  mesh.instanceMatrix.needsUpdate = true
  addDrawn(root, kept, mesh)
}

function ledSpots(chips: readonly Chip[]): LedSpot[] {
  return chips.map(chip => ({ x: chip.x, y: chip.h + 0.06, z: chip.z }))
}

function addLeds(root: Group, chips: readonly Chip[], kept: Kept, palette: string) {
  const mesh = new InstancedMesh(new BoxGeometry(0.28, 0.08, 0.28), new MeshBasicMaterial({
    color: '#ffffff',
    blending: AdditiveBlending,
    depthWrite: false,
    transparent: true,
  }), chips.length)
  mesh.name = 'atmos-led'
  mesh.userData.leds = ledSpots(chips)
  const color = new Color(paletteOf(palette).accent)
  chips.forEach((chip, index) => {
    placeBox(mesh, index, chip.x, chip.h + 0.06, chip.z, 1, 1, 1, 0)
    mesh.setColorAt(index, color)
  })
  mesh.instanceMatrix.needsUpdate = true
  if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true
  addDrawn(root, kept, mesh)
}

function addMotes(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const positions: number[] = []
  for (let index = 0; index < resolved.moteCount; index += 1) {
    const x = -8 + hash2(index, 2, resolved.seed) * 16
    const z = -9 + hash2(index, 4, resolved.seed) * 5.5
    positions.push(x, 0.04 + hash2(index, 6, resolved.seed) * 1.4, z)
  }
  const geo = new BufferGeometry()
  geo.setAttribute('position', new Float32BufferAttribute(positions, 3))
  const mat = new PointsMaterial({
    color: paletteOf(resolved.palette).accent,
    size: 0.045,
    sizeAttenuation: true,
    depthWrite: false,
  })
  const points = new Points(geo, mat)
  points.name = 'atmos-mote'
  addDrawn(root, kept, points)
}

function addPad(root: Group, kept: Kept) {
  const geo = new CircleGeometry(1.05, 24)
  geo.rotateX(-Math.PI / 2)
  const mesh = new Mesh(geo, new MeshBasicMaterial({ color: '#020403' }))
  mesh.name = 'atmos-pad'
  mesh.position.set(CLEARING_SUBJECT[0], 0.015, CLEARING_SUBJECT[2])
  addDrawn(root, kept, mesh)
}

function flatCircuit(resolved: ResolvedAtmos): { root: Group; kept: Kept } {
  const root = new Group()
  root.name = 'atmos-silicon-circuit'
  const kept = emptyKept()
  const geo = new PlaneGeometry(10, 10)
  geo.rotateX(-Math.PI / 2)
  const mesh = new Mesh(geo, new MeshBasicMaterial({ color: paletteOf(resolved.palette).ground }))
  mesh.name = 'atmos-pad'
  mesh.position.set(CLEARING_SUBJECT[0], 0, CLEARING_SUBJECT[2])
  addDrawn(root, kept, mesh)
  return { root, kept }
}

function paintBoard(root: Group, settings: AtmosSettings, seconds: number) {
  const mesh = root.getObjectByName('atmos-board') as Mesh | undefined
  if (!mesh) return
  const mat = mesh.material as ShaderMaterial
  mat.uniforms.uSweep.value = (seconds * pulseRate(settings.timeOfDay)) % 1
  mat.uniforms.uGain.value = settings.timeOfDay === 'compute' ? 1.35 : 0.62
  ;(mat.uniforms.uTrace.value as Color).set(paletteOf(settings.palette).accent)
  ;(mat.uniforms.uBoard.value as Color).set(paletteOf(settings.palette).ground)
}

function paintLeds(root: Group, resolved: ResolvedAtmos, seconds: number) {
  const leds = root.getObjectByName('atmos-led') as InstancedMesh | undefined
  const spots = leds?.userData.leds as LedSpot[] | undefined
  if (!leds || !spots) return
  const dummy = new Object3D()
  const on = new Color(paletteOf(resolved.palette).accent)
  const off = new Color('#041208')
  spots.forEach((spot, index) => {
    const lit = ledLit(index, spots.length, resolved.variant, seconds, resolved.timeOfDay, resolved.seed)
    dummy.position.set(spot.x, spot.y, spot.z)
    dummy.rotation.set(0, 0, 0)
    dummy.scale.set(1, lit ? 1 : 0.12, 1)
    dummy.updateMatrix()
    leds.setMatrixAt(index, dummy.matrix)
    leds.setColorAt(index, lit ? on : off)
  })
  leds.instanceMatrix.needsUpdate = true
  if (leds.instanceColor) leds.instanceColor.needsUpdate = true
}

function paintBeam(root: Group, settings: AtmosSettings) {
  const beam = root.getObjectByName('atmos-beam') as Mesh | undefined
  if (!beam) return
  const mat = beam.material as MeshBasicMaterial
  mat.color.set(paletteOf(settings.palette).accent)
  mat.opacity = settings.timeOfDay === 'compute' ? 0.18 : 0.08
}

function tuneFog(root: Group, density: number) {
  const fog = (root.parent as { fog?: unknown } | null)?.fog
  if (fog instanceof FogExp2) fog.density = 0.012 + density * 0.018
}

function syncCircuit(root: Group, seconds: number, resolved: ResolvedAtmos, live?: AtmosSettings) {
  const settings = live ?? resolved
  const next = { ...resolved, ...settings }
  paintBoard(root, next, seconds)
  paintLeds(root, next, seconds)
  paintBeam(root, next)
  tuneFog(root, next.fogDensity)
}

function liveHandle(root: Group, kept: Kept, resolved: ResolvedAtmos): AtmosHandle {
  return {
    ms: { shafts: 0, dof: 0, grade: 0 },
    passes: () => [],
    sync: (seconds, _camera, _light, _quality, _focus, live) => syncCircuit(root, seconds, resolved, live),
    dispose: disposeOnce(() => disposeKept(root, kept)),
  }
}

export function buildSiliconCircuit(resolved: ResolvedAtmos, webgl2: boolean): { root: Group; handle: AtmosHandle } {
  if (!webgl2) {
    const flat = flatCircuit(resolved)
    const handle = idleHandle(flat.root, flat.kept)
    flat.root.userData.atmos = handle
    return { root: flat.root, handle }
  }
  const root = new Group()
  root.name = 'atmos-silicon-circuit'
  const kept = emptyKept()
  const chips = circuitChips(resolved.seed, resolved.grassBlades)
  const towers = circuitTowers(resolved.seed, Math.max(2, Math.round(resolved.grassBlades * 0.5)), chips)
  const bridges = circuitBridges(resolved.seed, Math.max(2, Math.round(resolved.grassBlades * 0.4)), chips, towers)
  addSky(root, resolved, kept)
  addBoard(root, resolved, kept)
  addBeam(root, resolved, kept)
  addChips(root, chips, kept)
  addPins(root, chips, kept)
  addDots(root, chips, kept, resolved.palette)
  addTowers(root, towers, kept)
  addBridges(root, bridges, kept)
  addFins(root, heatsinkFins(), kept)
  addLeds(root, chips, kept, resolved.palette)
  addMotes(root, resolved, kept)
  addPad(root, kept)
  const handle = liveHandle(root, kept, resolved)
  root.userData.atmos = handle
  return { root, handle }
}

export const siliconCircuitSet: AtmosSetDefinition = {
  id: 'atmos-silicon-circuit',
  titleKey: 'template.atmos-silicon-circuit-wide.title',
  setting: 'circuit',
  seed: 88022,
  subject: CLEARING_SUBJECT,
  subjectYaw: 0.15,
  palettes: CIRCUIT_PALETTES,
  times: CIRCUIT_TIMES,
  defaults: { timeOfDay: 'idle', fogDensity: 0.22, wind: 0.05, motes: 0.4, palette: 'phosphor', variant: 4 },
  variant: { labelKey: 'atmos.active', min: 0, max: 8 },
  low: { shaftSteps: 0, grassBlades: 8, moteCount: 16 },
  high: { shaftSteps: 0, grassBlades: 14, moteCount: 32 },
  templates: [
    { id: 'atmos-silicon-circuit-wide', camera: 'establishment', eye: WIDE_EYE, look: WIDE_LOOK, fov: 50, duration: 6 },
    { id: 'atmos-silicon-circuit-low', camera: 'establishment', eye: LOW_EYE, look: LOW_LOOK, fov: 62, duration: 6 },
  ],
  build: buildSiliconCircuit,
  fallback(resolved) {
    const sky = CIRCUIT_PALETTES[resolved.palette as keyof typeof CIRCUIT_PALETTES]?.fog ?? CIRCUIT_PALETTES.phosphor.fog
    return { sky: hexColor(sky), ground: hexColor(FALLBACK_GROUND[resolved.palette] ?? FALLBACK_GROUND.phosphor) }
  },
}
