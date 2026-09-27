import bases from '../../../../app/shared/scene_bases.json' with { type: 'json' }
import { FX_CATALOG, parseSceneFx } from './types'

export type FxShowcaseCollection = 'all' | 'anime' | 'retro'

/** Non-destructive to actors/cameras/audio; the authored effect track is replaced explicitly. */
export function withFxShowcase<T extends { duration: number }>(document: T, collection: FxShowcaseCollection = 'all'): T & { sfx: ReturnType<typeof parseSceneFx> } {
  const presets = FX_CATALOG.filter(preset => collection === 'all' || preset.collection === collection)
  const duration = Math.max(document.duration, presets.length * 3)
  const layers = structuredClone(bases['2d'].layers)
  layers[0].animation.duration = duration
  return { ...document, ...('layers' in document && Array.isArray(document.layers) && !document.layers.length ? { layers } : {}), duration,
    sfx: parseSceneFx(presets.map((preset, i) => ({ id: `showcase-${preset.id}`, kind: preset.id,
      label: preset.id.replace('speedlines', 'speed lines').toUpperCase(), start: i * 3, end: i * 3 + 2.8, color: preset.color, size: 95, sound: true, seed: i + 17 }))) }
}

/** Server/MCP showcase commands omit `document` and return a stock base. */
export function isFxShowcaseDocument(document: unknown): boolean {
  if (!document || typeof document !== 'object' || Array.isArray(document)) return false
  const cues = (document as { sfx?: unknown }).sfx
  if (!Array.isArray(cues) || cues.length < 8) return false
  return cues.every(cue => Boolean(cue && typeof cue === 'object' && String((cue as { id?: unknown }).id ?? '').startsWith('showcase-')))
}

export function showcaseCollectionFrom(document: unknown): FxShowcaseCollection {
  const anime = new Set(FX_CATALOG.filter(preset => preset.collection === 'anime').map(preset => preset.id))
  const retro = new Set(FX_CATALOG.filter(preset => preset.collection === 'retro').map(preset => preset.id))
  const cues = document && typeof document === 'object' && !Array.isArray(document)
    ? (document as { sfx?: { kind?: string }[] }).sfx : undefined
  const kinds = Array.isArray(cues) ? cues.map(cue => cue?.kind).filter((kind): kind is string => Boolean(kind)) : []
  if (kinds.length > 0 && kinds.length <= 12 && kinds.every(kind => anime.has(kind))) return 'anime'
  if (kinds.length > 0 && kinds.length <= 12 && kinds.every(kind => retro.has(kind))) return 'retro'
  return 'all'
}

/** Layers, speakers, audio or SFX the user already authored in the open editor. */
export function sceneHasAuthoredContent(document: unknown): boolean {
  if (!document || typeof document !== 'object' || Array.isArray(document)) return false
  const value = document as Record<string, unknown>
  if (Array.isArray(value.layers) && value.layers.some(layer => (
    layer && typeof layer === 'object'
    && (layer as { type?: string }).type !== 'camera'
    && String((layer as { source?: string }).source ?? '').trim()
  ))) return true
  if (Array.isArray(value.slots) && value.slots.some(slot => {
    if (!slot || typeof slot !== 'object') return false
    const item = slot as { sourceUrl?: string; speech?: unknown; screen?: { sourceUrl?: string } }
    return Boolean(String(item.sourceUrl ?? '').trim() || item.speech || String(item.screen?.sourceUrl ?? '').trim())
  })) return true
  return Boolean(value.production)
    || ['sfx', 'worldSfx', 'texts', 'soundtrack'].some(key => Array.isArray(value[key]) && (value[key] as unknown[]).length > 0)
}

/** Keep the open scene when Wizard/MCP presents a stock showcase without its document. */
export function adoptPreparedSceneDocument<T extends { duration: number }>(current: T, incoming: T): { mode: 'retain' | 'replace'; document: T } {
  if (isFxShowcaseDocument(incoming) && sceneHasAuthoredContent(current)) {
    return { mode: 'retain', document: withFxShowcase(current, showcaseCollectionFrom(incoming)) }
  }
  return { mode: 'replace', document: incoming }
}
