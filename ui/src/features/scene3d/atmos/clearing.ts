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
  IcosahedronGeometry,
  Material,
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
import { hash2 } from './noise.ts'
import { fbm2 } from './noise.ts'
import { windAt } from './wind.ts'
import { clearingTrunks, CLEARING_SUBJECT, type Trunk } from './layout.ts'
import { barkTexture, cobbleJoint, cobbleTextures, leafCookie, leafSprite } from './textures.ts'
import { bindShaftLight, createDofPass, createGradePass, createShaftPass, projectSun } from './passes.ts'
import type { AtmosQuality, AtmosSettings, ResolvedAtmos } from './params.ts'

type Kept = { geometries: BufferGeometry[]; materials: Material[]; textures: Texture[]; lights: SpotLight[] }

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
    varying vec3 vWorld;
    void main() {
      vUv = uv;
      vec3 transformed = position;
      float h = uv.y;
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
    varying vec3 vWorld;
    float hash(vec2 p) {
      return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
    }
    void main() {
      float blade = smoothstep(0.0, 0.15, vUv.x) * smoothstep(1.0, 0.85, vUv.x);
      if (blade < 0.2) discard;
      float cell = hash(floor((vWorld.xz + uCookie) * 1.7));
      float dapple = smoothstep(0.38, 0.62, cell);
      vec3 color = mix(uBase, uTip, vUv.y) * mix(0.42, 1.2, dapple);
      color = mix(color, vec3(0.78, 0.86, 0.7), smoothstep(16.0, 34.0, vDist));
      gl_FragColor = vec4(color, 1.0);
    }
  `,
}

function keepTexture(kept: Kept, texture: Texture | null): Texture | null {
  if (texture) kept.textures.push(texture)
  return texture
}

function addTrunks(root: Group, trunks: readonly Trunk[], kept: Kept, seed: number) {
  const bark = keepTexture(kept, barkTexture(seed))
  const wood = new MeshStandardMaterial({ map: bark ?? null, color: bark ? 0xffffff : 0x6a5344, roughness: 0.9 })
  const canopy = new MeshStandardMaterial({ color: 0x87b85a, roughness: 0.8, transparent: true, opacity: 0.92 })
  kept.materials.push(wood, canopy)
  const branchGeo = new CylinderGeometry(0.045, 0.07, 1.15, 5)
  kept.geometries.push(branchGeo)
  for (const trunk of trunks) {
    const geo = new CylinderGeometry(trunk.radius * 0.72, trunk.radius, trunk.height, 7)
    const mesh = new Mesh(geo, wood)
    mesh.position.set(trunk.x, trunk.height / 2, trunk.z)
    mesh.rotation.y = trunk.yaw
    mesh.castShadow = true
    mesh.receiveShadow = true
    root.add(mesh)
    kept.geometries.push(geo)
    const crownGeo = new SphereGeometry(trunk.radius * (trunk.layer === 1 ? 2.4 : 3.2), 6, 5)
    const crown = new Mesh(crownGeo, canopy)
    crown.position.set(trunk.x, trunk.height * 1.08, trunk.z)
    crown.scale.set(1.15, 0.28, 1.15)
    crown.castShadow = true
    root.add(crown)
    kept.geometries.push(crownGeo)
    if (trunk.layer === 1) {
      addBranch(root, branchGeo, wood, trunk, 1)
      addBranch(root, branchGeo, wood, trunk, -1)
    }
  }
}

function addBranch(root: Group, geo: CylinderGeometry, wood: MeshStandardMaterial, trunk: Trunk, side: number) {
  const branch = new Mesh(geo, wood)
  branch.position.set(trunk.x + side * 0.15, trunk.height * 0.58, trunk.z)
  branch.rotation.set(0.35, trunk.yaw, side * 1.05)
  branch.castShadow = true
  root.add(branch)
}

function addGround(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const geo = new PlaneGeometry(48, 48, 40, 40)
  geo.rotateX(-Math.PI / 2)
  const pos = geo.attributes.position as BufferAttribute
  for (let i = 0; i < pos.count; i += 1) {
    const lift = fbm2(pos.getX(i) * 0.12, pos.getZ(i) * 0.12, resolved.seed) * 0.09
    pos.setY(i, lift)
  }
  geo.computeVertexNormals()
  const maps = cobbleTextures(resolved.stone, resolved.seed)
  keepTexture(kept, maps.albedo)
  keepTexture(kept, maps.normal)
  const mat = new MeshStandardMaterial({
    map: maps.albedo ?? null,
    normalMap: maps.normal ?? null,
    color: maps.albedo ? 0xffffff : resolved.stone,
    roughness: 0.92,
  })
  const mesh = new Mesh(geo, mat)
  mesh.name = 'atmos-ground'
  mesh.receiveShadow = true
  root.add(mesh)
  kept.geometries.push(geo)
  kept.materials.push(mat)
}

function seatBlade(i: number, seed: number): [number, number] {
  let x = (hash2(i, 1, seed) - 0.5) * 22
  let z = 4.2 - hash2(i, 2, seed) * 18
  for (let n = 0; n < 4; n += 1) {
    if (cobbleJoint(x, z, seed) < 0.28) break
    x += (hash2(i, 11 + n, seed) - 0.5) * 0.7
    z += (hash2(i, 17 + n, seed) - 0.5) * 0.7
  }
  const dx = x - CLEARING_SUBJECT[0]
  const dz = z - CLEARING_SUBJECT[2]
  if (dx * dx + dz * dz < 0.85 * 0.85) z -= 2.4
  return [x, z]
}

function addGrass(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const geo = new PlaneGeometry(0.016, 0.2, 1, 3)
  const phases = new Float32Array(resolved.grassBlades)
  const mat = new ShaderMaterial({
    uniforms: {
      uTime: { value: 0 },
      uBend: { value: 0.25 + resolved.wind * 0.45 },
      uCam: { value: new Vector3() },
      uBase: { value: new Color(resolved.grass).multiplyScalar(0.45) },
      uTip: { value: new Color(resolved.grass) },
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
    dummy.scale.setScalar(0.55 + hash2(i, 4, resolved.seed) * 0.7)
    dummy.updateMatrix()
    mesh.setMatrixAt(i, dummy.matrix)
    phases[i] = hash2(i, 5, resolved.seed) * Math.PI * 2
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
  const rockGeo = new IcosahedronGeometry(0.42, 1)
  const rockMat = new MeshStandardMaterial({ color: 0x9aa392, roughness: 0.95 })
  const rock = new Mesh(rockGeo, rockMat)
  rock.position.set(2.15, 0.2, 1.05)
  rock.scale.set(1.4, 0.7, 1.1)
  rock.castShadow = true
  rock.receiveShadow = true
  root.add(rock)
  kept.geometries.push(rockGeo)
  kept.materials.push(rockMat)
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
  addTrunks(root, clearingTrunks(resolved.seed), kept, resolved.seed)
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
