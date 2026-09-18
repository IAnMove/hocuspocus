import { applyScene3DTemplate } from '../templates'
import type { Scene3DDocument, Scene3DSourceRef } from '../types'
import { parseScene3DDocument } from '../document'
import { defaultSpeech, type SpeechClip } from './types'
import { safeMediaUrl } from './track'
import { randomUuid } from '../../../lib/uuid'

export type SpeechProductionInput = {
  kind: NonNullable<Scene3DDocument['production']>['kind']
  title: string
  sourceId?: string
  workspace: string
  duration: number
  offset: number
  cast: { id: string; name: string; model: Scene3DSourceRef;
    character?: import('../types').Scene3DSlot['character']; settings?: import('./profiles').FaceSettings }[]
  audio?: Scene3DSourceRef
  lines?: { id: string; characterId: string; text: string; start?: number; end?: number }[]
}
export function buildSpeechProduction(input: SpeechProductionInput): Scene3DDocument {
  if (!input.cast.length || input.cast.length > 2 || new Set(input.cast.map(c => c.id)).size !== input.cast.length) throw new Error('Choose one or two distinct speakers per shot.')
  if (!Number.isFinite(input.duration) || input.duration < .1 || input.duration > 90 || !Number.isFinite(input.offset) || input.offset < 0 || input.offset + input.duration > 600) throw new Error('Choose a source fragment up to 90 seconds, within the first 600 seconds.')
  if ((input.audio && !safeMediaUrl(input.audio.url)) || input.cast.some(c => !safeMediaUrl(c.model.url) || !/\.glb$/i.test(c.model.filename))) throw new Error('Use saved GLB models and audio.')
  const doc = applyScene3DTemplate(input.cast.length === 2 ? 'speech-dialogue' : 'speech-portrait')
  doc.duration = input.duration
  doc.production = { kind: input.kind, title: input.title, sourceId: input.sourceId, workspace: input.workspace }
  doc.soundtrack = input.audio ? [{ id: 'production-audio', audio: input.audio, start: 0, offset: input.offset, end: input.duration, gain: 1 }] : undefined
  const lines = input.lines?.length ? input.lines : input.cast.map((c, i) => ({
    id: 'line-' + i, characterId: c.id, text: '', start: i * input.duration / input.cast.length, end: (i + 1) * input.duration / input.cast.length,
  }))
  if (lines.some(line => !input.cast.some(c => c.id === line.characterId))) throw new Error('Every dialogue line needs a selected 3D character.')
  doc.slots = doc.slots.map(slot => {
    const castIndex = slot.slot === 'subject_1' ? 0 : slot.slot === 'subject_2' ? 1 : -1
    const character = input.cast[castIndex]
    if (!character) return slot
    const clips: SpeechClip[] = lines.flatMap((line, i) => {
      if (line.characterId !== character.id) return []
      const start = line.start ?? i * input.duration / lines.length
      const end = line.end ?? (i + 1) * input.duration / lines.length
      if (start < 0 || end > input.duration || end <= start) throw new Error('Dialogue timing is outside the shot.')
      return [{ id: line.id, text: line.text, audio: input.audio, start, end, offset: input.offset + start,
        gain: 1, audible: !input.audio, cues: [], driver: 'imported' }]
    })
    return { ...slot, character: { ...character.character, id: character.id, name: character.name }, sourceUrl: character.model.url, sourceRef: character.model, clip: null,
      speech: { ...defaultSpeech(), ...character.settings, clips } }
  })
  const parsed = parseScene3DDocument(doc)
  if (!parsed) throw new Error('Invalid 3D speech production.')
  return parsed
}
const HANDOFF_KEY = 'hocuspocus:pending-world3d-speech'
export const SPEECH_HANDOFF_EVENT = 'hocuspocus:world3d-speech'
export function queueSpeechProduction(document: Scene3DDocument, storage: Pick<Storage, 'setItem'> = sessionStorage) {
  const parsed = parseScene3DDocument(document)
  if (!parsed?.production) throw new Error('Invalid speech handoff.')
  storage.setItem(HANDOFF_KEY, JSON.stringify(parsed))
  if (typeof window !== 'undefined') window.dispatchEvent(new Event(SPEECH_HANDOFF_EVENT))
}
export function takeSpeechProduction(workspace: string, storage: Pick<Storage, 'getItem' | 'removeItem'> = sessionStorage, beforeTake?: () => void) {
  const raw = storage.getItem(HANDOFF_KEY)
  if (!raw) return null
  const parsed = parseScene3DDocument(JSON.parse(raw))
  if (!parsed?.production || parsed.production.workspace !== workspace) return null
  beforeTake?.()
  storage.removeItem(HANDOFF_KEY)
  return parsed
}
export function preserveSpeechDraft(workspace: string, document: Scene3DDocument) {
  const raw = JSON.stringify(document)
  sessionStorage.setItem('hocuspocus:world3d-speech-history:' + workspace + ':' + randomUuid(), raw)
  sessionStorage.setItem('hocuspocus:world3d-before-speech:' + workspace, raw)
}
