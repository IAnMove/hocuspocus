import { loadTalkingCutout } from './talkingCutout'
import { imageFootprint, type ImageFootprint } from './imageGrounding'
import { spriteFrame, type DirectionalSheet, type DirectionalSprite } from './directionalSprite'
import type { MediaScreen } from './mediaScreen'

/** Paints a directional 2D figure on the canvas of its image object (`screen.directional`, painted like `screen.talk` and
 * `screen.poseSequence`). The canvas is the plane `spriteFrame` describes: as wide as the widest cell, the boots on the
 * catalog's line, the figure `figure` of the height. Which cell and which way to mirror it is decided every frame from the
 * camera (`directionalView`, in the painter pass of `paintWorld`) and arrives as `screen.directional.view`. The sprite is
 * read from the screen being painted, so editing the heading or the walk repaints without reloading the sheets. */
const FOOTPRINT_SIDE = 384
const TALK_SIDE = 1024

type Sized = { image: CanvasImageSource; width: number; height: number }

async function decode(url: string, signal: AbortSignal): Promise<HTMLImageElement> {
  if (signal.aborted) throw new Error('screen-media-disposed')
  const image = new Image()
  image.crossOrigin = 'anonymous'
  image.src = url
  await image.decode()
  if (signal.aborted) throw new Error('screen-media-disposed')
  return image
}

/** Where the lowest opaque row of a pose is, read from a small copy of it. */
function poseFootprint(image: HTMLImageElement): ImageFootprint | null {
  const ratio = Math.min(1, FOOTPRINT_SIDE / Math.max(image.naturalWidth, image.naturalHeight))
  const canvas = document.createElement('canvas')
  canvas.width = Math.max(1, Math.round(image.naturalWidth * ratio)); canvas.height = Math.max(1, Math.round(image.naturalHeight * ratio))
  const context = canvas.getContext('2d', { willReadFrequently: true })
  if (!context) return null
  try {
    context.drawImage(image, 0, 0, canvas.width, canvas.height)
    return imageFootprint(context.getImageData(0, 0, canvas.width, canvas.height).data, canvas.width, canvas.height)
  } catch { return null } // An external image may not grant canvas readback.
}

/** The cell `frame` of a sheet, scaled to the canvas height and centred, mirrored about the middle of the canvas. */
function drawCell(context: CanvasRenderingContext2D, image: HTMLImageElement, sheet: DirectionalSheet, frame: number, mirror: boolean) {
  const { width, height } = context.canvas
  const cellWidth = image.naturalWidth / sheet.columns, cellHeight = image.naturalHeight / sheet.rows
  const scale = height / cellHeight
  context.save()
  if (mirror) { context.translate(width, 0); context.scale(-1, 1) }
  context.drawImage(image, (frame % sheet.columns) * cellWidth, Math.floor(frame / sheet.columns) * cellHeight, cellWidth, cellHeight,
    (width - cellWidth * scale) / 2, 0, cellWidth * scale, height)
  context.restore()
}

/** A pose picture with its boots on the line of the sheets and its height from the top to the boots the height of a figure. */
function drawPose(context: CanvasRenderingContext2D, pose: Sized, footprint: ImageFootprint | null, frame: { feet: number; figure: number }) {
  const { width, height } = context.canvas
  const below = footprint?.bottom ?? 0
  const scale = Math.min(frame.figure * height / (pose.height * (1 - below)), width / pose.width)
  const drawn = { width: pose.width * scale, height: pose.height * scale }
  context.drawImage(pose.image, (width - drawn.width) / 2, frame.feet * height - drawn.height * (1 - below), drawn.width, drawn.height)
}

export async function loadDirectionalSprite(screen: MediaScreen, signal: AbortSignal) {
  const sprite = screen.directional as DirectionalSprite
  const frame = spriteFrame(sprite)
  const sources = [...new Set(sprite.sheets.map(sheet => sheet.source))]
  const loaded = new Map(await Promise.all(sources.map(async source => [source, await decode(source, signal)] as const)))
  const poseImage = screen.sourceUrl ? await decode(screen.sourceUrl, signal).catch(() => null) : null
  const footprint = poseImage ? poseFootprint(poseImage) : null
  const talk = screen.talk && poseImage ? await loadTalkingCutout(screen.talk, signal) : null
  let talkCanvas: HTMLCanvasElement | null = null
  if (talk && poseImage) {
    const ratio = Math.min(1, TALK_SIDE / Math.max(poseImage.naturalWidth, poseImage.naturalHeight))
    talkCanvas = document.createElement('canvas')
    talkCanvas.width = Math.max(1, Math.round(poseImage.naturalWidth * ratio)); talkCanvas.height = Math.max(1, Math.round(poseImage.naturalHeight * ratio))
  }
  return {
    paint(context: CanvasRenderingContext2D, current: MediaScreen | undefined, seconds: number) {
      const live = current?.directional ?? sprite
      const view = live.view
      context.clearRect(0, 0, context.canvas.width, context.canvas.height)
      context.imageSmoothingQuality = 'high'
      const sheet = view?.kind === 'sheet' ? live.sheets[view.sheet] : undefined
      const image = sheet ? loaded.get(sheet.source) : undefined
      if (view?.kind === 'sheet' && sheet && image) { drawCell(context, image, sheet, view.frame, view.mirror); return }
      if (!poseImage) return
      if (view?.kind === 'pose' && view.talking && talk && talkCanvas) {
        talk.paint(talkCanvas.getContext('2d')!, current, seconds)
        drawPose(context, { image: talkCanvas, width: talkCanvas.width, height: talkCanvas.height }, footprint, frame)
      } else drawPose(context, { image: poseImage, width: poseImage.naturalWidth, height: poseImage.naturalHeight }, footprint, frame)
    },
    dispose() {
      for (const image of loaded.values()) image.src = ''
      loaded.clear()
      if (poseImage) poseImage.src = ''
      talk?.dispose()
      if (talkCanvas) { talkCanvas.width = 0; talkCanvas.height = 0 }
    },
  }
}
