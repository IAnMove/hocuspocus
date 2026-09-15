import { CanvasTexture, DoubleSide, Mesh, MeshBasicMaterial, SRGBColorSpace, type Object3D } from 'three'
import { mediaScreenRect, mediaScreenTime, type MediaScreen } from './mediaScreen.ts'
import { SCREEN_PLANE_NAME, attachScreenPlane, detachScreenPlane, screenUsesPlane } from './screenPlane.ts'
import { applyPsxImageMaterial, type ImageLook } from './imageLook'

export type ScreenMediaRuntime = {
  ready: boolean
  error: Error | null
  seek: (seconds: number, screen: MediaScreen) => Promise<void>
  dispose: () => void
}

function waitMedia(video: HTMLVideoElement, event: 'loadeddata' | 'seeked', signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    const finish = (error?: Error) => {
      clearTimeout(timer); video.removeEventListener(event, done); video.removeEventListener('error', failed); signal.removeEventListener('abort', aborted)
      if (error) reject(error); else resolve()
    }
    const done = () => finish(), failed = () => finish(new Error('screen-media-load-failed')), aborted = () => finish(new Error('screen-media-disposed'))
    const timer = setTimeout(() => finish(new Error('screen-media-timeout')), 15000)
    video.addEventListener(event, done, { once: true }); video.addEventListener('error', failed, { once: true }); signal.addEventListener('abort', aborted, { once: true })
    if (signal.aborted) aborted()
  })
}

/** Video is paused and sought from the scene clock, including during export. */
export async function bindScreenMedia(root: Object3D, screen: MediaScreen, standalone: boolean, signal: AbortSignal, onFrame: () => void = () => {}, imagePlate?: { look?: ImageLook }): Promise<ScreenMediaRuntime> {
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
  const canvas = document.createElement('canvas')
  const target = targets[0], previous = target.material
  const geometry = target.geometry as { parameters?: { width?: number; height?: number } }
  const aspect = imagePlate && geometry.parameters?.width && geometry.parameters.height
    ? geometry.parameters.width / geometry.parameters.height : screen.width / screen.height
  canvas.width = Math.max(2, Math.round(Math.min(1920, 1080 * aspect))); canvas.height = Math.max(2, Math.round(canvas.width / aspect))
  const context = canvas.getContext('2d')!
  const texture = new CanvasTexture(canvas); texture.colorSpace = SRGBColorSpace; texture.flipY = imagePlate || standalone || plane ? !screen.flipY : screen.flipY
  const material = imagePlate && !Array.isArray(previous) && 'map' in previous ? previous.clone() as MeshBasicMaterial
    : new MeshBasicMaterial({ toneMapped: false, side: DoubleSide })
  material.map = texture
  if (imagePlate?.look?.psx) applyPsxImageMaterial(material, texture, imagePlate.look.psx)
  const video = screen.media === 'video' ? document.createElement('video') : null
  const image = video ? null : new Image()
  const abort = new AbortController()
  let released = false
  const runtime: ScreenMediaRuntime = { ready: false, error: null, seek: async () => {}, dispose: () => {
    if (released) return
    released = true
    abort.abort(); if (video) { video.pause(); video.removeAttribute('src'); video.load() }
    if (image) image.src = ''; target.material = previous; texture.dispose(); material.dispose()
    if (attachedPlane) detachScreenPlane(root, attachedPlane)
  } }
  const disposed = () => runtime.dispose()
  signal.addEventListener('abort', disposed, { once: true })
  const paint = () => {
    const source = video ?? image!, width = video?.videoWidth ?? image!.naturalWidth, height = video?.videoHeight ?? image!.naturalHeight
    if (!width || !height || abort.signal.aborted) return
    const r = mediaScreenRect(canvas.width, canvas.height, width, height, screen.fit)
    context.fillStyle = '#080c13'; context.fillRect(0, 0, canvas.width, canvas.height); context.drawImage(source, r.x, r.y, r.width, r.height); texture.needsUpdate = true
    onFrame()
  }
  try {
    if (signal.aborted) throw new Error('screen-media-disposed')
    if (video) {
      video.crossOrigin = 'anonymous'; video.muted = true; video.playsInline = true; video.preload = 'auto'
      const loaded = waitMedia(video, 'loadeddata', abort.signal); video.src = screen.sourceUrl; video.load(); await loaded
    } else {
      image!.crossOrigin = 'anonymous'; image!.src = screen.sourceUrl; await image!.decode()
    }
    if (abort.signal.aborted) throw new Error('screen-media-disposed')
    target.material = material; paint(); runtime.ready = true
    let pending: Promise<void> | null = null, desired = 0, settled = 0
    runtime.seek = async (seconds, current) => {
      if (runtime.error) throw runtime.error
      if (!video || abort.signal.aborted) return
      desired = mediaScreenTime(seconds, video.duration, current)
      // Browsers snap to a frame; retrying the same clock time never lands exactly and hangs export.
      while (!abort.signal.aborted && (pending || settled !== desired)) {
        if (!pending) pending = (async () => {
          while (!abort.signal.aborted && settled !== desired) {
            const target = desired
            if (Math.abs(video.currentTime - target) > .0005) {
              const sought = waitMedia(video, 'seeked', abort.signal); video.currentTime = target; await sought; paint()
            }
            settled = target
          }
        })().catch(error => { runtime.error = error instanceof Error ? error : new Error(String(error)); throw runtime.error }).finally(() => { pending = null })
        await pending
      }
    }
    return runtime
  } catch (error) { runtime.dispose(); throw error }
  finally { signal.removeEventListener('abort', disposed) }
}
