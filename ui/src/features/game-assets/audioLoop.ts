/** Loop points in seconds. */
export interface LoopPoints {
  start: number
  end: number
}

type AudioContextClass = new () => AudioContext

export function audioContextClass(): AudioContextClass | null {
  const scope = globalThis as { AudioContext?: AudioContextClass; webkitAudioContext?: AudioContextClass }
  return scope.AudioContext || scope.webkitAudioContext || null
}

function fourCC(view: DataView, offset: number): string {
  return String.fromCharCode(view.getUint8(offset), view.getUint8(offset + 1), view.getUint8(offset + 2), view.getUint8(offset + 3))
}

/** The rate in a RIFF/WAVE ``fmt `` chunk, or 0. ``decodeAudioData`` resamples to the context rate. */
export function wavSampleRate(data: ArrayBuffer): number {
  const view = new DataView(data)
  if (view.byteLength < 12 || fourCC(view, 0) !== 'RIFF' || fourCC(view, 8) !== 'WAVE') return 0
  let offset = 12
  while (offset + 8 <= view.byteLength) {
    const size = view.getUint32(offset + 4, true)
    if (fourCC(view, offset) === 'fmt ') return offset + 16 <= view.byteLength ? view.getUint32(offset + 12, true) : 0
    offset += 8 + size + (size % 2)
  }
  return 0
}

/** Sample indices to seconds. ``loopEnd`` is inclusive, so the loop ends one sample after it. */
export function loopSeconds(loop: { start: number; end: number } | null, rate: number, duration: number): LoopPoints {
  if (!loop || rate <= 0) return { start: 0, end: duration }
  const start = Math.max(0, loop.start / rate)
  const end = Math.min(duration, (loop.end + 1) / rate)
  return end > start ? { start, end } : { start: 0, end: duration }
}

/** Where playback is and how many times it wrapped, after ``elapsed`` seconds from ``from``. */
export function loopPosition(from: number, elapsed: number, loop: LoopPoints): { position: number; turns: number } {
  const at = from + Math.max(0, elapsed)
  const length = loop.end - loop.start
  if (at < loop.end || length <= 0) return { position: Math.min(at, loop.end), turns: 0 }
  const over = at - loop.end
  return { position: loop.start + (over % length), turns: 1 + Math.floor(over / length) }
}

/** Two seconds before the loop end, so the wrap is heard right away. */
export function seamStart(loop: LoopPoints): number {
  return Math.max(loop.start, loop.end - 2)
}

async function fetchAudio(url: string): Promise<ArrayBuffer> {
  const response = await fetch(url)
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  return response.arrayBuffer()
}

/** One music take looped with an ``AudioBufferSourceNode`` between its sample-exact loop points. */
export class LoopEngine {
  private readonly url: string
  private readonly samples: { start: number; end: number } | null
  private context: AudioContext | null = null
  private buffer: AudioBuffer | null = null
  private source: AudioBufferSourceNode | null = null
  private loop: LoopPoints = { start: 0, end: 0 }
  private startedAt = 0
  private from = 0

  constructor(url: string, samples: { start: number; end: number } | null) {
    this.url = url
    this.samples = samples
  }

  points(): LoopPoints {
    return this.loop
  }

  private async load(context: AudioContext): Promise<AudioBuffer> {
    if (this.buffer) return this.buffer
    const data = await fetchAudio(this.url)
    const rate = wavSampleRate(data) // read before decoding: decoding detaches the bytes
    const buffer = await context.decodeAudioData(data)
    this.loop = loopSeconds(this.samples, rate || buffer.sampleRate, buffer.duration)
    this.buffer = buffer
    return buffer
  }

  async play(fromSeam: boolean): Promise<void> {
    const Context = audioContextClass()
    if (!Context) throw new Error('Web Audio is not available')
    this.context = this.context || new Context()
    const context = this.context
    const buffer = await this.load(context)
    if (this.context !== context) return // closed while the take loaded
    this.stop()
    if (context.state === 'suspended') await context.resume()
    if (this.context !== context) return
    const source = context.createBufferSource()
    source.buffer = buffer
    source.loop = true
    source.loopStart = this.loop.start
    source.loopEnd = this.loop.end
    source.connect(context.destination)
    this.from = fromSeam ? seamStart(this.loop) : 0
    this.startedAt = context.currentTime
    source.start(0, this.from)
    this.source = source
  }

  turns(): number {
    if (!this.context || !this.source) return 0
    return loopPosition(this.from, this.context.currentTime - this.startedAt, this.loop).turns
  }

  stop(): void {
    const source = this.source
    this.source = null
    if (!source) return
    try { source.stop() } catch { /* a source that never started cannot stop */ }
    source.disconnect()
  }

  /** Pause the context (e.g. a hidden tab); ``resume`` carries on from the same sample. */
  suspend(): void {
    if (this.context?.state === 'running') void this.context.suspend().catch(() => undefined)
  }

  resume(): void {
    if (this.source && this.context?.state === 'suspended') void this.context.resume().catch(() => undefined)
  }

  close(): void {
    this.stop()
    const context = this.context
    this.context = null
    if (context && context.state !== 'closed') void context.close().catch(() => undefined)
  }
}
