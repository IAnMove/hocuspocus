import { scheduleFx } from '../../sceneFx/audio'
import { worldSfxAudioCues } from '../../sceneFx/world'
import type { Scene3DDocument } from '../types'
import { scene3dOutputDuration, scene3dPlaybackSpeed } from '../clock'
import { safeMediaUrl } from './track'
import { sceneVoiceTracks } from './timeline'

export const MAX_VOICE_SECONDS = 600
export const MAX_DECODED_VOICES = 8

type VoiceSlot = { url: string; promise: Promise<AudioBuffer>; refs: number; used: number; failed: boolean }
const decodedVoices = new Map<string, VoiceSlot>()

export function resetVoiceDecodeCache() { decodedVoices.clear() }
export function voiceDecodeCacheSize() { return decodedVoices.size }
export function voiceDecodeCacheHas(url: string) {
  const slot = decodedVoices.get(url)
  return Boolean(slot && !slot.failed)
}

export async function decodeVoice(url: string, signal?: AbortSignal): Promise<AudioBuffer> {
  if (!safeMediaUrl(url)) throw new Error('Invalid voice URL.')
  if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')
  const slot = retainDecodedVoice(url)
  try {
    const decoded = await slot.promise
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')
    return decoded
  } finally { releaseDecodedVoice(slot) }
}

function retainDecodedVoice(url: string): VoiceSlot {
  let slot = decodedVoices.get(url)
  if (!slot || slot.failed) {
    const next: VoiceSlot = { url, promise: fetchAndDecode(url), refs: 0, used: 0, failed: false }
    decodedVoices.set(url, next)
    next.promise.catch(() => { next.failed = true })
    slot = next
  }
  slot.refs += 1
  slot.used = Date.now()
  return slot
}

function releaseDecodedVoice(slot: VoiceSlot) {
  slot.refs = Math.max(0, slot.refs - 1)
  if (slot.failed && slot.refs === 0 && decodedVoices.get(slot.url) === slot) decodedVoices.delete(slot.url)
  trimDecodedVoices()
}

function trimDecodedVoices() {
  while (decodedVoices.size > MAX_DECODED_VOICES) {
    const idle = [...decodedVoices.values()].filter(slot => slot.refs === 0).sort((a, b) => a.used - b.used)[0]
    if (!idle) break
    decodedVoices.delete(idle.url)
  }
}

async function fetchAndDecode(url: string): Promise<AudioBuffer> {
  const response = await fetch(url, { signal: AbortSignal.timeout(30000) })
  if (!response.ok) throw new Error('Voice could not be loaded.')
  if (Number(response.headers.get('content-length')) > 32 * 1024 * 1024) throw new Error('Voice file exceeds 32 MB.')
  const bytes = await response.arrayBuffer()
  if (bytes.byteLength > 32 * 1024 * 1024) throw new Error('Voice file exceeds 32 MB.')
  const decoded = await new OfflineAudioContext(1, 1, 48000).decodeAudioData(bytes)
  if (decoded.duration > MAX_VOICE_SECONDS) throw new Error('Use an audio source up to 600 seconds.')
  return decoded
}

export async function voiceWav(buffer: AudioBuffer, offset = 0, duration = buffer.duration - offset): Promise<ArrayBuffer> {
  if (!Number.isFinite(offset) || !Number.isFinite(duration) || offset < 0 || duration <= 0 || duration > 90 || offset + duration > buffer.duration + .001) throw new Error('Select an audio fragment of up to 90 seconds for lip-sync analysis.')
  const context = new OfflineAudioContext(1, Math.ceil(duration * 16000), 16000)
  const source = context.createBufferSource(); source.buffer = buffer; source.connect(context.destination); source.start(0, offset, duration)
  const samples = (await context.startRendering()).getChannelData(0)
  const bytes = new ArrayBuffer(44 + samples.length * 2), view = new DataView(bytes)
  const str = (at: number, value: string) => [...value].forEach((c, i) => view.setUint8(at + i, c.charCodeAt(0)))
  str(0, 'RIFF'); view.setUint32(4, bytes.byteLength - 8, true); str(8, 'WAVE'); str(12, 'fmt ')
  view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true)
  view.setUint32(24, 16000, true); view.setUint32(28, 32000, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true)
  str(36, 'data'); view.setUint32(40, samples.length * 2, true)
  samples.forEach((value, i) => view.setInt16(44 + i * 2, Math.round(Math.max(-1, Math.min(1, value)) * 32767), true))
  return bytes
}
export function voiceSchedule(start: number, offset: number, audioDuration: number, sceneDuration: number, speed: number) {
  return { when: start / speed, offset, rate: speed, duration: Math.max(0, Math.min(audioDuration - offset, sceneDuration - start)) }
}
export async function mixSceneSpeech(document: Scene3DDocument): Promise<AudioBuffer | undefined> {
  const tracks = sceneVoiceTracks(document)
  if (!tracks.length && !document.sfx?.some(cue => cue.sound && cue.volume) && !document.worldSfx?.some(cue => cue.sound && cue.volume)) return undefined
  const duration = scene3dOutputDuration(document), speed = scene3dPlaybackSpeed(document.playbackSpeed)
  // Bound memory explicitly; silent scenes retain the existing 600 s export contract.
  if (duration > 180) throw new Error('Voice exports support up to 180 output seconds per scene.')
  const context = new OfflineAudioContext(2, Math.ceil(duration * 48000), 48000)
  scheduleFx(context, [...(document.sfx ?? []), ...worldSfxAudioCues(document.worldSfx)], document.duration, speed)
  for (const track of tracks) {
    const buffer = await decodeVoice(track.audio!.url)
    const schedule = voiceSchedule(track.start, track.offset, buffer.duration, Math.min(document.duration, track.end ?? document.duration), speed)
    if (schedule.duration <= 0) continue
    const source = context.createBufferSource(), gain = context.createGain()
    source.buffer = buffer; source.playbackRate.value = schedule.rate; gain.gain.value = track.gain
    source.connect(gain); gain.connect(context.destination)
    source.start(schedule.when, schedule.offset, schedule.duration)
  }
  return context.startRendering()
}
