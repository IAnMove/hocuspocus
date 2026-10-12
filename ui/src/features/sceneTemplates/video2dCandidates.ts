// Video 2D cards with titles and a finish (documentary-history, city-postcard). Their plates move: a slow push or a
// sideways drift with parallax against the subject and the foreground, and their texts are controls.
import { buildTextTemplate, type KineticText } from '../../lib/kineticText'
import type { Scene, SceneLayer } from '../../types'
import { FINISH_PRESETS } from '../../lib/scene2d/finish'
import { asset, keyframes, layer, type Beat, type BuildContext, type Pose } from './sceneBuilders'

export type Video2dFrame = { width?: number; height?: number }
type Video2dBody = Pick<Scene, 'width' | 'height' | 'fps' | 'layers' | 'texts' | 'finish'>

/** Travel per authored shot; a longer shot travels further at the same speed, up to twice as far. */
function glide(c: BuildContext, from: Pose, to: Pose): Beat[] {
  const stretch = Math.min(2, c.duration / c.base)
  const along = (key: 'x' | 'y' | 'scale') => (from[key] ?? 0) + ((to[key] ?? 0) - (from[key] ?? 0)) * stretch
  return [{ at: 0, ...from, curve: 'linear' }, { at: 1, x: along('x'), y: along('y'), scale: along('scale') }]
}

function moving(c: BuildContext, slot: 'subject_1' | 'background' | 'foreground', from: Pose, to: Pose, z: number, fill: boolean, parallax = 1): SceneLayer {
  return { ...keyframes(asset(c, slot, from, z), glide(c, from, to)), fill, parallax }
}

function particles(c: BuildContext, kind: 'dust' | 'leaves'): SceneLayer {
  return { ...layer(`atmosphere-${kind}`, 'effect', '', c.duration, {}, 20), atmosphere: { kind, density: 24, speed: .4, size: 1.2, wind: 4, color: '#dbe7f5' } }
}

const text = (c: BuildContext, key: string) => String(c.options[key] ?? '').trim()

type Frame = { start: number; duration: number; width: number; height: number }
type Placement = Partial<Pick<KineticText, 'x' | 'y' | 'size' | 'align' | 'maxWidth'>>
const tall = (frame: Frame) => frame.height > frame.width

/** Moves the cues a text template built so they sit beside the card's subject, never over it. */
function placed(cues: KineticText[], where: Record<string, Placement>): KineticText[] {
  return cues.map(cue => ({ ...cue, ...where[cue.id] }))
}

// The archive photo stays centred and leaves the corners free: the counter in the top right, the date and the
// caption in the bottom left (below the photo on a tall frame, where the sides are too narrow).
const DOCUMENTARY_SUBJECT = { wide: [{ x: 51, y: 44, scale: .64 }, { x: 50, y: 43.5, scale: .68 }], tall: [{ x: 50, y: 42, scale: .42 }, { x: 50, y: 41.5, scale: .45 }] }
const DOCUMENTARY_TEXT: Record<'wide' | 'tall', Record<string, Placement>> = {
  wide: {
    count: { x: 95, y: 13, size: 12, align: 'right' }, label: { x: 95, y: 23, size: 4, align: 'right' },
    date: { x: 5, y: 80, size: 10, align: 'left' }, caption: { x: 5, y: 88, size: 4.5, align: 'left', maxWidth: 32 },
  },
  tall: {
    count: { x: 95, y: 12, size: 5.5, align: 'right' }, label: { x: 95, y: 17, size: 3, align: 'right' },
    date: { x: 6, y: 71, size: 6, align: 'left' }, caption: { x: 6, y: 78, size: 3.4, align: 'left', maxWidth: 86 },
  },
}

function documentary(c: BuildContext, frame: Frame): Video2dBody {
  const [caption, from, to, label] = ['caption', 'yearFrom', 'yearTo', 'yearLabel'].map(key => text(c, key))
  const shape = tall(frame) ? 'tall' : 'wide'
  const [photoFrom, photoTo] = DOCUMENTARY_SUBJECT[shape]
  const layers = [
    // Ken Burns with parallax: the plate pushes slowest, the photo counters, the foreground passes fastest.
    moving(c, 'background', { x: 49, y: 50, scale: 1.12 }, { x: 51.5, y: 49, scale: 1.2 }, 0, true, .3),
    moving(c, 'subject_1', photoFrom, photoTo, 10, false),
    ...(c.bindings.foreground ? [moving(c, 'foreground', { x: 47, y: 50, scale: 1.14 }, { x: 54, y: 50, scale: 1.24 }, 80, true, 1.6)] : []),
    particles(c, 'dust'),
  ]
  // An empty field adds nothing (the text templates would fall back to sample words); the counter needs two numbers.
  const counts = [from, to].every(value => value && Number.isFinite(Number(value)))
  const texts = placed([
    ...buildTextTemplate('lower-third-date', { date: to, caption }, frame).filter(cue => (cue.id === 'date' ? to : caption)),
    ...(counts ? buildTextTemplate('year-counter', { from, to, label }, frame) : []),
  ], DOCUMENTARY_TEXT[shape])
  return { width: frame.width, height: frame.height, fps: 24, layers, texts, finish: FINISH_PRESETS.oldDoc }
}

function postcard(c: BuildContext, frame: Frame): Video2dBody {
  const leaves = { ...particles(c, 'leaves'), strip: { enabled: true, count: 3, spacing: 30, direction: 'left' as const, speed: 6 },
    animation: { start: { x: 20, y: 60, scale: 1, opacity: 1 }, end: { x: 80, y: 40, scale: 1, opacity: 1 }, duration: c.duration, curve: 'ease' as const, path: { points: [{ x: 15, y: 70 }, { x: 40, y: 42 }, { x: 78, y: 58 }], orient: true } } }
  const layers = [
    // The city drifts sideways; the figure and the foreground cross it at their own depths.
    moving(c, 'background', { x: 54, y: 50, scale: 1.2 }, { x: 47, y: 49, scale: 1.22 }, 0, true, .3),
    // The figure stands low enough that the banner fits above its head.
    moving(c, 'subject_1', { x: 51, y: 62, scale: .66 }, { x: 48.5, y: 62, scale: .67 }, 10, false),
    ...(c.bindings.foreground ? [moving(c, 'foreground', { x: 58, y: 50, scale: 1.16 }, { x: 43, y: 50, scale: 1.16 }, 80, true, 1.6)] : []),
    leaves,
  ]
  const banner = text(c, 'banner')
  return {
    width: frame.width, height: frame.height, fps: 24, layers,
    texts: banner ? placed(buildTextTemplate('chorus-banner', { line: banner }, frame), { chorus: { y: 13 } }) : [],
    finish: { ...FINISH_PRESETS.paperComic, rays: { amount: 0.25, x: 70, y: 20, length: 0.4, threshold: 0.7 } },
  }
}

export const video2dScenes: Record<string, (c: BuildContext, frame: Video2dFrame) => Video2dBody> = {
  'documentary-history': (c, size) => documentary(c, { start: 0, duration: c.duration, width: size.width ?? 1920, height: size.height ?? 1080 }),
  'city-postcard': (c, size) => postcard(c, { start: 0, duration: c.duration, width: size.width ?? 1920, height: size.height ?? 1080 }),
}
