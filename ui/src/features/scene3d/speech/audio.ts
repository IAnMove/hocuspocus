import { scheduleFx } from '../../sceneFx/audio'
import { worldSfxAudioCues } from '../../sceneFx/world'
import type { Scene3DDocument } from '../types'
import { scene3dOutputDuration, scene3dPlaybackSpeed } from '../clock'
import { safeMediaUrl } from './track'
import { sceneVoiceTracks, speechClips } from './timeline'

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

/** Music under dialogue. The hold is −10 dB; fades match the attack and release. */
export const SOUNDTRACK_DUCK_DB = 10
export const SOUNDTRACK_DUCK_ATTACK = 0.12
export const SOUNDTRACK_DUCK_RELEASE = 0.4
export const SOUNDTRACK_DUCK_MARGIN = 0.08
export const SOUNDTRACK_FADE_IN = 0.12
export const SOUNDTRACK_FADE_OUT = 0.4
export const SOUNDTRACK_GAIN_STEP = 0.01

const DUCK_LINEAR = 10 ** (-SOUNDTRACK_DUCK_DB / 20)

export type DuckWindow = { start: number; end: number }

export function outputWindow(when: number, sourceDuration: number, rate: number): DuckWindow | undefined {
  const end = when + sourceDuration / rate
  return end > when ? { start: when, end } : undefined
}

function duckDepth(time: number, window: DuckWindow): number {
  const lead = window.start - SOUNDTRACK_DUCK_MARGIN
  const attackEnd = lead + SOUNDTRACK_DUCK_ATTACK
  const releaseEnd = window.end + SOUNDTRACK_DUCK_RELEASE
  const attack = time >= attackEnd ? 1 : time <= lead ? 0 : (time - lead) / SOUNDTRACK_DUCK_ATTACK
  const release = time <= window.end ? 1 : time >= releaseEnd ? 0 : 1 - (time - window.end) / SOUNDTRACK_DUCK_RELEASE
  return Math.min(attack, release)
}

function edgeFade(time: number, start: number, end: number): number {
  const span = end - start
  if (span <= 0 || time <= start || time >= end) return 0
  let fadeIn = SOUNDTRACK_FADE_IN
  let fadeOut = SOUNDTRACK_FADE_OUT
  if (fadeIn + fadeOut > span) {
    const scale = span / (fadeIn + fadeOut)
    fadeIn *= scale
    fadeOut *= scale
  }
  if (time < start + fadeIn) return fadeIn > 0 ? (time - start) / fadeIn : 1
  if (time > end - fadeOut) return fadeOut > 0 ? (end - time) / fadeOut : 1
  return 1
}

/** True when inaudible lip-sync already points at this file: the clip is the scene tape, not a music bed. */
export function soundtrackIsSceneTape(url: string | undefined, document: Scene3DDocument): boolean {
  if (!url) return false
  return document.slots.some(slot => slot.speech?.enabled && speechClips(slot.speech).some(clip =>
    clip.audible === false && clip.audio?.url === url))
}

/** Linear gain of one soundtrack clip at an output time. Dialogue windows use output seconds. */
export function soundtrackGainAt(
  time: number,
  gain: number,
  start: number,
  end: number,
  windows: readonly DuckWindow[],
  fade = true,
): number {
  let depth = 0
  for (const window of windows) depth = Math.max(depth, duckDepth(time, window))
  const ducked = 1 + (DUCK_LINEAR - 1) * depth
  return Math.max(0, gain) * ducked * (fade ? edgeFade(time, start, end) : 1)
}

export function soundtrackGainCurve(
  start: number,
  duration: number,
  gain: number,
  windows: readonly DuckWindow[],
  fade = true,
): Float32Array {
  const count = Math.max(2, Math.floor(duration / SOUNDTRACK_GAIN_STEP) + 1)
  const curve = new Float32Array(count)
  const end = start + duration
  for (let index = 0; index < count; index += 1) {
    const time = start + (duration * index) / (count - 1)
    curve[index] = soundtrackGainAt(time, gain, start, end, windows, fade)
  }
  return curve
}

function scheduleBuffer(
  context: OfflineAudioContext,
  buffer: AudioBuffer,
  schedule: ReturnType<typeof voiceSchedule>,
  gain: number,
  curve?: Float32Array,
) {
  const source = context.createBufferSource()
  const node = context.createGain()
  source.buffer = buffer
  source.playbackRate.value = schedule.rate
  source.connect(node)
  node.connect(context.destination)
  if (curve) node.gain.setValueCurveAtTime(curve, schedule.when, Math.max(schedule.duration / schedule.rate, 1 / context.sampleRate))
  else node.gain.value = gain
  source.start(schedule.when, schedule.offset, schedule.duration)
}

/** Soundtrack clips are music, except the lines world3d.scene.talk adds (`talk-<object>-<n>`): those are dialogue. */
export function isMusicTrack(track: { key: string }): boolean {
  return track.key.startsWith('soundtrack/') && !track.key.startsWith('soundtrack/talk-')
}

export async function mixSceneSpeech(document: Scene3DDocument): Promise<AudioBuffer | undefined> {
  const tracks = sceneVoiceTracks(document)
  if (!tracks.length && !document.sfx?.some(cue => cue.sound && cue.volume) && !document.worldSfx?.some(cue => cue.sound && cue.volume)) return undefined
  const duration = scene3dOutputDuration(document), speed = scene3dPlaybackSpeed(document.playbackSpeed)
  // Bound memory explicitly; silent scenes retain the existing 600 s export contract.
  if (duration > 180) throw new Error('Voice exports support up to 180 output seconds per scene.')
  const context = new OfflineAudioContext(2, Math.ceil(duration * 48000), 48000)
  scheduleFx(context, [...(document.sfx ?? []), ...worldSfxAudioCues(document.worldSfx)], document.duration, speed)
  const music = tracks.filter(isMusicTrack)
  const spoken = tracks.filter(track => !isMusicTrack(track))
  const windows: DuckWindow[] = []
  for (const track of spoken) {
    const buffer = await decodeVoice(track.audio!.url)
    const schedule = voiceSchedule(track.start, track.offset, buffer.duration, Math.min(document.duration, track.end ?? document.duration), speed)
    if (schedule.duration <= 0) continue
    const window = outputWindow(schedule.when, schedule.duration, schedule.rate)
    if (window) windows.push(window)
    scheduleBuffer(context, buffer, schedule, track.gain)
  }
  for (const track of music) {
    const buffer = await decodeVoice(track.audio!.url)
    const schedule = voiceSchedule(track.start, track.offset, buffer.duration, Math.min(document.duration, track.end ?? document.duration), speed)
    if (schedule.duration <= 0) continue
    const tape = soundtrackIsSceneTape(track.audio?.url, document)
    // The production tape is the audible mix. Music fades would swallow the first word and last 400 ms.
    if (tape && !windows.length) {
      scheduleBuffer(context, buffer, schedule, track.gain)
      continue
    }
    const span = schedule.duration / schedule.rate
    scheduleBuffer(context, buffer, schedule, track.gain, soundtrackGainCurve(schedule.when, span, track.gain, windows, !tape))
  }
  return context.startRendering()
}
