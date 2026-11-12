import { anchorRect, blinkingAt, loadTalkingCutout, talkStateAt, type CutoutAnchor, type TalkingCutout } from './talkingCutout'
import { imageFootprint, type ImageFootprint } from './imageGrounding'
import { spriteFrame, type Drawn, type DirectionalSheet, type DirectionalSprite } from './directionalSprite'
import type { MediaScreen } from './mediaScreen'

/** Paints a directional 2D figure on the canvas of its image object (`screen.directional`, painted like `screen.talk` and
 * `screen.poseSequence`). The canvas is the plane `spriteFrame` describes: as wide as the widest cell, the boots on the
 * catalog's line, the figure `figure` of the height. Which cell and which way to mirror it is decided every frame from the
 * camera (`directionalView`, in the camera pass of `paintWorld`) and arrives as `screen.directional.view`; a change of drawing
 * arrives with the drawing it fades from, and the two are added up so the picture never dips. A sheet that has a mouth is lip-synced
 * with the kit's mouth drawings. The sprite is read from the screen being painted, so editing the heading or the walk repaints
 * without reloading the sheets. */
const FOOTPRINT_SIDE = 384
const TALK_SIDE = 1024

type Sized = { image: CanvasImageSource; width: number; height: number }
type Box = { x: number; y: number; width: number; height: number }
/** Everything a frame is drawn from, decoded once. */
type Art = {
  sheets: Map<string, HTMLImageElement>
  pose: HTMLImageElement | null
  footprint: ImageFootprint | null
  talk: Awaited<ReturnType<typeof loadTalkingCutout>> | null
  talkCanvas: HTMLCanvasElement | null
  mouths: Map<string, HTMLImageElement>
  blink: HTMLImageElement | null
  frame: { feet: number; figure: number }
}

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

/** A mouth or eye drawing at its anchor of the cell it is on (the pose convention: % of the longer edge of the cell). */
function overlay(context: CanvasRenderingContext2D, image: HTMLImageElement, anchor: CutoutAnchor, cell: Box) {
  const rect = anchorRect(anchor, cell.width, cell.height, image.naturalWidth / image.naturalHeight)
  context.save()
  context.translate(cell.x + rect.x + rect.width / 2, cell.y + rect.y + rect.height / 2)
  context.rotate(anchor.rotation * Math.PI / 180)
  context.drawImage(image, -rect.width / 2, -rect.height / 2, rect.width, rect.height)
  context.restore()
}

/** The mouth for the cue of the second, and the blink, on a sheet that says where they are. */
function paintFace(context: CanvasRenderingContext2D, art: Art, sheet: DirectionalSheet, cell: Box, talk: TalkingCutout, seconds: number) {
  const mouth = art.mouths.get(talkStateAt(talk, seconds))
  if (mouth && sheet.mouth) overlay(context, mouth, sheet.mouth, cell)
  if (art.blink && sheet.eyes && blinkingAt(talk.blinks, seconds)) overlay(context, art.blink, sheet.eyes, cell)
}

/** The cell `frame` of a sheet, scaled to the canvas height and centred, mirrored about the middle of the canvas. */
function drawSheet(context: CanvasRenderingContext2D, art: Art, sprite: DirectionalSprite, drawn: Extract<Drawn, { kind: 'sheet' }>, screen: MediaScreen | undefined, seconds: number) {
  const sheet = sprite.sheets[drawn.sheet]
  const image = sheet && art.sheets.get(sheet.source)
  if (!image) return
  const { width, height } = context.canvas
  const cellWidth = image.naturalWidth / sheet.columns, cellHeight = image.naturalHeight / sheet.rows
  const scale = height / cellHeight
  const cell = { x: (width - cellWidth * scale) / 2, y: 0, width: cellWidth * scale, height }
  context.save()
  if (drawn.mirror) { context.translate(width, 0); context.scale(-1, 1) }
  context.drawImage(image, (drawn.frame % sheet.columns) * cellWidth, Math.floor(drawn.frame / sheet.columns) * cellHeight, cellWidth, cellHeight, cell.x, cell.y, cell.width, cell.height)
  if (drawn.speaking && screen?.talk) paintFace(context, art, sheet, cell, screen.talk, seconds)
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

/** The pose, with its mouth when the figure speaks: the kit's talking cutout painted at the pose's own size. */
function paintPose(context: CanvasRenderingContext2D, art: Art, talking: boolean, screen: MediaScreen | undefined, seconds: number) {
  const { pose, talkCanvas } = art
  if (!pose) return
  if (talking && art.talk && talkCanvas) {
    art.talk.paint(talkCanvas.getContext('2d')!, screen, seconds)
    drawPose(context, { image: talkCanvas, width: talkCanvas.width, height: talkCanvas.height }, art.footprint, art.frame)
  } else drawPose(context, { image: pose, width: pose.naturalWidth, height: pose.naturalHeight }, art.footprint, art.frame)
}

function drawLook(context: CanvasRenderingContext2D, art: Art, sprite: DirectionalSprite, drawn: Drawn | undefined, screen: MediaScreen | undefined, seconds: number) {
  if (drawn?.kind === 'sheet') drawSheet(context, art, sprite, drawn, screen, seconds)
  else paintPose(context, art, drawn?.talking ?? false, screen, seconds)
}

async function loadArt(screen: MediaScreen, sprite: DirectionalSprite, signal: AbortSignal): Promise<Art> {
  const sources = [...new Set(sprite.sheets.map(sheet => sheet.source))]
  const sheets = new Map(await Promise.all(sources.map(async source => [source, await decode(source, signal)] as const)))
  const pose = screen.sourceUrl ? await decode(screen.sourceUrl, signal).catch(() => null) : null
  const talk = screen.talk && pose ? await loadTalkingCutout(screen.talk, signal) : null
  let talkCanvas: HTMLCanvasElement | null = null
  if (talk && pose) {
    const ratio = Math.min(1, TALK_SIDE / Math.max(pose.naturalWidth, pose.naturalHeight))
    talkCanvas = document.createElement('canvas')
    talkCanvas.width = Math.max(1, Math.round(pose.naturalWidth * ratio)); talkCanvas.height = Math.max(1, Math.round(pose.naturalHeight * ratio))
  }
  const lipSync = Boolean(screen.talk && sprite.sheets.some(sheet => sheet.mouth || sheet.eyes))
  const mouths = new Map(lipSync ? await Promise.all(Object.entries(screen.talk!.mouths).map(async ([state, url]) => [state, await decode(url, signal)] as const)) : [])
  const blink = lipSync && screen.talk!.blink ? await decode(screen.talk!.blink.source, signal) : null
  const { feet, figure } = spriteFrame(sprite)
  return { sheets, pose, footprint: pose ? poseFootprint(pose) : null, talk, talkCanvas, mouths, blink, frame: { feet, figure } }
}

function release(art: Art) {
  for (const image of [...art.sheets.values(), ...art.mouths.values(), ...(art.pose ? [art.pose] : []), ...(art.blink ? [art.blink] : [])]) image.src = ''
  art.sheets.clear(); art.mouths.clear()
  art.talk?.dispose()
  if (art.talkCanvas) { art.talkCanvas.width = 0; art.talkCanvas.height = 0 }
}

export async function loadDirectionalSprite(screen: MediaScreen, signal: AbortSignal) {
  const sprite = screen.directional as DirectionalSprite
  const art = await loadArt(screen, sprite, signal)
  return {
    paint(context: CanvasRenderingContext2D, current: MediaScreen | undefined, seconds: number) {
      const live = current?.directional ?? sprite
      const view = live.view
      context.clearRect(0, 0, context.canvas.width, context.canvas.height)
      context.imageSmoothingQuality = 'high'
      if (!view?.blend) { drawLook(context, art, live, view, current, seconds); return }
      // A true crossfade: the old drawing at 1 - mix and the new one added at mix, so the sum is never thinner than either.
      context.globalAlpha = 1 - view.blend.mix
      drawLook(context, art, live, view.blend.from, current, seconds)
      context.globalCompositeOperation = 'lighter'
      context.globalAlpha = view.blend.mix
      drawLook(context, art, live, view, current, seconds)
      context.globalCompositeOperation = 'source-over'
      context.globalAlpha = 1
    },
    dispose() { release(art) },
  }
}
