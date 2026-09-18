import { parseMouthCues } from '../features/scene3d/speech/track'
import type { MouthCue } from '../features/scene3d/speech/types'
import { PHONETIC_MOUTH_STATE } from './characterMouthStates'
import type { CutoutDialoguePlan, SceneDialogueBeat } from './cutoutDialogue'

/** Cues use the analyzed fragment's clock, independent of scene placement. */
export type CutoutLipSync = {
  version: 1
  driver: 'phonetic' | 'pocketSphinx' | 'energy'
  text: string
  audioTrackId: string
  filename: string
  offset: number
  duration: number
  cues: MouthCue[]
}

export const CUTOUT_LIP_SYNC_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: { version: { const: 1 }, driver: { enum: ['phonetic', 'pocketSphinx', 'energy'] },
    text: { type: 'string', maxLength: 4000 }, audioTrackId: { type: 'string', maxLength: 120 },
    filename: { type: 'string', maxLength: 1200 }, offset: { type: 'number', minimum: 0, maximum: 600 },
    duration: { type: 'number', exclusiveMinimum: 0, maximum: 90 },
    cues: { type: 'array', maxItems: 10000, items: { type: 'object', additionalProperties: false,
      properties: { start: { type: 'number', minimum: 0, maximum: 90 }, end: { type: 'number', exclusiveMinimum: 0, maximum: 90.1 },
        viseme: { enum: ['rest', 'M', 'I', 'E', 'A', 'O', 'U', 'F', 'L'] }, manual: { const: true } },
      required: ['start', 'end', 'viseme'] } } },
  required: ['version', 'driver', 'text', 'audioTrackId', 'filename', 'offset', 'duration', 'cues'],
} as const

export function parseCutoutLipSync(raw: unknown): CutoutLipSync | undefined {
  if (raw === undefined) return undefined
  if (!raw || typeof raw !== 'object') throw new Error('Invalid cutout lip sync.')
  const value = raw as CutoutLipSync
  if (value.version !== 1 || !['phonetic', 'pocketSphinx', 'energy'].includes(value.driver)
    || ![value.text, value.audioTrackId, value.filename].every(item => typeof item === 'string' && item.length <= 4000)
    || !Number.isFinite(value.offset) || value.offset < 0
    || !Number.isFinite(value.duration) || value.duration <= 0 || value.duration > 90) throw new Error('Invalid cutout lip sync source.')
  const cues = parseMouthCues(value.cues)
  if (cues.some(cue => cue.end > value.duration + .1)) throw new Error('Mouth cues exceed the analyzed audio.')
  return { ...value, cues }
}

export function currentCutoutLipSync(beat: SceneDialogueBeat): CutoutLipSync | undefined {
  const sync = parseCutoutLipSync(beat.lipSync)
  return sync && sync.text === beat.text && sync.audioTrackId === beat.audioTrackId
    && Math.abs(sync.duration - (beat.end - beat.start)) < .05 ? sync : undefined
}

/** Real phonetic durations, including pauses and bilabial closures. No letter sampling. */
export function planPhoneticCutoutDialogue(beat: SceneDialogueBeat, duration: number): CutoutDialoguePlan | undefined {
  const sync = currentCutoutLipSync(beat)
  if (!sync) return undefined
  const start = Math.max(0, beat.start), end = Math.min(duration, beat.end)
  const visemes: CutoutDialoguePlan['visemes'] = [{ start: 0, end: start, state: 'closed' }]
  let cursor = start
  for (const cue of sync.cues) {
    const from = Math.max(start, beat.start + cue.start), until = Math.min(end, beat.start + cue.end)
    if (until <= from) continue
    if (from > cursor) visemes.push({ start: cursor, end: from, state: 'closed' })
    visemes.push({ start: from, end: until, state: PHONETIC_MOUTH_STATE[cue.viseme] })
    cursor = until
  }
  visemes.push({ start: cursor, end, state: 'closed' })
  return { start, end, visemes }
}
