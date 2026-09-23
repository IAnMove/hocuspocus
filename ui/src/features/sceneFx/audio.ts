import { FX_CATALOG, fxRandom, type SceneFx } from './types'
import { strokeTimes } from './lightningBolt'

const TAU = Math.PI * 2
/** Samples of filter history computed before a block, so blocks rendered
 *  one second at a time join without clicks. */
const WARMUP = 2048

/** White noise filtered to below `cutoff` Hz, rescaled to roughly unit
 *  loudness so a rumble and a hiss can be mixed by ear. */
function lowNoise(seed: number, first: number, count: number, sampleRate: number, cutoff: number) {
  const alpha = 1 - Math.exp(-TAU * cutoff / sampleRate)
  const gain = 1 / (.577 * Math.sqrt(alpha / (2 - alpha)))
  const out = new Float32Array(count)
  let state = 0
  for (let i = Math.max(0, first - WARMUP); i < first + count; i++) {
    state += alpha * (fxRandom(seed, i) * 2 - 1 - state)
    if (i >= first) out[i - first] = state * gain * .33
  }
  return out
}

/** Short decaying bursts on a jittered grid: fire pops, raindrops. The same
 *  sample always lands in the same slot, so no state crosses blocks. */
function pops(seed: number, t: number, slot: number, chance: number, decay: number) {
  let value = 0
  for (const index of [Math.floor(t / slot), Math.floor(t / slot) - 1]) {
    if (index < 0 || fxRandom(seed, index * 3) > chance) continue
    const at = (index + fxRandom(seed, index * 3 + 1) * .8) * slot
    if (t >= at) value += (fxRandom(seed, index * 3 + 2) * .6 + .4) * Math.exp(-(t - at) * decay)
  }
  return value
}

type Bank = { white: number; low: Float32Array; mid: Float32Array; high: Float32Array }

/** A strike's crack, then the rolling rumble that trails it. */
function thunder(cue: SceneFx, t: number, bank: Bank, i: number, strokes: readonly number[]) {
  let value = 0
  for (const at of strokes) {
    const dt = t - at
    if (dt < 0 || dt > 4) continue
    value += (bank.white - bank.mid[i] * .6) * Math.exp(-dt * 26) * .7
    const delay = .12 + fxRandom(cue.seed, Math.round(at * 100)) * .3, rt = dt - delay
    if (rt > 0) value += bank.low[i] * Math.min(1, rt * 7) * Math.exp(-rt * 1.1) * (.55 + .45 * Math.sin(rt * 5.3 + at))
  }
  return value
}

function sample(sound: string | undefined, cue: SceneFx, t: number, p: number, seconds: number, bank: Bank, i: number, strokes: readonly number[]) {
  const { white } = bank
  switch (sound) {
    case 'impact': return Math.sin(TAU * (58 * t - 9 * t * t)) * Math.exp(-t * 6) * .8 + bank.low[i] * Math.exp(-t * 3.5) * .45 + white * Math.exp(-t * 45) * .35
    case 'crackle': return bank.mid[i] * .2 * (.7 + .3 * Math.sin(t * 2.3)) + (white * .7 + bank.high[i] * .3) * pops(cue.seed, t, .035, .45, 260) * .95
    case 'rain': return (white - bank.mid[i]) * .16 + (white - bank.high[i]) * pops(cue.seed + 7, t, .009, .3, 900) * .22
    case 'wind': {
      const gust = .55 + .45 * Math.sin(t * .9 + Math.sin(t * .37) * 2)
      return (bank.low[i] * (1 - gust) + bank.mid[i] * gust) * .36
    }
    case 'pop': return Math.sin(TAU * (380 - 160 * (t % .4)) * t) * Math.exp(-(t % .4) * 70) * .6
    case 'chime': return (Math.sin(t * TAU * 880) + Math.sin(t * TAU * 1320) * .35 + Math.sin(t * TAU * 1760) * .12) * Math.exp(-t * 2) * .45
    case 'rise': return Math.sin(TAU * (120 * t + 100 * t * t / seconds)) * Math.sin(p * Math.PI) * .3 + bank.mid[i] * p * .05
    case 'whoosh': {
      const shape = Math.pow(Math.sin(p * Math.PI), 2)
      return (bank.mid[i] * (1 - shape) + bank.high[i] * shape) * shape * .45
    }
    case 'scan': return Math.sin(TAU * (400 * t + 80 * t * t)) * .13 + Math.sin(TAU * 8 * t) * Math.sin(TAU * 1200 * t) * .04
    case 'laser': return (Math.sin(TAU * (900 * t - 300 * t * t / seconds)) + Math.sin(TAU * (1805 * t - 600 * t * t / seconds)) * .25) * Math.exp(-t * 3) * .45
    case 'magic': return (Math.sin(TAU * (520 * t + 60 * t * t)) + Math.sin(TAU * 780 * t) * .4) * (.2 + .12 * Math.sin(t * 18)) * Math.sin(p * Math.PI)
    case 'power': return (Math.sin(TAU * (55 * t + 70 * t * t / seconds)) * .45 + bank.low[i] * .2) * Math.sin(p * Math.PI)
    case 'thunder': return thunder(cue, t, bank, i, strokes)
    case 'slash': return (bank.high[i] * .6 + Math.sin(TAU * (1600 * t - 600 * t * t / seconds)) * .2) * Math.pow(Math.sin(p * Math.PI), 4)
    default: return 0
  }
}

/** Small procedural Foley palette; these sounds are synthesized locally, not AI output. */
export function fxSamples(cue: SceneFx, sampleRate: number, offset = 0, duration = cue.end - cue.start - offset): Float32Array<ArrayBuffer> {
  const seconds = cue.end - cue.start
  const sound = FX_CATALOG.find(item => item.id === cue.kind)?.sound
  const data = new Float32Array(Math.ceil(duration * sampleRate))
  const first = Math.round(offset * sampleRate)
  const low = lowNoise(cue.seed + 101, first, data.length, sampleRate, 90)
  const mid = lowNoise(cue.seed + 202, first, data.length, sampleRate, 700)
  const high = lowNoise(cue.seed + 303, first, data.length, sampleRate, 3200)
  // Lightning thunders on its own strikes; other storms roll on a steady beat.
  const strokes = sound !== 'thunder' ? [] : cue.kind === 'lightning'
    ? strokeTimes(cue.seed, seconds)
    : Array.from({ length: Math.ceil(seconds / .7) }, (_, k) => k * .7 + fxRandom(cue.seed, 700 + k) * .2)
  for (let i = 0; i < data.length; i++) {
    const t = offset + i / sampleRate
    const bank = { white: fxRandom(cue.seed, first + i) * 2 - 1, low, mid, high }
    const edge = Math.min(1, t * 50, (seconds - t) * 20)
    const value = sample(sound, cue, t, t / seconds, seconds, bank, i, strokes) * edge * cue.volume
    data[i] = Math.max(-1, Math.min(1, value))
  }
  return data
}

/** Mix into ONE timeline buffer, avoiding 64 retained full-length audio buffers. */
export function scheduleFx(context: BaseAudioContext, cues: readonly SceneFx[], duration: number, speed = 1, offset = 0) {
  const audible = cues.filter(cue => cue.sound && cue.volume && Math.min(duration, cue.end) > Math.max(offset, cue.start))
  if (!audible.length) return []
  if (!Number.isFinite(duration) || duration <= 0 || duration > 600 || !Number.isFinite(offset) || offset < 0 || offset >= duration) throw new Error('Invalid SFX timeline.')
  const buffer = context.createBuffer(1, Math.ceil((duration - offset) * context.sampleRate), context.sampleRate)
  const mixed = buffer.getChannelData(0)
  for (const cue of audible) {
    // One short work block at a time, even for long ambient effects.
    const from = Math.max(offset, cue.start), end = Math.min(duration, cue.end)
    for (let at = from; at < end; at += 1) {
      const samples = fxSamples(cue, context.sampleRate, at - cue.start, Math.min(1, end - at))
      const target = Math.round((at - offset) * context.sampleRate)
      const count = Math.min(samples.length, mixed.length - target)
      for (let i = 0; i < count; i++) mixed[target + i] += samples[i]
    }
  }
  for (let i = 0; i < mixed.length; i++) mixed[i] = Math.max(-1, Math.min(1, mixed[i]))
  const source = context.createBufferSource(); source.buffer = buffer; source.playbackRate.value = speed
  source.connect(context.destination); source.start(context.currentTime)
  return [source]
}
