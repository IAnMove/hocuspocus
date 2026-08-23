import type { VideoEditorProbe } from '../../api/client'

export type ClipFit = 'fit' | 'fill'
export type Transition =
  | 'none'
  | 'crossfade'
  | 'fade-black'
  | 'wipe-left'
  | 'slide-left'
  | 'slide-right'
  | 'circle-open'
  | 'dissolve'
  | 'pixelize'
  | 'blur'
  | 'zoom-in'
  | 'later-clock'
  | 'later-tropical'
  | 'later-cinematic'

export interface EditorClip extends VideoEditorProbe {
  id: string
  name: string
  source: string
  previewUrl: string
  thumbnailUrl: string
  trimStart: number
  trimEnd: number
  volume: number
  muted: boolean
  fit: ClipFit
  transition: Transition
  transitionDuration: number
  transitionText: string
  transitionTextSize: number
}

export interface EditorClipNormalizationResult {
  clips: EditorClip[]
  repairedCount: number
  discardedCount: number
}

const MIN_TRIM_DURATION = 0.05
const FIT_VALUES = new Set<ClipFit>(['fit', 'fill'])
const TRANSITION_VALUES = new Set<Transition>([
  'none', 'crossfade', 'fade-black', 'wipe-left', 'slide-left', 'slide-right',
  'circle-open', 'dissolve', 'pixelize', 'blur', 'zoom-in', 'later-clock',
  'later-tropical', 'later-cinematic',
])

const finiteNumber = (value: unknown, fallback: number): number => (
  typeof value === 'number' && Number.isFinite(value) ? value : fallback
)

const positiveInteger = (value: unknown): number => {
  const number = finiteNumber(value, 0)
  return number > 0 ? Math.round(number) : 0
}

const clamp = (value: number, minimum: number, maximum: number): number => (
  Math.max(minimum, Math.min(maximum, value))
)

function uniqueClipId(rawId: unknown, usedIds: Set<string>, idFactory: () => string): string {
  const candidate = typeof rawId === 'string' ? rawId.trim() : ''
  if (candidate && !usedIds.has(candidate)) return candidate
  for (let attempt = 0; attempt < 20; attempt++) {
    const generated = String(idFactory() || '').trim()
    if (generated && !usedIds.has(generated)) return generated
  }
  let suffix = usedIds.size + 1
  while (usedIds.has(`clip-recovered-${suffix}`)) suffix += 1
  return `clip-recovered-${suffix}`
}

export function normalizeEditorClips(
  values: unknown,
  options: {
    idFactory: () => string
    thumbnailUrl: (source: string) => string
  },
): EditorClipNormalizationResult {
  if (!Array.isArray(values)) return { clips: [], repairedCount: 0, discardedCount: 0 }
  const clips: EditorClip[] = []
  const usedIds = new Set<string>()
  let repairedCount = 0
  let discardedCount = 0

  for (const value of values) {
    if (!value || typeof value !== 'object') {
      discardedCount += 1
      continue
    }
    const raw = value as Record<string, unknown>
    const source = typeof raw.source === 'string' ? raw.source.trim() : ''
    const duration = finiteNumber(raw.duration, 0)
    if (!source || duration <= MIN_TRIM_DURATION) {
      discardedCount += 1
      continue
    }

    let trimStart = clamp(finiteNumber(raw.trimStart, 0), 0, duration)
    let trimEnd = clamp(finiteNumber(raw.trimEnd, duration), 0, duration)
    if (trimStart > trimEnd) [trimStart, trimEnd] = [trimEnd, trimStart]
    if (trimEnd - trimStart < MIN_TRIM_DURATION) {
      if (trimStart + MIN_TRIM_DURATION <= duration) trimEnd = trimStart + MIN_TRIM_DURATION
      else {
        trimEnd = duration
        trimStart = Math.max(0, duration - MIN_TRIM_DURATION)
      }
    }

    const id = uniqueClipId(raw.id, usedIds, options.idFactory)
    usedIds.add(id)
    const normalized: EditorClip = {
      id,
      name: typeof raw.name === 'string' && raw.name.trim() ? raw.name.trim() : source.split('/').pop() || 'Recovered clip',
      source,
      previewUrl: typeof raw.previewUrl === 'string' && raw.previewUrl.trim() ? raw.previewUrl : source,
      thumbnailUrl: typeof raw.thumbnailUrl === 'string' && raw.thumbnailUrl.trim()
        ? raw.thumbnailUrl
        : options.thumbnailUrl(source),
      duration,
      width: positiveInteger(raw.width),
      height: positiveInteger(raw.height),
      fps: finiteNumber(raw.fps, 30) > 0 ? finiteNumber(raw.fps, 30) : 30,
      has_audio: raw.has_audio === true,
      pixel_format: typeof raw.pixel_format === 'string' && raw.pixel_format ? raw.pixel_format : 'unknown',
      has_alpha: raw.has_alpha === true,
      trimStart,
      trimEnd,
      volume: clamp(finiteNumber(raw.volume, 1), 0, 1),
      muted: raw.muted === true,
      fit: FIT_VALUES.has(raw.fit as ClipFit) ? raw.fit as ClipFit : 'fit',
      transition: TRANSITION_VALUES.has(raw.transition as Transition) ? raw.transition as Transition : 'none',
      transitionDuration: clamp(finiteNumber(raw.transitionDuration, 0.5), 0.05, 5),
      transitionText: typeof raw.transitionText === 'string' ? raw.transitionText : 'Momentos después…',
      transitionTextSize: clamp(finiteNumber(raw.transitionTextSize, 100), 50, 160),
    }
    if (Object.entries(normalized).some(([key, normalizedValue]) => raw[key] !== normalizedValue)) {
      repairedCount += 1
    }
    clips.push(normalized)
  }

  return { clips, repairedCount, discardedCount }
}

export const TIMELINE_MIN_TRIM_DURATION = 0.4
export const TIMELINE_TRIM_PX_PER_SEC = 80

export function splitClipAtTime(
  clip: EditorClip,
  cut: number,
  newId: string,
): [EditorClip, EditorClip] | null {
  if (!Number.isFinite(cut)) return null
  if (cut <= clip.trimStart + MIN_TRIM_DURATION || cut >= clip.trimEnd - MIN_TRIM_DURATION) return null
  const base = clip.name.replace(/ \(part [12]\)$/i, '')
  return [
    { ...clip, name: `${base} (part 1)`, trimEnd: cut, transition: 'none' },
    { ...clip, id: newId, name: `${base} (part 2)`, trimStart: cut },
  ]
}

export function applyTransitionToGaps(clips: EditorClip[], transition: Transition): EditorClip[] {
  if (clips.length < 2) return clips
  const interstitial = transition.startsWith('later-')
  return clips.map((clip, index) => {
    if (index >= clips.length - 1) return clip
    return {
      ...clip,
      transition,
      transitionDuration: interstitial
        ? Math.max(2, clip.transitionDuration || 2)
        : Math.max(0.4, Math.min(clip.transitionDuration || 0.5, 2)),
    }
  })
}

export function trimClipFromDelta(
  clip: EditorClip,
  edge: 'start' | 'end',
  deltaSeconds: number,
  minDuration = TIMELINE_MIN_TRIM_DURATION,
): EditorClip {
  const floor = Math.max(MIN_TRIM_DURATION, minDuration)
  if (edge === 'start') {
    return {
      ...clip,
      trimStart: Math.min(clip.trimEnd - floor, Math.max(0, clip.trimStart + deltaSeconds)),
    }
  }
  return {
    ...clip,
    trimEnd: Math.max(clip.trimStart + floor, Math.min(clip.duration, clip.trimEnd + deltaSeconds)),
  }
}

export function editorClipRecoveryMessage(result: EditorClipNormalizationResult): string | null {
  const parts: string[] = []
  if (result.repairedCount) parts.push(`${result.repairedCount} repaired`)
  if (result.discardedCount) parts.push(`${result.discardedCount} discarded because source or duration was invalid`)
  return parts.length ? `Recovered editor draft: ${parts.join(', ')}.` : null
}
