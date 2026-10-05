import { CanvasTexture, SRGBColorSpace, type Texture } from 'three'
import { paintSceneFx } from '../sceneFx/paint'
import type { ScreenBackdrop } from './screenBackdrop'

const LONG_SIDE = 1920

type Plate = { width?: number; height?: number; videoWidth?: number; videoHeight?: number }

/** Scale the plate to cover the frame, as the cinematic background does. */
function drawCover(ctx: CanvasRenderingContext2D, image: CanvasImageSource & Plate, width: number, height: number) {
  const w = image.videoWidth || image.width || 0, h = image.videoHeight || image.height || 0
  if (!w || !h) return
  const scale = Math.max(width / w, height / h)
  ctx.drawImage(image, (width - w * scale) / 2, (height - h * scale) / 2, w * scale, h * scale)
}

/** Repainted every frame from the scene clock: scrubbing and export draw the same backdrop. */
export class ScreenBackdropPainter {
  private canvas?: HTMLCanvasElement
  private texture?: CanvasTexture

  paint(backdrop: ScreenBackdrop, seconds: number, frameWidth: number, frameHeight: number, plate?: Texture): Texture | null {
    if (typeof document === 'undefined') return null
    const scale = Math.min(1, LONG_SIDE / Math.max(1, frameWidth, frameHeight))
    const width = Math.max(2, Math.round(frameWidth * scale)), height = Math.max(2, Math.round(frameHeight * scale))
    this.canvas ??= document.createElement('canvas')
    if (this.canvas.width !== width || this.canvas.height !== height) {
      this.canvas.width = width; this.canvas.height = height
      this.texture?.dispose(); this.texture = undefined
    }
    const ctx = this.canvas.getContext('2d')
    if (!ctx) return null
    ctx.globalCompositeOperation = 'source-over'; ctx.globalAlpha = 1
    ctx.fillStyle = backdrop.color; ctx.fillRect(0, 0, width, height)
    const image = plate?.image as (CanvasImageSource & Plate) | undefined
    if (image) drawCover(ctx, image, width, height)
    paintSceneFx(ctx, width, height, seconds, backdrop.sfx)
    if (!this.texture) {
      this.texture = new CanvasTexture(this.canvas)
      this.texture.colorSpace = SRGBColorSpace
    }
    this.texture.needsUpdate = true
    return this.texture
  }

  dispose() {
    this.texture?.dispose()
    this.texture = undefined
  }
}
