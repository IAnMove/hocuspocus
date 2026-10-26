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
  Quaternion,
  SphereGeometry,
  SRGBColorSpace,
  Vector3,
  type Object3D,
  type SkinnedMesh,
} from 'three'
import type { CharacterKit } from '../../lib/characterKit'
import { CHARACTER_MOUTH_STATES } from '../../lib/characterMouthStates'
import { durableScene3DSourceUrl } from './slotSource'
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
const PHI_START = Math.PI / 2 - FACE_CAP_SPAN / 2
/** The same sweep upwards and downwards, centred on the equator: the art keeps its proportions (80° wide, 80° tall). */
const THETA_START = Math.PI / 2 - FACE_CAP_SPAN / 2
export const FACE_DECAL_OUTSET = 1.04
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

/** Unit sphere cap. UVs cover the whole face image; default sphere UVs would show only a corner. */
export function faceCapGeometry(): SphereGeometry {
  const geometry = new SphereGeometry(1, 48, 24, PHI_START, FACE_CAP_SPAN, THETA_START, FACE_CAP_SPAN)
  const position = geometry.getAttribute('position')
  const uv = geometry.getAttribute('uv')
  for (let index = 0; index < position.count; index += 1) {
    const theta = Math.acos(Math.min(1, Math.max(-1, position.getY(index))))
    let u = 0.5
    if (Math.sin(theta) > 1e-4) {
      const phi = Math.atan2(position.getZ(index), -position.getX(index))
      u = (phi - PHI_START) / FACE_CAP_SPAN
    }
    uv.setXY(index, u, 1 - (theta - THETA_START) / FACE_CAP_SPAN)
  }
  uv.needsUpdate = true
  return geometry
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
  const expressions = expressionsOf(value.expressions)
  const art = artOf(value.art)
  return {
    kitId, bone, ...(pose ? { pose } : {}), ...(center ? { center } : {}), ...(radii ? { radii } : {}),
    ...(size !== undefined ? { size } : {}), ...(expressions.length ? { expressions } : {}), ...(art ? { art } : {}),
  }
}

type Painter = {
  paint: (context: CanvasRenderingContext2D, screen: { talk?: TalkingCutout } | undefined, seconds: number) => void
  dispose: () => void
}

export class FaceDecalRuntime {
  ready = false
  error?: Error
  private mesh?: Mesh
  private texture?: CanvasTexture
  private context?: CanvasRenderingContext2D
  private painters = new Map<string, Painter>()
  private abort?: AbortController
  private artKey = ''
  private placeKey = ''
  private requestRender: () => void

  constructor(requestRender: () => void) { this.requestRender = requestRender }

  sync(root: Object3D, decal: Scene3DFaceDecal | undefined, seconds: number) {
    if (!decal) { this.error = undefined; this.detach(); return }
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
    const key = `${bone.uuid}|${decal.center!.join()}|${decal.radii!.join()}|${decal.size ?? FACE_DECAL_OUTSET}`
    if (!this.mesh) this.mesh = this.createMesh()
    if (!this.mesh) return
    if (this.placeKey === key && this.mesh.parent === bone) return
    const inverse = bindInverse(root, bone)
    this.placeKey = key
    placeFaceCap(this.mesh, inverse, decal.center!, decal.radii!, decal.size ?? FACE_DECAL_OUTSET)
    bone.add(this.mesh)
  }

  private createMesh(): Mesh | undefined {
    const canvas = document.createElement('canvas')
    canvas.width = CANVAS
    canvas.height = CANVAS
    const context = canvas.getContext('2d')
    if (!context) { this.error = new Error('The 2D face canvas is unavailable.'); return undefined }
    this.context = context
    this.texture = new CanvasTexture(canvas)
    this.texture.colorSpace = SRGBColorSpace
    const material = new MeshBasicMaterial({
      map: this.texture, color: 0xfff6f0, transparent: true, alphaTest: 0.04, side: FrontSide, toneMapped: false,
      polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2,
    })
    const mesh = new Mesh(faceCapGeometry(), material)
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
    this.texture.needsUpdate = true
  }

  private detach() {
    this.ready = false
    this.placeKey = ''
    this.mesh?.removeFromParent()
  }

  dispose() {
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
