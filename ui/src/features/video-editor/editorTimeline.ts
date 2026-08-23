import type { EditorClip, Transition } from './editorClipNormalization'

export type InterstitialTransition = 'later-clock' | 'later-tropical' | 'later-cinematic'

export const INTERSTITIAL_TRANSITIONS = new Set<Transition>([
  'later-clock',
  'later-tropical',
  'later-cinematic',
])

type TimelineClip = Pick<EditorClip, 'trimStart' | 'trimEnd' | 'transition' | 'transitionDuration'>

export function isInterstitialTransition(value: Transition): value is InterstitialTransition {
  return INTERSTITIAL_TRANSITIONS.has(value)
}

export function effectiveDuration(clip: Pick<EditorClip, 'trimStart' | 'trimEnd'>): number {
  return Math.max(0, clip.trimEnd - clip.trimStart)
}

export function transitionDurationAfter(clips: TimelineClip[], index: number): number {
  const current = clips[index]
  const next = clips[index + 1]
  if (!current || !next || current.transition === 'none') return 0
  if (isInterstitialTransition(current.transition)) {
    return Math.max(0.5, Math.min(current.transitionDuration, 5))
  }
  return Math.max(
    0.05,
    Math.min(current.transitionDuration, effectiveDuration(current) * 0.45, effectiveDuration(next) * 0.45),
  )
}

export function clipTimelineStart(clips: TimelineClip[], index: number): number {
  let start = 0
  for (let cursor = 0; cursor < index; cursor++) {
    const transitionDuration = transitionDurationAfter(clips, cursor)
    start += effectiveDuration(clips[cursor]) + (
      isInterstitialTransition(clips[cursor].transition) ? transitionDuration : -transitionDuration
    )
  }
  return start
}

export function sequenceTotalDuration(clips: TimelineClip[]): number {
  const raw = clips.reduce((total, clip) => total + effectiveDuration(clip), 0)
  const transitionDelta = clips.reduce((total, clip, index) => {
    const duration = transitionDurationAfter(clips, index)
    return total + (isInterstitialTransition(clip.transition) ? duration : -duration)
  }, 0)
  return Math.max(0, raw + transitionDelta)
}

export function clipIndexAtTime(clips: TimelineClip[], time: number): number {
  if (!clips.length) return 0
  const clamped = Math.max(0, time)
  for (let index = clips.length - 1; index >= 0; index--) {
    if (clamped >= clipTimelineStart(clips, index)) return index
  }
  return 0
}

export function transitionTimelineStart(clips: TimelineClip[], index: number): number {
  const clip = clips[index]
  if (!clip) return 0
  const start = clipTimelineStart(clips, index)
  const duration = effectiveDuration(clip)
  if (!clips[index + 1] || clip.transition === 'none') return start + duration
  if (isInterstitialTransition(clip.transition)) return start + duration
  return Math.max(start, start + duration - transitionDurationAfter(clips, index))
}

export function sourceTimeAtSequenceTime(clips: TimelineClip[], time: number): {
  clipIndex: number
  sourceTime: number
  interstitial: boolean
  interstitialElapsed: number
} {
  const clipIndex = clipIndexAtTime(clips, time)
  const clip = clips[clipIndex]
  if (!clip) {
    return { clipIndex: 0, sourceTime: 0, interstitial: false, interstitialElapsed: 0 }
  }
  const start = clipTimelineStart(clips, clipIndex)
  const cardStart = start + effectiveDuration(clip)
  const local = Math.max(0, time - start)
  if (
    isInterstitialTransition(clip.transition)
    && clips[clipIndex + 1]
    && time >= cardStart
  ) {
    return {
      clipIndex,
      sourceTime: Math.max(clip.trimStart, clip.trimEnd - 0.01),
      interstitial: true,
      interstitialElapsed: Math.min(transitionDurationAfter(clips, clipIndex), Math.max(0, time - cardStart)),
    }
  }
  return {
    clipIndex,
    sourceTime: Math.min(clip.trimEnd - 0.01, clip.trimStart + local),
    interstitial: false,
    interstitialElapsed: 0,
  }
}

export function parsePlayheadSeconds(raw: string): number | null {
  const text = raw.trim().replace(',', '.')
  if (!text) return null
  const parts = text.split(':')
  if (parts.length === 1) {
    const seconds = Number(parts[0])
    return Number.isFinite(seconds) ? seconds : null
  }
  if (parts.length === 2) {
    const minutes = Number(parts[0])
    const seconds = Number(parts[1])
    if (!Number.isFinite(minutes) || !Number.isFinite(seconds)) return null
    return minutes * 60 + seconds
  }
  return null
}

export function formatPlayheadTime(value: number): string {
  if (!Number.isFinite(value)) return '0:00.00'
  const minutes = Math.floor(Math.max(0, value) / 60)
  const seconds = Math.max(0, value) - minutes * 60
  return `${minutes}:${seconds.toFixed(2).padStart(5, '0')}`
}
