import type { SceneKeyframe, SceneLayer } from '../../types'
import { atmosphere, cycles, keyframes, layer, repeatPath, type Beat, type BuildContext } from './sceneBuilders'
import { copySubject, movingSubject, sampledPath } from './musicMotionBuilders'

type Spot = { x: number; scale: number; opacity: number }
const LIT: Spot[] = [{ x: 28, scale: .9, opacity: 1 }, { x: 72, scale: .9, opacity: 1 }]
const DIM: Spot[] = [{ x: 25, scale: .48, opacity: .4 }, { x: 75, scale: .48, opacity: .4 }]
/** One hand-over of the spotlight per this many seconds, repeated through the whole shot. */
const RELAY_SECONDS = 1.5

/** Figure `who` (0 or 1): every relay swaps the light; the lit figure breathes so the frame never holds. */
function relayPath(c: BuildContext, who: 0 | 1): Beat[] {
  const relays = Math.max(2, Math.round(c.duration / RELAY_SECONDS))
  const lit = (relay: number) => (relay % 2 === 0) === (who === 0)
  const beats: Beat[] = [{ at: 0, ...(who === 0 ? LIT[0] : DIM[1]) }]
  for (let relay = 0; relay < relays; relay += 1) {
    const start = relay / relays
    const span = 1 / relays
    const next = lit(relay + 1) ? LIT[who] : DIM[who]
    beats.push({ at: start + span * .55, ...next })
    if (lit(relay + 1)) beats.push({ at: start + span * .78, ...next, scale: next.scale * 1.04 }, { at: start + span, ...next })
    else beats.push({ at: start + span, ...next, x: next.x + (who === 0 ? -1 : 1) })
  }
  return beats
}

// A full figure on every step stays whole on screen: the steps climb only as far as the follow camera can keep the
// head and the feet in frame, and the figure does not grow as it climbs.
const STEPS: Array<[x: number, y: number, scale: number]> = [[18, 66, .46], [34, 59, .48], [50, 52, .5], [66, 45, .52], [82, 38, .54]]
const HOP = 6
const FOLLOW = .5

/** One climb of four hops: an arc up, a landing squash and a small rebound on every step. */
function climb(): Beat[] {
  const hops = STEPS.length - 1
  const beats: Beat[] = [{ at: 0, x: STEPS[0][0], y: STEPS[0][1], scale: STEPS[0][2] }]
  for (let hop = 0; hop < hops; hop += 1) {
    const [x0, y0, s0] = STEPS[hop]
    const [x1, y1, s1] = STEPS[hop + 1]
    const at = (part: number) => (hop + part) / hops
    beats.push(
      { at: at(.45), x: (x0 + x1) / 2, y: Math.min(y0, y1) - HOP, scale: (s0 + s1) / 2 * 1.04, rotation: -4 },
      { at: at(.7), x: x1, y: y1 + 1.5, scale: s1 * 1.06, rotation: 2 },
      { at: at(.85), x: x1, y: y1 - 1, scale: s1 * .98, rotation: 0 },
      { at: at(1), x: x1, y: y1, scale: s1, rotation: 0 },
    )
  }
  return beats
}

/** The camera follows the climber half of the way from the centre. */
function followCamera(c: BuildContext, path: Beat[]): SceneLayer {
  // Not camera(): the climb already repeats on longer shots, so the follow must not stretch as well.
  return keyframes(layer('camera', 'camera', '', c.duration, {}, 100), path.filter((_, index) => index % 4 === 0).map(beat => ({
    at: beat.at, x: 50 + ((beat.x ?? 50) - 50) * FOLLOW, y: 50 + ((beat.y ?? 50) - 50) * FOLLOW, scale: 1.06,
  })))
}

/** Copies ride a conveyor at one speed; a copy leaving on the left re-enters on the right, off frame. */
function conveyorFrames(c: BuildContext, id: string, index: number): SceneKeyframe[] {
  const speed = 125 / c.base
  const exit = -26
  const ring = 152
  let x = 25 + index * 38
  let time = 0
  const frames: Array<{ time: number; x: number; curve: SceneKeyframe['curve'] }> = [{ time: 0, x, curve: 'linear' }]
  while (time + (x - exit) / speed < c.duration) {
    time += (x - exit) / speed
    frames.push({ time, x: exit, curve: 'hold' }, { time: Math.min(c.duration, time + .004), x: exit + ring, curve: 'linear' })
    x = exit + ring
    time += .004
  }
  frames.push({ time: c.duration, x: x - speed * (c.duration - time), curve: 'linear' })
  return frames.map((frame, at) => ({ id: `${id}-${at}`, ...frame, y: 57, scale: .5, opacity: 1, rotation: 0 }))
}

function conveyor(c: BuildContext): SceneLayer[] {
  return Array.from({ length: 4 }, (_, i) => {
    const copy = copySubject(c, i, [{ at: 0, x: 25 + i * 38, y: 57, scale: .5 }])
    const frames = conveyorFrames(c, copy.id, i)
    const pose = (frame: SceneKeyframe) => ({ ...copy.transform, x: frame.x, y: frame.y, scale: frame.scale, rotation: frame.rotation, opacity: frame.opacity })
    return { ...copy, animation: { ...copy.animation, keyframes: frames, start: pose(frames[0]), end: pose(frames[frames.length - 1]) } }
  })
}

export const musicMotionEnsemble: Record<string, (c: BuildContext) => SceneLayer[]> = {
  'music-orbit-duel': c => (['subject_1', 'subject_2'] as const).map((slot, index) => movingSubject(c, repeatPath(sampledPath(32, at => ({
    x: 50 + 27 * Math.cos(at * Math.PI * 2 + index * Math.PI),
    y: 53 + 19 * Math.sin(at * Math.PI * 2 + index * Math.PI), scale: .55, rotation: 0,
  })), cycles(c)), slot)),
  'music-high-five': c => [
    movingSubject(c, [{ at: 0, x: 15, scale: .65, rotation: -8 }, { at: .45, x: 38, y: 47, scale: .65, rotation: 8 }, { at: .65, x: 33, scale: .65, rotation: -5 }, { at: 1, x: 33, scale: .65, rotation: 0 }]),
    movingSubject(c, [{ at: 0, x: 85, scale: .65, rotation: 8 }, { at: .45, x: 62, y: 47, scale: .65, rotation: -8 }, { at: .65, x: 67, scale: .65, rotation: 5 }, { at: 1, x: 67, scale: .65, rotation: 0 }], 'subject_2'),
    atmosphere(c, 'sparkles'),
  ],
  'music-magnet-pull': c => [
    movingSubject(c, [{ at: 0, x: 25, scale: .65 }, { at: .5, x: 27, scale: .65, rotation: 5 }, { at: 1, x: 26, scale: .65 }]),
    movingSubject(c, [{ at: 0, x: 95, scale: .55, rotation: -12, curve: 'dramatic' }, { at: .6, x: 48, scale: .65, rotation: 8 }, { at: .78, x: 57, scale: .65, rotation: -5 }, { at: 1, x: 51, scale: .65 }], 'subject_2'),
  ],
  // Played backwards, a swap is the swap back: a longer shot keeps trading places.
  'music-portal-swap': c => [
    movingSubject(c, repeatPath([{ at: 0, x: 24, scale: .68 }, { at: .3, x: 28, scale: .68 }, { at: .46, x: 28, scale: .01, opacity: 0, curve: 'hold' }, { at: .54, x: 72, scale: .01, opacity: 0 }, { at: .72, x: 72, scale: .68 }, { at: 1, x: 76, scale: .68 }], cycles(c), 'pingpong')),
    movingSubject(c, repeatPath([{ at: 0, x: 76, scale: .68 }, { at: .3, x: 72, scale: .68 }, { at: .46, x: 72, scale: .01, opacity: 0, curve: 'hold' }, { at: .54, x: 28, scale: .01, opacity: 0 }, { at: .72, x: 28, scale: .68 }, { at: 1, x: 24, scale: .68 }], cycles(c), 'pingpong'), 'subject_2'),
    atmosphere(c, 'sparkles'),
  ],
  'music-spotlight-relay': c => [movingSubject(c, relayPath(c, 0)), movingSubject(c, relayPath(c, 1), 'subject_2'), atmosphere(c, 'bokeh')],
  'music-staircase-pop': c => {
    const path = repeatPath(climb(), cycles(c), 'pingpong')
    return [movingSubject(c, path), followCamera(c, path)]
  },
  'music-accordion-clones': c => Array.from({ length: 5 }, (_, i) => copySubject(c, i, repeatPath([
    { at: 0, x: 50, scale: .45, opacity: i === 0 ? 1 : 0 },
    { at: .3, x: 50 + (i - 2) * 18, scale: .45, rotation: (i - 2) * 6 },
    { at: .65, x: 50 + (i - 2) * 18, scale: .45, rotation: -(i - 2) * 6 },
    { at: 1, x: 50, scale: .45, opacity: i === 0 ? 1 : 0 },
  ], cycles(c)))),
  'music-domino-wave': c => Array.from({ length: 5 }, (_, i) => copySubject(c, i, repeatPath([
    { at: 0, x: 14 + i * 18, y: 62, scale: .36, rotation: 0 },
    { at: .1 + i * .12, x: 14 + i * 18, y: 62, scale: .36, rotation: 0 },
    { at: .22 + i * .12, x: 14 + i * 18, y: 62, scale: .36, rotation: 65 },
    { at: .4 + i * .12, x: 14 + i * 18, y: 62, scale: .36, rotation: 0 },
    { at: 1, x: 14 + i * 18, y: 62, scale: .36, rotation: 0 },
  ], cycles(c)))),
  'music-conveyor': conveyor,
  // The crowd bobs at the authored pace whatever the shot length; the surfer crosses once.
  'music-crowd-surf': c => {
    const bobs = 2 * c.duration / c.base
    return [movingSubject(c, sampledPath(Math.max(24, Math.ceil(24 * c.duration / c.base)), at => ({
      x: 12 + 76 * at, y: 40 + 4 * Math.sin(at * Math.PI * 2 * bobs), scale: .64, rotation: 75 + 6 * Math.sin(at * Math.PI * 2 * bobs),
    }))), ...Array.from({ length: 5 }, (_, i) => copySubject(c, i, sampledPath(Math.max(16, Math.ceil(16 * c.duration / c.base)), at => ({
      x: 10 + i * 20, y: 87 - 4 * Math.sin(at * Math.PI * 2 * bobs + i), scale: .4,
    })), 'prop_1'))]
  },
}
