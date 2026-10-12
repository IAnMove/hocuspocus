import type { SceneLayer } from '../../types'
import { asset, atmosphere, camera, keyframes, repeatPath, type Beat, type BuildContext } from './sceneBuilders'

const ENTRANCES: Record<string, Beat[]> = {
  rise: [{ at: 0, y: 98, opacity: 0 }, { at: .12, y: 90, opacity: 1 }, { at: .45, y: 67 }, { at: 1, y: 65 }],
  left: [{ at: 0, x: -12, rotation: -3 }, { at: .45, x: 47, rotation: 1 }, { at: .6, x: 50, rotation: 0 }, { at: 1, x: 51 }],
  right: [{ at: 0, x: 112, rotation: 3 }, { at: .45, x: 53, rotation: -1 }, { at: .6, x: 50, rotation: 0 }, { at: 1, x: 49 }],
}

/** A small idle sway (breath, weight shift) on a ~2.6 s cycle that repeats on longer shots. */
function idle(c: BuildContext, phase: number): Beat[] {
  const swing = Array.from({ length: 13 }, (_, index) => {
    const turn = index / 12 * Math.PI * 2 + phase
    return { at: index / 12, curve: 'linear' as const, rotation: 1.4 * Math.sin(turn), y: 64 - .6 * Math.sin(turn * 2), scale: .88 * (1 + .01 * Math.cos(turn)) }
  })
  return repeatPath(swing, Math.max(1, Math.round(c.duration / 2.6)))
}

/** These are shot grammars, not a second renderer: every result is editable
 * using the existing scene timeline, camera and normal asset layers. */
export const cinemaScenes: Record<string, (ctx: BuildContext) => SceneLayer[]> = {
  'cinema-establishing': c => c.options.mood === 'lonely'
    ? [asset(c, 'subject_1', { x: 48, y: 66, scale: .4 }), camera(c, [{ at: 0, y: 52, scale: 1.35 }, { at: 1, y: 42, scale: 1 }]), atmosphere(c, 'rain')]
    : [asset(c, 'subject_1', { x: 68, y: 70, scale: .48 }), camera(c, [{ at: 0, x: 46, scale: 1.1 }, { at: 1, x: 54, scale: 1 }]), atmosphere(c, 'dust')],
  'cinema-reveal': c => [keyframes(asset(c, 'subject_1', { x: 64, y: 64, scale: .86 }), [{ at: 0, x: 70, opacity: 0 }, { at: .3, x: 67, opacity: 1 }, { at: 1, x: 57 }]), camera(c, [{ at: 0, x: 40, scale: 1.14 }, { at: 1, x: 58, scale: 1.04 }])],
  'cinema-closeup': c => [asset(c, 'subject_1', { x: 62, y: 95, scale: 1.9 }), camera(c, [{ at: 0, x: 49, scale: 1 }, { at: 1, x: 51, y: 49, scale: 1.08 }]), atmosphere(c, 'bokeh', '#ffe5c3')],
  // A slow arc with a push: the plate (parallax .25), the pair and the foreground (1.6) separate as the camera turns.
  'cinema-two-shot': c => [
    keyframes(asset(c, 'subject_1', { x: 33, y: 64, scale: .88 }), idle(c, 0)),
    keyframes(asset(c, 'subject_2', { x: 68, y: 64, scale: .88 }), idle(c, 2.1)),
    camera(c, [{ at: 0, x: 44, y: 51, scale: 1, rotation: -1.2 }, { at: .5, x: 50, y: 49, scale: 1.06, rotation: 0 }, { at: 1, x: 56, y: 50, scale: 1.1, rotation: 1.2 }]),
  ],
  'cinema-detail': c => [asset(c, 'subject_1', { x: 63, y: 59, scale: 1.35 }), camera(c, [{ at: 0, x: 44, y: 52, scale: 1.28 }, { at: 1, x: 54, y: 48, scale: 1.13 }])],
  'cinema-hero': c => [
    keyframes(asset(c, 'subject_1', { x: 50, y: 66, scale: 1.04 }), ENTRANCES[String(c.options.entrance)] ?? ENTRANCES.rise),
    camera(c, [{ at: 0, y: 62, scale: 1.17 }, { at: 1, y: 47, scale: 1.02 }]),
    atmosphere(c, 'embers', '#fbc387'),
  ],
  'cinema-tracking': c => [
    keyframes(asset(c, 'subject_1', { x: 28, y: 65, scale: .85 }), [{ at: 0, x: 28 }, { at: 1, x: 72 }]),
    camera(c, [{ at: 0, x: 39, scale: 1.1 }, { at: 1, x: 61, scale: 1.1 }]),
    c.options.atmosphere === 'streaks' ? atmosphere(c, 'speedlines') : atmosphere(c, 'leaves', '#e3a475'),
  ],
}
