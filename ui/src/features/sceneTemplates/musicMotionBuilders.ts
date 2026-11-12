import type { SceneLayer } from '../../types'
import { asset, backdrop, keyframes, type Beat, type BuildContext, type Pose } from './sceneBuilders'
import type { TemplateSlotName } from './catalog'

/** These are screen-space cutout choreographies, not skeletal animation. */
export function movingSubject(c: BuildContext, points: Beat[], slot: TemplateSlotName = 'subject_1'): SceneLayer {
  return keyframes(asset(c, slot, { y: 56, scale: .8 }), points)
}

export function sampledPath(samples: number, pose: (at: number) => Pose): Beat[] {
  return Array.from({ length: samples + 1 }, (_, index) => {
    const at = index / samples
    return { at, curve: 'linear', ...pose(at) }
  })
}

export function copySubject(c: BuildContext, index: number, points: Beat[], slot: TemplateSlotName = 'subject_1'): SceneLayer {
  const source = asset(c, slot, { y: 56, scale: .45 })
  const id = index === 0 ? slot : `${slot}-copy-${index}`
  return keyframes({ ...source, id, name: `${source.name} · copia ${index + 1}` }, points)
}

/** A stable overscan underlay covers the viewport even at strip endpoints; no new
 * textures or providers are consulted. Real plates are not seamless, so the copies
 * touch and every other one is mirrored along the scroll axis: each join shows the
 * same pixels on both sides. A video background already moves, so it plays as one
 * looping layer without a strip. */
export function musicMotionBackground(id: string, c: BuildContext): SceneLayer[] {
  const base = backdrop(c)
  const scrolling: Record<string, NonNullable<SceneLayer['strip']>['direction']> = {
    'music-speed-flight': 'left', 'music-infinite-fall': 'up', 'music-conveyor': 'left',
  }
  const direction = scrolling[id]
  if (!direction || base.type === 'video') return [base]
  const strip = { ...base, id: 'background-scroll', name: 'background · desplazamiento', z: 1,
    // A filled copy is the frame times its scale on both axes, so this spacing makes the copies touch.
    strip: { enabled: true, count: 4, spacing: 100 * base.transform.scale, direction, speed: id === 'music-conveyor' ? 28 : 95, phase: 0, mirror: true },
  }
  return [base, strip]
}
