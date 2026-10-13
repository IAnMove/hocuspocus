import type { SceneLayer } from '../../types'
import { asset, atmosphere, camera, groundShadow, keyframes, layer, type Beat, type BuildContext, type Pose } from './sceneBuilders'

/** A figure walking into a shot without showing legs that never move: six grammars (owner idea, 2026-10-13).
 * The first four never move the legs: the walk is a bob, a lean onto the planted foot and the world moving past.
 * - walk-follow-back: from behind, waist up; the figure holds its place and the room comes to it;
 * - walk-toward-camera: from the front, waist up; the camera backs away and the room recedes;
 * - walk-behind-foreground: a whole figure in profile crosses behind a foreground that covers the legs;
 * - walk-shadow-first: a big shadow crosses the wall, then the figure is there (cut on action).
 * The last two do move them, with drawings of the figure in profile (it walks the way it looks, `facing`):
 * - walk-two-pose: a two-cell sheet (the stride, the legs together) plays one cell per half step with a contact shadow;
 *   the walk is paced so the boots do not skate and the figure stops on the sheet's last cell (legs together);
 * - walk-cycle-sheet: a sprite sheet of the gait (four poses: contact, passing, contact, passing) crosses the shot.
 * And one card for a figure that stays where it is (the Character Creator's animations):
 * - character-reaction: a sheet of a gesture (wave, nod, point) or an anime expression (angry, surprised...) plays on the mark. */

type Spot = { x: number; y: number; scale: number }
type Stride = { at: number; turn: number; lean: number; lift: number }

const SAMPLES_PER_STEP = 6
/** Builders think in these pixels: a figure's height and its ground speed. */
const FRAME = { width: 1280, height: 720 }
/** One step of a walk covers this share of the figure's height (two steps are about .85). */
const STEP_REACH = .42
/** Share of a whole-figure cutout (head to boots) that stays in the frame at each framing. */
const FRAMING_SHARE: Record<string, number> = { waist: .43, chest: .3 }
const HEAD_ROOM = 8
const FEET = { x: 50, y: 99 }
/** A walk-cycle sheet leaves a little room below the figure: its boots touch the floor at this share of a cell (`media.compose`
 * with `anchor: bottom` at 96) and the figure is this share of the cell's height. */
const SHEET_FEET = 96
const SHEET_FIGURE = .86
type Side = { from: number; mark: number }
const SIDES: Record<string, Side> = { left: { from: -14, mark: 52 }, right: { from: 114, mark: 48 } }

/** A profile figure walks the way it looks: looking right it comes in from the left, looking left from the right. */
const entering = (c: BuildContext): Side => String(c.options.facing) === 'left' ? SIDES.right : SIDES.left

const number = (c: BuildContext, key: string, fallback: number): number => {
  const value = Number(c.options[key])
  return Number.isFinite(value) ? value : fallback
}

/** A layer the camera zoom does not touch: it holds its size and place while the world moves. */
const pinned = (item: SceneLayer): SceneLayer => ({ ...item, parallax: 0, parallaxZoom: true })

/** The figure stands on its feet: scale and lean turn about the point where its boots touch the floor. */
const onFeet = (item: SceneLayer): SceneLayer => ({ ...item, focus: { ...FEET } })

/** Steps of a walk between two moments of the shot (0-1): a whole number of steps, so a footfall lands on both ends.
 * `lean` is +1 on a footfall of one foot and -1 on the other; `lift` is 0 on a footfall and 1 in mid-step. A longer
 * shot takes more steps instead of slower ones. */
function strides(c: BuildContext, from: number, to: number, perStep = SAMPLES_PER_STEP): Stride[] {
  const wanted = number(c, 'step', .55)
  const steps = Math.max(1, Math.round((to - from) * c.duration / wanted))
  return Array.from({ length: steps * perStep + 1 }, (_, index) => {
    const turn = index / perStep
    return { at: from + (to - from) * turn / steps, turn, lean: Math.cos(Math.PI * turn), lift: Math.abs(Math.sin(Math.PI * turn)) }
  })
}

/** A centimetre-scale bob that grows with the figure's size on screen and with the card's intensity. */
const bobOf = (c: BuildContext, scale: number, gain = 1): number => scale * (.45 + 1.1 * c.intensity) * gain

/** Where the figure is on one sample of its walk: dipped on a footfall, risen mid-step, leaning onto the planted foot. */
function figureAt(c: BuildContext, spot: Spot, { lean, lift }: Stride, gain: number): Pose {
  const sway = number(c, 'sway', 1.2)
  return { x: spot.x - sway * .25 * lean, y: spot.y - bobOf(c, spot.scale, gain) * lift, scale: spot.scale, rotation: sway * lean }
}

/** The figure's beats on a walk. */
function stepBeats(c: BuildContext, walk: Stride[], path: (at: number) => Spot, gain = 1): Beat[] {
  return walk.map(stride => ({ at: stride.at, curve: 'linear', ...figureAt(c, path(stride.at), stride, gain) }))
}

/** Breathing once the figure has stopped: a weight shift every 2.6 s that repeats on a longer shot. */
function breathe(c: BuildContext, from: number, spot: Spot): Beat[] {
  const cycles = Math.max(1, Math.round((1 - from) * c.duration / 2.6))
  const count = cycles * 8
  return Array.from({ length: count }, (_, index) => {
    const turn = (index + 1) / 8 * Math.PI * 2
    return { at: from + (1 - from) * (index + 1) / count, curve: 'linear', x: spot.x, y: spot.y - .3 * (1 - Math.cos(turn)) / 2, scale: spot.scale * (1 + .004 * Math.cos(turn)), rotation: .5 * Math.sin(turn) }
  })
}

/** Ease between two points of a path: slow in, steady, slow out, so a figure does not start or stop like a slide. */
const smooth = (value: number) => value * value * (3 - 2 * value)

/** A figure that stays where it is: waist up (or chest up), head near the top of the frame, boots below it. */
function waistUp(c: BuildContext): Spot {
  const share = FRAMING_SHARE[String(c.options.framing)] ?? FRAMING_SHARE.waist
  const scale = (100 - HEAD_ROOM) / 100 / share
  return { x: 50, y: HEAD_ROOM + 50 * scale, scale }
}

function followShot(c: BuildContext, push: Beat[]): SceneLayer[] {
  const spot = waistUp(c)
  return [
    keyframes(pinned(asset(c, 'subject_1', spot)), stepBeats(c, strides(c, 0, 1), () => spot)),
    camera(c, push),
    atmosphere(c, 'dust'),
  ]
}

/** Where the plate and the foreground sit while the camera moves: the room travels, the figure does not. */
export const walkPlates: Record<string, (c: BuildContext) => { plate: Partial<SceneLayer>; foreground: Partial<SceneLayer> }> = {
  'walk-follow-back': () => ({ plate: { parallax: .5, parallaxZoom: true }, foreground: { parallax: 1.6, parallaxZoom: true } }),
  'walk-toward-camera': () => ({ plate: { parallax: .5, parallaxZoom: true }, foreground: { parallax: 1.6, parallaxZoom: true } }),
  // The covering foreground is part of the picture, not a blurred lens object: it keeps its focus and colour.
  'walk-behind-foreground': () => ({ plate: {}, foreground: { parallax: 1, effects: { blur: 0, brightness: 1 } } }),
  'walk-shadow-first': () => ({ plate: {}, foreground: {} }),
  'walk-two-pose': () => ({ plate: {}, foreground: {} }),
  'walk-cycle-sheet': () => ({ plate: {}, foreground: {} }),
}

type Route = { side: Side; size: number; floor: number; start: number; end: number; eased: boolean }

/** The ground a walk covers across a wide shot, from out of frame to a mark: `path` is the figure's own place at each moment
 * and `walk` its steps. An eased path slows in and out; a paced one keeps the speed its feet need. */
function route(c: BuildContext, { side, size, floor, start, end, eased }: Route, perStep = SAMPLES_PER_STEP) {
  const path = (at: number): Spot => {
    const done = Math.min(1, Math.max(0, (at - start) / (end - start)))
    return { x: side.from + (side.mark - side.from) * (eased ? smooth(done) : done), y: floor, scale: size }
  }
  return { path, walk: strides(c, start, end, perStep) }
}

/** The walk across a wide shot: out of frame to a mark, then standing. */
function crossing(c: BuildContext, spec: Pick<Route, 'side' | 'size' | 'floor'>, gain: number) {
  const full: Route = { ...spec, start: .05, end: .7, eased: true }
  const { path, walk } = route(c, full)
  const beats = [{ at: 0, curve: 'linear' as const, ...path(0), rotation: 0 }, ...stepBeats(c, walk, path, gain), ...breathe(c, full.end, path(full.end))]
  return { beats, walk, path }
}

/** When a walk paced by its step reaches the mark: the feet need this speed, so the figure takes as long as the ground needs. */
function pacedEnd(c: BuildContext, side: Side, size: number, start: number): number {
  const wanted = number(c, 'step', .55)
  const speed = STEP_REACH * size * FRAME.height / wanted
  const seconds = Math.abs(side.mark - side.from) / 100 * FRAME.width / speed
  return Math.min(.9, start + Math.max(1, Math.round(seconds / wanted)) * wanted / c.duration)
}

/** The figure of a walk that stops: the walker (a sheet that loops, one cell per half step) until `settle`, then the same sheet held on
 * its last cell, which is where it stands and breathes. Both draw the same cells, so the figure does not change size at the hand-off. */
function handOff(c: BuildContext, walk: Stride[], path: (at: number) => Spot, gain: number, settle: number) {
  const edge = 1 / (c.duration * 60)
  const last = path(walk[walk.length - 1].at)
  const standing: Pose = { ...last, rotation: 0 }
  const walker: Beat[] = [{ at: 0, curve: 'linear', ...path(0), rotation: 0, opacity: 1 }, ...stepBeats(c, walk, path, gain).map(beat => ({ ...beat, opacity: 1 })),
    { at: settle - edge, curve: 'linear', ...standing, opacity: 1 }, { at: settle, curve: 'linear', ...standing, opacity: 0 }, { at: 1, curve: 'linear', ...standing, opacity: 0 }]
  const rest: Beat[] = [{ at: 0, curve: 'linear', ...path(0), opacity: 0 }, { at: settle - edge, curve: 'linear', ...standing, opacity: 0 },
    { at: settle, curve: 'linear', ...standing, opacity: 1 }, ...breathe(c, settle, last).map(beat => ({ ...beat, opacity: 1 }))]
  return { walker, rest }
}

/** The shadow under the feet: full and dark on a footfall, smaller and lighter when the foot is up. */
function contactShadow(c: BuildContext, walk: Stride[], path: (at: number) => Spot, size: number): SceneLayer {
  const width = size * .4
  const beats: Beat[] = [{ at: 0, opacity: 0, x: path(0).x, y: path(0).y + .4, scale: width }]
  for (const { at, lift } of walk) beats.push({ at, curve: 'linear', opacity: .9 - .4 * lift, x: path(at).x, y: path(at).y + .4, scale: width * (1 - .18 * lift) })
  const last = walk[walk.length - 1].at
  beats.push({ at: last + .001, curve: 'linear', opacity: .9, x: path(last).x, y: path(last).y + .4, scale: width }, { at: 1, opacity: .9, x: path(last).x, y: path(last).y + .4, scale: width })
  return groundShadow(c, 'contact-shadow', beats)
}

/** The silhouette thrown on the wall: the figure's own picture, black and soft, big as if cast by a low light. */
function wallShadow(c: BuildContext, side: { from: number; mark: number }, floor: number): SceneLayer {
  const binding = c.bindings.subject_1!
  const item = layer('shadow', binding.type, binding.source, c.duration, { opacity: 0, scale: 1.9, y: floor - 32 }, 6)
  item.name = `shadow · ${binding.name || 'subject_1'}`
  item.effects = { brightness: 0, blur: 1, shadow: 0 }
  const reach = side.from + (side.mark - side.from) * .55
  const lean = side.mark > side.from ? -5 : 5
  const cast = { y: floor - 32, scale: 1.9 }
  return keyframes(item, [
    { at: 0, x: side.from, rotation: lean, opacity: 0, ...cast },
    { at: .06, x: side.from + (reach - side.from) * .12, rotation: lean * .85, opacity: .8, ...cast },
    { at: .36, x: reach, rotation: 0, opacity: .8, ...cast },
    { at: .42, x: reach + (side.mark - side.from) * .05, rotation: 0, opacity: 0, ...cast },
    { at: 1, x: reach, rotation: 0, opacity: 0, ...cast },
  ])
}

/** Where a reaction stands: the figure's place across the frame, in % of its width. */
const MARKS: Record<string, number> = { centre: 50, left: 30, right: 70 }

/** A figure that stays on its mark and plays a sheet of poses: it pops in, plays once (and holds its last pose) or keeps playing,
 * and breathes. A bust stands with its bottom edge on the frame's bottom; a whole figure stands on the floor with a shadow. */
function reaction(c: BuildContext): SceneLayer[] {
  const bust = String(c.options.framing) === 'bust'
  const size = bust ? 1 : .8
  const floor = bust ? 100 : 92
  const x = MARKS[String(c.options.mark)] ?? MARKS.centre
  const count = Math.round(number(c, 'frames', 2))
  const columns = Math.min(count, Math.round(number(c, 'columns', 2)))
  const fps = number(c, 'fps', 4)
  const loop = ['loop', 'pingpong'].includes(String(c.options.loop)) ? String(c.options.loop) as 'loop' | 'pingpong' : 'once'
  const spot: Spot = { x, y: floor, scale: size }
  const settled = loop === 'once' ? Math.min(.9, .08 + count / fps / c.duration) : .08
  const item = asset(c, 'subject_1', { x, y: floor, scale: size * .92, opacity: 0 })
  item.focus = { x: 50, y: SHEET_FEET }
  item.sequence = { kind: 'sheet', source: item.source, columns, rows: Math.ceil(count / columns), count, fps, loop }
  const beats: Beat[] = [
    { at: 0, curve: 'ease', x, y: floor + 1.5, scale: size * .92, opacity: 0 },
    { at: .06, curve: 'ease', ...spot, opacity: 1 },
    { at: settled, curve: 'linear', ...spot, opacity: 1 },
    ...breathe(c, settled, spot).map(beat => ({ ...beat, opacity: 1 })),
  ]
  const shadow = bust ? [] : [groundShadow(c, 'contact-shadow', [{ at: 0, opacity: 0, x, y: floor + .4, scale: .2 }, { at: .06, opacity: .85, x, y: floor + .4, scale: .2, curve: 'linear' }, { at: 1, opacity: .85, x, y: floor + .4, scale: .2 }])]
  return [...shadow, keyframes(item, beats), camera(c, [{ at: 0, scale: 1 }, { at: 1, scale: 1.05 }])]
}

export const walkScenes: Record<string, (ctx: BuildContext) => SceneLayer[]> = {
  // The world comes toward the figure: the plate grows slowly, the foreground faster, the figure never changes size.
  'walk-follow-back': c => followShot(c, [{ at: 0, scale: 1 }, { at: 1, scale: 1 + number(c, 'travel', .5) }]),
  // The camera walks backwards in front of the figure: the plate shrinks away, the figure keeps its size.
  'walk-toward-camera': c => followShot(c, [{ at: 0, scale: 1 + number(c, 'travel', .5) }, { at: 1, scale: 1 }]),
  'walk-behind-foreground': c => {
    const { beats } = crossing(c, { side: entering(c), size: .92, floor: 97 }, 1.3)
    return [keyframes(onFeet(asset(c, 'subject_1', { x: -20, y: 97, scale: .92 })), beats), camera(c, [{ at: 0, scale: 1 }, { at: 1, scale: 1.05 }]), atmosphere(c, 'dust')]
  },
  // Cut on action: the shadow arrives first, then the figure is simply standing on its mark with a small stomp.
  'walk-shadow-first': c => {
    const side = SIDES[String(c.options.entrance)] ?? SIDES.left
    const size = .8
    const floor = 92
    const mark: Spot = { x: side.mark, y: floor, scale: size }
    const landing: Beat[] = [
      { at: 0, curve: 'hold', x: mark.x, y: floor, scale: size, opacity: 0 },
      { at: .41, curve: 'hold', opacity: 0 },
      { at: .42, curve: 'linear', y: floor - 1.6, scale: size * 1.025, opacity: 1 },
      { at: .46, curve: 'linear', y: floor, scale: size, opacity: 1 },
      ...breathe(c, .46, mark),
    ]
    return [wallShadow(c, side, floor), keyframes(onFeet(asset(c, 'subject_1', { x: mark.x, y: floor, scale: size })), landing),
      camera(c, [{ at: 0, scale: 1 }, { at: 1, scale: 1.07 }]), atmosphere(c, 'dust')]
  },
  // A two-cell sheet of the figure in profile (the stride, the legs together) plays one cell per half step; it stops on the last cell.
  'walk-two-pose': c => {
    const figure = .72
    const scale = figure / SHEET_FIGURE
    const floor = 86
    const side = entering(c)
    const end = pacedEnd(c, side, figure, 0)
    const { path, walk } = route(c, { side, size: scale, floor, start: 0, end, eased: false })
    const count = Math.max(2, Math.round(number(c, 'frames', 2)))
    const columns = Math.min(count, Math.round(number(c, 'columns', 2)))
    const stepSeconds = end * c.duration / ((walk.length - 1) / SAMPLES_PER_STEP)
    const { walker, rest } = handOff(c, walk, path, 1, end + .12 / c.duration)
    const sheet = (id: string, beats: Beat[], loop: 'loop' | 'once', fps: number) => {
      const item = asset(c, 'subject_1', { x: -20, y: floor, scale })
      item.id = id
      item.focus = { x: 50, y: SHEET_FEET }
      item.sequence = { kind: 'sheet', source: item.source, columns, rows: Math.ceil(count / columns), count, fps, loop }
      return keyframes(item, beats)
    }
    return [contactShadow(c, walk, path, figure), sheet('subject_1', walker, 'loop', Math.min(24, Math.max(1, count / stepSeconds))), sheet('rest', rest, 'once', 60),
      camera(c, [{ at: 0, x: 48, scale: 1.02 }, { at: 1, x: 53, scale: 1.02 }])]
  },
  'character-reaction': reaction,
  // A sheet of the gait (contact, passing, contact, passing) plays at the speed that keeps the boots from sliding.
  'walk-cycle-sheet': c => {
    const scale = .8
    const floor = 88
    const count = Math.round(number(c, 'frames', 4))
    const columns = Math.min(count, Math.round(number(c, 'columns', 4)))
    const [from, to] = String(c.options.facing) === 'left' ? [112, -12] : [-12, 112]
    // The cadence of a walk is its step and the ground one step covers is a share of the figure's height: the sheet plays at that
    // pace (a cycle is two steps) and the figure crosses at the speed its feet need, so a longer shot has more empty room, not slower feet.
    const wanted = number(c, 'step', .55)
    const speed = STEP_REACH * SHEET_FIGURE * scale * FRAME.height / wanted
    const start = .05
    const end = Math.min(.97, start + Math.abs(to - from) / 100 * FRAME.width / speed / c.duration)
    const path = (x: number): Pose => ({ x, y: floor, scale, curve: 'linear' })
    const cross = [{ at: 0, ...path(from) }, { at: start, ...path(from) }, { at: end, ...path(to) }, { at: 1, ...path(to) }]
    const item = asset(c, 'subject_1', { x: from, y: floor, scale })
    item.focus = { x: 50, y: SHEET_FEET }
    item.sequence = { kind: 'sheet', source: item.source, columns, rows: Math.ceil(count / columns), count, fps: Math.min(24, Math.max(3, count / (2 * wanted))), loop: 'loop' }
    const shadow = (at: number, x: number): Beat => ({ at, opacity: .85, x, y: floor + .4, scale: .2, curve: 'linear' })
    return [groundShadow(c, 'contact-shadow', [shadow(0, from), shadow(start, from), shadow(end, to), shadow(1, to)]), keyframes(item, cross)]
  },
}
