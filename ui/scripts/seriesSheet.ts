// Kit animations in a Series shot (services/series_cast_animation.py). A sprite sheet of the character's own kit (a walk,
// a wave, an anime expression) plays in place of its pose picture for an interval of the shot: the sheet is a layer of its
// own that stands on the pose's ground line at the pose's height, the pose and its mouth and eyes are hidden meanwhile and
// come back when it ends. The sheet is drawn as the Video 2D cards `walk-cycle-sheet` and `character-reaction` draw it
// (equal cells, the figure `figure` of a cell high, its boots on the line `feet`), by the painter's `sheet` sequence.
import type { SceneKeyframe, SceneLayer } from '../src/types/index.ts'
import type { CharacterKit } from '../src/lib/characterKit.ts'
import { ANIMATION_SHEET, type AnimationLoop, type KitAnimation } from '../src/lib/characterAnimations.ts'
import { evaluateSceneLayer, getSceneKeyframes, withSceneKeyframes } from '../src/lib/sceneTimeline.ts'

export type SheetRequest = { id: string; at?: number; duration?: number; loop?: AnimationLoop }
/** The parts of a cast member the sheets read (the CastSpec of seriesShot.ts). */
export type SheetCast = { animation?: SheetRequest; enter?: { fromX: number; start: number; end: number; gait?: 'hop' | 'walk'; step?: number } }
export type SheetWindow = {
  /** `walk-in` for the walk sheet of an entrance, else the animation's id. */
  part: string; animation: KitAnimation; start: number; end: number; loop: AnimationLoop; fps: number; mirror: boolean
}
/** A pose whose picture and face are hidden while its sheets play. */
export type SheetGate = { poseId: string; windows: Array<[number, number]> }

const round = (value: number, places = 3) => Math.round(value * 10 ** places) / 10 ** places
/** A window edge: opacity switches in a thousandth of a second, so no painted frame sees both pictures. */
const EDGE = 0.001
/** The shortest window worth drawing (s). */
const SHORTEST = 0.05
const WALK = 'walk'
const rounded = (point: Pick<SceneKeyframe, 'x' | 'y' | 'scale' | 'opacity' | 'rotation'>) => ({
  x: round(point.x), y: round(point.y), scale: round(point.scale, 5), opacity: round(point.opacity), rotation: round(point.rotation) })

/** The approved animation `id` of a kit; the reason it cannot be played otherwise (series_cast_animation.py checks the same in the script). */
export function playable(kit: CharacterKit, id: string): KitAnimation {
  const made = kit.animations?.[id]
  if (!made) throw new Error(`Character ${kit.name} has no animation ${id}`)
  if (made.reviewState === 'approved') return made
  throw new Error(`Animation ${id} of ${kit.name} ${made.reviewState === 'rejected' ? 'was rejected: make it again' : 'is pending approval: approve it'} in Characters › Animaciones`)
}

/** Seconds of one pass of a sheet: its cells at its fps; a `pingpong` goes there and back. */
export function passLength(animation: KitAnimation, loop: AnimationLoop): number {
  const count = Math.max(1, animation.sheet.count)
  return (loop === 'pingpong' && count > 1 ? count * 2 - 2 : count) / Math.max(1, animation.fps)
}

/** The walk of an entrance: a cycle is two steps, so the sheet plays at count / (2 steps) cells a second (3 to 24, as the card
 * does) and the feet land on the steps `enterStep` times. It walks the way it is drawn: against that, it is mirrored. */
function walkIn(animation: KitAnimation, enter: NonNullable<SheetCast['enter']>): SheetWindow {
  const step = enter.step && enter.step > 0 ? enter.step : 0.5
  const fps = round(Math.min(24, Math.max(3, animation.sheet.count / (2 * step))))
  const comes = enter.fromX < 50 ? 'right' : 'left'
  return { part: 'walk-in', animation, start: enter.start, end: enter.end, loop: 'loop', fps, mirror: animation.facing === 'left' ? comes === 'right' : animation.facing === 'right' && comes === 'left' }
}

/** The intervals of the shot in which this cast member's pose gives way to a sheet: the walk-in, when the kit has an approved
 * `walk` sheet and the entrance walks, and the cast entry's `animation`, which never starts before the walk has ended. */
export function sheetWindows(kit: CharacterKit, cast: SheetCast, duration: number): SheetWindow[] {
  const windows: SheetWindow[] = []
  const walk = cast.enter?.gait === 'walk' ? kit.animations?.[WALK] : undefined
  if (walk?.reviewState === 'approved' && cast.enter) windows.push(walkIn(walk, cast.enter))
  const wanted = cast.animation
  if (!wanted) return windows
  const animation = playable(kit, wanted.id)
  const loop = wanted.loop ?? animation.loop
  const start = Math.max(wanted.at ?? 0, windows[0]?.end ?? 0)
  const end = Math.min(duration, start + (wanted.duration ?? passLength(animation, loop)))
  if (end - start >= SHORTEST) windows.push({ part: wanted.id, animation, start, end, loop, fps: animation.fps, mirror: false })
  return windows
}

/** Where a sheet's cells go for a pose drawn `poseHeight` (% of the frame height): each cell is `poseHeight / figure` tall, so the
 * figure is as tall as the pose, and the line `feet` of the cell is the layer's `focus`, which stays on the ground. A cell wider
 * than the frame (a vertical one) is limited by its width, so the feet are lower in the layer's box than in the cell. */
export function sheetBox(animation: KitAnimation, poseHeight: number, aspect: number): { scale: number; focusY: number } {
  const ratio = animation.sheet.cell.width / animation.sheet.cell.height
  const cellHeight = poseHeight / ANIMATION_SHEET.figure
  const scale = ratio < aspect ? cellHeight / 100 : cellHeight / 100 * ratio / aspect
  return { scale: round(scale, 5), focusY: round(50 + (ANIMATION_SHEET.feet - 0.5) * 100 * Math.min(1, aspect / ratio)) }
}

/** Opacity of a layer inside the windows: `show` draws it only there, otherwise it is hidden there. Every other value of the layer
 * (place, size, tilt) goes on as it was: keys are added at the edges with the layer's own value at that moment. */
export function gateOpacity(layer: SceneLayer, windows: Array<[number, number]>, show: boolean, duration: number): SceneLayer {
  const source = getSceneKeyframes(layer)
  const near = (a: number, b: number) => Math.abs(a - b) < 1e-6
  const inside = (time: number) => windows.some(([from, to]) => time >= from - 1e-9 && time < to - 1e-9)
  // The key just before a window edge holds, so the switch happens on the edge and not across the step before it.
  const beforeEdge = (time: number) => windows.some(([from, to]) => near(time, round(from - EDGE)) || near(time, round(to - EDGE)))
  const added = [...new Set(windows.flatMap(([from, to]) => [from - EDGE, from, to - EDGE, to]).filter(time => time >= 0 && time <= duration).map(time => round(time)))]
    .filter(time => !source.some(frame => near(frame.time, time)))
  const points = [...source.map(frame => ({ time: frame.time, frame })), ...added.map(time => ({ time, frame: undefined as SceneKeyframe | undefined }))]
    .sort((a, b) => a.time - b.time)
  const frames: SceneKeyframe[] = points.map(({ time, frame }) => {
    const before = [...source].reverse().find(item => item.time <= time) ?? source[0]
    const point = frame ?? { ...rounded(evaluateSceneLayer(layer, time)), id: `${layer.id}-${Math.round(time * 1000)}`, time, curve: before.curve }
    return { ...point, opacity: inside(time) === show ? point.opacity : 0, ...(beforeEdge(time) ? { curve: 'hold' as const } : {}) }
  })
  return withSceneKeyframes(layer, frames, duration)
}

/** The pose (and its mouths, eyes and blink) hidden while a sheet plays. */
export function gateSheets(layers: SceneLayer[], gates: SheetGate[], duration: number): SceneLayer[] {
  if (!gates.length) return layers
  return layers.map(layer => {
    const gate = gates.find(item => layer.id === item.poseId || layer.faceBinding?.poseLayerId === item.poseId)
    return gate ? gateOpacity(layer, gate.windows, false, duration) : layer
  })
}

/** One window's sheet layer. `body` is the pose's own motion (its x, tilt and bob), which the sheet follows from the pose's
 * `restY` to the ground line `ground`; it is drawn only inside the window. */
export function sheetLayer(kit: CharacterKit, window: SheetWindow, args: {
  layerId: string; z: number; workspace: string; body: SceneKeyframe[]; restY: number; ground: number; poseHeight: number; aspect: number; duration: number
}): SceneLayer {
  const { sheet } = window.animation
  const { scale, focusY } = sheetBox(window.animation, args.poseHeight, args.aspect)
  const frames = args.body.map(frame => ({ ...frame, id: `${args.layerId}-${Math.round(frame.time * 1000)}`, y: round(frame.y - args.restY + args.ground), scale, opacity: 1 }))
  const first = frames[0]
  const transform = { x: first.x, y: first.y, scale, opacity: 1, rotation: first.rotation }
  const layer: SceneLayer = {
    id: args.layerId, name: `${kit.name} · ${window.part}`, type: 'image', source: sheet.source, visible: true, locked: false, z: args.z, fill: false,
    parallax: 1, focus: { x: 50, y: focusY }, transform,
    sequence: { kind: 'sheet', source: sheet.source, columns: sheet.columns, rows: sheet.rows, count: sheet.count, fps: window.fps, loop: window.loop,
      start: round(window.start), ...(window.mirror ? { mirror: true } : {}) },
    animation: { start: { ...transform }, end: { ...transform }, duration: args.duration, curve: 'linear', keyframes: frames },
  } as SceneLayer
  return gateOpacity(layer, [[window.start, window.end]], true, args.duration)
}
