import { DEFAULT_CUE_FADE, MAX_CLIP_CUES, parseClipCues, type Scene3DClipCue } from './clipCues.ts'
import { parseClipPlayback } from './performance.ts'
import type { Scene3DClipPlayback, Scene3DClipRef, Scene3DSlot } from './types.ts'

const MAX_SECONDS = 600

/** The current single clip becomes cue 0. A fade of 0 is a cut until another cue arrives. */
export function startClipSequence(slot: Pick<Scene3DSlot, 'clip' | 'clipPlayback'>): Scene3DClipCue[] | undefined {
  if (!slot.clip) return undefined
  const playback = parseClipPlayback(slot.clipPlayback) ?? { speed: 1, start: 0, loop: true }
  return parseClipCues([{
    clip: { index: slot.clip.index, name: slot.clip.name },
    start: 0,
    fade: 0,
    speed: playback.speed ?? 1,
    offset: playback.start ?? 0,
    loop: playback.loop !== false,
  }])
}

/** Append one cue after the last, fading in over the default 0.3 s. At 32 cues the list stays put. */
export function appendClipCue(cues: readonly Scene3DClipCue[], clip: Scene3DClipRef, shotDuration: number): Scene3DClipCue[] | undefined {
  if (cues.length >= MAX_CLIP_CUES) return parseClipCues([...cues])
  const last = cues.at(-1)
  const span = Number.isFinite(shotDuration) && shotDuration > 0 ? shotDuration : MAX_SECONDS
  const start = Math.min(MAX_SECONDS, Math.max(0, Math.min(span, (last?.start ?? 0) + Math.min(2, span))))
  return parseClipCues([...cues, {
    clip: { index: clip.index, name: clip.name },
    start,
    fade: DEFAULT_CUE_FADE,
    speed: last?.speed ?? 1,
    offset: 0,
    loop: last?.loop !== false,
  }])
}

export type ClipCuePatch = {
  clip?: Scene3DClipRef
  start?: number
  duration?: number | null
  fade?: number | null
  speed?: number | null
  offset?: number | null
  loop?: boolean
}

/** Replace one cue and re-parse, so a bad number cannot drop the cue from the sequence. */
export function replaceClipCue(cues: readonly Scene3DClipCue[], index: number, patch: ClipCuePatch): Scene3DClipCue[] | undefined {
  const current = cues[index]
  if (!current) return parseClipCues([...cues])
  const next: Scene3DClipCue = {
    ...current,
    clip: patch.clip ? { index: patch.clip.index, name: patch.clip.name } : current.clip,
    start: clamp(patch.start, 0, MAX_SECONDS) ?? current.start,
    loop: patch.loop ?? current.loop,
  }
  writeOptional(next, 'duration', patch.duration, 1e-6, MAX_SECONDS)
  writeOptional(next, 'fade', patch.fade, 0, 10)
  writeOptional(next, 'speed', patch.speed, 0.1, 4)
  writeOptional(next, 'offset', patch.offset, 0, MAX_SECONDS)
  return parseClipCues(cues.map((cue, i) => i === index ? next : cue))
}

export function removeClipCue(cues: readonly Scene3DClipCue[], index: number): Scene3DClipCue[] | undefined {
  return parseClipCues(cues.filter((_, i) => i !== index))
}

/** Leave sequence mode. The first cue becomes the single clip the slot already knows how to play. */
export function singleClipFromSequence(cues: readonly Scene3DClipCue[]): { clip: Scene3DClipRef | null; clipPlayback: Scene3DClipPlayback; clips: undefined } {
  const cue = cues[0]
  if (!cue) return { clip: null, clipPlayback: { speed: 1, start: 0, loop: true }, clips: undefined }
  return {
    clip: { index: cue.clip.index, name: cue.clip.name },
    clipPlayback: { speed: cue.speed ?? 1, start: cue.offset ?? 0, loop: cue.loop !== false },
    clips: undefined,
  }
}

function clamp(value: number | undefined, min: number, max: number): number | undefined {
  if (value == null || !Number.isFinite(value)) return undefined
  return Math.min(max, Math.max(min, value))
}

function writeOptional(cue: Scene3DClipCue, key: 'duration' | 'fade' | 'speed' | 'offset', value: number | null | undefined, min: number, max: number) {
  if (value === undefined) return
  if (value === null || !Number.isFinite(value)) {
    delete cue[key]
    return
  }
  cue[key] = Math.min(max, Math.max(min, value))
}
