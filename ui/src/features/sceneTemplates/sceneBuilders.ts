import type { SceneLayer, SceneKeyframe, SceneAtmosphereKind, SceneCatalogAssetReference } from '../../types'
import type { TemplateSlotName } from './catalog'

export interface TemplateAsset { source: string; type: 'image' | 'model3d'; name?: string; catalogAtAssignment?: SceneCatalogAssetReference }
export type TemplateBindings = Partial<Record<TemplateSlotName, TemplateAsset>>
export interface TemplateControls { duration: number; bpm: number; intensity: number }
export type Pose = Partial<Pick<SceneKeyframe, 'x' | 'y' | 'scale' | 'rotation' | 'opacity' | 'curve'>>
export type Beat = Pose & { at: number }
export interface BuildContext extends TemplateControls { bindings: TemplateBindings }
const basePose = { x: 50, y: 50, scale: 1, rotation: 0, opacity: 1 }

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
  if (!binding) throw new Error(`The resource for slot ${slot} is missing.`)
  const item = layer(slot, binding.type, binding.source, ctx.duration, pose, z)
  item.name = `${slot} · ${binding.name || slot}`
  if (binding.type === 'model3d') item.transform = { ...item.transform, rotationX: 65, rotationY: -35 }
  return item
}
export function camera(ctx: BuildContext, beats: Beat[], shake = 0): SceneLayer {
  const item = keyframes(layer('camera', 'camera', '', ctx.duration, {}, 100), beats)
  if (shake) item.animation.shake = { amount: shake, frequency: 3, seed: 2 }
  return item
}
export function backdrop(ctx: BuildContext): SceneLayer {
  return { ...asset(ctx, ctx.bindings.background ? 'background' : 'plate', { scale: 1.15 }, 0), fill: true, parallax: .25 }
}
export function foreground(ctx: BuildContext): SceneLayer[] {
  return ctx.bindings.foreground ? [{ ...asset(ctx, 'foreground', { scale: 1.12 }, 80), fill: true, parallax: 1.6 }] : []
}
export function atmosphere(ctx: BuildContext, kind: SceneAtmosphereKind, color = '#b9d5ff'): SceneLayer {
  return { ...layer(`atmosphere-${kind}`, 'effect', '', ctx.duration, { opacity: .35 }, 60), atmosphere: { kind, density: 25, speed: .5, size: .6, wind: 1, color } }
}
export function pulse(ctx: BuildContext, item: SceneLayer, kind: 'bounce' | 'scale' = 'scale'): SceneLayer {
  if (item.animation.keyframes?.length) throw new Error('The pulse needs a base pose; it does not replace existing keyframes.')
  const beats: Beat[] = []
  const seconds = 60 / ctx.bpm
  for (let time = 0; time < ctx.duration; time += seconds) {
    beats.push({ at: time / ctx.duration, scale: item.transform.scale, y: item.transform.y })
    beats.push({ at: Math.min(1, (time + seconds * .2) / ctx.duration), ...(kind === 'scale' ? { scale: item.transform.scale * (1 + .09 * ctx.intensity) } : { y: item.transform.y - 3 * ctx.intensity }) })
    beats.push({ at: Math.min(1, (time + seconds * .8) / ctx.duration), scale: item.transform.scale, y: item.transform.y })
  }
  beats.push({ at: 1 })
  return keyframes(item, beats.filter((beat, i) => !i || beat.at > beats[i - 1].at))
}

function graphic(kind: 'beam' | 'shield' | 'burst' | 'debris'): string {
  const shapes = {
    beam: '<path d="M15 256H497" stroke="#4deaff" stroke-width="18"/><path d="M15 256H497" stroke="white" stroke-width="5"/>',
    shield: '<ellipse cx="256" cy="256" rx="215" ry="175" fill="#77dcff" fill-opacity=".08" stroke="#87ecff" stroke-width="8"/><ellipse cx="256" cy="256" rx="195" ry="156" fill="none" stroke="#eaffff" stroke-opacity=".5" stroke-width="2"/>',
    burst: '<defs><radialGradient id="f"><stop stop-color="#fff"/><stop offset=".15" stop-color="#fff0a1"/><stop offset=".42" stop-color="#ff9d48" stop-opacity=".95"/><stop offset="1" stop-color="#fa4127" stop-opacity="0"/></radialGradient></defs><circle cx="256" cy="256" r="254" fill="url(#f)"/><path d="M256 15L281 223L486 256L281 282L256 499L233 282L17 256L231 226Z" fill="#ffe0a5" opacity=".8"/>',
    debris: '<path d="M80 105l60 12-23 52-47-15ZM311 52l37 5 12 37-47-8ZM398 323l40 38-12 42-43-18ZM114 373l62-16 22 31-42 33ZM239 211l34-18 36 54-41 20Z" fill="#88919e" stroke="#e8aa7b" stroke-width="3"/>',
  }
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512">${shapes[kind]}</svg>`)}`
}
export function effect(ctx: BuildContext, kind: 'beam' | 'shield' | 'burst' | 'debris', id: string, beats: Beat[]): SceneLayer {
  return keyframes(layer(id, 'image', graphic(kind), ctx.duration, { opacity: 0 }, 35), beats)
}
