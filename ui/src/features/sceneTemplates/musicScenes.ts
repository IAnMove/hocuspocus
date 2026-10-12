import type { SceneAtmosphereKind, SceneLayer } from '../../types'
import { asset, atmosphere, camera, cycles, keyframes, layer, pulse, repeatPath, type BuildContext } from './sceneBuilders'

/** The `camera` choices of music-pulse; `sweep`, `open` and `beat` are the cameras of the merged stage, finale and chorus. */
function pulseCamera(c: BuildContext): SceneLayer {
  if (c.options.camera === 'sweep') return camera(c, [{ at: 0, x: 40, y: 54, scale: 1.25 }, { at: .5, x: 50, y: 48, scale: 1 }, { at: 1, x: 60, y: 54, scale: 1.2 }])
  if (c.options.camera === 'open') return camera(c, [{ at: 0, scale: 1.4, rotation: -3 }, { at: .5, scale: 1.14, rotation: 0 }, { at: 1, scale: 1 }])
  if (c.options.camera === 'beat') return pulse(c, layer('camera', 'camera', '', c.duration, { scale: 1.04 }, 100))
  return camera(c, [{ at: 0, scale: 1 }, { at: 1, scale: 1.08 }])
}

const PULSE_ATMOSPHERES: Record<string, [SceneAtmosphereKind, string?]> = { fireflies: ['fireflies'], confetti: ['confetti', '#ffcc87'], bokeh: ['bokeh'] }

function orbit(c: BuildContext): SceneLayer[] {
  const prop = asset(c, 'prop_1', { scale: .23 }, 12)
  // One model maximum per slot; only 2D props may have repeated instances. Turns follow the shot length.
  prop.animation.orbit = { targetLayerId: 'subject_1', radiusX: 29, radiusY: 18, turns: c.duration / c.base, phase: 0, count: prop.type === 'model3d' ? 1 : 5, facing: 'fixed' }
  const subject = asset(c, 'subject_1', { y: 62, scale: .8 })
  return [c.options.bounce === 'off' ? subject : pulse(c, subject, 'bounce'), prop, camera(c, [{ at: 0, scale: 1.02 }, { at: 1, scale: 1.1 }]), atmosphere(c, 'sparkles')]
}

export const musicScenes: Record<string, (ctx: BuildContext) => SceneLayer[]> = {
  'music-pulse': c => {
    const [kind, color] = PULSE_ATMOSPHERES[String(c.options.atmosphere)] ?? PULSE_ATMOSPHERES.fireflies
    return [pulse(c, asset(c, 'subject_1', { x: 50, y: 65, scale: .92 }), 'bounce'), pulseCamera(c), atmosphere(c, kind, color)]
  },
  // The two figures take turns: one jumps on the even beats, the other on the odd ones.
  'music-duet': c => [pulse(c, asset(c, 'subject_1', { x: 32, y: 62, scale: .86 }), 'bounce', 'even'), pulse(c, asset(c, 'subject_2', { x: 68, y: 62, scale: .86 }), 'bounce', 'odd'), camera(c, [{ at: 0, rotation: -1.5 }, { at: 1, rotation: 1.5 }])],
  'music-orbit': orbit,
  'music-product': c => {
    const hero = keyframes(asset(c, 'subject_1', { x: 62, y: 52, scale: .9 }), repeatPath([{ at: 0, rotation: -5 }, { at: 1, rotation: 5 }], cycles(c), 'pingpong'))
    if (hero.type === 'model3d') hero.animation = { ...hero.animation, spin: true, rotationSpeed: 30 }
    return [hero, ...(c.bindings.prop_1 ? [asset(c, 'prop_1', { x: 24, y: 59, scale: .3 }, 12)] : []), camera(c, [{ at: 0, x: 47, scale: 1.05 }, { at: 1, x: 52, scale: 1.2 }]), atmosphere(c, 'sparkles', '#ffc185')]
  },
}
