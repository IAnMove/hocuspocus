import { imagePoseAtTime, imagePoseBounds, imagePoseRect, type ImagePose } from './imagePoseSequence'
import type { MediaScreen } from './mediaScreen'

export async function loadImagePoses(poses: readonly ImagePose[], signal: AbortSignal) {
  // Retain bounded canvases rather than full-resolution decoded source images.
  const images: { canvas: HTMLCanvasElement; bounds: ReturnType<typeof imagePoseBounds> }[] = []
  for (const pose of poses) {
    if (signal.aborted) throw new Error('screen-media-disposed')
    const image = new Image(); image.crossOrigin = 'anonymous'
    let timer: ReturnType<typeof setTimeout> | undefined
    let abortLoad: (() => void) | undefined
    try {
      image.src = pose.sourceUrl
      await Promise.race([image.decode(), new Promise<never>((_, reject) => {
        timer = setTimeout(() => reject(new Error('pose-sequence-load-timeout')), 15000)
        abortLoad = () => reject(new Error('screen-media-disposed'))
        signal.addEventListener('abort', abortLoad, { once: true })
      })])
      if (signal.aborted) throw new Error('screen-media-disposed')
      const ratio = Math.min(1, 1280 / Math.max(image.naturalWidth, image.naturalHeight))
      const canvas = document.createElement('canvas')
      canvas.width = Math.max(1, Math.round(image.naturalWidth * ratio)); canvas.height = Math.max(1, Math.round(image.naturalHeight * ratio))
      const context = canvas.getContext('2d', { willReadFrequently: true })!
      context.drawImage(image, 0, 0, canvas.width, canvas.height)
      const bounds = imagePoseBounds(context.getImageData(0, 0, canvas.width, canvas.height).data, canvas.width, canvas.height)
      images.push({ canvas, bounds })
    } finally {
      clearTimeout(timer); if (abortLoad) signal.removeEventListener('abort', abortLoad); image.src = ''
    }
  }
  return {
    paint(context: CanvasRenderingContext2D, screen: MediaScreen, seconds: number) {
      const frames = screen.poseSequence ?? poses
      const index = imagePoseAtTime(frames, seconds, screen), image = images[index]
      if (!image) throw new Error('pose-sequence-missing-image')
      const target = imagePoseRect(frames[index], image.bounds, context.canvas.width, context.canvas.height)
      context.clearRect(0, 0, context.canvas.width, context.canvas.height)
      const b = image.bounds
      context.drawImage(image.canvas, b.x, b.y, b.width, b.height, target.x, target.y, target.width, target.height)
    },
    dispose() { for (const image of images) { image.canvas.width = 0; image.canvas.height = 0 }; images.length = 0 },
  }
}
