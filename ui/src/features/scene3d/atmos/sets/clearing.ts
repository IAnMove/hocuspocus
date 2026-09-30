import {
  BackSide,
  BufferGeometry,
  DoubleSide,
  Color,
  CylinderGeometry,
  Float32BufferAttribute,
  FogExp2,
  Group,
  InstancedBufferAttribute,
  InstancedMesh,
  Mesh,
  MeshBasicMaterial,
  MeshStandardMaterial,
  Object3D,
  PlaneGeometry,
  Points,
  ShaderMaterial,
  SphereGeometry,
  SpotLight,
  Texture,
  Vector2,
  Vector3,
  type BufferAttribute,
  type Camera,
  type DirectionalLight,
} from 'three'
import type { Pass } from 'three/addons/postprocessing/Pass.js'
import { hash2 } from '../noise.ts'
import { fbm2 } from '../noise.ts'
import { windAt } from '../wind.ts'
import { clearingTrunks, CLEARING_SUBJECT, CLEARING_EYE, CLEARING_LOOK, BACKLIGHT_EYE, BACKLIGHT_LOOK } from '../layout.ts'
import { barkTexture, floorTexture, leafCookie, leafSprite } from '../textures.ts'
import { addCanopies, addTrunks, addUnderstory, type Kept } from '../forest.ts'
import { bindShaftLight, createDofPass, createGradePass, createShaftPass, projectSun } from '../passes.ts'
import type { AtmosSetDefinition } from '../definition.ts'
import type { AtmosQuality, AtmosSettings, ResolvedAtmos } from '../params.ts'

export type AtmosHandle = {
  sync: (seconds: number, camera: Camera, light: DirectionalLight, quality: AtmosQuality, focus: number, live?: AtmosSettings) => void
  passes: () => Pass[]
  dispose: () => void
  ms: { shafts: number; dof: number; grade: number }
}

const GRASS = {
  vertex: `
    attribute float aPhase;
    uniform float uTime;
    uniform float uBend;
    uniform vec3 uCam;
    varying vec2 vUv;
    varying float vDist;
    varying float vTint;
    varying vec3 vWorld;
    void main() {
      vUv = uv;
      vTint = fract(aPhase * 3.71);
      vec3 transformed = position;
      float h = uv.y;
      transformed.x *= 1.0 - h * 0.92;
      float sway = sin(uTime * 1.7 + aPhase) * uBend;
      transformed.x += sway * h * h;
      transformed.z += cos(uTime * 1.15 + aPhase) * uBend * 0.45 * h * h;
      vec4 world = instanceMatrix * vec4(transformed, 1.0);
      vWorld = world.xyz;
      vDist = distance(world.xyz, uCam);
      #include <project_vertex>
    }
  `,
  fragment: `
    uniform vec3 uBase;
    uniform vec3 uTip;
    uniform vec2 uCookie;
    varying vec2 vUv;
    varying float vDist;
    varying float vTint;
    varying vec3 vWorld;
    float hash(vec2 p) {
      return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
    }
    void main() {
      float cell = hash(floor((vWorld.xz + uCookie) * 1.7));
      float dapple = smoothstep(0.38, 0.62, cell);
      vec3 color = mix(uBase, uTip, pow(vUv.y, 0.8));
      color *= mix(0.78, 1.22, vTint);
      color = mix(color, color * vec3(1.22, 1.08, 0.62), smoothstep(0.82, 1.0, vTint) * 0.65);
      color *= mix(0.5, 1.15, dapple);
      color = mix(color, vec3(0.78, 0.86, 0.7), smoothstep(16.0, 34.0, vDist));
      gl_FragColor = vec4(color, 1.0);
    }
  `,
}

function keepTexture(kept: Kept, texture: Texture | null): Texture | null {
  if (texture) kept.textures.push(texture)
  return texture
}

function addGround(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const geo = new PlaneGeometry(48, 48, 96, 96)
  geo.rotateX(-Math.PI / 2)
  const pos = geo.attributes.position as BufferAttribute
  const colors: number[] = []
  for (let i = 0; i < pos.count; i += 1) {
    const x = pos.getX(i)
    const z = pos.getZ(i)
    pos.setY(i, fbm2(x * 0.16, z * 0.16, resolved.seed) * 0.22 - 0.05)
    const tint = 0.78 + fbm2(x * 0.07 + 9, z * 0.07, resolved.seed + 4) * 0.5
    colors.push(tint, tint * 0.98, tint * 0.9)
  }
  geo.setAttribute('color', new Float32BufferAttribute(colors, 3))
  geo.computeVertexNormals()
  const albedo = keepTexture(kept, floorTexture(resolved.grass, resolved.stone, resolved.seed))
  const mat = new MeshStandardMaterial({ map: albedo ?? null, vertexColors: true, color: albedo ? 0xffffff : resolved.stone, roughness: 0.95 })
  const mesh = new Mesh(geo, mat)
  mesh.name = 'atmos-ground'
  mesh.receiveShadow = true
  root.add(mesh)
  kept.geometries.push(geo)
  kept.materials.push(mat)
}

/** Grass is trimmed around the character so knees and feet stay in view, and grows to full height by 2.8 m out. */
export function lawn(x: number, z: number): number {
  const distance = Math.hypot(x - CLEARING_SUBJECT[0], z - CLEARING_SUBJECT[2])
  const t = Math.min(1, Math.max(0, (distance - 1) / 1.8))
  return 0.36 + 0.64 * t * t * (3 - 2 * t)
}

/** Blades grow in tufts of 18, denser near the camera, and step out of the subject's spot. */
function seatBlade(i: number, seed: number): [number, number] {
  const tuft = Math.floor(i / 18)
  const cx = (hash2(tuft, 1, seed) - 0.5) * 24
  const cz = 4.6 - hash2(tuft, 2, seed) ** 1.5 * 20
  const angle = hash2(i, 3, seed) * Math.PI * 2
  const radius = Math.sqrt(hash2(i, 4, seed)) * 0.42
  const x = cx + Math.cos(angle) * radius
  let z = cz + Math.sin(angle) * radius
  const dx = x - CLEARING_SUBJECT[0]
  const dz = z - CLEARING_SUBJECT[2]
  if (dx * dx + dz * dz < 0.85 * 0.85) z -= 2.4
  return [x, z]
}

function addGrass(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const geo = new PlaneGeometry(0.05, 0.3, 1, 3)
  geo.translate(0, 0.15, 0)
  const phases = new Float32Array(resolved.grassBlades)
  const mat = new ShaderMaterial({
    uniforms: {
      uTime: { value: 0 },
      uBend: { value: 0.25 + resolved.wind * 0.45 },
      uCam: { value: new Vector3() },
      uBase: { value: new Color(resolved.grass).multiplyScalar(0.36) },
      uTip: { value: new Color(resolved.grass).multiplyScalar(0.82) },
      uCookie: { value: new Vector2() },
    },
    vertexShader: GRASS.vertex,
    fragmentShader: GRASS.fragment,
  })
  const mesh = new InstancedMesh(geo, mat, resolved.grassBlades)
  mesh.name = 'atmos-grass'
  mesh.castShadow = false
  mesh.receiveShadow = false
  const dummy = new Object3D()
  for (let i = 0; i < resolved.grassBlades; i += 1) {
    const [x, z] = seatBlade(i, resolved.seed)
    dummy.position.set(x, 0, z)
    dummy.rotation.y = hash2(i, 3, resolved.seed) * Math.PI * 2
    dummy.scale.setScalar((0.7 + hash2(i, 5, resolved.seed) * 0.9) * lawn(x, z))
    dummy.updateMatrix()
    mesh.setMatrixAt(i, dummy.matrix)
    phases[i] = hash2(i, 6, resolved.seed) * Math.PI * 2
  }
  mesh.geometry.setAttribute('aPhase', new InstancedBufferAttribute(phases, 1))
  mesh.instanceMatrix.needsUpdate = true
  root.add(mesh)
  kept.geometries.push(geo)
  kept.materials.push(mat)
  return mat
}

function addMotes(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const geo = new BufferGeometry()
  const positions = new Float32Array(resolved.moteCount * 3)
  for (let i = 0; i < resolved.moteCount; i += 1) {
    positions[i * 3] = (hash2(i, 6, resolved.seed) - 0.5) * 10
    positions[i * 3 + 1] = 0.2 + hash2(i, 7, resolved.seed) * 3.2
    positions[i * 3 + 2] = 2 - hash2(i, 8, resolved.seed) * 14
  }
  geo.setAttribute('position', new Float32BufferAttribute(positions, 3))
  const mat = new ShaderMaterial({
    transparent: true,
    depthWrite: false,
    uniforms: { uSize: { value: 5 + resolved.motes * 8 }, uColor: { value: new Color('#fff6d8') } },
    vertexShader: `
      uniform float uSize;
      void main() {
        vec4 mv = modelViewMatrix * vec4(position, 1.0);
        gl_PointSize = uSize * (1.4 / max(0.3, -mv.z));
        gl_Position = projectionMatrix * mv;
      }
    `,
    fragmentShader: `
      uniform vec3 uColor;
      void main() {
        float d = length(gl_PointCoord - 0.5);
        if (d > 0.5) discard;
        gl_FragColor = vec4(uColor, (1.0 - d * 2.0) * 0.85);
      }
    `,
  })
  const points = new Points(geo, mat)
  points.name = 'atmos-mote'
  root.add(points)
  kept.geometries.push(geo)
  kept.materials.push(mat)
  return positions
}

function addSky(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const geo = new SphereGeometry(70, 24, 16)
  const mat = new ShaderMaterial({
    side: BackSide,
    depthWrite: false,
    uniforms: {
      uTop: { value: new Color(resolved.fogColor).multiplyScalar(1.15) },
      uHorizon: { value: new Color(resolved.fogColor) },
      uSun: { value: new Color(resolved.sunColor) },
      uRay: { value: new Vector3(...resolved.sun) },
    },
    vertexShader: `
      varying vec3 vDir;
      void main() {
        vDir = position;
        gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
      }
    `,
    fragmentShader: `
      uniform vec3 uTop;
      uniform vec3 uHorizon;
      uniform vec3 uSun;
      uniform vec3 uRay;
      varying vec3 vDir;
      void main() {
        vec3 dir = normalize(vDir);
        vec3 sky = mix(uHorizon, uTop, smoothstep(-0.05, 0.45, dir.y));
        float sun = pow(max(0.0, dot(dir, -normalize(uRay))), 180.0);
        float halo = pow(max(0.0, dot(dir, -normalize(uRay))), 12.0);
        gl_FragColor = vec4(sky + uSun * sun * 0.45 + uSun * halo * 0.08, 1.0);
      }
    `,
  })
  const mesh = new Mesh(geo, mat)
  mesh.name = 'atmos-sky'
  mesh.renderOrder = -2
  mesh.frustumCulled = false
  root.add(mesh)
  kept.geometries.push(geo)
  kept.materials.push(mat)
  return mat
}

function addLitter(root: Group, kept: Kept) {
  const geo = new PlaneGeometry(0.18, 0.08)
  const mat = new MeshStandardMaterial({ color: 0xb85a28, roughness: 0.85, side: DoubleSide })
  kept.geometries.push(geo)
  kept.materials.push(mat)
  for (let i = 0; i < 7; i += 1) {
    const mesh = new Mesh(geo, mat)
    mesh.position.set(-1.1 + hash2(i, 2, 9) * 3.1, 0.025, 0.6 - hash2(i, 4, 9) * 3.4)
    mesh.rotation.set(-Math.PI / 2, 0, hash2(i, 6, 9) * 6)
    mesh.receiveShadow = true
    root.add(mesh)
  }
}

function addFallingLeaf(root: Group, kept: Kept) {
  const geo = new PlaneGeometry(0.14, 0.06)
  const mat = new MeshBasicMaterial({ color: 0xc46a32, side: DoubleSide })
  const mesh = new Mesh(geo, mat)
  mesh.name = 'atmos-fall'
  root.add(mesh)
  kept.geometries.push(geo)
  kept.materials.push(mat)
}

function addProps(root: Group, kept: Kept, figure: boolean) {
  addLitter(root, kept)
  addFallingLeaf(root, kept)
  if (!figure) return
  const bodyGeo = new CylinderGeometry(0.22, 0.26, 1.15, 10)
  const bodyMat = new MeshStandardMaterial({ color: 0xc4b59a, roughness: 0.7 })
  const body = new Mesh(bodyGeo, bodyMat)
  body.position.set(CLEARING_SUBJECT[0], 0.85, CLEARING_SUBJECT[2])
  body.castShadow = true
  body.receiveShadow = true
  body.name = 'atmos-figure'
  root.add(body)
  kept.geometries.push(bodyGeo)
  kept.materials.push(bodyMat)
}

function flatClearing(resolved: ResolvedAtmos): { root: Group; kept: Kept } {
  const root = new Group()
  const kept: Kept = { geometries: [], materials: [], textures: [], lights: [] }
  const geo = new PlaneGeometry(16, 16)
  geo.rotateX(-Math.PI / 2)
  const mat = new MeshStandardMaterial({ color: resolved.stone })
  root.add(new Mesh(geo, mat))
  kept.geometries.push(geo)
  kept.materials.push(mat)
  return { root, kept }
}

export function buildClearing(resolved: ResolvedAtmos, webgl2: boolean): { root: Group; handle: AtmosHandle } {
  const kept: Kept = { geometries: [], materials: [], textures: [], lights: [] }
  if (!webgl2) {
    const flat = flatClearing(resolved)
    flat.root.name = 'atmos-clearing'
    const handle = simpleHandle(flat.root, flat.kept)
    flat.root.userData.atmos = handle
    return { root: flat.root, handle }
  }
  const root = new Group()
  root.name = 'atmos-clearing'
  addGround(root, resolved, kept)
  const trunks = clearingTrunks(resolved.seed)
  const bark = keepTexture(kept, barkTexture(resolved.seed))
  addTrunks(root, trunks, bark, resolved.seed, kept)
  addCanopies(root, trunks, resolved, kept)
  addUnderstory(root, trunks, resolved, bark, kept)
  const grass = addGrass(root, resolved, kept)
  const motes = addMotes(root, resolved, kept)
  const sky = addSky(root, resolved, kept)
  addProps(root, kept, resolved.previewFigure === true)
  const cookie = keepTexture(kept, leafCookie(resolved.seed))
  const spot = new SpotLight(resolved.sunColor, 2.4, 46, 1.05, 0.85, 1)
  spot.map = cookie
  spot.castShadow = false
  spot.target.position.set(CLEARING_SUBJECT[0], 0.2, CLEARING_SUBJECT[2])
  root.add(spot)
  root.add(spot.target)
  kept.lights.push(spot)
  const sprite = keepTexture(kept, leafSprite(resolved.grass))
  const leaves = addForeground(root, sprite, kept)
  const shafts = createShaftPass()
  const dof = createDofPass()
  const grade = createGradePass()
  dof.enabled = resolved.dof
  const handle = liveHandle({ root, kept, grass, motes, sky, spot, leaves, shafts, dof, grade, resolved })
  root.userData.atmos = handle
  return { root, handle }
}

function addForeground(root: Group, sprite: Texture | null, kept: Kept): Mesh[] {
  const mat = new MeshBasicMaterial({ map: sprite ?? null, color: sprite ? 0xffffff : 0x8fce58, transparent: true, opacity: 0.9, depthWrite: false })
  kept.materials.push(mat)
  const leaves: Mesh[] = []
  for (const [x, y, z, scale] of [[0.92, -0.02, -0.36, 1.8], [1.08, 0.24, -0.46, 1.4], [0.74, -0.26, -0.32, 1.25], [-1.02, 0.1, -0.44, 1.05]]) {
    const geo = new PlaneGeometry(0.42, 0.2)
    const mesh = new Mesh(geo, mat)
    mesh.name = 'atmos-leaf'
    mesh.userData.local = new Vector3(x, y, z)
    mesh.scale.setScalar(scale)
    mesh.renderOrder = 2
    root.add(mesh)
    kept.geometries.push(geo)
    leaves.push(mesh)
  }
  return leaves
}

function simpleHandle(root: Group, kept: Kept): AtmosHandle {
  const dispose = disposeOnce(() => disposeKept(root, kept))
  return {
    ms: { shafts: 0, dof: 0, grade: 0 },
    passes: () => [],
    sync: () => {},
    dispose,
  }
}

function liveHandle(parts: {
  root: Group
  kept: Kept
  grass: ShaderMaterial
  motes: Float32Array
  sky: ShaderMaterial
  spot: SpotLight
  leaves: Mesh[]
  shafts: ReturnType<typeof createShaftPass>
  dof: ReturnType<typeof createDofPass>
  grade: ReturnType<typeof createGradePass>
  resolved: ResolvedAtmos
}): AtmosHandle {
  const base = parts.motes.slice()
  return {
    ms: { shafts: 0, dof: 0, grade: 0 },
    passes: () => [parts.shafts, parts.dof, parts.grade],
    sync: (seconds, camera, light, quality, focus, live) => syncLive(parts, base, seconds, camera, light, quality, focus, live),
    dispose: disposeOnce(() => {
      parts.shafts.dispose()
      parts.dof.dispose()
      parts.grade.dispose()
      disposeKept(parts.root, parts.kept)
    }),
  }
}

function disposeOnce(run: () => void) {
  let done = false
  return () => {
    if (done) return
    done = true
    run()
  }
}

function syncLive(
  parts: {
    root: Group
    grass: ShaderMaterial
    motes: Float32Array
    sky: ShaderMaterial
    spot: SpotLight
    leaves: Mesh[]
    shafts: ReturnType<typeof createShaftPass>
    dof: ReturnType<typeof createDofPass>
    grade: ReturnType<typeof createGradePass>
    resolved: ResolvedAtmos
  },
  base: Float32Array,
  seconds: number,
  camera: Camera,
  light: DirectionalLight,
  quality: AtmosQuality,
  focus: number,
  live?: AtmosSettings,
) {
  const look = liveLook(parts.resolved, live)
  const wind = windAt(0, 0, seconds, 0.35 + look.wind, look.wind, look.seed)
  parts.grass.uniforms.uTime.value = seconds
  parts.grass.uniforms.uBend.value = 0.2 + wind.bend
  parts.grass.uniforms.uCam.value.copy(camera.position)
  parts.grass.uniforms.uCookie.value.set(seconds * 0.05, wind.x)
  moveMotes(parts.root, base, look, seconds)
  parts.spot.position.copy(light.position)
  parts.spot.color.copy(light.color)
  if (parts.spot.map) parts.spot.map.offset.set(seconds * (0.012 + look.wind * 0.02), seconds * 0.007)
  followLeaves(parts.leaves, camera)
  moveFall(parts.root, seconds)
  const fog = (parts.root.parent as { fog?: unknown } | null)?.fog
  if (fog instanceof FogExp2) fog.density = 0.014 + look.fogDensity * 0.034
  const uniforms = parts.shafts.uniforms
  const ray = light.position.clone().multiplyScalar(-1).normalize()
  projectSun(camera, ray, uniforms.uSunUv.value)
  bindShaftLight(parts.shafts, light, quality === 'high')
  uniforms.uSteps.value = quality === 'high' ? look.shaftSteps : 8
  uniforms.uStrength.value = 0.5 + look.fogDensity * 0.2
  uniforms.uFogDensity.value = 0.05 + look.fogDensity * 0.12
  uniforms.uFogColor.value.set(look.fogColor)
  uniforms.uProjectionInverse.value.copy(camera.projectionMatrixInverse)
  uniforms.uViewInverse.value.copy(camera.matrixWorld)
  parts.dof.enabled = false
  parts.dof.uniforms.uFocus.value = focus
  const lens = camera as Camera & { near?: number; far?: number }
  if (typeof lens.near === 'number' && typeof lens.far === 'number') {
    parts.dof.uniforms.uNear.value = lens.near
    parts.dof.uniforms.uFar.value = lens.far
    parts.shafts.uniforms.uNear.value = lens.near
    parts.shafts.uniforms.uFar.value = lens.far
  }
  parts.grade.uniforms.uFrame.value = Math.floor(seconds * 24)
  parts.grade.uniforms.uTemperature.value = look.palette === 'blue' ? -0.05 : 0.2
  parts.sky.uniforms.uRay.value.copy(ray)
}

function liveLook(resolved: ResolvedAtmos, live?: AtmosSettings): ResolvedAtmos {
  if (!live) return resolved
  return { ...resolved, fogDensity: live.fogDensity, wind: live.wind, motes: live.motes, palette: live.palette }
}

function moveMotes(root: Group, base: Float32Array, look: ResolvedAtmos, seconds: number) {
  const pos = root.getObjectByName('atmos-mote')
  const attr = (pos as Points | undefined)?.geometry.getAttribute('position') as BufferAttribute | undefined
  if (!attr) return
  const speed = 0.05 + look.motes * 0.08
  for (let i = 0; i < look.moteCount; i += 1) {
    const y = (base[i * 3 + 1] + seconds * speed) % 3.4
    attr.setXYZ(i, base[i * 3] + Math.sin(seconds * 0.35 + i) * 0.15, y, base[i * 3 + 2])
  }
  attr.needsUpdate = true
}

function followLeaves(leaves: Mesh[], camera: Camera) {
  for (const leaf of leaves) {
    const local = leaf.userData.local as Vector3
    leaf.position.copy(local).applyMatrix4(camera.matrixWorld)
    leaf.quaternion.copy(camera.quaternion)
  }
}

function moveFall(root: Group, seconds: number) {
  const fall = root.getObjectByName('atmos-fall')
  if (!fall) return
  const t = (seconds * 0.17) % 1
  fall.position.set(0.35 + Math.sin(seconds * 0.8) * 0.25, 3.4 * (1 - t) + 0.2, -1.8)
  fall.rotation.z = seconds * 1.4
}

function disposeKept(root: Group, kept: Kept) {
  root.removeFromParent()
  for (const geometry of kept.geometries) geometry.dispose()
  for (const material of kept.materials) material.dispose()
  for (const texture of kept.textures) texture.dispose()
  for (const light of kept.lights) light.dispose()
  kept.geometries.length = 0
}

const CLEARING_PALETTES = {
  green: { fog: '#d5e6c6', ground: '#b7bba6', accent: '#7cbc46', sky: ['#d5e6c6', '#e7f0dc'] },
  autumn: { fog: '#ead4b2', ground: '#c6b49c', accent: '#c4a04a', sky: ['#ead4b2', '#f0e2c8'] },
  blue: { fog: '#d4e4f0', ground: '#b7c2c8', accent: '#6aadc4', sky: ['#d4e4f0', '#e4eef6'] },
} as const

const CLEARING_TIMES = {
  dawn: { sun: [0.7, -0.28, 0.22], sunColor: '#ffb4c0' },
  morning: { sun: [0.4, -0.82, 0.16], sunColor: '#fff4dc' },
  golden: { sun: [0.82, -0.55, 0.16], sunColor: '#ffd39a' },
} as const

const FALLBACK_GROUND: Record<string, string> = {
  green: '#6d7d58',
  autumn: '#8a7a58',
  blue: '#7d8c86',
}

function hexColor(color: string): [number, number, number] {
  const n = Number.parseInt(color.slice(1), 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

export const clearingSet: AtmosSetDefinition = {
  id: 'atmos-clearing',
  titleKey: 'template.atmos-clearing-wide.title',
  setting: 'forest',
  seed: 17041,
  subject: CLEARING_SUBJECT,
  subjectYaw: 0.15,
  palettes: CLEARING_PALETTES,
  times: CLEARING_TIMES,
  defaults: { timeOfDay: 'golden', fogDensity: 0.58, wind: 0.46, motes: 0.72, palette: 'green' },
  low: { shaftSteps: 8, grassBlades: 12000, moteCount: 220 },
  high: { shaftSteps: 24, grassBlades: 60000, moteCount: 700 },
  templates: [
    { id: 'atmos-clearing-wide', camera: 'establishment', eye: CLEARING_EYE, look: CLEARING_LOOK, fov: 42, duration: 10 },
    { id: 'atmos-clearing-backlight', camera: 'establishment', eye: BACKLIGHT_EYE, look: BACKLIGHT_LOOK, fov: 40, duration: 10 },
  ],
  build: buildClearing,
  fallback(resolved) {
    const sky = CLEARING_PALETTES[resolved.palette as keyof typeof CLEARING_PALETTES]?.fog ?? CLEARING_PALETTES.green.fog
    return { sky: hexColor(sky), ground: hexColor(FALLBACK_GROUND[resolved.palette] ?? FALLBACK_GROUND.green) }
  },
}
