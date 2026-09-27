/** Optional source interval and continuous scene clock for long layered shots. */
export type MediaLoop = { loopRange?: [number, number]; pingPong?: boolean; timeOffset?: number }

export function parseMediaLoop(value: MediaLoop): MediaLoop {
  const range = value.loopRange
  return {
    ...(Array.isArray(range) && range.length === 2 && range.every(v => typeof v === 'number' && Number.isFinite(v))
      && range[0] >= 0 && range[1] > range[0] && range[1] <= 86400 ? { loopRange: [...range] as [number, number] } : {}),
    ...(value.pingPong === true ? { pingPong: true } : {}),
    ...(typeof value.timeOffset === 'number' && Number.isFinite(value.timeOffset) && value.timeOffset > 0
      ? { timeOffset: Math.min(86400, value.timeOffset) } : {}),
  }
}

export function loopedMediaTime(time: number, duration: number, loop: MediaLoop) {
  const upper = Math.max(0, duration - .001)
  const lower = Math.min(upper, loop.loopRange?.[0] ?? 0)
  const end = Math.max(lower, Math.min(upper, loop.loopRange?.[1] ?? upper))
  const span = end - lower
  if (!span) return lower
  const phase = Math.max(0, time - lower) % (span * (loop.pingPong ? 2 : 1))
  return lower + (loop.pingPong && phase > span ? 2 * span - phase : phase)
}
