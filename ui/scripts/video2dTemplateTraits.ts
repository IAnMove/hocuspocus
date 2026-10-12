// What a Video 2D scene template does, read from the compiled document (contract §10,
// docs/development/VIDEO2D_TEMPLATE_MODEL.md). The exporter compiles each card at its defaults with
// placeholder pictures and passes the normalized scene here. Every field is measured by sampling the real
// layer evaluator over the shot (one sample per frame at 30 fps), never written by hand:
// - moves: what the camera does (push, pull, slide, rise, descend, roll, shake; drift when it moves under all of
//   them; bounce when it pulses) and what the cast does on its own (orbit, bounce, spin);
// - travel: where the subjects go: across, up (rise), down (fall), round (orbit), in (enter the frame or grow
//   near) or out (leave the frame or shrink away);
// - holdShare: the share of the shot in which nothing but particles (atmospheres and the card's own graphics)
//   changes on screen. Texts do not count: a title over a frozen plate is still a frozen plate.
import { createSceneEvaluator, type SceneEvaluator } from '../src/lib/scene2d/evaluate.ts'
import { stripOffsets } from '../src/lib/scene2d/layerStyle.ts'
import type { AnimatorLayer, AnimatorScene, LayerState } from '../src/lib/scene2d/types.ts'

export const TRAIT_MOVES = ['push', 'pull', 'slide', 'rise', 'descend', 'orbit', 'roll', 'shake', 'drift', 'bounce', 'spin'] as const
export const TRAIT_MOVING = ['camera', 'subject', 'subjects', 'props', 'background', 'particles', 'text'] as const
export const TRAIT_TRAVEL = ['none', 'cross', 'rise', 'fall', 'orbit', 'in', 'out'] as const
export const TRAIT_USES = ['music', 'dance', 'performance', 'product', 'transition', 'entrance', 'exit', 'establishing', 'dialogue', 'documentary', 'space'] as const
export const TRAIT_BACKGROUNDS = ['still', 'drift', 'strip', 'video'] as const

export type TraitMove = typeof TRAIT_MOVES[number]
export type TraitMoving = typeof TRAIT_MOVING[number]
export type TraitTravel = typeof TRAIT_TRAVEL[number]
export type TraitUse = typeof TRAIT_USES[number]
export type TraitBackground = typeof TRAIT_BACKGROUNDS[number]
/** What a layer is in the card: bound to a slot of that role, the camera, or the template's own particles and graphics. */
export type LayerRole = 'subject' | 'prop' | 'background' | 'foreground' | 'camera' | 'particles'

export type Video2dTemplateTraits = {
  moves: TraitMove[]
  moving: TraitMoving[]
  /** True when nothing but particles moves for more than half the shot. */
  still: boolean
  /** Share of the shot (0-1) in which nothing but particles moves: no camera, cast, plate or graphic changes. */
  holdShare: number
  subjects: number
  props: number
  travel: TraitTravel
  format: 'landscape' | 'portrait'
  uses: TraitUse[]
  background: TraitBackground
  duration: number
}

export type CardHints = {
  id: string
  family: string
  /** Slot ids of the card, in catalog order; their names give the role (subject_1, hero → subject...). */
  slots: readonly string[]
  /** The role of each compiled layer, by layer id (a slot copy shares its slot's role). */
  roles: ReadonlyMap<string, LayerRole>
}

/** Samples per second of shot: one per frame at 30 fps. */
const SAMPLES_PER_SECOND = 30
const MIN_SAMPLES = 60
const EPSILON = { x: 1e-4, y: 1e-4, scale: 1e-5, rotation: 1e-3, opacity: 1e-4, modelYaw: 1e-3 }
/** Below this opacity a layer is gone from the picture. */
const HIDDEN_OPACITY = .02
// Camera thresholds over the whole shot: below all of them a moving camera is a drift.
const CAMERA_ZOOM = .06
const CAMERA_SLIDE = 8
const CAMERA_LIFT = 5
const CAMERA_ROLL = 2.5
// A swing at least this large that turns back counts as one beat of a bounce or a dance step.
const SWAY = { x: 3, rotation: 8 }
const BOUNCE_SWING = { y: 1, scale: .03, cameraScale: .015 }
const HOP_SHARE = .35
const SPIN_DEGREES = 180
// A path orbits when it turns this far around its centre and is round: its narrow side at least this share of its wide one.
const ORBIT_DEGREES = 300
const ORBIT_ROUNDNESS = .3
const ORBIT_SPAN = 4
// Travel: a crossing covers a quarter of the frame, a rise or fall a fifth; going far or near halves or doubles the size.
const CROSS = 25
const LIFT = 20
const FAR_RATIO = .45
const NEAR_RATIO = 2.2
/** A subject at most this tall (share of the frame height) at mid-shot is small in the place it shows. */
const SMALL_SUBJECT = .5
const PERFORMER = .5
const DIALOGUE_STEP = 10

type Sample = { time: number; state: LayerState }
type Channel = 'x' | 'y' | 'scale' | 'rotation'

export function sampleTimes(duration: number): number[] {
  const count = Math.max(MIN_SAMPLES, Math.round(duration * SAMPLES_PER_SECOND))
  return Array.from({ length: count + 1 }, (_, index) => index / count)
}

/** The role a slot name gives, in the contract vocabulary and the names it replaced. */
export function slotRole(slot: string): LayerRole {
  if (/^(subject|hero)/.test(slot)) return 'subject'
  if (/^(background|plate)/.test(slot)) return 'background'
  if (/^foreground/.test(slot)) return 'foreground'
  return 'prop'
}

const boxOf = (layer: AnimatorLayer, state: LayerState) => ({
  width: state.scale * (layer.type === 'model3d' ? 52 : 100),
  height: state.scale * (layer.type === 'model3d' ? 75 : 100),
})

const shown = (state: LayerState) => state.opacity >= HIDDEN_OPACITY && state.scale >= .01

/** Some of the layer shows in the frame: its motion is seen. */
export function inView(layer: AnimatorLayer, state: LayerState): boolean {
  const box = boxOf(layer, state)
  return shown(state) && Math.abs(state.x - 50) < 50 + box.width / 2 && Math.abs(state.y - 50) < 50 + box.height / 2
}

/** The layer's centre is in the frame: the figure is in the shot, not leaving or arriving at its edge. */
export function onScreen(state: LayerState): boolean {
  return shown(state) && Math.abs(state.x - 50) <= 50 && Math.abs(state.y - 50) <= 50
}

function changed(a: LayerState, b: LayerState): boolean {
  return (Object.keys(EPSILON) as (keyof typeof EPSILON)[]).some(key => Math.abs((a[key] ?? 0) - (b[key] ?? 0)) > EPSILON[key])
}

/** A layer whose picture plays on its own (a video, a frame sequence or a spinning model) moves at every instant. */
const playsOnItsOwn = (layer: AnimatorLayer) => layer.type === 'video' || Boolean(layer.sequence) || (layer.type === 'model3d' && Boolean(layer.animation.spin))

function renderedChange(layer: AnimatorLayer, before: LayerState[], after: LayerState[]): boolean {
  if (before.length !== after.length) return true
  return before.some((state, index) => {
    const next = after[index]
    const seen = inView(layer, state)
    if (seen !== inView(layer, next)) return true
    return seen && changed(state, next)
  })
}

/** Share of the shot in which no layer but particles changes on screen (camera, strips and orbits included). */
export function holdShare(scene: AnimatorScene, evaluator: SceneEvaluator, roles: ReadonlyMap<string, LayerRole>, times: number[]): number {
  const layers = scene.layers.filter(layer => layer.visible && layer.type !== 'camera' && roles.get(layer.id) !== 'particles')
  if (layers.some(playsOnItsOwn)) return 0
  let previous = layers.map(layer => evaluator.renderedLayerStates(layer, times[0]))
  let held = 0
  for (const time of times.slice(1)) {
    const current = layers.map(layer => evaluator.renderedLayerStates(layer, time))
    if (!layers.some((layer, index) => renderedChange(layer, previous[index], current[index]))) held += 1
    previous = current
  }
  return held / Math.max(1, times.length - 1)
}

/** The zigzag turns of a series: each time it goes back by at least ``swing`` from its last extreme. */
export function turns(values: number[], swing: number): number {
  let direction = 0
  let extreme = values[0] ?? 0
  const base = extreme
  let count = 0
  for (const value of values) {
    if (direction === 0) {
      if (Math.abs(value - base) >= swing) { direction = Math.sign(value - base); extreme = value }
      continue
    }
    if ((value - extreme) * direction > 0) extreme = value
    else if (Math.abs(extreme - value) >= swing) { count += 1; direction = -direction; extreme = value }
  }
  return count
}

const series = (samples: Sample[], channel: Channel) => samples.map(sample => sample.state[channel])
const range = (values: number[]) => Math.max(...values) - Math.min(...values)
const first = (values: number[]) => values[0]
const last = (values: number[]) => values[values.length - 1]

function layerSamples(evaluator: SceneEvaluator, layer: AnimatorLayer, times: number[], shake = true): Sample[] {
  return times.map(time => ({ time, state: evaluator.layerState(layer, time, new Set(), shake) }))
}

/** What the active camera does, without its shake: the moves of the contract, or drift when it moves under them all. */
export function cameraMoves(camera: AnimatorLayer | undefined, samples: Sample[]): TraitMove[] {
  if (!camera || !samples.length) return []
  const scale = series(samples, 'scale')
  const y = series(samples, 'y')
  const moves: TraitMove[] = []
  const zoom = last(scale) - first(scale)
  const punch = turns(scale, BOUNCE_SWING.cameraScale) === 1 && Math.abs(zoom) < BOUNCE_SWING.cameraScale
  const pulses = punch || turns(scale, BOUNCE_SWING.cameraScale) >= 2 || turns(y, BOUNCE_SWING.y) >= 2
  if (!pulses && zoom >= CAMERA_ZOOM) moves.push('push')
  if (!pulses && zoom <= -CAMERA_ZOOM) moves.push('pull')
  if (range(series(samples, 'x')) >= CAMERA_SLIDE) moves.push('slide')
  if (!pulses && last(y) - first(y) <= -CAMERA_LIFT) moves.push('rise')
  if (!pulses && last(y) - first(y) >= CAMERA_LIFT) moves.push('descend')
  if (range(series(samples, 'rotation')) >= CAMERA_ROLL) moves.push('roll')
  if (camera.animation.shake?.amount) moves.push('shake')
  if (pulses) moves.push('bounce')
  const moved = samples.some(sample => changed(samples[0].state, sample.state))
  if (moved && !moves.length) moves.push('drift')
  return moves
}

/** Unwrapped degrees a path turns around its own centre. */
function sweep(samples: Sample[]): number {
  const cx = samples.reduce((sum, sample) => sum + sample.state.x, 0) / samples.length
  const cy = samples.reduce((sum, sample) => sum + sample.state.y, 0) / samples.length
  let total = 0
  let previous: number | null = null
  for (const { state } of samples) {
    if (Math.hypot(state.x - cx, state.y - cy) < 1) continue
    const angle = Math.atan2(state.y - cy, state.x - cx) * 180 / Math.PI
    if (previous !== null) total += ((angle - previous + 540) % 360) - 180
    previous = angle
  }
  return Math.abs(total)
}

/** A loop, not a line: both sides of the path span at least ORBIT_SPAN % and the narrow one is a fair share of the wide one. */
function round(samples: Sample[], scene: AnimatorScene): boolean {
  const wide = range(series(samples, 'x'))
  const tall = range(series(samples, 'y'))
  const sides = [wide * scene.width, tall * scene.height]
  return Math.min(wide, tall) >= ORBIT_SPAN && Math.min(...sides) >= ORBIT_ROUNDNESS * Math.max(...sides)
}

const stays = (samples: Sample[]) => samples.every(sample => onScreen(sample.state))
const loops = (samples: Sample[], scene: AnimatorScene) => stays(samples) && round(samples, scene) && sweep(samples) >= ORBIT_DEGREES
const orbits = (layer: AnimatorLayer, samples: Sample[], scene: AnimatorScene) => Boolean(layer.animation.orbit) || loops(samples, scene)

/** Up and down rather than along an arc: the vertical swing is a fair share of the horizontal one (a pendulum sways). */
function hops(samples: Sample[], scene: AnimatorScene): boolean {
  const upright = range(series(samples, 'y')) * scene.height >= HOP_SHARE * range(series(samples, 'x')) * scene.width
  return upright && turns(series(samples, 'y'), BOUNCE_SWING.y) >= 2
}

/** A hop or pulse that repeats while the figure stays in the frame (an orbit's own ups and downs are not one). */
const bounces = (layer: AnimatorLayer, samples: Sample[], scene: AnimatorScene) => stays(samples) && !orbits(layer, samples, scene)
  && (hops(samples, scene) || turns(series(samples, 'scale'), BOUNCE_SWING.scale) >= 2)
const sways = (samples: Sample[]) => turns(series(samples, 'x'), SWAY.x) >= 2 || turns(series(samples, 'rotation'), SWAY.rotation) >= 2

/** The cast's own moves: orbit, bounce (a hop or pulse that repeats) and spin. */
export function castMoves(layer: AnimatorLayer, samples: Sample[], scene: AnimatorScene): TraitMove[] {
  const moves: TraitMove[] = []
  if (orbits(layer, samples, scene)) moves.push('orbit')
  if (bounces(layer, samples, scene)) moves.push('bounce')
  if (range(series(samples, 'rotation')) >= SPIN_DEGREES || (layer.type === 'model3d' && layer.animation.spin)) moves.push('spin')
  return moves
}

type Cast = { layer: AnimatorLayer; samples: Sample[] }

/** A figure that hops, pulses or sways back and forth in the frame: it dances rather than travels. */
const dances = ({ layer, samples }: Cast, scene: AnimatorScene) => bounces(layer, samples, scene) || (stays(samples) && sways(samples))

function viewAt(cast: Cast[], index: number) {
  return cast.some(({ samples }) => onScreen(samples[index].state))
}

const showsIn = (cast: Cast[]) => cast.length > 0 && cast[0].samples.some((_, index) => viewAt(cast, index))

const mean = (values: number[]) => values.reduce((sum, value) => sum + value, 0) / Math.max(1, values.length)

function shift(cast: Cast[], scene: AnimatorScene) {
  const dx = mean(cast.map(({ samples }) => last(series(samples, 'x')) - first(series(samples, 'x'))))
  const dy = mean(cast.map(({ samples }) => last(series(samples, 'y')) - first(series(samples, 'y'))))
  const ratio = mean(cast.map(({ samples }) => last(series(samples, 'scale')) / Math.max(.01, first(series(samples, 'scale')))))
  const across = Math.abs(dx) * scene.width >= Math.abs(dy) * scene.height
  return { dx, dy, ratio, across }
}

function passage(cast: Cast[], scene: AnimatorScene): TraitTravel {
  const { dy, across } = shift(cast, scene)
  if (across) return 'cross'
  return dy < 0 ? 'rise' : 'fall'
}

function displacement(cast: Cast[], scene: AnimatorScene): TraitTravel {
  const { dx, dy, ratio, across } = shift(cast, scene)
  if (ratio <= FAR_RATIO) return 'out'
  if (ratio >= NEAR_RATIO) return 'in'
  if (across && Math.abs(dx) >= CROSS) return 'cross'
  if (!across && dy <= -LIFT) return 'rise'
  if (!across && dy >= LIFT) return 'fall'
  return 'none'
}

/** Where the subjects go over the shot, read from their own paths (the camera aside). */
export function travelOf(cast: Cast[], scene: AnimatorScene): TraitTravel {
  if (!cast.length) return 'none'
  const atStart = viewAt(cast, 0)
  const atEnd = viewAt(cast, cast[0].samples.length - 1)
  if (atStart && !atEnd) return 'out'
  if (!atStart && atEnd) return 'in'
  if (!atStart) return showsIn(cast) ? passage(cast, scene) : 'none'
  if (cast.some(({ layer, samples }) => orbits(layer, samples, scene))) return 'orbit'
  return displacement(cast, scene)
}

type Measured = {
  scene: AnimatorScene
  hints: CardHints
  cast: Cast[]
  moves: TraitMove[]
  travel: TraitTravel
  subjects: number
  rhythm: boolean
}

const idWords = (id: string) => id.split(/[-_]/)
const heightShare = (layer: AnimatorLayer, state: LayerState) => state.scale * (layer.type === 'model3d' ? .75 : 1)

function midHeight(cast: Cast[]): number {
  return Math.max(0, ...cast.map(({ layer, samples }) => heightShare(layer, samples[Math.floor(samples.length / 2)].state)))
}

const alwaysInView = (cast: Cast[]) => cast.length > 0 && cast[0].samples.every((_, index) => viewAt(cast, index))
const clearAt = (cast: Cast[], index: number) => cast.length > 0 && !viewAt(cast, index)
const cameraOpens = (moves: TraitMove[]) => moves.some(move => move === 'pull' || move === 'slide' || move === 'rise')

function stepsAside(cast: Cast[]): boolean {
  return cast.some(({ samples }) => range(series(samples, 'x')) >= DIALOGUE_STEP || range(series(samples, 'y')) >= DIALOGUE_STEP)
}

const USE_RULES: ReadonlyArray<[TraitUse, (m: Measured) => boolean]> = [
  ['music', m => m.hints.family === 'music' || m.rhythm],
  ['dance', m => m.cast.some(cast => dances(cast, m.scene))],
  ['performance', m => m.hints.family === 'music' && alwaysInView(m.cast) && m.travel === 'none' && midHeight(m.cast) >= PERFORMER && m.moves.length > 0],
  ['product', m => idWords(m.hints.id).includes('product')],
  ['transition', m => showsIn(m.cast) && (clearAt(m.cast, 0) || clearAt(m.cast, m.cast[0].samples.length - 1))],
  ['entrance', m => showsIn(m.cast) && clearAt(m.cast, 0)],
  ['exit', m => showsIn(m.cast) && clearAt(m.cast, m.cast[0].samples.length - 1)],
  ['establishing', m => cameraOpens(m.moves) && midHeight(m.cast) <= SMALL_SUBJECT && m.hints.slots.some(slot => slotRole(slot) === 'background')],
  ['dialogue', m => m.subjects >= 2 && alwaysInView(m.cast) && m.travel === 'none' && !stepsAside(m.cast) && !m.cast.some(cast => dances(cast, m.scene))],
  ['documentary', m => idWords(m.hints.id).includes('documentary')],
  ['space', m => m.hints.family === 'space'],
]

function backgroundOf(scene: AnimatorScene, evaluator: SceneEvaluator, roles: ReadonlyMap<string, LayerRole>, times: number[]): TraitBackground {
  const plates = scene.layers.filter(layer => roles.get(layer.id) === 'background')
  if (plates.some(layer => layer.type === 'video')) return 'video'
  if (plates.some(layer => stripOffsets(layer, 0).length > 1)) return 'strip'
  const moves = plates.some(layer => {
    const states = times.map(time => evaluator.renderedLayerStates(layer, time))
    return states.some(state => renderedChange(layer, states[0], state))
  })
  return moves ? 'drift' : 'still'
}

function ownChange(layer: AnimatorLayer, samples: Sample[]): boolean {
  if (playsOnItsOwn(layer) || stripOffsets(layer, 0).length > 1) return true
  return samples.some(sample => inView(layer, sample.state) && changed(samples[0].state, sample.state))
}

function movingParts(scene: AnimatorScene, layers: Map<LayerRole, Cast[]>, cameraMoving: boolean): TraitMoving[] {
  const moving = (role: LayerRole) => (layers.get(role) ?? []).filter(({ layer, samples }) => ownChange(layer, samples)).length
  const parts: TraitMoving[] = []
  if (cameraMoving) parts.push('camera')
  const subjects = moving('subject')
  if (subjects === 1) parts.push('subject')
  if (subjects > 1) parts.push('subjects')
  if (moving('prop')) parts.push('props')
  if (moving('background')) parts.push('background')
  if ((layers.get('particles') ?? []).length) parts.push('particles')
  if (scene.texts?.length || scene.lyrics) parts.push('text')
  return parts
}

function byRole(scene: AnimatorScene, evaluator: SceneEvaluator, roles: ReadonlyMap<string, LayerRole>, times: number[]): Map<LayerRole, Cast[]> {
  const grouped = new Map<LayerRole, Cast[]>()
  for (const layer of scene.layers) {
    const role = roles.get(layer.id)
    if (!role || role === 'camera' || !layer.visible) continue
    grouped.set(role, [...(grouped.get(role) ?? []), { layer, samples: layerSamples(evaluator, layer, times) }])
  }
  return grouped
}

function orderedMoves(found: Iterable<TraitMove>): TraitMove[] {
  const set = new Set(found)
  return TRAIT_MOVES.filter(move => set.has(move))
}

const rounded = (value: number, places = 3) => Math.round(value * 10 ** places) / 10 ** places

export function templateTraits2d(scene: AnimatorScene, hints: CardHints): Video2dTemplateTraits {
  const evaluator = createSceneEvaluator(scene)
  const times = sampleTimes(scene.duration)
  const camera = evaluator.activeCameraLayer()
  const cameraSamples = camera ? layerSamples(evaluator, camera, times, false) : []
  const layers = byRole(scene, evaluator, hints.roles, times)
  const cast = layers.get('subject') ?? []
  const castMoving = [...cast, ...(layers.get('prop') ?? [])].flatMap(({ layer, samples }) => castMoves(layer, samples, scene))
  const moves = orderedMoves([...cameraMoves(camera, cameraSamples), ...castMoving])
  const hold = holdShare(scene, evaluator, hints.roles, times)
  const subjects = hints.slots.filter(slot => slotRole(slot) === 'subject').length
  const travel = travelOf(cast, scene)
  const shaken = camera ? layerSamples(evaluator, camera, times) : []
  const cameraMoving = shaken.some(sample => changed(shaken[0].state, sample.state))
  const measured: Measured = { scene, hints, cast, moves, travel, subjects, rhythm: Boolean(scene.rhythm?.beats?.length) }
  return {
    moves,
    moving: movingParts(scene, layers, cameraMoving),
    still: hold > .5,
    holdShare: rounded(hold, 2),
    subjects,
    props: hints.slots.filter(slot => slotRole(slot) === 'prop').length,
    travel,
    format: scene.height > scene.width ? 'portrait' : 'landscape',
    uses: USE_RULES.filter(([, applies]) => applies(measured)).map(([use]) => use),
    background: backgroundOf(scene, evaluator, hints.roles, times),
    duration: rounded(scene.duration),
  }
}
