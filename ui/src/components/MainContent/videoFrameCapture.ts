/** A grabbed video frame that is still empty. Chromium can report `seeked` before the picture exists. */

export function pixelsLookBlank(data: Uint8ClampedArray): boolean {
  if (data.length < 4) return true
  for (let index = 0; index < data.length; index += 4) {
    if (data[index] > 12 || data[index + 1] > 12 || data[index + 2] > 12) return false
  }
  return true
}

export async function captureShownFrame(video: HTMLVideoElement): Promise<Blob> {
  const canvas = document.createElement('canvas')
  canvas.width = video.videoWidth
  canvas.height = video.videoHeight
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('canvas unavailable')
  ctx.drawImage(video, 0, 0)
  for (let attempt = 0; attempt < 4 && sampledFrameIsBlank(ctx, canvas.width, canvas.height); attempt += 1) {
    await new Promise<void>(resolve => requestAnimationFrame(() => resolve()))
    ctx.drawImage(video, 0, 0)
  }
  return await new Promise((resolve, reject) => {
    canvas.toBlob(blob => (blob ? resolve(blob) : reject(new Error('frame capture failed'))), 'image/png')
  })
}

function sampledFrameIsBlank(ctx: CanvasRenderingContext2D, width: number, height: number): boolean {
  try {
    const sample = ctx.getImageData(0, 0, Math.min(width, 24), Math.min(height, 24)).data
    return pixelsLookBlank(sample)
  } catch {
    // A tainted canvas cannot be read. Keep the frame that was drawn.
    return false
  }
}
