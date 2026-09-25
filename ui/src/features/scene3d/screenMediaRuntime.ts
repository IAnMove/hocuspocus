import { CanvasTexture, DoubleSide, Mesh, MeshBasicMaterial, SRGBColorSpace, type Object3D } from 'three'
import { mediaScreenRect, mediaScreenTime, type MediaScreen } from './mediaScreen.ts'
import { SCREEN_PLANE_NAME, attachScreenPlane, detachScreenPlane, screenUsesPlane } from './screenPlane.ts'
import { applyPsxImageMaterial, type ImageLook } from './imageLook'
import { applyImageColorKey } from './imageColorKey'
import { loadImagePoses } from './imagePoseRuntime'

export type ScreenMediaRuntime = {
  /** The painted picture, for light the screen throws on its surroundings. */
  canvas?: HTMLCanvasElement
  ready: boolean
  error: Error | null
  seek: (seconds: number, screen: MediaScreen) => Promise<void>
  dispose: () => void
}

function waitMedia(video: HTMLVideoElement, event: 'loadeddata' | 'seeked', signal: AbortSignal, target?: number) {
  return new Promise<void>((resolve, reject) => {
    const finish = (error?: Error) => {
      clearTimeout(timer)
      video.removeEventListener(event, done)
      video.removeEventListener('timeupdate', onTime)
      video.removeEventListener('error', failed)
      signal.removeEventListener('abort', aborted)
      if (error) reject(error); else resolve()
    }
    const done = () => finish(), failed = () => finish(new Error('screen-media-load-failed')), aborted = () => finish(new Error('screen-media-disposed'))
    const onTime = () => {
      if (event === 'seeked' && target !== undefined && Number.isFinite(video.currentTime) && Math.abs(video.currentTime - target) <= .05) done()
    }
    // Seeked can miss on short clips. Do not stall export, but give a real
    // decoder time to land before painting the previous frame.
    const timer = setTimeout(
      () => event === 'seeked' ? finish() : finish(new Error('screen-media-timeout')),
      event === 'seeked' ? 2_000 : 15_000,
    )
    video.addEventListener(event, done, { once: true })
    if (event === 'seeked') video.addEventListener('timeupdate', onTime)
    video.addEventListener('error', failed, { once: true })
    signal.addEventListener('abort', aborted, { once: true })
    if (signal.aborted) aborted()
  })
}

function resolveScreenTarget(root: Object3D, screen: MediaScreen, standalone: boolean, imagePlate: boolean) {
  const plane = !imagePlate && screenUsesPlane(screen, standalone)
  const attachedPlane = plane ? attachScreenPlane(root, screen) : undefined
  const targetName = standalone ? 'SCREEN_CONTENT' : plane ? SCREEN_PLANE_NAME : screen.targetMesh
  const targets: Mesh[] = []
  if (imagePlate && root instanceof Mesh) targets.push(root)
  else root.traverse(child => { if (child instanceof Mesh && child.name === targetName) targets.push(child) })
  if (targets.length !== 1) {
    if (attachedPlane) detachScreenPlane(root, attachedPlane)
    throw new Error(targets.length ? 'screen-mesh-ambiguous' : 'screen-mesh-missing')
  }
  return { target: targets[0], attachedPlane, plane }
}

function screenSurfaceAspect(target: Mesh, screen: MediaScreen, imagePlate: boolean) {
  const geometry = target.geometry as { parameters?: { width?: number; height?: number } }
  return imagePlate && geometry.parameters?.width && geometry.parameters.height
    ? geometry.parameters.width / geometry.parameters.height : screen.width / screen.height
}

function applyScreenLook(material: MeshBasicMaterial, texture: CanvasTexture, screen: MediaScreen, imagePlate?: { look?: ImageLook }) {
  material.map = texture
  if (screen.transparent || screen.poseSequence) {
    material.transparent = true
    material.alphaTest = .05
    material.depthWrite = true
  }
  if (imagePlate?.look?.psx) applyPsxImageMaterial(material, texture, imagePlate.look.psx)
  if (imagePlate?.look?.colorKey) applyImageColorKey(material, imagePlate.look.colorKey)
}

function prepareScreenSurface(root: Object3D, screen: MediaScreen, standalone: boolean, imagePlate?: { look?: ImageLook }) {
  const { target, attachedPlane, plane } = resolveScreenTarget(root, screen, standalone, Boolean(imagePlate))
  const canvas = document.createElement('canvas')
  const previous = target.material
  const aspect = screenSurfaceAspect(target, screen, Boolean(imagePlate))
  // A CRT shows few lines; a small picture is both authentic and cheap for a wall of TVs.
  const lines = screen.style === 'crt' ? 240 : 1080
  canvas.width = Math.max(2, Math.round(Math.min(1920, lines * aspect))); canvas.height = Math.max(2, Math.round(canvas.width / aspect))
  const context = canvas.getContext('2d')!
  const texture = new CanvasTexture(canvas); texture.colorSpace = SRGBColorSpace; texture.flipY = imagePlate || standalone || plane ? !screen.flipY : screen.flipY
  const material = imagePlate && !Array.isArray(previous) && 'map' in previous ? previous.clone() as MeshBasicMaterial
    : new MeshBasicMaterial({ toneMapped: false, side: DoubleSide })
  applyScreenLook(material, texture, screen, imagePlate)
  return { attachedPlane, target, previous, canvas, context, texture, material }
}

type SharedVideo = { url: string; video: HTMLVideoElement; users: number; ready: Promise<void>; busy: boolean; waiting: (() => void)[]; pooled: boolean; sought?: number }
const sharedVideos = new Map<string, SharedVideo>()

/** TVs showing the same clip share one decoder: a wall of TVs in sync costs
 *  one seek per frame instead of one per TV. Other screens keep their own. */
function acquireVideo(url: string, pooled: boolean): SharedVideo {
  const known = pooled ? sharedVideos.get(url) : undefined
  if (known) { known.users++; return known }
  const video = document.createElement('video')
  video.crossOrigin = 'anonymous'; video.muted = true; video.playsInline = true; video.preload = 'auto'
  const ready = waitMedia(video, 'loadeddata', new AbortController().signal)
  video.src = url; video.load()
  const shared: SharedVideo = { url, video, users: 1, ready, busy: false, waiting: [], pooled }
  if (pooled) {
    ready.catch(() => { if (sharedVideos.get(url) === shared) sharedVideos.delete(url) })
    sharedVideos.set(url, shared)
  }
  return shared
}

function releaseVideo(shared: SharedVideo) {
  if (--shared.users > 0) return
  if (sharedVideos.get(shared.url) === shared) sharedVideos.delete(shared.url)
  shared.video.pause(); shared.video.removeAttribute('src'); shared.video.load()
}

/** Seek and paint without another screen moving the shared decoder between.
 *  A free decoder starts the seek at once, in the caller's turn. */
function exclusive(shared: SharedVideo, task: () => Promise<void>): Promise<void> {
  const run = () => {
    shared.busy = true
    return task().finally(() => { shared.busy = false; shared.waiting.shift()?.() })
  }
  if (!shared.busy) return run()
  return new Promise((resolve, reject) => shared.waiting.push(() => { run().then(resolve, reject) }))
}

function untilAborted<T>(promise: Promise<T>, signal: AbortSignal) {
  return new Promise<T>((resolve, reject) => {
    const aborted = () => reject(new Error('screen-media-disposed'))
    if (signal.aborted) { aborted(); return }
    signal.addEventListener('abort', aborted, { once: true })
    promise.then(resolve, reject).finally(() => signal.removeEventListener('abort', aborted))
  })
}

/** Scanlines, a darker rim and a glint of curved glass, drawn over each
 *  frame of a CRT picture. */
function crtOverlay(width: number, height: number) {
  const overlay = document.createElement('canvas')
  overlay.width = width; overlay.height = height
  const context = overlay.getContext('2d')
  if (!context) return overlay
  context.fillStyle = 'rgba(0,0,0,.3)'
  for (let y = 0; y < height; y += 3) context.fillRect(0, y, width, 1)
  const rim = context.createRadialGradient(width / 2, height / 2, Math.min(width, height) * .35, width / 2, height / 2, Math.hypot(width, height) * .55)
  rim.addColorStop(0, 'rgba(0,0,0,0)'); rim.addColorStop(1, 'rgba(0,0,0,.65)')
  context.fillStyle = rim; context.fillRect(0, 0, width, height)
  const glint = context.createLinearGradient(0, 0, width * .6, height * .6)
  glint.addColorStop(0, 'rgba(255,255,255,.09)'); glint.addColorStop(.45, 'rgba(255,255,255,0)')
  context.fillStyle = glint; context.fillRect(0, 0, width, height)
  return overlay
}

/** One picture on the screen canvas: optional matte, then the source, then
 *  the CRT tube over it. */
function drawScreenFrame(context: CanvasRenderingContext2D, canvas: HTMLCanvasElement, source: CanvasImageSource, r: { x: number; y: number; width: number; height: number },
  look: { matte: boolean; tube: HTMLCanvasElement | null; hue?: number }) {
  const { width, height } = canvas
  context.clearRect(0, 0, width, height)
  if (look.matte) { context.fillStyle = '#080c13'; context.fillRect(0, 0, width, height) }
  // Canvas filters cost CPU on every frame; only shifted tubes pay for one.
  const shifted = Boolean(look.tube && look.hue)
  if (shifted) context.filter = `hue-rotate(${look.hue}deg) saturate(1.25)`
  context.drawImage(source, r.x, r.y, r.width, r.height)
  if (shifted) context.filter = 'none'
  if (look.tube) context.drawImage(look.tube, 0, 0)
}

async function loadScreenSource(screen: MediaScreen, shared: SharedVideo | null, image: HTMLImageElement | null, signal: AbortSignal) {
  if (screen.poseSequence) return loadImagePoses(screen.poseSequence, signal)
  if (shared) await untilAborted(shared.ready, signal)
  else { image!.crossOrigin = 'anonymous'; image!.src = screen.sourceUrl; await image!.decode() }
  return undefined
}

/** Video is paused and sought from the scene clock, including during export. */
export async function bindScreenMedia(root: Object3D, screen: MediaScreen, standalone: boolean, signal: AbortSignal, onFrame: () => void = () => {}, imagePlate?: { look?: ImageLook }): Promise<ScreenMediaRuntime> {
  const { attachedPlane, target, previous, canvas, context, texture, material } = prepareScreenSurface(root, screen, standalone, imagePlate)
  const shared = screen.media === 'video' ? acquireVideo(screen.sourceUrl, screen.style === 'crt') : null
  const video = shared?.video ?? null
  const image = video || screen.poseSequence ? null : new Image()
  let poses: Awaited<ReturnType<typeof loadImagePoses>> | undefined
  const abort = new AbortController()
  let released = false
  const tube = screen.style === 'crt' ? crtOverlay(canvas.width, canvas.height) : null
  const runtime: ScreenMediaRuntime = { canvas, ready: false, error: null, seek: async () => {}, dispose: () => {
    if (released) return
    released = true
    abort.abort(); if (shared) releaseVideo(shared)
    if (image) image.src = ''; target.material = previous; texture.dispose(); material.dispose()
    poses?.dispose()
    if (attachedPlane) detachScreenPlane(root, attachedPlane)
  } }
  const disposed = () => runtime.dispose()
  signal.addEventListener('abort', disposed, { once: true })
  const paint = () => {
    if (poses) { poses.paint(context, screen, 0); texture.needsUpdate = true; onFrame(); return }
    const source = video ?? image!, width = video?.videoWidth ?? image!.naturalWidth, height = video?.videoHeight ?? image!.naturalHeight
    if (!width || !height || abort.signal.aborted) return
    const r = mediaScreenRect(canvas.width, canvas.height, width, height, screen.fit)
    drawScreenFrame(context, canvas, source, r, { matte: !screen.transparent && !imagePlate?.look?.colorKey, tube, hue: screen.hue })
    texture.needsUpdate = true
    onFrame()
  }
  try {
    if (signal.aborted) throw new Error('screen-media-disposed')
    poses = await loadScreenSource(screen, shared, image, abort.signal)
    if (abort.signal.aborted) throw new Error('screen-media-disposed')
    target.material = material; paint(); runtime.ready = true
    let pending: Promise<void> | null = null, desired = 0, settled = 0, shown = video?.currentTime ?? 0
    runtime.seek = async (seconds, current) => {
      if (runtime.error) throw runtime.error
      if (poses && !abort.signal.aborted) { poses.paint(context, current, seconds); texture.needsUpdate = true; onFrame(); return }
      if (!video || !shared || abort.signal.aborted) return
      const next = mediaScreenTime(seconds, video.duration, current)
      desired = Number.isFinite(next) ? next : 0
      // Browsers snap to a frame; retrying the same clock time never lands exactly and hangs export.
      while (!abort.signal.aborted && (pending || settled !== desired)) {
        if (!pending) pending = (async () => {
          while (!abort.signal.aborted && settled !== desired) {
            await exclusive(shared!, async () => {
              // Read desired here: waiters must follow the latest clock, not the
              // time they queued with, or a wall of TVs keeps seeking backwards.
              const target = desired
              if (Number.isFinite(target) && shared.sought !== target && Math.abs(video.currentTime - target) > .0005) {
                try {
                  const sought = waitMedia(video, 'seeked', abort.signal, target); video.currentTime = target; await sought
                } catch (error) {
                  if (abort.signal.aborted) throw error instanceof Error ? error : new Error(String(error))
                }
              }
              if (Number.isFinite(target)) shared.sought = target
              // Another screen may already have brought the decoder here.
              if (shown !== target) { paint(); shown = target }
              settled = Number.isFinite(target) ? target : 0
            })
          }
        })().catch(error => { runtime.error = error instanceof Error ? error : new Error(String(error)); throw runtime.error }).finally(() => { pending = null })
        await pending
      }
    }
    return runtime
  } catch (error) { runtime.dispose(); throw error }
  finally { signal.removeEventListener('abort', disposed) }
}
