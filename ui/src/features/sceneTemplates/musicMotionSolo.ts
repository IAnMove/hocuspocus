import type { SceneLayer } from '../../types'
import { asset, atmosphere, camera, cycles, keyframes, repeatPath, type BuildContext, type Beat } from './sceneBuilders'
import { movingSubject, sampledPath } from './musicMotionBuilders'

type Point = [x: number, y: number, rotation: number]
const PINBALL: Point[] = [[18, 20, -15], [84, 75, 25], [72, 16, -20], [16, 72, 30], [24, 22, -10], [70, 68, 10]]
const RICOCHET: Point[] = [[30, 56, 0], [88, 23, 0], [12, 33, 0], [86, 77, 0], [15, 65, 0], [33, 53, 0]]

/** Straight bounces through the wall points, five per authored shot: a longer shot keeps bouncing at the same pace. */
function bounces(points: Point[], segments: number, scale: number): Beat[] {
  return Array.from({ length: segments + 1 }, (_, index) => {
    const [x, y, rotation] = points[index % points.length]
    return { at: index / segments, x, y, scale, rotation, ...(index < segments ? { curve: 'linear' as const } : {}) }
  })
}

/** `bouncer: prop` is the merged music-ricochet-pass: a small prop bounces and the figure follows it with a turn. */
function pinball(c: BuildContext): SceneLayer[] {
  const segments = 5 * cycles(c)
  if (c.options.bouncer !== 'prop') return [movingSubject(c, bounces(PINBALL, segments, .42))]
  const path = bounces(RICOCHET, segments, .18)
  const watch = path.map((beat, index) => ({ at: beat.at, rotation: ((beat.x ?? 50) - 50) * .1, y: 62 - (index % 2) * 1.2 }))
  return [keyframes(asset(c, 'subject_1', { x: 50, y: 62, scale: .7 }), watch), keyframes(asset(c, 'prop_1', { scale: .18 }, 20), path)]
}

export const musicMotionSolo: Record<string, (c: BuildContext) => SceneLayer[]> = {
  'music-spiral-exit': c => [movingSubject(c, sampledPath(32, at => {
    const radius = 22 * Math.sin(Math.PI * at) * (1 - at)
    return { x: 50 + radius * Math.sin(at * Math.PI * 4), y: 50 + radius * Math.cos(at * Math.PI * 4),
      scale: .025 + .875 * (1 - at) ** 1.5, rotation: 720 * at, opacity: at > .9 ? (1 - at) * 10 : 1 }
  })), atmosphere(c, 'sparkles')],
  // Off frame at both ends, so a longer shot flies past again instead of crawling across.
  'music-speed-flight': c => [movingSubject(c, repeatPath([
    { at: 0, x: -35, y: 57, rotation: -12, curve: 'linear' },
    { at: .25, x: 22, y: 51, rotation: -10, curve: 'linear' },
    { at: .7, x: 65, y: 48, rotation: -10, curve: 'linear' },
    { at: 1, x: 135, y: 43, rotation: -14 },
  ], cycles(c))), atmosphere(c, 'speedlines')],
  'music-infinite-fall': c => [movingSubject(c, repeatPath([
    { at: 0, x: 50, y: -45, scale: .95, rotation: -15, curve: 'dramatic' },
    { at: .3, x: 52, y: 43, scale: .8, rotation: 5, curve: 'linear' },
    { at: .7, x: 47, y: 65, scale: .5, rotation: -12, curve: 'dramatic' },
    { at: 1, x: 50, y: 145, scale: .12, rotation: 20 },
  ], cycles(c)))],
  'music-pinball': pinball,
  'music-boomerang': c => [movingSubject(c, repeatPath(sampledPath(24, at => ({
    x: 22 + 62 * Math.sin(Math.PI * at), y: 58 - 27 * Math.sin(Math.PI * 2 * at),
    scale: .65 - .32 * Math.sin(Math.PI * at), rotation: 360 * at,
  })), cycles(c)))],
  'music-cannon-launch': c => [movingSubject(c, [
    { at: 0, x: 20, y: 78, scale: .6, rotation: -20 },
    { at: .25, x: 16, y: 82, scale: .48, rotation: -30, curve: 'dramatic' },
    { at: .5, x: 52, y: 20, scale: .7, rotation: 5, curve: 'linear' },
    { at: .7, x: 76, y: 8, scale: .56, rotation: 20, curve: 'dramatic' },
    { at: 1, x: 135, y: 60, scale: .4, rotation: 65 },
  ]), atmosphere(c, 'embers')],
  'music-trampoline': c => [movingSubject(c, repeatPath([
    { at: 0, y: 70, scale: .68 }, { at: .16, y: 76, scale: .56 },
    { at: .35, y: 17, scale: .72, rotation: -8 }, { at: .6, y: 76, scale: .56 },
    { at: .8, y: 27, scale: .72, rotation: 8 }, { at: 1, y: 70, scale: .68 },
  ], cycles(c)))],
  'music-pendulum': c => [movingSubject(c, repeatPath(sampledPath(32, at => {
    const angle = Math.sin(at * Math.PI * 4) * .7
    return { x: 50 + Math.sin(angle) * 42, y: 16 + Math.cos(angle) * 48, scale: .68, rotation: -angle * 40 }
  }), cycles(c)))],
  'music-rubber-band': c => [movingSubject(c, repeatPath([
    { at: 0, x: 50, rotation: 0 }, { at: .35, x: 16, rotation: -22, curve: 'dramatic' },
    { at: .48, x: 85, rotation: 18 }, { at: .62, x: 30, rotation: -12 },
    { at: .76, x: 64, rotation: 7 }, { at: .89, x: 44, rotation: -3 }, { at: 1, x: 50, rotation: 0 },
  ], cycles(c)))],
  'music-card-toss': c => [movingSubject(c, repeatPath([
    { at: 0, x: -40, y: 90, scale: .32, rotation: -140, opacity: 0 },
    { at: .3, x: 48, y: 47, scale: .82, rotation: 8 },
    { at: .48, x: 50, y: 52, scale: .8, rotation: -3 },
    { at: .7, x: 50, y: 52, scale: .8, rotation: 0, curve: 'dramatic' },
    { at: 1, x: 140, y: -35, scale: .38, rotation: 130, opacity: 0 },
  ], cycles(c)))],
  'music-corkscrew-rise': c => [movingSubject(c, repeatPath(sampledPath(36, at => ({
    x: 50 + 22 * Math.sin(at * Math.PI * 6), y: 110 - 130 * at,
    scale: .6 + .12 * Math.cos(at * Math.PI * 6), rotation: 16 * Math.cos(at * Math.PI * 6),
  })), cycles(c))), atmosphere(c, 'bubbles')],
  'music-shockwave': c => [movingSubject(c, [
    { at: 0, y: 63, scale: .55 }, { at: .3, y: 66, scale: .5 },
    { at: .45, y: 49, scale: 1.25, rotation: -4 }, { at: .62, y: 55, scale: .88, rotation: 2 },
    { at: 1, y: 55, scale: .9, rotation: 0 },
  ]), camera(c, [{ at: 0, scale: 1 }, { at: .3, scale: 1 }, { at: .45, scale: 1.15 }, { at: 1, scale: 1 }]), atmosphere(c, 'confetti')],
}
