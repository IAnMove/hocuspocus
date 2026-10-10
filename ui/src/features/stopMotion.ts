/** Stop-motion holds. ``t' = floor(t·fps/N)·N/fps``: the picture changes every N frames and the audio is not read here. */

export type MotionStep = 2 | 3 | 4

export function motionStepOf(value: unknown): MotionStep | null {
  return value === 2 || value === 3 || value === 4 ? value : null
}

/** 0 when absent or not a positive finite number. A set value stays within 0–2 px. */
export function stopMotionJitterOf(value: unknown): number {
  if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0) return 0
  return Math.min(2, value)
}

/** Valid hold fields only. An absent or rejected value is left out, so a plain scene stays unchanged. */
export function holdFields(step: unknown, jitter: unknown): { motionStep?: MotionStep; stopMotionJitter?: number } {
  const motionStep = motionStepOf(step)
  const stopMotionJitter = stopMotionJitterOf(jitter)
  return { ...(motionStep ? { motionStep } : {}), ...(stopMotionJitter ? { stopMotionJitter } : {}) }
}

/** The scene time a frame paints. No step leaves ``seconds`` as it arrived. */
export function heldFrameTime(seconds: number, fps: number, step: MotionStep | null): number {
  if (!step || !(fps > 0) || !(seconds > 0)) return seconds > 0 ? seconds : 0
  const frame = Math.round(seconds * fps)
  return (frame - (frame % step)) / fps
}

/** Which hold ``seconds`` belongs to. Frames in one hold share a jitter. */
export function holdBlock(seconds: number, fps: number, step: MotionStep): number {
  if (!(fps > 0)) return 0
  return Math.floor(Math.round(Math.max(0, seconds) * fps) / step)
}

/** Deterministic pixel offset of one hold, inside ±jitter. The same block always returns the same point. */
export function stopMotionOffset(block: number, jitter: number): { x: number; y: number } {
  if (!(jitter > 0)) return { x: 0, y: 0 }
  const hash = Math.imul(block + 1, 0x45d9f3b) >>> 0
  const along = (hash % 5) / 4 * 2 - 1
  const across = ((hash >>> 8) % 5) / 4 * 2 - 1
  return { x: Math.round(along * jitter), y: Math.round(across * jitter) }
}

/** Slide a finished frame by a hold's offset. A zero offset does not read the pixels back. */
export function shiftHeldFrame(
  ctx: CanvasRenderingContext2D,
  width: number,
  height: number,
  offset: { x: number; y: number },
) {
  if (!offset.x && !offset.y) return
  if (typeof ctx.getImageData !== 'function' || typeof ctx.putImageData !== 'function') return
  const image = ctx.getImageData(0, 0, width, height)
  ctx.fillStyle = '#000000'
  ctx.fillRect(0, 0, width, height)
  ctx.putImageData(image, offset.x, offset.y)
}
