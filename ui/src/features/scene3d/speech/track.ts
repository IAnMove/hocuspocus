import { EXPRESSIONS, VISEMES, defaultSpeech, type Expression, type ExpressionCue, type FacePlacement, type MouthCue, type Scene3DSpeech, type SpeechClip, type Scene3DSoundtrack, type Viseme } from './types'
import { parseScene3DSourceRef } from '../slotSource'

const RHUBARB: Record<string, Viseme> = { X: 'rest', A: 'M', B: 'I', C: 'E', D: 'A', E: 'O', F: 'U', G: 'F', H: 'L' }
const object = (value: unknown): Record<string, unknown> => value && typeof value === 'object' ? value as Record<string, unknown> : {}
const finite = (value: unknown, min: number, max: number): value is number => typeof value === 'number' && Number.isFinite(value) && value >= min && value <= max
const vector = (value: unknown, length: number, min: number, max: number) => Array.isArray(value) && value.length === length && value.every(n => finite(n, min, max))

export function parseMouthCues(raw: unknown): MouthCue[] {
  const data = object(raw)
  const entries = Array.isArray(raw) ? raw : data.mouthCues ?? data.cues ?? object(data.track).cues
  if (!Array.isArray(entries) || entries.length > 10000) throw new Error('Invalid mouth cues (maximum 10,000).')
  const cues = entries.map(entry => {
    const cue = object(entry)
    const shape = cue.value ?? cue.shape
    const viseme = (typeof shape === 'string' ? RHUBARB[shape] : undefined) ?? cue.viseme
    if (!VISEMES.includes(viseme as Viseme) || !finite(cue.start, 0, 600) || !finite(cue.end, 0, 600) || cue.end <= cue.start) throw new Error('Invalid mouth cue.')
    if (cue.manual !== undefined && cue.manual !== true) throw new Error('Invalid mouth cue.')
    return { start: cue.start, end: cue.end, viseme: viseme as Viseme, ...(cue.manual === true ? { manual: true as const } : {}) }
  }).sort((a, b) => a.start - b.start)
  if (cues.some((cue, index) => index > 0 && cue.start < cues[index - 1].end - 1e-6)) throw new Error('Overlapping mouth cues.')
  return cues
}
export function parseExpressionCues(raw: unknown): ExpressionCue[] {
  if (raw === undefined) return []
  if (!Array.isArray(raw) || raw.length > 10000) throw new Error('Invalid expression cues (maximum 10,000).')
  const cues = raw.map(entry => {
    const cue = object(entry)
    const expression = cue.expression
    if (!EXPRESSIONS.includes(expression as Expression) || !finite(cue.start, 0, 600) || !finite(cue.end, 0, 600) || cue.end <= cue.start) throw new Error('Invalid expression cue.')
    if (cue.manual !== undefined && cue.manual !== true) throw new Error('Invalid expression cue.')
    return { start: cue.start, end: cue.end, expression: expression as Expression, ...(cue.manual === true ? { manual: true as const } : {}) }
  }).sort((a, b) => a.start - b.start)
  if (cues.some((cue, index) => index > 0 && cue.start < cues[index - 1].end - 1e-6)) throw new Error('Overlapping expression cues.')
  return cues
}
export function validFace(value: unknown): value is FacePlacement {
  const face = object(value), eyes = object(face.eyes)
  return Number.isInteger(face.meshIndex) && finite(face.meshIndex, 0, 1023)
    && vector(face.center, 3, -10000, 10000) && vector(face.size, 2, .00001, 10000) && vector(face.skin, 3, 0, 1)
    && vector(eyes.left, 3, -10000, 10000) && vector(eyes.right, 3, -10000, 10000)
    && vector(eyes.size, 2, .00001, 10000) && vector(eyes.skinLeft, 3, 0, 1) && vector(eyes.skinRight, 3, 0, 1)
}
function speechAppearance(data: Record<string, unknown>, defaults: Scene3DSpeech) {
  return { clean: data.clean !== false,
    style: data.style === 'toon' || data.style === 'pixel' ? data.style : 'soft',
    driver: data.driver === 'rhubarb' || data.driver === 'rhubarb-vocals' || data.driver === 'amplitude' ? data.driver : 'imported',
    lip: typeof data.lip === 'string' && /^#[0-9a-f]{6}$/i.test(data.lip) ? data.lip : defaults.lip,
    expression: EXPRESSIONS.includes(data.expression as typeof EXPRESSIONS[number]) ? data.expression as typeof EXPRESSIONS[number] : 'neutral',
    blink: data.blink !== false, eyes: data.eyes !== false } as Pick<Scene3DSpeech, 'clean' | 'style' | 'driver' | 'lip' | 'expression' | 'blink' | 'eyes'>
}

function speechRange(data: Record<string, unknown>) {
  if (data.end !== undefined && (!finite(data.end, 0, 600) || data.end <= (data.start as number))) throw new Error('Invalid speech end.')
  if (data.audible !== undefined && typeof data.audible !== 'boolean') throw new Error('Invalid speech audio switch.')
  return { ...(data.end !== undefined ? { end: data.end as number } : {}),
    ...(data.audible !== undefined ? { audible: data.audible as boolean } : {}) }
}

export function parseSpeech(raw: unknown): Scene3DSpeech | undefined {
  if (raw === undefined) return undefined
  const data = object(raw), defaults = defaultSpeech()
  if (data.version !== 1 || typeof data.enabled !== 'boolean') throw new Error('Invalid speech configuration.')
  if (data.face !== undefined && !validFace(data.face)) throw new Error('Invalid face placement.')
  const ref = (key: 'audio' | 'atlas' | 'facePack') => {
    if (data[key] === undefined) return undefined
    const parsed = parseScene3DSourceRef(data[key])
    if (!parsed || !safeMediaUrl(parsed.url)) throw new Error('Invalid speech asset.')
    return parsed
  }
  for (const [key, min, max] of [['start', 0, 600], ['offset', 0, 600], ['gain', 0, 1], ['strength', 0, 1.5]] as const) {
    if (!finite(data[key], min, max)) throw new Error('Invalid speech timing or level.')
  }
  const clips = data.clips === undefined ? undefined : parseSpeechClips(data.clips)
  const facePack = ref('facePack')
  const expressionCues = data.expressionCues === undefined ? undefined : parseExpressionCues(data.expressionCues)
  return { ...defaults, ...speechAppearance(data, defaults), ...speechRange(data), ...(clips ? { clips } : {}),
    version: 1, enabled: data.enabled, face: data.face as FacePlacement | undefined,
    audio: ref('audio'), atlas: ref('atlas'), ...(facePack ? { facePack } : {}),
    cues: parseMouthCues(data.cues), ...(expressionCues && expressionCues.length ? { expressionCues } : {}),
    start: data.start as number, offset: data.offset as number,
    gain: data.gain as number, strength: data.strength as number }
}
export function parseSpeechClips(raw: unknown): SpeechClip[] {
  if (!Array.isArray(raw) || raw.length > 32) throw new Error('Maximum 32 interventions per character.')
  const ids = new Set<string>()
  const clips = raw.map(value => {
    const clip = object(value)
    if (typeof clip.id !== 'string' || !clip.id || clip.id.length > 160 || ids.has(clip.id)) throw new Error('Invalid intervention identity.')
    ids.add(clip.id)
    // Strip nested clips before parsing; a clip is never another face configuration.
    const speech = parseSpeech({ ...defaultSpeech(), ...clip, clips: undefined })!
    if (clip.text !== undefined && (typeof clip.text !== 'string' || clip.text.length > 4000)) throw new Error('Invalid intervention text.')
    return { id: clip.id, ...(clip.text !== undefined ? { text: clip.text as string } : {}), audio: speech.audio,
      cues: speech.cues, driver: speech.driver, start: speech.start, offset: speech.offset,
      ...(speech.end !== undefined ? { end: speech.end } : {}), gain: speech.gain,
      ...(speech.audible !== undefined ? { audible: speech.audible } : {}) }
  })
  const ordered = [...clips].sort((a, b) => a.start - b.start)
  if (ordered.some((clip, i) => i > 0 && clip.start < (ordered[i - 1].end ?? 600))) throw new Error('Interventions of one character must not overlap; set their end times.')
  return clips
}
export function parseSoundtrack(raw: unknown): Scene3DSoundtrack[] | undefined {
  if (raw === undefined) return undefined
  if (!Array.isArray(raw) || raw.length > 32) throw new Error('Invalid scene soundtrack.')
  const ids = new Set<string>()
  return raw.map(value => {
    const [clip] = parseSpeechClips([{ ...object(value), cues: [], driver: 'imported' }])
    if (!clip.audio || ids.has(clip.id)) throw new Error('Invalid scene soundtrack identity or source.')
    ids.add(clip.id)
    return { id: clip.id, audio: clip.audio, start: clip.start, offset: clip.offset, gain: clip.gain,
      ...(clip.end !== undefined ? { end: clip.end } : {}) }
  })
}
export function safeMediaUrl(url: string) {
  return /^(https?:\/\/|\/(?!\/))/.test(url) && ![...url].some(c => c.charCodeAt(0) <= 32 || c === '\\')
}
export function cueAt(cues: readonly MouthCue[], time: number): Viseme {
  let lo = 0, hi = cues.length - 1, found: MouthCue | undefined
  while (lo <= hi) { const mid = (lo + hi) >> 1; if (cues[mid].start <= time) { found = cues[mid]; lo = mid + 1 } else hi = mid - 1 }
  return found && time < found.end ? found.viseme : 'rest'
}
export function expressionCueAt(cues: readonly ExpressionCue[], time: number, fallback: Expression): Expression {
  let lo = 0, hi = cues.length - 1, found: ExpressionCue | undefined
  while (lo <= hi) { const mid = (lo + hi) >> 1; if (cues[mid].start <= time) { found = cues[mid]; lo = mid + 1 } else hi = mid - 1 }
  return found && time < found.end ? found.expression : fallback
}
export function expressionAt(speech: Scene3DSpeech, sceneSeconds: number): Expression {
  if (speech.clips) {
    const clip = speech.clips.find(item => sceneSeconds >= item.start && sceneSeconds < (item.end ?? 600))
    return clip ? expressionAt({ ...speech, ...clip, clips: undefined }, sceneSeconds) : speech.expression
  }
  const time = sceneSeconds - speech.start + speech.offset
  if (!speech.enabled || sceneSeconds < speech.start || sceneSeconds >= (speech.end ?? Infinity)) return speech.expression
  return expressionCueAt(speech.expressionCues ?? [], time, speech.expression)
}
/** Pure time sampling, including seeking backwards and rendering frames out of order. */
export function mouthAt(speech: Scene3DSpeech, sceneSeconds: number): { a: number; b: number; mix: number } {
  if (speech.clips) {
    const clip = speech.clips.find(item => sceneSeconds >= item.start && sceneSeconds < (item.end ?? 600))
    return clip ? mouthAt({ ...speech, ...clip, clips: undefined }, sceneSeconds) : { a: 0, b: 0, mix: 1 }
  }
  const time = sceneSeconds - speech.start + speech.offset
  if (!speech.enabled || sceneSeconds < speech.start || sceneSeconds >= (speech.end ?? Infinity)) return { a: 0, b: 0, mix: 1 }
  const current = cueAt(speech.cues, time)
  const previous = cueAt(speech.cues, time - .045)
  let boundary = 0
  for (const cue of speech.cues) {
    if (cue.start <= time) boundary = Math.max(boundary, cue.start)
    if (cue.end <= time) boundary = Math.max(boundary, cue.end)
    if (cue.start > time) break
  }
  return { a: VISEMES.indexOf(previous), b: VISEMES.indexOf(current), mix: Math.min(1, Math.max(0, (time - boundary) / .045)) }
}
export function amplitudeCues(buffer: AudioBuffer, offset = 0, duration = buffer.duration - offset): MouthCue[] {
  const samples = buffer.getChannelData(0), from = Math.floor(offset * buffer.sampleRate)
  const until = Math.min(samples.length, Math.ceil((offset + duration) * buffer.sampleRate))
  // Keep even a full ten-minute source below the cue-file contract.
  const step = Math.max(1, Math.round(buffer.sampleRate / 30), Math.ceil((until - from) / 9999)), levels: number[] = []
  for (let i = from; i < until; i += step) {
    let sum = 0
    for (let j = i; j < Math.min(i + step, until); j++) sum += samples[j] ** 2
    levels.push(Math.sqrt(sum / step))
  }
  const peak = Math.max(.03, ...levels), result: MouthCue[] = []
  levels.forEach((level, i) => {
    const normalized = Math.max(0, (level - .006) / (peak * .7))
    const viseme: Viseme = normalized < .055 ? 'rest' : normalized > .45 ? 'A' : 'E'
    const end = Math.min(until / buffer.sampleRate, (from + (i + 1) * step) / buffer.sampleRate)
    if (result.at(-1)?.viseme === viseme) result[result.length - 1].end = end
    else result.push({ start: (from + i * step) / buffer.sampleRate, end, viseme })
  })
  return result
}
