import {
  BufferGeometry,
  Color,
  CylinderGeometry,
  Float32BufferAttribute,
  Group,
  IcosahedronGeometry,
  InstancedMesh,
  Material,
  Mesh,
  MeshStandardMaterial,
  Object3D,
  SphereGeometry,
  type Texture,
} from 'three'
import { hash2 } from './noise.ts'
import { scatter, type Area, type Trunk } from './layout.ts'
import type { ResolvedAtmos } from './params.ts'

export type Kept = { geometries: BufferGeometry[]; materials: Material[]; textures: Texture[]; lights: import('three').SpotLight[] }

const TAU = Math.PI * 2
const MOSS = new Color(0x5f8a33)

function smooth(edge0: number, edge1: number, x: number): number {
  const t = Math.min(1, Math.max(0, (x - edge0) / (edge1 - edge0)))
  return t * t * (3 - 2 * t)
}

/** A trunk that flares into roots, leans a little and carries moss near the ground. Base sits at y = 0. */
export function trunkGeometry(trunk: Trunk, seed: number, tint: number): BufferGeometry {
  const geo = new CylinderGeometry(trunk.radius * 0.52, trunk.radius, trunk.height, 9, 12, true)
  geo.translate(0, trunk.height / 2, 0)
  const pos = geo.getAttribute('position')
  const uv = geo.getAttribute('uv')
  const phase = hash2(Math.round(trunk.x * 10), Math.round(trunk.z * 10), seed) * TAU
  const bark = new Color(0x9a7855).multiplyScalar(0.85 + tint * 0.3)
  const colors: number[] = []
  const shade = new Color()
  for (let i = 0; i < pos.count; i += 1) {
    const x = pos.getX(i)
    const y = pos.getY(i)
    const z = pos.getZ(i)
    const angle = Math.atan2(z, x)
    const flare = 1 + 1.15 * Math.exp(-y / 0.5) * (0.62 + 0.38 * Math.cos(5 * angle + phase))
    const lean = Math.sin((y / trunk.height) * 2.6 + phase) * 0.28 * (y / trunk.height)
    pos.setXYZ(i, x * flare + lean, y, z * flare)
    uv.setY(i, uv.getY(i) * trunk.height / 3)
    const moss = smooth(1.7, 0.1, y) * (0.45 + 0.55 * Math.cos(angle - phase))
    shade.copy(bark).lerp(MOSS, Math.min(0.85, Math.max(0, moss)))
    colors.push(shade.r, shade.g, shade.b)
  }
  geo.setAttribute('color', new Float32BufferAttribute(colors, 3))
  geo.computeVertexNormals()
  return geo
}

export function addTrunks(root: Group, trunks: readonly Trunk[], bark: Texture | null, seed: number, kept: Kept) {
  const wood = new MeshStandardMaterial({ map: bark, vertexColors: true, roughness: 0.95, flatShading: true, emissive: 0x3a2a1c, emissiveIntensity: 0.7 })
  kept.materials.push(wood)
  trunks.forEach((trunk, index) => {
    const geo = trunkGeometry(trunk, seed, hash2(index, 31, seed))
    const mesh = new Mesh(geo, wood)
    mesh.position.set(trunk.x, 0, trunk.z)
    mesh.rotation.y = trunk.yaw
    mesh.castShadow = true
    mesh.receiveShadow = true
    root.add(mesh)
    kept.geometries.push(geo)
  })
}

function leafShades(resolved: ResolvedAtmos, seed: number, count: number, low: number, high: number, tone?: string): Color[] {
  const base = new Color(tone ?? resolved.grass)
  return Array.from({ length: count }, (_, i) => {
    const color = base.clone().multiplyScalar(low + (high - low) * hash2(i, 61, seed))
    color.offsetHSL((hash2(i, 62, seed) - 0.5) * 0.05, 0, 0)
    return color
  })
}

function blobs(mesh: InstancedMesh, entries: Array<{ x: number; y: number; z: number; sx: number; sy: number; sz: number }>, colors: Color[]) {
  const dummy = new Object3D()
  entries.forEach((entry, i) => {
    dummy.position.set(entry.x, entry.y, entry.z)
    dummy.scale.set(entry.sx, entry.sy, entry.sz)
    dummy.rotation.y = i * 1.7
    dummy.updateMatrix()
    mesh.setMatrixAt(i, dummy.matrix)
    mesh.setColorAt(i, colors[i % colors.length])
  })
  mesh.instanceMatrix.needsUpdate = true
  if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true
}

/** Flat-shaded leaf clusters near each trunk top. One draw call for the whole forest. */
export function addCanopies(root: Group, trunks: readonly Trunk[], resolved: ResolvedAtmos, kept: Kept) {
  const geo = new IcosahedronGeometry(1, 1)
  const mat = new MeshStandardMaterial({ color: 0xffffff, roughness: 0.9, flatShading: true })
  const entries: Array<{ x: number; y: number; z: number; sx: number; sy: number; sz: number }> = []
  trunks.forEach((trunk, t) => {
    const reach = trunk.layer === 1 ? 2.3 : trunk.layer === 2 ? 3 : 3.8
    const count = 5 + (t % 2)
    for (let k = 0; k < count; k += 1) {
      const angle = hash2(t, k, resolved.seed) * TAU
      const spread = (0.2 + hash2(t, k + 9, resolved.seed) * 0.8) * reach * 0.7
      const size = reach * (0.55 + hash2(t, k + 19, resolved.seed) * 0.5)
      entries.push({
        x: trunk.x + Math.cos(angle) * spread,
        y: trunk.height * (0.78 + hash2(t, k + 29, resolved.seed) * 0.24),
        z: trunk.z + Math.sin(angle) * spread,
        sx: size, sy: size * 0.68, sz: size,
      })
    }
  })
  const mesh = new InstancedMesh(geo, mat, entries.length)
  mesh.name = 'atmos-canopy'
  mesh.castShadow = true
  mesh.frustumCulled = false
  blobs(mesh, entries, leafShades(resolved, resolved.seed, 24, 0.3, 0.62))
  root.add(mesh)
  kept.geometries.push(geo)
  kept.materials.push(mat)
}

function jitter(geo: IcosahedronGeometry, seed: number, amount: number) {
  const pos = geo.getAttribute('position')
  for (let i = 0; i < pos.count; i += 1) {
    const k = 1 + (hash2(Math.round(pos.getX(i) * 40), Math.round(pos.getZ(i) * 40), seed) - 0.5) * amount
    pos.setXYZ(i, pos.getX(i) * k, pos.getY(i) * k, pos.getZ(i) * k)
  }
  geo.computeVertexNormals()
}

/** Area, count and leaf colour default to the clearing's; other sets pass their own. */
export type PlantOptions = { area?: Area; count?: number; tone?: string; salt?: number }

export function addBushes(root: Group, trunks: readonly Trunk[], resolved: ResolvedAtmos, kept: Kept, options: PlantOptions = {}) {
  const geo = new IcosahedronGeometry(0.5, 1)
  jitter(geo, resolved.seed, 0.22)
  const mat = new MeshStandardMaterial({ color: 0xffffff, roughness: 0.92, flatShading: true, emissive: 0x1c3a12, emissiveIntensity: 0.5 })
  const spots = scatter(options.count ?? 46, resolved.seed, options.salt ?? 71, trunks, options.area ?? { x0: -10, x1: 10, z0: 3, z1: -15 }, 0.4)
  const entries = spots.map(([x, z], i) => {
    const size = 0.55 + hash2(i, 72, resolved.seed) * 0.9
    return { x, y: size * 0.16, z, sx: size, sy: size * 0.62, sz: size * (0.8 + hash2(i, 73, resolved.seed) * 0.5) }
  })
  const mesh = new InstancedMesh(geo, mat, entries.length)
  mesh.name = 'atmos-bushes'
  mesh.castShadow = true
  mesh.receiveShadow = true
  blobs(mesh, entries, leafShades(resolved, resolved.seed + 5, 16, 0.55, 0.95, options.tone))
  root.add(mesh)
  kept.geometries.push(geo)
  kept.materials.push(mat)
}

const PETALS = [0xfff4e0, 0xffd84a, 0xff9ec2, 0xb9a0ff]

export function addFlowers(root: Group, trunks: readonly Trunk[], resolved: ResolvedAtmos, kept: Kept, options: PlantOptions = {}) {
  const centers = scatter(options.count ?? 16, resolved.seed, options.salt ?? 81, trunks, options.area ?? { x0: -8, x1: 8, z0: 2.5, z1: -11 }, 0.6)
  const spots: Array<[number, number]> = []
  centers.forEach(([cx, cz], c) => {
    for (let k = 0; k < 9; k += 1) {
      const angle = hash2(c, k, resolved.seed + 82) * TAU
      const radius = Math.sqrt(hash2(c, k + 40, resolved.seed + 82)) * 0.65
      spots.push([cx + Math.cos(angle) * radius, cz + Math.sin(angle) * radius])
    }
  })
  const stemGeo = new CylinderGeometry(0.006, 0.008, 0.22, 3)
  stemGeo.translate(0, 0.11, 0)
  const headGeo = new SphereGeometry(0.04, 6, 4)
  const stemMat = new MeshStandardMaterial({ color: 0x79b545, roughness: 1, emissive: 0x2c4a18 })
  const headMat = new MeshStandardMaterial({ color: 0xffffff, roughness: 0.7 })
  const stems = new InstancedMesh(stemGeo, stemMat, spots.length)
  const heads = new InstancedMesh(headGeo, headMat, spots.length)
  const dummy = new Object3D()
  spots.forEach(([x, z], i) => {
    const tall = 0.85 + hash2(i, 83, resolved.seed) * 0.6
    dummy.position.set(x, 0, z)
    dummy.scale.set(1, tall, 1)
    dummy.updateMatrix()
    stems.setMatrixAt(i, dummy.matrix)
    dummy.position.set(x, 0.22 * tall, z)
    dummy.scale.set(1, 0.7, 1)
    dummy.updateMatrix()
    heads.setMatrixAt(i, dummy.matrix)
    heads.setColorAt(i, new Color(PETALS[Math.floor(hash2(Math.floor(i / 9), 84, resolved.seed) * PETALS.length)]))
  })
  stems.name = 'atmos-flower-stems'
  heads.name = 'atmos-flowers'
  root.add(stems, heads)
  kept.geometries.push(stemGeo, headGeo)
  kept.materials.push(stemMat, headMat)
}

function addMushrooms(root: Group, trunks: readonly Trunk[], resolved: ResolvedAtmos, kept: Kept) {
  const near = trunks.filter(trunk => trunk.layer === 1).slice(0, 5)
  const capGeo = new SphereGeometry(0.1, 8, 4, 0, TAU, 0, Math.PI / 2)
  const stemGeo = new CylinderGeometry(0.028, 0.036, 0.1, 6)
  stemGeo.translate(0, 0.05, 0)
  const capMat = new MeshStandardMaterial({ color: 0xd2452e, roughness: 0.6 })
  const stemMat = new MeshStandardMaterial({ color: 0xf1e6cf, roughness: 0.8 })
  const caps = new InstancedMesh(capGeo, capMat, near.length * 3)
  const stems = new InstancedMesh(stemGeo, stemMat, near.length * 3)
  const dummy = new Object3D()
  near.forEach((trunk, t) => {
    for (let k = 0; k < 3; k += 1) {
      const angle = hash2(t, k, resolved.seed + 91) * TAU
      const distance = trunk.radius * 1.6 + 0.12 + k * 0.1
      const size = 0.7 + hash2(t, k + 5, resolved.seed + 91) * 0.9
      dummy.position.set(trunk.x + Math.cos(angle) * distance, 0, trunk.z + Math.sin(angle) * distance)
      dummy.scale.setScalar(size)
      dummy.updateMatrix()
      stems.setMatrixAt(t * 3 + k, dummy.matrix)
      dummy.position.y = 0.1 * size
      dummy.updateMatrix()
      caps.setMatrixAt(t * 3 + k, dummy.matrix)
    }
  })
  caps.name = 'atmos-mushrooms'
  root.add(caps, stems)
  kept.geometries.push(capGeo, stemGeo)
  kept.materials.push(capMat, stemMat)
}

function addRocks(root: Group, resolved: ResolvedAtmos, kept: Kept) {
  const mat = new MeshStandardMaterial({ color: 0x9aa39a, roughness: 0.96, flatShading: true, emissive: 0x1c2420, emissiveIntensity: 0.5 })
  kept.materials.push(mat)
  const rocks: Array<[number, number, number, number, number]> = [
    [2.35, 1.15, 0.48, 0.7, 0.9], [-2.7, -1.9, 0.36, 0.6, 1.9], [3.6, -3.2, 0.6, 0.7, 3.1], [-4.1, 0.4, 0.28, 0.55, 4.2], [-1.9, -6.2, 0.7, 0.65, 5.3],
  ]
  rocks.forEach(([x, z, size, flat, turn], i) => {
    const geo = new IcosahedronGeometry(1, 1)
    jitter(geo, resolved.seed + i, 0.45)
    const rock = new Mesh(geo, mat)
    rock.position.set(x, size * flat * 0.4, z)
    rock.scale.set(size * 1.25, size * flat, size)
    rock.rotation.y = turn
    rock.castShadow = true
    rock.receiveShadow = true
    root.add(rock)
    kept.geometries.push(geo)
  })
}

function addLog(root: Group, bark: Texture | null, kept: Kept) {
  const geo = new CylinderGeometry(0.3, 0.34, 3.6, 9, 3)
  const mat = new MeshStandardMaterial({ map: bark, color: 0xb59c80, roughness: 0.95, flatShading: true, emissive: 0x3a2a1c, emissiveIntensity: 0.6 })
  const log = new Mesh(geo, mat)
  log.position.set(-2.9, 0.27, -3.4)
  log.rotation.set(0.05, 0.55, Math.PI / 2)
  log.castShadow = true
  log.receiveShadow = true
  root.add(log)
  kept.geometries.push(geo)
  kept.materials.push(mat)
}

/** Everything that makes the floor read as a forest: bushes, flowers, mushrooms, mossy rocks and a fallen log. */
export function addUnderstory(root: Group, trunks: readonly Trunk[], resolved: ResolvedAtmos, bark: Texture | null, kept: Kept) {
  addBushes(root, trunks, resolved, kept)
  addFlowers(root, trunks, resolved, kept)
  addMushrooms(root, trunks, resolved, kept)
  addRocks(root, resolved, kept)
  addLog(root, bark, kept)
}
