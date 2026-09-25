export type FitMode = 'contain' | 'cover' | 'stretch'

export function fitRectangle(sourceWidth: number, sourceHeight: number, width: number, height: number, mode: FitMode) {
  const scale = mode === 'cover'
    ? Math.max(width / sourceWidth, height / sourceHeight)
    : Math.min(width / sourceWidth, height / sourceHeight)
  const drawWidth = mode === 'stretch' ? width : sourceWidth * scale
  const drawHeight = mode === 'stretch' ? height : sourceHeight * scale
  return { x: (width - drawWidth) / 2, y: (height - drawHeight) / 2, width: drawWidth, height: drawHeight }
}

export function paintFit(image: HTMLImageElement, width: number, height: number, mode: FitMode, sourceSize = { width: image.width, height: image.height }, mask = false): HTMLCanvasElement {
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('Canvas is unavailable')
  // Source padding stays transparent. Mask padding is black (preserve).
  if (mask) {
    ctx.fillStyle = '#000'
    ctx.fillRect(0, 0, width, height)
  }
  const rect = fitRectangle(sourceSize.width, sourceSize.height, width, height, mode)
  ctx.drawImage(image, rect.x, rect.y, rect.width, rect.height)
  return canvas
}

export async function loadFitImage(src: string): Promise<HTMLImageElement> {
  const image = new Image()
  image.src = src
  await image.decode()
  return image
}

export function fitFile(canvas: HTMLCanvasElement, name: string): Promise<File> {
  return new Promise((resolve, reject) => {
    canvas.toBlob(blob => blob
      ? resolve(new File([blob], name, { type: 'image/png' }))
      : reject(new Error('Cannot export fitted image')), 'image/png')
  })
}
