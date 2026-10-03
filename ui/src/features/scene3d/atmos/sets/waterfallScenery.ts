import {
  AdditiveBlending,
  BufferGeometry,
  CircleGeometry,
  Color,
  ConeGeometry,
  CylinderGeometry,
  DoubleSide,
  Float32BufferAttribute,
  Group,
  IcosahedronGeometry,
  InstancedMesh,
  Mesh,
  MeshStandardMaterial,
  Object3D,
  PlaneGeometry,
  RingGeometry,
  ShaderMaterial,
  type BufferAttribute,
} from 'three'
import type { ResolvedAtmos } from '../params.ts'
import { fbm2, hash2 } from '../noise.ts'
import { scatter, type Area } from '../layout.ts'
import { floorTexture } from '../textures.ts'
import { addBushes, addFlowers, type Kept } from '../forest.ts'
import {
  cliffBoulders, poolRocks, rimPines, FALLS_X, LEFT_BANK, POOL, RIGHT_BANK, SHEET_Z, WATER,
  type Boulder,
} from './waterfallLayout.ts'

const ROCK_TONES: Record<string, readonly string[]> = {
  moss: ['#8b8676', '#a39d8a', '#6f6c60'],
  amber: ['#a08262', '#bf9c72', '#7c6448'],
}
const MEADOW: Record<string, string> = { moss: '#72b04c', amber: '#b9a04c' }
const PINE_GREEN: Record<string, string> = { moss: '#2f6b4a', amber: '#5c7a3a' }

const PINE_LEFT: Area = { x0: -8.4, x1: -3.6, z0: -2.4, z1: 0.2 }
const PINE_RIGHT: Area = { x0: 3.9, x1: 8.4, z0: -2.4, z1: 0.2 }

const POOL_VERTEX = `
  varying vec2 vP;
  void main() {
    vP = (uv - 0.5) * 2.0;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`
const POOL_FRAGMENT = `
  uniform float uTime;
  uniform float uFlow;
  uniform vec3 uDeep;
  uniform vec3 uShallow;
  uniform vec3 uFoam;
  varying vec2 vP;
  float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
  float noise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash(i), hash(i + vec2(1, 0)), f.x), mix(hash(i + vec2(0, 1)), hash(i + vec2(1, 1)), f.x), f.y);
  }
  void main() {
    float r = length(vP);
    vec2 src = vec2(0.0, -0.3);
    float d = length(vP - src);
    float ring = 0.5 + 0.5 * sin(d * 24.0 - uTime * uFlow * 2.6);
    float ripple = ring * smoothstep(1.1, 0.15, d) * 0.25;
    vec3 color = mix(uShallow, uDeep, smoothstep(1.0, 0.15, r));
    color += ripple * 0.3;
    float churn = noise(vP * 9.0 + vec2(0.0, uTime * uFlow * 0.9));
    float foam = smoothstep(0.62, 0.0, d) * (0.55 + 0.6 * churn);
    foam += smoothstep(0.78, 1.0, r) * (0.35 + 0.5 * noise(vP * 14.0 + uTime * 0.2));
    color = mix(color, uFoam, clamp(foam, 0.0, 0.95));
    float glint = step(0.987, hash(floor(vP * 46.0) + floor(uTime * 2.5)));
    color += glint * 0.35;
    gl_FragColor = vec4(color, 0.94 * smoothstep(1.0, 0.94, r));
  }
`
const RAINBOW_VERTEX = `
  varying vec2 vR;
  void main() {
    vR = position.xy;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`
const RAINBOW_FRAGMENT = `
  uniform float uInner;
  uniform float uOuter;
  varying vec2 vR;
  void main() {
    float t = (length(vR) - uInner) / (uOuter - uInner);
    vec3 color = 0.5 + 0.5 * cos(6.28318 * (vec3(1.0 - t) * 0.72 + vec3(0.0, 0.33, 0.67)));
    float band = pow(sin(3.14159 * clamp(t, 0.0, 1.0)), 1.6);
    float feet = smoothstep(0.0, 0.32, vR.y / uOuter);
    gl_FragColor = vec4(color, band * feet * 0.2);
  }
`

function tone(resolved: ResolvedAtmos, boulder: Boulder): Color {
  const set = ROCK_TONES[resolved.palette] ?? ROCK_TONES.moss
  const color = new Color(set[Math.min(set.length - 1, Math.floor(boulder.y / 1.35 + boulder.tone * 0.9) % set.length)])
  color.multiplyScalar(0.85 + boulder.tone * 0.3)
  if (boulder.y < 0.9) color.multiplyScalar(0.62)
  if (boulder.moss > 0) color.lerp(new Color(MEADOW[resolved.palette] ?? MEADOW.moss).multiplyScalar(0.75), boulder.moss)
  return color
}

function jitteredRock(seed: number): IcosahedronGeometry {
  const geo = new IcosahedronGeometry(1, 1)
  const pos = geo.getAttribute('position')
  for (let i = 0; i < pos.count; i += 1) {
    const k = 1 + (hash2(Math.round(pos.getX(i) * 40), Math.round(pos.getZ(i) * 40) + Math.round(pos.getY(i) * 13), seed) - 0.5) * 0.4
    pos.setXYZ(i, pos.getX(i) * k, pos.getY(i) * k, pos.getZ(i) * k)
  }
  geo.computeVertexNormals()
  return geo
}

function rockMesh(name: string, boulders: readonly Boulder[], resolved: ResolvedAtmos, kept: Kept, seed: number): Mesh {
  const geo = jitteredRock(seed)
  const mat = new MeshStandardMaterial({ color: 0xffffff, roughness: 0.96, flatShading: true, emissive: 0x24221c, emissiveIntensity: 0.55 })
  const mesh = new InstancedMesh(geo, mat, boulders.length)
  mesh.name = name
  mesh.castShadow = true
  mesh.receiveShadow = true
  const dummy = new Object3D()
  boulders.forEach((boulder, i) => {
    dummy.position.set(boulder.x, boulder.y, boulder.z)
    dummy.scale.set(boulder.sx, boulder.sy, boulder.sz)
    dummy.rotation.set(0, boulder.yaw, (boulder.tone - 0.5) * 0.3)
    dummy.updateMatrix()
    mesh.setMatrixAt(i, dummy.matrix)
    mesh.setColorAt(i, tone(resolved, boulder))
  })
  mesh.instanceMatrix.needsUpdate = true
  kept.geometries.push(geo)
  kept.materials.push(mat)
  return mesh
}

export function addRockWalls(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  root.add(rockMesh('atmos-cliff', cliffBoulders(resolved.seed), resolved, kept, resolved.seed))
  root.add(rockMesh('atmos-stone', poolRocks(resolved.seed), resolved, kept, resolved.seed + 9))
}

export function addGround(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const geo = new PlaneGeometry(40, 40, 72, 72)
  geo.rotateX(-Math.PI / 2)
  const pos = geo.attributes.position as BufferAttribute
  const colors: number[] = []
  for (let i = 0; i < pos.count; i += 1) {
    const x = pos.getX(i)
    const z = pos.getZ(i)
    const wet = Math.max(0, 1 - Math.hypot((x - POOL.x) / (POOL.rx + 1.4), (z - POOL.z) / (POOL.rz + 1.1)))
    pos.setY(i, fbm2(x * 0.2, z * 0.2, resolved.seed) * 0.12 * (1 - wet) - 0.03)
    const tint = 0.82 + fbm2(x * 0.09 + 3, z * 0.09, resolved.seed + 4) * 0.42
    colors.push(tint * (1 - wet * 0.45), tint * (1 - wet * 0.28), tint * (1 - wet * 0.1))
  }
  geo.setAttribute('color', new Float32BufferAttribute(colors, 3))
  geo.computeVertexNormals()
  const map = floorTexture(MEADOW[resolved.palette] ?? MEADOW.moss, resolved.stone, resolved.seed)
  const mat = new MeshStandardMaterial({ map, vertexColors: true, roughness: 0.95, emissive: 0x1c2618, emissiveIntensity: 0.5 })
  const mesh = new Mesh(geo, mat)
  mesh.name = 'atmos-ground'
  mesh.receiveShadow = true
  root.add(mesh)
  kept.geometries.push(geo)
  kept.materials.push(mat)
  if (map) kept.textures.push(map)
}

export function addPool(root: Group, resolved: ResolvedAtmos, kept: Kept, flow: number): ShaderMaterial {
  const geo = new CircleGeometry(1, 48)
  geo.rotateX(-Math.PI / 2)
  const accent = new Color(WATER[resolved.palette] ?? WATER.moss)
  const mat = new ShaderMaterial({
    transparent: true,
    depthWrite: false,
    uniforms: {
      uTime: { value: 0 },
      uFlow: { value: flow },
      uDeep: { value: accent.clone().multiplyScalar(0.62) },
      uShallow: { value: accent.clone().lerp(new Color('#bfeee0'), 0.35) },
      uFoam: { value: new Color(resolved.palette === 'amber' ? '#f8e7cf' : '#eafaf5') },
    },
    vertexShader: POOL_VERTEX,
    fragmentShader: POOL_FRAGMENT,
  })
  const mesh = new Mesh(geo, mat)
  mesh.name = 'atmos-river'
  mesh.position.set(POOL.x, 0.045, POOL.z)
  mesh.scale.set(POOL.rx, 1, POOL.rz)
  root.add(mesh)
  kept.geometries.push(geo)
  kept.materials.push(mat)
  return mat
}

function pineTiers(): { geometry: ConeGeometry; y: number }[] {
  return [
    { geometry: new ConeGeometry(0.95, 1.5, 7), y: 1.45 },
    { geometry: new ConeGeometry(0.75, 1.3, 7), y: 2.35 },
    { geometry: new ConeGeometry(0.52, 1.15, 7), y: 3.2 },
  ]
}

export function addPines(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const banks = [
    ...scatter(3, resolved.seed, 101, [], PINE_LEFT, 0.6).map(([x, z]) => ({ x, y: 0, z, scale: 0.55 + hash2(Math.round(x * 10), Math.round(z * 10), resolved.seed) * 0.3 })),
    ...scatter(3, resolved.seed, 107, [], PINE_RIGHT, 0.6).map(([x, z]) => ({ x, y: 0, z, scale: 0.55 + hash2(Math.round(x * 7), Math.round(z * 7), resolved.seed) * 0.3 })),
  ]
  const spots = [...rimPines(resolved.seed), ...banks]
  const green = new Color(PINE_GREEN[resolved.palette] ?? PINE_GREEN.moss)
  const trunkGeo = new CylinderGeometry(0.1, 0.16, 1.7, 6)
  trunkGeo.translate(0, 0.85, 0)
  const trunkMat = new MeshStandardMaterial({ color: 0x6d5240, roughness: 0.95, flatShading: true, emissive: 0x2a1e14, emissiveIntensity: 0.6 })
  const trunks = new InstancedMesh(trunkGeo, trunkMat, spots.length)
  trunks.name = 'atmos-pine-trunks'
  const leafMat = new MeshStandardMaterial({ color: 0xffffff, roughness: 0.9, flatShading: true, emissive: 0x2b5c3c, emissiveIntensity: 0.65 })
  const dummy = new Object3D()
  spots.forEach((spot, i) => {
    dummy.position.set(spot.x, spot.y, spot.z)
    dummy.scale.setScalar(spot.scale)
    dummy.rotation.set(0, i * 2.1, 0)
    dummy.updateMatrix()
    trunks.setMatrixAt(i, dummy.matrix)
  })
  root.add(trunks)
  kept.geometries.push(trunkGeo)
  kept.materials.push(trunkMat, leafMat)
  for (const tier of pineTiers()) {
    const tiers = new InstancedMesh(tier.geometry, leafMat, spots.length)
    tiers.name = 'atmos-pine'
    tiers.castShadow = true
    spots.forEach((spot, i) => {
      dummy.position.set(spot.x, spot.y + tier.y * spot.scale, spot.z)
      dummy.scale.setScalar(spot.scale)
      dummy.rotation.set(0, i * 2.1 + tier.y, 0)
      dummy.updateMatrix()
      tiers.setMatrixAt(i, dummy.matrix)
      tiers.setColorAt(i, green.clone().multiplyScalar(0.95 + hash2(i, Math.round(tier.y * 10), resolved.seed) * 0.5))
    })
    root.add(tiers)
    kept.geometries.push(tier.geometry)
  }
}

export function addBankPlants(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const pool = [{ x: POOL.x, z: POOL.z, height: 1, radius: 1.9, layer: 1 as const, yaw: 0 }]
  const tone = MEADOW[resolved.palette] ?? MEADOW.moss
  const half = Math.max(4, Math.ceil(resolved.grassBlades / 2))
  addBushes(root, pool, resolved, kept, { area: LEFT_BANK, count: half, tone, salt: 141 })
  addBushes(root, pool, resolved, kept, { area: RIGHT_BANK, count: half, tone, salt: 147 })
  addFlowers(root, pool, resolved, kept, { area: LEFT_BANK, count: 4, salt: 151 })
  addFlowers(root, pool, resolved, kept, { area: RIGHT_BANK, count: 4, salt: 157 })
}

export function addRainbow(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const inner = 2.55
  const outer = 3.0
  const geo: BufferGeometry = new RingGeometry(inner, outer, 72, 1, 0, Math.PI)
  const mat = new ShaderMaterial({
    transparent: true,
    depthWrite: false,
    side: DoubleSide,
    blending: AdditiveBlending,
    uniforms: { uInner: { value: inner }, uOuter: { value: outer } },
    vertexShader: RAINBOW_VERTEX,
    fragmentShader: RAINBOW_FRAGMENT,
  })
  const mesh = new Mesh(geo, mat)
  mesh.name = 'atmos-rainbow'
  mesh.position.set(FALLS_X + 0.1, 0.5, SHEET_Z + 0.55)
  mesh.visible = resolved.timeOfDay === 'golden'
  root.add(mesh)
  kept.geometries.push(geo)
  kept.materials.push(mat)
}
