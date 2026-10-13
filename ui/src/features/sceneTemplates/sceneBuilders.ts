import type { SceneLayer, SceneKeyframe, SceneAtmosphereKind, SceneCatalogAssetReference } from '../../types'
// The i18next instance src/i18n initializes at app start. E2E specs load this module in Node,
// where src/i18n's locale JSON cannot load, so it is not imported here.
import i18n from 'i18next'
import type { ControlValue, TemplateAssetKind, TemplateSlotName } from './catalog'
import { ATMOSPHERE_OPACITY, ATMOSPHERE_PRESETS } from '../../lib/scene2d/layerStyle'

export interface TemplateAsset { source: string; type: TemplateAssetKind; name?: string; catalogAtAssignment?: SceneCatalogAssetReference }
export type TemplateBindings = Partial<Record<TemplateSlotName, TemplateAsset>>
export interface TemplateControls { duration: number; bpm: number; intensity: number }
export type Pose = Partial<Pick<SceneKeyframe, 'x' | 'y' | 'scale' | 'rotation' | 'opacity' | 'curve'>>
export type Beat = Pose & { at: number }
export interface BuildContext extends TemplateControls {
  bindings: TemplateBindings
  /** Every resolved control of the card (choices, texts, drift…), by name. */
  options: Readonly<Record<string, ControlValue>>
  /** The card's authored duration: motion written for it keeps its speed on longer shots. */
  base: number
}
const basePose = { x: 50, y: 50, scale: 1, rotation: 0, opacity: 1 }
const POSE_KEYS = ['x', 'y', 'scale', 'rotation', 'opacity'] as const

export function layer(id: string, type: SceneLayer['type'], source: string, duration: number, pose: Pose = {}, z = 10): SceneLayer {
  const transform = { ...basePose, ...pose }
  return { id, name: id, type, source, visible: true, z, parallax: 1, transform, animation: { start: transform, end: transform, duration, curve: 'ease' } }
}
export function keyframes(item: SceneLayer, beats: Beat[]): SceneLayer {
  const frames: SceneKeyframe[] = beats.map(({ at, ...pose }, i) => ({ id: `${item.id}-${i}`, time: at * item.animation.duration, ...basePose, ...item.transform, curve: 'ease', ...pose }))
  const endpoint = (frame: SceneKeyframe) => ({ ...item.transform, x: frame.x, y: frame.y, scale: frame.scale, rotation: frame.rotation, opacity: frame.opacity })
  return { ...item, animation: { ...item.animation,
    ...(frames.length ? { start: endpoint(frames[0]), end: endpoint(frames[frames.length - 1]) } : {}),
    keyframes: frames,
  } }
}
export function asset(ctx: BuildContext, slot: TemplateSlotName, pose: Pose = {}, z = 10): SceneLayer {
  const binding = ctx.bindings[slot]
  if (!binding) throw new Error(i18n.t('scene3d:templateErrors.missingSlotResource', { slot }))
  const item = layer(slot, binding.type, binding.source, ctx.duration, pose, z)
  item.name = `${slot} · ${binding.name || slot}`
  if (binding.type === 'model3d') item.transform = { ...item.transform, rotationX: 65, rotationY: -35 }
  // A video background is a seamless loop on its own clock, whatever the shot length.
  if (binding.type === 'video') item.playback = { start: 0, loop: 'loop', speed: 1 }
  return item
}

/** Repeats a choreography written for the card's own duration, so a longer shot repeats it instead of slowing it. */
export function cycles(ctx: BuildContext): number {
  return Math.max(1, Math.round(ctx.duration / ctx.base))
}

const samePose = (a: Pose, b: Pose) => POSE_KEYS.every(key => Math.abs((a[key] ?? 0) - (b[key] ?? 0)) < 1e-6 && (a[key] === undefined) === (b[key] === undefined))

function reversedPath(beats: Beat[]): Beat[] {
  return beats.map((_, index) => {
    const source = beats[beats.length - 1 - index]
    // The curve of a segment lives on its first keyframe; backwards, that is the next one.
    const reversed: Beat = { ...source, at: 1 - source.at }
    delete reversed.curve
    const segment = beats[beats.length - 2 - index]?.curve
    return segment ? { ...reversed, curve: segment } : reversed
  })
}

/** `times` copies of a 0..1 path in one 0..1 timeline. `pingpong` plays every other copy backwards; a copy that does
 * not start where the last one ended jumps (hold, then switch), which only suits paths that start and end off frame. */
export function repeatPath(beats: Beat[], times: number, mode: 'loop' | 'pingpong' = 'loop'): Beat[] {
  if (times <= 1) return beats
  const out: Beat[] = []
  const jump = .002 / times
  for (let cycle = 0; cycle < times; cycle += 1) {
    const path = mode === 'pingpong' && cycle % 2 ? reversedPath(beats) : beats
    path.forEach((beat, index) => {
      const at = (cycle + beat.at) / times
      if (!cycle || index) return void out.push({ ...beat, at })
      const previous = out[out.length - 1]
      if (samePose(previous, beat)) return
      out[out.length - 1] = { ...previous, curve: 'hold' }
      out.push({ ...beat, at: at + jump })
    })
  }
  return out
}

const CAMERA_BOUNDS = { x: [30, 70], y: [35, 65], scale: [.9, 1.6], rotation: [-8, 8] } as const

/** A longer shot travels further (up to twice the authored move, kept inside the frame) instead of moving slower. */
function reach(ctx: BuildContext, beats: Beat[]): Beat[] {
  const stretch = Math.min(2, Math.max(1, ctx.duration / ctx.base))
  if (stretch === 1 || !beats.length) return beats
  const first = { ...basePose, ...beats[0] }
  return beats.map(beat => {
    const out: Beat = { ...beat }
    for (const key of ['x', 'y', 'scale', 'rotation'] as const) {
      const value = beat[key]
      if (value === undefined) continue
      const [low, high] = CAMERA_BOUNDS[key]
      const stretched = first[key] + (value - first[key]) * stretch
      // The bounds never pull an authored pose back: they only stop the stretch.
      out[key] = Math.min(Math.max(stretched, Math.min(low, value)), Math.max(high, value))
    }
    return out
  })
}
export function camera(ctx: BuildContext, beats: Beat[], shake = 0): SceneLayer {
  const item = keyframes(layer('camera', 'camera', '', ctx.duration, {}, 100), reach(ctx, beats))
  if (shake) item.animation.shake = { amount: shake, frequency: 3, seed: 2 }
  return item
}
export function backdrop(ctx: BuildContext): SceneLayer {
  return { ...asset(ctx, 'background', { scale: 1.15 }, 0), fill: true, parallax: .25 }
}
export function foreground(ctx: BuildContext): SceneLayer[] {
  return ctx.bindings.foreground ? [{ ...asset(ctx, 'foreground', { scale: 1.12 }, 80), fill: true, parallax: 1.6 }] : []
}
/** The editor's own preset for the kind (density, size, speed, wind, opacity), so the particles read over a real
 * plate: a fixed 25 particles of size .6 at 35 % read on the plain demo art and vanished over real pictures. */
export function atmosphere(ctx: BuildContext, kind: SceneAtmosphereKind, color?: string): SceneLayer {
  const { density, speed, size, wind, color: presetColor } = ATMOSPHERE_PRESETS[kind]
  return { ...layer(`atmosphere-${kind}`, 'effect', '', ctx.duration, { opacity: ATMOSPHERE_OPACITY[kind] }, 60),
    atmosphere: { kind, density, speed, size, wind, color: color ?? presetColor } }
}
/** Pulses a layer on the visual BPM: on every beat, or only on the even or odd beats (two figures taking turns). */
export function pulse(ctx: BuildContext, item: SceneLayer, kind: 'bounce' | 'scale' = 'scale', on: 'all' | 'even' | 'odd' = 'all'): SceneLayer {
  if (item.animation.keyframes?.length) throw new Error(i18n.t('scene3d:templateErrors.pulseNeedsBase'))
  const beats: Beat[] = []
  const seconds = 60 / ctx.bpm
  const rest = { scale: item.transform.scale, y: item.transform.y }
  for (let time = 0, index = 0; time < ctx.duration; time += seconds, index += 1) {
    const active = on === 'all' || (index % 2 === 0) === (on === 'even')
    beats.push({ at: time / ctx.duration, ...rest })
    if (active) beats.push({ at: Math.min(1, (time + seconds * .2) / ctx.duration), ...(kind === 'scale' ? { scale: item.transform.scale * (1 + .09 * ctx.intensity) } : { y: item.transform.y - 3 * ctx.intensity }) })
    if (active) beats.push({ at: Math.min(1, (time + seconds * .8) / ctx.duration), ...rest })
  }
  beats.push({ at: 1 })
  return keyframes(item, beats.filter((beat, i) => !i || beat.at > beats[i - 1].at))
}

export const GRAPHIC_KINDS = ['beam', 'bolt', 'shield', 'burst', 'debris'] as const
export type GraphicKind = typeof GRAPHIC_KINDS[number]
/** The bolt is long (8:1) so a shot reads at a glance: a cyan glow, a bright body that fades to the tail and a
 * white-hot core. The thin square `beam` stays as it was for scenes that already use it. */
const GRAPHIC_SIZE: Record<GraphicKind, [number, number]> = { beam: [512, 512], bolt: [1024, 128], shield: [512, 512], burst: [512, 512], debris: [512, 512] }
function graphic(kind: GraphicKind): string {
  const shapes = {
    beam: '<path d="M15 256H497" stroke="#4deaff" stroke-width="18"/><path d="M15 256H497" stroke="white" stroke-width="5"/>',
    bolt: '<defs><linearGradient id="b" x2="1"><stop stop-color="#5ff0ff" stop-opacity="0"/><stop offset=".3" stop-color="#7ff6ff" stop-opacity=".9"/><stop offset="1" stop-color="#ffffff"/></linearGradient></defs><rect x="6" y="16" width="1012" height="96" rx="48" fill="#22d8ff" fill-opacity=".38"/><rect x="40" y="38" width="976" height="52" rx="26" fill="url(#b)"/><rect x="330" y="53" width="680" height="22" rx="11" fill="#ffffff"/>',
    shield: '<ellipse cx="256" cy="256" rx="215" ry="175" fill="#77dcff" fill-opacity=".08" stroke="#87ecff" stroke-width="8"/><ellipse cx="256" cy="256" rx="195" ry="156" fill="none" stroke="#eaffff" stroke-opacity=".5" stroke-width="2"/>',
    burst: '<defs><radialGradient id="f"><stop stop-color="#fff"/><stop offset=".15" stop-color="#fff0a1"/><stop offset=".42" stop-color="#ff9d48" stop-opacity=".95"/><stop offset="1" stop-color="#fa4127" stop-opacity="0"/></radialGradient></defs><circle cx="256" cy="256" r="254" fill="url(#f)"/><path d="M256 15L281 223L486 256L281 282L256 499L233 282L17 256L231 226Z" fill="#ffe0a5" opacity=".8"/>',
    debris: '<path d="M80 105l60 12-23 52-47-15ZM311 52l37 5 12 37-47-8ZM398 323l40 38-12 42-43-18ZM114 373l62-16 22 31-42 33ZM239 211l34-18 36 54-41 20Z" fill="#88919e" stroke="#e8aa7b" stroke-width="3"/>',
  }
  const [width, height] = GRAPHIC_SIZE[kind]
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">${shapes[kind]}</svg>`)}`
}
/** Every graphic source the builders emit, byte for byte: the review showcase accepts these and no other SVG. */
export const builtInGraphicSources = (): string[] => GRAPHIC_KINDS.map(graphic)

export function effect(ctx: BuildContext, kind: GraphicKind, id: string, beats: Beat[]): SceneLayer {
  return keyframes(layer(id, 'image', graphic(kind), ctx.duration, { opacity: 0 }, 35), beats)
}
