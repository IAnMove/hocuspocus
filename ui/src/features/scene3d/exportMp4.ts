import { ArrayBufferTarget, Muxer } from 'mp4-muxer'
import { canonicalSceneFps } from '../../lib/sceneFps.ts'
import { encodeSpeechAudio } from './speech/encodeAudio'
import { scene3dFrameCount, scene3dFrameTime } from './clock.ts'
import { scene3dCopy } from './copy.ts'

export function throwIfAborted(signal?: AbortSignal) {
  if (!signal?.aborted) return
  throw signal.reason instanceof DOMException ? signal.reason : new DOMException('Aborted', 'AbortError')
}

export function evenDim(value: number): number {
  const n = Math.round(Number.isFinite(value) ? value : 0)
  return Math.max(2, n - (n % 2))
}

export function world3dExportSize(width: number, height: number) {
  const maxW = width >= height ? 1920 : 1080
  const maxH = width >= height ? 1080 : 1920
  const scale = Math.min(1, maxW / Math.max(1, width), maxH / Math.max(1, height))
  return {
    width: evenDim(width * scale),
    height: evenDim(height * scale),
  }
}

export function world3dEncoderConfig(width: number, height: number, fps: number): VideoEncoderConfig {
  const blocksPerSecond = Math.ceil(width / 16) * Math.ceil(height / 16) * fps
  return {
    codec: blocksPerSecond > 245760 ? 'avc1.64002a' : 'avc1.640028',
    width, height, framerate: fps,
    bitrate: Math.round(Math.max(4_000_000, Math.min(24_000_000, width * height * fps * 0.18))),
    avc: { format: 'avc' },
  }
}

export function world3dExportPlan(duration: number, fps: number) {
  const rate = canonicalSceneFps(fps)
  const count = scene3dFrameCount(duration, rate)
  const times = Array.from({ length: count }, (_, index) => scene3dFrameTime(index, duration, rate))
  return { count, fps: rate, times }
}

function nextPaint(): Promise<void> {
  return new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve())))
}

async function supportedEncoder(size: ReturnType<typeof world3dExportSize>, fps: number) {
  if (!('VideoEncoder' in window) || typeof VideoEncoder.isConfigSupported !== 'function') {
    throw new Error(scene3dCopy('stage.cannotEncode'))
  }
  const supported = await VideoEncoder.isConfigSupported(world3dEncoderConfig(size.width, size.height, fps))
  if (!supported.supported || !supported.config) {
    throw new Error(scene3dCopy('stage.cannotEncodeResolution'))
  }
  return supported.config
}

export async function encodeWorld3DFrames(options: {
  width: number
  height: number
  fps: number
  duration: number
  audio?: AudioBuffer
  paint: (seconds: number) => HTMLCanvasElement | Promise<HTMLCanvasElement>
  onProgress?: (index: number, count: number) => void
  overlay?: (context: CanvasRenderingContext2D, width: number, height: number, seconds: number) => void
  signal?: AbortSignal
}): Promise<Blob> {
  throwIfAborted(options.signal)
  const size = world3dExportSize(options.width, options.height)
  const plan = world3dExportPlan(options.duration, options.fps)
  const config = await supportedEncoder(size, plan.fps)
  throwIfAborted(options.signal)
  const copy = document.createElement('canvas')
  copy.width = size.width
  copy.height = size.height
  const context = copy.getContext('2d')
  if (!context) throw new Error(scene3dCopy('stage.exportCanvasFailed'))
  const audioChannels = options.audio ? Math.min(2, Math.max(1, options.audio.numberOfChannels || 1)) : 1
  const target = new ArrayBufferTarget()
  const muxer = new Muxer({
    target,
    video: { codec: 'avc', width: size.width, height: size.height, frameRate: plan.fps },
    fastStart: 'in-memory',
    audio: options.audio ? { codec: 'aac', numberOfChannels: audioChannels, sampleRate: options.audio.sampleRate } : undefined,
    firstTimestampBehavior: 'strict',
  })
  let encoderError: Error | null = null
  const encoder = new VideoEncoder({
    output: (chunk, metadata) => muxer.addVideoChunk(chunk, metadata),
    error: error => { encoderError = error instanceof Error ? error : new Error(String(error)) },
  })
  encoder.configure(config)
  const frameDurationUs = Math.round(1_000_000 / plan.fps)
  try {
    if (options.audio) await encodeSpeechAudio(muxer, options.audio)
    for (let index = 0; index < plan.count; index += 1) {
      throwIfAborted(options.signal)
      if (encoderError) throw encoderError
      const source = await options.paint(plan.times[index] ?? 0)
      context.drawImage(source, 0, 0, size.width, size.height)
      options.overlay?.(context, size.width, size.height, plan.times[index] ?? 0)
      await nextPaint()
      throwIfAborted(options.signal)
      const frame = new VideoFrame(copy, { timestamp: index * frameDurationUs, duration: frameDurationUs })
      encoder.encode(frame, { keyFrame: index % Math.max(1, plan.fps * 2) === 0 })
      frame.close()
      if (encoder.encodeQueueSize > 8) await encoder.flush()
      options.onProgress?.(index + 1, plan.count)
    }
    await encoder.flush()
    if (encoderError) throw encoderError
    muxer.finalize()
    return new Blob([target.buffer], { type: 'video/mp4' })
  } finally {
    if (encoder.state !== 'closed') encoder.close()
  }
}
