import { VISEMES, type MouthCue, type Scene3DSpeech, type Viseme } from './types'

const EPS = 1e-6
export const MAX_ANALYZE_SECONDS = 90

export type CueInterval = { start: number; end: number }
export type SpeechClocks = Pick<Scene3DSpeech, 'start' | 'offset'>

export function sourceToScene(source: number, speech: SpeechClocks) {
  return speech.start + source - speech.offset
}
export function sceneToSource(scene: number, speech: SpeechClocks) {
  return scene - speech.start + speech.offset
}
export function clipInterval(start: number, end: number, min = 0, max = 600): CueInterval | undefined {
  const from = Math.min(start, end), to = Math.max(start, end)
  const clipped = { start: Math.max(min, from), end: Math.min(max, to) }
  return clipped.end - clipped.start > EPS ? clipped : undefined
}
export function waveformPeaks(samples: ArrayLike<number>, buckets: number) {
  const count = Math.max(1, Math.min(Math.floor(buckets) || 1, samples.length || 1))
  const peaks = new Array<number>(count).fill(0)
  if (!samples.length) return peaks
  const step = samples.length / count
  for (let i = 0; i < count; i++) {
    const from = Math.floor(i * step), until = Math.max(from + 1, Math.floor((i + 1) * step))
    let peak = 0
    for (let j = from; j < until; j++) peak = Math.max(peak, Math.abs(samples[j] ?? 0))
    peaks[i] = peak
  }
  return peaks
}
export function markManual(cue: MouthCue): MouthCue {
  return { start: cue.start, end: cue.end, viseme: cue.viseme, manual: true }
}
function outsideParts(cue: MouthCue, from: number, to: number): MouthCue[] {
  if (cue.end <= from + EPS || cue.start >= to - EPS) return [cue]
  const parts: MouthCue[] = []
  if (cue.start < from - EPS) parts.push({ ...cue, end: Math.min(cue.end, from) })
  if (cue.end > to + EPS) parts.push({ ...cue, start: Math.max(cue.start, to) })
  return parts.filter(part => part.end - part.start > EPS)
}
function normalizeCues(cues: MouthCue[]): MouthCue[] {
  const ordered = [...cues].filter(cue => cue.end - cue.start > EPS).sort((a, b) => a.start - b.start || a.end - b.end)
  const result: MouthCue[] = []
  for (const cue of ordered) {
    const previous = result.at(-1)
    let next = cue
    if (previous && next.start < previous.end - EPS) next = { ...next, start: previous.end }
    if (next.end - next.start > EPS) result.push(next)
  }
  if (result.length > 10000) throw new Error('Invalid mouth cues (maximum 10,000).')
  return result
}
export function replaceCueInterval(cues: readonly MouthCue[], from: number, to: number, next: readonly MouthCue[]): MouthCue[] {
  const range = clipInterval(from, to)
  if (!range) return [...cues]
  const kept = cues.flatMap(cue => outsideParts(cue, range.start, range.end))
  const inserted = next.flatMap(cue => {
    const clipped = clipInterval(cue.start, cue.end, range.start, range.end)
    return clipped ? [{ start: clipped.start, end: clipped.end, viseme: cue.viseme, ...(cue.manual ? { manual: true as const } : {}) }] : []
  })
  return normalizeCues([...kept, ...inserted])
}
export function setCueViseme(cues: readonly MouthCue[], index: number, viseme: Viseme): MouthCue[] {
  if (!VISEMES.includes(viseme) || index < 0 || index >= cues.length) return [...cues]
  return cues.map((cue, i) => i === index ? markManual({ ...cue, viseme }) : cue)
}
export function moveCueBound(cues: readonly MouthCue[], index: number, edge: 'start' | 'end', time: number): MouthCue[] {
  const cue = cues[index]
  if (!cue || !Number.isFinite(time)) return [...cues]
  const previousEnd = cues[index - 1]?.end ?? 0
  const nextStart = cues[index + 1]?.start ?? 600
  const start = edge === 'start' ? Math.min(cue.end - EPS, Math.max(previousEnd, time)) : cue.start
  const end = edge === 'end' ? Math.max(cue.start + EPS, Math.min(nextStart, time)) : cue.end
  if (end - start <= EPS) return [...cues]
  return cues.map((item, i) => i === index ? markManual({ ...item, start, end }) : item)
}
export function addSilence(cues: readonly MouthCue[], from: number, to: number): MouthCue[] {
  const range = clipInterval(from, to)
  return range ? replaceCueInterval(cues, range.start, range.end, [{ start: range.start, end: range.end, viseme: 'rest', manual: true }]) : [...cues]
}
export function mapFragmentCues(cues: readonly MouthCue[], origin: number): MouthCue[] {
  return cues.map(cue => ({ start: cue.start + origin, end: cue.end + origin, viseme: cue.viseme }))
}
export function analysisWindow(from: number, to: number, audioDuration: number) {
  const range = clipInterval(from, to, 0, Math.min(600, audioDuration))
  if (!range) throw new Error('Select an audio fragment of up to 90 seconds for lip-sync analysis.')
  const duration = range.end - range.start
  if (duration > MAX_ANALYZE_SECONDS) throw new Error('Select an audio fragment of up to 90 seconds for lip-sync analysis.')
  return { start: range.start, duration }
}
