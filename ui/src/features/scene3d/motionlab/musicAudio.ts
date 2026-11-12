import type { MotionLabSettings } from './types'
import { beatSeconds, hasMotionLabMusic, MUSIC_LIMIT_SECONDS, musicContacts, type MusicContact, type MotionMusicKind } from './musicTimeline'

export { hasMotionLabMusic } from './musicTimeline'
export const MUSIC_SAMPLE_RATE = 16000
const TAU = Math.PI * 2

function noteSample(contact: MusicContact, time: number, tail: number): number {
  const phase = TAU * contact.frequency * time
  const envelope = Math.min(1, time / .003, (tail - time) / .025)
  const fundamental = Math.sin(phase) * Math.exp(-5 * time / tail)
  const partials = .32 * Math.sin(phase * 2.01) * Math.exp(-12 * time / tail)
    + .12 * Math.sin(phase * 3.99) * Math.exp(-22 * time / tail)
  return (fundamental + partials) * envelope * contact.velocity * .38
}

function mixContact(samples: Float32Array, contact: MusicContact, offset: number, rate: number, tail: number, volume: number) {
  const first = Math.max(0, Math.ceil((contact.seconds - offset) * rate))
  const last = Math.min(samples.length, Math.ceil((contact.seconds + tail - offset) * rate))
  for (let index = first; index < last; index++) {
    const time = offset + index / rate - contact.seconds
    samples[index] += noteSample(contact, time, tail) * volume
  }
}

/** Duration is the scene end; offset is its seek position. External speed follows scene playback/export.
 * One mono buffer, <=16 kHz and <=600 scene seconds (38.4 MB), regardless of density or contact count.
 * Cropping retains tails from earlier contacts and never restarts a note at the seek position.
 */
export function scheduleMotionLabMusic(context: BaseAudioContext, kind: string | undefined, settings: MotionLabSettings,
  duration: number, speed = 1, offset = 0): AudioBufferSourceNode[] {
  if (!hasMotionLabMusic(kind, settings)) return []
  if (!Number.isFinite(duration) || duration <= 0 || duration > MUSIC_LIMIT_SECONDS
    || !Number.isFinite(offset) || offset < 0 || offset >= duration || !Number.isFinite(speed) || speed <= 0) {
    throw new Error('Invalid Motion Lab music timeline.')
  }
  const started = context.currentTime, rate = Math.min(context.sampleRate, MUSIC_SAMPLE_RATE)
  const buffer = context.createBuffer(1, Math.ceil((duration - offset) * rate), rate)
  const samples = buffer.getChannelData(0), tail = Math.min(.65, beatSeconds(settings) * 2)
  for (const contact of musicContacts(kind as MotionMusicKind, settings, Math.max(0, offset - tail), duration)) {
    mixContact(samples, contact, offset, rate, tail, settings.volume)
  }
  for (let index = 0; index < samples.length; index++) samples[index] = Math.max(-1, Math.min(1, samples[index]))
  // A live audio clock advances during synthesis; export's offline clock stays at zero.
  const now = context.currentTime, skip = Math.max(0, now - started) * speed
  const remaining = duration - offset - skip
  if (remaining <= 0) return []
  const source = context.createBufferSource()
  source.buffer = buffer
  source.playbackRate.value = speed
  source.connect(context.destination)
  source.onended = () => source.disconnect()
  source.start(now, skip, remaining)
  return [source]
}
