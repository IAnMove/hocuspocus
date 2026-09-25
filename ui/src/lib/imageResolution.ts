const PIXEL = /^([1-9][0-9]{1,4})x([1-9][0-9]{1,4})$/

function snap(value: number, max = 4096, multiple = 8): number {
  return Math.min(max, Math.max(64, Math.round(value / multiple) * multiple))
}

export function isPixelResolution(value: string): boolean {
  const match = PIXEL.exec(value)
  if (!match) return false
  const width = Number(match[1])
  const height = Number(match[2])
  return width >= 64 && width <= 4096 && height >= 64 && height <= 4096
    && width % 8 === 0 && height % 8 === 0
}

export function snapImageResolution(width: number, height: number, maxEdge = 2048, modelType?: unknown): string {
  const scale = Math.min(1, maxEdge / Math.max(width, height, 1))
  return `${snap(width * scale, 4096, imageResolutionMultiple(modelType))}x${snap(height * scale, 4096, imageResolutionMultiple(modelType))}`
}

/** Image commands reject `auto` / `auto_720p`. Turn those labels into a canvas. */
export function concreteImageResolution(resolution: unknown, modelType?: unknown): string {
  const multiple = imageResolutionMultiple(modelType)
  const raw = String(resolution || '').trim()
  const match = PIXEL.exec(raw)
  if (match) return `${snap(Number(match[1]), 4096, multiple)}x${snap(Number(match[2]), 4096, multiple)}`
  const qwen21 = String(modelType || '').startsWith('qwen_image_21')
  const mapped: Record<string, string> = {
    auto: '1024x1024',
    auto_480p: '848x480',
    auto_540p: '960x544',
    auto_720p: qwen21 ? '1024x1024' : '1280x720',
    auto_768p: '1344x768',
    auto_1080p: qwen21 ? '2048x2048' : '1920x1088',
  }
  const value = mapped[raw] || '1024x1024'
  const [width, height] = value.split('x').map(Number)
  return `${snap(width, 4096, multiple)}x${snap(height, 4096, multiple)}`
}


export function imageResolutionMultiple(modelType?: unknown): number {
  return String(modelType || '').startsWith('qwen_image_21') ? 32 : 8
}

/** Preserve the source aspect at a selected pixel budget, on the model's grid. */
export function referenceImageResolution(width: number, height: number, preset: string, modelType?: unknown): string {
  const edge = preset === '1080p' ? 2048 : 1024
  const aspect = Math.max(1 / 8, Math.min(8, width / Math.max(1, height)))
  return snapImageResolution(edge * Math.sqrt(aspect), edge / Math.sqrt(aspect), 4096, modelType)
}
