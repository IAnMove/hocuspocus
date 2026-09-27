import { fitFile } from './imageFit'
import { uploadImage } from '../api/generation'
import { getOutputThumbnailUrl, type ApiOutput } from '../api/outputs'
import { randomUuid } from './uuid'

export type CropRect = { x: number; y: number; width: number; height: number }
const bounded = (value: number, min: number, max: number) => Math.min(max, Math.max(min, Math.round(Number.isFinite(value) ? value : min)))

/** All coordinates are original, EXIF-oriented pixels, never preview pixels. */
export function clampCrop(rect: CropRect, width: number, height: number): CropRect {
  const x = bounded(rect.x, 0, width - 1), y = bounded(rect.y, 0, height - 1)
  return { x, y, width: bounded(rect.width, 1, width - x), height: bounded(rect.height, 1, height - y) }
}

export function cropFromPoints(a: { x: number; y: number }, b: { x: number; y: number }, width: number, height: number): CropRect {
  const ax = bounded(a.x, 0, width), ay = bounded(a.y, 0, height)
  const bx = bounded(b.x, 0, width), by = bounded(b.y, 0, height)
  return clampCrop({ x: Math.min(ax, bx), y: Math.min(ay, by), width: Math.abs(ax - bx), height: Math.abs(ay - by) }, width, height)
}

export async function cropImageFile(image: HTMLImageElement, rect: CropRect, name: string): Promise<File> {
  const crop = clampCrop(rect, image.naturalWidth, image.naturalHeight)
  const canvas = document.createElement('canvas')
  canvas.width = crop.width; canvas.height = crop.height
  const context = canvas.getContext('2d')
  if (!context) throw new Error('Canvas is unavailable')
  context.drawImage(image, crop.x, crop.y, crop.width, crop.height, 0, 0, crop.width, crop.height)
  // Unique name even for repeated identical crops. Never write back to the source.
  const stem = name.replace(/\.[^.]+$/, '').replace(/[^\p{L}\p{N}_-]/gu, '-').slice(0, 80) || 'image'
  return fitFile(canvas, `${stem}-crop-${randomUuid()}.png`)
}

export async function saveCroppedImage(file: File): Promise<ApiOutput> {
  const uploaded = await uploadImage(file)
  return { name: uploaded.filename, type: 'image', mode: null, size: file.size,
    created_at: Date.now() / 1000, url: uploaded.url, path: uploaded.path,
    workspace_id: '__uploads__', thumbnail_url: `${getOutputThumbnailUrl(uploaded.filename, '__uploads__')}&size=sm` }
}
