const PIXEL = /^([1-9][0-9]{1,4})x([1-9][0-9]{1,4})$/

function snap(value: number, max = 4096): number {
  return Math.min(max, Math.max(64, Math.round(value / 8) * 8))
}

export function isPixelResolution(value: string): boolean {
  const match = PIXEL.exec(value)
  if (!match) return false
  const width = Number(match[1])
  const height = Number(match[2])
  return width >= 64 && width <= 4096 && height >= 64 && height <= 4096
    && width % 8 === 0 && height % 8 === 0
}

export function snapImageResolution(width: number, height: number, maxEdge = 2048): string {
  const scale = Math.min(1, maxEdge / Math.max(width, height, 1))
  return `${snap(width * scale)}x${snap(height * scale)}`
}

/** Image commands reject `auto` / `auto_720p`. Turn those labels into a canvas. */
export function concreteImageResolution(resolution: unknown, modelType?: unknown): string {
  const raw = String(resolution || '').trim()
  const match = PIXEL.exec(raw)
  if (match) return `${snap(Number(match[1]))}x${snap(Number(match[2]))}`
  const qwen21 = String(modelType || '').startsWith('qwen_image_21')
  const mapped: Record<string, string> = {
    auto: qwen21 ? '2048x2048' : '1024x1024',
    auto_480p: '848x480',
    auto_540p: '960x544',
    auto_720p: qwen21 ? '1024x1024' : '1280x720',
    auto_768p: '1344x768',
    auto_1080p: qwen21 ? '2048x2048' : '1920x1088',
  }
  return mapped[raw] || (qwen21 ? '2048x2048' : '1024x1024')
}
