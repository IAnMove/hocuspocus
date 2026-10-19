import { cameraEyeAtTime, cameraLookAtTime } from './camera'
import type { Scene3DCameraFamily, Scene3DDocument, Scene3DFraming, Scene3DSlot, Vec3 } from './types.ts'

/** What a shot card tells an agent before the document is opened: how close the
 * camera is, what it does, what the template itself animates, who fits in it and
 * what it is good for. Everything is read from the built document, so the fields
 * are estimates of the authored scene, never hand-written claims. */
export const TEMPLATE_SHOT_SIZES = ['close', 'medium', 'wide', 'far', 'plate'] as const
export type TemplateShotSize = typeof TEMPLATE_SHOT_SIZES[number]

export const TEMPLATE_CAMERA_MOVES = ['push', 'pull', 'slide', 'rise', 'descend', 'arc', 'orbit', 'zoom', 'roll', 'ride', 'track', 'shake'] as const
export type TemplateCameraMove = typeof TEMPLATE_CAMERA_MOVES[number]

export const TEMPLATE_MOVING_PARTS = ['camera', 'subjects', 'props', 'screens', 'effects', 'backdrop', 'texts'] as const
export type TemplateMovingPart = typeof TEMPLATE_MOVING_PARTS[number]

export const TEMPLATE_USES = ['dialogue', 'talk', 'reaction', 'figure', 'establishing', 'action', 'speed', 'impact', 'reveal', 'product', 'music', 'drive', 'transition', 'title', 'look', 'plate'] as const
export type TemplateUse = typeof TEMPLATE_USES[number]

/** The shelf a card sits on: a finished scene, a room mold, a camera technique, a look, a cut piece or a title. */
export const TEMPLATE_KINDS = ['scene', 'stage', 'camera', 'look', 'transition', 'title'] as const
export type TemplateKind = typeof TEMPLATE_KINDS[number]

export type TemplateAuthoredFor = 'model' | 'cutout' | 'mixed' | 'none'

export type TemplateTraits = {
  kind: TemplateKind
  /** How much of a person the frame holds at mid-shot: `close` (head and shoulders or tighter), `medium` (to the waist), `wide` (whole figure), `far` (the figure under a third of the frame), `plate` (no subject slot). */
  shot: TemplateShotSize
  /** Metres from the camera to the subject at mid-shot, rounded; null for a plate. */
  distance: number | null
  /** What the camera does over the shot; empty when it holds still. */
  moves: TemplateCameraMove[]
  /** What the template itself animates. A bound GLB clip or a talking cutout adds to this. */
  moving: TemplateMovingPart[]
  /** True when `moving` is empty: only the cast's own clip or speech can move the picture. */
  still: boolean
  /** A subject slot walks a motion path: the figure crosses the set. */
  travel: boolean
  subjects: number
  props: number
  screens: number
  /** The media the subject slots were authored with. A production may still bind the other kind. */
  authoredFor: TemplateAuthoredFor
  floor: string
  uses: TemplateUse[]
}

export type TemplateTraitHints = {
  category?: string
  /** The technique family (`lighting`, `color`, `lenses`...) or the camera family. */
  family?: string
}

/** A model is drawn this tall at scale 1 (the production compiler's MODEL_HEIGHT). */
export const MODEL_HEIGHT = 1.7
/** The height of a figure below its head anchor. */
const BODY_BELOW_HEAD = 1.6
/** The frame holds this many figure heights at the top of each size. */
const SHOT_FRACTIONS: ReadonlyArray<[TemplateShotSize, number]> = [['close', 0.5], ['medium', 1.1], ['wide', 3.5]]
const LOOK_FAMILIES = new Set(['lighting', 'color', 'lenses', 'genre-looks', 'viral-looks', 'atmosphere'])
const CAMERA_FAMILIES = new Set(['camera-movement', 'framing', 'camera-angles', 'composition', 'editing', 'time-and-motion', 'effects'])
/** Camera families that ride a vehicle or run after one: never a conversation, always speed. */
const FAST_CAMERAS = new Set<Scene3DCameraFamily>(['chase', 'pursuit', 'hood', 'wing'])
const TRACKING_MOVES = new Set<TemplateCameraMove>(['track', 'ride', 'slide'])
/** A figure covering this many metres a second is running, riding or driving, not talking (the talks stay under 0.6). */
const RUN_PACE = 1
const EXPLOSIVE_FX = new Set(['explosion', 'shockwave', 'lightning', 'laser', 'energy_beam', 'fire', 'ice_burst'])
const SUBJECT_ROLES = new Set(['subject_1', 'subject_2'])
/** Dressings whose set moves on its own (endless roads and treadmills, procedural weather and water, pixel skies, native motion sets). */
const MOVING_DRESSINGS = new Set(['treadmill', 'open-sea', 'lunar', 'rooftop', 'hangar', 'train', 'space-lane'])
const MOVING_DRESSING_PREFIXES = ['atmos-', 'pixel-', 'drive-', 'motion-']

const length = (v: Vec3) => Math.hypot(v[0], v[1], v[2])
const sub = (a: Vec3, b: Vec3): Vec3 => [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
const dot = (a: Vec3, b: Vec3) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
const visibleHeight = (distance: number, fovDeg: number) => 2 * distance * Math.tan((fovDeg * Math.PI) / 360)

function subjectOf(doc: Scene3DDocument): Scene3DSlot | undefined {
  return doc.slots.find(slot => slot.slot === 'subject_1')
    ?? doc.slots.find(slot => slot.slot === 'subject_2')
    ?? doc.slots.find(slot => slot.slot === 'prop' && slot.media === 'model3d')
}

/** A model stands MODEL_HEIGHT × scale; an image cutout is a plane two units tall at its scale. */
function figureHeight(slot: Scene3DSlot) {
  return slot.media === 'image' ? Math.max(0.05, slot.scale) * 2 : MODEL_HEIGHT * Math.max(0.05, slot.scale)
}

function activeFraming(doc: Scene3DDocument): Scene3DFraming | undefined {
  const framing = doc.camera.family === 'fixed' ? undefined : doc.camera.framing
  return framing && doc.slots.some(slot => slot.id === framing.targetSlot) ? framing : undefined
}

/** Framing offsets are authored in figure units around the anchor, so the figure share needs no scale. */
function framedShot(framing: Scene3DFraming, fov: number): { distance: number; fraction: number } {
  const distance = (length(framing.from) + length(framing.to)) / 2
  const fovFrom = framing.fovFrom ?? fov
  const visible = visibleHeight(distance, (fovFrom + (framing.fovTo ?? fovFrom)) / 2)
  const fraction = framing.anchor === 'center' ? visible / MODEL_HEIGHT : visible / 2 / (framing.anchor === 'head' ? BODY_BELOW_HEAD : MODEL_HEIGHT)
  return { distance, fraction }
}

function familyShot(doc: Scene3DDocument, subject: Scene3DSlot): { distance: number; fraction: number } {
  const mid = doc.duration / 2
  const eye = cameraEyeAtTime(doc.camera, mid, doc.duration, doc.slots)
  const look = cameraLookAtTime(doc.camera, mid, doc.duration, doc.slots)
  const height = figureHeight(subject)
  const target: Vec3 = [subject.position[0], subject.position[1] + height / 2, subject.position[2]]
  const forward = sub(look, eye)
  const span = length(forward) || 1
  const depth = Math.max(0.3, dot(sub(target, eye), forward) / span)
  return { distance: depth, fraction: visibleHeight(depth, doc.camera.fov) / height }
}

function shotSize(fraction: number): TemplateShotSize {
  for (const [size, limit] of SHOT_FRACTIONS) if (fraction < limit) return size
  return 'far'
}

function framingMoves(framing: Scene3DFraming, fov: number): TemplateCameraMove[] {
  const moves: TemplateCameraMove[] = []
  const from = length(framing.from), to = length(framing.to)
  if (to < from * 0.95) moves.push('push')
  else if (to > from * 1.05) moves.push('pull')
  if (Math.abs(framing.to[0] - framing.from[0]) > 0.08) moves.push('slide')
  if (framing.to[1] - framing.from[1] > 0.08) moves.push('rise')
  else if (framing.from[1] - framing.to[1] > 0.08) moves.push('descend')
  if (Math.abs(framing.orbitTurns ?? 0) >= 0.02) moves.push('arc')
  const fovFrom = framing.fovFrom ?? fov
  if (Math.abs((framing.fovTo ?? fovFrom) - fovFrom) > 1) moves.push('zoom')
  const rollFrom = framing.rollFrom ?? 0
  if (Math.abs((framing.rollTo ?? rollFrom) - rollFrom) > 1) moves.push('roll')
  return moves
}

function familyMoves(doc: Scene3DDocument, subject: Scene3DSlot | undefined): TemplateCameraMove[] {
  switch (doc.camera.family) {
    case 'establishment': return ['push']
    case 'reveal': return ['rise', 'push']
    case 'encounter': return ['slide']
    case 'orbit': case 'product': case 'musical': return (doc.camera.orbitTurns ?? 1) !== 0 ? ['orbit'] : []
    case 'chase': case 'hood': return ['ride']
    case 'follow': case 'pursuit': case 'side': case 'front': return subject?.motion ? ['track'] : []
    default: return []
  }
}

function cameraMoves(doc: Scene3DDocument, framing: Scene3DFraming | undefined, subject: Scene3DSlot | undefined): TemplateCameraMove[] {
  const moves = framing ? framingMoves(framing, doc.camera.fov) : familyMoves(doc, subject)
  // A framing hangs off its target's anchor, so the camera travels with a figure that walks.
  if (framing && doc.slots.some(slot => slot.id === framing.targetSlot && slot.motion)) moves.push('track')
  if (doc.camera.shake?.length) moves.push('shake')
  return moves
}

const ANIMATED_SLOT_KEYS = ['motion', 'clip', 'clips', 'performance', 'rhythm', 'appearance', 'speech'] as const
const animatedSlot = (slot: Scene3DSlot) => ANIMATED_SLOT_KEYS.some(key => {
  const value = slot[key]
  return Array.isArray(value) ? value.length > 0 : Boolean(value)
})
const isSubject = (slot: Scene3DSlot) => SUBJECT_ROLES.has(slot.slot)
const isProp = (slot: Scene3DSlot) => slot.slot === 'prop' && slot.media !== 'screen'
const playsVideo = (slot: Scene3DSlot) => slot.screen?.media === 'video' && Boolean(slot.screen.sourceUrl)
const scrollsBackground = (slot: Scene3DSlot) => slot.slot === 'background' && Boolean(slot.loop?.cylinder) && slot.loop?.speed !== 0
const hasEffects = (doc: Scene3DDocument) => Boolean(doc.worldSfx?.length || doc.sfx?.length || doc.screenBackdrop?.sfx?.length)
const hasTexts = (doc: Scene3DDocument) => Boolean(doc.texts?.length || doc.lyrics)
const proceduralWorld = (doc: Scene3DDocument) => Boolean(doc.atmos || doc.pixelWorld || doc.motionLab || doc.environment?.road)
const movingSet = (dressing: string) => MOVING_DRESSINGS.has(dressing) || MOVING_DRESSING_PREFIXES.some(prefix => dressing.startsWith(prefix))

function backdropMoves(doc: Scene3DDocument): boolean {
  return proceduralWorld(doc) || movingSet(doc.dressing ?? '') || doc.slots.some(scrollsBackground)
}

const MOVING_RULES: ReadonlyArray<[TemplateMovingPart, (doc: Scene3DDocument) => boolean]> = [
  ['subjects', doc => doc.slots.some(slot => isSubject(slot) && animatedSlot(slot))],
  ['props', doc => doc.slots.some(slot => isProp(slot) && animatedSlot(slot))],
  ['screens', doc => doc.slots.some(playsVideo)],
  ['effects', hasEffects],
  ['backdrop', backdropMoves],
  ['texts', hasTexts],
]

function movingParts(doc: Scene3DDocument, moves: TemplateCameraMove[]): TemplateMovingPart[] {
  const parts: TemplateMovingPart[] = moves.length ? ['camera'] : []
  for (const [part, applies] of MOVING_RULES) if (applies(doc)) parts.push(part)
  return parts
}

function authoredFor(doc: Scene3DDocument): TemplateAuthoredFor {
  const media = new Set(doc.slots.filter(isSubject).map(slot => slot.media))
  if (!media.size) return 'none'
  if (media.has('image') && media.has('model3d')) return 'mixed'
  return media.has('image') ? 'cutout' : 'model'
}

const FLOORLESS_DRESSINGS = new Set(['space', 'treadmill', 'cafe', 'desert', 'jungle', 'snow', 'casino'])

function floorOf(doc: Scene3DDocument): string {
  if (doc.environment?.floorStyle) return doc.environment.floorStyle
  if (doc.environment?.reflectiveFloor) return 'mirror'
  const dressing = doc.dressing ?? ''
  return FLOORLESS_DRESSINGS.has(dressing) || movingSet(dressing) ? 'none' : 'tiles'
}

type Measured = Pick<TemplateTraits, 'shot' | 'moves' | 'moving' | 'subjects'> & { framing?: Scene3DFraming }
type UseContext = Measured & { doc: Scene3DDocument; hints: TemplateTraitHints; near: boolean; beat: boolean; look: boolean; rush: boolean }

/** A place is shown when the template paints one: a bound plate, a set that moves, or a procedural world. */
function showsPlace(doc: Scene3DDocument, moving: TemplateMovingPart[]) {
  return moving.includes('backdrop') || doc.slots.some(slot => slot.slot === 'background' && slot.sourceUrl)
}

const craneRise = (framing?: Scene3DFraming) => Boolean(framing && framing.to[1] - framing.from[1] >= 0.4)
const explosive = (doc: Scene3DDocument) => (doc.worldSfx ?? []).some(cue => EXPLOSIVE_FX.has(String(cue.kind)))
const subjectsTravel = (doc: Scene3DDocument) => doc.slots.some(slot => isSubject(slot) && slot.motion)
const fastCamera = (doc: Scene3DDocument) => FAST_CAMERAS.has(doc.camera.family)
const fastSet = (doc: Scene3DDocument) => doc.dressing === 'treadmill' || Boolean(doc.dressing?.startsWith('drive-'))
const tracksRush = (ctx: UseContext) => ctx.rush && ctx.moves.some(move => TRACKING_MOVES.has(move))

/** Metres a slot's motion path covers, through its waypoints. */
function pathLength(slot: Scene3DSlot): number {
  if (!slot.motion) return 0
  const stops: Vec3[] = [slot.position, ...(slot.motion.via ? [slot.motion.via] : []), ...(slot.motion.points ?? []), slot.motion.to]
  return stops.slice(1).reduce((total, stop, index) => total + length(sub(stop, stops[index])), 0)
}

/** The fastest subject's metres per second over the shot. */
function pace(doc: Scene3DDocument): number {
  return Math.max(0, ...doc.slots.filter(isSubject).map(pathLength)) / Math.max(doc.duration, 1e-6)
}

const USE_RULES: ReadonlyArray<[TemplateUse, (ctx: UseContext) => boolean]> = [
  ['plate', ctx => ctx.shot === 'plate'],
  ['dialogue', ctx => ctx.subjects >= 2 && ctx.shot !== 'far' && ctx.hints.category !== 'product' && !fastCamera(ctx.doc) && !ctx.beat && !ctx.rush],
  ['talk', ctx => ctx.subjects >= 1 && ctx.near && !ctx.beat],
  ['reaction', ctx => ctx.subjects === 1 && ctx.shot === 'close' && (ctx.moves.includes('arc') || ctx.moves.includes('push') || (!ctx.moves.length && !ctx.look))],
  ['figure', ctx => ctx.subjects >= 1 && ctx.shot === 'wide'],
  ['establishing', ctx => ctx.shot === 'far' || ctx.shot === 'plate' || (ctx.shot === 'wide' && showsPlace(ctx.doc, ctx.moving))],
  ['action', ctx => ctx.hints.category === 'action' || ctx.hints.family === 'chase' || ctx.hints.family === 'pursuit' || ctx.beat || subjectsTravel(ctx.doc)],
  ['speed', ctx => ctx.hints.category === 'drive' || fastCamera(ctx.doc) || fastSet(ctx.doc) || tracksRush(ctx) || ctx.doc.templateId.startsWith('speed-')],
  ['impact', ctx => ctx.beat],
  ['reveal', ctx => ctx.doc.camera.family === 'reveal' || craneRise(ctx.framing) || (ctx.moves.includes('pull') && ctx.moves.includes('zoom'))],
  ['product', ctx => ctx.hints.category === 'product'],
  ['music', ctx => ctx.hints.category === 'music' || Boolean(ctx.doc.rhythm)],
  ['drive', ctx => ctx.hints.category === 'drive'],
  ['transition', ctx => ctx.doc.duration <= 3 && ctx.moving.includes('effects')],
  ['title', ctx => ctx.moving.includes('texts')],
  ['look', ctx => ctx.look],
]

function usesOf(doc: Scene3DDocument, measured: Measured, hints: TemplateTraitHints): TemplateUse[] {
  const ctx: UseContext = {
    ...measured, doc, hints,
    near: measured.shot === 'close' || measured.shot === 'medium',
    beat: measured.moves.includes('shake') || explosive(doc),
    look: Boolean(hints.family && LOOK_FAMILIES.has(hints.family)),
    rush: pace(doc) >= RUN_PACE,
  }
  return USE_RULES.filter(([, applies]) => applies(ctx)).map(([use]) => use)
}

/** The family decides for a technique card; a pack id or the document decides for the rest. */
function kindOf(doc: Scene3DDocument, measured: Measured, uses: TemplateUse[], hints: TemplateTraitHints): TemplateKind {
  const family = hints.family ?? ''
  if (LOOK_FAMILIES.has(family)) return 'look'
  if (CAMERA_FAMILIES.has(family)) return 'camera'
  if (uses.includes('transition') || doc.templateId.startsWith('transition-')) return 'transition'
  if (doc.templateId.startsWith('title-') || (measured.subjects === 0 && measured.moving.includes('texts'))) return 'title'
  if (doc.room) return 'stage'
  return 'scene'
}

/** The dressing or mold the document was built in: the card's `place`, a filter an agent matches exactly. */
export function templatePlace(doc: Scene3DDocument): string | null {
  const place = doc.room?.mold.id ?? doc.dressing
  return place && place !== 'none' ? place : null
}

export function templateTraits(doc: Scene3DDocument, hints: TemplateTraitHints = {}): TemplateTraits {
  const subject = subjectOf(doc)
  const framing = activeFraming(doc)
  const measured = subject ? (framing ? framedShot(framing, doc.camera.fov) : familyShot(doc, subject)) : null
  const shot = measured ? shotSize(measured.fraction) : 'plate'
  const moves = cameraMoves(doc, framing, subject)
  const moving = movingParts(doc, moves)
  const subjects = doc.slots.filter(slot => SUBJECT_ROLES.has(slot.slot)).length
  const props = doc.slots.filter(slot => slot.slot === 'prop' && slot.media !== 'screen').length
  const screens = doc.slots.filter(slot => slot.media === 'screen').length
  const uses = usesOf(doc, { shot, moves, moving, subjects, framing }, hints)
  return {
    kind: kindOf(doc, { shot, moves, moving, subjects }, uses, hints),
    shot,
    distance: measured ? Math.round(measured.distance * 10) / 10 : null,
    moves,
    moving,
    still: moving.length === 0,
    travel: subjectsTravel(doc),
    subjects,
    props,
    screens,
    authoredFor: authoredFor(doc),
    floor: floorOf(doc),
    uses,
  }
}

/** The words a text search should see for these traits, in both languages' shared vocabulary. */
export function templateTraitWords(traits: TemplateTraits): string[] {
  return [traits.shot, ...traits.moves, ...traits.moving, ...traits.uses, traits.kind, traits.authoredFor, traits.still ? 'still' : 'animated', ...(traits.travel ? ['travel'] : [])]
}
