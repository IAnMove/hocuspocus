import {
  BufferGeometry,
  Color,
  Float32BufferAttribute,
  Group,
  IcosahedronGeometry,
  InstancedMesh,
  Material,
  Mesh,
  MeshStandardMaterial,
  Object3D,
  PlaneGeometry,
  type BufferAttribute,
  type Texture,
} from 'three'
import { fbm2, hash2 } from '../noise.ts'
import { terrainTexture, type TerrainPaint } from '../textures.ts'

/** What every set already tracks for disposal. `textures` is created on first use. */
export type KitKept = { geometries: BufferGeometry[]; materials: Material[]; textures?: Texture[] }

export function retainTexture(kept: KitKept, texture: Texture | null) {
  if (texture) (kept.textures ??= []).push(texture)
}

export type TerrainOptions = {
  size: number
  segments: number
  seed: number
  paint: TerrainPaint
  /** Height of the ground at x, z, in metres. */
  height?: (x: number, z: number) => number
  /** Brightness multiplier at x, z (soft tint so the texture never reads as a repeat). */
  tint?: (x: number, z: number) => number
  /** Keep this disc flat so a character can stand there. */
  flat?: { x: number; z: number; radius: number }
  emissive?: number
}

function flatten(x: number, z: number, flat: TerrainOptions['flat']): number {
  if (!flat) return 1
  const t = Math.min(1, Math.max(0, (Math.hypot(x - flat.x, z - flat.z) - flat.radius) / (flat.radius * 0.8)))
  return t * t * (3 - 2 * t)
}

/** Lit, painted ground with real relief. Replaces a flat coloured plane. */
export function paintedTerrain(root: Group, kept: KitKept, options: TerrainOptions): Mesh {
  const geo = new PlaneGeometry(options.size, options.size, options.segments, options.segments)
  geo.rotateX(-Math.PI / 2)
  const pos = geo.attributes.position as BufferAttribute
  const colors: number[] = []
  for (let i = 0; i < pos.count; i += 1) {
    const x = pos.getX(i)
    const z = pos.getZ(i)
    const keep = flatten(x, z, options.flat)
    pos.setY(i, (options.height ? options.height(x, z) : 0) * keep)
    const tint = (options.tint ? options.tint(x, z) : 0.85 + fbm2(x * 0.08 + 3, z * 0.08, options.seed + 4) * 0.35)
    colors.push(tint, tint, tint)
  }
  geo.setAttribute('color', new Float32BufferAttribute(colors, 3))
  geo.computeVertexNormals()
  const map = terrainTexture(options.paint)
  const mat = new MeshStandardMaterial({ map, vertexColors: true, roughness: 0.96, flatShading: true, emissive: options.emissive ?? 0x1a1a1a, emissiveIntensity: 0.4 })
  const mesh = new Mesh(geo, mat)
  mesh.name = 'atmos-ground'
  mesh.receiveShadow = true
  root.add(mesh)
  kept.geometries.push(geo)
  kept.materials.push(mat)
  retainTexture(kept, map)
  return mesh
}

export type BoulderSpot = { x: number; z: number; size: number; flat?: number; tone?: number }

function jittered(seed: number, amount: number): IcosahedronGeometry {
  const geo = new IcosahedronGeometry(1, 1)
  const pos = geo.getAttribute('position')
  for (let i = 0; i < pos.count; i += 1) {
    const k = 1 + (hash2(Math.round(pos.getX(i) * 40), Math.round(pos.getZ(i) * 40) + Math.round(pos.getY(i) * 13), seed) - 0.5) * amount
    pos.setXYZ(i, pos.getX(i) * k, pos.getY(i) * k, pos.getZ(i) * k)
  }
  geo.computeVertexNormals()
  return geo
}

/** Faceted rocks in one draw call, tinted from a short palette. */
export function boulders(root: Group, kept: KitKept, spots: readonly BoulderSpot[], palette: readonly string[], seed: number, name = 'atmos-rock'): InstancedMesh {
  const geo = jittered(seed, 0.42)
  const mat = new MeshStandardMaterial({ color: 0xffffff, roughness: 0.97, flatShading: true, emissive: 0x1d1d1d, emissiveIntensity: 0.5 })
  const mesh = new InstancedMesh(geo, mat, spots.length)
  mesh.name = name
  mesh.castShadow = true
  mesh.receiveShadow = true
  const dummy = new Object3D()
  spots.forEach((spot, i) => {
    const flat = spot.flat ?? 0.7
    dummy.position.set(spot.x, spot.size * flat * 0.45, spot.z)
    dummy.scale.set(spot.size * (1 + hash2(i, 61, seed) * 0.35), spot.size * flat, spot.size)
    dummy.rotation.set(0, hash2(i, 62, seed) * Math.PI, (hash2(i, 63, seed) - 0.5) * 0.3)
    dummy.updateMatrix()
    mesh.setMatrixAt(i, dummy.matrix)
    const pick = palette[Math.floor((spot.tone ?? hash2(i, 64, seed)) * palette.length) % palette.length]
    mesh.setColorAt(i, new Color(pick).multiplyScalar(0.85 + hash2(i, 65, seed) * 0.3))
  })
  mesh.instanceMatrix.needsUpdate = true
  root.add(mesh)
  kept.geometries.push(geo)
  kept.materials.push(mat)
  return mesh
}

export type RidgeOptions = {
  seed: number
  count: number
  radius: number
  /** Peak height range in metres. */
  height: readonly [number, number]
  width: readonly [number, number]
  color: string
  /** Colour the distant layer fades toward, so far ridges read as haze. */
  haze: string
  /** Half-width of the arc behind the scene, in radians. */
  arc?: number
  layers?: number
}

/** Layered low-poly mountain silhouettes behind the scene. Far layers fade toward the haze colour. */
export function ridge(root: Group, kept: KitKept, options: RidgeOptions): InstancedMesh {
  const layers = options.layers ?? 3
  const geo = jittered(options.seed + 7, 0.3)
  const mat = new MeshStandardMaterial({ color: 0xffffff, roughness: 1, flatShading: true, emissive: 0x2a2a2a, emissiveIntensity: 0.6 })
  const total = options.count * layers
  const mesh = new InstancedMesh(geo, mat, total)
  mesh.name = 'atmos-ridge'
  mesh.frustumCulled = false
  const dummy = new Object3D()
  const near = new Color(options.color)
  const far = new Color(options.haze)
  const arc = options.arc ?? 1.25
  for (let layer = 0; layer < layers; layer += 1) {
    for (let k = 0; k < options.count; k += 1) {
      const i = layer * options.count + k
      const angle = (k / (options.count - 1) - 0.5) * 2 * arc + (hash2(i, 71, options.seed) - 0.5) * 0.12
      const radius = options.radius * (1 + layer * 0.22) + (hash2(i, 72, options.seed) - 0.5) * 3
      const peak = options.height[0] + hash2(i, 73, options.seed) * (options.height[1] - options.height[0])
      const wide = options.width[0] + hash2(i, 74, options.seed) * (options.width[1] - options.width[0])
      dummy.position.set(Math.sin(angle) * radius, peak * 0.32 - layer * 0.8, -Math.cos(angle) * radius)
      dummy.scale.set(wide, peak, wide * 0.85)
      dummy.rotation.set(0, hash2(i, 75, options.seed) * Math.PI, 0)
      dummy.updateMatrix()
      mesh.setMatrixAt(i, dummy.matrix)
      mesh.setColorAt(i, near.clone().lerp(far, Math.min(0.85, 0.28 + layer * 0.3)).multiplyScalar(0.9 + hash2(i, 76, options.seed) * 0.2))
    }
  }
  mesh.instanceMatrix.needsUpdate = true
  root.add(mesh)
  kept.geometries.push(geo)
  kept.materials.push(mat)
  return mesh
}

export type BackdropOptions = {
  height: readonly [number, number]
  width: readonly [number, number]
  /** Colour of the nearest layer. Defaults to the set's ground colour, darkened. */
  near?: string
  tone?: number
  radius?: number
  count?: number
  layers?: number
  arc?: number
}

/** A `ridge` coloured from the resolved set: ground colour up close, fog colour far away. Keep radius × 1.22^(layers-1) inside the sky sphere. */
export function backdropRidge(root: Group, kept: KitKept, resolved: { stone: string; fogColor: string; seed: number }, options: BackdropOptions): InstancedMesh {
  const near = options.near ?? `#${new Color(resolved.stone).multiplyScalar(options.tone ?? 0.72).getHexString()}`
  return ridge(root, kept, {
    seed: resolved.seed, count: options.count ?? 11, radius: options.radius ?? 17, height: options.height, width: options.width,
    color: near, haze: resolved.fogColor, layers: options.layers ?? 2, arc: options.arc,
  })
}
