import {
  BackSide,
  BoxGeometry,
  BufferGeometry,
  Color,
  ConeGeometry,
  CylinderGeometry,
  DoubleSide,
  Float32BufferAttribute,
  FogExp2,
  Group,
  InstancedMesh,
  Mesh,
  MeshBasicMaterial,
  Object3D,
  PlaneGeometry,
  Points,
  ShaderMaterial,
  SphereGeometry,
  type BufferAttribute,
  type Material,
} from 'three'
import type { AtmosHandle } from './clearing.ts'
import type { AtmosSetDefinition } from '../definition.ts'
import type { AtmosSettings, ResolvedAtmos } from '../params.ts'
import { hash2 } from '../noise.ts'
import { CLEARING_SUBJECT, scatter, type Area } from '../layout.ts'
import { backdropRidge } from './kit.ts'

type Kept = { geometries: BufferGeometry[]; materials: Material[] }

const FLAKE_VERTEX = `
  attribute float aSeed;
  uniform float uTime;
  uniform float uSpeed;
  uniform float uSpan;
  uniform float uSize;
  void main() {
    vec3 p = position;
    p.y -= mod(uTime * uSpeed + aSeed * uSpan, uSpan);
    p.x += sin(uTime * 0.45 + aSeed * 6.28318) * 0.12;
    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    gl_PointSize = uSize;
    gl_Position = projectionMatrix * mv;
  }
`
const FLAKE_FRAGMENT = `
  uniform vec3 uColor;
  uniform float uAlpha;
  void main() {
    vec2 uv = gl_PointCoord * 2.0 - 1.0;
    float falloff = 1.0 - dot(uv, uv);
    if (falloff <= 0.0) discard;
    gl_FragColor = vec4(uColor, uAlpha * falloff);
  }
`
const AURORA_VERTEX = `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`
const AURORA_FRAGMENT = `
  uniform float uTime;
  varying vec2 vUv;
  void main() {
    float wave = sin(vUv.x * 6.0 + uTime * 0.55) * 0.08;
    float edge = smoothstep(0.0, 0.22, vUv.x) * smoothstep(1.0, 0.78, vUv.x);
    float green = smoothstep(0.18, 0.36, vUv.y + wave) * smoothstep(0.58, 0.4, vUv.y + wave);
    float violet = smoothstep(0.48, 0.64, vUv.y - wave) * smoothstep(0.9, 0.72, vUv.y - wave);
    vec3 color = mix(vec3(0.45, 0.93, 0.62), vec3(0.67, 0.52, 0.96), violet);
    gl_FragColor = vec4(color, max(green, violet * 0.9) * edge);
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

const LEFT_FIELD: Area = { x0: -6.4, x1: -1.85, z0: -6.2, z1: 1.2 }
const RIGHT_FIELD: Area = { x0: 2.2, x1: 6.4, z0: -6.2, z1: 1.2 }
const CABIN = { x: 5.4, z: -8.4 }
const SPRUCE: Record<string, string> = { frost: '#1e4036', twilight: '#163028' }
const WOOD: Record<string, string> = { frost: '#5c3a2e', twilight: '#3e291f' }
const SNOWCAP: Record<string, string> = { frost: '#f7fbff', twilight: '#e7eef6' }
const FALLBACK_GROUND: Record<string, string> = { frost: '#e4eaf2', twilight: '#c5d0de' }

const SNOW_PALETTES = {
  frost: { fog: '#d4e2f0', ground: '#f4f7fb', accent: '#1e4036', sky: ['#d4e2f0', '#eef6ff'] },
  twilight: { fog: '#5d7394', ground: '#d5deea', accent: '#163028', sky: ['#5d7394', '#1a2748'] },
} as const

const SNOW_TIMES = {
  day: { sun: [0.18, -0.7, -0.52], sunColor: '#f4f8ff' },
  blue: { sun: [-0.42, -0.22, -0.78], sunColor: '#9eb6e8' },
} as const

const WIDE_EYE = [0.12, 1.55, 4.15] as const
const WIDE_LOOK = [0.35, 2.5, -9.2] as const
const LOW_EYE = [1.15, 0.42, 2.05] as const
const LOW_LOOK = [-0.55, 2.7, -8.8] as const

function emptyKept(): Kept {
  return { geometries: [], materials: [] }
}

function hexColor(color: string): [number, number, number] {
  const n = Number.parseInt(color.slice(1), 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

function swatch(table: Record<string, string>, palette: string): string {
  return table[palette] ?? table.frost
}

function flakeCount(variant: number | undefined): number {
  const value = typeof variant === 'number' && Number.isFinite(variant) ? variant : 36
  return Math.round(Math.min(80, Math.max(0, value)))
}

function zenithColor(time: string): string {
  return time === 'blue' ? '#1a2748' : '#eef6ff'
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

function addMesh(root: Group, kept: Kept, mesh: Mesh | InstancedMesh | Points) {
  root.add(mesh)
  kept.geometries.push(mesh.geometry)
}

function flatSnow(resolved: ResolvedAtmos): { root: Group; kept: Kept } {
  const root = new Group()
  root.name = 'atmos-snow'
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
  const geo = new PlaneGeometry(32, 32, 16, 16)
  geo.rotateX(-Math.PI / 2)
  const pos = geo.attributes.position as BufferAttribute
  for (let i = 0; i < pos.count; i += 1) {
    const x = pos.getX(i)
    const z = pos.getZ(i)
    const dx = x - CLEARING_SUBJECT[0]
    const dz = z - CLEARING_SUBJECT[2]
    if (dx * dx + dz * dz < 2.2) continue
    pos.setY(i, (hash2(Math.round(x * 3), Math.round(z * 3), resolved.seed) - 0.5) * 0.16)
  }
  geo.computeVertexNormals()
  const mat = new MeshBasicMaterial({ color: resolved.stone })
  const mesh = new Mesh(geo, mat)
  mesh.name = 'atmos-ground'
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function fieldSpots(count: number, seed: number, salt: number): Array<[number, number]> {
  const half = Math.ceil(count / 2)
  const back: Array<[number, number]> = [[-7, -12.4], [-3.4, -12.2], [0.2, -12.6], [3.6, -12.3], [7.1, -12.5]]
  return [
    ...scatter(half, seed, salt, [], LEFT_FIELD, 0.85),
    ...scatter(count - half, seed, salt + 5, [], RIGHT_FIELD, 0.85),
    ...back,
  ]
}

function placeColumn(mesh: InstancedMesh, spots: Array<[number, number]>, seed: number, base: number, height: number, radius: number) {
  const dummy = new Object3D()
  spots.forEach(([x, z], index) => {
    const scale = 0.8 + hash2(index, 4, seed) * 0.55
    dummy.position.set(x, base * scale + height * scale * 0.5, z)
    dummy.rotation.set(0, 0, 0)
    dummy.scale.set(radius * scale, height * scale, radius * scale)
    dummy.updateMatrix()
    mesh.setMatrixAt(index, dummy.matrix)
  })
}

function addPines(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const spots = fieldSpots(resolved.grassBlades, resolved.seed, 17)
  if (spots.length < 1) return
  const trunkGeo = new CylinderGeometry(1, 1, 1, 5)
  const canopyGeo = new ConeGeometry(1, 1, 5)
  const capGeo = new ConeGeometry(1, 1, 5)
  const trunkMat = new MeshBasicMaterial({ color: swatch(WOOD, resolved.palette) })
  const canopyMat = new MeshBasicMaterial({ color: swatch(SPRUCE, resolved.palette) })
  const capMat = new MeshBasicMaterial({ color: swatch(SNOWCAP, resolved.palette) })
  const trunks = new InstancedMesh(trunkGeo, trunkMat, spots.length)
  const pines = new InstancedMesh(canopyGeo, canopyMat, spots.length)
  const caps = new InstancedMesh(capGeo, capMat, spots.length)
  trunks.name = 'atmos-trunk'
  pines.name = 'atmos-pine'
  caps.name = 'atmos-cap'
  placeColumn(trunks, spots, resolved.seed, 0, 0.7, 0.16)
  placeColumn(pines, spots, resolved.seed, 0.55, 2.1, 0.9)
  placeColumn(caps, spots, resolved.seed, 2.35, 0.45, 0.38)
  addMesh(root, kept, trunks)
  addMesh(root, kept, pines)
  addMesh(root, kept, caps)
  kept.materials.push(trunkMat, canopyMat, capMat)
}

function printSpots(): Array<[number, number]> {
  const spots: Array<[number, number]> = []
  for (let i = 0; i < 10; i += 1) {
    const t = i / 9
    const side = i % 2 === 0 ? 0.16 : -0.16
    spots.push([-2.35 - t * 0.4 + side, 0.95 - t * 5.1])
  }
  return spots
}

function addPrints(root: Group, kept: Kept) {
  const spots = printSpots()
  const geo = new PlaneGeometry(0.22, 0.42)
  geo.rotateX(-Math.PI / 2)
  const mat = new MeshBasicMaterial({ color: '#7f93a8', transparent: true, opacity: 0.92 })
  const mesh = new InstancedMesh(geo, mat, spots.length)
  mesh.name = 'atmos-print'
  const dummy = new Object3D()
  spots.forEach(([x, z], index) => {
    dummy.position.set(x, 0.03, z)
    dummy.rotation.set(0, 0, 0)
    dummy.updateMatrix()
    mesh.setMatrixAt(index, dummy.matrix)
  })
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function addCabin(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const wood = swatch(WOOD, resolved.palette)
  const bodyGeo = new BoxGeometry(2.1, 1.45, 1.6)
  const bodyMat = new MeshBasicMaterial({ color: wood })
  const body = new Mesh(bodyGeo, bodyMat)
  body.name = 'atmos-cabin'
  body.position.set(CABIN.x, 0.78, CABIN.z)
  const roofGeo = new ConeGeometry(1.55, 0.85, 4)
  const roofMat = new MeshBasicMaterial({ color: swatch(SNOWCAP, resolved.palette) })
  const roof = new Mesh(roofGeo, roofMat)
  roof.position.set(CABIN.x, 1.85, CABIN.z)
  const winGeo = new BoxGeometry(0.48, 0.36, 0.08)
  const winMat = new MeshBasicMaterial({ color: '#ffc27a' })
  const win = new Mesh(winGeo, winMat)
  win.name = 'atmos-window'
  win.position.set(CABIN.x, 0.86, CABIN.z + 0.82)
  addMesh(root, kept, body)
  addMesh(root, kept, roof)
  addMesh(root, kept, win)
  kept.materials.push(bodyMat, roofMat, winMat)
}

function addAurora(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  if (resolved.timeOfDay !== 'blue') return
  const geo = new PlaneGeometry(22, 5.4)
  const mat = new ShaderMaterial({
    uniforms: { uTime: { value: 0 } },
    vertexShader: AURORA_VERTEX,
    fragmentShader: AURORA_FRAGMENT,
    transparent: true,
    depthWrite: false,
    side: DoubleSide,
  })
  const mesh = new Mesh(geo, mat)
  mesh.name = 'atmos-aurora'
  mesh.position.set(-0.2, 7.1, -14.2)
  mesh.frustumCulled = false
  addMesh(root, kept, mesh)
  kept.materials.push(mat)
}

function flakeGeometry(count: number, seed: number, salt: number, y0: number, span: number): BufferGeometry {
  const geo = new BufferGeometry()
  const pos = new Float32Array(count * 3)
  const seeds = new Float32Array(count)
  for (let i = 0; i < count; i += 1) {
    pos[i * 3] = -7 + hash2(i, salt, seed) * 14
    pos[i * 3 + 1] = y0 + hash2(i, salt + 1, seed) * span
    pos[i * 3 + 2] = -8 + hash2(i, salt + 2, seed) * 10
    seeds[i] = hash2(i, salt + 3, seed)
  }
  geo.setAttribute('position', new Float32BufferAttribute(pos, 3))
  geo.setAttribute('aSeed', new Float32BufferAttribute(seeds, 1))
  return geo
}

function addFlakeLayer(root: Group, kept: Kept, name: string, count: number, seed: number, salt: number, y0: number, span: number, speed: number, size: number, alpha: number) {
  const geo = flakeGeometry(count, seed, salt, y0, span)
  const mat = new ShaderMaterial({
    uniforms: {
      uTime: { value: 0 },
      uSpeed: { value: speed },
      uSpan: { value: span },
      uSize: { value: size },
      uColor: { value: new Color('#f7fbff') },
      uAlpha: { value: alpha },
    },
    vertexShader: FLAKE_VERTEX,
    fragmentShader: FLAKE_FRAGMENT,
    transparent: true,
    depthWrite: false,
  })
  const points = new Points(geo, mat)
  points.name = name
  points.frustumCulled = false
  addMesh(root, kept, points)
  kept.materials.push(mat)
}

function addFlakes(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const count = flakeCount(resolved.variant)
  if (count < 1) return
  addFlakeLayer(root, kept, 'atmos-near', count, resolved.seed, 23, 0.35, 2.8, 0.38, 14, 0.95)
  addFlakeLayer(root, kept, 'atmos-far', count * 2, resolved.seed, 31, 2.4, 5.4, 0.8, 5.5, 0.7)
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

function paintTime(root: Group, name: string, seconds: number) {
  const mesh = root.getObjectByName(name) as Points | Mesh | undefined
  const material = mesh?.material
  if (material instanceof ShaderMaterial) material.uniforms.uTime.value = seconds
}

function syncSnow(root: Group, seconds: number, resolved: ResolvedAtmos, live?: AtmosSettings) {
  paintTime(root, 'atmos-near', seconds)
  paintTime(root, 'atmos-far', seconds)
  paintTime(root, 'atmos-aurora', seconds)
  const fog = (root.parent as { fog?: unknown } | null)?.fog
  if (fog instanceof FogExp2) fog.density = 0.014 + (live ?? resolved).fogDensity * 0.034
}

function liveHandle(root: Group, kept: Kept, resolved: ResolvedAtmos): AtmosHandle {
  return {
    ms: { shafts: 0, dof: 0, grade: 0 },
    passes: () => [],
    sync: (seconds, _camera, _light, _quality, _focus, live) => syncSnow(root, seconds, resolved, live),
    dispose: disposeOnce(() => disposeKept(root, kept)),
  }
}

export function buildSnow(resolved: ResolvedAtmos, webgl2: boolean): { root: Group; handle: AtmosHandle } {
  if (!webgl2) {
    const flat = flatSnow(resolved)
    const handle = idleHandle(flat.root, flat.kept)
    flat.root.userData.atmos = handle
    return { root: flat.root, handle }
  }
  const root = new Group()
  root.name = 'atmos-snow'
  const kept = emptyKept()
  addGround(root, resolved, kept)
  addPines(root, resolved, kept)
  addPrints(root, kept)
  addCabin(root, resolved, kept)
  addAurora(root, resolved, kept)
  addFlakes(root, resolved, kept)
  backdropRidge(root, kept, resolved, { near: '#9db0c8', height: [3, 6.5], width: [5, 9], radius: 16 })
  addSky(root, resolved, kept)
  const handle = liveHandle(root, kept, resolved)
  root.userData.atmos = handle
  return { root, handle }
}

export const snowSet: AtmosSetDefinition = {
  id: 'atmos-snow',
  titleKey: 'template.atmos-snow-wide.title',
  setting: 'snow',
  seed: 55017,
  subject: CLEARING_SUBJECT,
  subjectYaw: 0.15,
  palettes: SNOW_PALETTES,
  times: SNOW_TIMES,
  defaults: { timeOfDay: 'blue', fogDensity: 0.08, wind: 0.35, motes: 0.8, palette: 'frost', variant: 36 },
  variant: { labelKey: 'atmos.flakes', min: 0, max: 80 },
  low: { shaftSteps: 0, grassBlades: 8, moteCount: 36 },
  high: { shaftSteps: 0, grassBlades: 14, moteCount: 72 },
  templates: [
    { id: 'atmos-snow-wide', camera: 'establishment', eye: WIDE_EYE, look: WIDE_LOOK, fov: 46, duration: 6 },
    { id: 'atmos-snow-low', camera: 'establishment', eye: LOW_EYE, look: LOW_LOOK, fov: 52, duration: 6 },
  ],
  build: buildSnow,
  fallback(resolved) {
    const sky = SNOW_PALETTES[resolved.palette as keyof typeof SNOW_PALETTES]?.fog ?? SNOW_PALETTES.frost.fog
    return { sky: hexColor(sky), ground: hexColor(FALLBACK_GROUND[resolved.palette] ?? FALLBACK_GROUND.frost) }
  },
}
