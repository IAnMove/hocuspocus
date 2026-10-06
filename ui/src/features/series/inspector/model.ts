import * as api from '../../../api/client'
import type { SeriesLineVoice, SeriesShotScript } from '../../../api/seriesShotInspector'
import type { CharacterKitLibrary } from '../../../lib/characterKit'
import { seriesAssetUrl } from '../referenceImages'
import type { SeriesAsset, SeriesEpisode, SeriesProject, SeriesRenderAttempt, SeriesScoreCue, SeriesShot } from '../types'
import type { SectionDraft, SectionKey } from './inspectorStore'

/**
 * The shot inspector's model: which parts a shot has, each part as the script keys its edit sends (the vocabulary of
 * series.shot.update), what changed, what the next render regenerates, and the pictures of a shot without a take.
 */
export const SECTION_FIELDS: Record<SectionKey, readonly string[]> = {
  plan: ['framing', 'camera', 'timing', 'duration'],
  cast: ['cast'],
  cast3d: ['scene3d'],
  lines: ['lines'],
  set: ['location', 'variant', 'layers', 'castDepth'],
  props: ['props'],
  fx: ['fx'],
  sfx: ['sfx'],
  sound: ['music', 'foley', 'voiceRoom'],
  card: ['card'],
  scene3d: ['scene3d'],
  video: ['clipAudio', 'clipVolume', 'clipFit'],
}

/** The part a script key belongs to (the first that edits it), to name a saved change. */
export function keyPart(key: string): SectionKey | undefined {
  return (Object.keys(SECTION_FIELDS) as SectionKey[]).find(section => SECTION_FIELDS[section].includes(key))
}

/** Keys whose empty list means something (a shot's own `layers: []` turns its location's layers off). */
const EMPTY_LIST_KEPT = new Set(['layers'])
export const VIDEO_METHODS = new Set(['generated_video', 'imported_video'])

export type InspectorPart = SectionKey | 'takes'

/** The parts of a shot, in the order the inspector shows them. */
export function shotParts(shot: SeriesShot, script: SeriesShotScript | undefined): InspectorPart[] {
  const method = shot.productionMethod || 'generated_video'
  if (VIDEO_METHODS.has(method)) return ['video', 'lines', 'set', 'sfx', 'sound', 'takes']
  if (method === 'animation_3d') return ['scene3d', 'cast3d', 'lines', 'set', 'fx', 'sfx', 'sound', 'plan', 'takes']
  return ['cast', 'lines', 'set', 'props', 'fx', 'sfx', 'sound', 'plan', ...(script?.card ? ['card' as const] : []), 'takes']
}

export function stableJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(',')}]`
  if (value && typeof value === 'object') {
    return `{${Object.keys(value).sort().filter(key => (value as Record<string, unknown>)[key] !== undefined)
      .map(key => `${JSON.stringify(key)}:${stableJson((value as Record<string, unknown>)[key])}`).join(',')}}`
  }
  return JSON.stringify(value ?? null)
}

/** The keys of one part as they are now (copies, so a draft never edits the shot). */
export function sectionSlice(script: SeriesShotScript | undefined, section: SectionKey): SectionDraft {
  const slice: SectionDraft = {}
  for (const key of SECTION_FIELDS[section]) if (script?.[key] !== undefined) slice[key] = structuredClone(script[key])
  return slice
}

function emptied(key: string, value: unknown): boolean {
  if (value === undefined || value === null || value === '') return true
  if (Array.isArray(value) && !value.length) return !EMPTY_LIST_KEPT.has(key)
  return typeof value === 'object' && !Array.isArray(value) && !Object.keys(value as object).length
}

/** What a part's draft changes, for series.shot.update `changes` (null removes a key); null when nothing changed. */
export function sectionChanges(section: SectionKey, draft: SectionDraft, script: SeriesShotScript | undefined): Record<string, unknown> | null {
  const changes: Record<string, unknown> = {}
  for (const key of SECTION_FIELDS[section]) {
    const before = emptied(key, script?.[key]) ? null : script?.[key]
    const after = emptied(key, draft[key]) ? null : draft[key]
    if (stableJson(before) !== stableJson(after)) changes[key] = after
  }
  return Object.keys(changes).length ? changes : null
}

/** The script keys of a line that are not a language (who, delivery, emotion, pause, room). */
const LINE_FIELDS = new Set(['who', 'emotion', 'delivery', 'pauseBefore', 'voiceRoom'])

export function lineLanguages(line: Record<string, unknown>): string[] {
  return Object.keys(line).filter(key => !LINE_FIELDS.has(key) && typeof line[key] === 'string')
}

export function lineText(line: Record<string, unknown>, language: string): string {
  const value = line[language]
  return typeof value === 'string' ? value : ''
}

/** The series' own language key of the script's lines: the voices' language, else the one every line has. */
export function originalLanguage(lines: Array<Record<string, unknown>> | undefined, known?: string): string {
  if (known) return known
  const counts = new Map<string, number>()
  for (const line of lines || []) for (const language of lineLanguages(line)) counts.set(language, (counts.get(language) || 0) + 1)
  return [...counts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] || 'spanish'
}

export interface TakeEntry {
  attempt: SeriesRenderAttempt
  asset: SeriesAsset
  url: string
  thumbnail: string
  number: number
  sceneFilename?: string
}

/** Every finished take of the shot with its video, newest first, numbered in the order they were made. */
export function shotTakes(series: SeriesProject, shot: SeriesShot): TakeEntry[] {
  const takes: TakeEntry[] = []
  shot.attempts.forEach((attempt, index) => {
    if (attempt.status !== 'completed') return
    const asset = attempt.outputAssetIds.map(id => series.assets[id]).find(item => item?.kind === 'video')
    if (!asset) return
    const filename = asset.uri.replace(/^outputs\//, '')
    const scene = asset.metadata?.sceneFilename
    takes.push({ attempt, asset, number: index + 1, url: api.getFileUrl(filename, asset.workspaceId),
      thumbnail: api.getOutputThumbnailUrl(filename, asset.workspaceId), sceneFilename: typeof scene === 'string' && scene ? scene : undefined })
  })
  return takes.reverse()
}

export function takeTime(attempt: SeriesRenderAttempt | undefined): number {
  const value = attempt ? Date.parse(attempt.completedAt || attempt.createdAt || '') : NaN
  return Number.isFinite(value) ? value : 0
}

/** The picture a 2D shot is drawn on: the location plate (a video), its background, the variant's or its own image. */
export function planBackground(series: SeriesProject, shot: SeriesShot): { url: string; video: boolean } | undefined {
  const location = series.locations.find(item => item.id === shot.locationId)
  if (!location) return undefined
  const variant = location.variants.find(item => item.id === shot.locationVariantId)
  const ids = [location.layout2d?.plateAssetId, location.layout2d?.backgroundAssetId, ...(variant?.referenceAssetIds || []),
    ...location.referenceAssetIds]
  for (const id of ids) {
    const asset = id ? series.assets[id] : undefined
    if (!asset?.uri || !['image', 'video', 'location'].includes(asset.kind)) continue
    if (asset.kind === 'video') return { url: api.getOutputThumbnailUrl(asset.uri.replace(/^outputs\//, ''), asset.workspaceId), video: true }
    return { url: seriesAssetUrl(asset), video: false }
  }
  return undefined
}

export interface PlanFigure { characterId: string; name: string; src?: string; x: number; scale: number }

/** A cast member's pose drawing: the pose the plan names, else the kit's base. */
function poseSource(series: SeriesProject, kits: CharacterKitLibrary | null, characterId: string, poseId?: string): string | undefined {
  const ref = series.characters.find(item => item.id === characterId)?.voiceProfile?.characterKitRef
  const kit = ref ? kits?.kits[ref.id] : undefined
  const pose = poseId && poseId !== 'base' ? kit?.poses[poseId] : undefined
  return pose?.source || kit?.base?.source
}

/** The cast as the plan places it (pose drawing, x %), to sketch a shot that has no take yet. */
export function planCast(series: SeriesProject, shot: SeriesShot, kits: CharacterKitLibrary | null): PlanFigure[] {
  const cast: Array<{ characterId: string; poseId?: string; x?: number; scale?: number }> = Array.isArray(shot.layout2d?.cast)
    ? shot.layout2d.cast : shot.visibleCharacterIds.map(characterId => ({ characterId }))
  const spread = (index: number) => ((index + 1) * 100) / (cast.length + 1)
  return cast.slice(0, 8).map((entry, index) => ({
    characterId: entry.characterId, name: series.characters.find(item => item.id === entry.characterId)?.name || entry.characterId,
    src: poseSource(series, kits, entry.characterId, entry.poseId), x: typeof entry.x === 'number' ? entry.x : spread(index),
    scale: typeof entry.scale === 'number' ? entry.scale : 1,
  }))
}

export interface Regeneration {
  /** The next render of the shot makes its take (2D or 3D); a video take only gets its cut sound, at the cut. */
  renders: boolean
  /** Lines it records first (no recording for their text and voice yet). */
  record: SeriesLineVoice[]
  /** Lines recorded after the latest take: the take does not have them yet. */
  newer: SeriesLineVoice[]
  /** The shot changed after its latest take, or it has none. */
  stale: boolean
  foley: boolean
}

/** What re-rendering the shot regenerates, from its line recordings and when it was last edited here. */
export function regeneration(shot: SeriesShot, voices: SeriesLineVoice[], editedAt: number | undefined): Regeneration {
  const renders = !VIDEO_METHODS.has(shot.productionMethod || 'generated_video')
  const latest = [...shot.attempts].reverse().find(item => item.status === 'completed')
  const record = renders ? voices.filter(line => line.voice !== false && !line.recorded) : []
  const newer = voices.filter(line => line.newerThanTake)
  const stale = !latest || Boolean(editedAt && editedAt > takeTime(latest)) || newer.length > 0
  return { renders, record, newer, stale, foley: Boolean(shot.foley?.prompt) }
}

export function neighbours(order: string[], id: string) {
  const index = order.indexOf(id)
  return { index, total: order.length, previous: index > 0 ? order[index - 1] : undefined,
    next: index >= 0 && index < order.length - 1 ? order[index + 1] : undefined }
}

/** A workspace file a script item names, as a URL the page can play or show. */
export function workspaceFileUrl(workspace: string, file: unknown): string | undefined {
  return typeof file === 'string' && file ? api.getFileUrl(file, workspace) : undefined
}

/** An object with one key set (undefined or '' removes it). */
export function withField<T extends Record<string, unknown>>(item: T, key: string, value: unknown): T {
  const next = { ...item } as Record<string, unknown>
  if (value === undefined || value === '') delete next[key]; else next[key] = value
  return next as T
}

/** The grid the inline editors lay their fields in. */
export const grid = 'grid grid-cols-2 gap-2 @md:grid-cols-3 @2xl:grid-cols-4'

export const VOICE_ROOMS = ['none', 'small_room', 'room', 'hall', 'cathedral', 'cockpit', 'outdoor', 'radio'] as const
export type VoiceRoom = typeof VOICE_ROOMS[number]
/** A room preset by name (anything else reads as dry). */
export const voiceRoom = (value: unknown): VoiceRoom => VOICE_ROOMS.find(item => item === value) || 'none'

/** The episode's score cue this shot plays under (by scene, or a run of shots from one cut to another). */
export function scoreCue(episode: SeriesEpisode, shot: SeriesShot): SeriesScoreCue | undefined {
  const order = new Map(episode.shots.map(item => [item.id, item.order]))
  return (episode.score || []).find(cue => {
    if (cue.sceneId) return cue.sceneId === shot.sceneId
    const from = order.get(cue.fromShotId || ''), to = cue.toShotId ? order.get(cue.toShotId) : undefined
    return from !== undefined && shot.order >= from && (to === undefined ? shot.order === from : shot.order <= to)
  })
}

const LANGUAGE_CODES: Record<string, string> = { english: 'en', spanish: 'es', french: 'fr', german: 'de', italian: 'it', portuguese: 'pt',
  japanese: 'ja', korean: 'ko', chinese: 'zh', russian: 'ru' }

/** A line's language key (`spanish`) in the UI's language (`español`). */
export function languageName(key: string, ui: string): string {
  const code = LANGUAGE_CODES[key]
  try { return code ? new Intl.DisplayNames([ui], { type: 'language' }).of(code) || key : key } catch { return key }
}
