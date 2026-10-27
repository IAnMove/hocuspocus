/** A 2D Character Kit painted as a cap on a model's head.

The cap is a partial sphere in model space, parented to the Head bone with that bone's
bind inverse, so it follows the head and still faces the model's +Z. The toon look
skips it: the drawing stays flat, with a slight warm tint and no ink hull.
*/
import {
  Bone,
  CanvasTexture,
  FrontSide,
  Matrix4,
  Mesh,
  MeshBasicMaterial,
  MeshStandardMaterial,
  PlaneGeometry,
  Quaternion,
  SphereGeometry,
  SRGBColorSpace,
  Vector3,
  type Object3D,
  type Texture,
  type SkinnedMesh,
} from 'three'
import type { CharacterKit } from '../../lib/characterKit'
import { CHARACTER_MOUTH_STATES } from '../../lib/characterMouthStates'
import { durableScene3DSourceUrl } from './slotSource'
import { useMapUv } from './atlasProjection'
import {
  loadTalkingCutout,
  parseAnchor,
  parseTalkingCutout,
  type CutoutAnchor,
  type TalkCue,
  type TalkingCutout,
} from './talkingCutout'

/** Horizontal sweep of the cap, centred on model +Z. Wide enough that a ±30° orbit still meets the head. */
export const FACE_CAP_SPAN = 80 * Math.PI / 180
/** The same sweep upwards and downwards, centred on the equator, unless the decal gives its own `span`. */
export const FACE_DECAL_OUTSET = 1.04
/** A plane face: width and height in head radii, then how far up its centre sits from the head centre, also in radii.
A painted head fills its square picture with hair above and a neck below, so the picture is wider than the skull and its centre lower. */
export const FACE_PLANE_DEFAULT: readonly [number, number, number] = [3.3, 3.3, -0.5]
const CANVAS = 1024
const MOUTH_FALLBACK: CutoutAnchor = { offsetX: 0, offsetY: 0, scale: 0.16, rotation: 0 }
const EYE_FALLBACK: CutoutAnchor = { offsetX: 0, offsetY: 0, scale: 1, rotation: 0 }

const MARKED = new WeakSet<Object3D>()

export function markFaceDecal(object: Object3D) {
  MARKED.add(object)
  object.userData.faceDecal = true
}

export function isFaceDecal(object: Object3D): boolean {
  return MARKED.has(object) || object.userData?.faceDecal === true
}

export type FacePoseArt = { base: string; mouth: CutoutAnchor; eyes: CutoutAnchor; blink?: string }
export type FaceDecalArt = {
  poses: Record<string, FacePoseArt>
  mouths: Record<string, string>
  rest: string
  cues?: TalkCue[]
  blinks?: number[]
}
export type FaceExpressionCue = { start: number; pose: string }
export type Scene3DFaceDecal = {
  kitId: string
  pose?: string
  center?: [number, number, number]
  radii?: [number, number, number]
  /** How far the cap sits outside the head, from 1 to 1.2. Distinct from a faceAnchor diameter. */
  size?: number
  /** Degrees of head the face covers, horizontal then vertical (default 80 x 80). */
  span?: [number, number]
  /** `plane`: a flat picture on the head (a painted head with its hair) instead of the cap; `mesh`: the picture is painted
  into the model's own `face` material (a lofted head carries that primitive with UVs), lit like the body. Default `cap`. */
  shape?: 'cap' | 'plane' | 'mesh'
  /** `mesh` only: the skin colour filled under the drawing (the face primitive is opaque). */
  skin?: string
  /** The plane's width, height and lift in head radii (default `FACE_PLANE_DEFAULT`). */
  plane?: [number, number, number]
  /** Jaw of the egg head the cap hugs: how much the radius narrows toward the chin (0 is a sphere, 0.35 the lofted anime head). */
  taper?: number
  /** Frontal projection of the kit picture: the drawn skull's centre and half-size as image fractions `[cu, cv, ru, rv]`.
  The cap then covers 200 x 180 degrees, each vertex takes the pixel in front of it, and rows below the chin stay transparent. */
  fit?: [number, number, number, number]
  bone: string
  expressions?: FaceExpressionCue[]
  art?: FaceDecalArt
}

export function poseAt(decal: { pose?: string; expressions?: readonly FaceExpressionCue[] }, seconds: number): string {
  let pose = decal.pose || 'neutral'
  const cues = [...(decal.expressions ?? [])].filter(item => Number.isFinite(item.start)).sort((a, b) => a.start - b.start)
  for (const cue of cues) if (cue.start <= seconds) pose = cue.pose
  return pose
}

/** The same cutout `world3d.scene.talk` paints, built from the art stored on the document. */
export function cutoutOf(art: FaceDecalArt, pose: string): TalkingCutout | undefined {
  const drawn = art.poses[pose] || art.poses.neutral || art.poses.base || Object.values(art.poses)[0]
  if (!drawn) return undefined
  const blink = drawn.blink ? { source: drawn.blink, anchor: drawn.eyes } : undefined
  return parseTalkingCutout({
    base: drawn.base, mouths: art.mouths, mouth: drawn.mouth, rest: art.rest, cues: art.cues ?? [],
    ...(blink ? { blink } : {}), blinks: art.blinks ?? [],
  })
}

function approvedSource(asset?: { reviewState?: string; source?: string }): string {
  return asset?.reviewState === 'approved' && asset.source ? asset.source : ''
}

/** What the server stores on `faceDecal.art`. Undefined when the kit cannot be painted. */
export function artFromKit(kit: Pick<CharacterKit, 'base' | 'poses' | 'mouth' | 'eyes' | 'anchors' | 'mouthMapping'>): FaceDecalArt | undefined {
  const mouths: Record<string, string> = {}
  for (const state of CHARACTER_MOUTH_STATES) {
    const source = approvedSource(kit.mouth[state])
    if (!source) return undefined
    mouths[state] = source
  }
  const poses: Record<string, FacePoseArt> = {}
  const add = (name: string, asset?: CharacterKit['base']) => {
    const base = approvedSource(asset)
    if (!base) return
    const group = kit.anchors[name] ?? kit.anchors.base
    const blink = group?.blink === false ? '' : (group?.blinkSource || kit.eyes.blink?.source || '')
    poses[name] = { base, mouth: group?.mouth ?? MOUTH_FALLBACK, eyes: group?.eyes ?? EYE_FALLBACK, ...(blink ? { blink } : {}) }
  }
  add('base', kit.base)
  for (const [name, asset] of Object.entries(kit.poses || {})) add(name, asset)
  if (!Object.keys(poses).length) return undefined
  const mapped = kit.mouthMapping?.rest
  return { poses, mouths, rest: mapped && mouths[mapped] ? mapped : 'closed' }
}

/** The span a projected (`fit`) cap covers: past the ears and from the crown to under the chin. */
export const FACE_FIT_SPAN: readonly [number, number] = [200, 180]
/** A transparent pixel of a keyed head picture: its top-left corner. */
const FIT_OUTSIDE: readonly [number, number] = [0, 1]

/** The jaw of the lofted anime head (`blob_loft.egg_scale`): the radius share at a height `y` of the unit head. */
export function eggScale(y: number, taper: number): number {
  return 1 - taper * Math.max(0, -y) ** 2
}

/** Unit sphere cap. UVs cover the whole face image; default sphere UVs would show only a corner.
With `fit` the picture is projected from the front instead (`u = cu + x ru`, `v = 1 - cv + y rv`), rows below the chin
land on a transparent corner, and `taper` narrows the cap toward the chin like the egg head under it. */
export function faceCapGeometry(span?: readonly [number, number], taper = 0, fit?: readonly [number, number, number, number]): SphereGeometry {
  const extent = fit ? FACE_FIT_SPAN : span
  const wide = extent ? extent[0] * Math.PI / 180 : FACE_CAP_SPAN
  const tall = extent ? extent[1] * Math.PI / 180 : FACE_CAP_SPAN
  const phiStart = Math.PI / 2 - wide / 2
  const thetaStart = Math.PI / 2 - tall / 2
  const geometry = new SphereGeometry(1, 48, 24, phiStart, wide, thetaStart, tall)
  const position = geometry.getAttribute('position')
  const uv = geometry.getAttribute('uv')
  for (let index = 0; index < position.count; index += 1) {
    const x = position.getX(index), y = position.getY(index), z = position.getZ(index)
    if (fit) {
      const [cu, cv, ru, rv] = fit
      const imageX = cu + x * ru
      const imageY = cv - y * rv
      const inside = imageX >= 0 && imageX <= 1 && imageY >= 0 && imageY <= cv + rv
      if (inside) uv.setXY(index, imageX, 1 - imageY)
      else uv.setXY(index, FIT_OUTSIDE[0], FIT_OUTSIDE[1])
    } else {
      const theta = Math.acos(Math.min(1, Math.max(-1, y)))
      let u = 0.5
      if (Math.sin(theta) > 1e-4) {
        const phi = Math.atan2(z, -x)
        u = (phi - phiStart) / wide
      }
      uv.setXY(index, u, 1 - (theta - thetaStart) / tall)
    }
    if (taper > 0) {
      const k = eggScale(y, taper)
      position.setXYZ(index, x * k, y, z * k)
    }
  }
  uv.needsUpdate = true
  if (taper > 0) { position.needsUpdate = true; geometry.computeVertexNormals() }
  return geometry
}

/** Unit square facing +Z. Its UVs already cover the whole picture. */
export function facePlaneGeometry(): PlaneGeometry {
  return new PlaneGeometry(1, 1)
}

/** The plane sits `outset` head radii in front of the head centre, lifted by `plane[2]` radii, `plane[0]` x `plane[1]` radii big. */
export function placeFacePlane(mesh: Object3D, boneInverse: Matrix4, center: readonly number[], radii: readonly number[], outset = FACE_DECAL_OUTSET, plane: readonly [number, number, number] = FACE_PLANE_DEFAULT) {
  const inverse = boneInverse.clone()
  const position = new Vector3(center[0], center[1] + radii[1] * plane[2], center[2] + radii[2] * outset).applyMatrix4(inverse)
  const quaternion = new Quaternion()
  const scale = new Vector3()
  inverse.decompose(new Vector3(), quaternion, scale)
  mesh.position.copy(position)
  mesh.quaternion.copy(quaternion)
  mesh.scale.set(radii[0] * plane[0] * scale.x, radii[1] * plane[1] * scale.y, scale.z)
}

/** `boneInverse` maps model space into the bone. The mesh is then parented to that bone. */
export function placeFaceCap(mesh: Object3D, boneInverse: Matrix4, center: readonly number[], radii: readonly number[], outset = FACE_DECAL_OUTSET) {
  const inverse = boneInverse.clone()
  const position = new Vector3(center[0], center[1], center[2]).applyMatrix4(inverse)
  const quaternion = new Quaternion()
  const scale = new Vector3()
  inverse.decompose(new Vector3(), quaternion, scale)
  mesh.position.copy(position)
  mesh.quaternion.copy(quaternion)
  mesh.scale.set(radii[0] * outset * scale.x, radii[1] * outset * scale.y, radii[2] * outset * scale.z)
}

/** Exact name, then a `:` or `_` suffix, then a camelCase boundary. `overhead` is not a head. */
export function boneMatches(name: string, wanted: string): boolean {
  if (name === wanted) return true
  if (name.length <= wanted.length || !name.toLowerCase().endsWith(wanted.toLowerCase())) return false
  const before = name[name.length - wanted.length - 1]
  const first = name[name.length - wanted.length]
  const capital = first === first.toUpperCase() && first !== first.toLowerCase()
  return before === ':' || before === '_' || (before === before.toLowerCase() && capital)
}

/** The material named `face` on the model (a lofted head's own face primitive), if any. */
export function findFaceMaterial(root: Object3D): MeshStandardMaterial | undefined {
  let found: MeshStandardMaterial | undefined
  root.traverse(object => {
    if (found || !(object as Mesh).isMesh) return
    const material = (object as Mesh).material
    for (const item of Array.isArray(material) ? material : [material]) {
      if (item && item.name === 'face') { found = item as MeshStandardMaterial; return }
    }
  })
  return found
}

export function findBone(root: Object3D, wanted: string): Bone | undefined {
  const bones: Bone[] = []
  root.traverse(object => { if ((object as Bone).isBone) bones.push(object as Bone) })
  return bones.find(bone => bone.name === wanted) ?? bones.find(bone => boneMatches(bone.name, wanted))
}

/** glTF inverse bind matrix, or the first-frame bone matrix relative to the model root. */
export function bindInverse(root: Object3D, bone: Bone): Matrix4 {
  let inverse: Matrix4 | undefined
  root.traverse(object => {
    if (inverse) return
    const skin = object as SkinnedMesh
    if (!skin.isSkinnedMesh) return
    const index = skin.skeleton.bones.indexOf(bone)
    if (index >= 0) inverse = skin.skeleton.boneInverses[index]
  })
  if (inverse) return inverse.clone()
  root.updateMatrixWorld(true)
  return new Matrix4().copy(bone.matrixWorld).invert().multiply(root.matrixWorld)
}

function finiteTriple(value: unknown, positive: boolean): [number, number, number] | undefined {
  if (!Array.isArray(value) || value.length !== 3) return undefined
  const numbers = value.map(item => typeof item === 'number' && Number.isFinite(item) ? item : Number.NaN)
  if (numbers.some(item => Number.isNaN(item))) return undefined
  if (positive && numbers.some(item => item <= 0 || item > 5)) return undefined
  if (!positive && numbers.some(item => Math.abs(item) > 50)) return undefined
  return [numbers[0], numbers[1], numbers[2]]
}

function poseArt(value: unknown): FacePoseArt | undefined {
  if (!value || typeof value !== 'object') return undefined
  const raw = value as Record<string, unknown>
  const base = durableScene3DSourceUrl(String(raw.base ?? ''))
  const mouth = parseAnchor(raw.mouth)
  if (!base || !mouth) return undefined
  const blink = durableScene3DSourceUrl(String(raw.blink ?? ''))
  return { base, mouth, eyes: parseAnchor(raw.eyes) ?? EYE_FALLBACK, ...(blink ? { blink } : {}) }
}

function artOf(value: unknown): FaceDecalArt | undefined {
  if (!value || typeof value !== 'object') return undefined
  const raw = value as Record<string, unknown>
  const poses = Object.fromEntries(Object.entries((raw.poses ?? {}) as Record<string, unknown>)
    .map(([name, pose]) => [name, poseArt(pose)] as const)
    .filter((entry): entry is readonly [string, FacePoseArt] => Boolean(entry[1])))
  const mouths = Object.fromEntries(Object.entries((raw.mouths ?? {}) as Record<string, unknown>)
    .map(([state, url]) => [state, durableScene3DSourceUrl(String(url ?? ''))] as const)
    .filter(([, url]) => url))
  if (!Object.keys(poses).length || !Object.keys(mouths).length) return undefined
  const rest = typeof raw.rest === 'string' && mouths[raw.rest] ? raw.rest : Object.keys(mouths)[0]
  const cues: TalkCue[] = []
  for (const item of Array.isArray(raw.cues) ? raw.cues : []) {
    if (!item || typeof item !== 'object') continue
    const cue = item as { start?: unknown; end?: unknown; state?: unknown }
    if (typeof cue.state !== 'string' || typeof cue.start !== 'number' || typeof cue.end !== 'number') continue
    cues.push({ start: cue.start, end: cue.end, state: cue.state })
    if (cues.length >= 10000) break
  }
  const blinks = (Array.isArray(raw.blinks) ? raw.blinks : []).filter((time): time is number => typeof time === 'number' && time >= 0 && time <= 3600).slice(0, 2000)
  return { poses, mouths, rest, ...(cues.length ? { cues } : {}), ...(blinks.length ? { blinks } : {}) }
}

function expressionsOf(value: unknown): FaceExpressionCue[] {
  if (!Array.isArray(value)) return []
  const found: FaceExpressionCue[] = []
  for (const item of value) {
    if (!item || typeof item !== 'object') continue
    const cue = item as { pose?: unknown; start?: unknown }
    if (typeof cue.pose !== 'string' || cue.pose.length === 0 || cue.pose.length > 80) continue
    if (typeof cue.start !== 'number' || cue.start < 0 || cue.start > 600) continue
    found.push({ start: cue.start, pose: cue.pose })
    if (found.length >= 32) break
  }
  return found.sort((a, b) => a.start - b.start)
}

/** Drop a bad face instead of rejecting the whole scene document. */
function spanOf(raw: unknown): [number, number] | undefined {
  if (!Array.isArray(raw) || raw.length !== 2) return undefined
  const [wide, tall] = raw
  const ok = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v) && v >= 60 && v <= 150
  return ok(wide) && ok(tall) ? [Math.round(wide * 100) / 100, Math.round(tall * 100) / 100] : undefined
}

function planeOf(raw: unknown): [number, number, number] | undefined {
  if (!Array.isArray(raw) || raw.length < 2 || raw.length > 3) return undefined
  const [wide, tall, lift = FACE_PLANE_DEFAULT[2]] = raw
  const size = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v) && v >= 1 && v <= 8
  const ok = size(wide) && size(tall) && typeof lift === 'number' && Number.isFinite(lift) && lift >= -3 && lift <= 3
  const round = (v: number) => Math.round(v * 1000) / 1000
  return ok ? [round(wide), round(tall), round(lift)] : undefined
}

function fitOf(raw: unknown): [number, number, number, number] | undefined {
  if (!Array.isArray(raw) || raw.length !== 4) return undefined
  const [cu, cv, ru, rv] = raw
  const unit = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v) && v >= 0 && v <= 1
  const ok = unit(cu) && unit(cv) && unit(ru) && unit(rv) && ru > 0 && rv > 0
  const round = (v: number) => Math.round(v * 10000) / 10000
  return ok ? [round(cu), round(cv), round(ru), round(rv)] : undefined
}

export function parseFaceDecal(raw: unknown): Scene3DFaceDecal | undefined {
  if (!raw || typeof raw !== 'object') return undefined
  const value = raw as Record<string, unknown>
  const kitId = typeof value.kitId === 'string' ? value.kitId.trim() : ''
  if (!kitId || kitId.length > 120) return undefined
  const bone = typeof value.bone === 'string' && value.bone.trim() ? value.bone.trim().slice(0, 80) : 'Head'
  const pose = typeof value.pose === 'string' && value.pose.trim() ? value.pose.trim().slice(0, 80) : undefined
  const center = finiteTriple(value.center, false)
  const radii = finiteTriple(value.radii, true)
  const size = typeof value.size === 'number' && value.size >= 1 && value.size <= 1.2 ? Math.round(value.size * 1000) / 1000 : undefined
  const span = spanOf(value.span)
  const shape = value.shape === 'plane' ? 'plane' : value.shape === 'mesh' ? 'mesh' : undefined
  const plane = shape === 'plane' ? planeOf(value.plane) ?? [...FACE_PLANE_DEFAULT] as [number, number, number] : undefined
  const skin = typeof value.skin === 'string' && /^#[0-9a-fA-F]{6}$/.test(value.skin) ? value.skin : undefined
  const taper = typeof value.taper === 'number' && Number.isFinite(value.taper) && value.taper > 0 && value.taper <= 0.6 ? Math.round(value.taper * 1000) / 1000 : undefined
  const fit = fitOf(value.fit)
  const expressions = expressionsOf(value.expressions)
  const art = artOf(value.art)
  return {
    kitId, bone, ...(pose ? { pose } : {}), ...(center ? { center } : {}), ...(radii ? { radii } : {}),
    ...(size !== undefined ? { size } : {}), ...(span ? { span } : {}), ...(shape === 'plane' ? { shape, plane } : shape ? { shape } : {}),
    ...(skin ? { skin } : {}),
    ...(taper !== undefined ? { taper } : {}), ...(fit ? { fit } : {}),
    ...(expressions.length ? { expressions } : {}), ...(art ? { art } : {}),
  }
}

function capKey(decal: Scene3DFaceDecal): string {
  return `${(decal.span ?? []).join()}|${decal.taper ?? ''}|${(decal.fit ?? []).join()}`
}

type Painter = {
  paint: (context: CanvasRenderingContext2D, screen: { talk?: TalkingCutout } | undefined, seconds: number) => void
  dispose: () => void
}

export class FaceDecalRuntime {
  ready = false
  error?: Error
  private mesh?: Mesh
  private faceMaterial?: MeshStandardMaterial
  private spanKey = ''
  private texture?: CanvasTexture
  private context?: CanvasRenderingContext2D
  private originalMap?: Texture | null
  private painters = new Map<string, Painter>()
  private abort?: AbortController
  private artKey = ''
  private placeKey = ''
  private requestRender: () => void

  constructor(requestRender: () => void) { this.requestRender = requestRender }

  sync(root: Object3D, decal: Scene3DFaceDecal | undefined, seconds: number) {
    if (!decal) { this.error = undefined; this.detach(); return }
    if (decal.shape === 'mesh') {
      if (!decal.art) { this.error = new Error('A face needs art.'); this.ready = false; return }
      const face = findFaceMaterial(root)
      if (!face) { this.error = new Error('No face material on the model to paint the face into.'); this.ready = false; return }
      this.error = undefined
      this.mountMaterial(face)
      // a kit made from a photograph has no skin colour: its keyed edges are cut out so the skull's own picture (hair, skin) shows through
      const cut = decal.skin ? 0 : 0.5
      if (face.alphaTest !== cut) { face.alphaTest = cut; face.needsUpdate = true }
      this.watch(decal)
      this.paint(decal, seconds)
      return
    }
    if (!decal.art || !decal.center || !decal.radii) {
      this.error = new Error('A 2D face needs a center, radii and art.')
      this.ready = false
      this.detach()
      return
    }
    const bone = findBone(root, decal.bone || 'Head')
    if (!bone) {
      this.error = new Error(`No ${decal.bone || 'Head'} bone to hang the 2D face on.`)
      this.ready = false
      return
    }
    this.error = undefined
    this.mount(root, bone, decal)
    this.watch(decal)
    this.paint(decal, seconds)
  }

  private mount(root: Object3D, bone: Bone, decal: Scene3DFaceDecal) {
    const plane = decal.shape === 'plane'
    const key = `${bone.uuid}|${decal.center!.join()}|${decal.radii!.join()}|${decal.size ?? FACE_DECAL_OUTSET}|${plane ? (decal.plane ?? FACE_PLANE_DEFAULT).join() : ''}`
    if (!this.mesh) this.mesh = this.createMesh(decal)
    if (!this.mesh) return
    const spanKey = plane ? 'plane' : capKey(decal)
    if (spanKey !== this.spanKey) {
      this.spanKey = spanKey
      this.mesh.geometry.dispose()
      this.mesh.geometry = plane ? facePlaneGeometry() : faceCapGeometry(decal.span, decal.taper ?? 0, decal.fit)
      const material = this.mesh.material as MeshBasicMaterial
      material.color.set(plane ? 0xffffff : 0xfff6f0)
    }
    if (this.placeKey === key && this.mesh.parent === bone) return
    const inverse = bindInverse(root, bone)
    this.placeKey = key
    if (plane) placeFacePlane(this.mesh, inverse, decal.center!, decal.radii!, decal.size ?? FACE_DECAL_OUTSET, decal.plane ?? FACE_PLANE_DEFAULT)
    else placeFaceCap(this.mesh, inverse, decal.center!, decal.radii!, decal.size ?? FACE_DECAL_OUTSET)
    bone.add(this.mesh)
  }

  /** The picture becomes the model's own face material's map: lit by the scene, outlined with the head. */
  private mountMaterial(face: MeshStandardMaterial) {
    if (!this.texture) {
      const canvas = document.createElement('canvas')
      canvas.width = CANVAS
      canvas.height = CANVAS
      const context = canvas.getContext('2d')
      if (!context) { this.error = new Error('The 2D face canvas is unavailable.'); return }
      this.context = context
      this.texture = new CanvasTexture(canvas)
      this.texture.colorSpace = SRGBColorSpace
    }
    if (this.faceMaterial !== face) {
      this.faceMaterial = face
      this.originalMap = face.map
      useMapUv(face, true)
      face.map = this.texture
      face.transparent = false
      face.needsUpdate = true
    }
  }

  private createMesh(decal: Scene3DFaceDecal): Mesh | undefined {
    const plane = decal.shape === 'plane'
    const canvas = document.createElement('canvas')
    canvas.width = CANVAS
    canvas.height = CANVAS
    const context = canvas.getContext('2d')
    if (!context) { this.error = new Error('The 2D face canvas is unavailable.'); return undefined }
    this.context = context
    this.texture = new CanvasTexture(canvas)
    this.texture.colorSpace = SRGBColorSpace
    // The cap takes a slight warm tint on a flat drawing. A painted head keeps its own colours.
    const material = new MeshBasicMaterial({
      map: this.texture, color: plane ? 0xffffff : 0xfff6f0, transparent: true, alphaTest: 0.04, side: FrontSide, toneMapped: false,
      polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2,
    })
    this.spanKey = plane ? 'plane' : capKey(decal)
    const mesh = new Mesh(plane ? facePlaneGeometry() : faceCapGeometry(decal.span, decal.taper ?? 0, decal.fit), material)
    mesh.name = 'blob-face'
    mesh.frustumCulled = false
    mesh.renderOrder = 2
    mesh.castShadow = false
    mesh.receiveShadow = false
    markFaceDecal(mesh)
    return mesh
  }

  private watch(decal: Scene3DFaceDecal) {
    const art = decal.art!
    const key = Object.entries(art.poses).map(([name, pose]) => `${name}=${pose.base}|${pose.blink ?? ''}`).join(';')
      + '#' + Object.entries(art.mouths).map(([state, url]) => `${state}=${url}`).join(',')
    if (key === this.artKey) return
    this.artKey = key
    this.ready = false
    this.abort?.abort()
    const abort = new AbortController()
    this.abort = abort
    void Promise.all(Object.keys(art.poses).map(async name => {
      const cutout = cutoutOf(art, name)
      if (!cutout) throw new Error(`The ${name} pose cannot be painted.`)
      return [name, await loadTalkingCutout(cutout, abort.signal)] as const
    })).then(loaded => {
      if (abort.signal.aborted) { for (const [, painter] of loaded) painter.dispose(); return }
      for (const painter of this.painters.values()) painter.dispose()
      this.painters = new Map(loaded)
      this.ready = this.painters.size > 0
      this.requestRender()
    }).catch((error: unknown) => {
      if (abort.signal.aborted) return
      this.ready = false
      this.error = error instanceof Error ? error : new Error(String(error))
      this.requestRender()
    })
  }

  private paint(decal: Scene3DFaceDecal, seconds: number) {
    const pose = poseAt(decal, seconds)
    const painter = this.painters.get(pose) || this.painters.get('neutral') || this.painters.get('base') || this.painters.values().next().value
    if (!painter || !this.context || !this.texture || !decal.art) return
    const live = cutoutOf(decal.art, pose)
    painter.paint(this.context, live ? { talk: live } : undefined, seconds)
    if (decal.shape === 'mesh' && decal.skin) {
      // the face primitive is opaque: the skin goes under the drawing
      const context = this.context
      context.save()
      context.globalCompositeOperation = 'destination-over'
      context.fillStyle = decal.skin
      context.fillRect(0, 0, CANVAS, CANVAS)
      context.restore()
    }
    this.texture.needsUpdate = true
  }

  private detach() {
    this.ready = false
    this.placeKey = ''
    this.mesh?.removeFromParent()
    if (this.faceMaterial) {
      this.faceMaterial.map = this.originalMap ?? null   // a draped atlas goes back to its picture
      useMapUv(this.faceMaterial, false)
      this.originalMap = undefined
      this.faceMaterial.needsUpdate = true
      this.faceMaterial = undefined
    }
  }

  dispose() {
    this.detach()
    this.abort?.abort()
    for (const painter of this.painters.values()) painter.dispose()
    this.painters.clear()
    this.texture?.dispose()
    this.mesh?.geometry.dispose()
    const material = this.mesh?.material
    if (material && !Array.isArray(material)) material.dispose()
    this.mesh?.removeFromParent()
    this.mesh = undefined
    this.ready = false
  }
}
