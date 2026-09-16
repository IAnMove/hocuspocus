import type { VideoJsDocument, VideoJsScene, VideoJsSceneError } from './types.ts'

export const VIDEOJS_CHANNEL = 'hocuspocus-videojs'

/** Scene code is untrusted. The iframe has an opaque origin (sandbox without
 *  allow-same-origin) and this policy removes network, navigation targets and
 *  nested frames, so code cannot call the HocusPocus API or read app state.
 *  The Worker created from a blob inherits the same policy. */
export const VIDEOJS_SANDBOX_CSP = [
  "default-src 'none'",
  "script-src 'unsafe-inline' 'unsafe-eval' blob:",
  'worker-src blob:',
  'img-src data: blob:',
  "style-src 'unsafe-inline'",
  'font-src data:',
  "connect-src 'none'",
  "media-src 'none'",
  "frame-src 'none'",
  "form-action 'none'",
  "base-uri 'none'",
].join('; ')

const PARENT_TIMEOUT_MS = 60_000
const MAX_ERRORS = 50

export function videoJsSandboxSrcdoc(hostSource: string): string {
  const script = hostSource.replace(/<\/script/gi, '<\\/script')
  return `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${VIDEOJS_SANDBOX_CSP}"></head><body><script>${script}</script></body></html>`
}

export function sanitizeSceneErrors(value: unknown): VideoJsSceneError[] {
  if (!Array.isArray(value)) return []
  return value.slice(0, MAX_ERRORS).flatMap(item => {
    if (!item || typeof item !== 'object') return []
    const raw = item as Record<string, unknown>
    const phase = ['compile', 'setup', 'render', 'timeout', 'runtime'].includes(String(raw.phase)) ? raw.phase as VideoJsSceneError['phase'] : 'runtime'
    const line = typeof raw.line === 'number' && Number.isInteger(raw.line) && raw.line > 0 ? raw.line : undefined
    return [{
      sceneId: typeof raw.sceneId === 'string' ? raw.sceneId.slice(0, 64) : '',
      phase,
      message: typeof raw.message === 'string' ? raw.message.slice(0, 1000) : 'Unknown error',
      ...(line ? { line } : {}),
    }]
  })
}

export function mergeSceneErrors(current: VideoJsSceneError[], next: VideoJsSceneError[]): VideoJsSceneError[] {
  if (!next.length) return current
  const byScene = new Map(current.map(error => [error.sceneId, error]))
  let changed = false
  for (const error of next) {
    const previous = byScene.get(error.sceneId)
    if (previous?.message === error.message && previous.phase === error.phase) continue
    byScene.set(error.sceneId, error)
    changed = true
  }
  return changed ? [...byScene.values()] : current
}

export type VideoJsRenderSpec = Pick<VideoJsDocument, 'width' | 'height' | 'fps' | 'theme'> & {
  scenes: Array<Pick<VideoJsScene, 'id' | 'kind' | 'duration' | 'transition' | 'transitionDuration' | 'code'>>
}

/** Only the fields that change pixels; titles and notes never reach the sandbox. */
export function videoJsRenderSpec(document: VideoJsRenderSpec): VideoJsRenderSpec {
  return {
    width: document.width,
    height: document.height,
    fps: document.fps,
    theme: document.theme,
    scenes: document.scenes.map(({ id, kind, duration, transition, transitionDuration, code }) => ({ id, kind, duration, transition, transitionDuration, code })),
  }
}

export class VideoJsSandboxError extends Error {
  readonly sceneError: VideoJsSceneError

  constructor(sceneError: VideoJsSceneError) {
    super(sceneError.message)
    this.name = 'VideoJsSandboxError'
    this.sceneError = sceneError
  }
}

interface Waiter {
  resolve: (message: Record<string, unknown>) => void
  reject: (error: Error) => void
  timer: number
}

export interface VideoJsFrame {
  bitmap: ImageBitmap
  errors: VideoJsSceneError[]
}

/** Parent-side RPC with the sandbox. Requests are serialized: the sandbox
 *  renders one frame at a time and a crash invalidates the loaded document. */
export class VideoJsSandbox {
  private readonly iframe: HTMLIFrameElement
  private readonly booted: Promise<void>
  private readonly waiters = new Map<number, Waiter>()
  private chain: Promise<unknown> = Promise.resolve()
  private nextId = 1
  private loaded = false
  private disposed = false
  private readonly onMessage: (event: MessageEvent) => void

  constructor(host: HTMLElement, hostSource: string) {
    this.iframe = host.ownerDocument.createElement('iframe')
    this.iframe.setAttribute('sandbox', 'allow-scripts')
    this.iframe.setAttribute('aria-hidden', 'true')
    this.iframe.tabIndex = -1
    this.iframe.title = 'Video JS sandbox'
    this.iframe.style.cssText = 'position:absolute;width:1px;height:1px;border:0;opacity:0;pointer-events:none'
    let markBooted: () => void = () => undefined
    this.booted = new Promise(resolve => { markBooted = resolve })
    this.onMessage = event => {
      if (event.source !== this.iframe.contentWindow) return
      const data = event.data as Record<string, unknown> | null
      if (!data || data.channel !== VIDEOJS_CHANNEL) return
      if (data.type === 'boot') { markBooted(); return }
      const waiter = typeof data.id === 'number' ? this.waiters.get(data.id) : undefined
      if (!waiter) return
      this.waiters.delete(data.id as number)
      window.clearTimeout(waiter.timer)
      waiter.resolve(data)
    }
    window.addEventListener('message', this.onMessage)
    this.iframe.srcdoc = videoJsSandboxSrcdoc(hostSource)
    host.appendChild(this.iframe)
  }

  get isLoaded(): boolean {
    return this.loaded
  }

  private request(message: Record<string, unknown>): Promise<Record<string, unknown>> {
    const run = async () => {
      if (this.disposed) throw new Error('Video JS sandbox was closed')
      await this.booted
      const id = this.nextId++
      return new Promise<Record<string, unknown>>((resolve, reject) => {
        const timer = window.setTimeout(() => {
          this.waiters.delete(id)
          this.loaded = false
          reject(new Error('Video JS sandbox did not respond'))
        }, PARENT_TIMEOUT_MS)
        this.waiters.set(id, { resolve, reject, timer })
        this.iframe.contentWindow?.postMessage({ channel: VIDEOJS_CHANNEL, id, ...message }, '*')
      })
    }
    const result = this.chain.then(run, run)
    this.chain = result.catch(() => undefined)
    return result
  }

  private fatal(message: Record<string, unknown>): never {
    this.loaded = false
    const [error] = sanitizeSceneErrors([message.error])
    throw new VideoJsSandboxError(error ?? { sceneId: '', phase: 'runtime', message: 'Video JS sandbox failed' })
  }

  async load(document: VideoJsRenderSpec, sources: { runtime: string; three: string | null }): Promise<VideoJsSceneError[]> {
    this.loaded = false
    const reply = await this.request({ type: 'load', runtime: sources.runtime, three: sources.three, document: videoJsRenderSpec(document) })
    if (reply.type !== 'loaded') this.fatal(reply)
    this.loaded = true
    return sanitizeSceneErrors(reply.errors)
  }

  async frame(seconds: number): Promise<VideoJsFrame> {
    const reply = await this.request({ type: 'frame', time: Math.max(0, Number.isFinite(seconds) ? seconds : 0) })
    if (reply.type !== 'frame' || !(reply.bitmap instanceof ImageBitmap)) this.fatal(reply)
    return { bitmap: reply.bitmap as ImageBitmap, errors: sanitizeSceneErrors(reply.errors) }
  }

  dispose(): void {
    this.disposed = true
    this.loaded = false
    window.removeEventListener('message', this.onMessage)
    for (const waiter of this.waiters.values()) {
      window.clearTimeout(waiter.timer)
      waiter.reject(new Error('Video JS sandbox was closed'))
    }
    this.waiters.clear()
    this.iframe.remove()
  }
}
