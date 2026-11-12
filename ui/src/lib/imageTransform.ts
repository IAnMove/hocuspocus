import type { CropRect } from './imageCrop'

/** The four basic changes of the image editor: a quarter turn either way and a mirror either way. */
export type ImageTransform = 'rotateLeft' | 'rotateRight' | 'flipHorizontal' | 'flipVertical'

export const IMAGE_TRANSFORMS: readonly ImageTransform[] = ['rotateLeft', 'rotateRight', 'flipHorizontal', 'flipVertical']

const quarterTurn = (op: ImageTransform) => op === 'rotateLeft' || op === 'rotateRight'

/** A quarter turn swaps width and height; a mirror keeps them. */
export function transformedSize(width: number, height: number, op: ImageTransform): { width: number; height: number } {
  return quarterTurn(op) ? { width: height, height: width } : { width, height }
}

/** The same area of the picture, in the pixel coordinates the picture has after the change. */
export function transformRect(rect: CropRect, width: number, height: number, op: ImageTransform): CropRect {
  switch (op) {
    case 'rotateRight': return { x: height - rect.y - rect.height, y: rect.x, width: rect.height, height: rect.width }
    case 'rotateLeft': return { x: rect.y, y: width - rect.x - rect.width, width: rect.height, height: rect.width }
    case 'flipHorizontal': return { ...rect, x: width - rect.x - rect.width }
    case 'flipVertical': return { ...rect, y: height - rect.y - rect.height }
  }
}

/** Paint the image changed by ``op`` on a new canvas of its new size. Pixels are moved, never resampled. */
export function transformImage(image: HTMLImageElement, op: ImageTransform): HTMLCanvasElement {
  const width = image.naturalWidth, height = image.naturalHeight
  const size = transformedSize(width, height, op)
  const canvas = document.createElement('canvas')
  canvas.width = size.width; canvas.height = size.height
  const context = canvas.getContext('2d')
  if (!context) throw new Error('Canvas is unavailable')
  if (op === 'rotateRight') { context.translate(height, 0); context.rotate(Math.PI / 2) }
  else if (op === 'rotateLeft') { context.translate(0, width); context.rotate(-Math.PI / 2) }
  else if (op === 'flipHorizontal') { context.translate(width, 0); context.scale(-1, 1) }
  else { context.translate(0, height); context.scale(1, -1) }
  context.drawImage(image, 0, 0)
  return canvas
}

/** A temporary address for the changed picture. The caller revokes it when the picture is replaced or closed. */
export function canvasObjectUrl(canvas: HTMLCanvasElement): Promise<string> {
  return new Promise((resolve, reject) => {
    canvas.toBlob(blob => blob ? resolve(URL.createObjectURL(blob)) : reject(new Error('Cannot export the changed image')), 'image/png')
  })
}
