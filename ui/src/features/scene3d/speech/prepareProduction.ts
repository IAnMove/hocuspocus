import { useStore } from '../../../stores/useStore'
import { getPlayableFileUrl } from '../../../api/client'
import type { Scene } from '../../../types'
import { buildSpeechProduction, queueSpeechProduction, type SpeechProductionInput } from './production'
import { decodeVoice } from './audio'
import { analyzeProductionTrack } from './analyzeProduction'
import { fetchCharacterKitLibrary } from '../../../api/characters'
import { characterSlotPatch } from './characterBinding'
import { faceSettings, modelDigest } from './profiles'

export async function prepareSpeechProduction(input: SpeechProductionInput, phonetic = true, signal?: AbortSignal) {
  const doc = buildSpeechProduction(input)
  if (!input.audio) return doc
  const buffer = await decodeVoice(input.audio.url)
  if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')
  if (input.offset + input.duration > buffer.duration + .01) throw new Error('The selected fragment extends beyond the audio file.')
  // Analyze the complete shot once, so gaps and repeated speakers share timing.
  const track = await analyzeProductionTrack(input, buffer, phonetic, signal)
  for (const slot of doc.slots) if (slot.speech?.clips) for (const clip of slot.speech.clips) {
    Object.assign(clip, track, { cues: track.cues.filter(c => c.end > clip.offset && c.start < clip.offset + (clip.end! - clip.start)) })
  }
  if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')
  return doc
}
export function openSpeechProduction(document: ReturnType<typeof buildSpeechProduction>) {
  if (useStore.getState().activeWorkspace !== document.production?.workspace) throw new Error('Workspace changed. Reopen the source and try again.')
  queueSpeechProduction(document)
  useStore.getState().setSettingsOpen(false)
  useStore.getState().setDashboardOpen(false)
  useStore.getState().setMediaFilter('world3d')
}
/** Upgrade only a selected GLB. All image/cutout actions retain their old path. */
export async function speakLegacyModel(scene: Scene, modelId: string, trackId: string, workspace: string, start: number, end: number, text: string) {
  const model = scene.layers.find(layer => layer.id === modelId && layer.type === 'model3d')
  const track = scene.audioTracks?.find(item => item.id === trackId)
  if (!model?.source || !track) throw new Error('Choose a saved GLB and the character audio first.')
  const source = new URL(model.source, window.location.origin)
  const name = decodeURIComponent(source.pathname.split('/').at(-1) || '')
  const input: SpeechProductionInput = { kind: track.kind === 'music' ? 'song' : 'dialogue', title: scene.name, sourceId: scene.name,
    workspace, duration: end - start, offset: start - track.startTime,
    cast: [{ id: model.id, name: model.name, model: { workspaceId: workspace, filename: name, url: model.source } }],
    audio: { workspaceId: workspace, filename: track.filename, url: getPlayableFileUrl('', track.filename, workspace) },
    lines: [{ id: 'dialogue', characterId: model.id, text, start: 0, end: end - start }] }
  if (model.characterKitRef) {
    const ref = model.characterKitRef, library = await fetchCharacterKitLibrary(ref.workspace), kit = library.kits[ref.id]
    if (!kit?.speech3d) throw new Error('The linked character is unavailable. Choose its saved definition again.')
    if (await modelDigest(model.source) !== kit.speech3d.digest) throw new Error('The linked character uses another GLB. Select the matching character or clear the link.')
    const patch = await characterSlotPatch(kit, ref.workspace, library.revision)
    input.cast[0] = { ...input.cast[0], character: patch.character, settings: faceSettings(patch.speech!) }
  }
  const document = await prepareSpeechProduction(input)
  openSpeechProduction(document)
}
