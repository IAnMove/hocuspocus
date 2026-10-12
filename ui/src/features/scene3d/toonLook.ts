import {
  BackSide,
  BufferAttribute,
  Color,
  DataTexture,
  Mesh,
  MeshBasicMaterial,
  MeshToonMaterial,
  NearestFilter,
  RedFormat,
  ShaderMaterial,
  SkinnedMesh,
  UniformsLib,
  UniformsUtils,
  Vector3,
  type BufferGeometry,
  type Material,
  type MeshLambertMaterial,
  type MeshPhongMaterial,
  type MeshStandardMaterial,
  type Object3D,
} from 'three'
import type { Scene3DDocument, Scene3DToon } from './types'

/** Cel shading and ink outlines for model slots (`renderLook: 'toon'`).

The look is swapped in only around a draw: `ToonLook.draw` gives every mesh under the model roots a `MeshToonMaterial`
and an inverted-hull ink outline, renders, and puts the authored materials back. Code that runs between frames
(speech faces, materialization, picking, bounds, shadows) never sees a toon material or an outline mesh, and
switching the look off leaves the scene exactly as authored.
*/

export type ToonSettings = { steps: number; outline: number; ink: string }
export type ToonTarget = { root: Object3D; outline: boolean }

export const DEFAULT_TOON: ToonSettings = { steps: 3, outline: 3, ink: '#141018' }
/** Light of the darkest band; the others are spread evenly up to full light. */
const SHADOW_BAND = 0.3
/** Ink widths are pixels of a 1080-pixel-high frame, so preview and any export size match. */
const REFERENCE_HALF_HEIGHT = 540
/** Lines keep their full width up to this distance in metres and thin out beyond it, down to INK_FLOOR. */
const INK_REACH = 6
const INK_FLOOR = 0.35
/** The hull sits this fraction of its distance behind the surface, so it never covers a front face. */
const INK_DEPTH = 0.0015
/** Hull faces turned further from the camera than this (cosine) are dropped. The line comes from faces near the
 * silhouette; faces turned away only show through holes and open seams of a scanned mesh, as black specks. */
const INK_AWAY = -0.6
export const OUTLINE_NORMAL = 'toonOutlineNormal'
const HEX = /^#[0-9a-f]{6}$/i

function bounded(value: unknown, min: number, max: number): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? Math.min(max, Math.max(min, value)) : undefined
}

/** A stored toon block, bounded; unusable values are left out so the defaults apply. */
export function parseToon(raw: unknown): Scene3DToon | undefined {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return undefined
  const value = raw as Record<string, unknown>
  const steps = bounded(value.steps, 2, 4)
  const outline = bounded(value.outline, 0, 8)
  const ink = typeof value.ink === 'string' && HEX.test(value.ink) ? value.ink.toLowerCase() : undefined
  return {
    ...(steps !== undefined ? { steps: Math.round(steps) } : {}),
    ...(outline !== undefined ? { outline: Math.round(outline * 100) / 100 } : {}),
    ...(ink ? { ink } : {}),
  }
}

export function toonField(raw: unknown): { toon?: Scene3DToon } {
  const toon = parseToon(raw)
  return toon ? { toon } : {}
}

/** The effective settings of a document, or null when the look is off. */
export function resolveToon(document: Pick<Scene3DDocument, 'renderLook' | 'toon'>): ToonSettings | null {
  return document.renderLook === 'toon' ? { ...DEFAULT_TOON, ...parseToon(document.toon) } : null
}

/** `steps` flat bands of light, sampled without filtering so the terminator stays a hard edge. */
export function toonGradient(steps: number): DataTexture {
  const data = new Uint8Array(steps)
  for (let i = 0; i < steps; i += 1) data[i] = Math.round(255 * (SHADOW_BAND + (1 - SHADOW_BAND) * i / (steps - 1)))
  const texture = new DataTexture(data, steps, 1, RedFormat)
  texture.minFilter = NearestFilter
  texture.magFilter = NearestFilter
  texture.generateMipmaps = false
  texture.needsUpdate = true
  return texture
}

type LitMaterial = MeshStandardMaterial | MeshLambertMaterial | MeshPhongMaterial
type Flags = Partial<Record<'isMeshStandardMaterial' | 'isMeshLambertMaterial' | 'isMeshPhongMaterial' | 'isMeshBasicMaterial', boolean>>

/** Standard and physical (PBR), Lambert and Phong materials; unlit, shader and image materials stay as they are. */
export function isLitMaterial(material: Material): material is LitMaterial {
  const flags = material as Material & Flags
  return Boolean(flags.isMeshStandardMaterial || flags.isMeshLambertMaterial || flags.isMeshPhongMaterial)
}

/** Opaque surfaces get ink; glass, alpha-cut cards and hidden materials do not. */
export function inkable(material: Material): boolean {
  const surface = isLitMaterial(material) || (material as Material & Flags).isMeshBasicMaterial === true
  const cut = material.alphaTest > 0 || material.alphaHash || Boolean((material as Material & { alphaMap?: unknown }).alphaMap)
  return surface && material.visible && material.colorWrite && !(material.transparent && material.opacity < 1) && !cut
}

/** Properties copied from the authored material on every draw, so runtime changes (opacity, maps, visibility) show. */
const MIRRORED = [
  'name', 'visible', 'side', 'shadowSide', 'transparent', 'opacity', 'alphaTest', 'alphaHash', 'alphaToCoverage',
  'blending', 'blendSrc', 'blendDst', 'blendEquation', 'blendSrcAlpha', 'blendDstAlpha', 'blendEquationAlpha',
  'premultipliedAlpha', 'depthFunc', 'depthTest', 'depthWrite', 'colorWrite', 'polygonOffset', 'polygonOffsetFactor',
  'polygonOffsetUnits', 'dithering', 'toneMapped', 'vertexColors', 'forceSinglePass', 'fog', 'wireframe',
  'map', 'alphaMap', 'emissiveMap', 'emissiveIntensity',
] as const

function mirror(source: LitMaterial, toon: MeshToonMaterial) {
  const from = source as unknown as Record<string, unknown>
  const to = toon as unknown as Record<string, unknown>
  for (const key of MIRRORED) if (key in from && to[key] !== from[key]) to[key] = from[key] ?? null
  toon.color.copy(source.color)
  toon.emissive.copy(source.emissive)
}

/** Everything that selects a different shader program; `version` catches `needsUpdate` and shader patches. */
function programKey(source: LitMaterial): string {
  return [
    Boolean(source.map), Boolean(source.alphaMap), Boolean(source.emissiveMap), source.vertexColors, source.alphaTest > 0,
    source.alphaHash, source.alphaToCoverage, source.side, source.fog, source.toneMapped, source.premultipliedAlpha,
    source.dithering, source.version,
  ].join('|')
}

/** Diffuse light a white surface gets from the generated room environment at intensity 1. Measured on a sphere and
 * a box seen from three sides (0.19 to 0.47 at intensity 0.25, about 0.3 on average). */
const ROOM_FILL = 1.2

/** Flat ambient irradiance that gives a toon surface the diffuse light a PBR surface gets from the environment.
 * MeshToonMaterial takes no environment map, so without it a scene lit mostly by its environment goes dark. */
export function environmentFill(intensity: number): number {
  return Math.PI * ROOM_FILL * Math.max(0, intensity)
}

export type ToonFill = { value: Color }

/** Adds `fill` as indirect diffuse light after three's own lights. */
export function withEnvironmentFill(shader: { uniforms: Record<string, unknown>; fragmentShader: string }, fill: ToonFill) {
  shader.uniforms.toonFill = fill
  shader.fragmentShader = shader.fragmentShader
    .replace('#include <common>', '#include <common>\nuniform vec3 toonFill;')
    .replace('#include <lights_fragment_end>', '#include <lights_fragment_end>\n\treflectedLight.indirectDiffuse += toonFill * BRDF_Lambert( material.diffuseColor );')
}

/** A toon copy that also runs the authored material's shader patches (speech faces, materialization). */
export function toonMaterialFor(source: LitMaterial, fill: ToonFill = { value: new Color(0) }): MeshToonMaterial {
  const toon = new MeshToonMaterial()
  toon.onBeforeCompile = (shader, renderer) => {
    source.onBeforeCompile(shader, renderer)
    withEnvironmentFill(shader, fill)
  }
  toon.customProgramCacheKey = () => `toon-fill:${source.customProgramCacheKey()}`
  mirror(source, toon)
  return toon
}

function weldedPositions(geometry: BufferGeometry): { ids: Int32Array; count: number } {
  const position = geometry.getAttribute('position')
  if (!geometry.boundingBox) geometry.computeBoundingBox()
  const size = geometry.boundingBox!.getSize(new Vector3())
  const step = Math.max(size.x, size.y, size.z, 1e-6) * 1e-5
  const ids = new Int32Array(position.count)
  const seen = new Map<string, number>()
  for (let i = 0; i < position.count; i += 1) {
    const key = `${Math.round(position.getX(i) / step)},${Math.round(position.getY(i) / step)},${Math.round(position.getZ(i) / step)}`
    let id = seen.get(key)
    if (id === undefined) { id = seen.size; seen.set(key, id) }
    ids[i] = id
  }
  return { ids, count: seen.size }
}

const corner = [new Vector3(), new Vector3(), new Vector3()]
const edgeA = new Vector3(), edgeB = new Vector3(), face = new Vector3()

/** Face normals summed per welded position, each weighted by the angle of its corner there, so how a face was cut
 * into triangles does not tilt the result. */
function faceNormalSums(geometry: BufferGeometry, ids: Int32Array, count: number): Float32Array {
  const position = geometry.getAttribute('position')
  const index = geometry.getIndex()
  const sums = new Float32Array(count * 3)
  const corners = index ? index.count : position.count
  for (let t = 0; t + 2 < corners; t += 3) {
    const vertices = [0, 1, 2].map(k => index ? index.getX(t + k) : t + k)
    vertices.forEach((vertex, k) => corner[k].fromBufferAttribute(position, vertex))
    face.subVectors(corner[2], corner[1]).cross(edgeA.subVectors(corner[0], corner[1]))
    if (face.lengthSq() === 0) continue
    face.normalize()
    for (let k = 0; k < 3; k += 1) {
      const angle = edgeA.subVectors(corner[(k + 1) % 3], corner[k]).angleTo(edgeB.subVectors(corner[(k + 2) % 3], corner[k]))
      const at = ids[vertices[k]] * 3
      sums[at] += face.x * angle; sums[at + 1] += face.y * angle; sums[at + 2] += face.z * angle
    }
  }
  return sums
}

/** One normal per position, averaged over every face that touches it. Hard edges and UV seams split vertices,
 * and a hull pushed along split normals tears open at them. Stored once on the shared geometry. */
export function outlineNormals(geometry: BufferGeometry): BufferAttribute {
  const existing = geometry.getAttribute(OUTLINE_NORMAL)
  if (existing instanceof BufferAttribute) return existing
  const { ids, count } = weldedPositions(geometry)
  const sums = faceNormalSums(geometry, ids, count)
  const normal = geometry.getAttribute('normal')
  const normals = new Float32Array(ids.length * 3)
  for (let i = 0; i < ids.length; i += 1) {
    const at = ids[i] * 3
    const length = Math.hypot(sums[at], sums[at + 1], sums[at + 2])
    if (length > 0) normals.set([sums[at] / length, sums[at + 1] / length, sums[at + 2] / length], i * 3)
    else if (normal) normals.set([normal.getX(i), normal.getY(i), normal.getZ(i)], i * 3)
    else normals[i * 3 + 1] = 1
  }
  const attribute = new BufferAttribute(normals, 3)
  geometry.setAttribute(OUTLINE_NORMAL, attribute)
  return attribute
}

export const INK_VERTEX = /* glsl */`
#include <common>
#include <fog_pars_vertex>
#include <morphtarget_pars_vertex>
#include <skinning_pars_vertex>
#include <logdepthbuf_pars_vertex>
attribute vec3 ${OUTLINE_NORMAL};
uniform float inkWidth;
varying float inkFacing;
void main() {
  #include <morphinstance_vertex>
  vec3 objectNormal = ${OUTLINE_NORMAL};
  #include <morphnormal_vertex>
  #include <skinbase_vertex>
  #include <skinnormal_vertex>
  #include <begin_vertex>
  #include <morphtarget_vertex>
  #include <skinning_vertex>
  #include <project_vertex>
  mvPosition.xyz *= 1.0 + ${INK_DEPTH};
  gl_Position = projectionMatrix * mvPosition;
  vec3 viewNormal = normalize(normalMatrix * objectNormal);
  inkFacing = dot(viewNormal, normalize(-mvPosition.xyz));
  // Push the hull out across the screen: the same width for any model scale or frame size.
  float aspect = projectionMatrix[1][1] / projectionMatrix[0][0];
  vec2 across = (projectionMatrix * vec4(viewNormal, 0.0)).xy * vec2(aspect, 1.0);
  float span = length(across);
  if (span > 1e-5) {
    float reach = clamp(${INK_REACH.toFixed(1)} / max(gl_Position.w, 1e-3), ${INK_FLOOR}, 1.0);
    gl_Position.xy += across / span * vec2(1.0 / aspect, 1.0) * inkWidth * reach * gl_Position.w;
  }
  #include <logdepthbuf_vertex>
  #include <fog_vertex>
}`

export const INK_FRAGMENT = /* glsl */`
uniform vec3 inkColor;
varying float inkFacing;
#include <common>
#include <fog_pars_fragment>
#include <logdepthbuf_pars_fragment>
void main() {
  if (inkFacing < ${INK_AWAY.toFixed(2)}) discard;
  #include <logdepthbuf_fragment>
  gl_FragColor = vec4(inkColor, 1.0);
  #include <tonemapping_fragment>
  #include <colorspace_fragment>
  #include <fog_fragment>
}`

export function inkMaterial(): ShaderMaterial {
  return new ShaderMaterial({
    name: 'toon-ink',
    uniforms: UniformsUtils.merge([UniformsLib.fog, { inkColor: { value: new Color(DEFAULT_TOON.ink) }, inkWidth: { value: 0 } }]),
    vertexShader: INK_VERTEX,
    fragmentShader: INK_FRAGMENT,
    side: BackSide,
    fog: true,
  })
}

const HULLS = new WeakSet<Object3D>()

export function isInkHull(object: Object3D): boolean {
  return HULLS.has(object)
}

/** A mesh drawn with the same geometry (and skeleton) as `mesh`, attached as its child only while drawing. */
export function inkHull(mesh: Mesh): Mesh {
  outlineNormals(mesh.geometry)
  const skinned = mesh as SkinnedMesh
  const hull = skinned.isSkinnedMesh ? new SkinnedMesh(mesh.geometry) : new Mesh(mesh.geometry)
  hull.name = `${mesh.name || 'mesh'}:toon-ink`
  hull.castShadow = false
  hull.receiveShadow = false
  hull.frustumCulled = false
  hull.raycast = () => {}
  HULLS.add(hull)
  return hull
}

function followMesh(hull: Mesh, mesh: Mesh) {
  hull.morphTargetInfluences = mesh.morphTargetInfluences
  hull.morphTargetDictionary = mesh.morphTargetDictionary
  hull.renderOrder = mesh.renderOrder
  hull.layers.mask = mesh.layers.mask
  const source = mesh as SkinnedMesh, skinned = hull as SkinnedMesh
  if (!source.isSkinnedMesh || !skinned.isSkinnedMesh) return
  skinned.bindMode = source.bindMode
  if (skinned.skeleton !== source.skeleton || !skinned.bindMatrix.equals(source.bindMatrix)) skinned.bind(source.skeleton, source.bindMatrix)
}

/** three flat-shades PBR, Lambert and Phong materials whose geometry has no normals (GLTFLoader leaves Hunyuan3D
 * meshes so), but not toon materials: their normal would be zero and the light NaN, which bloom then spreads over
 * the whole frame. Such a geometry borrows the welded outline normals for the draw; returns it to take them back. */
function lendNormals(geometry: BufferGeometry): BufferGeometry | undefined {
  if (geometry.getAttribute('normal')) return undefined
  geometry.setAttribute('normal', outlineNormals(geometry))
  return geometry
}

type Converted = { toon: MeshToonMaterial; key: string; pass: number }
type Swap = { mesh: Mesh; material: Mesh['material']; hull?: Mesh; normals?: BufferGeometry }

export class ToonLook {
  private settings: ToonSettings | null = null
  private targets: readonly ToonTarget[] = []
  private gradient?: { steps: number; texture: DataTexture }
  private converted = new Map<Material, Converted>()
  private hulls = new Map<Mesh, { hull: Mesh; pass: number }>()
  private ink?: ShaderMaterial
  private hidden?: MeshBasicMaterial
  private pass = 0
  private fill: ToonFill = { value: new Color(0) }

  /** Settings and model roots for the next draws; null switches the look off and frees what it created.
   * `environment` is the scene's environment light intensity (0 without one), given back to toon surfaces as fill. */
  sync(settings: ToonSettings | null, targets: readonly ToonTarget[], environment = 0) {
    this.settings = settings
    this.targets = settings ? targets : []
    this.fill.value.setScalar(environmentFill(environment))
    if (!settings) this.dispose()
  }

  /** Render with toon materials and ink hulls in place, then give every mesh its authored material back. */
  draw(render: () => void) {
    const settings = this.settings
    if (!settings) { render(); return }
    this.pass += 1
    const swaps = this.swapIn(settings)
    try {
      render()
    } finally {
      for (const swap of swaps) {
        swap.mesh.material = swap.material
        swap.hull?.removeFromParent()
        swap.normals?.deleteAttribute('normal')
      }
      this.sweep()
    }
  }

  dispose() {
    for (const entry of this.converted.values()) entry.toon.dispose()
    this.converted.clear()
    this.hulls.clear()
    this.ink?.dispose(); this.ink = undefined
    this.hidden?.dispose(); this.hidden = undefined
    this.gradient?.texture.dispose(); this.gradient = undefined
  }

  private swapIn(settings: ToonSettings): Swap[] {
    const meshes: { mesh: Mesh; outline: boolean }[] = []
    for (const target of this.targets) {
      target.root.traverse(object => {
        if ((object as Mesh).isMesh && !HULLS.has(object)) meshes.push({ mesh: object as Mesh, outline: target.outline && settings.outline > 0 })
      })
    }
    const swaps: Swap[] = []
    for (const { mesh, outline } of meshes) {
      const material = mesh.material
      const toon = Array.isArray(material) ? material.map(item => this.convert(item, settings)) : this.convert(material, settings)
      const hull = outline ? this.attachHull(mesh, material, settings) : undefined
      const changed = Array.isArray(toon) ? toon.some((item, index) => item !== (material as Material[])[index]) : toon !== material
      if (!changed && !hull) continue
      mesh.material = toon
      swaps.push({ mesh, material, hull, normals: changed ? lendNormals(mesh.geometry) : undefined })
    }
    return swaps
  }

  private convert(source: Material, settings: ToonSettings): Material {
    if (!isLitMaterial(source)) return source
    let entry = this.converted.get(source)
    if (!entry) {
      entry = { toon: toonMaterialFor(source, this.fill), key: programKey(source), pass: 0 }
      this.converted.set(source, entry)
    }
    if (entry.pass !== this.pass) {
      entry.pass = this.pass
      mirror(source, entry.toon)
      entry.toon.gradientMap = this.gradientFor(settings.steps)
      const key = programKey(source)
      if (key !== entry.key) { entry.key = key; entry.toon.needsUpdate = true }
    }
    return entry.toon
  }

  private attachHull(mesh: Mesh, material: Mesh['material'], settings: ToonSettings): Mesh | undefined {
    const skinned = mesh as Mesh & { isInstancedMesh?: boolean; isBatchedMesh?: boolean }
    if (skinned.isInstancedMesh || skinned.isBatchedMesh) return undefined
    const materials = Array.isArray(material) ? material : [material]
    const inked = materials.map(inkable)
    if (!inked.some(Boolean)) return undefined
    let entry = this.hulls.get(mesh)
    if (!entry || entry.hull.geometry !== mesh.geometry || Boolean((entry.hull as SkinnedMesh).isSkinnedMesh) !== Boolean((mesh as SkinnedMesh).isSkinnedMesh)) {
      entry = { hull: inkHull(mesh), pass: 0 }
      this.hulls.set(mesh, entry)
    }
    entry.pass = this.pass
    const ink = this.inkFor(settings)
    entry.hull.material = Array.isArray(material) ? inked.map(ok => ok ? ink : this.hiddenMaterial()) : ink
    followMesh(entry.hull, mesh)
    mesh.add(entry.hull)
    return entry.hull
  }

  private inkFor(settings: ToonSettings): ShaderMaterial {
    this.ink ??= inkMaterial()
    this.ink.uniforms.inkWidth.value = settings.outline / REFERENCE_HALF_HEIGHT
    ;(this.ink.uniforms.inkColor.value as Color).set(settings.ink)
    return this.ink
  }

  private hiddenMaterial(): MeshBasicMaterial {
    this.hidden ??= new MeshBasicMaterial({ visible: false })
    return this.hidden
  }

  private gradientFor(steps: number): DataTexture {
    if (this.gradient?.steps !== steps) {
      this.gradient?.texture.dispose()
      this.gradient = { steps, texture: toonGradient(steps) }
    }
    return this.gradient.texture
  }

  /** Free the toon copies of materials and the hulls of meshes that were not drawn this time. */
  private sweep() {
    for (const [source, entry] of this.converted) {
      if (entry.pass === this.pass) continue
      entry.toon.dispose()
      this.converted.delete(source)
    }
    for (const [mesh, entry] of this.hulls) if (entry.pass !== this.pass) this.hulls.delete(mesh)
  }
}
